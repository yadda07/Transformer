# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Recipe safety: pure persistence checks and native QGIS4 geometry contracts."""

import ast
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _pure_config_manager():
    """Execute the actual manager with only its QGIS logging boundary replaced."""
    tree = ast.parse((ROOT / "core/config_manager.py").read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("qgis"))
    )]
    class Log:
        @staticmethod
        def logMessage(*_args):
            pass
    namespace = {
        "QgsMessageLog": Log, "MsgInfo": 0, "MsgWarning": 1, "MsgCritical": 2,
        "is_filter_enabled": lambda config: bool(config and config.get("enabled") and config.get("expression", "").strip()),
        "get_filter_expression": lambda config: config.get("expression", "") if config else "",
    }
    exec(compile(tree, str(ROOT / "core/config_manager.py"), "exec"), namespace)
    return namespace["ConfigManager"]


def _pure_task():
    tree = ast.parse((ROOT / "core/transform_task.py").read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("qgis"))
    ) and not (isinstance(node, ast.ClassDef) and node.name == "DetachedLayerSource")]
    class Task:
        def __init__(self, *_args):
            self.cancelled = False
        def isCanceled(self):
            return self.cancelled
        def cancel(self):
            self.cancelled = True
        def setProgress(self, _value):
            pass
        def setDependentLayers(self, layers):
            self.dependencies = layers
    class Project:
        @classmethod
        def instance(cls):
            return cls()
        def transformContext(self):
            return object()
    class Scopes:
        @staticmethod
        def globalScope():
            return object()
        @staticmethod
        def projectScope(_project):
            return object()
    class Application:
        @classmethod
        def instance(cls):
            return cls()
        def thread(self):
            return "main-thread"
    class Snapshot:
        def __new__(cls, layer, _scopes):
            return layer
        @staticmethod
        def _detached_scope(scope):
            return scope
    namespace = {"QgsTask": Task, "QgsProject": Project, "QgsExpressionContextUtils": Scopes,
                 "QgsVectorLayer": object, "QgsCoordinateReferenceSystem": object, "TaskCanCancel": 1,
                 "QgsApplication": Application, "DetachedLayerSource": Snapshot}
    exec(compile(tree, str(ROOT / "core/transform_task.py"), "exec"), namespace)
    return namespace["TransformTask"]


class RecipePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = _pure_config_manager()(self.temp.name)

    def add_recipe(self, name="recipe", **kwargs):
        return self.manager.add_table_config(name, "Livraison", {"code": '"code"'}, **kwargs)

    def import_file(self, tables, **extra):
        path = Path(self.temp.name) / "incoming.json"
        path.write_text(json.dumps({"version": "1.2", "tables": tables, **extra}), encoding="utf-8")
        return str(path)

    def test_orphan_cleanup_never_deletes_saved_rules(self):
        self.add_recipe()
        self.manager.save_config()
        before = Path(self.manager.config_file).read_bytes()
        self.assertEqual(self.manager.cleanup_missing_sources(), 0)
        self.assertTrue(self.manager.has_table_config("recipe"))
        self.assertEqual(before, Path(self.manager.config_file).read_bytes())

    def test_layer_identity_does_not_match_a_homonym(self):
        self.add_recipe(source_id="layer-first")
        self.assertEqual(self.manager.get_tables_for_source("Livraison", source_id="layer-first"), ["recipe"])
        self.assertEqual(self.manager.get_tables_for_source("Livraison", source_id="layer-other"), [])

    def test_legacy_source_is_still_resolved(self):
        self.add_recipe()
        self.assertEqual(self.manager.get_tables_for_source("Livraison", source_id="new-layer-id"), ["recipe"])

    def test_getter_cannot_mutate_the_recipe(self):
        self.add_recipe()
        value = self.manager.get_table_config("recipe")
        value["calculated_fields"]["code"] = "'changed'"
        self.assertEqual(self.manager.get_table_config("recipe")["calculated_fields"]["code"], '"code"')

    def test_import_conflict_is_rejected_until_a_decision(self):
        self.add_recipe()
        self.manager.save_config()
        before = copy.deepcopy(self.manager.config_data)
        path = self.import_file({"recipe": {"source_file": "Other", "calculated_fields": {"x": "1"}}})
        self.assertEqual(self.manager.preview_import_config(path)["conflicts"], ["recipe"])
        self.assertFalse(self.manager.import_config(path))
        self.assertEqual(before, self.manager.config_data)

    def test_explicit_replacement_keeps_previous_revision(self):
        self.add_recipe()
        self.manager.save_config()
        path = self.import_file({"recipe": {"source_file": "Other", "calculated_fields": {"x": "1"}}})
        self.assertTrue(self.manager.import_config(path, conflict_policy="replace"))
        self.assertEqual(self.manager.get_table_config("recipe")["recipe_version"], 2)
        self.assertEqual(self.manager.config_data["recipe_history"]["recipe"][0]["calculated_fields"], {"code": '"code"'})

    def test_failed_import_keeps_the_active_catalogue(self):
        self.add_recipe()
        self.manager.save_config()
        before = copy.deepcopy(self.manager.config_data)
        path = self.import_file({"new": {"calculated_fields": {"x": "1"}}})
        with patch.object(self.manager, "save_config", return_value=False):
            self.assertFalse(self.manager.import_config(path))
        self.assertEqual(before, self.manager.config_data)

    def test_invalid_import_is_validated_before_any_mutation(self):
        path = self.import_file({"bad": {"calculated_fields": ["not", "a", "mapping"]}})
        before = copy.deepcopy(self.manager.config_data)
        self.assertFalse(self.manager.preview_import_config(path)["valid"])
        self.assertFalse(self.manager.import_config(path))
        self.assertEqual(before, self.manager.config_data)

    def test_failed_atomic_replace_preserves_disk_and_memory(self):
        self.add_recipe()
        self.manager.save_config()
        before = Path(self.manager.config_file).read_bytes()
        self.add_recipe(force_replace=True, target_crs="EPSG:2154")
        with patch("os.replace", side_effect=OSError("read-only destination")):
            self.assertFalse(self.manager.save_config())
        self.assertEqual(before, Path(self.manager.config_file).read_bytes())
        self.assertIsNone(self.manager.get_table_config("recipe")["target_crs"])
        self.assertFalse(list(Path(self.temp.name).glob("*.tmp")))

    def test_version_and_schema_survive_a_reload(self):
        definition = {"code": {"type": "Integer64", "description": "Identifiant", "length": 0, "precision": 0}}
        self.add_recipe(field_definitions=definition, source_id="stable", destination={})
        self.manager.save_config()
        self.add_recipe(force_replace=True, field_definitions=definition, source_id="stable", target_crs="EPSG:2154")
        self.manager.save_config()
        restored = _pure_config_manager()(self.temp.name).get_table_config("recipe")
        self.assertEqual(restored["recipe_version"], 2)
        self.assertEqual(restored["field_definitions"], definition)
        self.assertEqual(restored["destination"], {})

    def test_invalid_destination_is_rejected_before_catalogue_mutation(self):
        invalid = ["file", [], 5, None, {"kind": "unknown"}, {"kind": []},
                   {"kind": "file", "path": 5, "format": "GeoJSON", "encoding": "utf-8"},
                   {"kind": "file", "path": "out.json", "format": "GeoJSON", "encoding": "utf-8", "replay": 1},
                   {"kind": "postgresql", "targets": "public.table"},
                   {"kind": "postgresql", "targets": [{"schema": "public", "table": 7}]},
                   {"kind": "postgresql", "targets": [{"schema": "public", "table": "out", "layer": []}]}]
        for destination in invalid:
            with self.subTest(destination=destination):
                path = self.import_file({"bad": {"calculated_fields": {"code": '"code"'}, "destination": destination}})
                before = copy.deepcopy(self.manager.config_data)
                self.assertFalse(self.manager.preview_import_config(path)["valid"])
                self.assertFalse(self.manager.import_config(path))
                self.assertEqual(before, self.manager.config_data)

    def test_valid_file_and_postgresql_destinations_are_preserved(self):
        destinations = [
            {"kind": "file", "path": "out.gpkg", "format": "GeoPackage", "encoding": "utf-8", "selected_only": False, "replay": True},
            {"kind": "postgresql", "targets": [{"schema": "public", "table": "delivery", "layer": "source"}], "replay": False},
        ]
        for index, destination in enumerate(destinations):
            with self.subTest(destination=destination):
                self.assertTrue(self.add_recipe(f"out_{index}", destination=destination)["success"])
                self.assertEqual(self.manager.get_table_config(f"out_{index}")["destination"], destination)

    def test_secret_metadata_is_rejected_but_column_names_are_allowed(self):
        for key in ("password", "secret", "token", "PASSWORD", "access_token"):
            with self.subTest(key=key):
                path = self.import_file({"unsafe": {"calculated_fields": {"code": '"code"'}, "destination": {"kind": "postgresql", "targets": [{"schema": "public", "table": "out", key: "do-not-share"}]}}})
                self.assertFalse(self.manager.preview_import_config(path)["valid"])
                self.assertFalse(self.manager.import_config(path))
        result = self.manager.add_table_config("safe", "source", {"token": '"token"'}, field_definitions={"token": {"type": "Text"}})
        self.assertTrue(result["success"])

    def test_new_attribute_geometry_name_is_rejected_without_deleting_a_rule(self):
        self.add_recipe()
        before = copy.deepcopy(self.manager.config_data)
        for name in ("geometry", "Geometry", "GEOMETRY"):
            with self.subTest(name=name):
                result = self.manager.add_table_config("reserved", "source", {name: '"wkt"'})
                self.assertFalse(result["success"])
                self.assertIn("Renommez", result["message"])
                self.assertEqual(before, self.manager.config_data)

    def test_legacy_geometry_aliases_become_explicit_geometry_only(self):
        for expression, geometry_expression in (("$geometry", None), ("centroid($geometry)", "centroid($geometry)")):
            with self.subTest(expression=expression):
                cfg = {"calculated_fields": {"code": '"code"', "geometry": expression}, "geometry_expression": geometry_expression}
                path = self.import_file({"legacy": cfg}, version="1.1")
                self.assertTrue(self.manager.preview_import_config(path)["valid"])
                self.assertTrue(self.manager.import_config(path, conflict_policy="replace"))
                recipe = self.manager.get_table_config("legacy")
                self.assertEqual(recipe["calculated_fields"], {"code": '"code"'})
                self.assertEqual(recipe["geometry_expression"], expression)

    def test_legacy_geometry_attribute_is_kept_on_load_and_flagged_for_rename(self):
        cfg = {"version": "1.1", "tables": {"legacy": {"calculated_fields": {"geometry": '"wkt"', "code": '"code"'}}}}
        path = Path(self.manager.config_file)
        path.write_text(json.dumps(cfg), encoding="utf-8")
        before = path.read_bytes()
        loaded = _pure_config_manager()(self.temp.name)
        self.assertEqual(loaded.get_table_config("legacy")["calculated_fields"]["geometry"], '"wkt"')
        self.assertTrue(loaded.validation_warnings)
        self.assertEqual(before, path.read_bytes())
        self.assertFalse(self.manager.preview_import_config(str(path))["valid"])

    def test_current_geometry_alias_is_not_silently_migrated(self):
        path = self.import_file({"current": {"calculated_fields": {"code": '"code"', "geometry": "$geometry"}}})
        self.assertFalse(self.manager.preview_import_config(path)["valid"])
        self.assertFalse(self.manager.import_config(path))


