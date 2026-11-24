# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Resource, performance, concurrency, and multi-plugin coexistence regressions (C7)."""

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from qgis.PyQt.QtCore import QEvent, QPointF
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtWidgets import QApplication, QLabel, QWidget
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from Transfomer.core.config_manager import ConfigManager
from Transfomer.core.transform_task import TransformTask
from Transfomer.core.transformer import SimpleTransformer
from Transfomer.export.export_module import ExportWidget
from Transfomer.pg.postgresql_integration import (
    PostgreSQLConfigWidget,
    PostgreSQLIntegrationWidget,
    PostgreSQLMappingWidget,
)
from Transfomer.processing_provider.common import resolve_postgres_connection_params
from Transfomer.shared import compat
from Transfomer.shared.logger import TransformerLogger
from Transfomer.widgets.expression_tester_dialog import ExpressionTesterDialog
from Transfomer.widgets.fluent import apply_fluent_style
from Transfomer.widgets.log_monitor_widget import LogMonitorWidget


@unittest.skipUnless(QgsApplication.instance() is not None, "Run via tests/run_qgis4.py")
class PerfAndResourceTests(unittest.TestCase):
    """Verify C7 resource caps, lazy refresh while hidden, and fast-path parity."""

    def test_fluent_context_detaches_app_filter_when_hidden(self):
        root = QWidget()
        try:
            QLabel("Probe", root)
            apply_fluent_style(root)
            ctx = root._fluent_context
            self.assertFalse(ctx._app_filter_installed)
            root.show()
            QApplication.processEvents()
            self.assertTrue(ctx._app_filter_installed)
            root.hide()
            QApplication.processEvents()
            self.assertFalse(ctx._app_filter_installed)
            root.setProperty("fluentReducedMotion", True)
            self.assertTrue(ctx.reduced)
            root.show()
            QApplication.processEvents()
            self.assertTrue(ctx._app_filter_installed)
            # MouseMove must not flip keyboard flag on _InputModeFilter
            ctx.keyboard = True
            ev = QMouseEvent(
                compat.EventMouseMove,
                QPointF(5, 5),
                compat.MouseLeftButton,
                compat.MouseLeftButton,
                compat.NoModifier,
            )
            self.assertFalse(ctx._app_filter.eventFilter(root, ev))
            self.assertTrue(ctx.keyboard)
        finally:
            root.close()
            root.deleteLater()
            QApplication.processEvents()

    def test_expression_tester_limits_features_instead_of_full_layer_scan(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=v:integer", "big_probe", "memory")
        feats = []
        for idx in range(600):
            f = QgsFeature(layer.fields())
            f.setAttributes([idx])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(idx * 0.001, 48.0)))
            feats.append(f)
        self.assertTrue(layer.dataProvider().addFeatures(feats)[0])

        seen_requests = []
        orig_get_features = layer.getFeatures

        def spy_get_features(request=None):
            seen_requests.append(request)
            return orig_get_features(request) if request is not None else orig_get_features()

        dlg = ExpressionTesterDialog(layer=layer)
        try:
            dlg.expression_widget.set_expression('"v" * 2')
            with patch.object(layer, "getFeatures", side_effect=spy_get_features):
                dlg.test_expression(sample_size=5)
            self.assertEqual(dlg.results_table.rowCount(), 5)
            self.assertEqual(seen_requests[-1].limit(), 5)

            dlg.test_expression(sample_size=None)
            self.assertEqual(dlg.results_table.rowCount(), ExpressionTesterDialog.MAX_TEST_FEATURES)
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_hidden_export_and_pg_widgets_defer_work_until_shown(self):
        export_w = ExportWidget()
        mapping_w = PostgreSQLMappingWidget()
        try:
            layer = QgsVectorLayer("Point?crs=EPSG:4326&field=a:string", "deferred_probe", "memory")
            QgsProject.instance().addMapLayer(layer)
            try:
                self.assertFalse(export_w.isVisible())
                self.assertFalse(mapping_w.isVisible())
                self.assertTrue(export_w._layers_dirty)
                self.assertTrue(mapping_w._layers_dirty)

                export_w.show()
                mapping_w.show()
                QApplication.processEvents()
                self.assertFalse(export_w._layers_dirty)
                self.assertFalse(mapping_w._layers_dirty)
                self.assertGreaterEqual(export_w.layers_tree.topLevelItemCount(), 1)
            finally:
                QgsProject.instance().removeMapLayer(layer.id())
        finally:
            export_w.teardown_resources()
            export_w.close()
            export_w.deleteLater()
            mapping_w.teardown_qgis_signals()
            mapping_w.close()
            mapping_w.deleteLater()

        cfg_w = PostgreSQLConfigWidget()
        try:
            cfg_w._connections["p"] = cfg_w._normalize_profile(
                {"host": "localhost", "port": 5432, "database": "db", "username": "u", "_session_password": ""}
            )
            cfg_w._active_name = "p"
            cfg_w._apply_active_profile()
            self.assertTrue(cfg_w._pending_auto_test)
            with patch.object(cfg_w, "auto_test_connection") as mock_test:
                cfg_w.show()
                QApplication.processEvents()
                self.assertFalse(cfg_w._pending_auto_test)
                # auto_test_connection is scheduled on QTimer after showEvent
                from qgis.PyQt.QtTest import QTest
                QTest.qWait(300)
                self.assertGreaterEqual(mock_test.call_count, 1)
        finally:
            cfg_w.close()
            cfg_w.deleteLater()

        pg_int = PostgreSQLIntegrationWidget()
        try:
            pg_int.teardown_resources()
        finally:
            pg_int.close()
            pg_int.deleteLater()

    def test_log_monitor_defers_table_rows_while_hidden_and_tears_down(self):
        custom_logger = TransformerLogger()
        monitor = LogMonitorWidget(transformer_logger=custom_logger)
        try:
            custom_logger.info("hidden event message", module="transformer", code="INFO")
            self.assertEqual(monitor.table.rowCount(), 0)
            self.assertTrue(monitor._dirty)
            self.assertGreaterEqual(len(monitor._all_entries), 1)

            monitor.show()
            QApplication.processEvents()
            self.assertFalse(monitor._dirty)
            self.assertGreaterEqual(monitor.table.rowCount(), 1)

            before_count = len(monitor._all_entries)
            monitor.teardown()
            custom_logger.info("after teardown message", module="transformer", code="INFO")
            self.assertEqual(len(monitor._all_entries), before_count)
        finally:
            monitor.close()
            monitor.deleteLater()

    def test_config_manager_caps_recipe_history_at_20(self):
        with tempfile.TemporaryDirectory(prefix="transformer-hist-") as tmpdir:
            mgr = ConfigManager(tmpdir)
            for i in range(25):
                res = mgr.add_table_config(
                    "rec",
                    "src",
                    {"val": f"{i}"},
                    force_replace=True,
                )
                self.assertTrue(res["success"])
            history = mgr.config_data.get("recipe_history", {}).get("rec", [])
            self.assertEqual(len(history), ConfigManager._MAX_RECIPE_HISTORY)
            self.assertEqual(history[0]["calculated_fields"]["val"], "4")
            self.assertEqual(history[-1]["calculated_fields"]["val"], "23")

    def test_resolve_postgres_connection_params_reads_nested_connections_dict(self):
        with tempfile.TemporaryDirectory(prefix="transformer-pg-prof-") as tmpdir:
            pg_dir = Path(tmpdir) / "pg"
            pg_dir.mkdir()
            profile_file = pg_dir / "transformer_postgresql_connections.json"
            profile_file.write_text(
                json.dumps({
                    "active": "prod",
                    "connections": {
                        "prod": {
                            "host": "pg.internal",
                            "port": 5433,
                            "database": "gis",
                            "username": "etl",
                            "authcfg": "",
                        }
                    },
                }),
                encoding="utf-8",
            )
            fake_registry = types.SimpleNamespace(
                providerMetadata=lambda _name: types.SimpleNamespace(findConnection=lambda _n: None)
            )
            with patch(
                "Transfomer.processing_provider.common.QgsProviderRegistry.instance",
                return_value=fake_registry,
            ):
                params = resolve_postgres_connection_params("prod", plugin_dir=tmpdir)
            self.assertEqual(params["host"], "pg.internal")
            self.assertEqual(params["port"], 5433)
            self.assertEqual(params["database"], "gis")
            self.assertEqual(params["user"], "etl")

    def test_fast_path_converter_and_transform_task_progress(self):
        layer = QgsVectorLayer("Point?crs=EPSG:2154&field=lbl:string&field=n:double", "perf_src", "memory")
        feats = []
        for idx in range(5):
            f = QgsFeature(layer.fields())
            f.setAttributes([f"row_{idx}", float(idx) if idx < 4 else 1.5])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(idx, idx)))
            feats.append(f)
        self.assertTrue(layer.dataProvider().addFeatures(feats)[0])

        with tempfile.TemporaryDirectory(prefix="transformer-fast-") as tmpdir:
            mgr = ConfigManager(tmpdir)
            transformer = SimpleTransformer(mgr)
            transformer.batch_size = 2

            # Fractional float -> Integer must still raise strictly
            with self.assertRaises(ValueError):
                transformer.execute_to_sink(
                    source=layer,
                    table_name="strict_probe",
                    calculated_fields={"lbl": '"lbl"', "i": '"n"'},
                    sink_factory=SimpleTransformer.create_memory_sink_factory("strict_probe"),
                    field_definitions={
                        "lbl": {"type": "Text", "length": 20},
                        "i": {"type": "Integer"},
                    },
                    raise_on_error=True,
                )

            # Valid TransformTask emits intermediate progress and preserves recipe without deep-copying history
            mgr.add_table_config(
                "clean_out",
                layer.name(),
                {"lbl": '"lbl"'},
                field_definitions={"lbl": {"type": "Text", "length": 20}},
                source_id=layer.id(),
            )
            mgr.config_data["recipe_history"] = {"clean_out": [{"dummy": 1}] * 10}
            progress_values = []
            task = TransformTask(
                transformer,
                [{"filename": layer.id(), "shapefile_info": {"layer": layer, "name": layer.name()}, "table_names": ["clean_out"]}],
            )
            self.assertNotIn("recipe_history", task._worker_transformer.config_manager.config_data)
            task.progressChanged.connect(progress_values.append)
            self.assertTrue(task.run())
            self.assertTrue(any(0 < p < 100 for p in progress_values), f"Expected intermediate progress, got {progress_values}")


if __name__ == "__main__":
    unittest.main()
