# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Garder la portée, le bilan et l'ouverture explicite avec un moteur C5 retenu."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QComboBox

from Transfomer.export.export_module import ExportFormat, ExportWidget
from Transfomer.ui.delivery_panel import DeliveryPanel


class ExporterRetenu(QObject):
    request_started = pyqtSignal(dict)
    export_finished = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.format_combo = QComboBox()
        for fmt in (ExportFormat.CSV, ExportFormat.GEOPACKAGE):
            self.format_combo.addItem(fmt.value, fmt)
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItem("Windows-1252", "cp1252")
        self.encoding_combo.addItem("UTF-8", "utf-8")
        self.export_manager = SimpleNamespace(format_extensions={ExportFormat.CSV: ".csv", ExportFormat.GEOPACKAGE: ".gpkg"})
        self._export_batch = None
        self.calls = []
        self.decline = False
        self.before_start = None
        self.cancelled = False

    _export_job = staticmethod(ExportWidget._export_job)
    _safe_file_name = staticmethod(ExportWidget._safe_file_name)

    def _start_export_jobs(self, jobs, single_package=False, overwrite_confirmed=False):
        self.calls.append((jobs, single_package, overwrite_confirmed))
        if self.before_start:
            self.before_start()
        if self.decline:
            return
        self._export_batch = SimpleNamespace(closed=False)
        self.request_started.emit({"kind": "file_export", "destinations": [job["path"] for job in jobs],
            "layers": [job["name"] for job in jobs], "selected_only": False})

    def finish(self, **result):
        self._export_batch.closed = True
        self.export_finished.emit(result)

    def cancel_export(self):
        self.cancelled = True