class RecipeTaskContractTests(unittest.TestCase):
    class Layer:
        def id(self):
            return "source-id"
        def parent(self):
            return None
        def moveToThread(self, thread):
            self._thread = thread
        def thread(self):
            return self._thread

    class Engine:
        def __init__(self, cancel=False):
            self.calls = []
            self.cancel = cancel
            self.result_summaries = []
        def transform_qgis_layer_to_memory_layers(self, _layer, name, _crs, table_filter=None):
            self.calls.append((name, table_filter))
            self.result_summaries = [{"recipe": (table_filter or ["all"])[0], "status": "success", "produced_count": 1}]
            if self.cancel:
                self._current_task.cancel()
            return [RecipeTaskContractTests.Layer()]

    def test_task_obeys_each_items_recipe_names_and_deduplicates(self):
        engine = self.Engine()
        items = [{"filename": "source-id", "shapefile_info": {"layer": self.Layer()}, "table_names": names}
                 for names in (["A"], ["A", "B"], ["B"])]
        task = _pure_task()(engine, items)
        self.assertTrue(task.run())
        self.assertEqual(engine.calls, [("source-id", ["A"]), ("source-id", ["B"])])
        self.assertEqual(len(task.created_layers), 2)

    def test_cancelled_task_discards_even_a_returned_layer(self):
        engine = self.Engine(cancel=True)
        task = _pure_task()(engine, [{"filename": "source-id", "shapefile_info": {"layer": self.Layer()}, "table_names": ["A"]}])
        self.assertFalse(task.run())
        self.assertEqual(task.created_layers, [])
        self.assertEqual(task.success_count, 0)
        self.assertEqual(task.result_summary["status"], "cancelled")


