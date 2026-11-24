# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Livrer un résultat choisi en conservant les contrôles du moteur d'export C5."""

import os
from pathlib import Path

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QSignalBlocker
from qgis.PyQt.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from ..export.export_module import ExportFormat
from ..shared.compat import (
    FileDialogDontConfirmOverwrite,
    FocusNoFocus,
    FormAllNonFixedFieldsGrow,
    FrameNoFrame,
    PlainText,
    ScrollBarAlwaysOff,
    SizePolicyIgnored,
    SizePolicyPreferred,
    TextSelectableByMouse,
)
from ..widgets.fluent import FluentButton, StableStatus


_FORMAT_TEXT = {
    ExportFormat.GEOPACKAGE: ("GeoPackage (recommandé)", "Un fichier pour les colonnes et les formes, facile à rouvrir dans QGIS."),
    ExportFormat.GEOJSON: ("GeoJSON", "Un fichier de données géographiques, utilisable par de nombreux outils."),
    ExportFormat.SHAPEFILE: ("Shapefile", "Un ensemble de fichiers à conserver ensemble ; les noms et types de colonnes ont des limites."),
    ExportFormat.CSV: ("CSV", "Une table de valeurs. La géométrie n'est pas conservée dans ce format de livraison."),
    ExportFormat.XLSX: ("Classeur Excel", "Un classeur de valeurs. La géométrie n'est pas conservée dans ce format de livraison."),
    ExportFormat.KML: ("KML", "Un format géographique pour la visualisation ; vérifiez les coordonnées dans le logiciel destinataire."),
    ExportFormat.DXF: ("Dessin DXF", "Un dessin pour un logiciel de CAO ; les possibilités d'attributs dépendent du format."),
    ExportFormat.TAB: ("MapInfo TAB", "Un ensemble de fichiers MapInfo à conserver ensemble."),
    ExportFormat.GML: ("GML", "Un échange géographique dont les fichiers associés doivent rester ensemble."),
    ExportFormat.SQLITE: ("SQLite / SpatiaLite", "Un fichier de base de données pour les valeurs et les géométries."),
    ExportFormat.FLATGEOBUF: ("FlatGeobuf", "Un fichier de données géographiques destiné aux logiciels qui le prennent en charge."),
}


def _path_key(value):
    return os.path.normcase(os.path.abspath(os.fspath(value)))


