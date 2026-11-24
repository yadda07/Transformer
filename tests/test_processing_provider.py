# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""End-to-end and adverse tests for Transformer QGIS Processing provider & Python API."""

import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

try:
    from qgis.PyQt.QtCore import QMetaType
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProcessing,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingFeedback,
        QgsProcessingModelAlgorithm,
        QgsProcessingModelChildAlgorithm,
        QgsProcessingModelChildParameterSource,
        QgsProcessingModelOutput,
        QgsProcessingModelParameter,
        QgsProcessingParameterVectorLayer,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    NATIVE = QgsApplication.instance() is not None
except ImportError:
    NATIVE = False


def _ensure_processing_initialized():
    """Initialize QGIS Processing framework inside the isolated QGIS 4 runner."""
    qgis_prefix = QgsApplication.prefixPath()
    candidates = [
        Path(qgis_prefix) / "python" / "plugins",
        Path(r"C:\Program Files\QGIS 4.2.1\apps\qgis\python\plugins"),
    ]
    for path in candidates:
        if path.is_dir() and str(path) not in sys.path:
            sys.path.append(str(path))
    import processing as qgis_processing
    from processing.core.Processing import Processing
    if not QgsApplication.processingRegistry().providers():
        Processing.initialize()
    return qgis_processing


class _FakePgCursor:
    """In-memory transactional SQL cursor double matching PgExportTask contracts."""

    def __init__(self, state):
        self._state = state
        self._result = []
        self.rowcount = 0
        self.closed = False

    def execute(self, query, params=None):
        sql_text = str(query)
        upper = sql_text.upper()
        if "INFORMATION_SCHEMA.TABLES" in upper:
            key = (params[0], params[1])
            self._result = [(1 if key in self._state["pending_tables"] else 0,)]
        elif "INFORMATION_SCHEMA.COLUMNS" in upper:
            key = (params[0], params[1])
            cols = self._state["pending_tables"].get(key, {}).get("columns", [])
            self._result = list(cols)
        elif upper.startswith("CREATE TABLE"):
            table_key = self._state["create_key"]
            self._state["pending_tables"][table_key] = {
                "columns": list(self._state["created_columns"]),
                "rows": [],
            }
            self._state["executed"].append(sql_text)
        elif upper.startswith("CREATE INDEX"):
            self._state["executed"].append(sql_text)
        elif upper.startswith("DELETE FROM"):
            table_key = self._state["target_key"]
            self._state["pending_tables"][table_key]["rows"] = []
            self._state["executed"].append(sql_text)
        else:
            self._state["executed"].append(sql_text)

    def executemany(self, query, batch):
        sql_text = str(query)
        if self._state.get("fail_on_insert"):
            raise RuntimeError(
                f"simulated insert failure with secret {self._state.get('secret', '')}"
            )
        table_key = self._state["target_key"]
        self._state["pending_tables"][table_key]["rows"].extend(batch)
        self._state["executed"].append(sql_text)
        self.rowcount = len(batch)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        self.closed = True


class _FakePgConnection:
    def __init__(self, state):
        self._state = state
        self.closed = 0

    def cursor(self):
        return _FakePgCursor(self._state)

    def commit(self):
        self._state["committed_tables"] = {
            key: {"columns": list(val["columns"]), "rows": list(val["rows"])}
            for key, val in self._state["pending_tables"].items()
        }
        self._state["commits"] += 1

    def rollback(self):
        self._state["pending_tables"] = {
            key: {"columns": list(val["columns"]), "rows": list(val["rows"])}
            for key, val in self._state["committed_tables"].items()
        }
        self._state["rollbacks"] += 1

    def close(self):
        self.closed = 1


def _make_fake_psycopg2(state):
    class _SQL:
        def __init__(self, text):
            self.text = str(text)

        def format(self, *args, **kwargs):
            return _SQL(
                self.text.format(
                    *map(str, args),
                    **{k: str(v) for k, v in kwargs.items()},
                )
            )

        def join(self, items):
            return _SQL(self.text.join(map(str, items)))

        def __add__(self, other):
            return _SQL(self.text + str(other))

        def __str__(self):
            return self.text

    def connect(**kwargs):
        state["connect_kwargs"] = dict(kwargs)
        return _FakePgConnection(state)

    mod = types.SimpleNamespace(
        __name__="fake_psycopg2",
        connect=connect,
        sql=types.SimpleNamespace(
            SQL=_SQL,
            Identifier=lambda name: _SQL(f'"{name}"'),
            Placeholder=lambda: _SQL("%s"),
            Literal=lambda value: _SQL(str(value)),
        ),
    )
    return mod


