# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Mesure locale du parcours réel sur 10 000 points mémoire, sans publication."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer, Qgis
from qgis.PyQt import QtCore, QtTest, QtWidgets

from Transfomer.core.config_manager import ConfigManager
from Transfomer.core.transformer import SimpleTransformer
from Transfomer.ui.main_window import EnhancedTransformerDialog

APP = globals().get("reception_app") or QtWidgets.QApplication.instance()
RUNTIME = Path(globals()["reception_runtime"])
OUT = Path(__file__).resolve().parents[1] / "reception" / "2026-10-25" / "mesures.json"
COUNT = 10000
INTERVAL_MS = 16
proof = {
    "date_utc": datetime.now(timezone.utc).isoformat(),
    "reussite": False,
    "conditions": {"qgis": Qgis.QGIS_VERSION, "qt_runtime": QtCore.qVersion(),
        "python": sys.version.split()[0], "mode": "Qt natif hors écran, rendu logiciel",
        "nombre_objets": COUNT, "geometrie": "Point EPSG:2154",
        "attributs": ["identifiant (texte)", "quantite (entier)", "commune (texte)"],
        "profil": "temporaire isolé par tests/run_qgis4.py", "reseau": "interdit par le runner",
        "sources": "mémoire synthétique, marquée en lecture seule", "repetitions": 1,
        "processeurs_logiques": os.cpu_count(), "initialisation_qgis_incluse": False},
    "latences_ms": {}, "verification": {}, "exceptions_qt": [],
    "limites": ["Une seule exécution locale, sans mesure comparative avant refonte.",
        "Hors écran : latence du rendu logiciel, pas celle d'un écran ou d'un geste physique.",
        "PostgreSQL, réseau, source disque, gros polygones, export et lecteur d'écran non mesurés.",
        "Les retards du heartbeat incluent l'ordonnancement Windows et la charge du poste.",
        "La fermeture native du processus n'est pas couverte par le runner."],
}
previous_hook = sys.excepthook
sys.excepthook = lambda kind, value, tb: proof["exceptions_qt"].append(str(value))
window = None
heartbeat = QtCore.QTimer(APP)
heartbeat.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
heartbeat.setInterval(INTERVAL_MS)
phase = "repos"
last_tick = None
gaps = []


def beat():
    global last_tick
    now = time.perf_counter()
    if last_tick is not None:
        gaps.append((phase, (now - last_tick) * 1000))
    last_tick = now


heartbeat.timeout.connect(beat)


def measured(name, operation):
    global phase
    APP.processEvents()
    phase = name
    start = time.perf_counter()
    result = operation()
    APP.processEvents()
    proof["latences_ms"][name] = round((time.perf_counter() - start) * 1000, 3)
    QtTest.QTest.qWait(20)
    return result


def signature(layer):
    digest = hashlib.sha256()
    digest.update(json.dumps([(field.name(), field.typeName(), field.length(), field.precision())
                              for field in layer.fields()], ensure_ascii=False).encode("utf-8"))
    digest.update(layer.crs().authid().encode("ascii"))
    for feature in layer.getFeatures():
        digest.update(json.dumps([feature.id(), feature.attributes()], ensure_ascii=False,
                                 separators=(",", ":"), default=str).encode("utf-8"))
        digest.update(bytes(feature.geometry().asWkb()))
    return digest.hexdigest()


def wait_for(condition, milliseconds=30000):
    if condition():
        return
    loop = QtCore.QEventLoop()
    check = QtCore.QTimer()
    check.setInterval(10)
    check.timeout.connect(lambda: loop.quit() if condition() else None)
    deadline = QtCore.QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    check.start()
    deadline.start(milliseconds)
    loop.exec()
    check.stop()
    deadline.stop()
    assert condition(), "La transformation n'a pas terminé dans le budget de mesure."