@unittest.skipUnless(QgsApplication.instance(), "Lancer sous tests/run_qgis4.py pour le banc Qt isolé")
class DeliveryGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.before = set(QgsProject.instance().mapLayers())
        self.layer = QgsVectorLayer("Point?crs=EPSG:2154&field=nom:string", "Résultat préparé", "memory")
        feature = QgsFeature(self.layer.fields())
        feature.setAttributes(["Exemple"])
        feature.setGeometry(QgsGeometry.fromWkt("POINT(700000 6600000)"))
        self.layer.dataProvider().addFeatures([feature])
        self.backend = ExporterRetenu()
        self.panel = DeliveryPanel(self.backend)
        self.panel.resize(780, 560)
        self.panel.set_results([self.layer])
        self.panel.show()
        QApplication.processEvents()
        self.path = Path(self.temp.name) / "resultat.gpkg"

    def tearDown(self):
        for layer_id in set(QgsProject.instance().mapLayers()) - self.before:
            QgsProject.instance().removeMapLayer(layer_id)
        self.panel.close()
        self.panel.deleteLater()
        self.backend.format_combo.deleteLater()
        self.backend.encoding_combo.deleteLater()
        self.backend.deleteLater()
        QApplication.processEvents()

    def prepare(self, path=None):
        self.panel.layer_combo.setCurrentIndex(self.panel.layer_combo.findData(self.layer.id()))
        self.panel.path_edit.setText(str(path or self.path))

    def test_result_is_explicit_and_missing_destination_never_starts(self):
        self.assertIsNone(self.panel.layer_combo.currentData())
        self.assertFalse(self.panel.deliver())
        self.assertFalse(self.panel.open_result())
        self.panel.layer_combo.setCurrentIndex(1)
        self.assertFalse(self.panel.deliver())
        self.assertEqual(self.backend.calls, [])
        self.assertFalse(self.panel.open_button.isEnabled())

    def test_declined_replacement_keeps_file_controls_and_stable_status(self):
        self.path.write_bytes(b"copie existante fictive")
        self.prepare()
        self.backend.decline = True
        status_height = self.panel.delivery_status.height()
        self.assertFalse(self.panel.deliver())
        QApplication.processEvents()
        self.assertEqual(self.path.read_bytes(), b"copie existante fictive")
        self.assertFalse(self.backend.calls[0][2])
        self.assertTrue(self.panel.path_edit.isEnabled())
        self.assertFalse(self.panel.cancel_button.isEnabled())
        self.assertFalse(self.panel.open_button.isEnabled())
        self.assertEqual(self.panel.delivery_status.height(), status_height)
        self.assertIn("pas été confirmé", self.panel.delivery_status.text())

    def test_job_uses_chosen_result_full_scope_utf8_and_backend_preflight(self):
        self.prepare()
        self.layer.selectAll()
        self.assertTrue(self.panel.deliver())
        jobs, package, confirmed = self.backend.calls[0]
        self.assertIs(jobs[0]["layer"], self.layer)
        self.assertFalse(jobs[0]["selected"])
        self.assertEqual(jobs[0]["count"], 1)
        self.assertFalse(package)
        self.assertFalse(confirmed)
        self.assertEqual(self.backend.encoding_combo.currentData(), "utf-8")
        self.assertEqual(self.backend.format_combo.currentData(), ExportFormat.GEOPACKAGE)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.panel._progress.maximum(), 0)
        self.assertFalse(self.panel.open_button.isEnabled())

    def test_foreign_started_and_success_signals_cannot_open_another_file(self):
        foreign = str(Path(self.temp.name) / "autre.gpkg")
        self.backend.request_started.emit({"destinations": [foreign]})
        self.backend.export_finished.emit({"status": "success", "outputs": [foreign]})
        self.assertFalse(self.panel.open_button.isEnabled())
        self.prepare()
        self.assertTrue(self.panel.deliver())
        self.backend.request_started.emit({"destinations": [foreign]})
        self.backend.export_finished.emit({"status": "success", "outputs": [foreign]})
        self.assertTrue(self.panel._busy)
        self.assertFalse(self.panel.open_button.isEnabled())
        self.backend.finish(status="failed", outputs=[], errors=["Refus fictif"])
        self.assertFalse(self.panel._busy)

    def test_failure_and_cancellation_remain_distinct_and_never_enable_open(self):
        self.prepare()
        for status, expected in (("failed", "échouée"), ("cancelled", "annulée")):
            with self.subTest(status=status):
                self.assertTrue(self.panel.deliver())
                if status == "cancelled":
                    self.panel.cancel_button.click()
                    self.assertTrue(self.backend.cancelled)
                    self.assertTrue(self.panel._busy)
                    self.assertFalse(self.panel.cancel_button.isEnabled())
                self.backend.finish(status=status, outputs=[], errors=["Contrôle fictif"])
                self.assertIn(expected, self.panel.delivery_status.text())
                self.assertTrue(self.panel.deliver_button.isEnabled())
                self.assertFalse(self.panel.open_button.isEnabled())
                self.assertFalse(self.panel.open_result())

    def test_nested_request_during_confirmation_cannot_start_second_job(self):
        self.prepare()
        nested = []
        self.backend.before_start = lambda: nested.append(self.panel.deliver())
        self.assertTrue(self.panel.deliver())
        self.assertEqual(nested, [False])
        self.assertEqual(len(self.backend.calls), 1)

    def test_new_results_during_delivery_do_not_erase_confirmed_file(self):
        self.prepare()
        self.assertTrue(self.panel.deliver())
        replacement = QgsVectorLayer("None?field=code:string", "Autre résultat", "memory")
        self.panel.set_results([replacement])
        self.backend.finish(status="success", outputs=[str(self.path)], errors=[])
        self.assertTrue(self.panel.open_button.isEnabled())
        self.assertEqual(self.panel._result_path, str(self.path))
        self.assertIn(str(self.path), self.panel.delivery_status.text())

    def test_changed_path_invalidates_success_without_touching_existing_output(self):
        self.prepare()
        self.assertTrue(self.panel.deliver())
        self.backend.finish(status="success", outputs=[str(self.path)], errors=[])
        self.panel.path_edit.setText(str(Path(self.temp.name) / "autre.gpkg"))
        self.assertFalse(self.panel.open_button.isEnabled())
        self.assertFalse(self.panel.open_result())

    def test_only_explicit_open_adds_readable_delivered_file_to_project(self):
        csv = Path(self.temp.name) / "resultat.csv"
        csv.write_text("nom,valeur\nExemple,1\n", encoding="utf-8")
        self.prepare(csv)
        self.panel.format_combo.setCurrentIndex(self.panel.format_combo.findData(ExportFormat.CSV))
        self.assertTrue(self.panel.deliver())
        self.backend.finish(status="success", outputs=[str(csv)], errors=[])
        self.assertEqual(set(QgsProject.instance().mapLayers()), self.before)
        self.assertTrue(self.panel.open_result())
        self.assertEqual(len(set(QgsProject.instance().mapLayers()) - self.before), 1)
        self.assertTrue(self.panel.open_result())
        self.assertEqual(len(set(QgsProject.instance().mapLayers()) - self.before), 1)

    def test_success_with_missing_file_is_not_opened(self):
        self.prepare()
        self.assertTrue(self.panel.deliver())
        self.backend.finish(status="success", outputs=[str(self.path)], errors=[])
        self.assertFalse(self.panel.open_result())
        self.assertEqual(set(QgsProject.instance().mapLayers()), self.before)
        self.assertIn("plus disponible", self.panel.delivery_status.text())

    def test_replay_preserves_recorded_encoding_and_receives_visible_completion(self):
        csv = Path(self.temp.name) / "reprise.csv"
        csv.write_text("nom,valeur\nExemple,1\n", encoding="cp1252")
        destination = {"kind": "file", "path": str(csv), "format": ExportFormat.CSV.value,
                       "encoding": "cp1252", "selected_only": False, "replay": True}
        self.assertTrue(self.panel.replay(self.layer, destination))
        self.assertEqual(self.panel.layer_combo.currentData(), self.layer.id())
        self.assertEqual(self.panel.format_combo.currentData(), ExportFormat.CSV)
        self.assertEqual(self.backend.encoding_combo.currentData(), "cp1252")
        self.assertIn("Windows-1252", self.panel.encoding_label.text())
        self.assertFalse(self.backend.calls[0][2])
        self.assertFalse(self.panel.open_button.isEnabled())
        self.backend.finish(status="success", outputs=[str(csv)], errors=[])
        self.assertTrue(self.panel.open_button.isEnabled())
        self.assertIn(str(csv), self.panel.delivery_status.text())
        self.assertEqual(set(QgsProject.instance().mapLayers()), self.before)
        self.assertTrue(self.panel.open_result())

    def test_replay_unavailable_encoding_or_partial_scope_never_starts(self):
        destination = {"kind": "file", "path": str(self.path), "format": ExportFormat.GEOPACKAGE.value}
        self.assertFalse(self.panel.replay(self.layer, {**destination, "encoding": "absent"}))
        self.assertFalse(self.panel.replay(self.layer, {**destination, "selected_only": True}))
        self.assertEqual(self.backend.calls, [])
        self.assertFalse(self.panel.open_button.isEnabled())

    def test_replay_declined_replacement_does_not_claim_success_and_manual_delivery_uses_utf8(self):
        destination = {"kind": "file", "path": str(self.path), "format": ExportFormat.GEOPACKAGE.value,
                       "encoding": "cp1252"}
        self.backend.decline = True
        self.assertFalse(self.panel.replay(self.layer, destination))
        self.assertFalse(self.panel.open_button.isEnabled())
        self.assertEqual(self.backend.encoding_combo.currentData(), "cp1252")
        self.backend.decline = False
        self.assertTrue(self.panel.deliver())
        self.assertEqual(self.backend.encoding_combo.currentData(), "utf-8")


if __name__ == "__main__":
    unittest.main()
