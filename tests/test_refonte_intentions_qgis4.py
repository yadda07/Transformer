# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Intentions contextuelles et gestes clavier, sans source métier ni traitement."""

import copy
import json
import os
from pathlib import Path
import unittest

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QCheckBox, QLabel

from Transfomer.core.intentions import build_intentions
from Transfomer.ui.intentions_panel import IntentionsPanel


def context(**updates):
    result = {"source_id": "source-fictive", "source_name": "Ouvrages de démonstration",
              "field_names": ["nom", "hauteur", "visite"],
              "field_types": {"nom": "Text", "hauteur": "Double", "visite": "Date"},
              "geometry": True, "feature_count": 1234, "compatible_recipes": []}
    result.update(updates)
    return result


def indexed(value):
    return {item["id"]: item for item in build_intentions(value)}


class IntentionsRulesTests(unittest.TestCase):
    def test_no_source_has_seven_explained_choices_without_recommendation(self):
        intentions = build_intentions({})
        self.assertEqual([item["id"] for item in intentions],
                         ["clean", "fields", "filter", "geometry", "compare", "deliver", "replay"])
        self.assertTrue(all(not item["enabled"] and not item["recommended"] for item in intentions))
        self.assertTrue(all("entrée" in item["reason"] for item in intentions))
        json.dumps(intentions)

    def test_read_only_table_still_allows_preparing_a_copy(self):
        choices = indexed(context(geometry=False, read_only=True))
        self.assertFalse(choices["geometry"]["enabled"])
        self.assertIn("sans géométrie", choices["geometry"]["reason"])
        self.assertFalse(choices["replay"]["enabled"])
        self.assertTrue(all(choices[key]["enabled"] for key in ("clean", "fields", "filter", "compare", "deliver")))
        self.assertIn("lecture seule", choices["deliver"]["reason"].casefold())
        self.assertIn("copie", choices["deliver"]["reason"].casefold())

    def test_suggestions_follow_observed_types_not_column_name_or_profile(self):
        text = indexed(context())
        unknown = indexed(context(field_types={}, user_profile="expert"))
        numeric = indexed(context(field_types={"nom": "Integer", "hauteur": "Double"}))
        self.assertTrue(text["clean"]["recommended"])
        self.assertIn("nom", text["clean"]["reason"])
        self.assertFalse(unknown["clean"]["recommended"])
        self.assertFalse(numeric["clean"]["recommended"])
        self.assertTrue(unknown["compare"]["recommended"])

    def test_replay_requires_actual_compatible_names_and_deduplicates(self):
        source = context(compatible_recipes=["  Préparation A  ", "Préparation A", "", None, "Préparation B"])
        replay = indexed(source)["replay"]
        self.assertTrue(replay["enabled"])
        self.assertTrue(replay["recommended"])
        self.assertEqual(replay["reason"].count("Préparation A"), 1)
        self.assertIn("Préparation B", replay["reason"])
        self.assertFalse(indexed(context(compatible_recipes="Préparation A"))["replay"]["enabled"])

    def test_incomplete_context_does_not_invent_columns_geometry_or_recipes(self):
        for value in (None, [], "source", {"source_id": "fictive", "field_names": "nom", "field_types": [], "geometry": "Point"}):
            with self.subTest(value=value):
                choices = indexed(value)
                self.assertFalse(choices["fields"]["enabled"])
                self.assertFalse(choices["geometry"]["enabled"])
                self.assertFalse(choices["replay"]["enabled"])
        self.assertTrue(indexed(context(field_names=[], feature_count=0))["deliver"]["enabled"])

    def test_build_is_repeatable_and_does_not_mutate_context(self):
        value = context(compatible_recipes=["Préparation A"])
        before = copy.deepcopy(value)
        first = build_intentions(value)
        self.assertEqual(value, before)
        self.assertEqual(first, build_intentions(value))
        first[0]["reason"] = "Modifié dans l'appelant"
        self.assertNotEqual(first, build_intentions(value))