@unittest.skipUnless(NATIVE, "Requires isolated QGIS 4 runtime")
class ProcessingProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(ROOT.parent) not in sys.path:
            sys.path.insert(0, str(ROOT.parent))
        cls.processing = _ensure_processing_initialized()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.tmp_dir = Path(self.temp.name)

        from Transfomer.main_plugin import TransformerPlugin
        self.plugin = TransformerPlugin(iface=None)
        self.plugin.plugin_dir = str(self.tmp_dir)
        self.plugin.initProcessing()
        self.addCleanup(self.plugin.unload)

    def _make_point_layer(self, name="source_pts", crs="EPSG:4326"):
        layer = QgsVectorLayer(
            f"Point?crs={crs}&field=code:integer&field=label:string&field=amount:double",
            name,
            "memory",
        )
        rows = [
            (1, "  alpha ", 10.5, 2.0, 48.0),
            (2, "beta", 20.0, 2.5, 48.5),
            (3, "gamma", 5.0, 3.0, 49.0),
        ]
        feats = []
        for code, label, amount, x, y in rows:
            feat = QgsFeature(layer.fields())
            feat.setAttributes([code, label, amount])
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            feats.append(feat)
        ok, _ = layer.dataProvider().addFeatures(feats)
        self.assertTrue(ok)
        return layer

    def _write_recipe_file(self, filename, tables, version="1.2"):
        path = self.tmp_dir / filename
        payload = {"version": version, "tables": tables}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    # ------------------------------------------------------------------
    # Couture 1: Plugin lifecycle & provider registration
    # ------------------------------------------------------------------

    def test_metadata_declares_processing_provider(self):
        metadata_text = (ROOT / "metadata.txt").read_text(encoding="utf-8")
        self.assertIn("hasProcessingProvider=yes", metadata_text)

    def test_headless_init_processing_registers_three_algorithms_and_unloads_cleanly(self):
        registry = QgsApplication.processingRegistry()
        provider = registry.providerById("transformer")
        self.assertIsNotNone(provider)
        alg_ids = sorted(alg.id() for alg in provider.algorithms())
        self.assertEqual(
            alg_ids,
            [
                "transformer:apply_recipe",
                "transformer:publish_postgresql",
                "transformer:transform_vector",
            ],
        )
        # Idempotent registration
        self.plugin.initProcessing()
        self.assertIs(registry.providerById("transformer"), provider)

        # Fresh createInstance & batch flag on each algorithm
        batch_flag = getattr(
            getattr(QgsProcessingAlgorithm, "Flag", QgsProcessingAlgorithm),
            "FlagSupportsBatch",
            0,
        )
        for alg_id in alg_ids:
            alg = registry.algorithmById(alg_id)
            self.assertIsNotNone(alg)
            self.assertIsNot(alg.createInstance(), alg)
            self.assertTrue(bool(alg.flags() & batch_flag))

        self.plugin.unload()
        self.assertIsNone(registry.providerById("transformer"))

    # ------------------------------------------------------------------
    # Couture 2: transformer:apply_recipe
    # ------------------------------------------------------------------

    def test_apply_recipe_portable_json_to_memory_and_geopackage(self):
        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "portable.json",
            {
                "bpe_clean": {
                    "source_file": "source_pts",
                    "recipe_version": 3,
                    "calculated_fields": {
                        "id_ext": '"code" * 1000000000',
                        "nom": 'upper(trim("label"))',
                        "jour": "to_date('2026-11-24')",
                    },
                    "field_definitions": {
                        "id_ext": {"type": "Integer64"},
                        "nom": {"type": "Text", "length": 40},
                        "jour": {"type": "Date"},
                    },
                    "filter": {"enabled": True, "expression": '"amount" >= 10'},
                    "geometry_expression": "centroid($geometry)",
                    "target_crs": "EPSG:3857",
                }
            },
        )

        # Memory sink (single recipe -> RECIPE_NAME optional)
        res_mem = self.processing.run(
            "transformer:apply_recipe",
            {
                "INPUT": layer,
                "RECIPE_FILE": recipe_path,
                "RECIPE_NAME": "",
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
        )
        out_layer = res_mem["OUTPUT"]
        self.assertEqual(res_mem["PRODUCED_COUNT"], 2)
        self.assertEqual(res_mem["FILTERED_OUT_COUNT"], 1)
        self.assertEqual(res_mem["RECIPE_VERSION"], 3)
        self.assertEqual(out_layer.crs().authid(), "EPSG:3857")
        self.assertEqual(out_layer.fields().field("id_ext").type(), QMetaType.Type.LongLong)
        self.assertEqual(out_layer.fields().field("jour").type(), QMetaType.Type.QDate)
        feats = list(out_layer.getFeatures())
        self.assertEqual([f["id_ext"] for f in feats], [1000000000, 2000000000])
        self.assertEqual([f["nom"] for f in feats], ["ALPHA", "BETA"])
        self.assertGreater(feats[0].geometry().asPoint().x(), 200000)

        # Direct GDAL/OGR GeoPackage streaming sink
        out_gpkg = str(self.tmp_dir / "livraison.gpkg")
        res_gpkg = self.processing.run(
            "transformer:apply_recipe",
            {
                "INPUT": layer,
                "RECIPE_FILE": recipe_path,
                "OUTPUT": out_gpkg,
            },
        )
        self.assertEqual(res_gpkg["PRODUCED_COUNT"], 2)
        reloaded = QgsVectorLayer(res_gpkg["OUTPUT"], "check", "ogr")
        self.assertTrue(reloaded.isValid())
        self.assertEqual(reloaded.featureCount(), 2)
        self.assertEqual(reloaded.crs().authid(), "EPSG:3857")
        self.assertEqual([f["nom"] for f in reloaded.getFeatures()], ["ALPHA", "BETA"])
        del reloaded

    def test_apply_recipe_local_catalogue_and_overrides(self):
        from Transfomer.core.config_manager import ConfigManager

        manager = ConfigManager(str(self.tmp_dir))
        res_save = manager.add_table_config(
            "catalogue_rec",
            "source_pts",
            {"code_str": 'to_string("code")'},
            filter_config={"enabled": True, "expression": '"code" = 1'},
            target_crs="EPSG:4326",
            field_definitions={"code_str": {"type": "Text", "length": 10}},
        )
        self.assertTrue(res_save["success"])
        self.assertTrue(manager.save_config())

        layer = self._make_point_layer()
        res = self.processing.run(
            "transformer:apply_recipe",
            {
                "INPUT": layer,
                "RECIPE_FILE": "",
                "RECIPE_NAME": "catalogue_rec",
                "FILTER_OVERRIDE": '"code" >= 2',
                "CRS_OVERRIDE": "EPSG:2154",
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
        )
        self.assertEqual(res["PRODUCED_COUNT"], 2)
        self.assertEqual(res["FILTERED_OUT_COUNT"], 1)
        self.assertEqual(res["OUTPUT"].crs().authid(), "EPSG:2154")
        self.assertEqual([f["code_str"] for f in res["OUTPUT"].getFeatures()], ["2", "3"])

    def test_apply_recipe_non_spatial_table_constructs_points_with_target_crs(self):
        table = QgsVectorLayer(
            "None?field=id_site:string&field=x:double&field=y:double",
            "sites_csv",
            "memory",
        )
        feat = QgsFeature(table.fields())
        feat.setAttributes(["S1", 652469.0, 6862035.0])
        self.assertTrue(table.dataProvider().addFeatures([feat])[0])

        recipe_path = self._write_recipe_file(
            "xy_to_points.json",
            {
                "sites_geom": {
                    "source_file": "sites_csv",
                    "calculated_fields": {"site": '"id_site"'},
                    "geometry_expression": 'make_point("x", "y")',
                    "target_crs": "EPSG:2154",
                }
            },
        )
        res = self.processing.run(
            "transformer:apply_recipe",
            {
                "INPUT": table,
                "RECIPE_FILE": recipe_path,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
        )
        out = res["OUTPUT"]
        self.assertEqual(res["PRODUCED_COUNT"], 1)
        self.assertEqual(out.crs().authid(), "EPSG:2154")
        self.assertEqual(QgsWkbTypes.flatType(out.wkbType()), QgsWkbTypes.Point)
        pt = next(out.getFeatures()).geometry().asPoint()
        self.assertAlmostEqual(pt.x(), 652469.0, places=3)
        self.assertAlmostEqual(pt.y(), 6862035.0, places=3)

    def test_apply_recipe_mixed_single_and_multi_geometry_promotes_cleanly_for_gpkg(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:2154&field=k:integer", "polys", "memory")
        f1 = QgsFeature(layer.fields())
        f1.setAttributes([1])
        f1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"))
        f2 = QgsFeature(layer.fields())
        f2.setAttributes([2])
        f2.setGeometry(QgsGeometry.fromWkt("POLYGON((20 0, 30 0, 30 10, 20 10, 20 0))"))
        self.assertTrue(layer.dataProvider().addFeatures([f1, f2])[0])

        recipe_path = self._write_recipe_file(
            "mixed_multi.json",
            {
                "mixed": {
                    "source_file": "polys",
                    "calculated_fields": {"k": '"k"'},
                    "geometry_expression": (
                        'CASE WHEN "k" = 1 THEN $geometry '
                        'ELSE collect_geometries($geometry, translate($geometry, 50, 0)) END'
                    ),
                }
            },
        )
        out_gpkg = str(self.tmp_dir / "mixed_multi.gpkg")
        res = self.processing.run(
            "transformer:apply_recipe",
            {"INPUT": layer, "RECIPE_FILE": recipe_path, "OUTPUT": out_gpkg},
        )
        self.assertEqual(res["PRODUCED_COUNT"], 2)
        reloaded = QgsVectorLayer(res["OUTPUT"], "mixed_check", "ogr")
        self.assertTrue(reloaded.isValid())
        self.assertEqual(reloaded.featureCount(), 2)
        self.assertTrue(QgsWkbTypes.isMultiType(reloaded.wkbType()))
        del reloaded

    def test_apply_recipe_strict_shapefile_preflight_blocks_long_field_before_file_creation(self):
        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "long_field.json",
            {
                "too_long": {
                    "source_file": "source_pts",
                    "calculated_fields": {"nom_colonne_trop_long_dbf": '"label"'},
                    "field_definitions": {"nom_colonne_trop_long_dbf": {"type": "Text", "length": 30}},
                }
            },
        )
        out_shp = self.tmp_dir / "blocked.shp"
        with self.assertRaises(QgsProcessingException) as ctx:
            self.processing.run(
                "transformer:apply_recipe",
                {
                    "INPUT": layer,
                    "RECIPE_FILE": recipe_path,
                    "STRICT_SCHEMA_CHECK": True,
                    "OUTPUT": str(out_shp),
                },
            )
        self.assertIn("10 octets", str(ctx.exception))
        self.assertFalse(out_shp.exists())

        # Explicitly disabling strict check allows GDAL fallback
        res = self.processing.run(
            "transformer:apply_recipe",
            {
                "INPUT": layer,
                "RECIPE_FILE": recipe_path,
                "STRICT_SCHEMA_CHECK": False,
                "OUTPUT": str(out_shp),
            },
        )
        self.assertEqual(res["PRODUCED_COUNT"], 3)
        self.assertTrue(out_shp.exists())

    def test_apply_recipe_adverse_failures_fail_fast(self):
        layer = self._make_point_layer()

        # Ambiguous multi-recipe file without RECIPE_NAME
        multi_path = self._write_recipe_file(
            "multi.json",
            {
                "r1": {"source_file": "a", "calculated_fields": {"c": '"code"'}},
                "r2": {"source_file": "b", "calculated_fields": {"c": '"code"'}},
            },
        )
        with self.assertRaises(QgsProcessingException) as ctx:
            self.processing.run(
                "transformer:apply_recipe",
                {"INPUT": layer, "RECIPE_FILE": multi_path, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
            )
        self.assertIn("RECIPE_NAME", str(ctx.exception))

        # Secret embedded in recipe JSON must be rejected
        secret_path = self._write_recipe_file(
            "secret.json",
            {
                "bad": {
                    "source_file": "a",
                    "calculated_fields": {"c": '"code"'},
                    "password": "leaked",
                }
            },
        )
        with self.assertRaises(QgsProcessingException) as ctx_secret:
            self.processing.run(
                "transformer:apply_recipe",
                {"INPUT": layer, "RECIPE_FILE": secret_path, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
            )
        self.assertIn("secrets", str(ctx_secret.exception).lower())

        # Lossy float-to-integer conversion must fail fast
        lossy_path = self._write_recipe_file(
            "lossy.json",
            {
                "lossy": {
                    "source_file": "a",
                    "calculated_fields": {"entier": '"amount"'},
                    "field_definitions": {"entier": {"type": "Integer"}},
                }
            },
        )
        with self.assertRaises(QgsProcessingException) as ctx_lossy:
            self.processing.run(
                "transformer:apply_recipe",
                {"INPUT": layer, "RECIPE_FILE": lossy_path, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
            )
        self.assertIn("tronquée", str(ctx_lossy.exception))

        # Cancellation before start raises QgsProcessingException
        ok_path = self._write_recipe_file(
            "ok.json",
            {"ok": {"source_file": "a", "calculated_fields": {"c": '"code"'}}},
        )
        fb = QgsProcessingFeedback()
        fb.cancel()
        with self.assertRaises(QgsProcessingException):
            self.processing.run(
                "transformer:apply_recipe",
                {"INPUT": layer, "RECIPE_FILE": ok_path, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
                feedback=fb,
            )

    def test_apply_recipe_supports_dynamic_attributes_function(self):
        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "dyn_attr.json",
            {
                "dyn": {
                    "source_file": "source_pts",
                    "calculated_fields": {"dyn_val": "attribute($currentfeature, 'label')"},
                }
            },
        )
        res = self.processing.run(
            "transformer:apply_recipe",
            {"INPUT": layer, "RECIPE_FILE": recipe_path, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
        )
        self.assertEqual(res["PRODUCED_COUNT"], 3)
        self.assertEqual(next(res["OUTPUT"].getFeatures())["dyn_val"], "  alpha ")

    # ------------------------------------------------------------------
    # Couture 3: transformer:transform_vector (ad-hoc)
    # ------------------------------------------------------------------

    def test_transform_vector_field_mapping_and_empty_mapping_identity(self):
        layer = self._make_point_layer()

        res = self.processing.run(
            "transformer:transform_vector",
            {
                "INPUT": layer,
                "FIELDS_MAPPING": [
                    {
                        "name": "code_x2",
                        "type": int(QMetaType.Type.LongLong),
                        "length": 0,
                        "precision": 0,
                        "expression": '"code" * 2',
                    },
                    {
                        "name": "tag",
                        "type": int(QMetaType.Type.QString),
                        "length": 20,
                        "precision": 0,
                        "expression": 'upper(trim("label"))',
                    },
                ],
                "FILTER_EXPRESSION": '"code" <= 2',
                "GEOMETRY_EXPRESSION": "buffer($geometry, 0.01)",
                "TARGET_CRS": "EPSG:3857",
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
        )
        out = res["OUTPUT"]
        self.assertEqual(res["PRODUCED_COUNT"], 2)
        self.assertEqual(res["FILTERED_OUT_COUNT"], 1)
        self.assertEqual(out.crs().authid(), "EPSG:3857")
        self.assertEqual(QgsWkbTypes.geometryType(out.wkbType()), QgsWkbTypes.PolygonGeometry)
        self.assertEqual(out.fields().field("code_x2").type(), QMetaType.Type.LongLong)
        self.assertEqual([f["tag"] for f in out.getFeatures()], ["ALPHA", "BETA"])

        # Empty FIELDS_MAPPING preserves all source fields as-is
        res_id = self.processing.run(
            "transformer:transform_vector",
            {
                "INPUT": layer,
                "FIELDS_MAPPING": [],
                "FILTER_EXPRESSION": '"code" = 3',
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
        )
        self.assertEqual(res_id["PRODUCED_COUNT"], 1)
        self.assertEqual(res_id["OUTPUT"].fields().names(), ["code", "label", "amount"])
        self.assertEqual(next(res_id["OUTPUT"].getFeatures())["label"], "gamma")

    # ------------------------------------------------------------------
    # Couture 4: Graphical Modeler chaining (.model3)
    # ------------------------------------------------------------------

    def test_graphical_modeler_chains_apply_recipe_into_transform_vector(self):
        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "step1.json",
            {
                "etape1": {
                    "source_file": "source_pts",
                    "calculated_fields": {
                        "id_num": '"code"',
                        "nom": 'upper(trim("label"))',
                    },
                    "field_definitions": {
                        "id_num": {"type": "Integer"},
                        "nom": {"type": "Text", "length": 30},
                    },
                    "filter": {"enabled": True, "expression": '"amount" >= 10'},
                }
            },
        )

        model = QgsProcessingModelAlgorithm("etl_chain", "TransformerTest")
        model.addModelParameter(
            QgsProcessingParameterVectorLayer("in_layer", "Entree"),
            QgsProcessingModelParameter("in_layer"),
        )

        child1 = QgsProcessingModelChildAlgorithm("transformer:apply_recipe")
        child1.setChildId("step_recipe")
        child1.addParameterSources(
            "INPUT", [QgsProcessingModelChildParameterSource.fromModelParameter("in_layer")],
        )
        child1.addParameterSources(
            "RECIPE_FILE", [QgsProcessingModelChildParameterSource.fromStaticValue(recipe_path)],
        )
        model.addChildAlgorithm(child1)

        child2 = QgsProcessingModelChildAlgorithm("transformer:transform_vector")
        child2.setChildId("step_reproj")
        child2.addParameterSources(
            "INPUT",
            [QgsProcessingModelChildParameterSource.fromChildOutput("step_recipe", "OUTPUT")],
        )
        child2.addParameterSources(
            "FIELDS_MAPPING",
            [QgsProcessingModelChildParameterSource.fromStaticValue([
                {
                    "name": "label_final",
                    "type": int(QMetaType.Type.QString),
                    "length": 50,
                    "precision": 0,
                    "expression": '"nom" || \'_\' || to_string("id_num")',
                }
            ])],
        )
        child2.addParameterSources(
            "TARGET_CRS",
            [QgsProcessingModelChildParameterSource.fromStaticValue("EPSG:3857")],
        )
        model_out = QgsProcessingModelOutput("final_out", "final_out")
        model_out.setChildId("step_reproj")
        model_out.setChildOutputName("OUTPUT")
        child2.setModelOutputs({"final_out": model_out})
        model.addChildAlgorithm(child2)

        out_gpkg = str(self.tmp_dir / "model_chained.gpkg")
        res = self.processing.run(
            model,
            {
                "in_layer": layer,
                "final_out": out_gpkg,
            },
        )
        reloaded = QgsVectorLayer(res["final_out"], "model_check", "ogr")
        self.assertTrue(reloaded.isValid())
        self.assertEqual(reloaded.crs().authid(), "EPSG:3857")
        self.assertEqual([f["label_final"] for f in reloaded.getFeatures()], ["ALPHA_1", "BETA_2"])
        del reloaded

    def test_geopackage_handle_is_released_immediately_after_run(self):
        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "release.json",
            {"rel": {"source_file": "source_pts", "calculated_fields": {"c": '"code"'}}},
        )
        out_gpkg = self.tmp_dir / "immediate_unlink.gpkg"
        res = self.processing.run(
            "transformer:apply_recipe",
            {"INPUT": layer, "RECIPE_FILE": recipe_path, "OUTPUT": str(out_gpkg)},
        )
        self.assertEqual(res["PRODUCED_COUNT"], 3)
        self.assertTrue(out_gpkg.exists())
        # Must succeed immediately on Windows without PermissionError
        os.unlink(out_gpkg)
        self.assertFalse(out_gpkg.exists())

    def test_background_processing_thread_rejects_unsafe_live_project_expression(self):
        from qgis.PyQt.QtCore import QEventLoop, QTimer
        from qgis.core import QgsProcessingAlgRunnerTask

        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "unsafe_bg.json",
            {
                "unsafe": {
                    "source_file": "source_pts",
                    "calculated_fields": {"bad": "get_feature('other', 'code', 1)"},
                }
            },
        )
        alg = QgsApplication.processingRegistry().algorithmById("transformer:apply_recipe")
        ctx = QgsProcessingContext()
        errors = []

        class _CaptureFeedback(QgsProcessingFeedback):
            def reportError(self, error, fatalError=False):
                errors.append(error)
                super().reportError(error, fatalError)

        fb = _CaptureFeedback()
        outcome = {}
        loop = QEventLoop()

        def on_done(ok, results):
            outcome["ok"] = ok
            outcome["results"] = results
            loop.quit()

        task = QgsProcessingAlgRunnerTask(
            alg,
            {
                "INPUT": layer,
                "RECIPE_FILE": recipe_path,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
            ctx,
            fb,
        )
        task.executed.connect(on_done)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(12000)
        QgsApplication.taskManager().addTask(task)
        loop.exec()
        timer.stop()

        self.assertIn("ok", outcome)
        self.assertFalse(outcome["ok"])
        combined = " ".join(errors)
        self.assertIn("get_feature", combined)

    # ------------------------------------------------------------------
    # Couture 5: transformer:publish_postgresql
    # ------------------------------------------------------------------

    def test_publish_postgresql_append_replace_update_and_rollback_secret_masking(self):
        layer = self._make_point_layer()
        state = {
            "target_key": ("public", "bpe_cible"),
            "create_key": ("public", "bpe_cible"),
            "secret": "TopSecretPgPass99",
            "commits": 0,
            "rollbacks": 0,
            "executed": [],
            "fail_on_insert": False,
            "committed_tables": {
                ("public", "bpe_cible"): {
                    "columns": [
                        ("code_pg", "integer", "int4"),
                        ("nom_pg", "text", "text"),
                        ("geom", "USER-DEFINED", "geometry"),
                    ],
                    "rows": [(99, "EXISTING", "SRID=4326;POINT(0 0)")],
                }
            },
        }
        state["pending_tables"] = {
            k: {"columns": list(v["columns"]), "rows": list(v["rows"])}
            for k, v in state["committed_tables"].items()
        }
        fake_pg = _make_fake_psycopg2(state)
        conn_params = {
            "host": "localhost",
            "port": 5432,
            "database": "sig",
            "user": "gis",
            "password": "TopSecretPgPass99",
        }

        with (
            patch(
                "Transfomer.processing_provider.publish_postgresql_algorithm.resolve_postgres_connection_params",
                return_value=conn_params,
            ),
            patch.dict(sys.modules, {"psycopg2": fake_pg}),
            patch("Transfomer.pg.export_task.pg_sql", fake_pg.sql),
        ):
            # Atomic replace
            res = self.processing.run(
                "transformer:publish_postgresql",
                {
                    "INPUT": layer,
                    "CONNECTION": "pg_prod",
                    "SCHEMA": "public",
                    "TABLE": "bpe_cible",
                    "MODE": 1,  # replace
                    "ALLOW_CREATE": False,
                    "FIELD_MAPPING": json.dumps({"code": "code_pg", "label": "nom_pg"}),
                },
            )
            self.assertEqual(res["STATUS"], "success")
            self.assertEqual(res["COMMITTED_COUNT"], 3)
            self.assertEqual(len(state["committed_tables"][("public", "bpe_cible")]["rows"]), 3)
            self.assertEqual(state["commits"], 1)

            # Upsert with different source/target key names
            res_up = self.processing.run(
                "transformer:publish_postgresql",
                {
                    "INPUT": layer,
                    "CONNECTION": "pg_prod",
                    "SCHEMA": "public",
                    "TABLE": "bpe_cible",
                    "MODE": 2,  # update
                    "ALLOW_CREATE": False,
                    "FIELD_MAPPING": json.dumps({"code": "code_pg", "label": "nom_pg"}),
                    "SOURCE_KEY_FIELD": "code",
                    "TARGET_KEY_FIELD": "code_pg",
                },
            )
            self.assertEqual(res_up["STATUS"], "success")
            self.assertTrue(any("ON CONFLICT" in sql for sql in state["executed"]))

            # Failure during replace rolls back old rows and masks secret
            state["fail_on_insert"] = True
            with self.assertRaises(QgsProcessingException) as ctx_err:
                self.processing.run(
                    "transformer:publish_postgresql",
                    {
                        "INPUT": layer,
                        "CONNECTION": "pg_prod",
                        "SCHEMA": "public",
                        "TABLE": "bpe_cible",
                        "MODE": 1,
                        "FIELD_MAPPING": json.dumps({"code": "code_pg", "label": "nom_pg"}),
                    },
                )
            self.assertNotIn("TopSecretPgPass99", str(ctx_err.exception))
            self.assertGreaterEqual(state["rollbacks"], 1)
            self.assertGreater(len(state["committed_tables"][("public", "bpe_cible")]["rows"]), 0)

            # Missing table without ALLOW_CREATE must fail
            state["fail_on_insert"] = False
            with self.assertRaises(QgsProcessingException) as ctx_create:
                self.processing.run(
                    "transformer:publish_postgresql",
                    {
                        "INPUT": layer,
                        "CONNECTION": "pg_prod",
                        "SCHEMA": "public",
                        "TABLE": "table_absente",
                        "MODE": 0,
                        "ALLOW_CREATE": False,
                    },
                )
            self.assertIn("création", str(ctx_create.exception).lower())

    # ------------------------------------------------------------------
    # Couture 6: Public Python API (Transfomer.api) & single-recipe export
    # ------------------------------------------------------------------

    def test_python_api_facade_and_single_recipe_export(self):
        from Transfomer import api
        from Transfomer.core.config_manager import ConfigManager
        from Transfomer.processing_provider.common import build_processing_python_snippet

        manager = ConfigManager(str(self.tmp_dir))
        manager.add_table_config(
            "rec_a", "src_a", {"c": '"code"'}, field_definitions={"c": {"type": "Integer"}},
        )
        manager.add_table_config(
            "rec_b", "src_b", {"lbl": 'upper("label")'}, field_definitions={"lbl": {"type": "Text", "length": 20}},
        )
        self.assertTrue(manager.save_config())

        self.assertEqual(api.list_recipes(plugin_dir=str(self.tmp_dir)), ["rec_a", "rec_b"])

        single_json = str(self.tmp_dir / "rec_b_seule.json")
        api.export_recipe("rec_b", single_json, plugin_dir=str(self.tmp_dir))
        self.assertEqual(api.list_recipes(recipe_file=single_json), ["rec_b"])

        # Apply recipe directly via api.apply_recipe to memory and GPKG
        layer = self._make_point_layer()
        res_mem = api.apply_recipe(layer, recipe_file=single_json)
        self.assertEqual(res_mem["summary"]["produced_count"], 3)
        self.assertEqual(res_mem["layer"].fields().names(), ["lbl"])

        out_gpkg = str(self.tmp_dir / "api_out.gpkg")
        res_file = api.apply_recipe(
            layer,
            recipe_file=single_json,
            output=out_gpkg,
            target_crs="EPSG:3857",
            filter_expression='"code" = 2',
        )
        self.assertIsNone(res_file["layer"])
        self.assertEqual(res_file["summary"]["produced_count"], 1)
        check = QgsVectorLayer(res_file["output_path"], "api_check", "ogr")
        self.assertTrue(check.isValid())
        self.assertEqual(check.featureCount(), 1)
        self.assertEqual(next(check.getFeatures())["lbl"], "BETA")
        del check

        # Ad-hoc transform_vector directly via api
        res_adhoc = api.transform_vector(
            layer,
            calculated_fields={"sum_val": '"code" + 10'},
            filter_expression='"code" = 1',
        )
        self.assertEqual(next(res_adhoc["layer"].getFeatures())["sum_val"], 11)

        snippet = build_processing_python_snippet("rec_b", recipe_file=single_json, input_ref="bpe")
        self.assertIn('processing.run("transformer:apply_recipe"', snippet)
        self.assertIn("qgis_process run transformer:apply_recipe", snippet)

    # ------------------------------------------------------------------
    # Hardening regressions (Axe 1 & Axe 2 review invariants)
    # ------------------------------------------------------------------

    def test_partial_file_is_cleaned_up_on_mid_stream_failure(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=val:double", "partial_src", "memory")
        feats = []
        for idx, val in enumerate([1.0, 2.0, 3.0, 4.5, 5.0]):
            f = QgsFeature(layer.fields())
            f.setAttributes([val])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(idx, idx)))
            feats.append(f)
        self.assertTrue(layer.dataProvider().addFeatures(feats)[0])

        recipe_path = self._write_recipe_file(
            "fail_mid.json",
            {
                "fail_mid": {
                    "source_file": "partial_src",
                    "calculated_fields": {"strict_int": '"val"'},
                    "field_definitions": {"strict_int": {"type": "Integer"}},
                }
            },
        )
        out_gpkg = self.tmp_dir / "must_not_remain.gpkg"
        from Transfomer.core.transformer import SimpleTransformer
        orig_init = SimpleTransformer.__init__

        def small_batch_init(tself, cfg):
            orig_init(tself, cfg)
            tself.batch_size = 2

        with patch.object(SimpleTransformer, "__init__", small_batch_init):
            with self.assertRaises(QgsProcessingException):
                self.processing.run(
                    "transformer:apply_recipe",
                    {"INPUT": layer, "RECIPE_FILE": recipe_path, "OUTPUT": str(out_gpkg)},
                )
        self.assertFalse(out_gpkg.exists())

    def test_pg_pool_key_distinguishes_services(self):
        from Transfomer.pg.connection_task import PgConnectionPoolManager
        key_a = PgConnectionPoolManager._pool_key({"service": "svc_prod_a"})
        key_b = PgConnectionPoolManager._pool_key({"service": "svc_prod_b"})
        self.assertNotEqual(key_a, key_b)

    def test_publish_postgresql_resolves_connection_on_main_thread_in_prepare_algorithm(self):
        from qgis.PyQt.QtCore import QEventLoop, QThread, QTimer
        from qgis.core import QgsProcessingAlgRunnerTask

        layer = self._make_point_layer()
        main_thread = QgsApplication.instance().thread()
        observed_threads = {}

        state = {
            "target_key": ("public", "t_mt"),
            "create_key": ("public", "t_mt"),
            "commits": 0,
            "rollbacks": 0,
            "executed": [],
            "fail_on_insert": False,
            "committed_tables": {
                ("public", "t_mt"): {
                    "columns": [
                        ("code", "integer", "int4"),
                        ("geom", "USER-DEFINED", "geometry"),
                    ],
                    "rows": [],
                }
            },
        }
        state["pending_tables"] = {
            k: {"columns": list(v["columns"]), "rows": list(v["rows"])}
            for k, v in state["committed_tables"].items()
        }
        fake_pg = _make_fake_psycopg2(state)

        def fake_resolve(conn_name, plugin_dir=""):
            observed_threads["resolve_thread"] = QThread.currentThread()
            return {"host": "localhost", "port": 5432, "database": "sig", "user": "gis"}

        alg = QgsApplication.processingRegistry().algorithmById("transformer:publish_postgresql")
        ctx = QgsProcessingContext()
        fb = QgsProcessingFeedback()
        outcome = {}
        loop = QEventLoop()

        def on_done(ok, results):
            outcome["ok"] = ok
            outcome["results"] = results
            loop.quit()

        with (
            patch(
                "Transfomer.processing_provider.publish_postgresql_algorithm.resolve_postgres_connection_params",
                side_effect=fake_resolve,
            ),
            patch.dict(sys.modules, {"psycopg2": fake_pg}),
            patch("Transfomer.pg.export_task.pg_sql", fake_pg.sql),
        ):
            task = QgsProcessingAlgRunnerTask(
                alg,
                {
                    "INPUT": layer,
                    "CONNECTION": "pg_prod",
                    "SCHEMA": "public",
                    "TABLE": "t_mt",
                    "MODE": 0,
                    "FIELD_MAPPING": json.dumps({"code": "code"}),
                },
                ctx,
                fb,
            )
            task.executed.connect(on_done)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(12000)
            QgsApplication.taskManager().addTask(task)
            loop.exec()
            timer.stop()

        self.assertTrue(outcome.get("ok"), outcome)
        self.assertEqual(observed_threads.get("resolve_thread"), main_thread)

    def test_transform_vector_preserves_native_time_and_handles_negative_length_and_property(self):
        from qgis.PyQt.QtCore import QTime
        from qgis.core import QgsProperty

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "with_time", "memory")
        layer.dataProvider().addAttributes([
            QgsField("code", QMetaType.Type.Int),
            QgsField("heure", QMetaType.Type.QTime),
        ])
        layer.updateFields()
        feat = QgsFeature(layer.fields())
        feat.setAttributes([5, QTime(14, 30, 0)])
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 48)))
        self.assertTrue(layer.dataProvider().addFeatures([feat])[0])

        # Empty FIELDS_MAPPING must preserve QTime without crashing
        res_id = self.processing.run(
            "transformer:transform_vector",
            {"INPUT": layer, "FIELDS_MAPPING": [], "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
        )
        self.assertEqual(res_id["PRODUCED_COUNT"], 1)
        self.assertEqual(res_id["OUTPUT"].fields().field("heure").type(), QMetaType.Type.QTime)

        # Negative sentinel length/precision (-1) via processing.run must succeed
        mapping_list = [
            {
                "name": "c_out",
                "type": int(QMetaType.Type.Int),
                "length": -1,
                "precision": -1,
                "expression": '"code" + 1',
            }
        ]
        res_neg = self.processing.run(
            "transformer:transform_vector",
            {
                "INPUT": layer,
                "FIELDS_MAPPING": mapping_list,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
        )
        self.assertEqual(res_neg["PRODUCED_COUNT"], 1)
        self.assertEqual(next(res_neg["OUTPUT"].getFeatures())["c_out"], 6)

        # QgsProperty evaluation helper stays resilient if a model supplies one
        from Transfomer.processing_provider.transform_vector_algorithm import TransformVectorAlgorithm
        ctx = QgsProcessingContext()
        parsed = TransformVectorAlgorithm._parse_fields_mapping(
            QgsProperty.fromValue(mapping_list), context=ctx,
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "c_out")

    def test_filtered_sampling_ignores_excluded_rows_for_geometry_type(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=keep:integer", "filt_sample", "memory")
        f_bad = QgsFeature(layer.fields())
        f_bad.setAttributes([0])
        # Null geometry on excluded row
        f_ok = QgsFeature(layer.fields())
        f_ok.setAttributes([1])
        f_ok.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 48)))
        self.assertTrue(layer.dataProvider().addFeatures([f_bad, f_ok])[0])

        recipe_path = self._write_recipe_file(
            "filt_geom.json",
            {
                "filt_geom": {
                    "source_file": "filt_sample",
                    "calculated_fields": {"k": '"keep"'},
                    "filter": {"enabled": True, "expression": '"keep" = 1'},
                    "geometry_expression": "centroid($geometry)",
                }
            },
        )
        res = self.processing.run(
            "transformer:apply_recipe",
            {"INPUT": layer, "RECIPE_FILE": recipe_path, "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT},
        )
        self.assertEqual(res["PRODUCED_COUNT"], 1)
        self.assertEqual(res["FILTERED_OUT_COUNT"], 1)

    def test_inferred_text_succeeds_on_shapefile_and_ogr_uri_is_parsed(self):
        from Transfomer.processing_provider.common import extract_output_destination_path

        self.assertEqual(
            extract_output_destination_path(Path("C:/tmp/a.gpkg")),
            "C:\\tmp\\a.gpkg" if os.name == "nt" else "C:/tmp/a.gpkg",
        )
        self.assertEqual(
            extract_output_destination_path("ogr:dbname='C:/tmp/out.gpkg' table=\"couche\" (geom)"),
            "C:/tmp/out.gpkg",
        )

        # Inferred text field without explicit field_definitions must work on Shapefile
        layer = self._make_point_layer()
        recipe_path = self._write_recipe_file(
            "inferred_shp.json",
            {"inf_shp": {"source_file": "source_pts", "calculated_fields": {"lbl": 'upper("label")'}}},
        )
        out_shp = self.tmp_dir / "inferred_ok.shp"
        res = self.processing.run(
            "transformer:apply_recipe",
            {
                "INPUT": layer,
                "RECIPE_FILE": recipe_path,
                "STRICT_SCHEMA_CHECK": True,
                "OUTPUT": str(out_shp),
            },
        )
        self.assertEqual(res["PRODUCED_COUNT"], 3)
        self.assertTrue(out_shp.exists())

    def test_main_plugin_lazy_export_flag_works_without_init_gui(self):
        from Transfomer import main_plugin
        self.assertTrue(main_plugin.EXPORT_MODULE_AVAILABLE)
        self.assertTrue(main_plugin.ENHANCED_INTERFACE_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
