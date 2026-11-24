# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Pure contract checks; actual Qt widgets and keyboard paths need QGIS receipt.

Run with the ordinary Python runtime: python -B tests/test_widgets_recipe.py
Methods with no Qt-dependent logic are compiled from the real source AST. This
does not import QGIS or claim that an offscreen window was exercised.
"""

import ast
from copy import deepcopy
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def source_function(path, name, class_name=None, namespace=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    body = tree.body
    if class_name:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    function = next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)
    scope = {"deepcopy": deepcopy}
    scope.update(namespace or {})
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / path), "exec"), scope)
    return scope[name]


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class SettingsBackend:
    def __init__(self, values=None, error=0):
        self.values = dict(values or {})
        self.error = error

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass

    def status(self):
        return self.error


class SettingsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = runpy.run_path(str(ROOT / "shared/interface_config.py"))
        cls.Settings = cls.module["InterfaceSettings"]

    def test_all_historical_preferences_have_defaults(self):
        settings = self.Settings()
        for key in ("theme", "show_tooltips", "enable_animations", "compact_toolbar",
                    "auto_save_config", "expression_syntax_highlighting", "auto_complete_expressions",
                    "max_undo_steps", "show_performance_stats", "enable_debugging", "auto_backup_interval"):
            self.assertTrue(hasattr(settings, key), key)

    def test_injected_settings_roundtrip(self):
        backend = SettingsBackend()
        original = self.Settings(show_tooltips=False, max_undo_steps=42)
        self.assertTrue(original.save(backend))
        loaded = self.Settings()
        self.assertIs(loaded.load(backend), loaded)
        self.assertFalse(loaded.show_tooltips)
        self.assertEqual(loaded.max_undo_steps, 42)

    def test_settings_conversion_and_bounds(self):
        loaded = self.Settings().load(SettingsBackend({
            "Transformer/interface/show_tooltips": "false",
            "Transformer/interface/max_undo_steps": "-800",
            "Transformer/interface/auto_backup_interval": "bad",
            "Transformer/interface/theme": "dark",
        }))
        self.assertFalse(loaded.show_tooltips)
        self.assertEqual(loaded.max_undo_steps, 10)
        self.assertEqual(loaded.auto_backup_interval, 300)
        self.assertEqual(loaded.theme.value, "qgis_native")

    def test_failed_settings_write_is_not_success(self):
        self.assertFalse(self.Settings().save(SettingsBackend(error=1)))


class DefinitionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = "widgets/field_definition_dialog.py"
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "FIELD_TYPE_LABELS" for target in node.targets))
        cls.labels = ast.literal_eval(assignment.value)
        cls.normalize = staticmethod(source_function(path, "normalize_field_definition", namespace={"FIELD_TYPE_LABELS": cls.labels}))

    def test_seven_types_and_description_survive_normalization(self):
        self.assertEqual(set(self.labels), {"Text", "Integer", "Integer64", "Real", "Date", "DateTime", "Boolean"})
        for field_type in self.labels:
            value = {"type": field_type, "length": 12, "precision": 3, "description": "Unité métier"}
            result = self.normalize(value)
            self.assertEqual(result, value)
            self.assertIsNot(result, value)

    def test_malformed_lengths_do_not_break_dialog(self):
        result = self.normalize({"type": "Real", "length": "bad", "precision": -3, "description": None})
        self.assertEqual(result, {"type": "Real", "length": 0, "precision": 0, "description": ""})


class RecipeMethodTests(unittest.TestCase):
    def test_shortened_and_cleared_expression_stays_as_edited(self):
        get_expression = source_function("widgets/advanced_expression_widget.py", "get_expression", "AdvancedExpressionWidget")
        clear_expression = source_function("widgets/advanced_expression_widget.py", "clear_expression", "AdvancedExpressionWidget")
        emit_expression = source_function("widgets/advanced_expression_widget.py", "_emit_expression_changed", "AdvancedExpressionWidget")
        state = {"expression": 'upper("code")'}
        builder = SimpleNamespace(
            expressionText=lambda: state["expression"],
            setExpressionText=lambda text: state.update(expression=text),
        )
        widget = SimpleNamespace(expression_builder=builder, _original_expression='upper("code") || \'old\'',
                                 expression_changed=Signal(), validate_expression=lambda: None)
        widget._last_emitted_expression = state["expression"]
        widget.get_expression = lambda: get_expression(widget)
        widget._emit_expression_changed = lambda: emit_expression(widget)
        self.assertEqual(get_expression(widget), 'upper("code")')
        clear_expression(widget)
        self.assertEqual(get_expression(widget), "")
        self.assertEqual(widget._original_expression, "")
        self.assertEqual(widget.expression_changed.values[-1], ("",))
        clear_expression(widget)
        self.assertEqual(widget.expression_changed.values, [("",)])

    def test_excluding_all_never_accesses_saved_recipes(self):
        clear = source_function("widgets/field_widget.py", "clear_all_fields", "FieldWidget")
        widget = SimpleNamespace(calculated_fields={"a": {}, "b": {}}, field_definitions={"a": {"type": "Text"}},
                                 field_removed=Signal(), refresh_fields_list=lambda: None)
        self.assertTrue(clear(widget))
        self.assertEqual(widget.calculated_fields, {})
        self.assertEqual(widget.field_definitions, {})
        self.assertEqual(widget.field_removed.values, [("a",), ("b",)])
        self.assertFalse(clear(widget))

    def test_field_definitions_are_independent_and_exclude_geometry(self):
        get_definitions = source_function("widgets/field_widget.py", "get_field_definitions", "FieldWidget")
        definitions = {"count": {"type": "Integer64", "length": 0, "precision": 0, "description": "Volume"}}
        widget = SimpleNamespace(field_definitions=definitions,
                                 calculated_fields={"count": {"expression": '"n"'}, "geometry": {"is_geometry": True}},
                                 _infer_definition=lambda *_: self.fail("Explicit metadata must be retained"))
        result = get_definitions(widget)
        self.assertEqual(list(result), ["count"])
        result["count"]["description"] = "changed outside widget"
        self.assertEqual(definitions["count"]["description"], "Volume")

    def _rename(self, target_name):
        warnings = []
        definition = {"type": "Real", "length": 12, "precision": 3, "description": "Surface"}
        dialog = SimpleNamespace(
            set_field_info=lambda *_: None, set_field_definition=lambda *_: None,
            exec=lambda: 1, get_field_info=lambda: (target_name, "Surface"),
            get_field_definition=lambda: deepcopy(definition),
        )
        edit = source_function("widgets/field_widget.py", "edit_selected_field", "FieldWidget", {
            "FieldDefinitionDialog": lambda *_, **__: dialog,
            "_DialogCode": SimpleNamespace(Accepted=1),
            "QMessageBox": SimpleNamespace(warning=lambda *values: warnings.append(values)),
        })
        widget = SimpleNamespace(
            fields_tree=SimpleNamespace(currentItem=lambda: SimpleNamespace(text=lambda _: "old"),
                                        setFocus=lambda: None),
            calculated_fields={"old": {"expression": 'area($geometry)', "description": "Before"},
                               "taken": {"expression": '"other"'}},
            field_definitions={"old": {"type": "Text"}, "taken": {"type": "Text"}},
            expression_widget=None, field_modified=Signal(), refresh_fields_list=lambda: None,
        )
        return edit(widget), widget, warnings

    def test_rename_collision_preserves_both_rules(self):
        result, widget, warnings = self._rename("TAKEN")
        self.assertFalse(result)
        self.assertTrue(warnings)
        self.assertEqual(list(widget.calculated_fields), ["old", "taken"])
        self.assertEqual(widget.field_modified.values, [])

    def test_rename_preserves_position_expression_and_definition(self):
        result, widget, _ = self._rename("surface")
        self.assertTrue(result)
        self.assertEqual(list(widget.calculated_fields), ["surface", "taken"])
        self.assertEqual(widget.calculated_fields["surface"]["expression"], 'area($geometry)')
        self.assertEqual(widget.field_definitions["surface"]["type"], "Real")
        self.assertEqual(widget.field_modified.values, [("old", "surface", "area($geometry)")])

    def test_geometry_name_is_reserved_for_attribute_rename(self):
        for reserved in ("geometry", "Geometry", "GEOMETRY"):
            result, widget, warnings = self._rename(reserved)
            self.assertFalse(result)
            self.assertTrue(warnings)
            self.assertEqual(list(widget.calculated_fields), ["old", "taken"])
            self.assertEqual(widget.field_modified.values, [])

    def test_geometry_name_is_reserved_for_attribute_addition(self):
        warnings = []
        add = source_function("widgets/field_widget.py", "add_calculated_field", "FieldWidget", {
            "QMessageBox": SimpleNamespace(warning=lambda *args: warnings.append(args)),
        })
        widget = SimpleNamespace(calculated_fields={"existing": {"expression": '"a"'}},
                                 field_definitions={"existing": {"type": "Text"}})
        for reserved in ("geometry", "Geometry", " GEOMETRY "):
            self.assertFalse(add(widget, reserved, '"source"'))
        self.assertEqual(len(warnings), 3)
        self.assertEqual(list(widget.calculated_fields), ["existing"])

    def test_imported_geometry_attribute_is_refused_before_mutation(self):
        load = source_function("widgets/field_widget.py", "set_calculated_fields", "FieldWidget")
        widget = SimpleNamespace(calculated_fields={"keep": {"expression": '"a"'}},
                                 field_definitions={"keep": {"type": "Text"}})
        for reserved in ("geometry", "Geometry"):
            with self.assertRaisesRegex(ValueError, "geometry_attribut"):
                load(widget, {reserved: '"geometry"'}, "centroid($geometry)")
        self.assertEqual(list(widget.calculated_fields), ["keep"])

    def test_legacy_geometry_argument_and_renamed_attribute_remain_distinct(self):
        load = source_function("widgets/field_widget.py", "set_calculated_fields", "FieldWidget", {
            "normalize_field_definition": deepcopy,
        })
        split = source_function("widgets/field_widget.py", "get_calculated_fields_with_geometry_info", "FieldWidget")
        widget = SimpleNamespace(calculated_fields={}, field_definitions={},
                                 parent=lambda: None, refresh_fields_list=lambda: None)
        load(widget, {"geometry_attribut": '"geometry"'}, "centroid($geometry)",
             {"geometry_attribut": {"type": "Text", "description": "Source conservée"}})
        self.assertTrue(widget.calculated_fields["geometry"]["is_geometry"])
        attributes, geometry = split(widget)
        self.assertEqual(attributes, {"geometry_attribut": '"geometry"'})
        self.assertEqual(geometry, "centroid($geometry)")

    def test_definition_dialog_reserves_geometry_without_accepting(self):
        warnings = []
        accept = source_function("widgets/field_definition_dialog.py", "accept", "FieldDefinitionDialog", {
            "QMessageBox": SimpleNamespace(warning=lambda *args: warnings.append(args)),
        })
        focused = []
        dialog = SimpleNamespace(name_edit=SimpleNamespace(text=lambda: "Geometry", setFocus=lambda: focused.append(True)))
        accept(dialog)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Géométrie", warnings[0][2])
        self.assertTrue(focused)

    def test_disabled_filter_keeps_saved_expression(self):
        get_config = source_function("widgets/smart_filter_widget.py", "get_filter_config", "SmartFilterWidget")
        widget = SimpleNamespace(enable_filter_cb=SimpleNamespace(isChecked=lambda: False),
                                 filter_expression=SimpleNamespace(text=lambda: ' "status" = 2 '))
        self.assertEqual(get_config(widget), {"enabled": False, "expression": '"status" = 2'})

    def test_toggle_does_not_clear_filter_rule(self):
        toggle = source_function("widgets/smart_filter_widget.py", "on_filter_enabled_changed", "SmartFilterWidget")
        state = {"expression": '"status" = 2', "invalidations": 0}
        control = SimpleNamespace(setEnabled=lambda value: None)
        widget = SimpleNamespace(filter_expression=control, builder_btn=control, test_filter_btn=control,
                                 template_buttons=[control],
                                 _invalidate_preview=lambda: state.update(invalidations=state["invalidations"] + 1),
                                 emit_filter_changed=lambda: None)
        toggle(widget, False)
        self.assertEqual(state["expression"], '"status" = 2')
        self.assertEqual(state["invalidations"], 1)

    def test_filter_preview_reads_at_most_one_extra_source_object(self):
        state = {"reads": 0, "limit": None, "closed": False, "errors": []}

        class Request:
            def setLimit(self, limit):
                state["limit"] = limit
                return self

        class Iterator:
            def __iter__(self):
                return self

            def __next__(self):
                # Deliberately unbounded provider double: the widget must stop.
                state["reads"] += 1
                if state["reads"] > 502:
                    raise AssertionError("Source read was not bounded")
                return SimpleNamespace(id=lambda: state["reads"])

            def close(self):
                state["closed"] = True

        expression = SimpleNamespace(prepare=lambda _: True)
        preview = source_function("widgets/smart_filter_widget.py", "test_filter", "SmartFilterWidget", {
            "QgsFeatureRequest": Request,
            "validate_expression_syntax": lambda _: (True, "", expression),
            "create_layer_expression_context": lambda _: SimpleNamespace(setFeature=lambda _: None),
            "evaluate_expression": lambda *_: (True, 1, ""),
            "QMessageBox": SimpleNamespace(information=lambda *_: None,
                                           warning=lambda *args: state["errors"].append(args)),
        })
        label = SimpleNamespace(setText=lambda _: None)
        widget = SimpleNamespace(layer=SimpleNamespace(getFeatures=lambda _: Iterator()),
                                 get_filter_expression=lambda: '"status" = 2', PREVIEW_LIMIT=500,
                                 update_filter_status=lambda *_: None, filter_count_label=label,
                                 last_test_result=None)
        preview(widget)
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["limit"], 501)
        self.assertEqual(state["reads"], 501)
        self.assertTrue(state["closed"])
        self.assertEqual(widget.last_test_result["sampled"], 500)
        self.assertTrue(widget.last_test_result["truncated"])


@unittest.skipUnless(
    "qgis.core" in sys.modules and sys.modules["qgis.core"].QgsApplication.instance() is not None,
    "Nécessite le runner QGIS4 isolé ; aucun widget natif lancé par Python seul.",
)
class NativeWidgetAccessibilityTests(unittest.TestCase):
    """Exercise real controls only inside the coordinator's isolated QGIS runner."""

    @classmethod
    def setUpClass(cls):
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtTest import QTest
        from qgis.PyQt.QtWidgets import QApplication
        cls.Qt, cls.QTest, cls.app = Qt, QTest, QApplication.instance()

    def _show(self, widget, width=640, height=640):
        self.addCleanup(widget.deleteLater)
        self.addCleanup(widget.close)
        font = widget.font()
        font.setPointSize(18)
        widget.setFont(font)
        widget.resize(width, height)
        widget.show()
        widget.activateWindow()
        self.app.processEvents()
        return widget

    def _assert_control_fits(self, control):
        self.assertGreaterEqual(control.height(), control.minimumSizeHint().height())
        self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())

    def test_field_form_buddies_keyboard_and_large_font(self):
        from qgis.PyQt.QtWidgets import QFormLayout, QDialogButtonBox
        from Transfomer.widgets.field_definition_dialog import FieldDefinitionDialog
        dialog = self._show(FieldDefinitionDialog())
        form = dialog.findChild(QFormLayout)
        for control in (dialog.name_edit, dialog.type_combo, dialog.length_spin,
                        dialog.precision_spin, dialog.description_edit):
            self.assertIs(form.labelForField(control).buddy(), control)
            self.assertTrue(control.accessibleName())
            self._assert_control_fits(control)
        dialog.name_edit.setFocus()
        self.QTest.keyClick(dialog.name_edit, self.Qt.Key.Key_Tab)
        self.assertTrue(dialog.type_combo.hasFocus())
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Cancel).text(), "Annuler")
        self.QTest.keyClick(dialog, self.Qt.Key.Key_Escape)
        self.assertEqual(dialog.result(), 0)

    def test_history_preserves_full_rule_and_supports_keyboard_choice(self):
        from Transfomer.widgets.advanced_expression_widget import ExpressionHistoryDialog
        first = "'" + "référence longue " * 12 + "'"
        dialog = self._show(ExpressionHistoryDialog([first, 'upper("code")']))
        self.assertEqual(dialog.list_widget.item(0).text(), first)
        self.assertEqual(dialog.list_widget.item(0).toolTip(), first)
        self.assertEqual(dialog.get_selected_expression(), first)
        self.QTest.keyClick(dialog.list_widget, self.Qt.Key.Key_Down)
        self.QTest.keyClick(dialog.list_widget, self.Qt.Key.Key_Return)
        self.assertEqual(dialog.get_selected_expression(), 'upper("code")')
        self.assertEqual(dialog.result(), 1)

    def test_expression_tools_have_accessible_names_and_keyboard_focus(self):
        from qgis.PyQt.QtWidgets import QToolBar
        from Transfomer.widgets.advanced_expression_widget import AdvancedExpressionWidget
        widget = self._show(AdvancedExpressionWidget(), width=1000)
        toolbar = widget.findChild(QToolBar)
        self.assertTrue(toolbar.accessibleName())
        for action in (widget.validate_action, widget.clear_action,
                       widget.history_action, widget.help_action):
            button = toolbar.widgetForAction(action)
            self.assertTrue(button.accessibleName())
            self.assertEqual(button.focusPolicy(), self.Qt.FocusPolicy.StrongFocus)
            self._assert_control_fits(button)

    def test_field_matrix_keyboard_commands_and_large_font_actions(self):
        from Transfomer.widgets.field_widget import FieldWidget
        widget = self._show(FieldWidget())
        widget.set_calculated_fields({"code": '"source"'})
        widget.fields_tree.setCurrentItem(widget.fields_tree.topLevelItem(0))
        widget.fields_tree.setFocus()
        for control in (widget.add_field_btn, widget.edit_field_btn,
                        widget.remove_field_btn, widget.clear_all_btn):
            self.assertTrue(control.accessibleName())
            self._assert_control_fits(control)
        with patch.object(widget, "edit_selected_field") as edit:
            self.QTest.keyClick(widget.fields_tree, self.Qt.Key.Key_F2)
            self.QTest.keyClick(widget.fields_tree, self.Qt.Key.Key_Return)
            self.assertEqual(edit.call_count, 2)
        with patch.object(widget, "remove_selected_field") as remove:
            self.QTest.keyClick(widget.fields_tree, self.Qt.Key.Key_Delete)
            remove.assert_called_once_with()

    def test_filter_keyboard_order_buddy_and_disabled_rule_retention(self):
        from qgis.PyQt.QtWidgets import QLabel
        from Transfomer.widgets.smart_filter_widget import SmartFilterWidget
        widget = self._show(SmartFilterWidget())
        widget.enable_filter_cb.setChecked(True)
        widget.filter_expression.setText('"status" = 2')
        self.assertTrue(any(label.buddy() is widget.filter_expression
                            for label in widget.findChildren(QLabel)))
        widget.filter_expression.setFocus()
        self.QTest.keyClick(widget.filter_expression, self.Qt.Key.Key_Tab)
        self.assertTrue(widget.builder_btn.hasFocus())
        self.QTest.keyClick(widget.builder_btn, self.Qt.Key.Key_Tab)
        self.assertTrue(widget.test_filter_btn.hasFocus())
        for control in (widget.builder_btn, widget.test_filter_btn, *widget.template_buttons):
            self._assert_control_fits(control)
        widget.enable_filter_cb.setChecked(False)
        self.assertEqual(widget.get_filter_config(), {"enabled": False, "expression": '"status" = 2'})

    def test_preferences_and_help_tabs_keep_native_keyboard_contracts(self):
        from qgis.PyQt.QtWidgets import QFormLayout, QWidget
        from Transfomer.shared.interface_config import InterfaceSettings
        from Transfomer.widgets.preferences_dialog import PreferencesDialog
        from Transfomer.widgets.sliding_tab_bar import SlidingTabWidget
        dialog = self._show(PreferencesDialog(InterfaceSettings(), qsettings=SettingsBackend()))
        form = dialog.findChild(QFormLayout)
        self.assertIs(form.labelForField(dialog.theme_combo).buddy(), dialog.theme_combo)
        self._assert_control_fits(dialog.theme_combo)
        dialog.close()
        tabs = SlidingTabWidget()
        tabs.addTab(QWidget(), "Première rubrique")
        tabs.addTab(QWidget(), "Deuxième rubrique")
        self._show(tabs)
        self.assertEqual(tabs._bar.elideMode(), self.Qt.TextElideMode.ElideNone)
        tabs._bar.setFocus()
        self.QTest.keyClick(tabs._bar, self.Qt.Key.Key_Right)
        self.assertEqual(tabs.currentIndex(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
