# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Réception visuelle et livraison réelle sur données fictives et profil isolé."""
import json
import time
from pathlib import Path
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, Qgis
from qgis.PyQt import QtCore, QtGui, QtWidgets, QtTest, sip
from Transfomer.core.config_manager import ConfigManager
from Transfomer.core.transformer import SimpleTransformer
from Transfomer.ui.main_window import EnhancedTransformerDialog
from Transfomer.export.export_module import ExportFormat

APP = globals().get('reception_app') or QtWidgets.QApplication.instance()
RUNTIME = Path(globals()['reception_runtime'])
OUT = Path(__file__).resolve().parents[1] / 'reception' / '2026-10-25'
OUT.mkdir(parents=True, exist_ok=True)
APP.setStyle('Fusion')
proof = {'qgis': Qgis.QGIS_VERSION, 'qt': QtCore.qVersion(),
    'mode': 'Qt natif hors écran, données fictives, profil isolé, aucune base métier',
    'captures': [], 'livraison': {}, 'erreurs_qt': []}
previous_hook = __import__('sys').excepthook
__import__('sys').excepthook = lambda kind, value, tb: proof['erreurs_qt'].append(str(value))

def wait_until(condition, message, milliseconds=15000):
    end = time.monotonic() + milliseconds / 1000
    while not condition() and time.monotonic() < end:
        QtTest.QTest.qWait(10)
    assert condition(), message

def capture(window, name):
    QtTest.QTest.qWait(180)
    image = window.grab()
    assert not image.isNull() and image.save(str(OUT / name))
    proof['captures'].append({'fichier':name, 'largeur':image.width(), 'hauteur':image.height()})

def palette(theme):
    values = (('#f3f5f7','#ffffff','#192b32','#155fc6','#ffffff','#e9eff2') if theme == 'clair'
              else ('#20262d','#171e25','#eef3f6','#76b9f4','#102638','#27323d'))
    colors = dict(zip(('Window','Base','WindowText','Highlight','HighlightedText','AlternateBase'), values))
    colors.update(Text=values[2], Button=values[0], ButtonText=values[2],
                  ToolTipBase=values[1], ToolTipText=values[2], PlaceholderText='#7d919c')
    p = QtGui.QPalette()
    for role, value in colors.items():
        p.setColor(getattr(QtGui.QPalette.ColorRole, role), QtGui.QColor(value))
    APP.setPalette(p)

def source():
    layer = QgsVectorLayer('Point?crs=EPSG:2154&field=identifiant:string&field=longueur:double&field=commune:string',
                           'Réseau exemple', 'memory')
    for index, name in enumerate((' n-001 ', ' n-002 ', ' n-003 ')):
        feature = QgsFeature(layer.fields())
        feature.setAttributes([name, 42.5 + index, 'Saint-Éloi'])
        feature.setGeometry(QgsGeometry.fromWkt('POINT(%s 6800000)' % (650000 + index)))
        assert layer.dataProvider().addFeatures([feature])[0]
    layer.updateExtents()
    QgsProject.instance().addMapLayer(layer)
    return layer

try:
    for theme in ('clair','sombre'):
        palette(theme)
        layer = source()
        original = [tuple(feature.attributes()) for feature in layer.getFeatures()]
        manager = ConfigManager(str(RUNTIME / ('recettes-' + theme)))
        window = EnhancedTransformerDialog(manager, SimpleTransformer(manager))
        window.resize(1200, 820)
        window.show()
        QtTest.QTest.qWait(100)
        assert window._editing_source_id == layer.id()
        assert window.workspace_stack.currentIndex() == 1
        assert window.context_banner.isVisible()
        window._show_intentions()
        for identifier in ('clean','compare','deliver'):
            choice = window.intentions_panel.findChild(QtWidgets.QCheckBox, 'transformer_intention_choice_' + identifier)
            assert choice is not None and choice.isEnabled()
            choice.setChecked(True)
        if theme == 'clair':
            capture(window, 'refonte-intentions.png')
        window._begin_intentions(window.intentions_panel.selected_intentions())
        rules = window.quick_rules
        rules.field_combo.setCurrentIndex(rules.field_combo.findData('identifiant'))
        for operation in ('trim','upper'):
            rules.operation_combo.setCurrentIndex(rules.operation_combo.findData(operation))
            assert rules.apply(), rules.reason_label.text()
        capture(window, 'refonte-' + theme + '.png')
        started = time.perf_counter()
        assert window.test_configuration()
        preview_ms = (time.perf_counter() - started) * 1000
        if theme == 'clair':
            assert not window.preview_table.item(0, 2).icon().isNull()
            capture(window, 'comparaison.png')
            window._primary_workspace_action()
            wait_until(lambda: window._active_transform_task is None and bool(window._result_layers), 'Résultat non créé')
            window._open_result_delivery()
            delivery = window.delivery_panel
            delivery.format_combo.setCurrentIndex(delivery.format_combo.findData(ExportFormat.GEOPACKAGE))
            destination = RUNTIME / 'résultat exploitable.gpkg'
            delivery.path_edit.setText(str(destination))
            assert delivery.deliver(), delivery.delivery_status.text()
            wait_until(lambda: getattr(window.export_widget, '_export_batch', None) is not None
                       and window.export_widget._export_batch.closed, 'Livraison sans bilan')
            assert destination.is_file()
            assert delivery.open_result(), delivery.delivery_status.text()
            output = QgsVectorLayer(str(destination), 'Contrôle du fichier livré', 'ogr')
            assert output.isValid() and output.featureCount() == 3
            assert [feature['identifiant'] for feature in output.getFeatures()] == ['N-001','N-002','N-003']
            assert set(layer.fields().names()).issubset(output.fields().names())
            generated_fields = [name for name in output.fields().names() if name not in layer.fields().names()]
            assert generated_fields == ['fid'], generated_fields
            assert output.crs() == layer.crs()
            assert [tuple(feature.attributes()) for feature in layer.getFeatures()] == original
            proof['livraison'] = {'format':'GeoPackage','lignes':3,'colonnes':output.fields().names(),
                'crs':output.crs().authid(),'valeurs':['N-001','N-002','N-003'],'source_conservee':True,
                'identifiants_techniques_format':generated_fields,
                'fichier_relu_ogr':True,'ouverture_qgis':True,'apercu_ms_sur_3_objets':round(preview_ms,2),
                'recu':window._run_history[-1]['status']}
            capture(window, 'resultat.png')
            sip.delete(output)
        else:
            window.resize(1024, 700)
            window.setProperty('fluentReducedMotion', True)
            font = QtGui.QFont(window.font())
            font.setPointSizeF(max(11.0, font.pointSizeF() * 1.15))
            window.setFont(font)
            window.apply_theme()
            capture(window, 'refonte-compact-1024x700.png')
        window._saved_state = window._recipe_state()
        window._force_dirty = False
        window.close()
        window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QgsProject.instance().removeAllMapLayers()
        APP.processEvents()
    assert not proof['erreurs_qt'], proof['erreurs_qt']
finally:
    __import__('sys').excepthook = previous_hook
    (OUT / 'resultats.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(proof, ensure_ascii=False), flush=True)