try:
    assert APP is not None, "Utiliser le runner QGIS isolé."
    APP.setStyle("Fusion")
    start = time.perf_counter()
    source = QgsVectorLayer("Point?crs=EPSG:2154&field=identifiant:string&field=quantite:integer&field=commune:string",
                            "Mesure synthétique 10000 points", "memory")
    assert source.isValid()
    features = []
    for index in range(COUNT):
        feature = QgsFeature(source.fields())
        feature.setAttributes(["  client %05d  " % index, index, "Secteur synthétique"])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(650000 + index * .25, 6800000 + index % 100)))
        features.append(feature)
    assert source.dataProvider().addFeatures(features)[0]
    del features
    source.updateExtents()
    source.setReadOnly(True)
    QgsProject.instance().addMapLayer(source)
    proof["latences_ms"]["creation_jeu_synthetique"] = round((time.perf_counter() - start) * 1000, 3)
    original = signature(source)

    last_tick = time.perf_counter()
    heartbeat.start()
    QtTest.QTest.qWait(35)

    def open_workspace():
        manager = ConfigManager(str(RUNTIME / "recettes-mesure-10000"))
        view = EnhancedTransformerDialog(manager, SimpleTransformer(manager))
        view.resize(1200, 820)
        view.show()
        APP.processEvents()
        assert not view.grab().isNull()
        return view

    window = measured("ouverture_atelier_premier_rendu", open_workspace)
    assert window._editing_source_id == source.id()
    measured("contexte_objectifs", lambda: window._begin_intentions(["clean", "compare"]))
    rules = window.quick_rules
    rules.field_combo.setCurrentIndex(rules.field_combo.findData("identifiant"))

    def apply_rule(operation):
        rules.operation_combo.setCurrentIndex(rules.operation_combo.findData(operation))
        assert rules.apply(), rules.reason_label.text()

    measured("regle_trim", lambda: apply_rule("trim"))
    measured("regle_upper", lambda: apply_rule("upper"))
    assert measured("comparaison_50_objets", window.test_configuration)
    assert window._last_control["read"] == 50 and window._last_control["errors"] == []
    assert window.preview_table.rowCount() == 50
    assert window.preview_table.item(0, 2).text() == "CLIENT 00000"

    phase = "transformation_asynchrone"
    start = time.perf_counter()
    window._primary_workspace_action()
    proof["latences_ms"]["lancement_transformation_retour_ui"] = round((time.perf_counter() - start) * 1000, 3)
    assert window._active_transform_task is not None, "Le scénario doit lancer une vraie tâche QgsTask."
    wait_for(lambda: window._active_transform_task is None and bool(window._result_layers))
    proof["latences_ms"]["transformation_complete_et_bilan_ui"] = round((time.perf_counter() - start) * 1000, 3)
    QtTest.QTest.qWait(40)
    heartbeat.stop()
    grouped = defaultdict(list)
    for name, gap in gaps:
        grouped[name].append(gap)
    proof["heartbeat_ui"] = {
        "intervalle_demande_ms": INTERVAL_MS, "echantillons": len(gaps),
        "ecart_max_entre_tics_ms": round(max((gap for _, gap in gaps), default=0), 3),
        "retard_max_au_dela_intervalle_ms": round(max((gap - INTERVAL_MS for _, gap in gaps), default=0), 3),
        "par_phase": {name: {"echantillons": len(values), "ecart_max_ms": round(max(values), 3),
                             "retard_max_ms": round(max(0, max(values) - INTERVAL_MS), 3)}
                      for name, values in grouped.items()},
        "instrumentation": "QTimer PreciseTimer 16 ms; création du jeu, empreintes et vérification finale exclues.",
    }

    start = time.perf_counter()
    assert len(window._result_layers) == 1
    output = window._result_layers[0]
    assert output is not source and output.isValid() and output.featureCount() == COUNT
    assert output.crs() == source.crs()
    seen = set()
    for feature in output.getFeatures():
        index = feature["quantite"]
        assert isinstance(index, int) and 0 <= index < COUNT
        assert feature["identifiant"] == "CLIENT %05d" % index
        assert feature["commune"] == "Secteur synthétique"
        point = feature.geometry().asPoint()
        assert point.x() == 650000 + index * .25 and point.y() == 6800000 + index % 100
        seen.add(index)
    assert len(seen) == COUNT
    unchanged = signature(source) == original
    assert unchanged and source.featureCount() == COUNT
    assert window._run_history[-1]["status"] == "success"
    proof["latences_ms"]["verification_integrale_hors_heartbeat"] = round((time.perf_counter() - start) * 1000, 3)

    # Mesure séparée de l'écriture fichier (GeoPackage) et de la relecture OGR sur les 10 000 points
    from Transfomer.export.export_module import ExportFormat
    from qgis.PyQt import sip
    window._open_result_delivery()
    delivery = window.delivery_panel
    delivery.layer_combo.setCurrentIndex(delivery.layer_combo.findData(output.id()))
    delivery.format_combo.setCurrentIndex(delivery.format_combo.findData(ExportFormat.GEOPACKAGE))
    gpkg_path = RUNTIME / "mesure_10000_points.gpkg"
    delivery.path_edit.setText(str(gpkg_path))
    export_start = time.perf_counter()
    assert delivery.deliver(), delivery.delivery_status.text()
    wait_for(lambda: getattr(window.export_widget, "_export_batch", None) is not None
             and window.export_widget._export_batch.closed)
    proof["latences_ms"]["export_geopackage_10000_points"] = round((time.perf_counter() - export_start) * 1000, 3)
    assert gpkg_path.is_file()
    reread_start = time.perf_counter()
    reread_layer = QgsVectorLayer(str(gpkg_path), "Relecture 10000 points", "ogr")
    assert reread_layer.isValid() and reread_layer.featureCount() == COUNT
    first_reread = next(reread_layer.getFeatures())
    assert first_reread["identifiant"].startswith("CLIENT ")
    proof["latences_ms"]["relecture_ogr_10000_points"] = round((time.perf_counter() - reread_start) * 1000, 3)
    sip.delete(reread_layer)

    # Mesure séparée sur géométries polygonales lourdes (1 000 polygones à 32 sommets + buffer + reprojection EPSG:4326)
    POLY_COUNT = 1000
    poly_start = time.perf_counter()
    poly_source = QgsVectorLayer(
        "Polygon?crs=EPSG:2154&field=code:string&field=surface_ref:double",
        "Mesure 1000 polygones", "memory",
    )
    assert poly_source.isValid()
    poly_features = []
    for idx in range(POLY_COUNT):
        feat = QgsFeature(poly_source.fields())
        feat.setAttributes(["  parcelle_%04d  " % idx, float(idx * 10)])
        cx = 650000 + (idx % 50) * 50.0
        cy = 6800000 + (idx // 50) * 50.0
        pt_geom = QgsGeometry.fromPointXY(QgsPointXY(cx, cy)).buffer(12.0, 8)
        feat.setGeometry(pt_geom)
        poly_features.append(feat)
    assert poly_source.dataProvider().addFeatures(poly_features)[0]
    del poly_features
    poly_source.updateExtents()
    poly_source.setReadOnly(True)
    QgsProject.instance().addMapLayer(poly_source)
    proof["latences_ms"]["creation_jeu_1000_polygones"] = round((time.perf_counter() - poly_start) * 1000, 3)
    poly_original_sig = signature(poly_source)

    window.auto_load_qgis_layers()
    window.refresh_shapefile_list()
    for row_idx in range(window.shp_tree.topLevelItemCount()):
        item = window.shp_tree.topLevelItem(row_idx)
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(data, dict) and data.get("source_file") == poly_source.id() and data.get("table_name") is None:
            window._saved_state = window._recipe_state()
            window._force_dirty = False
            window.shp_tree.setCurrentItem(item)
            break
    APP.processEvents()
    window._begin_intentions(["clean", "geometry", "compare"])
    window.quick_rules.field_combo.setCurrentIndex(window.quick_rules.field_combo.findData("code"))
    window.quick_rules.operation_combo.setCurrentIndex(window.quick_rules.operation_combo.findData("trim"))
    assert window.quick_rules.apply()
    window.geometry_expression_edit.setText("buffer($geometry, 2)")
    window.set_target_crs("EPSG:4326", "WGS 84")
    poly_preview_start = time.perf_counter()
    assert window.test_configuration()
    proof["latences_ms"]["comparaison_50_polygones_buffer_reproj"] = round((time.perf_counter() - poly_preview_start) * 1000, 3)
    poly_calc_start = time.perf_counter()
    window._saved_state = window._recipe_state()
    window._force_dirty = False
    assert window.transform_selected_shapefile()
    wait_for(lambda: window._active_transform_task is None and bool(window._result_layers))
    proof["latences_ms"]["transformation_1000_polygones_buffer_reproj"] = round((time.perf_counter() - poly_calc_start) * 1000, 3)
    poly_out = window._result_layers[0]
    assert poly_out.isValid() and poly_out.featureCount() == POLY_COUNT
    assert poly_out.crs().authid() == "EPSG:4326"
    sample_poly = next(poly_out.getFeatures())
    assert sample_poly["code"] == "parcelle_0000"
    bbox = sample_poly.geometry().boundingBox()
    assert 1.5 < bbox.center().x() < 3.5 and 47.5 < bbox.center().y() < 49.5
    poly_unchanged = signature(poly_source) == poly_original_sig
    assert poly_unchanged

    proof["verification"] = {"objets_sortie": output.featureCount(), "valeurs_identifiant_verifiees": COUNT,
        "valeurs_attendues": "CLIENT 00000 à CLIENT 09999, sans espaces périphériques",
        "entiers_uniques": len(seen), "autre_texte_et_geometries_identiques": True,
        "crs": output.crs().authid(), "source_inchangee_sha256": unchanged,
        "empreinte_source_avant_apres": original, "statut_recu": window._run_history[-1]["status"],
        "export_gpkg_10000_points_relu": True,
        "polygones_1000_buffer_reproj_epsg4326": {
            "objets_sortie": poly_out.featureCount(),
            "crs_sortie": poly_out.crs().authid(),
            "source_inchangee_sha256": poly_unchanged,
            "empreinte_source_polygones": poly_original_sig,
        }}
    assert not proof["exceptions_qt"], proof["exceptions_qt"]
    proof["reussite"] = True
except BaseException:
    proof["erreur"] = traceback.format_exc()
    raise
finally:
    heartbeat.stop()
    if window is not None and window._active_transform_task is None:
        window._saved_state = window._recipe_state()
        window._force_dirty = False
        window.close()
        window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QgsProject.instance().removeAllMapLayers()
        APP.processEvents()
    sys.excepthook = previous_hook
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({"reussite": proof["reussite"], "latences_ms": proof["latences_ms"],
                  "heartbeat_ui": proof["heartbeat_ui"], "verification": proof["verification"]},
                 ensure_ascii=False), flush=True)