class DeliveryPanel(QWidget):
    """Une demande explicite de livraison, sans écriture propre au panneau."""

    def __init__(self, exporter, parent=None):
        super().__init__(parent)
        self.setObjectName("transformer_delivery_panel")
        self.exporter = exporter
        self._layers = {}
        self._busy = False
        self._pending_path = ""
        self._owned_batch = None
        self._request_initiated = False
        self._result_path = ""
        self._opened_layer_id = ""
        self._deferred_results = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 20)
        outer.setSpacing(12)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(FrameNoFrame)
        self._scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        self._scroll.setFocusPolicy(FocusNoFocus)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll, 1)

        title = QLabel("Obtenir un résultat utilisable")
        title.setProperty("fluentRole", "title")
        title.setWordWrap(True)
        layout.addWidget(title)
        introduction = QLabel("Choisissez le résultat préparé, puis le fichier à créer. Votre source reste conservée.")
        introduction.setWordWrap(True)
        introduction.setProperty("fluentRole", "body")
        layout.addWidget(introduction)

        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(FormAllNonFixedFieldsGrow)
        self.layer_combo = QComboBox()
        self.layer_combo.setObjectName("transformer_delivery_layer")
        self.layer_combo.setAccessibleName("Résultat à livrer")
        self.layer_combo.setMinimumHeight(38)
        form.addRow("Résultat à livrer", self.layer_combo)
        self.format_combo = QComboBox()
        self.format_combo.setObjectName("transformer_delivery_format")
        self.format_combo.setAccessibleName("Format du fichier")
        self.format_combo.setMinimumHeight(38)
        available = [exporter.format_combo.itemData(index) for index in range(exporter.format_combo.count())]
        for export_format in (ExportFormat.GEOPACKAGE, *[item for item in ExportFormat if item != ExportFormat.GEOPACKAGE]):
            if export_format in available:
                self.format_combo.addItem(_FORMAT_TEXT[export_format][0], export_format)
        form.addRow("Format du fichier", self.format_combo)
        self.encoding_label = QLabel("UTF-8 : les caractères accentués sont contrôlés avant l'installation du fichier.")
        self.encoding_label.setObjectName("transformer_delivery_encoding")
        self.encoding_label.setProperty("fluentRole", "meta")
        self.encoding_label.setWordWrap(True)
        form.addRow("Encodage", self.encoding_label)
        destination = QHBoxLayout()
        destination.setSpacing(12)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("transformer_delivery_path")
        self.path_edit.setAccessibleName("Fichier de destination")
        self.path_edit.setPlaceholderText("Choisissez où enregistrer le fichier")
        self.path_edit.setMinimumHeight(38)
        destination.addWidget(self.path_edit, 1)
        self.browse_button = FluentButton("Parcourir…", icon_name="open")
        self.browse_button.setObjectName("transformer_delivery_browse")
        self.browse_button.clicked.connect(self._browse)
        destination.addWidget(self.browse_button)
        form.addRow("Fichier de destination", destination)
        layout.addLayout(form)

        self.content_summary = QLabel()
        self.content_summary.setObjectName("transformer_delivery_content")
        self.content_summary.setTextFormat(PlainText)
        self.content_summary.setWordWrap(True)
        self.content_summary.setTextInteractionFlags(TextSelectableByMouse)
        self.content_summary.setProperty("fluentRole", "body")
        self.content_summary.setSizePolicy(SizePolicyIgnored, SizePolicyPreferred)
        layout.addWidget(self.content_summary)
        self.format_description = QLabel()
        self.format_description.setObjectName("transformer_delivery_format_description")
        self.format_description.setProperty("fluentRole", "meta")
        self.format_description.setWordWrap(True)
        layout.addWidget(self.format_description)
        layout.addStretch(1)
        layout = outer

        self.delivery_status = StableStatus("Aucun résultat choisi. Exécutez une préparation, puis choisissez sa sortie.")
        self.delivery_status.setObjectName("transformer_delivery_status")
        self.delivery_status.setAccessibleName("État de la livraison")
        layout.addWidget(self.delivery_status)
        progress_slot = QWidget()
        progress_slot.setFixedHeight(6)
        progress_layout = QHBoxLayout(progress_slot)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self._progress = QProgressBar()
        self._progress.setObjectName("transformer_delivery_activity")
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.setAccessibleName("Livraison en cours, avancement non mesuré")
        self._progress.hide()
        progress_layout.addWidget(self._progress)
        layout.addWidget(progress_slot)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.open_button = FluentButton("Ouvrir dans QGIS", icon_name="open")
        self.open_button.setObjectName("transformer_delivery_open")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_result)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        self.cancel_button = FluentButton("Annuler", icon_name="clear")
        self.cancel_button.setObjectName("transformer_delivery_cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        actions.addWidget(self.cancel_button)
        self.deliver_button = FluentButton("Créer le fichier", variant="primary", icon_name="export")
        self.deliver_button.setObjectName("transformer_delivery_create")
        self.deliver_button.clicked.connect(self.deliver)
        actions.addWidget(self.deliver_button)
        layout.addLayout(actions)

        self.layer_combo.currentIndexChanged.connect(self._configuration_changed)
        self.format_combo.currentIndexChanged.connect(self._configuration_changed)
        self.path_edit.textChanged.connect(self._configuration_changed)
        exporter.request_started.connect(self._on_request_started)
        exporter.export_finished.connect(self._on_finished)
        QWidget.setTabOrder(self.layer_combo, self.format_combo)
        QWidget.setTabOrder(self.format_combo, self.path_edit)
        QWidget.setTabOrder(self.path_edit, self.browse_button)
        QWidget.setTabOrder(self.browse_button, self.open_button)
        QWidget.setTabOrder(self.open_button, self.cancel_button)
        QWidget.setTabOrder(self.cancel_button, self.deliver_button)
        self.set_results([])

    def set_results(self, layers):
        """Recevoir les sorties du calcul ; aucune couche du projet n'est choisie implicitement."""
        if self._busy:
            self._deferred_results = list(layers or [])
            return
        selected = self.layer_combo.currentData()
        self._layers = {}
        with QSignalBlocker(self.layer_combo):
            self.layer_combo.clear()
            self.layer_combo.addItem("Choisissez un résultat préparé…", None)
            for layer in layers or []:
                try:
                    if isinstance(layer, QgsVectorLayer) and layer.isValid() and layer.id() not in self._layers:
                        self._layers[layer.id()] = layer
                        self.layer_combo.addItem(layer.name(), layer.id())
                except RuntimeError:
                    continue
            index = self.layer_combo.findData(selected) if selected in self._layers else 0
            self.layer_combo.setCurrentIndex(index)
        self._configuration_changed()

    def _layer(self):
        layer = self._layers.get(self.layer_combo.currentData())
        try:
            return layer if layer is not None and layer.isValid() else None
        except RuntimeError:
            return None

    def _configuration_changed(self, *_args):
        if self._busy:
            return
        self._result_path = ""
        self._opened_layer_id = ""
        self.open_button.setText("Ouvrir dans QGIS")
        self.open_button.setEnabled(False)
        layer = self._layer()
        export_format = self.format_combo.currentData()
        self.format_description.setText(_FORMAT_TEXT.get(export_format, ("", "Choisissez un format disponible."))[1])
        if layer is None:
            self.content_summary.setText("Seuls les résultats d'une préparation exécutée sont proposés ici.")
            self._status("Aucun résultat choisi. Exécutez une préparation, puis choisissez sa sortie.")
        else:
            count = layer.featureCount()
            names = [field.name() for field in layer.fields()]
            geometry = ("Coordonnées du résultat préparé : " + (layer.crs().authid() or layer.crs().description() or "non renseignées")) if layer.isSpatial() else "Table sans géométrie."
            self.content_summary.setText((format(count, ",").replace(",", " ") + " lignes" if count >= 0 else "Nombre de lignes non connu")
                + " · " + str(len(names)) + " colonnes\n" + geometry + "\nColonnes : "
                + (", ".join(names[:8]) + ("…" if len(names) > 8 else "") if names else "aucune"))
            self._status("Choisissez la destination. Le contenu sera contrôlé avant l'installation du fichier ; votre source reste conservée.")
        self.deliver_button.setEnabled(layer is not None and isinstance(export_format, ExportFormat))

    def _status(self, message):
        self.delivery_status.setText(message)
        self.delivery_status.setAccessibleDescription(message)

    def _extension(self):
        return self.exporter.export_manager.format_extensions.get(self.format_combo.currentData(), "")

    def _browse(self):
        if self._busy:
            return
        layer = self._layer()
        extension = self._extension()
        suggested = self.path_edit.text().strip()
        if not suggested and layer is not None:
            suggested = self.exporter._safe_file_name(layer.name()) + extension
        export_format = self.format_combo.currentData()
        title = _FORMAT_TEXT.get(export_format, ("Fichier", ""))[0]
        destination, _ = QFileDialog.getSaveFileName(self, "Choisir le fichier à créer", suggested,
            title + " (*" + extension + ")", options=FileDialogDontConfirmOverwrite)
        if destination and not self._busy:
            self.path_edit.setText(destination)

    def deliver(self):
        """Demander au moteur une livraison ; vrai signifie demande acceptée, pas succès."""
        return self._dispatch("utf-8")

    def replay(self, layer, destination):
        """Reprendre une destination enregistrée avec le même suivi et son encodage déclaré."""
        active = getattr(self.exporter, "_export_batch", None)
        if self._busy or (active is not None and not getattr(active, "closed", True)):
            self._status("Une livraison est déjà en cours. Attendez son bilan avant de reprendre une destination.")
            return False
        if not isinstance(destination, dict) or destination.get("kind") != "file" or destination.get("selected_only"):
            self._status("Cette destination ne peut pas être reprise ici. Choisissez un résultat complet et un fichier de destination.")
            return False
        try:
            valid = isinstance(layer, QgsVectorLayer) and layer.isValid()
        except RuntimeError:
            valid = False
        if not valid:
            self._status("Le résultat préparé n'est plus disponible. Relancez sa préparation avant de reprendre la livraison.")
            return False
        requested_format = destination.get("format")
        format_index = next((index for index in range(self.format_combo.count())
            if self.format_combo.itemData(index) == requested_format
            or getattr(self.format_combo.itemData(index), "value", None) == requested_format), -1)
        encoding = destination.get("encoding", "utf-8")
        if format_index < 0 or not isinstance(encoding, str) or self.exporter.encoding_combo.findData(encoding) < 0:
            self._status("Le format ou l'encodage enregistré n'est plus disponible. Choisissez une nouvelle destination avant de livrer.")
            return False
        if layer.id() not in self._layers:
            self.set_results([*self._layers.values(), layer])
        self.layer_combo.setCurrentIndex(self.layer_combo.findData(layer.id()))
        self.format_combo.setCurrentIndex(format_index)
        self.path_edit.setText(str(destination.get("path") or ""))
        return self._dispatch(encoding)

    def _dispatch(self, encoding):
        """Point unique de départ vers C5, y compris pour une destination reprise."""
        active = getattr(self.exporter, "_export_batch", None)
        if self._busy or (active is not None and not getattr(active, "closed", True)):
            self._status("Une livraison est déjà en cours. Attendez son bilan avant de créer un autre fichier.")
            return False
        layer = self._layer()
        if layer is None:
            self._status("Choisissez un résultat préparé avant de créer le fichier.")
            self.layer_combo.setFocus()
            return False
        path = self.path_edit.text().strip()
        if not path or not os.path.isabs(path):
            self._status("Choisissez un chemin complet avec Parcourir, puis créez le fichier.")
            self.path_edit.setFocus()
            return False
        extension = self._extension()
        if not extension:
            self._status("Choisissez un format de fichier disponible.")
            return False
        if not Path(path).suffix:
            path += extension
        elif Path(path).suffix.casefold() != extension.casefold():
            self._status("Le format choisi attend un fichier " + extension + ". Adaptez le nom ou choisissez un autre format.")
            self.path_edit.setFocus()
            return False
        export_format = self.format_combo.currentData()
        format_index = self.exporter.format_combo.findData(export_format)
        encoding_index = self.exporter.encoding_combo.findData(encoding)
        if format_index < 0 or encoding_index < 0:
            self._status("Le format ou l'encodage demandé n'est plus disponible. Choisissez un autre format ou rouvrez l'atelier.")
            return False
        self.path_edit.setText(path)
        encoding_name = self.exporter.encoding_combo.itemText(encoding_index)
        self.encoding_label.setText(encoding_name + " : les valeurs sont contrôlées avec cet encodage avant l'installation du fichier.")
        self._result_path = ""
        self.open_button.setEnabled(False)
        self._pending_path = _path_key(path)
        self._request_initiated = False
        self._owned_batch = None
        self._set_busy(True)
        self._status("Vérification de la destination. Si le fichier existe, son remplacement doit être confirmé.")
        try:
            self.exporter.format_combo.setCurrentIndex(format_index)
            self.exporter.encoding_combo.setCurrentIndex(encoding_index)
            job = self.exporter._export_job(layer, path, False)
            self.exporter._start_export_jobs([job], overwrite_confirmed=False)
        except Exception as error:
            self._set_busy(False)
            self._pending_path = ""
            self._status("La livraison n'a pas pu démarrer. " + str(error))
            return False
        if not self._request_initiated:
            self._set_busy(False)
            self._pending_path = ""
            if self._deferred_results is not None:
                layers, self._deferred_results = self._deferred_results, None
                self.set_results(layers)
            self._status("Aucun fichier créé. Le remplacement n'a pas été confirmé ; choisissez une autre destination ou réessayez.")
        return self._request_initiated

    def _on_request_started(self, request):
        destinations = request.get("destinations", []) if isinstance(request, dict) else []
        if not self._pending_path or self._pending_path not in {_path_key(path) for path in destinations}:
            return
        self._request_initiated = True
        self._owned_batch = getattr(self.exporter, "_export_batch", None)
        self._set_busy(True)
        self._status("Livraison en cours. Les valeurs sont contrôlées et le fichier est préparé avant son installation.")

    def _on_finished(self, result):
        if not self._busy or not isinstance(result, dict):
            return
        if self._owned_batch is not None and getattr(self.exporter, "_export_batch", None) is not self._owned_batch:
            return
        requested = self._pending_path
        outputs = result.get("outputs") or []
        if result.get("status") == "success" and outputs and requested not in {_path_key(path) for path in outputs}:
            return
        self._pending_path = ""
        self._owned_batch = None
        self._set_busy(False)
        if self._deferred_results is not None:
            layers, self._deferred_results = self._deferred_results, None
            self.set_results(layers)
        self._result_path = ""
        status = result.get("status")
        matches = [str(path) for path in outputs if _path_key(path) == requested]
        if status == "success" and matches:
            self._result_path = matches[0]
            self._status("Fichier créé et contrôlé : " + self._result_path + ". Ouvrez-le dans QGIS pour consulter le résultat.")
        elif status in ("cancelled", "canceled"):
            recovery = result.get("recovery_directories") or []
            self._status("Livraison annulée. " + ("Restauration à vérifier : " + ", ".join(map(str, recovery)) if recovery else
                "Les fichiers précédents ont été conservés ou restaurés."))
        else:
            errors = result.get("errors") or []
            detail = "; ".join(map(str, errors)) or "Le moteur n'a pas confirmé de fichier pour la destination choisie."
            self._status("Livraison échouée. " + detail)
        self.open_button.setEnabled(bool(self._result_path))

    def _set_busy(self, busy):
        self._busy = bool(busy)
        for widget in (self.layer_combo, self.format_combo, self.path_edit, self.browse_button):
            widget.setEnabled(not busy)
        self.deliver_button.setBusy(busy)
        self.deliver_button.setEnabled(not busy and self._layer() is not None)
        self.cancel_button.setEnabled(busy)
        self._progress.setVisible(busy)

    def _cancel(self):
        if self._busy:
            self.cancel_button.setEnabled(False)
            self.exporter.cancel_export()
            if self._busy:
                self._status("Annulation demandée. Attendez le bilan avant de relancer ; la destination précédente reste protégée par le moteur.")

    def open_result(self):
        """Ouvrir sur demande explicite le fichier confirmé, puis l'ajouter au projet."""
        if self._busy or not self._result_path:
            return False
        if not Path(self._result_path).is_file():
            self._status("Le fichier livré n'est plus disponible à cet emplacement. Vérifiez sa présence avant de l'ouvrir.")
            return False
        existing = QgsProject.instance().mapLayer(self._opened_layer_id) if self._opened_layer_id else None
        if existing is not None and existing.isValid():
            return True
        layer = QgsVectorLayer(self._result_path, Path(self._result_path).stem, "ogr")
        if not layer.isValid():
            self._status("Le fichier a été créé, mais QGIS ne peut pas le lire. Consultez le bilan et vérifiez le format dans le logiciel destinataire.")
            return False
        if QgsProject.instance().addMapLayer(layer) is None:
            self._status("Le fichier est lisible, mais il n'a pas pu être ajouté au projet QGIS.")
            return False
        self._opened_layer_id = layer.id()
        self.open_button.setText("Ouvert dans QGIS")
        self._status("Résultat ouvert dans QGIS. Le fichier reste disponible à cet emplacement : " + self._result_path)
        return True
