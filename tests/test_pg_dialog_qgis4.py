# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Réception des dialogues PostgreSQL Qt6, sur destinations fictives.

Exécution réservée au runner isolé tests/run_qgis4.py. Aucun serveur, aucun
profil métier et aucune écriture de publication ne sont utilisés.
"""

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QPoint, QSignalBlocker, Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QDialog, QLabel, QLineEdit, QMessageBox, QScrollArea

from Transfomer.pg.postgresql_integration import (
    IntegrationConfirmationDialog,
    PostgreSQLConfigWidget,
    PostgreSQLMappingWidget,
)


@unittest.skipUnless(QgsApplication.instance(), "Lancer avec tests/run_qgis4.py dans QGIS4")
class PostgreSQLDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.widgets = []
        self.analysis = [{
            "layer": "Source métier non traduite",
            "layer_id": "source-fictive",
            "schema": "Production_CASE",
            "table": "Target_Table",
            "requires_creation": False,
            "geometry_compatible": True,
            "crs_compatible": True,
            "source_fields": [
                {"name": "source_code", "type": "text"},
                {"name": "source_value", "type": "integer"},
            ],
            "dest_fields": [
                {"name": "Target_Code", "type": "text"},
                {"name": "Target_Value", "type": "integer"},
                {"name": "Alternative_Code", "type": "text"},
            ],
            "field_matches": {
                "source_code": "Target_Code",
                "source_value": "Target_Value",
            },
        }]

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QgsApplication.processEvents()

    def dialog(self):
        dialog = IntegrationConfirmationDialog(copy.deepcopy(self.analysis), ["Production_CASE"])
        self.widgets.append(dialog)
        return dialog

    def table(self, dialog):
        return next(iter(dialog.mapping_widgets.values()))["table"]

    def config(self):
        root = Path(self.temp.name)
        with patch.object(PostgreSQLConfigWidget, "_connections_path", return_value=str(root / "connections.json")), \
                patch.object(PostgreSQLConfigWidget, "_legacy_path", return_value=str(root / "absent-legacy.json")), \
                patch.object(PostgreSQLConfigWidget, "auto_test_connection", return_value=None):
            widget = PostgreSQLConfigWidget()
        widget._config_dir = str(root)
        self.widgets.append(widget)
        return widget

    def discovery_widget(self):
        with patch.object(PostgreSQLMappingWidget, "auto_load_existing_mappings", return_value=None):
            widget = PostgreSQLMappingWidget()
        self.widgets.append(widget)
        widget.config_widget = self.config()
        widget.config_widget.host_edit.setText("hote-fictif")
        widget.config_widget.database_edit.setText("base-fictive")
        widget.config_widget.username_edit.setText("lecteur-fictif")
        widget.config_widget.password_edit.setText("secret-fictif-uniquement")
        params = {
            "host": "hote-fictif", "port": 5432, "database": "base-fictive",
            "user": "lecteur-fictif", "password": "secret-fictif-uniquement",
        }
        widget.available_schemas = ["Production_CASE"]
        widget.available_tables = {"Production_CASE": ["Preserved_Table"]}
        row = widget._insert_saved_destination("Source métier non traduite", "Production_CASE", "Target_Table")
        return widget, params, row

    def discovery_task(self, params, cancelled=False):
        return SimpleNamespace(
            conn_params=dict(params), isCanceled=lambda: cancelled, error="",
            schemas=["Unwanted_Schema"], tables_by_schema={"Production_CASE": ["Unwanted_Table"]},
            elapsed_ms=1,
        )

    def test_initial_plan_preserves_identifiers_and_defaults_to_append(self):
        dialog = self.dialog()
        self.assertEqual(dialog.get_selected_export_mode(), "append")
        plan = dialog.get_execution_plans()[0]
        self.assertEqual((plan["layer"], plan["schema"], plan["table"]),
                         (self.analysis[0]["layer"], "Production_CASE", "Target_Table"))
        self.assertEqual(plan["field_mapping"], [
            {"source": "source_code", "target": "Target_Code", "type": ""},
            {"source": "source_value", "target": "Target_Value", "type": ""},
        ])
        self.assertNotIn("confirmed", self.analysis[0])

    def test_replace_warning_follows_selected_mode(self):
        dialog = self.dialog()
        dialog.show()
        QgsApplication.processEvents()
        self.assertFalse(dialog.warning_label.isVisible())
        dialog.replace_mode.click()
        self.assertEqual(dialog.get_selected_export_mode(), "replace")
        self.assertTrue(dialog.warning_label.isVisible())
        self.assertTrue(dialog.warning_label.text().strip())
        dialog.append_mode.click()
        self.assertEqual(dialog.get_selected_export_mode(), "append")
        self.assertFalse(dialog.warning_label.isVisible())

    def test_mapping_choices_and_conversion_are_in_execution_plan(self):
        dialog = self.dialog()
        table = self.table(dialog)
        destination = table.cellWidget(0, 2)
        destination.setCurrentIndex(destination.findData("Alternative_Code"))
        conversion = table.cellWidget(0, 4)
        conversion.setCurrentText("character varying")
        plan = dialog.get_execution_plans()[0]
        self.assertEqual(plan["field_mapping"][0], {
            "source": "source_code", "target": "Alternative_Code", "type": "character varying",
        })
        self.assertEqual(self.analysis[0]["field_matches"]["source_code"], "Target_Code")

    def test_duplicate_target_requires_correction(self):
        dialog = self.dialog()
        destination = self.table(dialog).cellWidget(1, 2)
        destination.setCurrentIndex(destination.findData("Target_Code"))
        with self.assertRaisesRegex(ValueError, "plusieurs sources"):
            dialog.get_execution_plans()

    def test_clearing_requires_a_mapping_and_reset_restores_it(self):
        dialog = self.dialog()
        dialog.clear_btn.click()
        with self.assertRaisesRegex(ValueError, "correspondance"):
            dialog.get_execution_plans()
        dialog.reset_btn.click()
        self.assertEqual(len(dialog.get_execution_plans()[0]["field_mapping"]), 2)

    def test_escape_cancels_without_accepting(self):
        dialog = self.dialog()
        accepted = []
        rejected = []
        dialog.accepted.connect(lambda: accepted.append(True))
        dialog.rejected.connect(lambda: rejected.append(True))
        dialog.show()
        QgsApplication.processEvents()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(accepted, [])
        self.assertEqual(rejected, [True])
        self.assertNotIn("confirmed", dialog.compatibility_info[0])

    def test_confirmation_cannot_be_disabled_and_mapping_controls_are_named(self):
        dialog = self.dialog()
        dialog.show()
        QgsApplication.processEvents()
        self.assertFalse(dialog.dont_show_checkbox.isVisible())
        self.assertFalse(dialog.dont_show_checkbox.isChecked())
        self.assertFalse(dialog.dont_show_again)
        for widget in (dialog.tabs, self.table(dialog), dialog.proceed_btn, dialog.cancel_btn,
                       self.table(dialog).cellWidget(0, 2), self.table(dialog).cellWidget(0, 4)):
            self.assertTrue(widget.accessibleName().strip(), type(widget).__name__)

    def test_compact_dialog_keeps_actions_visible_with_enlarged_font(self):
        dialog = self.dialog()
        enlarged_font = QFont(dialog.font())
        enlarged_font.setPointSize(16)
        dialog.setFont(enlarged_font)
        dialog.resize(1000, 620)
        dialog.show()
        QgsApplication.processEvents()
        self.assertLessEqual(dialog.width(), 1024)
        self.assertLessEqual(dialog.height(), 700)
        scroll_areas = dialog.findChildren(QScrollArea)
        self.assertTrue(scroll_areas, "Le contenu doit défiler quand la police grandit")
        for button in (dialog.cancel_btn, dialog.proceed_btn):
            self.assertTrue(button.isVisible())
            top_left = button.mapTo(dialog, QPoint(0, 0))
            bottom_right = button.mapTo(dialog, button.rect().bottomRight())
            self.assertTrue(dialog.rect().contains(top_left), button.text())
            self.assertTrue(dialog.rect().contains(bottom_right), button.text())
        self.assertFalse(any(scroll.isAncestorOf(dialog.proceed_btn) for scroll in scroll_areas))

    def test_connection_form_has_buddies_and_masks_session_password(self):
        widget = self.config()
        widget.password_edit.setText("secret-fictif-uniquement")
        self.assertEqual(widget.password_edit.echoMode(), QLineEdit.EchoMode.Password)
        labels = widget.findChildren(QLabel)
        for control in (widget.host_edit, widget.port_edit, widget.database_edit,
                        widget.username_edit, widget.password_edit):
            self.assertTrue(control.accessibleName().strip(), type(control).__name__)
            self.assertTrue(any(label.buddy() is control for label in labels), control.accessibleName())
        self.assertFalse((Path(self.temp.name) / "connections.json").exists())
        widget.update_status("connected")
        self.assertNotIn("Connection", widget.status_label.text())
        self.assertTrue(widget.status_label.text().strip())

    def test_connection_callback_ignores_obsolete_and_cancelled_results(self):
        widget = self.config()
        old_task = SimpleNamespace(success=True, isCanceled=lambda: False, message="", elapsed_ms=1)
        current_task = SimpleNamespace(success=True, isCanceled=lambda: True, message="", elapsed_ms=2)
        widget._active_conn_task = current_task
        with patch.object(widget, "update_status") as status, \
                patch.object(widget, "trigger_schema_refresh") as refresh, \
                patch("Transfomer.pg.postgresql_integration.log_success") as success, \
                patch("Transfomer.pg.postgresql_integration.log_critical") as failure:
            widget._on_connection_tested(old_task, False, "hote-fictif", 5432, "base-fictive", "lecteur-fictif")
            self.assertIs(widget._active_conn_task, current_task)
            status.assert_not_called()
            refresh.assert_not_called()
            success.assert_not_called()
            failure.assert_not_called()
            widget._on_connection_tested(current_task, False, "hote-fictif", 5432, "base-fictive", "lecteur-fictif")
            self.assertIsNone(widget._active_conn_task)
            status.assert_not_called()
            refresh.assert_not_called()
            success.assert_not_called()
            failure.assert_not_called()

    def test_consequences_name_destination_and_describe_append_replace_and_creation(self):
        dialog = self.dialog()
        destination = "Production_CASE.Target_Table"
        self.assertIn(destination, dialog.consequences_label.text())
        self.assertIn("conserver", dialog.consequences_label.text().lower())
        dialog.replace_mode.click()
        self.assertIn(destination, dialog.consequences_label.text())
        self.assertIn("supprimer", dialog.consequences_label.text().lower())
        creation_analysis = copy.deepcopy(self.analysis)
        creation_analysis[0]["requires_creation"] = True
        creation_dialog = IntegrationConfirmationDialog(creation_analysis, ["Production_CASE"])
        self.widgets.append(creation_dialog)
        self.assertIn(destination, creation_dialog.consequences_label.text())
        self.assertIn("créer", creation_dialog.consequences_label.text().lower())
        self.assertFalse(self.analysis[0]["requires_creation"])

    def test_publish_keeps_invalid_mapping_open_then_accepts_corrected_plan(self):
        dialog = self.dialog()
        dialog.show()
        QgsApplication.processEvents()
        destination = self.table(dialog).cellWidget(1, 2)
        destination.setCurrentIndex(destination.findData("Target_Code"))
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(True))
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok) as warning:
            dialog.proceed_btn.click()
            warning.assert_called_once()
            self.assertTrue(dialog.isVisible())
            self.assertEqual(accepted, [])
            destination.setCurrentIndex(destination.findData("Target_Value"))
            dialog.proceed_btn.click()
            self.assertEqual(warning.call_count, 1)
        self.assertEqual(accepted, [True])
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(dialog.isVisible())

    def test_saved_destination_is_executable_even_when_schema_is_not_cached(self):
        with patch.object(PostgreSQLMappingWidget, "auto_load_existing_mappings", return_value=None):
            widget = PostgreSQLMappingWidget()
        self.widgets.append(widget)
        self.assertIsNone(widget.config_widget)
        self.assertEqual(widget.available_schemas, [])
        self.assertEqual(widget.available_tables, {})
        row = widget._insert_saved_destination(
            "Source métier non traduite", "Production_CASE", "Target_Table",
        )
        self.assertEqual(widget.get_current_mappings(), [{
            "transformed": "Source métier non traduite",
            "schema": "Production_CASE",
            "table": "Target_Table",
        }])
        for column in range(3):
            self.assertTrue(widget.mapping_table.cellWidget(row, column).accessibleName().strip())
        self.assertIsNone(widget._active_conn_task)
        self.assertIsNone(widget._active_schema_task)
        self.assertIsNone(widget._active_table_task)

    def test_discovery_obsolete_callbacks_preserve_newer_tasks_and_existing_cache(self):
        widget, params, row = self.discovery_widget()
        old_task = self.discovery_task(params)
        current_task = self.discovery_task(params)
        schemas_before = list(widget.available_schemas)
        tables_before = copy.deepcopy(widget.available_tables)
        target = widget.mapping_table.cellWidget(row, 2)
        choices_before = [target.itemText(index) for index in range(target.count())]
        widget._active_schema_task = current_task
        widget._on_schemas_discovered(old_task, params)
        self.assertIs(widget._active_schema_task, current_task)
        widget._active_table_task = current_task
        widget._on_tables_discovered(old_task, "Production_CASE", target)
        self.assertIs(widget._active_table_task, current_task)
        self.assertEqual(widget.available_schemas, schemas_before)
        self.assertEqual(widget.available_tables, tables_before)
        self.assertEqual([target.itemText(index) for index in range(target.count())], choices_before)

    def test_discovery_cancelled_or_changed_connection_callbacks_do_not_mutate_cache(self):
        for changed_connection in (False, True):
            with self.subTest(changed_connection=changed_connection):
                widget, params, row = self.discovery_widget()
                task = self.discovery_task(params, cancelled=not changed_connection)
                target = widget.mapping_table.cellWidget(row, 2)
                schemas_before = list(widget.available_schemas)
                tables_before = copy.deepcopy(widget.available_tables)
                choices_before = [target.itemText(index) for index in range(target.count())]
                if changed_connection:
                    widget.config_widget.username_edit.setText("autre-lecteur-fictif")
                widget._active_schema_task = task
                widget._on_schemas_discovered(task, params)
                self.assertIsNone(widget._active_schema_task)
                widget._active_table_task = task
                widget._on_tables_discovered(task, "Production_CASE", target)
                self.assertIsNone(widget._active_table_task)
                self.assertEqual(widget.available_schemas, schemas_before)
                self.assertEqual(widget.available_tables, tables_before)
                self.assertEqual([target.itemText(index) for index in range(target.count())], choices_before)

    def test_table_discovery_ignores_changed_schema_and_removed_destination(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                widget, params, row = self.discovery_widget()
                task = self.discovery_task(params)
                target = widget.mapping_table.cellWidget(row, 2)
                tables_before = copy.deepcopy(widget.available_tables)
                choices_before = [target.itemText(index) for index in range(target.count())]
                if removed:
                    widget.mapping_table.removeRow(row)
                else:
                    schema_combo = widget.mapping_table.cellWidget(row, 1)
                    blocker = QSignalBlocker(schema_combo)
                    schema_combo.setCurrentText("Autre_SCHEMA")
                    del blocker
                widget._active_table_task = task
                widget._on_tables_discovered(task, "Production_CASE", target)
                self.assertIsNone(widget._active_table_task)
                self.assertEqual(widget.available_tables, tables_before)
                if removed:
                    self.assertEqual(widget.mapping_table.rowCount(), 0)
                else:
                    self.assertEqual([target.itemText(index) for index in range(target.count())], choices_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
