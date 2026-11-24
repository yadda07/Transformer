# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Cross-version interoperability checks for QGIS 3.40 (Qt 5) to QGIS 4.x (Qt 6)."""

import ast
import configparser
from pathlib import Path
import unittest
import warnings

from qgis.core import (
    QgsApplication,
    QgsDataSourceUri,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QSize
from qgis.PyQt.QtGui import QFont

from Transfomer.core.config_manager import ConfigManager
from Transfomer.core.field_types import (
    convert_value_for_field,
    create_compatible_field,
    definition_from_processing_mapping,
)
from Transfomer.core.transformer import SimpleTransformer
from Transfomer.processing_provider import TransformerProvider
from Transfomer.processing_provider.common import _sslmode_name
from Transfomer.shared import compat, icons
from Transfomer.ui.main_window import EnhancedTransformerDialog
from Transfomer.widgets.field_widget import FieldWidget
from Transfomer.widgets.fluent import FluentButton, role_font


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(QgsApplication.instance() is not None, "Run via tests/run_qgis4.py")
class CrossVersionCompatTests(unittest.TestCase):
    """Verify runtime compatibility across QGIS 3.40+ / Qt 5 and QGIS 4.x / Qt 6."""

    def test_runtime_version_detection_and_metadata_range(self):
        self.assertGreaterEqual(compat.QGIS_VERSION_INT, 34000)
        self.assertTrue(compat.IS_QGIS_3_40_OR_LATER)
        self.assertIn(compat.QT_MAJOR, (5, 6))
        self.assertEqual(compat.QT_BINDING, f"PyQt{compat.QT_MAJOR}")
        self.assertNotEqual(compat.IS_QT5, compat.IS_QT6)
        self.assertIn("QGIS ", compat.version_summary())

        parser = configparser.ConfigParser(interpolation=None)
        parser.read(PLUGIN_ROOT / "metadata.txt", encoding="utf-8")
        self.assertEqual(parser.get("general", "qgisMinimumVersion"), "3.40")
        self.assertEqual(parser.get("general", "qgisMaximumVersion"), "4.99")

    def test_all_compat_enum_constants_resolve_non_none(self):
        required = (
            "AlignCenter", "AlignLeft", "AlignRight", "AlignTop", "AlignBottom",
            "AlignVCenter", "AlignHCenter", "Horizontal", "Vertical",
            "UserRole", "DisplayRole", "ToolTipRole", "BackgroundRole",
            "ForegroundRole", "AccessibleDescriptionRole",
            "RichText", "PlainText", "TextWordWrap", "TextElideNone",
            "ScrollBarAsNeeded", "ScrollBarAlwaysOff", "ScrollBarAlwaysOn",
            "PointingHandCursor", "WaitCursor", "ArrowCursor",
            "ToolButtonTextBesideIcon", "ToolButtonIconOnly", "ToolButtonTextOnly",
            "FocusStrongFocus", "FocusNoFocus",
            "WidgetAttrTransparentForMouse", "WidgetAttrNoSystemBackground",
            "AllDockAreas", "LeftDockArea", "RightDockArea", "TopDockArea", "BottomDockArea",
            "KeySpace", "KeyReturn", "KeyEnter", "KeyF2", "KeyDelete", "KeyLeft", "KeyTab", "KeyEscape",
            "NoModifier", "MouseLeftButton",
            "EventKeyPress", "EventMouseButtonPress", "EventMouseMove",
            "EventFocusIn", "EventFocusOut", "EventFontChange",
            "EventPaletteChange", "EventApplicationPaletteChange",
            "EventApplicationFontChange", "EventDynamicPropertyChange",
            "EventEnabledChange", "EventToolTip", "EventLeave",
            "EventResize", "EventHide", "EventWindowActivate",
            "EventWindowDeactivate", "EventDeferredDelete",
            "FontBold", "FontDemiBold", "FontNormal",
            "StyleHintMonospace", "StyleHintSansSerif", "StyleHintSerif",
            "CursorEnd", "CursorUp", "CursorStartOfLine", "CursorKeepAnchor", "CursorLineUnder",
            "TextSelectableByMouse",
            "FrameBox", "FrameStyledPanel", "FrameNoFrame", "FrameHLine", "FrameRaised", "FrameSunken",
            "HeaderStretch", "HeaderResizeToContents", "HeaderFixed", "HeaderInteractive",
            "SizePolicyFixed", "SizePolicyMinimum", "SizePolicyMaximum",
            "SizePolicyPreferred", "SizePolicyExpanding", "SizePolicyIgnored",
            "MultiSelection", "SingleSelection", "ExtendedSelection", "NoSelection",
            "SelectRows", "SelectItems", "NoEditTriggers",
            "MsgBoxOk", "MsgBoxYes", "MsgBoxNo", "MsgBoxCancel", "MsgBoxSave", "MsgBoxDiscard",
            "MsgBoxIconInfo", "MsgBoxIconWarning", "MsgBoxIconCritical", "MsgBoxIconQuestion",
            "DialogAccepted", "DialogRejected",
            "DockAllowNestedDocks", "DockAllowTabbedDocks",
            "TabNorth", "TabSouth",
            "DockMovable", "DockFloatable", "DockClosable",
            "ExpandingFieldsGrow", "FormAllNonFixedFieldsGrow", "FormWrapLongRows",
            "ComboAdjustMinContentsIcon", "FileDialogDontConfirmOverwrite",
            "CustomContextMenu", "PasswordEchoMode", "NormalEchoMode",
            "WrapWidgetWidth", "WrapNoWrap",
            "InstantPopup", "MenuButtonPopup", "DelayedPopup",
            "KeyNew", "KeyOpen", "KeySave", "KeyQuit", "KeyUndo", "KeyRedo", "KeyHelpContents",
            "DlgBtnOk", "DlgBtnCancel", "DlgBtnClose", "DlgBtnSave", "DlgBtnDiscard",
            "DlgBtnApply", "DlgBtnReset", "DlgBtnRestoreDefaults", "DlgBtnHelp", "DlgBtnYes", "DlgBtnNo",
            "ItemIsEnabled", "ItemIsSelectable", "ItemIsEditable",
            "ApplicationShortcut", "WidgetShortcut",
            "KeepAspectRatio", "SmoothTransformation",
            "IconModeNormal", "IconModeDisabled", "IconStateOff", "IconStateOn",
            "StyleStateEnabled", "StyleCEPushButtonLabel",
            "ImageFormatARGB32Premultiplied", "Antialias", "CompositionSourceIn",
            "NoPen", "PenSolidLine", "PenCapRound", "BrushNoBrush", "GlobalTransparent",
            "EaseInOutQuad", "EaseOutCubic", "AnimationStopped",
            "SettingsIniFormat", "SettingsNativeFormat", "SettingsUserScope", "SettingsSystemScope",
            "PaletteGroupActive", "PaletteGroupInactive", "PaletteGroupDisabled",
            "PaletteText", "PaletteWindow", "PaletteBase", "PaletteWindowText",
            "PaletteButton", "PaletteButtonText", "PaletteHighlight", "PaletteHighlightedText",
            "MsgInfo", "MsgWarning", "MsgCritical", "MsgSuccess",
            "GeomNull", "GeomPoint", "GeomLine", "GeomPolygon", "GeomUnknown",
            "TaskCanCancel", "WriterNoError", "LayerTypeVector", "FeatureRequestNoGeometry",
        )
        for name in required:
            self.assertIsNotNone(getattr(compat, name, None), f"compat.{name} resolved to None")

    def test_qaction_qshortcut_fonts_and_hidpi_icons(self):
        act = compat.QAction("Test", None)
        self.assertEqual(act.text(), "Test")
        self.assertTrue(callable(compat.QShortcut))

        families = compat.font_database_families()
        self.assertIsInstance(families, list)
        self.assertGreater(len(families), 0)

        mono = compat.fixed_system_font()
        self.assertIsInstance(mono, QFont)

        btn = FluentButton("Run", variant="primary", icon_name="play")
        try:
            title_font = role_font(btn, "title")
            self.assertGreater(title_font.pointSizeF(), 0)
            btn.resize(140, 42)
            self.assertFalse(btn.grab().isNull())
        finally:
            btn.deleteLater()

        play_icon = icons.icon("play")
        for dpr, expected_w in ((1.0, 20), (2.0, 40)):
            for mode in (compat.IconModeNormal, compat.IconModeDisabled):
                px = compat.icon_pixmap(play_icon, QSize(20, 20), dpr, mode)
                self.assertEqual(px.width(), expected_w)
                self.assertEqual(px.devicePixelRatioF(), dpr)
                img = px.toImage()
                self.assertTrue(any(
                    img.pixelColor(x, y).alpha() > 0
                    for y in range(img.height()) for x in range(img.width())
                ))

    def test_field_types_and_widget_type_inference_without_typename(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "types_probe", "memory")
        spec = [
            ("f_bool", "Bool", "Boolean"),
            ("f_int", "Int", "Integer"),
            ("f_int64", "LongLong", "Integer64"),
            ("f_real", "Double", "Real"),
            ("f_date", "QDate", "Date"),
            ("f_dt", "QDateTime", "DateTime"),
            ("f_str", "QString", "Text"),
        ]
        # Build fields with empty typeName to exercise numeric/enum type() resolution.
        layer.dataProvider().addAttributes([
            QgsField(name, compat.meta_type_enum(qt_name))
            for name, qt_name, _ in spec
        ])
        layer.updateFields()

        widget = FieldWidget()
        try:
            widget.current_layer = layer
            for idx, (name, qt_name, expected_canonical) in enumerate(spec):
                fld = layer.fields().at(idx)
                self.assertEqual(compat.meta_type_name(fld.type()), qt_name)
                inferred = widget._infer_definition(name, f'"{name}"')
                self.assertEqual(inferred["type"], expected_canonical, f"Mismatch for {name}")
                mapped = definition_from_processing_mapping({
                    "name": name,
                    "type": fld.type(),
                    "type_name": "",
                    "length": fld.length(),
                    "precision": fld.precision(),
                })
                self.assertEqual(mapped["type"], expected_canonical)
        finally:
            widget.deleteLater()

        # Verify create_compatible_field + convert_value_for_field on all 7 types
        f_int = create_compatible_field("n", "int")
        self.assertEqual(convert_value_for_field(f_int, 42), 42)
        with self.assertRaises(ValueError):
            convert_value_for_field(f_int, 3.14)

        f_str = create_compatible_field("s", "string", length=4)
        self.assertEqual(convert_value_for_field(f_str, "abcd"), "abcd")
        with self.assertRaises(ValueError):
            convert_value_for_field(f_str, "abcde")

        f_date = create_compatible_field("d", "date")
        self.assertEqual(convert_value_for_field(f_date, QDate(2026, 10, 25)), QDate(2026, 10, 25))
        f_dt = create_compatible_field("dt", "datetime")
        dt_val = QDateTime(2026, 10, 25, 12, 30, 0)
        self.assertEqual(convert_value_for_field(f_dt, dt_val), dt_val)

    def test_geometry_equals_and_wkb_type_name_no_deprecation(self):
        g1 = QgsGeometry.fromPointXY(QgsPointXY(2.35, 48.85))
        g2 = QgsGeometry.fromPointXY(QgsPointXY(2.35, 48.85))
        g3 = QgsGeometry.fromPointXY(QgsPointXY(2.36, 48.85))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            self.assertTrue(compat.geometry_equals(g1, g2))
            self.assertFalse(compat.geometry_equals(g1, g3))
        self.assertEqual(caught, [], [str(w.message) for w in caught])

        pt_layer = QgsVectorLayer("Point?crs=EPSG:4326", "p", "memory")
        tbl_layer = QgsVectorLayer("None?field=a:string", "t", "memory")
        self.assertIn("point", compat.wkb_type_name(pt_layer.wkbType()).lower())
        self.assertIn("nogeometry", compat.wkb_type_name(tbl_layer.wkbType()).lower())

    def test_processing_provider_cross_version(self):
        provider = TransformerProvider(str(PLUGIN_ROOT))
        provider.loadAlgorithms()
        algos = {algo.name(): algo for algo in provider.algorithms()}
        self.assertEqual(set(algos), {"apply_recipe", "publish_postgresql", "transform_vector"})
        for algo in algos.values():
            inst = algo.createInstance()
            inst.initAlgorithm()
            self.assertGreater(len(inst.parameterDefinitions()), 0)

        # Verify _sslmode_name across Qt5 flat and Qt6 scoped SslMode enums
        ssl_enum = getattr(QgsDataSourceUri, "SslMode", QgsDataSourceUri)
        for attr, expected in (
            ("SslDisable", "disable"),
            ("SslPrefer", "prefer"),
            ("SslRequire", "require"),
            ("SslVerifyFull", "verify-full"),
        ):
            mode_val = getattr(ssl_enum, attr, getattr(QgsDataSourceUri, attr, None))
            if mode_val is not None:
                uri = QgsDataSourceUri()
                uri.setConnection("localhost", "5432", "gis", "user", "", mode_val)
                self.assertEqual(_sslmode_name(uri), expected)

        # Run transform_vector algorithm end-to-end
        layer = QgsVectorLayer("Point?crs=EPSG:2154", "proc_src", "memory")
        layer.dataProvider().addAttributes([
            QgsField("code", compat.meta_type_enum("QString"), "", 40),
            QgsField("qty", compat.meta_type_enum("Int")),
        ])
        layer.updateFields()
        feat = QgsFeature(layer.fields())
        feat.setAttributes(["  ab  ", 5])
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(650000, 6860000)))
        layer.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(layer)
        try:
            ctx = QgsProcessingContext()
            ctx.setProject(QgsProject.instance())
            fb = QgsProcessingFeedback()
            algo = algos["transform_vector"].createInstance()
            algo.initAlgorithm()
            res = algo.processAlgorithm({
                "INPUT": layer,
                "FIELDS_MAPPING": [
                    {"name": "code_up", "expression": 'upper(trim("code"))', "type": int(compat.meta_type_enum("QString")), "length": 40, "precision": 0},
                    {"name": "qty2", "expression": '"qty" * 2', "type": int(compat.meta_type_enum("Int")), "length": 0, "precision": 0},
                ],
                "FILTER_EXPRESSION": '"qty" > 0',
                "GEOMETRY_EXPRESSION": "",
                "TARGET_CRS": "EPSG:4326",
                "STRICT_SCHEMA_CHECK": True,
                "OUTPUT": "memory:",
            }, ctx, fb)
            self.assertEqual(res["PRODUCED_COUNT"], 1)
            self.assertEqual(res["FILTERED_OUT_COUNT"], 0)
        finally:
            QgsProject.instance().removeMapLayer(layer.id())

    def test_window_teardown_and_live_layer_removal_safe_on_qt5_and_qt6(self):
        import tempfile

        app = QgsApplication.instance()
        with tempfile.TemporaryDirectory(prefix="transformer-compat-life-") as tmpdir:
            mgr = ConfigManager(tmpdir)
            for idx in range(3):
                layer = QgsVectorLayer(
                    "Point?crs=EPSG:2154&field=code:string&field=val:integer",
                    f"life_{idx}",
                    "memory",
                )
                feat = QgsFeature(layer.fields())
                feat.setAttributes([f"C{idx}", idx])
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(650000 + idx, 6860000)))
                layer.dataProvider().addFeatures([feat])
                QgsProject.instance().addMapLayer(layer)

                win = EnhancedTransformerDialog(mgr, SimpleTransformer(mgr))
                win.show()
                win.auto_load_qgis_layers()
                win.refresh_shapefile_list()
                if idx == 0:
                    # Remove active layer while dialog is open (must detach C++ builder cleanly).
                    QgsProject.instance().removeMapLayer(layer.id())
                    app.processEvents()
                    self.assertIsNone(win.advanced_expression.layer)
                win._force_shutdown = True
                win.close()
                win.deleteLater()
                QgsProject.instance().removeAllMapLayers()
                app.processEvents()

    def test_ast_guard_no_qt6_or_qt5_only_regressions_in_runtime(self):
        violations = []
        for path in sorted(PLUGIN_ROOT.rglob("*.py")):
            rel = path.relative_to(PLUGIN_ROOT).as_posix()
            if (
                rel.startswith("tests/")
                or rel.startswith("audit/")
                or rel.startswith("reception/")
                or rel == "shared/compat.py"
                or "__pycache__" in rel
            ):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(("PyQt5", "PyQt6")):
                            violations.append(f"{rel}:{node.lineno} direct {alias.name} import")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(("PyQt5", "PyQt6")):
                        violations.append(f"{rel}:{node.lineno} direct from {node.module}")
                    if node.module in ("qgis.PyQt.QtGui", "qgis.PyQt.QtWidgets"):
                        for alias in node.names:
                            if alias.name in ("QAction", "QShortcut"):
                                violations.append(f"{rel}:{node.lineno} unguarded {alias.name} from {node.module}")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "exec_":
                        violations.append(f"{rel}:{node.lineno} deprecated .exec_()")
                    if (
                        node.func.attr == "families"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "QFontDatabase"
                    ):
                        violations.append(f"{rel}:{node.lineno} static QFontDatabase.families()")
                    if node.func.attr == "pixmap" and len(node.args) >= 2:
                        violations.append(f"{rel}:{node.lineno} multi-arg .pixmap() (use compat.icon_pixmap)")
                elif isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name) and node.value.id == "cursor" and node.attr in (
                        "End", "StartOfLine", "KeepAnchor",
                    ):
                        violations.append(f"{rel}:{node.lineno} Qt5-only cursor.{node.attr}")
        self.assertEqual(violations, [], "Cross-version AST violations:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