@unittest.skipUnless(QgsApplication.instance(), "Lancer sous tests/run_qgis4.py pour le banc Qt isolé")
class IntentionsPanelTests(unittest.TestCase):
    def setUp(self):
        self.before_layers = set(QgsProject.instance().mapLayers())
        self.panel = IntentionsPanel()
        self.panel.resize(860, 900)
        self.changed, self.continued = [], []
        self.panel.intentionsChanged.connect(lambda value: self.changed.append(list(value)))
        self.panel.continueRequested.connect(lambda value: self.continued.append(list(value)))
        self.panel.set_context(context())
        self.panel.show()
        QApplication.processEvents()

    def tearDown(self):
        self.assertEqual(set(QgsProject.instance().mapLayers()), self.before_layers)
        self.panel.close()
        self.panel.deleteLater()
        QApplication.processEvents()

    def choice(self, identifier):
        return self.panel.findChild(QCheckBox, "transformer_intention_choice_" + identifier)

    def test_context_and_suggestions_never_select_or_continue_automatically(self):
        self.assertEqual(self.panel.selected_intentions(), [])
        self.assertEqual(self.changed, [])
        self.assertEqual(self.continued, [])
        self.assertFalse(self.panel.continue_button.isEnabled())
        self.assertIn("1 234", self.panel.findChild(QLabel, "transformer_intentions_context").text())
        self.assertIn("Ouvrages", self.panel.findChild(QLabel, "transformer_intentions_source").text())

    def test_combined_choices_emit_only_on_explicit_continue(self):
        self.choice("fields").click()
        self.choice("compare").click()
        self.assertEqual(self.panel.selected_intentions(), ["fields", "compare"])
        self.assertEqual(self.changed, [["fields"], ["fields", "compare"]])
        self.assertIn("choisir ou compléter les colonnes", self.panel.findChild(QLabel, "transformer_intentions_selection").text().casefold())
        self.assertIn("comparer avant et après", self.panel.findChild(QLabel, "transformer_intentions_selection").text().casefold())
        self.choice("fields").click()
        self.assertEqual(self.panel.selected_intentions(), ["compare"])
        self.assertNotIn("choisir ou compléter les colonnes", self.panel.findChild(QLabel, "transformer_intentions_selection").text().casefold())
        self.choice("fields").click()
        self.assertEqual(self.continued, [])
        self.panel.continue_button.click()
        self.assertEqual(self.continued, [["fields", "compare"]])

    def test_read_only_context_and_focus_first_choice(self):
        self.panel.set_context(context(geometry=False, read_only=True))
        scope_text = self.panel.findChild(QLabel, "transformer_intentions_context").text()
        self.assertIn("Table sans géométrie", scope_text)
        self.assertIn("Lecture seule", scope_text)
        self.panel.focus_first_choice()
        QApplication.processEvents()
        self.assertTrue(self.choice("clean").hasFocus())
        self.choice("filter").click()
        self.panel.focus_first_choice()
        QApplication.processEvents()
        self.assertTrue(self.choice("filter").hasFocus())

    def test_same_source_retains_valid_choices_and_new_source_clears_them(self):
        self.choice("geometry").click()
        self.choice("compare").click()
        self.panel.set_context(context(geometry=False))
        self.assertEqual(self.panel.selected_intentions(), ["compare"])
        self.panel.set_context(context(source_id="autre-source"))
        self.assertEqual(self.panel.selected_intentions(), [])
        self.assertFalse(self.panel.continue_button.isEnabled())
        self.assertEqual(self.continued, [])

    def test_removed_recipe_and_missing_source_release_unavailable_selections(self):
        self.panel.set_context(context(compatible_recipes=["Exemple existant"]))
        self.choice("replay").click()
        self.panel.set_context(context())
        self.assertFalse(self.choice("replay").isEnabled())
        self.assertEqual(self.panel.selected_intentions(), [])
        self.panel.set_context({})
        self.assertTrue(all(not widget.isEnabled() for widget in self.panel.findChildren(QCheckBox)))
        self.assertIn("entrée", self.panel.findChild(QLabel, "transformer_intentions_source").text())

    def test_space_and_tab_are_native_and_do_not_launch_a_treatment(self):
        first = self.choice("clean")
        first.setFocus()
        QTest.keyClick(first, Qt.Key.Key_Space)
        self.assertEqual(self.panel.selected_intentions(), ["clean"])
        QTest.keyClick(first, Qt.Key.Key_Tab)
        QApplication.processEvents()
        self.assertTrue(self.choice("fields").hasFocus())
        QTest.keyClick(self.choice("fields"), Qt.Key.Key_Space)
        self.assertEqual(self.panel.selected_intentions(), ["clean", "fields"])
        self.assertEqual(self.continued, [])

    def test_compact_keyboard_reveals_choice_and_footer_remains_available(self):
        self.panel.resize(780, 560)
        self.panel.set_context(context(geometry=False))
        QApplication.processEvents()
        target = self.choice("deliver")
        target.setFocus()
        QApplication.processEvents()
        viewport = self.panel._scroll.viewport()
        point = target.mapTo(viewport, target.rect().topLeft())
        self.assertGreaterEqual(point.y(), 0)
        self.assertLessEqual(point.y() + target.height(), viewport.height())
        self.assertEqual(self.panel._scroll.horizontalScrollBar().maximum(), 0)
        footer = self.panel.continue_button.geometry()
        self.assertLessEqual(footer.bottom(), self.panel.height())
        self.assertGreaterEqual(self.panel.continue_button.height(), 42)

    def test_emitted_lists_cannot_change_internal_selection(self):
        self.panel.intentionsChanged.connect(lambda value: value.append("geometry"))
        self.choice("fields").click()
        self.assertEqual(self.panel.selected_intentions(), ["fields"])
        self.panel.continue_button.click()
        self.assertEqual(self.continued, [["fields"]])

    def test_palette_long_context_and_native_render(self):
        palette = self.panel.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#20242b"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#eef0f4"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#171b21"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#eef0f4"))
        self.panel.setPalette(palette)
        self.panel.set_context(context(source_name="Entrée de démonstration longue " * 5,
            compatible_recipes=["Préparation de démonstration"] * 4))
        QApplication.processEvents()
        self.assertFalse(self.panel.grab().isNull())
        self.assertEqual(self.panel._scroll.horizontalScrollBar().maximum(), 0)
        self.assertTrue(self.choice("replay").isEnabled())
        self.assertIn("Préparation de démonstration", self.choice("replay").accessibleDescription())
        capture = os.environ.get("TRANSFORMER_INTENTIONS_CAPTURE")
        if capture:
            self.panel.grab().save(str(Path(capture)))


if __name__ == "__main__":
    unittest.main()
