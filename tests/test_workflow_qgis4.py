# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Scénarios de travail réels sur widgets Qt6 et sources QGIS fictives."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qgis.core import QgsApplication,QgsProject,QgsVectorLayer,QgsFeature,QgsGeometry
from qgis.PyQt.QtCore import Qt,QSignalBlocker
from qgis.PyQt.QtGui import QCloseEvent
from qgis.PyQt.QtWidgets import QMessageBox,QInputDialog,QFileDialog
from Transfomer.core.config_manager import ConfigManager
from Transfomer.core.transformer import SimpleTransformer
from Transfomer.ui.main_window import EnhancedTransformerDialog
from Transfomer.widgets.preferences_dialog import PreferencesDialog


@unittest.skipUnless(QgsApplication.instance(),'Lancer avec tests/run_qgis4.py dans QGIS4')
class WorkspaceFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dialogs=[]
        def warn(*args,**kwargs):
            self.dialogs.append(args[1:3])
            return QMessageBox.StandardButton.Ok
        self.patches=[patch.object(QMessageBox,'warning',side_effect=warn),patch.object(QMessageBox,'critical',side_effect=warn),patch.object(QMessageBox,'information',side_effect=warn),patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Discard)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.layer=self.make_layer('Livraison',3)
        self.manager=ConfigManager(self.temp.name)
        self.window=EnhancedTransformerDialog(self.manager,SimpleTransformer(self.manager))
        self.window.show()
        self.choose_source(self.layer.id())

    def tearDown(self):
        self.window._json_pending=False
        self.window._saved_state=self.window._recipe_state()
        self.window.close()
        self.window.deleteLater()
        QgsProject.instance().removeAllMapLayers()
        QgsApplication.processEvents()

    def make_layer(self,name,count):
        layer=QgsVectorLayer('Point?crs=EPSG:2154&field=code:string&field=valeur:integer',name,'memory')
        features=[]
        for index in range(count):
            feature=QgsFeature(layer.fields())
            feature.setAttributes([f'A{index}',index])
            feature.setGeometry(QgsGeometry.fromWkt(f'POINT({650000+index} 6800000)'))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def choose_source(self,source_id,recipe=None):
        self.window.auto_load_qgis_layers()
        self.window.refresh_shapefile_list()
        for index in range(self.window.shp_tree.topLevelItemCount()):
            item=self.window.shp_tree.topLevelItem(index)
            data=item.data(0,Qt.ItemDataRole.UserRole)
            if data.get('source_file')==source_id and data.get('table_name')==recipe:
                self.window.shp_tree.setCurrentItem(item)
                return item
        self.fail('Source ou recette absente de la liste')

    def test_save_and_reopen_keep_geometry_crs_and_field_types(self):
        self.window.geometry_expression_edit.setText('centroid($geometry)')
        self.window.set_target_crs('EPSG:4326','WGS84')
        self.assertTrue(self.window.save_current_table_config())
        name=self.window._loaded_recipe_name
        manager=ConfigManager(self.temp.name)
        saved=manager.get_table_config(name)
        self.assertEqual(saved['source_id'],self.layer.id())
        self.assertEqual(saved['geometry_expression'],'centroid($geometry)')
        self.assertEqual(saved['target_crs'],'EPSG:4326')
        self.assertEqual(saved['field_definitions']['valeur']['type'],'Integer')
        self.window._apply_table_config(name,saved)
        self.assertEqual(self.window.geometry_expression_edit.text(),'centroid($geometry)')
        self.assertEqual(self.window._recipe_state()['geometry_expression'],'centroid($geometry)')
        self.assertFalse(self.window.has_unsaved_changes())

    def test_filter_only_changes_are_dirty_and_disabling_keeps_expression(self):
        self.assertTrue(self.window.save_current_table_config())
        self.window.smart_filter.set_filter_expression('"valeur" > 0')
        self.assertTrue(self.window.has_unsaved_changes())
        self.window.smart_filter.enable_filter_cb.setChecked(False)
        state=self.window._recipe_state()['filter']
        self.assertFalse(state['enabled'])
        self.assertEqual(state['expression'],'"valeur" > 0')
        self.assertTrue(self.window.save_current_table_config())
        self.assertEqual(self.manager.get_table_config(self.window._loaded_recipe_name)['filter'],state)

    def test_disk_failure_does_not_close_or_erase_draft(self):
        self.assertTrue(self.window.save_current_table_config())
        before=Path(self.manager.config_file).read_bytes()
        self.window.geometry_expression_edit.setText('centroid($geometry)')
        event=QCloseEvent()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save),patch.object(self.manager,'save_config',return_value=False):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.window.has_unsaved_changes())
        self.assertEqual(Path(self.manager.config_file).read_bytes(),before)
        self.assertEqual(self.window.geometry_expression_edit.text(),'centroid($geometry)')

    def test_selection_cancel_preserves_the_working_source(self):
        self.window.geometry_expression_edit.setText('centroid($geometry)')
        other=self.make_layer('Deuxième livraison',1)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):
            self.choose_source(other.id())
        self.assertEqual(self.window._editing_source_id,self.layer.id())
        self.assertEqual(self.window.geometry_expression_edit.text(),'centroid($geometry)')
        self.assertEqual(self.window._selected_data().get('source_file'),self.layer.id())

    def test_two_homonymous_sources_remain_distinct(self):
        other=self.make_layer(self.layer.name(),1)
        self.window.auto_load_qgis_layers()
        self.assertEqual(set(self.window.loaded_shapefiles),{self.layer.id(),other.id()})

    def test_recipe_without_source_remains_visible_and_not_aliased(self):
        self.manager.add_table_config('Recette absente','Livraison',{'code':'"code"'},source_id='absent-layer-id')
        self.window.refresh_shapefile_list()
        found=[self.window._selected_data(self.window.shp_tree.topLevelItem(i)) for i in range(self.window.shp_tree.topLevelItemCount())]
        self.assertIn({'source_file':None,'table_name':'Recette absente'},found)
        self.assertEqual(self.manager.cleanup_missing_sources(),0)
        self.assertTrue(self.manager.has_table_config('Recette absente'))

    def test_selected_recipe_does_not_expand_to_other_recipes_of_source(self):
        for name in ('premiere','deuxieme'):
            self.manager.add_table_config(name,self.layer.name(),{'code':'"code"'},source_id=self.layer.id())
        item=self.choose_source(self.layer.id(),'premiere')
        items=self.window._snapshot_selected_transform_items([item,item])
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['table_names'],['premiere'])

    def test_json_requires_explicit_apply_and_cannot_silently_overwrite_rules(self):
        self.assertTrue(self.window.save_current_table_config())
        original=copy.deepcopy(self.window._recipe_state())
        self.window.config_preview.setPlainText('{invalid')
        self.assertFalse(self.window.save_current_table_config())
        self.assertEqual(self.window._recipe_state(),original)
        self.assertFalse(self.window.apply_json_changes())
        state=copy.deepcopy(original)
        state['geometry_expression']='centroid($geometry)'
        self.window.config_preview.setPlainText(json.dumps(state))
        self.assertTrue(self.window.apply_json_changes())
        self.assertEqual(self.window.geometry_expression_edit.text(),'centroid($geometry)')
        self.assertTrue(self.window.has_unsaved_changes())

    def test_preview_is_bounded_and_invalidated_by_source_change(self):
        large=self.make_layer('Grande livraison',80)
        self.choose_source(large.id())
        self.assertTrue(self.window.test_configuration())
        self.assertEqual(self.window._last_control['read'],50)
        self.assertEqual(self.window.preview_table.rowCount(),50)
        large.dataChanged.emit()
        self.assertIsNone(self.window._last_control)
        self.assertIn('actualiser',self.window.control_status.text())

    def test_preferences_and_native_help_tabs_construct(self):
        dialog=PreferencesDialog(self.window.interface_settings,self.window)
        self.assertIsNotNone(dialog)
        self.assertIsInstance(self.window.help_dock.widget(),type(self.window.stage_tabs))
        self.assertEqual(self.window.help_dock.widget().count(),4)
        dialog.reject()

    def test_native_layout_fits_compact_window_without_advanced_docks(self):
        self.window.resize(1024,700)
        QgsApplication.processEvents()
        self.assertLessEqual(self.window.width(),1024)
        self.assertLessEqual(self.window.height(),700)
        self.assertFalse(self.window.config_dock.isVisible())
        self.assertFalse(self.window.log_dock.isVisible())
        self.assertTrue(self.window.stage_tabs.isVisible())
        self.assertTrue(self.window.context_banner.isVisible())

    def test_preview_uses_saved_geometric_rule_instead_of_editor_side_state(self):
        self.window.geometry_expression_edit.setText('centroid($geometry)')
        self.assertTrue(self.window.test_configuration())
        geometry=self.window.preview_table.item(0,self.window.preview_table.columnCount()-1).text()
        self.assertTrue(geometry.lower().startswith('point'))

    def test_destination_and_replay_choice_survive_recipe_reload(self):
        self.assertTrue(self.window.save_current_table_config())
        name=self.window._loaded_recipe_name
        self.window._on_file_export_requested({'layers':[name],'destinations':[str(Path(self.temp.name)/'delivery.geojson')],'format':'GeoJSON','selected_only':False})
        self.window.replay_destination_cb.setChecked(True)
        self.assertTrue(self.window.has_unsaved_changes())
        self.assertTrue(self.window.save_current_table_config())
        saved=ConfigManager(self.temp.name).get_table_config(name)
        self.assertEqual(saved['destination']['kind'],'file')
        self.assertTrue(saved['destination']['replay'])
        self.window._apply_table_config(name,saved)
        self.assertTrue(self.window.replay_destination_cb.isChecked())

    def test_full_recipe_run_and_file_delivery_produce_a_distinct_receipt(self):
        from qgis.PyQt.QtCore import QEventLoop,QTimer
        from Transfomer.export.export_module import ExportFormat
        path=Path(self.temp.name)/'replayed.geojson'
        self.window._recipe_destination={'kind':'file','format':ExportFormat.GEOJSON.value,'path':str(path),'encoding':'utf-8','selected_only':False,'replay':True}
        self.window._refresh_destination_label()
        loop=QEventLoop()
        result=[]
        self.window.export_widget.export_finished.connect(lambda value:(result.append(value),loop.quit()))
        timer=QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.assertTrue(self.window.transform_selected_shapefile())
        timer.start(15000)
        loop.exec()
        timer.stop()
        self.assertTrue(result,'La livraison fichier n’a pas rendu de reçu dans le délai du scénario.')
        self.assertEqual(result[0]['status'],'success',result)
        self.assertTrue(path.exists())
        output=QgsVectorLayer(str(path),'relecture','ogr')
        self.assertTrue(output.isValid())
        self.assertEqual(output.featureCount(),3)
        self.assertEqual({row['operation'] for row in self.window._run_history},{'Transformation','Export fichier'})
        self.assertEqual(len(self.window._run_history[0]['plan']),1)
        self.assertEqual(self.window._run_history[0]['plan'][0]['source_id'],self.layer.id())
        from qgis.PyQt import sip
        output.dataProvider().invalidateConnections(str(path))
        sip.delete(output)

    def test_saving_before_switch_keeps_tree_and_editor_on_requested_recipe(self):
        self.assertTrue(self.window.save_current_table_config())
        other=self.make_layer('Autre entrée',1)
        self.manager.add_table_config('autre_recette',other.name(),{'code':'"code"'},source_id=other.id())
        self.window.geometry_expression_edit.setText('centroid($geometry)')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save):
            self.choose_source(other.id(),'autre_recette')
        self.assertEqual(self.window._editing_source_id,other.id())
        self.assertEqual(self.window._loaded_recipe_name,'autre_recette')
        selected=[self.window._selected_data(item) for item in self.window.shp_tree.selectedItems()]
        self.assertEqual(selected,[{'source_file':other.id(),'table_name':'autre_recette'}])

    def test_copy_with_failed_save_is_still_a_protected_draft(self):
        with patch.object(QInputDialog,'getText',return_value=('copie_protegee',True)),patch.object(self.manager,'save_config',return_value=False):
            self.window.duplicate_current_configuration()
        self.assertEqual(self.window.table_name_edit.text(),'copie_protegee')
        self.assertTrue(self.window.has_unsaved_changes())
        self.assertFalse(self.manager.has_table_config('copie_protegee'))

    def test_json_candidate_is_fully_checked_before_mutating_editor(self):
        before=copy.deepcopy(self.window._recipe_state())
        candidates=[]
        for key,value in [('target_crs','EPSG:999999'),('destination','invalid'),('filter',{'enabled':'yes','expression':''}),('field_definitions',{'code':{'type':'Unknown'}})]:
            state=copy.deepcopy(before)
            state[key]=value
            candidates.append(state)
        reserved=copy.deepcopy(before)
        reserved['calculated_fields']['Geometry']='"code"'
        candidates.append(reserved)
        for state in candidates:
            self.window.config_preview.setPlainText(json.dumps(state))
            self.assertFalse(self.window.apply_json_changes(),state)
            self.assertEqual(self.window._recipe_state(),before)
            self.assertTrue(self.window._json_pending)

    def test_invalid_saved_crs_stays_visible_instead_of_becoming_keep_source(self):
        state=self.window._recipe_state()
        state['target_crs']='EPSG:999999'
        self.window._apply_table_config('invalide',state)
        self.assertEqual(self.window._recipe_state()['target_crs'],'EPSG:999999')
        self.assertIn('invalide',self.window.target_crs_label.text())
        self.assertFalse(self.window.validate_configuration())

    def test_source_attribute_geometry_gets_an_explicit_non_reserved_output_name(self):
        source=QgsVectorLayer('Point?crs=EPSG:2154&field=geometry:string&field=geometry_attribut:string','Attribut géométrique','memory')
        QgsProject.instance().addMapLayer(source)
        self.choose_source(source.id())
        fields=self.window._recipe_state()['calculated_fields']
        self.assertNotIn('geometry',fields)
        self.assertEqual(fields['geometry_attribut_2'],'"geometry"')
        self.assertEqual(fields['geometry_attribut'],'"geometry_attribut"')

    def test_rebind_checks_filter_references_before_changing_the_source(self):
        self.window.smart_fields.set_calculated_fields({'code':'"code"'},None,{'code':{'type':'Text'}})
        self.window.smart_filter.set_filter_expression('"valeur" > 0')
        self.window._on_recipe_edited()
        source=QgsVectorLayer('Point?crs=EPSG:2154&field=code:string','Incomplète','memory')
        QgsProject.instance().addMapLayer(source)
        self.window.auto_load_qgis_layers()
        label=f'{source.name()} · EPSG:2154 · {source.id()[-8:]}'
        with patch.object(QInputDialog,'getItem',return_value=(label,True)):
            self.window.rebind_recipe()
        self.assertEqual(self.window._editing_source_id,self.layer.id())
        self.assertTrue(any('valeur' in str(message) for message in self.dialogs))

    def test_rebind_shows_changed_input_types_and_can_be_refused(self):
        source=QgsVectorLayer('Point?crs=EPSG:2154&field=code:string&field=valeur:string','Types différents','memory')
        QgsProject.instance().addMapLayer(source)
        self.window.auto_load_qgis_layers()
        label=f'{source.name()} · EPSG:2154 · {source.id()[-8:]}'
        with patch.object(QInputDialog,'getItem',return_value=(label,True)),patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No) as question:
            self.window.rebind_recipe()
        self.assertTrue(question.called)
        self.assertIn('valeur',question.call_args.args[2])
        self.assertEqual(self.window._editing_source_id,self.layer.id())

    def test_imported_current_recipe_is_loaded_before_the_next_execution(self):
        self.assertTrue(self.window.save_current_table_config())
        name=self.window._loaded_recipe_name
        recipe=self.manager.get_table_config(name)
        recipe['calculated_fields']['valeur']='"valeur" * 2'
        incoming=Path(self.temp.name)/'import.json'
        incoming.write_text(json.dumps({'version':'1.2','tables':{name:recipe}}),encoding='utf-8')
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(incoming),'')),patch.object(QInputDialog,'getItem',return_value=('Remplacer les recettes homonymes',True)):
            self.window.open_configuration()
        self.assertEqual(self.window.smart_fields.get_calculated_fields()['valeur'],'"valeur" * 2')
        self.assertFalse(self.window.has_unsaved_changes())
        self.assertTrue(self.window.save_current_table_config())
        self.assertEqual(self.manager.get_table_config(name)['calculated_fields']['valeur'],'"valeur" * 2')

    def test_selection_uses_its_saved_destination_instead_of_another_open_recipe(self):
        self.assertTrue(self.window.save_current_table_config())
        name_a=self.window._loaded_recipe_name
        dest_a={'kind':'file','format':'GeoJSON','path':str(Path(self.temp.name)/'a.geojson'),'encoding':'utf-8','replay':True}
        dest_b={'kind':'file','format':'GeoJSON','path':str(Path(self.temp.name)/'b.geojson'),'encoding':'utf-8','replay':True}
        self.window._recipe_destination=dest_a
        self.assertTrue(self.window.save_current_table_config())
        self.assertTrue(self.manager.add_table_config('recette_b',self.layer.name(),{'code':'"code"'},source_id=self.layer.id(),destination=dest_b)['success'])
        self.window.refresh_shapefile_list()
        with QSignalBlocker(self.window.shp_tree):
            self.window.shp_tree.clearSelection()
            for index in range(self.window.shp_tree.topLevelItemCount()):
                item=self.window.shp_tree.topLevelItem(index)
                if self.window._selected_data(item).get('table_name')=='recette_b':
                    item.setSelected(True)
        self.assertEqual(self.window._loaded_recipe_name,name_a)
        with patch.object(self.window,'_launch_transform_task') as launch:
            self.assertTrue(self.window.transform_selected_shapefile())
        self.assertEqual(launch.call_args.args[0][0]['table_names'],['recette_b'])
        self.assertEqual(self.window._pending_delivery['path'],dest_b['path'])

    def test_support_diagnostic_excludes_business_names_values_and_paths(self):
        self.window._run_history=[{'operation':'Transformation','status':'failed','recipes':['Confidentiel-Demo'],'outputs':['C:/Confidentiel-Demo/livraison.geojson'],'errors':['Valeur privée fictive 0612345678'],'result':{'source_count':30,'produced_count':0,'rejected_count':1,'errors':['password=fictif']}}]
        diagnostic=self.window.build_anonymized_diagnostic()
        text=json.dumps(diagnostic)
        self.assertNotIn('Confidentiel-Demo',text)
        self.assertNotIn('0612345678',text)
        self.assertNotIn('password=',text)
        self.assertEqual(diagnostic['operations'][0]['error_count'],1)
        self.assertEqual(diagnostic['operations'][0]['source_count'],30)

    def test_old_transform_callback_cannot_clear_the_current_execution(self):
        current=object()
        self.window._active_transform_task=current
        self.window._on_transform_finished(object())
        self.assertIs(self.window._active_transform_task,current)
        self.assertEqual(self.window._run_history,[])
        self.window._active_transform_task=None


if __name__=='__main__':
    unittest.main()
