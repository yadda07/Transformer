# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Native-export orchestration tests with task doubles and scratch files only.

Run: python -B tests/test_export_tasks.py
No QGIS runtime, remote database or user export is opened by these tests.
"""

import ast
import codecs
from contextlib import closing
from enum import Enum
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile
import importlib
import math
import uuid

try:
    from qgis.core import QgsApplication
    NATIVE_QGIS = QgsApplication.instance() is not None
except ImportError:
    NATIVE_QGIS = False


ROOT = Path(__file__).resolve().parents[1]


class BoundSignal:
    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)

    def emit(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class Signal:
    def __init__(self, *args):
        pass

    def __set_name__(self, owner, name):
        self.name = "_signal_" + name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.setdefault(self.name, BoundSignal())


class Object:
    def __init__(self, *args):
        pass


class Task(Object):
    CanCancel = 1
    progressChanged = Signal(float)
    taskTerminated = Signal()

    def __init__(self, *args):
        self.cancelled = False

    def isCanceled(self):
        return self.cancelled

    def cancel(self):
        self.cancelled = True

    def setProgress(self, progress):
        self.progressChanged.emit(progress)


class NativeWriter(Task):
    completed = Signal(str, str)
    errorOccurred = Signal(int, str)

    def __init__(self, layer, path, options):
        super().__init__()
        self.layer, self.path, self.options = layer, Path(path), options

    def setDependentLayers(self, layers):
        self.dependencies = layers

    def finish_synthetic(self):
        if self.isCanceled():
            self.taskTerminated.emit()
            return
        if self.options.driverName == "GPKG":
            table = self.options.layerName
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute('CREATE TABLE "' + table + '" (value TEXT)')
                connection.executemany('INSERT INTO "' + table + '" VALUES (?)', [("demo",)] * self.layer.featureCount())
                connection.commit()
        else:
            self.path.write_bytes(b"synthetic vector data")
        self.completed.emit(str(self.path), getattr(self.options, "layerName", ""))


class Field:
    def __init__(self, name, kind="QString", length=0, precision=0, subtype="QString"):
        self.values = name, kind, length, precision, subtype

    def name(self):
        return self.values[0]

    def type(self):
        return self.values[1]

    def typeName(self):
        return self.values[1]

    def length(self):
        return self.values[2]

    def precision(self):
        return self.values[3]

    def subType(self):
        return self.values[4]


class Iterator:
    def __init__(self, records):
        self.records = iter(records)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.records)

    def close(self):
        self.closed = True


class FeatureRequest:
    def __init__(self):
        self.fids = None

    def setFlags(self, flags):
        return self

    def setSubsetOfAttributes(self, attributes):
        return self

    def setFilterFids(self, fids):
        self.fids = fids
        return self


class FeatureSource:
    def __init__(self, layer):
        self.records = list(layer.records)
        self.iterator = None

    def getFeatures(self, request):
        self.iterator = Iterator(record for index, record in enumerate(self.records) if request.fids is None or index in request.fids)
        return self.iterator


class Layer:
    def __init__(self, name, count=2, selected=1, fields=(), records=()):
        self.value, self.count, self.selected = name, count, selected
        self.schema, self.records = fields, records

    def name(self):
        return self.value

    def featureCount(self):
        return self.count

    def selectedFeatureCount(self):
        return self.selected

    def selectedFeatureIds(self):
        return list(range(self.selected))

    def fields(self):
        return self.schema


class Scheduler:
    def __init__(self):
        self.tasks = []
        self.timers = []

    def addTask(self, task):
        self.tasks.append(task)

    def drain(self):
        while self.tasks or self.timers:
            while self.timers:
                self.timers.pop(0)()
            if self.tasks:
                task = self.tasks.pop(0)
                if isinstance(task, NativeWriter):
                    task.finish_synthetic()
                else:
                    result = task.run()
                    task.finished(result)


def load_exports(scheduler):
    namespace = {
        "QObject": Object, "QWidget": Object, "QgsTask": Task,
        "QgsVectorFileWriterTask": NativeWriter, "pyqtSignal": Signal,
        "QTimer": types.SimpleNamespace(singleShot=lambda delay, callback: scheduler.timers.append(callback)),
        "QgsApplication": types.SimpleNamespace(taskManager=lambda: scheduler),
        "QgsVectorFileWriter": types.SimpleNamespace(SaveVectorOptions=types.SimpleNamespace),
        "Path": Path, "os": os, "re": re, "shutil": shutil,
        "tempfile": tempfile, "sqlite3": sqlite3, "zipfile": zipfile, "closing": closing,
        "Enum": Enum, "GPKG_ACTION_ADD_LAYER": 1, "GPKG_ACTION_CREATE_FILE": 0,
        "codecs": codecs, "math": math, "uuid": uuid, "ogr": None,
        "QMetaType": types.SimpleNamespace(Type=types.SimpleNamespace(**{name: name for name in (
            "Int", "LongLong", "Bool", "Double", "QString", "QDate", "QTime", "QDateTime", "QByteArray", "QStringList", "QVariantList", "QVariantMap",
        )})),
        "QgsVectorLayerFeatureSource": FeatureSource, "QgsFeatureRequest": FeatureRequest,
        "Qgis": types.SimpleNamespace(FeatureRequestFlag=types.SimpleNamespace(NoGeometry=1)),
        "QgsVariantUtils": types.SimpleNamespace(isNull=lambda value: value is None),
    }
    tree = ast.parse((ROOT / "export/export_module.py").read_text(encoding="utf-8-sig"))
    names = {"ExportFormat", "ExportManager", "ExportPreflight", "ExportFileTask", "ExportBatch", "ExportWidget"}
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "export/export_module.py", "exec"), namespace)
    return namespace


class ExportTaskTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        self.namespace = load_exports(self.scheduler)
        self.Format = self.namespace["ExportFormat"]
        self.Batch = self.namespace["ExportBatch"]
        self.temp = tempfile.TemporaryDirectory(prefix="transformer-export-test-")
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def manager(self):
        def table_name(name, used):
            base = re.sub(r"[^a-zA-Z0-9_]", "_", name)
            candidate = base
            index = 2
            while candidate in used:
                candidate = f"{base}_{index}"
                index += 1
            used.add(candidate)
            return candidate
        return types.SimpleNamespace(
            driver_mapping={self.Format.GEOPACKAGE: "GPKG", self.Format.SHAPEFILE: "ESRI Shapefile", self.Format.GEOJSON: "GeoJSON"},
            _configure_format_options=lambda *args: None,
            _sanitize_gpkg_table_name=table_name,
        )

    def jobs(self, destination, names=("first", "second")):
        return [{"layer": Layer(name), "name": name, "count": 2, "path": str(destination), "selected": False} for name in names]

    def test_shared_package_writers_are_sequential_and_installed_once(self):
        destination = self.folder / "delivery.gpkg"
        batch = self.Batch(self.manager(), self.jobs(destination), self.Format.GEOPACKAGE, "utf-8", True)
        results = []
        batch.finished.connect(results.append)
        batch.start()
        self.assertEqual(len(batch.writer_tasks), 2)
        self.assertEqual(self.scheduler.tasks, [batch.writer_tasks[0]])
        self.assertEqual(batch.writer_tasks[0].options.actionOnExistingFile, 0)
        self.assertEqual(batch.writer_tasks[1].options.actionOnExistingFile, 1)
        self.assertFalse(destination.exists())
        self.scheduler.drain()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "success")
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM "first"').fetchone()[0], 2)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM "second"').fetchone()[0], 2)
        self.assertFalse(list(self.folder.glob(".transformer-*")))

    def test_shared_package_preserves_unrelated_existing_tables(self):
        destination = self.folder / "existing.gpkg"
        with closing(sqlite3.connect(destination)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.execute("INSERT INTO unrelated VALUES ('preserve')")
            connection.commit()
        batch = self.Batch(self.manager(), self.jobs(destination, ("new_data",)), self.Format.GEOPACKAGE, "utf-8", True)
        batch.start()
        self.scheduler.drain()
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0], "preserve")

    def test_cancel_before_writer_completion_preserves_previous_file(self):
        destination = self.folder / "delivery.geojson"
        destination.write_bytes(b"previous file")
        batch = self.Batch(self.manager(), self.jobs(destination, ("first",)), self.Format.GEOJSON, "utf-8")
        results = []
        batch.finished.connect(results.append)
        batch.start()
        batch.cancel()
        self.scheduler.drain()
        self.assertEqual(results[0]["status"], "cancelled")
        self.assertEqual(destination.read_bytes(), b"previous file")

    def test_external_destination_change_is_not_overwritten(self):
        destination = self.folder / "delivery.geojson"
        destination.write_bytes(b"previous")
        batch = self.Batch(self.manager(), self.jobs(destination, ("first",)), self.Format.GEOJSON, "utf-8")
        results = []
        batch.finished.connect(results.append)
        batch.start()
        destination.write_bytes(b"external update")
        self.scheduler.drain()
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(destination.read_bytes(), b"external update")

    def test_group_install_failure_restores_original_sidecars(self):
        destination = self.folder / "delivery.shp"
        destination.write_bytes(b"old shp")
        destination.with_suffix(".dbf").write_bytes(b"old dbf")
        stage_dir = Path(tempfile.mkdtemp(prefix=".transformer-", dir=self.folder))
        (stage_dir / "delivery.shp").write_bytes(b"new shp")
        (stage_dir / "delivery.dbf").write_bytes(b"new dbf")
        (stage_dir / "delivery.shx").write_bytes(b"new shx")
        batch = self.Batch(self.manager(), [], self.Format.SHAPEFILE, "utf-8")
        batch.groups = [{"destination": destination, "directory": stage_dir, "stage": stage_dir / destination.name,
                         "before": batch._fingerprint(destination), "tables": []}]
        real_replace = os.replace
        def fail_once(source, target):
            if Path(source).parent == stage_dir and Path(source).suffix == ".dbf":
                raise OSError("Synthetic installation failure")
            return real_replace(source, target)
        with patch.object(os, "replace", fail_once):
            result = batch._install_files(Task())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(destination.read_bytes(), b"old shp")
        self.assertEqual(destination.with_suffix(".dbf").read_bytes(), b"old dbf")

    def test_encoding_selection_and_dependencies_are_passed_to_native_task(self):
        destination = self.folder / "selection.shp"
        job = self.jobs(destination, ("first",))[0]
        job["selected"] = True
        batch = self.Batch(self.manager(), [job], self.Format.SHAPEFILE, "cp1252")
        batch.start()
        writer = batch.writer_tasks[0]
        self.assertEqual(writer.options.fileEncoding, "cp1252")
        self.assertTrue(writer.options.onlySelectedFeatures)
        self.assertEqual(writer.options.layerOptions, ["ENCODING=cp1252"])
        self.assertEqual(writer.dependencies, [job["layer"]])
        batch.cancel()
        self.scheduler.drain()

    def test_empty_selection_is_refused_and_names_stay_in_destination(self):
        widget = self.namespace["ExportWidget"]
        with self.assertRaises(ValueError):
            widget._export_job(Layer("demo", selected=0), str(self.folder / "out.shp"), True)
        self.assertEqual(widget._safe_file_name("../bad\\folder\x00"), "_bad_folder_")
        self.assertEqual(widget._safe_file_name("CON"), "couche_CON")

    def test_duplicate_error_signals_emit_one_receipt(self):
        destination = self.folder / "delivery.geojson"
        batch = self.Batch(self.manager(), self.jobs(destination, ("first",)), self.Format.GEOJSON, "utf-8")
        results = []
        batch.finished.connect(results.append)
        batch.start()
        task = batch.writer_tasks[0]
        task.errorOccurred.emit(1, "Synthetic writer error")
        task.taskTerminated.emit()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")

    def checked_batch(self, fields, records=(), encoding="utf-8", selected=False):
        destination = self.folder / "previous.shp"
        destination.write_bytes(b"previous geometry")
        destination.with_suffix(".dbf").write_bytes(b"previous attributes")
        layer = Layer("parcelles", count=len(records), fields=fields, records=records)
        job = self.namespace["ExportWidget"]._export_job(layer, str(destination), selected)
        batch = self.Batch(self.manager(), [job], self.Format.SHAPEFILE, encoding)
        results = []
        batch.finished.connect(results.append)
        batch.start()
        return batch, results, destination

    def assert_refused_without_writing(self, results, destination, codes):
        self.scheduler.drain()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")
        self.assertTrue(set(codes).issubset({issue["code"] for issue in results[0]["preflight_issues"]}), results)
        self.assertEqual(destination.read_bytes(), b"previous geometry")
        self.assertEqual(destination.with_suffix(".dbf").read_bytes(), b"previous attributes")
        self.assertFalse(list(self.folder.glob(".transformer-*")))
        self.assertEqual(self.scheduler.tasks, [])
        self.assertIn("parcelles", results[0]["errors"][0])

    def test_dbf_names_collision_and_declared_width_are_refused_before_staging(self):
        with patch.object(self.namespace["Path"], "mkdir", side_effect=AssertionError("Aucun staging avant validation")):
            batch, results, destination = self.checked_batch([
                Field("abcdefghijX", length=255), Field("ABCDEFGHIJY"),
            ])
            self.assert_refused_without_writing(results, destination, {"field_name", "name_collision", "field_width"})
        self.assertTrue(batch.closed)
        self.assertIn("GeoPackage", " ".join(results[0]["errors"]))

    def test_dbf_name_limit_uses_encoded_bytes_and_driver_normalization(self):
        check = self.namespace["ExportPreflight"](
            Layer("parcelles", fields=[Field("éééééé"), Field("code:"), Field("code_"), Field("trailing\t")]),
            self.Format.SHAPEFILE, "utf-8", "ESRI Shapefile",
        )
        self.assertEqual(sum(item["code"] == "field_name" for item in check.issues), 3)
        self.assertTrue(any(item["code"] == "name_collision" for item in check.issues))

    def test_incompatible_field_types_are_refused_without_implicit_conversion(self):
        for kind in ("QTime", "QDateTime", "QStringList", "QVariantList", "QByteArray"):
            with self.subTest(kind=kind):
                _, results, destination = self.checked_batch([Field("valeur", kind)])
                self.assert_refused_without_writing(results, destination, {"unsupported_type"})

    def test_text_byte_limit_and_invalid_encoding_preserve_previous_files(self):
        for encoding, value, code in (("utf-8", "é" * 128, "text_value"),
                                      ("cp1252", "terrain طريق", "value_encoding"),
                                      ("utf-8", "a\0b", "text_value")):
            with self.subTest(encoding=encoding, code=code):
                batch, results, destination = self.checked_batch([Field("libelle")], [(value,)], encoding)
                self.assertEqual(len(self.scheduler.tasks), 1)
                self.assertIsInstance(self.scheduler.tasks[0], self.namespace["ExportFileTask"])
                self.assertFalse(list(self.folder.glob(".transformer-*")))
                source = batch.preflights[0].source
                self.assert_refused_without_writing(results, destination, {code})
                self.assertTrue(source.iterator.closed)

    def test_utf16_is_refused_for_dbf_before_any_task(self):
        _, results, destination = self.checked_batch([Field("code")], [("demo",)], "utf-16")
        self.assert_refused_without_writing(results, destination, {"encoding"})

    def test_decimal_rounding_and_overflow_are_refused_before_writing(self):
        for value in (1.234, 123456.0, float("inf")):
            with self.subTest(value=value):
                _, results, destination = self.checked_batch([Field("montant", "Double", 6, 2)], [(value,)])
                self.assert_refused_without_writing(results, destination, {"numeric_value"})

    def test_valid_dbf_selected_values_use_main_thread_snapshot_and_close_iterator(self):
        layer = Layer("parcelles", fields=[Field("libelle", length=12), Field("montant", "Double", 6, 2)],
                      records=[("é" * 127, 1.25), ("é" * 128, 1.234)])
        check = self.namespace["ExportPreflight"](layer, self.Format.SHAPEFILE, "utf-8", "ESRI Shapefile", True)
        layer.records[0] = ("bad\0value", 99999999)
        self.assertEqual(check.check(), [])
        self.assertTrue(check.source.iterator.closed)
        self.assertEqual(check.request.fids, [0])

    def test_preflight_can_be_cancelled_without_creating_staging(self):
        batch, results, destination = self.checked_batch([Field("code")], [("demo",)])
        source = batch.preflights[0].source
        batch.cancel()
        self.scheduler.drain()
        self.assertEqual(results[0]["status"], "cancelled")
        self.assertFalse(list(self.folder.glob(".transformer-*")))
        self.assertEqual(destination.read_bytes(), b"previous geometry")
        self.assertIsNone(source.iterator)

    def test_other_formats_use_driver_types_without_dbf_limits(self):
        metadata = {"DMD_CREATIONFIELDDATATYPES": "String Integer Real Date DateTime"}
        self.namespace["ogr"] = types.SimpleNamespace(GetDriverByName=lambda name: types.SimpleNamespace(GetMetadata=lambda: metadata))
        layer = Layer("parcelles", fields=[Field("a very long field name", length=4000), Field("entier64", "LongLong")])
        check = self.namespace["ExportPreflight"](layer, self.Format.KML, "utf-8", "KML")
        self.assertEqual([item["code"] for item in check.issues], ["unsupported_type"])
        self.assertEqual(check.issues[0]["field"], "entier64")

    def test_geopackage_complex_conversion_requires_explicit_representation(self):
        layer = Layer("parcelles", fields=[Field("details", "QStringList")])
        check = self.namespace["ExportPreflight"](layer, self.Format.GEOPACKAGE, "utf-8", "GPKG")
        self.assertEqual(check.issues[0]["code"], "type_conversion")

    def test_tab_fixed_width_is_checked_in_bytes_without_dbf_name_limit(self):
        layer = Layer("parcelles", fields=[Field("description_longue", length=5)], records=[("été",)])
        check = self.namespace["ExportPreflight"](layer, self.Format.TAB, "utf-8", "MapInfo File")
        self.assertEqual(check.check(), [])  # Five bytes exactly.
        layer.records = [("été!",)]
        check = self.namespace["ExportPreflight"](layer, self.Format.TAB, "utf-8", "MapInfo File")
        self.assertEqual(check.check()[0]["code"], "text_value")
        layer.schema = [Field("a" * 32)]
        check = self.namespace["ExportPreflight"](layer, self.Format.TAB, "utf-8", "MapInfo File")
        self.assertEqual(check.issues[0]["code"], "field_name")

    def test_dxf_custom_attributes_and_gml_renamed_fields_are_refused(self):
        layer = Layer("parcelles", fields=[Field("code_metier")])
        check = self.namespace["ExportPreflight"](layer, self.Format.DXF, "utf-8", "DXF")
        self.assertEqual(check.issues[0]["code"], "unsupported_field")
        layer.schema = [Field("code metier")]
        check = self.namespace["ExportPreflight"](layer, self.Format.GML, "utf-8", "GML")
        self.assertEqual(check.issues[0]["code"], "field_name")

    def test_format_options_keep_text_json_strings_and_tab_encoding_explicit(self):
        manager = self.namespace["ExportManager"].__new__(self.namespace["ExportManager"])
        options = types.SimpleNamespace(fileEncoding="cp1252")
        manager._configure_format_options(self.Format.TAB, options, Layer("demo"))
        self.assertEqual(options.layerOptions, ["ENCODING=CP1252"])
        manager._configure_format_options(self.Format.GEOJSON, options, Layer("demo"))
        self.assertIn("AUTODETECT_JSON_STRINGS=NO", options.layerOptions)

    def overwrite_fixture(self, destination, export_format):
        prompts = []
        self.namespace.update({
            "QFileDialog": types.SimpleNamespace(getSaveFileName=lambda *args: (str(destination.with_suffix("")), "")),
            "QMessageBox": types.SimpleNamespace(question=lambda *args: (prompts.append(args[2]), 2)[1]),
            "MsgBoxYes": 1, "MsgBoxNo": 2,
        })
        widget = self.namespace["ExportWidget"].__new__(self.namespace["ExportWidget"])
        widget.format_combo = types.SimpleNamespace(currentData=lambda: export_format)
        extension = ".gpkg" if export_format == self.Format.GEOPACKAGE else ".geojson"
        widget.export_manager = types.SimpleNamespace(format_extensions={export_format: extension})
        widget._use_single_geopackage_export = lambda: True
        self.namespace["ExportBatch"] = lambda *args: self.fail("L'écrasement refusé ne doit pas démarrer de lot.")
        return widget, prompts

    def test_final_single_file_name_is_confirmed_after_extension_is_added(self):
        destination = self.folder / "delivery.geojson"
        destination.write_bytes(b"previous data")
        widget, prompts = self.overwrite_fixture(destination, self.Format.GEOJSON)
        widget._export_single_layer_file(Layer("delivery"))
        self.assertEqual(len(prompts), 1)
        self.assertIn("delivery.geojson", prompts[0])
        self.assertEqual(destination.read_bytes(), b"previous data")
        self.assertFalse(list(self.folder.glob(".transformer-*")))

    def test_final_shared_package_name_is_confirmed_once_after_extension_is_added(self):
        destination = self.folder / "delivery.gpkg"
        destination.write_bytes(b"previous package")
        widget, prompts = self.overwrite_fixture(destination, self.Format.GEOPACKAGE)
        widget._export_multiple_layers([Layer("first"), Layer("second")])
        self.assertEqual(len(prompts), 1)
        self.assertIn("1 fichier(s)", prompts[0])
        self.assertIn("delivery.gpkg", prompts[0])
        self.assertEqual(destination.read_bytes(), b"previous package")
        self.assertFalse(list(self.folder.glob(".transformer-*")))


@unittest.skipUnless(NATIVE_QGIS, "Nécessite une QgsApplication déjà initialisée par le runner natif.")
class NativeExportTests(unittest.TestCase):
    """Real QGIS writers, all destinations inside a dedicated temp directory."""

    def setUp(self):
        if str(ROOT.parent) not in sys.path:
            sys.path.insert(0, str(ROOT.parent))
        self.module = importlib.import_module(ROOT.name + ".export.export_module")
        self.manager = self.module.ExportManager()
        self.temp = tempfile.TemporaryDirectory(prefix="transformer-native-export-")
        self.folder = Path(self.temp.name)
        self.layers = []
        self.opened = []
        self.batches = []

    def tearDown(self):
        from qgis.core import QgsProject
        from qgis.PyQt import sip
        from qgis.PyQt.QtCore import QCoreApplication, QEvent
        import gc

        for batch in self.batches:
            if not batch.closed:
                batch.cancel()
            batch.writer_tasks.clear()
            batch.jobs.clear()
            batch.active_task = None
            batch.deleteLater()
        self.batches.clear()
        for layer in self.opened:
            if not sip.isdeleted(layer):
                self._release_reader(layer)
        self.opened.clear()
        for layer in self.layers:
            if not sip.isdeleted(layer):
                QgsProject.instance().removeMapLayer(layer.id())
                if not sip.isdeleted(layer):
                    sip.delete(layer)
        self.layers.clear()
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
        self.temp.cleanup()

    def make_layer(self, name, records=None, text_length=80):
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject
        from qgis.PyQt.QtCore import QMetaType
        records = records if records is not None else [("Été", 7), ("Forêt", 11), ("Zéro", 0)]
        layer = QgsVectorLayer("Point?crs=EPSG:2154", name, "memory")
        layer.dataProvider().addAttributes([
            QgsField("code", QMetaType.Type.QString, len=text_length), QgsField("nombre", QMetaType.Type.Int),
        ])
        layer.updateFields()
        features = []
        for index, record in enumerate(records):
            feature = QgsFeature(layer.fields())
            feature.setAttributes(list(record))
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(650000 + index, 6860000 + index)))
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self.layers.append(layer)
        return layer

    def run_batch(self, jobs, export_format, single_package=False, encoding="utf-8", expected_status="success"):
        from qgis.PyQt.QtCore import QEventLoop, QTimer
        batch = self.module.ExportBatch(self.manager, jobs, export_format, encoding, single_package)
        self.batches.append(batch)
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        results = []
        batch.finished.connect(lambda result: (results.append(result), loop.quit()))
        timer.timeout.connect(loop.quit)
        timer.start(20000)
        QTimer.singleShot(0, batch.start)
        loop.exec()
        timer.stop()
        self.assertTrue(results, "La file d'export n'a pas terminé en 20 secondes.")
        self.assertEqual(results[0]["status"], expected_status, results[0])
        return results[0]

    def read_records(self, path, table=None):
        from qgis.core import QgsVectorLayer
        uri = str(path) + ("|layername=" + table if table else "")
        layer = QgsVectorLayer(uri, "vérification", "ogr")
        self.opened.append(layer)
        iterator = None
        try:
            self.assertTrue(layer.isValid(), uri)
            iterator = layer.getFeatures()
            return [(feature["code"], feature["nombre"]) for feature in iterator]
        finally:
            if iterator is not None:
                iterator.close()
            self._release_reader(layer)

    @staticmethod
    def _release_reader(layer):
        from qgis.PyQt import sip

        provider = layer.dataProvider()
        if provider is not None:
            # OGR keeps an idle connection pool after the feature iterator and
            # Python layer wrapper are released. Invalidate this scratch source
            # explicitly before deleting the C++ provider on Windows.
            source = layer.source()
            provider.invalidateConnections(source)
            provider.invalidateConnections(source.split("|", 1)[0])
        sip.delete(layer)

    def test_shared_geopackage_keeps_existing_table_and_both_new_layers(self):
        from qgis.core import QgsVectorFileWriter, QgsProject
        destination = self.folder / "shared.gpkg"
        reference = self.make_layer("reference", [("À conserver", 1)])
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "reference"
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            reference, str(destination), QgsProject.instance().transformContext(), options,
        )
        self.assertEqual(result[0], self.module.WriterNoError)
        first = self.make_layer("first_delivery", [("Été", 7), ("Forêt", 11)])
        second = self.make_layer("second_delivery", [("Zéro", 0)])
        jobs = [self.module.ExportWidget._export_job(layer, str(destination)) for layer in (first, second)]
        self.run_batch(jobs, self.module.ExportFormat.GEOPACKAGE, True)
        self.assertEqual(self.read_records(destination, "reference"), [("À conserver", 1)])
        self.assertEqual(self.read_records(destination, "first_delivery"), [("Été", 7), ("Forêt", 11)])
        self.assertEqual(self.read_records(destination, "second_delivery"), [("Zéro", 0)])

    def test_selected_geojson_preserves_only_the_selected_record(self):
        layer = self.make_layer("selection")
        first_id = next(layer.getFeatures()).id()
        layer.selectByIds([first_id])
        destination = self.folder / "selection.geojson"
        job = self.module.ExportWidget._export_job(layer, str(destination), True)
        receipt = self.run_batch([job], self.module.ExportFormat.GEOJSON)
        self.assertEqual(receipt["features"], 1)
        self.assertEqual(self.read_records(destination), [("Été", 7)])

    def test_csv_and_type_sidecar_round_trip_accents_and_integers(self):
        layer = self.make_layer("csv")
        destination = self.folder / "delivery.csv"
        job = self.module.ExportWidget._export_job(layer, str(destination))
        receipt = self.run_batch([job], self.module.ExportFormat.CSV)
        self.assertTrue(destination.with_suffix(".csvt").is_file())
        self.assertFalse(receipt["atomic"])
        self.assertEqual(self.read_records(destination), [("Été", 7), ("Forêt", 11), ("Zéro", 0)])

    def test_shapefile_components_round_trip_with_selected_encoding(self):
        layer = self.make_layer("shapefile")
        destination = self.folder / "delivery.shp"
        job = self.module.ExportWidget._export_job(layer, str(destination))
        self.run_batch([job], self.module.ExportFormat.SHAPEFILE, encoding="cp1252")
        for suffix in (".shp", ".shx", ".dbf"):
            self.assertTrue(destination.with_suffix(suffix).is_file())
        self.assertEqual(self.read_records(destination), [("Été", 7), ("Forêt", 11), ("Zéro", 0)])

    def test_shapefile_declared_width_255_is_refused_before_any_file(self):
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QMetaType
        layer = self.make_layer("largeur")
        layer.dataProvider().addAttributes([QgsField("libelle", QMetaType.Type.QString, len=255)])
        layer.updateFields()
        destination = self.folder / "blocked.shp"
        job = self.module.ExportWidget._export_job(layer, str(destination))
        receipt = self.run_batch([job], self.module.ExportFormat.SHAPEFILE, expected_status="failed")
        self.assertTrue(any(issue["code"] == "field_width" for issue in receipt["preflight_issues"]))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_shapefile_oversized_utf8_text_is_refused_with_existing_destination_intact(self):
        layer = self.make_layer("octets", [("é" * 128, 7)], text_length=0)
        destination = self.folder / "blocked.shp"
        destination.write_bytes(b"previous geometry")
        destination.with_suffix(".dbf").write_bytes(b"previous attributes")
        job = self.module.ExportWidget._export_job(layer, str(destination))
        receipt = self.run_batch([job], self.module.ExportFormat.SHAPEFILE, expected_status="failed")
        self.assertTrue(any(issue["code"] == "text_value" for issue in receipt["preflight_issues"]))
        self.assertEqual(destination.read_bytes(), b"previous geometry")
        self.assertEqual(destination.with_suffix(".dbf").read_bytes(), b"previous attributes")
        self.assertFalse(list(self.folder.glob(".transformer-*")))

    def test_shapefile_selection_ignores_invalid_text_outside_selection(self):
        layer = self.make_layer("selection", [("Été", 7), ("é" * 128, 11)], text_length=0)
        first_id = next(layer.getFeatures()).id()
        layer.selectByIds([first_id])
        destination = self.folder / "selected.shp"
        job = self.module.ExportWidget._export_job(layer, str(destination), True)
        self.run_batch([job], self.module.ExportFormat.SHAPEFILE)
        self.assertEqual(self.read_records(destination), [("Été", 7)])

    def test_geojson_preserves_json_looking_text_as_string(self):
        layer = self.make_layer("texte_json", [('["Été", 7]', 7)])
        destination = self.folder / "literal.geojson"
        job = self.module.ExportWidget._export_job(layer, str(destination))
        self.run_batch([job], self.module.ExportFormat.GEOJSON)
        self.assertEqual(self.read_records(destination), [('["Été", 7]', 7)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
