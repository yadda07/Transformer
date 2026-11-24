# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Parcours guidés intégrés, moteur et livraison réels sur données temporaires.

Exécution uniquement avec tests/run_qgis4.py : réseau, connexions et profil isolés.
Ces quatre scénarios n'importent aucune classe de tests d'un autre module.
"""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qgis.core import (
    QgsApplication, QgsExpression, QgsExpressionContext, QgsFeature, QgsField,
    QgsGeometry, QgsProject, QgsVariantUtils, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEvent, QEventLoop, QMetaType, QTimer, Qt
from qgis.PyQt.QtTest import QSignalSpy
from qgis.PyQt.QtWidgets import QMessageBox

from Transfomer.core.config_manager import ConfigManager
from Transfomer.core.transformer import SimpleTransformer
from Transfomer.export.export_module import ExportFormat
from Transfomer.shared.compat import geometry_equals, meta_type_name
from Transfomer.ui.main_window import EnhancedTransformerDialog


@unittest.skipUnless(QgsApplication.instance() is not None, "Utiliser tests/run_qgis4.py")
class RefonteIntegratedFlowTests(unittest.TestCase):
    NAME = 'nom "usuel" d’équipe'
    INTENTIONS = ["clean", "filter", "compare", "deliver"]

    def setUp(self):
        self.app = QgsApplication.instance()
        self.temp = tempfile.TemporaryDirectory(prefix="transformer-parcours-")
        self.addCleanup(self.temp.cleanup)
        self.dialogs = []

        def record(*args, **kwargs):
            self.dialogs.append(args[1:3])
            return QMessageBox.StandardButton.Ok

        for method in ("warning", "critical", "information"):
            replacement = patch.object(QMessageBox, method, side_effect=record)
            replacement.start()
            self.addCleanup(replacement.stop)
        question = patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard)
        question.start()
        self.addCleanup(question.stop)
        self.layer = self.make_layer("Entrée de démonstration")
        self.manager = ConfigManager(self.temp.name)
        self.window = EnhancedTransformerDialog(self.manager, SimpleTransformer(self.manager))
        self.window.show()
        self.choose_source(self.layer.id())
        self.app.processEvents()
        self.source_before = self.snapshot(self.layer)

    def tearDown(self):
        if self.window._active_transform_task is not None:
            self.window._active_transform_task.cancel()
            self.wait_until(lambda: self.window._active_transform_task is None,
                            "La tâche annulée reste active avant nettoyage", milliseconds=5000)
        self.window._json_pending = False
        self.window._saved_state = self.window._recipe_state()
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QgsProject.instance().removeAllMapLayers()
        self.app.processEvents()

    def make_layer(self, name):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
        self.assertTrue(layer.isValid())
        layer.dataProvider().addAttributes([
            QgsField(self.NAME, QMetaType.Type.QString, "", 60),
            QgsField("valeur", QMetaType.Type.Int),
        ])
        layer.updateFields()
        features = []
        for index, text in enumerate(("  L'équipe Nord  ", "Secteur Sud", "", None)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([text, index + 1])
            feature.setGeometry(QgsGeometry.fromWkt(f"POINT({2 + index / 100} 48)"))
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        layer.updateExtents()
        layer.setReadOnly(True)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def choose_source(self, source_id, recipe=None):
        self.window.auto_load_qgis_layers()
        self.window.refresh_shapefile_list()
        for index in range(self.window.shp_tree.topLevelItemCount()):
            item = self.window.shp_tree.topLevelItem(index)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data.get("source_file") == source_id and data.get("table_name") == recipe:
                self.window.shp_tree.setCurrentItem(item)
                self.app.processEvents()
                return item
        self.fail("Source ou préparation absente de la liste")

    @staticmethod
    def snapshot(layer):
        return {
            "fields": [(field.name(), meta_type_name(field.type())) for field in layer.fields()],
            "crs": layer.crs().authid(),
            "rows": [(feature.id(),
                      tuple(None if QgsVariantUtils.isNull(value) else value for value in feature.attributes()),
                      feature.geometry().asWkt(8)) for feature in layer.getFeatures()],
        }

    def wait_until(self, condition, message, milliseconds=12000):
        """Attente native bornée, sans attendre un signal déjà livré."""
        if condition():
            return
        loop, tick, deadline = QEventLoop(), QTimer(), QTimer()
        errors = []

        def check():
            try:
                if condition():
                    loop.quit()
            except Exception as error:
                errors.append(error)
                loop.quit()

        tick.setInterval(10)
        tick.timeout.connect(check)
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        tick.start()
        deadline.start(milliseconds)
        loop.exec()
        tick.stop()
        deadline.stop()
        if errors:
            raise errors[0]
        self.assertTrue(condition(), message)

    def clean(self, operation):
        rules = self.window.quick_rules
        rules.field_combo.setCurrentIndex(rules.field_combo.findData(self.NAME))
        rules.operation_combo.setCurrentIndex(rules.operation_combo.findData(operation))
        self.assertTrue(rules.apply(), rules.reason_label.text())

    def guided_filter(self, column, operator, value=""):
        self.window.filter_column.setCurrentText(column)
        self.window.filter_operator.setCurrentIndex(self.window.filter_operator.findData(operator))
        self.window.filter_value.setText(value)
        self.window._apply_guided_filter()
        config = self.window.smart_filter.get_filter_config()
        self.assertTrue(config["enabled"], self.window.workspace_message.text())
        expression = QgsExpression(config["expression"])
        self.assertFalse(expression.hasParserError(), expression.parserErrorString())
        return expression

    def matching_values(self, expression):
        context = QgsExpressionContext()
        context.setFields(self.layer.fields())
        result = []
        for feature in self.layer.getFeatures():
            context.setFeature(feature)
            included = expression.evaluate(context)
            self.assertFalse(expression.hasEvalError(), expression.evalErrorString())
            if not QgsVariantUtils.isNull(included) and included:
                result.append(feature["valeur"])
        return result

    def test_objectifs_combines_nettoient_filtrent_creent_et_livrent_un_fichier_relu(self):
        self.window._begin_intentions(self.INTENTIONS)
        self.assertEqual(self.window._chosen_intentions, self.INTENTIONS)
        self.assertEqual(self.window.workspace_stack.currentIndex(), 1)
        self.clean("trim")
        self.clean("upper")
        expression = self.guided_filter(self.NAME, "contains", "L'équipe")
        self.assertEqual(self.matching_values(expression), [1])

        self.window._primary_workspace_action()
        self.assertIsNotNone(self.window._last_control)
        self.assertEqual(self.window._last_control["errors"], [])
        self.assertEqual(self.window._last_control["rows"], 1)
        self.assertEqual(self.window.preview_table.rowCount(), 1)
        self.assertEqual(self.window.preview_table.item(0, 1).text(), "  L'équipe Nord  ")
        self.assertEqual(self.window.preview_table.item(0, 2).text(), "L'ÉQUIPE NORD")
        self.assertFalse(self.window.preview_table.item(0, 2).icon().isNull(), "Le signe de modification ne doit pas dépendre de la seule couleur")
        self.assertIn("Valeur modifiée", self.window.preview_table.item(0, 2).data(Qt.ItemDataRole.AccessibleDescriptionRole))
        self.assertEqual(self.window._result_layers, [], "Comparer ne doit pas lancer le calcul complet")

        self.window._primary_workspace_action()
        self.wait_until(lambda: self.window._active_transform_task is None and bool(self.window._result_layers),
                        "Le moteur n'a pas produit la couche du résultat")
        self.assertEqual(len(self.window._result_layers), 1)
        result = self.window._result_layers[0]
        self.assertNotEqual(result.id(), self.layer.id())
        self.assertEqual(result.featureCount(), 1)
        result_feature = next(result.getFeatures())
        self.assertEqual(result_feature[self.NAME], "L'ÉQUIPE NORD")
        self.assertEqual(result_feature["valeur"], 1)
        self.assertEqual(result.fields().field("valeur").type(), QMetaType.Type.Int)

        self.window._open_result_delivery()
        panel = self.window.delivery_panel
        layer_index = panel.layer_combo.findData(result.id())
        self.assertGreaterEqual(layer_index, 0)
        panel.layer_combo.setCurrentIndex(layer_index)
        format_index = panel.format_combo.findData(ExportFormat.GEOJSON)
        self.assertGreaterEqual(format_index, 0)
        panel.format_combo.setCurrentIndex(format_index)
        destination = Path(self.temp.name) / "résultat vérifié.geojson"
        panel.path_edit.setText(str(destination))
        finished = QSignalSpy(self.window.export_widget.export_finished)
        self.assertTrue(panel.deliver(), panel.delivery_status.text())
        self.wait_until(lambda: len(finished) > 0, "La livraison n'a pas rendu son reçu")
        receipt = finished[-1][0]
        self.assertEqual(receipt["status"], "success", receipt)
        self.assertTrue(destination.is_file())

        reread = QgsVectorLayer(str(destination), "Relecture temporaire", "ogr")
        self.assertTrue(reread.isValid())
        self.assertEqual(reread.featureCount(), result.featureCount())
        self.assertEqual(reread.fields().names(), result.fields().names())
        self.assertEqual(reread.crs().authid(), result.crs().authid())
        reread_feature = next(reread.getFeatures())
        self.assertEqual(reread_feature.attributes(), result_feature.attributes())
        self.assertTrue(geometry_equals(reread_feature.geometry(), result_feature.geometry()))
        reread.dataProvider().invalidateConnections(str(destination))
        from qgis.PyQt import sip
        sip.delete(reread)

        before_ids = set(QgsProject.instance().mapLayers())
        self.assertTrue(panel.open_result(), panel.delivery_status.text())
        opened_ids = set(QgsProject.instance().mapLayers()) - before_ids
        self.assertTrue(opened_ids, "Ouvrir doit ajouter la livraison au projet QGIS")
        opened = [QgsProject.instance().mapLayer(layer_id) for layer_id in opened_ids]
        self.assertTrue(any(layer.isValid() and layer.providerType() == "ogr"
                            and layer.featureCount() == 1 for layer in opened))
        self.assertEqual(self.snapshot(self.layer), self.source_before)
        self.assertTrue(self.layer.readOnly())
        self.assertEqual({entry["operation"] for entry in self.window._run_history},
                         {"Transformation", "Export fichier"})
        self.assertEqual(self.dialogs, [])

    def test_comparaison_perimee_reste_identifiee_et_la_commande_recompare(self):
        self.window._begin_intentions(["clean", "compare"])
        self.window._primary_workspace_action()
        self.assertIsNotNone(self.window._last_control)
        self.assertIn("Aperçu actuel", self.window.recipe_status_label.text())
        previous_cells = [[self.window.preview_table.item(row, column).text()
                           for column in range(self.window.preview_table.columnCount())]
                          for row in range(self.window.preview_table.rowCount())]
        self.clean("trim")
        self.assertIsNone(self.window._last_control)
        self.assertIn("Contrôle à actualiser", self.window.recipe_status_label.text())
        self.assertIn("précédent", self.window.control_status.text().casefold())
        self.assertIn("actualiser", self.window.control_status.text().casefold())
        self.assertEqual(self.window.transform_selected_btn.text(), "Comparer les changements")
        self.assertEqual([[self.window.preview_table.item(row, column).text()
                           for column in range(self.window.preview_table.columnCount())]
                          for row in range(self.window.preview_table.rowCount())], previous_cells)
        self.window._primary_workspace_action()
        self.assertIsNotNone(self.window._last_control)
        self.assertEqual(self.window._last_control["fingerprint"],
                         self.window._state_fingerprint(self.window._recipe_state()))
        self.assertEqual(self.window.preview_table.item(0, 2).text(), "L'équipe Nord")
        self.assertIn("Aperçu actuel", self.window.recipe_status_label.text())
        self.assertEqual(self.window._result_layers, [])
        self.assertEqual(self.snapshot(self.layer), self.source_before)

    def test_retour_aux_objectifs_et_changement_de_source_retrouvent_la_preparation(self):
        self.window._begin_intentions(["clean", "filter", "compare"])
        self.clean("trim")
        self.guided_filter("valeur", "greater", "1")
        self.window._primary_workspace_action()
        self.assertTrue(self.window.save_current_table_config())
        recipe = self.window._loaded_recipe_name
        state = copy.deepcopy(self.window._recipe_state())
        self.window._show_intentions()
        self.assertEqual(self.window.workspace_stack.currentIndex(), 0)
        self.assertEqual(self.window._recipe_state(), state)
        self.window._begin_intentions(["compare", "deliver"])
        self.assertEqual(self.window.stage_tabs.currentIndex(), 3)
        self.assertEqual(self.window._recipe_state(), state)

        other = self.make_layer("Autre entrée temporaire")
        self.choose_source(other.id())
        self.window._begin_intentions(["fields"])
        self.assertEqual(self.window.stage_tabs.currentIndex(), 0)
        self.choose_source(self.layer.id(), recipe)
        self.wait_until(lambda: self.window.workspace_stack.currentIndex() == 1
                        and self.window.stage_tabs.currentIndex() == 3,
                        "Le retour à la préparation n'a pas restauré son étape de comparaison")
        self.assertEqual(self.window._editing_source_id, self.layer.id())
        self.assertEqual(self.window._loaded_recipe_name, recipe)
        self.assertEqual(self.window._recipe_state(), state)
        self.assertEqual(self.snapshot(self.layer), self.source_before)

    def test_conditions_guidees_citent_noms_valeurs_et_distinguent_null_et_nombre(self):
        self.window._begin_intentions(["filter", "compare"])
        for column, operator, value, expected in (
                (self.NAME, "equal", "  L'équipe Nord  ", [1]),
                (self.NAME, "contains", "L'équipe", [1]),
                (self.NAME, "null", "", [4]),
                ("valeur", "greater", "2,5", [3, 4])):
            with self.subTest(operator=operator):
                expression = self.guided_filter(column, operator, value)
                self.assertEqual(self.matching_values(expression), expected)
        previous = copy.deepcopy(self.window.smart_filter.get_filter_config())
        self.window.filter_value.setText("2 OR 1=1")
        self.window._apply_guided_filter()
        self.assertEqual(self.window.smart_filter.get_filter_config(), previous)
        self.assertIn("nombre", self.window.workspace_message.text().casefold())
        self.assertEqual(self.snapshot(self.layer), self.source_before)

    def test_resultat_supprime_nativement_ne_casse_pas_ouverture_de_livraison(self):
        from qgis.PyQt import sip

        self.window._begin_intentions(["compare", "deliver"])
        self.window._primary_workspace_action()
        self.assertIsNotNone(self.window._last_control)
        self.window._primary_workspace_action()
        self.wait_until(lambda: self.window._active_transform_task is None and bool(self.window._result_layers),
                        "Le résultat à retirer n'a pas été créé")
        result = self.window._result_layers[0]
        result_id = result.id()
        self.assertIsNotNone(QgsProject.instance().mapLayer(result_id))
        QgsProject.instance().removeMapLayer(result_id)
        self.assertTrue(sip.isdeleted(result), "Le scénario doit détruire l'objet Qt, pas seulement vider la liste")

        self.window._open_result_delivery()
        panel = self.window.delivery_panel
        self.assertIsNone(panel.layer_combo.currentData())
        self.assertFalse(panel.deliver_button.isEnabled())
        self.assertFalse(panel.open_button.isEnabled())
        self.assertFalse(panel.deliver())
        self.assertFalse(panel.open_result())
        self.assertIn("résultat", panel.delivery_status.text().casefold())
        self.assertEqual(self.snapshot(self.layer), self.source_before)

    def test_objectifs_sans_regle_avancent_par_etapes_sans_application_automatique(self):
        before = copy.deepcopy(self.window._recipe_state())
        self.window._begin_intentions(["clean", "fields", "filter", "geometry", "compare"])
        self.assertEqual(self.window.stage_tabs.currentIndex(), 0)
        self.assertEqual(self.window.transform_selected_btn.text(), "Choisir les lignes")
        self.assertEqual(self.window._recipe_state(), before)

        for stage, next_action in ((1, "Transformer la forme"),
                                   (2, "Comparer les changements"),
                                   (3, "Créer le résultat")):
            with self.subTest(stage=stage):
                self.window._primary_workspace_action()
                self.assertEqual(self.window.stage_tabs.currentIndex(), stage)
                self.assertEqual(self.window.transform_selected_btn.text(), next_action)
                self.assertEqual(self.window._recipe_state(), before)
                self.assertIsNone(self.window._active_transform_task)
                self.assertEqual(self.window._result_layers, [])
                self.assertEqual(self.snapshot(self.layer), self.source_before)
                if stage != 3:
                    self.assertIsNone(self.window._last_control)
        self.assertIsNotNone(self.window._last_control)
        self.assertEqual(self.window._last_control["errors"], [])
        self.assertEqual(self.window._last_control["rows"], self.layer.featureCount())
        self.assertEqual(self.dialogs, [])

    def test_rejeu_geojson_enregistre_rend_le_bilan_et_ouverture_dans_le_panneau(self):
        destination = Path(self.temp.name) / "rejeu enregistré.geojson"
        expected_destination = {
            "kind": "file", "format": ExportFormat.GEOJSON.value,
            "path": str(destination), "encoding": "utf-8",
            "selected_only": False, "replay": True,
        }
        self.window._recipe_destination = copy.deepcopy(expected_destination)
        self.window._refresh_destination_label()
        self.window._on_recipe_edited()
        self.assertTrue(self.window.save_current_table_config())
        recipe = self.window._loaded_recipe_name
        saved = ConfigManager(self.temp.name).get_table_config(recipe)
        self.assertEqual(saved["destination"], expected_destination)
        self.window._apply_table_config(recipe, saved)
        self.window._restore_selection((self.layer.id(), recipe))
        self.assertTrue(self.window.replay_destination_cb.isChecked())
        self.window._begin_intentions(["compare", "deliver"])
        self.window._primary_workspace_action()
        self.assertIsNotNone(self.window._last_control)
        finished = QSignalSpy(self.window.export_widget.export_finished)
        self.window._primary_workspace_action()
        self.wait_until(lambda: len(finished) > 0,
                        "Le rejeu de la destination enregistrée n'a pas rendu de reçu")
        receipt = finished[-1][0]
        self.assertEqual(receipt["status"], "success", receipt)
        self.assertTrue(destination.is_file())
        self.assertEqual(self.window._active_transform_task, None)

        panel = self.window.delivery_panel
        self.assertEqual(self.window.main_tabs.currentIndex(), 1)
        self.assertEqual(panel.format_combo.currentData(), ExportFormat.GEOJSON)
        self.assertEqual(panel.layer_combo.currentData(), self.window._result_layers[0].id())
        self.assertTrue(panel.open_button.isEnabled(), panel.delivery_status.text())
        self.assertIn(str(destination), panel.delivery_status.text())
        self.assertEqual(self.window.export_widget.get_selected_encoding(), "utf-8")
        before_ids = set(QgsProject.instance().mapLayers())
        self.assertTrue(panel.open_result(), panel.delivery_status.text())
        opened_ids = set(QgsProject.instance().mapLayers()) - before_ids
        self.assertEqual(len(opened_ids), 1)
        reread = QgsProject.instance().mapLayer(opened_ids.pop())
        self.assertTrue(reread.isValid())
        self.assertEqual(reread.providerType(), "ogr")
        self.assertEqual(reread.featureCount(), self.layer.featureCount())
        self.assertEqual(reread.fields().names(), self.layer.fields().names())
        self.assertEqual(self.snapshot(self.layer), self.source_before)
        self.assertEqual(self.dialogs, [])

    def test_r01_r02_r03_contextes_sans_couche_table_sans_geometrie_lecture_seule_et_retrait_intention(self):
        # Ouverture directe dans l'atelier avec bandeau d'actions rapides
        self.assertEqual(self.window.workspace_stack.currentIndex(), 1)
        self.assertTrue(self.window.context_banner.isVisible())
        self.assertFalse(self.window.workspace_doc_btn.icon().isNull())
        self.assertTrue(self.window.open_documentation_dock())
        self.assertTrue(self.window.doc_dock.isVisible())
        self.window.doc_dock.hide()
        from qgis.PyQt.QtCore import QTranslator, QCoreApplication
        i18n_root = Path(__file__).resolve().parent.parent / "i18n"
        for lang, expected in (("fr", "Aide"), ("en", "Help")):
            tr = QTranslator()
            self.assertTrue(tr.load(str(i18n_root / f"Transformer_{lang}.qm")))
            QCoreApplication.installTranslator(tr)
            try:
                self.assertEqual(QCoreApplication.translate("Transformer", "Aide"), expected)
            finally:
                QCoreApplication.removeTranslator(tr)
        self.window.banner_clean_btn.click()
        self.assertEqual(self.window.stage_tabs.currentIndex(), 0)
        self.assertTrue(self.window.quick_rules.isVisible())
        self.window.banner_filter_btn.click()
        self.assertEqual(self.window.stage_tabs.currentIndex(), 1)
        self.window.banner_geom_btn.click()
        self.assertEqual(self.window.stage_tabs.currentIndex(), 2)
        self.window.banner_close_btn.click()
        self.assertFalse(self.window.context_banner.isVisible())

        # R03 : retrait d'une intention après retour aux objectifs, sans transformation implicite
        self.window._begin_intentions(["clean", "filter", "compare"])
        self.assertTrue(self.window.quick_rules.isVisible())
        self.window.workspace_back.click()
        self.app.processEvents()
        self.assertEqual(self.window.workspace_stack.currentIndex(), 0)
        self.window.intentions_panel.skip_button.click()
        self.assertEqual(self.window.workspace_stack.currentIndex(), 1)
        self.window.workspace_back.click()
        self.window._begin_intentions(["filter", "compare"])
        self.assertEqual(self.window._chosen_intentions, ["filter", "compare"])
        self.assertFalse(self.window.quick_rules.isVisible())
        self.assertEqual(self.window.stage_tabs.currentIndex(), 1)
        self.assertEqual(self.window._result_layers, [])

        # R02 : table sans géométrie en lecture seule
        table = QgsVectorLayer("None?field=code:string&field=montant:double", "Table comptable", "memory")
        feat = QgsFeature(table.fields())
        feat.setAttributes(["  c-01  ", 125.5])
        self.assertTrue(table.dataProvider().addFeatures([feat])[0])
        table.setReadOnly(True)
        QgsProject.instance().addMapLayer(table)
        self.choose_source(table.id())
        self.assertIsNotNone(self.window.shp_tree.currentItem())
        self.assertFalse(self.window.shp_tree.currentItem().icon(0).isNull())
        scope_label = self.window.intentions_panel.findChild(type(self.window.recipe_source_label), "transformer_intentions_context")
        self.assertIn("Table sans géométrie", scope_label.text())
        self.assertIn("Lecture seule", scope_label.text())
        self.assertFalse(self.window.stage_tabs.isTabEnabled(2))
        self.window._begin_intentions(["clean", "compare"])
        self.window.quick_rules.field_combo.setCurrentIndex(self.window.quick_rules.field_combo.findData("code"))
        self.window.quick_rules.operation_combo.setCurrentIndex(self.window.quick_rules.operation_combo.findData("trim"))
        self.assertTrue(self.window.quick_rules.apply())
        self.assertTrue(self.window.test_configuration())
        self.assertEqual(self.window.preview_table.item(0, 2).text(), "c-01")
        self.assertEqual(self.window.preview_table.item(0, 5).text(), "Sans géométrie")

        # R01 : ouverture / projet sans couche disponible
        QgsProject.instance().removeAllMapLayers()
        self.window.on_project_cleared()
        self.app.processEvents()
        self.assertTrue(self.window.empty_sources_label.isVisible())
        self.assertIn("bibliothèque", self.window.recipe_source_label.text().casefold())

    def test_r12_r13_compact_1024x700_police_agrandie_sombre_mouvement_reduit_et_authcfg_sans_secret(self):
        import json
        from qgis.PyQt.QtGui import QColor, QFont, QPalette
        from Transfomer.pg.postgresql_integration import PostgreSQLConfigWidget

        # R13 : 1024x700, police agrandie, thème sombre et mouvement réduit
        self.window.resize(1024, 700)
        big_font = QFont(self.window.font())
        big_font.setPointSizeF(max(11.0, big_font.pointSizeF() * 1.2))
        self.window.setFont(big_font)
        dark = QPalette(self.window.palette())
        dark.setColor(QPalette.ColorRole.Window, QColor("#20262d"))
        dark.setColor(QPalette.ColorRole.Base, QColor("#171e25"))
        dark.setColor(QPalette.ColorRole.WindowText, QColor("#eef3f6"))
        dark.setColor(QPalette.ColorRole.Text, QColor("#eef3f6"))
        dark.setColor(QPalette.ColorRole.Button, QColor("#27323d"))
        dark.setColor(QPalette.ColorRole.ButtonText, QColor("#eef3f6"))
        dark.setColor(QPalette.ColorRole.Highlight, QColor("#76b9f4"))
        dark.setColor(QPalette.ColorRole.HighlightedText, QColor("#102638"))
        self.window.setPalette(dark)
        self.window.setProperty("fluentReducedMotion", True)
        self.window.apply_theme()
        self.app.processEvents()
        self.assertLessEqual(self.window.intentions_panel.continue_button.geometry().bottom(),
                             self.window.intentions_panel.height())
        self.window._begin_intentions(["clean", "compare"])
        self.app.processEvents()
        self.assertTrue(self.window.save_recipe_button.isVisible())
        self.assertTrue(self.window.transform_selected_btn.isVisible())
        self.assertIn("recette", self.window.save_recipe_button.toolTip().casefold())

        # R19 / O28 : aucun secret en clair dans recette, connexions PostgreSQL ou diagnostic anonymisé
        bad_doc = {"version": "1.2", "tables": {" fuite ": {"calculated_fields": {"a": '"valeur"'}, "destination": {"password": "secret"}}}}
        errors = self.manager._validate_document(bad_doc)
        self.assertTrue(any("secrets" in err.casefold() for err in errors))

        pg_file = Path(self.temp.name) / "pg_connections.json"
        with patch.object(PostgreSQLConfigWidget, "_connections_path", return_value=str(pg_file)), \
                patch.object(PostgreSQLConfigWidget, "_legacy_path", return_value=str(Path(self.temp.name) / "none.json")), \
                patch.object(PostgreSQLConfigWidget, "auto_test_connection", return_value=None):
            pg_widget = PostgreSQLConfigWidget()
            self.addCleanup(pg_widget.deleteLater)
            pg_widget._config_dir = str(self.temp.name)
            pg_widget._connections["Prod"] = {
                "host": "db.interne", "port": 5432, "database": "sig",
                "username": "operateur", "password": "mot-de-passe-interdit", "authcfg": "cfg7890",
            }
            self.assertTrue(pg_widget._write_all_profiles())
            raw_saved = pg_file.read_text(encoding="utf-8")
            self.assertNotIn("mot-de-passe-interdit", raw_saved)
            self.assertIn("cfg7890", raw_saved)

        diag = json.dumps(self.window.build_anonymized_diagnostic(), ensure_ascii=False)
        self.assertNotIn("L'équipe Nord", diag)
        self.assertNotIn("mot-de-passe-interdit", diag)


if __name__ == "__main__":
    unittest.main()