try:
    from qgis.core import QgsApplication, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem
    NATIVE = QgsApplication.instance() is not None
except ImportError:
    NATIVE = False


@unittest.skipUnless(NATIVE, "Requires the isolated QGIS4 runtime with an application instance")
class RecipeGeometryTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT.parent))
        self.addCleanup(lambda: sys.path.remove(str(ROOT.parent)))
        self.module = importlib.import_module(f"{ROOT.name}.core.transformer")
        manager_module = importlib.import_module(f"{ROOT.name}.core.config_manager")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = manager_module.ConfigManager(self.temp.name)
        self.engine = self.module.SimpleTransformer(self.manager)
        self.layer = QgsVectorLayer("Point?crs=EPSG:4326&field=code:integer", "Livraison", "memory")
        feature = QgsFeature(self.layer.fields())
        feature.setAttributes([7])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 48)))
        self.assertTrue(self.layer.dataProvider().addFeatures([feature])[0])

    def test_active_empty_or_invalid_filter_never_falls_back_to_all(self):
        for expression in ("", '"code" =', '"missing" > 0'):
            result = self.engine.create_memory_layer_from_qgis_layer(self.layer, "out", {"code": '"code"'}, {"enabled": True, "expression": expression})
            self.assertIsNone(result)
            self.assertEqual(self.engine.last_result_summary["status"], "failed")

    def test_geometry_expression_runs_before_reprojection(self):
        crs = QgsCoordinateReferenceSystem("EPSG:3857")
        output = self.engine.create_memory_layer_from_qgis_layer(self.layer, "out", {"code": '"code"'}, target_crs=crs, geometry_expression="centroid($geometry)")
        self.assertIsNotNone(output, self.engine.last_result_summary)
        point = next(output.getFeatures()).geometry().asPoint()
        self.assertGreater(point.x(), 200000)
        self.assertGreater(point.y(), 6000000)
        self.assertEqual(output.crs().authid(), "EPSG:3857")
        self.assertEqual(next(self.layer.getFeatures()).geometry().asPoint().x(), 2)

    def test_each_recipe_uses_its_own_crs_and_exact_selection(self):
        for name, crs in (("mercator", "EPSG:3857"), ("original", None)):
            self.manager.add_table_config(name, self.layer.name(), {"code": '"code"'}, target_crs=crs, source_id=self.layer.id())
        outputs = self.engine.transform_qgis_layer_to_memory_layers(self.layer, self.layer.id(), table_filter=["original"])
        self.assertEqual([layer.name() for layer in outputs], ["original"])
        self.assertEqual(outputs[0].crs().authid(), "EPSG:4326")

    def test_expression_error_rejects_the_recipe_instead_of_null_success(self):
        result = self.engine.create_memory_layer_from_qgis_layer(self.layer, "bad", {"bad": 'to_int(\'bad value\')'})
        self.assertIsNone(result)
        self.assertEqual(self.engine.last_result_summary["produced_count"], 0)

    def test_typed_date_and_integer64_are_preserved(self):
        definitions = {"large": {"type": "Integer64"}, "day": {"type": "Date"}}
        output = self.engine.create_memory_layer_from_qgis_layer(self.layer, "typed", {"large": "5000000000", "day": "to_date('2026-10-24')"}, field_definitions=definitions)
        self.assertIsNotNone(output, self.engine.last_result_summary)
        from qgis.PyQt.QtCore import QMetaType
        self.assertEqual(output.fields().field("large").type(), QMetaType.Type.LongLong)
        self.assertEqual(output.fields().field("day").type(), QMetaType.Type.QDate)
        self.assertEqual(next(output.getFeatures())["large"], 5000000000)

    def test_declared_integer_refuses_fraction_instead_of_truncating(self):
        result = self.engine.create_memory_layer_from_qgis_layer(
            self.layer, "strict_integer", {"fraction": "1.5"},
            field_definitions={"fraction": {"type": "Integer"}},
        )
        self.assertIsNone(result)
        self.assertEqual(self.engine.last_result_summary["status"], "failed")
        self.assertIn("tronquée", self.engine.last_result_summary["errors"][0])

    def test_cancellation_does_not_return_a_partial_output(self):
        class Cancelled:
            @staticmethod
            def isCanceled():
                return True
        self.engine._current_task = Cancelled()
        self.assertIsNone(self.engine.create_memory_layer_from_qgis_layer(self.layer, "cancel", {"code": '"code"'}))
        self.assertEqual(self.engine.last_result_summary["status"], "cancelled")

    def test_background_worker_rejects_live_project_expression(self):
        task_module = importlib.import_module(f"{ROOT.name}.core.transform_task")
        self.manager.add_table_config("unsafe", self.layer.name(), {"lookup": "get_feature('other', 'code', 7)"}, source_id=self.layer.id())
        task = task_module.TransformTask(self.engine, [{"filename": self.layer.id(), "shapefile_info": {"layer": self.layer}, "table_names": ["unsafe"]}])
        self.assertFalse(task.run())
        self.assertEqual(task.created_layers, [])
        self.assertEqual(task.result_summary["status"], "failed")
        message = " ".join(task.result_summary["errors"])
        self.assertIn("lookup", message)
        self.assertIn("get_feature", message)

    def test_task_manager_uses_snapshot_and_publishes_on_main_thread(self):
        from qgis.core import QgsProject, QgsExpressionContextUtils
        from qgis.PyQt.QtCore import QThread, QObject, QEventLoop, QTimer
        task_module = importlib.import_module(f"{ROOT.name}.core.transform_task")
        main_thread = QgsApplication.instance().thread()
        QgsExpressionContextUtils.setLayerVariable(self.layer, "delivery_tag", "snapshot-value")
        self.manager.add_table_config("threaded", self.layer.name(), {"code": '"code" + 1', "tag": "@delivery_tag"},
                                      target_crs="EPSG:3857", source_id=self.layer.id())
        observed = {}
        loop = QEventLoop()

        class ObservedTask(task_module.TransformTask):
            def run(task_self):
                observed["worker_thread"] = QThread.currentThread()
                source = task_self.items[0]["shapefile_info"]["layer"]
                observed["source_is_qobject"] = isinstance(source, QObject)
                observed["source_id"] = source.id()
                result = super().run()
                observed["output_threads"] = [layer.thread() for layer in task_self.created_layers]
                return result
            def finished(task_self, result):
                observed["finished_thread"] = QThread.currentThread()
                super().finished(result)
                observed["summary"] = copy.deepcopy(task_self.result_summary)
                observed["layers"] = list(task_self.created_layers)
                observed["done"] = True
                loop.quit()

        task = ObservedTask(self.engine, [{"filename": self.layer.id(), "shapefile_info": {"layer": self.layer}, "table_names": ["threaded"]}])
        self.assertEqual([layer.id() for layer in task.dependentLayers()], [self.layer.id()])
        self.assertIsNot(task.items[0]["shapefile_info"]["layer"], self.layer)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(12000)
        QgsApplication.taskManager().addTask(task)
        loop.exec()
        timeout.stop()
        if not observed.get("done"):
            task.cancel()
        self.assertTrue(observed.get("done"), "La tâche native n'a pas terminé dans le délai de réception.")
        self.assertNotEqual(observed["worker_thread"], main_thread)
        self.assertEqual(observed["finished_thread"], main_thread)
        self.assertFalse(observed["source_is_qobject"])
        self.assertEqual(observed["source_id"], self.layer.id())
        self.assertEqual(observed["output_threads"], [main_thread])
        self.assertEqual(observed["summary"]["status"], "success", observed["summary"])
        self.assertEqual(len(observed["layers"]), 1)
        layer = observed["layers"][0]
        self.addCleanup(lambda: QgsProject.instance().removeMapLayer(layer.id()))
        self.assertIs(QgsProject.instance().mapLayer(layer.id()), layer)
        feature = next(layer.getFeatures())
        self.assertEqual(feature["code"], 8)
        self.assertEqual(feature["tag"], "snapshot-value")
        self.assertEqual(layer.crs().authid(), "EPSG:3857")
        self.assertTrue(observed["summary"]["recipes"][0]["published"])


if __name__ == "__main__":
    unittest.main()
