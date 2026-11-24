# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Règles guidées natives, sur couches mémoire et sans écriture de la source."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from qgis.core import (
    QgsApplication, QgsExpression, QgsExpressionContext, QgsFeature, QgsField,
    QgsVariantUtils, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEvent, QMetaType, Qt
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtTest import QSignalSpy, QTest
from qgis.PyQt.QtWidgets import QPushButton

from Transfomer.widgets.field_definition_dialog import FieldDefinitionDialog
from Transfomer.widgets.field_widget import FieldWidget
from Transfomer.widgets.quick_rules import QuickRules


@unittest.skipUnless(QgsApplication.instance() is not None, "Utiliser le runner QGIS 4 isolé")
class QuickRulesTests(unittest.TestCase):
    NAME = 'nom "usuel" d’équipe'

    def setUp(self):
        self.app = QgsApplication.instance()
        self.layer = QgsVectorLayer("Point?crs=EPSG:2154", "Source temporaire", "memory")
        provider = self.layer.dataProvider()
        provider.addAttributes([
            QgsField(self.NAME, QMetaType.Type.QString, "", 40, 0, "Nom source"),
            QgsField("compte", QMetaType.Type.Int),
        ])
        self.layer.updateFields()
        features = []
        for value in ("  Élise d'Or  ", "", "   ", None):
            feature = QgsFeature(self.layer.fields())
            feature.setAttributes([value, 7])
            features.append(feature)
        self.assertTrue(provider.addFeatures(features)[0])
        self.layer.setReadOnly(True)
        self.widget = FieldWidget()
        self.widget.set_layer(self.layer)
        self.widget.set_calculated_fields({
            self.NAME: QgsExpression.quotedColumnRef(self.NAME),
            "compte": QgsExpression.quotedColumnRef("compte"),
        })
        self.rules = QuickRules(self.widget)
        self.rules.set_source(self.layer)
        self.addCleanup(self.widget.deleteLater)
        self.addCleanup(self.rules.deleteLater)

    def choose(self, operation, name=None):
        index = self.rules.field_combo.findData(name or self.NAME)
        self.assertGreaterEqual(index, 0)
        self.rules.field_combo.setCurrentIndex(index)
        self.rules.operation_combo.setCurrentIndex(self.rules.operation_combo.findData(operation))

    def values(self):
        expression = QgsExpression(self.widget.get_calculated_fields()[self.NAME])
        self.assertFalse(expression.hasParserError(), expression.parserErrorString())
        context = QgsExpressionContext()
        context.setFields(self.layer.fields())
        results = []
        for feature in self.layer.getFeatures():
            context.setFeature(feature)
            result = expression.evaluate(context)
            self.assertFalse(expression.hasEvalError(), expression.evalErrorString())
            results.append(None if QgsVariantUtils.isNull(result) else result)
        return results

    def test_changer_source_et_choix_ne_modifie_pas_la_recette(self):
        before = deepcopy(self.widget.calculated_fields)
        changed = QSignalSpy(self.rules.changed)
        self.choose("upper")
        self.rules.set_source(self.layer)
        self.assertEqual(self.widget.calculated_fields, before)
        self.assertEqual(len(changed), 0)
        self.assertTrue(self.rules.apply_button.isEnabled())
        self.rules.set_source(None)
        self.assertFalse(self.rules.apply_button.isEnabled())
        self.assertIn("couche", self.rules.reason_label.text())
        self.assertEqual(self.widget.calculated_fields, before)

    def test_espaces_et_casse_se_composent_sans_modifier_les_valeurs_source(self):
        before = [f.attributes() for f in self.layer.getFeatures()]
        modified = QSignalSpy(self.widget.field_modified)
        changed = QSignalSpy(self.rules.changed)
        for operation in ("trim", "upper", "lower"):
            self.choose(operation)
            self.assertTrue(self.rules.apply())
        self.assertEqual(self.values(), ["élise d'or", "", "", None])
        self.assertEqual(len(modified), 3)
        self.assertEqual(len(changed), 3)
        self.assertEqual([f.attributes() for f in self.layer.getFeatures()], before)
        definition = self.widget.get_field_definitions()[self.NAME]
        self.assertEqual(definition["type"], "Text")
        self.assertEqual(definition["description"], "Nom source")
        self.assertEqual(definition["length"], 0)
        self.assertEqual(self.widget.get_field_definitions()["compte"]["type"], "Integer")

    def test_texte_de_remplacement_apostrophe_et_antislash_est_cite_par_qgis(self):
        self.choose("fill")
        self.assertFalse(self.rules.apply())
        self.assertIn("Saisissez", self.rules.reason_label.text())
        replacement = "L'équipe \\ secteur\nNord"
        self.rules.replacement_edit.setText(replacement)
        self.assertTrue(self.rules.apply())
        self.assertEqual(self.values(), ["  Élise d'Or  ", replacement, replacement, replacement])

    def test_nettoyage_texte_refuse_nombres_sans_coercition_implicite(self):
        self.choose("upper", "compte")
        before = deepcopy(self.widget.calculated_fields)
        self.assertFalse(self.rules.apply_button.isEnabled())
        self.assertFalse(self.rules.apply())
        self.assertIn("nombres", self.rules.reason_label.text())
        self.assertEqual(self.widget.calculated_fields, before)

    def test_appliquer_ne_lit_pas_les_objets_et_n_entre_pas_en_edition(self):
        self.choose("trim")
        with patch.object(self.layer, "getFeatures", side_effect=AssertionError("Lecture d'objets interdite")):
            self.rules.set_source(self.layer)
            self.assertTrue(self.rules.apply())
        self.assertFalse(self.layer.isEditable())
        self.assertTrue(self.layer.readOnly())

    def test_annulation_restaure_expression_description_et_type(self):
        before = deepcopy(self.widget.calculated_fields[self.NAME])
        definition = deepcopy(self.widget.get_field_definitions()[self.NAME])
        self.choose("upper")
        self.assertTrue(self.rules.apply())
        self.assertTrue(self.rules.undo_button.isEnabled())
        self.assertTrue(self.rules.undo())
        self.assertEqual(self.widget.calculated_fields[self.NAME], before)
        self.assertEqual(self.widget.get_field_definitions()[self.NAME], definition)
        self.assertFalse(self.rules.undo_button.isEnabled())

    def test_annulation_necrase_pas_une_regle_experte_plus_recente(self):
        self.choose("trim")
        self.assertTrue(self.rules.apply())
        self.widget.apply_guided_rule(self.NAME, "'Modification experte'", {"type": "Text"})
        self.assertFalse(self.rules.undo_button.isEnabled())
        self.assertFalse(self.rules.undo())
        self.assertEqual(self.widget.get_calculated_fields()[self.NAME], "'Modification experte'")

    def test_source_changee_invalide_une_application_et_l_annulation(self):
        self.choose("trim")
        self.assertTrue(self.rules.apply())
        self.widget.set_layer(None)
        before = deepcopy(self.widget.calculated_fields)
        self.assertFalse(self.rules.apply())
        self.assertFalse(self.rules.undo())
        self.assertEqual(self.widget.calculated_fields, before)

    def test_expression_existante_invalide_est_refusee_sans_mutation(self):
        self.widget.apply_guided_rule(self.NAME, "upper(")
        self.choose("trim")
        before = deepcopy(self.widget.calculated_fields)
        self.assertFalse(self.rules.apply())
        self.assertEqual(self.widget.calculated_fields, before)
        self.assertIn("Vérifiez", self.rules.result_label.text())

    def test_boutons_de_la_factory_sont_utilises_et_clic_clavier_applique(self):
        created = []

        def factory(text, parent=None):
            button = QPushButton(text, parent)
            created.append(button)
            return button

        rules = QuickRules(self.widget, button_factory=factory)
        self.addCleanup(rules.deleteLater)
        rules.set_source(self.layer)
        rules.resize(700, 360)
        rules.show()
        self.app.processEvents()
        self.assertEqual(created, [rules.apply_button, rules.undo_button])
        changed = QSignalSpy(rules.changed)
        rules.apply_button.setFocus()
        QTest.keyClick(rules.apply_button, Qt.Key.Key_Space)
        self.assertEqual(len(changed), 1)
        self.assertTrue(self.widget.get_calculated_fields()[self.NAME].startswith("trim("))
        rules.close()

    def test_matrice_selection_et_lignes_suivent_la_police_et_le_clavier(self):
        font = self.widget.font()
        font.setPointSize(18)
        self.widget.setFont(font)
        self.widget.resize(800, 440)
        self.widget.show()
        self.app.processEvents()
        tree = self.widget.fields_tree
        item = tree.topLevelItem(0)
        tree.setCurrentItem(item)
        tree.setFocus()
        self.assertGreaterEqual(tree.visualItemRect(item).height(), tree.fontMetrics().height() + 12)
        self.assertIn(self.NAME, self.widget.selection_help.text())
        with patch.object(self.widget, "edit_selected_field") as edit:
            QTest.keyClick(tree, Qt.Key.Key_F2)
            repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F2,
                               Qt.KeyboardModifier.NoModifier, "", True, 1)
            self.app.sendEvent(tree, repeat)
            self.assertEqual(edit.call_count, 1)
        self.widget.close()

    def test_dialogue_guide_le_type_sans_perdre_metadonnees_ni_copie(self):
        dialog = FieldDefinitionDialog(existing_names={self.NAME}, original_name=self.NAME)
        self.addCleanup(dialog.deleteLater)
        definition = {"type": "Real", "length": 18, "precision": 4, "description": "Surface en m²"}
        dialog.set_field_info("Surface")
        dialog.set_field_definition(definition)
        self.assertEqual(dialog.get_field_definition(), definition)
        self.assertIn("mesures", dialog.type_help.text())
        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("Boolean"))
        self.assertFalse(dialog.precision_spin.isEnabled())
        self.assertIn("absente", dialog.type_help.text())
        self.assertEqual(definition, {"type": "Real", "length": 18, "precision": 4, "description": "Surface en m²"})


if __name__ == "__main__":
    unittest.main()
