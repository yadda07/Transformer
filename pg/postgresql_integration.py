# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
PostgreSQL integration module for Transformer
Mapping & export of transformed tables to PostgreSQL
"""

import os
import json

from qgis.PyQt.QtCore import QStringListModel, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QMessageBox, QDialog,
    QFormLayout, QGroupBox, QFrame, QTabWidget, QInputDialog, QRadioButton,
    QScrollArea
)

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import (
    QColor, QPainter, QPen, QBrush,
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsMessageLog, QgsApplication
)
from datetime import datetime
from ..shared.logger import log_info, log_success, log_warning, log_error, log_critical
from ..shared.field_icons import field_type_icon
from ..shared.geom_types import get_pg_geom_type
from ..shared.compat import (
    AlignCenter,
    ComboAdjustMinContentsIcon,
    DialogAccepted,
    EventFontChange,
    FormAllNonFixedFieldsGrow,
    FormWrapLongRows,
    FrameBox,
    FrameNoFrame,
    FrameRaised,
    FrameStyledPanel,
    HeaderInteractive,
    HeaderStretch,
    ItemIsEnabled,
    ItemIsSelectable,
    MsgBoxIconInfo,
    MsgBoxNo,
    MsgBoxOk,
    MsgBoxYes,
    MsgCritical,
    MsgInfo,
    MsgSuccess,
    MsgWarning,
    PasswordEchoMode,
    PlainText,
    SelectRows,
    _SizePolicy,
)

# Import PostgreSQL dependencies
try:
    import psycopg2
    from psycopg2 import sql
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    QgsMessageLog.logMessage("psycopg2 not available. PostgreSQL features will be limited.", "Transformer", MsgWarning)


from .export_task import PgExportTask
from .connection_task import (
    PgConnectionTask,
    PgSchemaTask,
    PgCompatibilityTask,
)
from .connection_task import PgConnectionPoolManager  # noqa: F401


class IntegrationConfirmationDialog(QDialog):
    """Interactive dialog for PostgreSQL mapping confirmation"""

    def __init__(self, compatibility_info, available_schemas=None, parent=None):
        super().__init__(parent)
        self.compatibility_info = compatibility_info
        self.available_schemas = available_schemas or []
        self.modified_mappings = {}  # Stockage des modifications
        self.original_mappings = {}  # Mappings originaux pour comparaison
        self.mapping_widgets = {}  # Widgets de mapping pour chaque couche
        self.dont_show_again = False  # Attribut manquant

        # Sauvegarder les mappings originaux
        for info in compatibility_info:
            key = info['layer']
            self.original_mappings[key] = {
                'schema': info['schema'],
                'table': info['table']
            }

        self.setup_ui()

    def setup_ui(self):
        """Setup the UI for the PostgreSQL mapping dialog"""
        self.setWindowTitle("Publier vers PostgreSQL")
        self.setAccessibleName("Confirmation de la publication PostgreSQL")
        self.setModal(True)

        # Optimized size for the mapping table
        self.resize(920, 640)

        # Main layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(FrameNoFrame)
        self.content_scroll.setAccessibleName("Paramètres et correspondances de publication")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)
        self.content_scroll.setWidget(content)
        outer.addWidget(self.content_scroll, 1)

        # Title and instructions - NATIVE QGIS STYLE
        title_label = QLabel("Vérifier les correspondances avant publication")
        title_label.setWordWrap(True)
        title_label.setAlignment(AlignCenter)
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        subtitle_label = QLabel("L'analyse n'a modifié aucune donnée. Choisissez les champs à livrer puis vérifiez les conséquences ci-dessous.")
        subtitle_label.setWordWrap(True)
        subtitle_label.setAlignment(AlignCenter)
        layout.addWidget(subtitle_label)

        # Tabs for each layer - NATIVE QGIS STYLE
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Correspondances par couche source")
        self.tabs.setMinimumHeight(self.fontMetrics().height() * 12)
        # Remove all custom CSS - use native QGIS styling

        # Create a tab for each layer
        for i, info in enumerate(self.compatibility_info):
            tab_widget = self._create_field_mapping_table(info)
            self.tabs.addTab(tab_widget, f"{info['layer']}")

        layout.addWidget(self.tabs)

        # Statistiques de mapping - NATIVE QGIS STYLE
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setAccessibleName("Bilan des correspondances")
        # Create native frame for stats
        stats_frame = QFrame()
        stats_frame.setFrameStyle(FrameBox | FrameRaised)
        stats_frame.setLineWidth(1)
        stats_frame_layout = QHBoxLayout(stats_frame)
        stats_frame_layout.addWidget(self.stats_label)
        stats_layout.addWidget(stats_frame)
        layout.addLayout(stats_layout)
        actions_layout = QHBoxLayout()

        # Quick action buttons - NATIVE QGIS STYLE
        self.auto_map_btn = QPushButton("&Associer automatiquement")
        self.clear_btn = QPushButton("&Vider les associations")
        self.add_field_btn = QPushButton("Ajouter une &constante")
        self.add_field_btn.setEnabled(False)
        self.add_field_btn.setToolTip("Définissez les constantes dans la recette avant le calcul, puis publiez la couche obtenue.")

        actions_layout.addWidget(self.auto_map_btn)
        actions_layout.addWidget(self.clear_btn)
        actions_layout.addWidget(self.add_field_btn)
        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        # **NOUVELLEMENT AJOUTÃ‰** - Section Mode d'Export
        export_mode_frame = QFrame()
        export_mode_frame.setFrameStyle(FrameBox | FrameRaised)
        export_mode_frame.setLineWidth(1)
        export_mode_layout = QVBoxLayout(export_mode_frame)

        # Titre section
        mode_title = QLabel("Données des tables de destination")
        mode_title_font = mode_title.font()
        mode_title_font.setBold(True)
        mode_title.setFont(mode_title_font)
        export_mode_layout.addWidget(mode_title)

        # Radio buttons pour les modes
        mode_buttons_layout = QHBoxLayout()

        self.append_mode = QRadioButton("&Ajouter les lignes")
        self.append_mode.setAccessibleName("Ajouter les lignes aux tables de destination")
        self.append_mode.setToolTip("Conserver les lignes existantes et ajouter celles des couches sources. Un rejeu peut créer des doublons.")
        self.append_mode.setChecked(True)  # Mode par défaut

        self.replace_mode = QRadioButton("&Remplacer les données")
        self.replace_mode.setAccessibleName("Remplacer toutes les données des tables de destination")
        self.replace_mode.setToolTip("Supprimer toutes les lignes existantes de chaque table puis insérer les lignes sources, dans une même transaction par table.")

        self.update_mode = QRadioButton("Mettre à jour (indisponible)")
        self.update_mode.setEnabled(False)
        self.update_mode.setToolTip("La mise à jour par clé n'est pas disponible. Choisissez l'ajout ou le remplacement.")

        mode_buttons_layout.addWidget(self.append_mode)
        mode_buttons_layout.addWidget(self.replace_mode)
        mode_buttons_layout.addWidget(self.update_mode)
        mode_buttons_layout.addStretch()

        export_mode_layout.addLayout(mode_buttons_layout)

        # **NOUVEAU** - Configuration Update Mode
        self.update_config_widget = QWidget()
        update_config_layout = QVBoxLayout(self.update_config_widget)

        # Type de clé de jointure
        join_type_layout = QHBoxLayout()
        join_type_layout.addWidget(QLabel("Type de jointure :"))

        self.attribute_join = QRadioButton("Par attribut")
        self.attribute_join.setToolTip("Associer les lignes par un champ commun (identifiant, code).")
        self.attribute_join.setChecked(True)

        self.spatial_join = QRadioButton("Par géométrie")
        self.spatial_join.setToolTip("Associer les lignes par relation spatiale.")

        join_type_layout.addWidget(self.attribute_join)
        join_type_layout.addWidget(self.spatial_join)
        join_type_layout.addStretch()
        update_config_layout.addLayout(join_type_layout)

        # Configuration clé attributaire
        self.attribute_config = QWidget()
        attr_layout = QHBoxLayout(self.attribute_config)
        attr_layout.addWidget(QLabel("Champ de jointure :"))

        self.source_key_combo = QComboBox()
        self.source_key_combo.setToolTip("Champ de jointure de la couche source")
        self.target_key_combo = QComboBox()
        self.target_key_combo.setToolTip("Champ de jointure de la table de destination")

        attr_layout.addWidget(QLabel("Source :"))
        attr_layout.addWidget(self.source_key_combo)
        attr_layout.addWidget(QLabel("Destination :"))
        attr_layout.addWidget(self.target_key_combo)
        attr_layout.addStretch()
        update_config_layout.addWidget(self.attribute_config)

        # Configuration clé spatiale
        self.spatial_config = QWidget()
        spatial_layout = QHBoxLayout(self.spatial_config)
        spatial_layout.addWidget(QLabel("Relation spatiale :"))

        self.spatial_method_combo = QComboBox()
        self.spatial_method_combo.addItems([
            "Intersects", "Contains", "Within",
            "Touches", "Overlaps", "Nearest (buffer)"
        ])
        self.spatial_method_combo.setToolTip("Relation spatiale utilisée pour associer les lignes")

        self.buffer_distance = QDoubleSpinBox()
        self.buffer_distance.setRange(0, 10000)
        self.buffer_distance.setValue(0.1)
        self.buffer_distance.setSuffix(" m")
        self.buffer_distance.setToolTip("Distance de recherche pour la jointure spatiale")

        spatial_layout.addWidget(self.spatial_method_combo)
        spatial_layout.addWidget(QLabel("Distance :"))
        spatial_layout.addWidget(self.buffer_distance)
        spatial_layout.addStretch()
        update_config_layout.addWidget(self.spatial_config)

        self.update_config_widget.setVisible(False)  # Masqué par défaut
        export_mode_layout.addWidget(self.update_config_widget)

        # Message d'avertissement pour Replace mode
        self.warning_label = QLabel("Remplacement : toutes les lignes actuelles des tables de destination seront supprimées. Vérifiez le schéma et la table de chaque onglet.")
        self.warning_label.setWordWrap(True)
        warning_font = self.warning_label.font()
        warning_font.setBold(True)
        self.warning_label.setFont(warning_font)
        self.warning_label.setVisible(False)
        export_mode_layout.addWidget(self.warning_label)

        # Connecter les radio buttons pour afficher/masquer l'avertissement et config
        self.replace_mode.toggled.connect(self._on_export_mode_changed)
        self.append_mode.toggled.connect(self._on_export_mode_changed)
        self.update_mode.toggled.connect(self._on_export_mode_changed)

        # Connecter les radio buttons de type de jointure
        self.attribute_join.toggled.connect(self._on_join_type_changed)
        self.spatial_join.toggled.connect(self._on_join_type_changed)

        layout.addWidget(export_mode_frame)

        self.consequences_label = QLabel()
        self.consequences_label.setTextFormat(PlainText)
        self.consequences_label.setWordWrap(True)
        self.consequences_label.setAccessibleName("Conséquences de la publication")
        layout.addWidget(self.consequences_label)

        # Case à cocher "Ne plus afficher" - NATIVE QGIS STYLE
        checkbox_container = QHBoxLayout()
        self.dont_show_checkbox = QCheckBox("Confirmation obligatoire avant chaque publication")
        self.dont_show_checkbox.setEnabled(False)
        self.dont_show_checkbox.hide()
        # Use native QGIS checkbox styling - no custom CSS
        checkbox_container.addWidget(self.dont_show_checkbox)
        checkbox_container.addStretch()
        layout.addLayout(checkbox_container)

        # Main buttons - NATIVE QGIS STYLE
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)

        self.reset_btn = QPushButton("&Rétablir")
        self.save_column_config_btn = QPushButton("&Enregistrer les associations")
        self.cancel_btn = QPushButton("&Annuler")
        self.proceed_btn = QPushButton("&Publier")
        self.proceed_btn.setAccessibleName("Confirmer et publier vers PostgreSQL")
        self.cancel_btn.setAccessibleName("Annuler sans modifier PostgreSQL")

        # Native QGIS button sizes - no custom styling
        secondary_layout = QHBoxLayout()
        secondary_layout.addWidget(self.reset_btn)
        secondary_layout.addWidget(self.save_column_config_btn)
        secondary_layout.addStretch()
        layout.addLayout(secondary_layout)
        self.cancel_btn.setDefault(True)
        self.proceed_btn.setAutoDefault(False)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_btn)
        buttons_layout.addWidget(self.proceed_btn)

        outer.addLayout(buttons_layout)
        self.setTabOrder(self.tabs, self.auto_map_btn)
        self.setTabOrder(self.auto_map_btn, self.clear_btn)
        self.setTabOrder(self.clear_btn, self.add_field_btn)
        self.setTabOrder(self.add_field_btn, self.append_mode)
        self.setTabOrder(self.append_mode, self.replace_mode)
        self.setTabOrder(self.cancel_btn, self.proceed_btn)

        # Connexions
        self.tabs.currentChanged.connect(self._update_stats)
        self.auto_map_btn.clicked.connect(self._auto_map_current_layer)
        self.clear_btn.clicked.connect(self._clear_current_mapping)
        self.add_field_btn.clicked.connect(self._add_custom_field)
        self.reset_btn.clicked.connect(self._reset_mappings)
        self.save_column_config_btn.clicked.connect(self._save_column_config)
        self.cancel_btn.clicked.connect(self.reject)
        self.proceed_btn.clicked.connect(self._confirm_publication)
        self.dont_show_checkbox.toggled.connect(self._on_dont_show_toggled)

        # Update initial stats
        self._update_stats()
        self._update_consequences()
        self.cancel_btn.setFocus()

    def _update_consequences(self):
        """Rendre la portée du plan visible sans lire ni modifier la base."""
        mode = self.get_selected_export_mode()
        rows = []
        for widgets in self.mapping_widgets.values():
            info = widgets['info']
            table = widgets['table']
            fields = sum(bool(table.cellWidget(row, 2).currentData())
                         for row in range(table.rowCount()) if table.cellWidget(row, 2))
            if info.get('requires_creation'):
                action = "créer la table et insérer les lignes sources"
            elif mode == 'replace':
                action = "supprimer les lignes existantes puis insérer les lignes sources"
            else:
                action = "conserver les lignes existantes et ajouter les lignes sources"
            rows.append(f"{info['layer']} : {info['schema']}.{info['table']} ; {action} ; {fields} champ(s) associé(s).")
        rows.append("Chaque table est validée séparément. En cas d'échec ou d'annulation, les tables déjà validées restent publiées. Consultez le bilan avant de relancer pour éviter les doublons.")
        self.consequences_label.setText("\n".join(rows))

    def _confirm_publication(self):
        """Garder les corrections de correspondance dans le dialogue ouvert."""
        try:
            self.get_execution_plans()
        except ValueError as exc:
            QMessageBox.warning(self, "Correspondances à corriger", str(exc))
            return
        self.accept()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == EventFontChange and hasattr(self, 'mapping_widgets'):
            for widgets in self.mapping_widgets.values():
                widgets['table'].verticalHeader().setDefaultSectionSize(max(32, self.fontMetrics().height() + 16))

    def _create_field_mapping_table(self, info):
        """Create the field mapping table for a layer"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # En-tête avec informations sur la couche - NATIVE QGIS STYLE
        header_frame = QFrame()
        header_frame.setFrameStyle(FrameStyledPanel | FrameRaised)
        header_layout = QHBoxLayout(header_frame)

        layer_info = QLabel(f"Source : {info['layer']}\nDestination : {info['schema']}.{info['table']}")
        layer_info.setTextFormat(PlainText)
        layer_info.setWordWrap(True)
        layer_font = layer_info.font()
        layer_font.setBold(True)
        layer_info.setFont(layer_font)
        header_layout.addWidget(layer_info)
        layout.addWidget(header_frame)

        # Table for field mapping
        table = QTableWidget()
        table.setAccessibleName(f"Correspondances de {info['layer']} vers {info['schema']}.{info['table']}")
        table.setColumnCount(7)  # Add a column for deletion
        table.setHorizontalHeaderLabels([
            "Champ source",
            "Type source",
            "Champ cible",
            "Type cible",
            "Conversion",
            "État",
            "Action"
        ])

        # Use native QGIS table styling - remove all custom CSS

        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(SelectRows)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(max(32, self.fontMetrics().height() + 16))

        # Column configuration
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(HeaderInteractive)
        header.setMinimumSectionSize(self.fontMetrics().horizontalAdvance("Conversion") + 24)

        # Column widths
        table.setColumnWidth(0, 160)  # Source field
        table.setColumnWidth(1, 90)  # Source type
        table.setColumnWidth(3, 110)  # Destination type
        table.setColumnWidth(4, 110)  # Forced type
        table.setColumnWidth(5, 60)  # Status
        table.setColumnWidth(6, self.fontMetrics().horizontalAdvance("Retirer") + 40)
        table.setColumnWidth(2, max(180, self.fontMetrics().horizontalAdvance("Champ cible") + 40))

        # Field source and destination retrieval
        source_fields = info.get('source_fields', [])
        dest_fields = info.get('dest_fields', [])
        field_matches = info.get('field_matches', {})

        # Add rows for each source field
        table.setRowCount(len(source_fields))

        for row, source_field in enumerate(source_fields):
            # Source field (read-only)
            source_item = QTableWidgetItem(source_field['name'])
            source_item.setFlags(ItemIsEnabled | ItemIsSelectable)

            # Set icon only if it exists
            icon = self._get_field_icon(source_field['type'])
            if icon:
                source_item.setIcon(icon)

            table.setItem(row, 0, source_item)

            # Source type (read-only)
            type_item = QTableWidgetItem(source_field['type'])
            type_item.setFlags(ItemIsEnabled | ItemIsSelectable)
            table.setItem(row, 1, type_item)

            # Destination field (ComboBox modifiable)
            dest_combo = QComboBox()
            dest_combo.addItem("<Non associé>", "")
            dest_combo.setAccessibleName(f"Champ cible pour {source_field['name']}")

            # Add all available destination fields
            for dest_field in dest_fields:
                dest_combo.addItem(dest_field['name'], dest_field['name'])

            # Select automatic mapping if it exists
            if source_field['name'] in field_matches:
                matched_field = field_matches[source_field['name']]
                index = dest_combo.findData(matched_field)
                if index >= 0:
                    dest_combo.setCurrentIndex(index)

            dest_combo.currentTextChanged.connect(
                lambda text, r=row: self._on_field_mapping_changed(r)
            )

            table.setCellWidget(row, 2, dest_combo)

            # Destination type (read-only, automatically updated)
            dest_type_item = QTableWidgetItem()
            dest_type_item.setFlags(ItemIsEnabled | ItemIsSelectable)
            self._update_dest_type(dest_type_item, dest_combo.currentData(), dest_fields)
            table.setItem(row, 3, dest_type_item)

            # Forced type (ComboBox modifiable)
            forced_type_combo = QComboBox()
            forced_type_combo.setAccessibleName(f"Conversion pour {source_field['name']}")
            forced_type_combo.addItems([
                "<Auto>",  # Default value - uses the destination type
                "character varying",
                "text",
                "integer",
                "bigint",
                "double precision",
                "real",
                "boolean",
                "date",
                "timestamp",
                "uuid"
            ])

            forced_type_combo.currentTextChanged.connect(
                lambda text, r=row: self._on_field_mapping_changed(r)
            )

            table.setCellWidget(row, 4, forced_type_combo)

            # Compatibility status
            status_item = QTableWidgetItem()
            status_item.setFlags(ItemIsEnabled | ItemIsSelectable)
            self._update_compatibility_status(status_item, source_field, dest_combo.currentData(), dest_fields)
            table.setItem(row, 5, status_item)

            # Delete button (only for non-essential fields) - NATIVE QGIS STYLE
            delete_btn = QPushButton("Retirer")
            delete_btn.setAccessibleName(f"Retirer le champ {source_field['name']} de la publication")
            delete_btn.setToolTip("Retirer cette association du plan ; le champ de la couche source est conservé.")
            # Use native QGIS button styling - no custom CSS
            delete_btn.clicked.connect(lambda checked, r=row: self._delete_field_mapping(r))
            table.setCellWidget(row, 6, delete_btn)

        layout.addWidget(table)

        # Save table reference
        layer_key = f"{info['layer']} / {info['schema']}.{info['table']}"
        self.mapping_widgets[layer_key] = {
            'table': table,
            'info': info,
            'source_fields': source_fields,
            'dest_fields': dest_fields
        }

        return widget

    def _get_field_icon(self, field_type):
        """Return an icon reflecting the PostgreSQL/QGIS field type."""
        if not field_type:
            return None
        return field_type_icon(field_type)

    def _update_dest_type(self, item, dest_field_name, dest_fields):
        """Update the destination field type"""
        if not dest_field_name:
            item.setText("-")
            return

        for field in dest_fields:
            if field['name'] == dest_field_name:
                item.setText(field['type'])
                return

        item.setText("Inconnu")

    def _update_compatibility_status(self, item, source_field, dest_field_name, dest_fields):
        """Update the compatibility status"""
        if not dest_field_name:
            item.setText("NOK")
            item.setToolTip("Champ non associé ; il ne sera pas publié.")
            return

        # Search for the destination field
        dest_field = None
        for field in dest_fields:
            if field['name'] == dest_field_name:
                dest_field = field
                break

        if not dest_field:
            item.setText("ERR")
            item.setToolTip("Champ cible introuvable ; choisissez un champ existant.")
            return

        # Check type compatibility
        if self._are_types_compatible(source_field['type'], dest_field['type']):
            item.setText("OK")
            item.setToolTip("Types compatibles")
        else:
            item.setText("À vérifier")
            item.setToolTip(f"Attention: {source_field['type']} -> {dest_field['type']}")

    def _are_types_compatible(self, source_type, dest_type):
        """Vérifie si deux types de champs sont compatibles"""
        # Mapping des types compatibles
        compatibility_map = {
            'String': ['character varying', 'text', 'varchar', 'char'],
            'Integer': ['integer', 'bigint', 'smallint', 'int4', 'int8'],
            'Real': ['double precision', 'real', 'numeric', 'float8', 'float4'],
            'Date': ['date', 'timestamp', 'timestamptz'],
            'DateTime': ['timestamp', 'timestamptz', 'date'],
            'Boolean': ['boolean', 'bool']
        }

        dest_type_lower = dest_type.lower()

        if source_type in compatibility_map:
            return any(compat.lower() in dest_type_lower for compat in compatibility_map[source_type])

        # By default, consider as compatible if same name
        return source_type.lower() == dest_type_lower

    def _update_compatibility_status_with_forced_type(self, item, source_field, dest_field_name, dest_fields, forced_type):
        """Update the compatibility status taking into account the forced type"""
        if not dest_field_name:
            item.setText("NOK")
            item.setToolTip("Champ non associé ; il ne sera pas publié.")
            return

        # If a forced type is defined, always compatible (force conversion)
        if forced_type != "<Auto>":
            item.setText("FORCE")
            item.setToolTip(f"Conversion forcée : {source_field['type']} -> {forced_type}. Une valeur incompatible peut faire échouer la table.")
            return

        # Otherwise, use normal logic
        dest_field = None
        for field in dest_fields:
            if field['name'] == dest_field_name:
                dest_field = field
                break

        if not dest_field:
            item.setText("ERR")
            item.setToolTip("Champ cible introuvable ; choisissez un champ existant.")
            return

        # Check type compatibility
        if self._are_types_compatible(source_field['type'], dest_field['type']):
            item.setText("OK")
            item.setToolTip("Types compatibles")
        else:
            item.setText("À vérifier")
            item.setToolTip(f"Conversion à vérifier : {source_field['type']} -> {dest_field['type']}. Choisissez une conversion si nécessaire.")

    def _on_field_mapping_changed(self, row):
        """Called when a field mapping is modified"""
        current_tab = self.tabs.currentIndex()
        if current_tab < 0:
            return

        layer_key = list(self.mapping_widgets.keys())[current_tab]
        widgets = self.mapping_widgets[layer_key]
        table = widgets['table']
        dest_fields = widgets['dest_fields']

        # Récupération du nouveau mapping
        combo = table.cellWidget(row, 2)
        if not combo:
            return

        dest_field_name = combo.currentData()

        # Vérifier si c'est un champ personnalisé ou un champ source normal
        if row < len(widgets['source_fields']):
            # Champ source normal
            source_field = widgets['source_fields'][row]
        else:
            # Champ personnalisé - créer une structure compatible
            source_item = table.item(row, 0)
            type_item = table.item(row, 1)
            if source_item and type_item:
                source_field = {
                    'name': source_item.text(),
                    'type': type_item.text()
                }
            else:
                return  # Impossible de traiter cette ligne

        # Mise à jour du type de destination
        dest_type_item = table.item(row, 3)
        if dest_type_item:
            self._update_dest_type(dest_type_item, dest_field_name, dest_fields)

        # Mise à jour du statut de compatibilité (reste colonne 5)
        status_item = table.item(row, 5)
        if status_item:
            # Prendre en compte le type forcé si défini
            forced_type_combo = table.cellWidget(row, 4)
            forced_type = forced_type_combo.currentText() if forced_type_combo else "<Auto>"

            self._update_compatibility_status_with_forced_type(status_item, source_field, dest_field_name, dest_fields, forced_type)

        # Update statistics
        self._update_stats()

    def _update_stats(self):
        """Update mapping statistics"""
        if not self.mapping_widgets:
            return

        current_tab = self.tabs.currentIndex()
        if current_tab < 0:
            return

        layer_key = list(self.mapping_widgets.keys())[current_tab]
        widgets = self.mapping_widgets[layer_key]
        table = widgets['table']

        total_fields = table.rowCount()
        mapped_fields = 0
        compatible_fields = 0

        for row in range(total_fields):
            combo = table.cellWidget(row, 2)
            status_item = table.item(row, 5)  # Statut en colonne 5 maintenant

            if combo and combo.currentData():
                mapped_fields += 1

                if status_item and status_item.text() in ["OK", "FORCE"]:
                    compatible_fields += 1

        mapping_percentage = (mapped_fields / total_fields * 100) if total_fields > 0 else 0
        compatibility_percentage = (compatible_fields / mapped_fields * 100) if mapped_fields > 0 else 0

        stats_text = (
            f"{layer_key}: "
            f"{mapped_fields}/{total_fields} champs associés ({mapping_percentage:.1f}%) | "
            f"{compatible_fields}/{mapped_fields} compatibles ({compatibility_percentage:.1f}%)"
        )

        self.stats_label.setText(stats_text)
        if hasattr(self, 'consequences_label'):
            self._update_consequences()

    def _auto_map_current_layer(self):
        """Apply automatic mapping to the current layer"""
        current_tab = self.tabs.currentIndex()
        if current_tab < 0:
            return

        layer_key = list(self.mapping_widgets.keys())[current_tab]
        widgets = self.mapping_widgets[layer_key]
        table = widgets['table']
        source_fields = widgets['source_fields']
        dest_fields = widgets['dest_fields']

        for row in range(len(source_fields)):
            source_field = source_fields[row]
            combo = table.cellWidget(row, 2)

            if not combo:
                continue

            # Recherche du meilleur match automatique
            best_match = self._find_best_field_match(source_field, dest_fields)
            if best_match:
                index = combo.findData(best_match)
                if index >= 0:
                    combo.setCurrentIndex(index)

    def _find_best_field_match(self, source_field, dest_fields):
        """Find the best automatic match for a field"""
        source_name = source_field['name'].lower()

        # Exact match first
        for dest_field in dest_fields:
            if dest_field['name'].lower() == source_name:
                return dest_field['name']

        # Recherche par similarité de nom
        for dest_field in dest_fields:
            dest_name = dest_field['name'].lower()
            if source_name in dest_name or dest_name in source_name:
                return dest_field['name']

        return None

    def _clear_current_mapping(self):
        """Clear the mapping of the current layer"""
        current_tab = self.tabs.currentIndex()
        if current_tab < 0:
            return

        layer_key = list(self.mapping_widgets.keys())[current_tab]
        widgets = self.mapping_widgets[layer_key]
        table = widgets['table']

        for row in range(table.rowCount()):
            combo = table.cellWidget(row, 2)
            if combo:
                combo.setCurrentIndex(0)  # "<Non mappé>"

    def _reset_mappings(self):
        """Reset all mappings to their initial state"""
        for layer_key, widgets in self.mapping_widgets.items():
            table = widgets['table']
            info = widgets['info']
            field_matches = info.get('field_matches', {})

            for row in range(table.rowCount()):
                combo = table.cellWidget(row, 2)
                if not combo:
                    continue

                source_field_name = widgets['source_fields'][row]['name']

                # Remettre le mapping automatique original
                if source_field_name in field_matches:
                    matched_field = field_matches[source_field_name]
                    index = combo.findData(matched_field)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                    else:
                        combo.setCurrentIndex(0)
                else:
                    combo.setCurrentIndex(0)

    def _add_custom_field(self):
        """Add a custom field with default value"""
        current_tab = self.tabs.currentIndex()
        if current_tab < 0:
            QMessageBox.warning(self, "Choisir une couche", "Sélectionnez un onglet de couche avant d'ajouter un champ.")
            return

        # Dialogue for entering the custom field name and default value
        field_name, ok1 = QInputDialog.getText(self,
                                               "Nom du champ",
                                               "Nom du champ constant :")

        if not ok1 or not field_name.strip():
            return

        field_name = field_name.strip()

        # Dialogue for entering the default value
        default_value, ok2 = QInputDialog.getText(self,
                                                  "Valeur constante",
                                                  f"Valeur à affecter à '{field_name}' :")

        if not ok2:
            return

        # Dialogue for entering the PostgreSQL type
        pg_types = [
            "character varying",
            "text",
            "integer",
            "bigint",
            "double precision",
            "real",
            "boolean",
            "date",
            "timestamp",
            "uuid"
        ]

        pg_type, ok3 = QInputDialog.getItem(self,
                                            "Type PostgreSQL",
                                            f"Choisissez le type PostgreSQL pour '{field_name}':",
                                            pg_types, 0, False)

        if not ok3:
            return

        # Add the custom field to the current layer table
        layer_key = list(self.mapping_widgets.keys())[current_tab]
        widgets = self.mapping_widgets[layer_key]
        table = widgets['table']

        # Add a new row
        row_count = table.rowCount()
        table.setRowCount(row_count + 1)
        row = row_count

        # Champ source (personnalisé)
        source_item = QTableWidgetItem(f"[CUSTOM] {field_name}")
        source_item.setFlags(ItemIsEnabled | ItemIsSelectable)
        source_item.setBackground(QColor(255, 255, 200))  # Jaune clair pour les champs personnalisés
        table.setItem(row, 0, source_item)

        # Type source
        type_item = QTableWidgetItem("Constante")
        type_item.setFlags(ItemIsEnabled | ItemIsSelectable)
        type_item.setBackground(QColor(255, 255, 200))
        table.setItem(row, 1, type_item)

        # Destination field (modifiable - user can choose)
        dest_combo = QComboBox()
        dest_combo.addItem("<Non associé>", "")

        # Add all available destination fields
        dest_fields = widgets['dest_fields']
        for dest_field in dest_fields:
            dest_combo.addItem(dest_field['name'], dest_field['name'])

        # Add the custom field name as an option
        dest_combo.addItem(f"[NOUVEAU] {field_name}", field_name)

        # Select the new field by default
        dest_combo.setCurrentIndex(dest_combo.count() - 1)

        # Connect for modifications
        dest_combo.currentTextChanged.connect(
            lambda text, r=row: self._on_field_mapping_changed(r)
        )

        table.setCellWidget(row, 2, dest_combo)

        # Type destination
        dest_type_item = QTableWidgetItem(pg_type)
        dest_type_item.setFlags(ItemIsEnabled | ItemIsSelectable)
        dest_type_item.setBackground(QColor(255, 255, 200))
        table.setItem(row, 3, dest_type_item)

        # Forced type (already defined)
        forced_type_combo = QComboBox()
        forced_type_combo.addItem(pg_type)
        forced_type_combo.setCurrentIndex(0)
        forced_type_combo.setEnabled(False)  # Non modifiable
        table.setCellWidget(row, 4, forced_type_combo)

        # Custom status
        status_item = QTableWidgetItem("CUSTOM")
        status_item.setFlags(ItemIsEnabled | ItemIsSelectable)
        status_item.setToolTip(f"Constante : {field_name} = '{default_value}' ({pg_type})")
        status_item.setBackground(QColor(255, 255, 200))
        table.setItem(row, 5, status_item)

        # Delete button for custom fields - NATIVE QGIS STYLE
        delete_btn = QPushButton("Retirer")
        delete_btn.setToolTip("Retirer cette constante du plan de publication")
        # Use native QGIS button styling - no custom CSS
        delete_btn.clicked.connect(lambda checked, r=row: self._delete_field_mapping(r))
        table.setCellWidget(row, 6, delete_btn)

        # Store custom field information
        if not hasattr(widgets, 'custom_fields'):
            widgets['custom_fields'] = []

        widgets['custom_fields'].append({
            'name': field_name,
            'default_value': default_value,
            'type': pg_type,
            'row': row
        })

        # Update stats
        self._update_stats()

        QgsMessageLog.logMessage(f"Custom field '{field_name}' added successfully with type {pg_type}", "Transformer", MsgSuccess)

    def _delete_field_mapping(self, row):
        """Supprime un mapping de champ"""
        current_tab = self.tabs.currentIndex()
        current_widget = self.tabs.widget(current_tab)

        # Trouver la table dans le layout
        table = None
        for i in range(current_widget.layout().count()):
            widget = current_widget.layout().itemAt(i).widget()
            if isinstance(widget, QTableWidget):
                table = widget
                break

        if not table:
            return

        # Confirmation de suppression
        source_item = table.item(row, 0)
        if source_item:
            field_name = source_item.text()
            reply = QMessageBox.question(
                self,
                "Retirer une association",
                f"Retirer l'association de '{field_name}' du plan de publication ? Le champ source sera conservé.",
                MsgBoxYes | MsgBoxNo,
                MsgBoxNo
            )

            if reply == MsgBoxYes:
                # Remove the row
                table.removeRow(row)

                # Clean up custom fields if necessary
                layer_key = list(self.mapping_widgets.keys())[current_tab]
                widgets = self.mapping_widgets[layer_key]

                if hasattr(widgets, 'custom_fields'):
                    # Mettre à jour les indices des champs personnalisés
                    widgets['custom_fields'] = [
                        cf for cf in widgets['custom_fields']
                        if cf.get('row', -1) != row
                    ]

                    # Réajuster les indices
                    for cf in widgets['custom_fields']:
                        if cf.get('row', -1) > row:
                            cf['row'] -= 1

                # Mise à jour des statistiques
                self._update_stats()

    def get_modified_mappings(self):
        """Récupère tous les mappings modifiés"""
        mappings = {}

        for layer_key, widgets in self.mapping_widgets.items():
            table = widgets['table']
            widgets['source_fields']

            field_mapping = {}
            for row in range(table.rowCount()):
                combo = table.cellWidget(row, 2)
                if combo and combo.currentData():
                    # Retrieve the source field name from the table
                    source_item = table.item(row, 0)
                    if source_item:
                        source_field_name = source_item.text()
                        # Clean the name for custom fields
                        if source_field_name.startswith("[CUSTOM] "):
                            source_field_name = source_field_name.replace("[CUSTOM] ", "")

                        dest_field_name = combo.currentData()
                        field_mapping[source_field_name] = dest_field_name

            mappings[layer_key] = field_mapping

        return mappings

    def get_execution_plans(self):
        """Freeze exactly the source, destination and conversion shown to the user."""
        plans = []
        for widgets in self.mapping_widgets.values():
            table = widgets["table"]
            entries = []
            targets = set()
            for row in range(table.rowCount()):
                source_item = table.item(row, 0)
                destination = table.cellWidget(row, 2)
                if source_item is None or destination is None:
                    continue
                target = destination.currentData()
                if not target:
                    continue
                if target in targets:
                    raise ValueError(f"Le champ cible '{target}' reçoit plusieurs sources.")
                targets.add(target)
                type_widget = table.cellWidget(row, 4)
                conversion = type_widget.currentText() if type_widget else "<Auto>"
                entries.append({
                    "source": source_item.text().strip(), "target": target,
                    "type": "" if conversion == "<Auto>" else conversion,
                })
            if not entries:
                raise ValueError("Choisissez au moins une correspondance pour chaque table.")
            plans.append({**widgets["info"], "field_mapping": entries})
        return plans

    def _on_export_mode_changed(self):
        """Gère l'affichage du message d'avertissement et de la config selon le mode sélectionné"""
        if self.replace_mode.isChecked():
            self.warning_label.setVisible(True)
            self.update_config_widget.setVisible(False)
        elif self.update_mode.isChecked():
            self.warning_label.setVisible(False)
            self.update_config_widget.setVisible(True)
            self._populate_key_fields()
        else:  # append mode
            self.warning_label.setVisible(False)
            self.update_config_widget.setVisible(False)
        if hasattr(self, 'consequences_label'):
            self._update_consequences()

    def _on_join_type_changed(self):
        """Gère l'affichage des configurations selon le type de jointure"""
        if self.attribute_join.isChecked():
            self.attribute_config.setVisible(True)
            self.spatial_config.setVisible(False)
        else:  # spatial join
            self.attribute_config.setVisible(False)
            self.spatial_config.setVisible(True)

    def _populate_key_fields(self):
        """Remplit les combo boxes avec les champs disponibles"""
        # Vider les combos
        self.source_key_combo.clear()
        self.target_key_combo.clear()

        # Remplir avec les champs des couches sources
        for table_info in self.compatibility_info:
            layer_name = table_info.get('layer', '')
            layer = QgsProject.instance().mapLayersByName(layer_name)
            if layer:
                source_layer = layer[0]
                for field in source_layer.fields():
                    self.source_key_combo.addItem(field.name())
                break

        # Remplir avec les champs de la table PostgreSQL cible
        # On peut prendre le premier mapping comme exemple
        if self.compatibility_info:
            first_table = self.compatibility_info[0]
            first_table.get('schema', '')
            first_table.get('table', '')

            try:
                # Récupérer les champs de la table PostgreSQL
                # (Code de connexion similaire à celui utilisé ailleurs)
                self.target_key_combo.addItem("id")  # Champ ID généralement présent
                # TODO: Récupérer dynamiquement les champs de la table PostgreSQL
            except Exception as exc:
                QgsMessageLog.logMessage(f"Error populating key fields: {exc}", "Transformer", MsgWarning)

    def get_selected_export_mode(self):
        """Retourne le mode d'export sélectionné"""
        if self.append_mode.isChecked():
            return "append"
        elif self.replace_mode.isChecked():
            return "replace"
        elif self.update_mode.isChecked():
            return "update"
        else:
            return "append"  # Par défaut

    def get_update_configuration(self):
        """Retourne la configuration pour le mode Update"""
        if not self.update_mode.isChecked():
            return None

        config = {
            'join_type': 'attribute' if self.attribute_join.isChecked() else 'spatial'
        }

        if config['join_type'] == 'attribute':
            config.update({
                'source_key_field': self.source_key_combo.currentText(),
                'target_key_field': self.target_key_combo.currentText()
            })
        else:  # spatial
            config.update({
                'spatial_method': self.spatial_method_combo.currentText().lower(),
                'buffer_distance': self.buffer_distance.value()
            })

        return config

    def _on_dont_show_toggled(self, checked):
        """Handle the 'do not show again' checkbox"""
        self.dont_show_again = checked

    def _save_column_config(self):
        """Save complete column configuration to postgresql_detailed_mappings.json"""
        try:
            # Get complete mapping info from all tabs
            detailed_mappings = []

            for tab_index in range(self.tabs.count()):
                # Temporarily switch to each tab to extract its data
                current_tab = self.tabs.currentIndex()
                self.tabs.setCurrentIndex(tab_index)

                tab_widget = self.tabs.widget(tab_index)
                tab_text = self.tabs.tabText(tab_index)

                if tab_widget and hasattr(tab_widget, 'children'):
                    # Extract complete mapping info
                    complete_info = self.get_complete_mapping_info()

                    # Find corresponding layer info
                    layer_info = None
                    for info in self.compatibility_info:
                        if info['layer'] == tab_text:
                            layer_info = info
                            break

                    if layer_info:
                        detailed_mapping = {
                            "layer_name": layer_info['layer'],
                            "schema": layer_info['schema'],
                            "table": layer_info['table'],
                            "field_mappings": complete_info.get('field_mapping', {}),
                            "forced_types": complete_info.get('forced_types', {}),
                            "custom_fields": complete_info.get('custom_fields', {}),
                            "timestamp": datetime.now().isoformat(),
                            "auto_generated": False
                        }
                        detailed_mappings.append(detailed_mapping)

                # Restore original tab selection
                self.tabs.setCurrentIndex(current_tab)

            if not detailed_mappings:
                QgsMessageLog.logMessage("No column configurations to save", "Transformer", MsgWarning)
                return

            # Path to the detailed mappings file
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")

            # Load existing mappings
            existing_mappings = []
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        existing_mappings = json.load(f)
                        if not isinstance(existing_mappings, list):
                            existing_mappings = []
                except Exception:
                    existing_mappings = []

            # Update existing mappings with complete column configurations
            for new_mapping in detailed_mappings:
                layer_name = new_mapping["layer_name"]
                schema = new_mapping["schema"]
                table = new_mapping["table"]

                # Find existing mapping and update it completely
                found_index = -1
                for i, existing in enumerate(existing_mappings):
                    if (existing.get("layer_name") == layer_name and existing.get("schema") == schema and existing.get("table") == table):
                        found_index = i
                        break

                if found_index >= 0:
                    # Update existing mapping with complete details
                    existing_mappings[found_index] = new_mapping
                else:
                    # Add new complete mapping
                    existing_mappings.append(new_mapping)

            # Save updated mappings
            with open(config_path, 'w') as f:
                json.dump(existing_mappings, f, indent=2)

            saved_count = len(detailed_mappings)
            QgsMessageLog.logMessage(
                f"Column configurations saved: {saved_count} complete mapping(s) saved to postgresql_detailed_mappings.json",
                "Transformer",
                MsgSuccess
            )

        except Exception as e:
            QgsMessageLog.logMessage(f"Error saving column configurations: {str(e)}", "Transformer", MsgCritical)

    def get_complete_mapping_info(self):
        """Extrait les informations complètes de mapping depuis la boîte de dialogue

        Returns:
            dict: Dictionnaire contenant field_mapping, forced_types et custom_fields
        """
        try:
            # Obtenir le widget de l'onglet actuellement sélectionné
            current_tab_index = self.tabs.currentIndex()
            current_tab_widget = self.tabs.widget(current_tab_index)

            if not current_tab_widget:
                return {'field_mapping': {}, 'forced_types': {}, 'custom_fields': {}}

            # Chercher la table de mapping dans le widget de l'onglet
            mapping_table = None
            for child in current_tab_widget.findChildren(QTableWidget):
                if child.columnCount() >= 7:  # Notre table a 7 colonnes
                    mapping_table = child
                    break

            if not mapping_table:
                QgsMessageLog.logMessage("Table de mapping non trouvée dans l'onglet", "Transformer", MsgWarning)
                return {'field_mapping': {}, 'forced_types': {}, 'custom_fields': {}}

            field_mapping = {}
            forced_types = {}
            custom_fields = {}

            # Parcourir chaque ligne de la table
            for row in range(mapping_table.rowCount()):
                # Colonne 0: Champ source
                source_item = mapping_table.item(row, 0)
                if not source_item:
                    continue
                source_field = source_item.text().strip()

                # Colonne 2: Champ destination (ComboBox)
                dest_combo = mapping_table.cellWidget(row, 2)
                if not isinstance(dest_combo, QComboBox):
                    continue
                dest_field = dest_combo.currentData()

                # Colonne 4: Type forcé (ComboBox)
                forced_type_combo = mapping_table.cellWidget(row, 4)
                forced_type = "<Auto>"  # Valeur par défaut
                if isinstance(forced_type_combo, QComboBox):
                    forced_type = forced_type_combo.currentText().strip()

                # Seulement ajouter si il y a un mapping valide
                if source_field and dest_field:
                    field_mapping[source_field] = dest_field

                    # Ajouter le type forcé seulement s'il n'est pas "<Auto>"
                    if forced_type and forced_type != "<Auto>":
                        forced_types[source_field] = forced_type

            # Log pour debugging
            QgsMessageLog.logMessage(
                f"Extraction mapping: {len(field_mapping)} champs, {len(forced_types)} types forcés",
                "Transformer", MsgInfo
            )

            return {
                'field_mapping': field_mapping,
                'forced_types': forced_types,
                'custom_fields': custom_fields  # À implémenter plus tard si nécessaire
            }

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Erreur lors de l'extraction des informations de mapping: {str(e)}",
                "Transformer", MsgWarning
            )
            return {'field_mapping': {}, 'forced_types': {}, 'custom_fields': {}}


CONNECTIONS_FILE_NAME = "transformer_postgresql_connections.json"
LEGACY_CONFIG_FILE_NAME = "transformer_postgresql.json"


class _StatusLed(QFrame):
    """Paint-based circular LED indicator. No CSS, no emoji.

    States: 'not_tested' (gray), 'connected' (green), 'error' (orange),
    'failed' (red).
    """

    _COLORS = {
        "not_tested": QColor(120, 120, 120),
        "connected": QColor(46, 204, 113),
        "error": QColor(243, 156, 18),
        "failed": QColor(231, 76, 60),
        "testing": QColor(52, 152, 219),
    }
    _TOOLTIPS = {
        "not_tested": "Connexion non testée",
        "connected": "Connexion établie",
        "error": "Connexion à vérifier",
        "failed": "Échec de connexion",
        "testing": "Test de connexion en cours…",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._state = "not_tested"
        self.setToolTip(self._TOOLTIPS[self._state])
        self.setAccessibleName(self._TOOLTIPS[self._state])

    def set_state(self, state: str):
        if state not in self._COLORS:
            state = "not_tested"
        self._state = state
        self.setToolTip(self._TOOLTIPS[state])
        self.setAccessibleName(self._TOOLTIPS[state])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Antialiasing flag (Qt5 flat / Qt6 scoped)
        aa = getattr(QPainter, 'Antialiasing', None)
        if aa is None:
            aa = getattr(getattr(QPainter, 'RenderHint', QPainter), 'Antialiasing', None)
        if aa is not None:
            painter.setRenderHint(aa)

        color = self._COLORS[self._state]
        ring = QColor(color)
        ring.setAlpha(140)
        painter.setPen(QPen(ring, 1))
        painter.setBrush(QBrush(color))
        d = min(self.width(), self.height()) - 2
        x = (self.width() - d) // 2
        y = (self.height() - d) // 2
        painter.drawEllipse(x, y, d, d)


class PostgreSQLConfigWidget(QWidget):
    """PostgreSQL connection settings with named profiles and LED status.

    Connection profiles are stored in ``transformer_postgresql_connections.json``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_dir = os.path.dirname(os.path.abspath(__file__))
        self._connections = {}     # name -> profile dict
        self._active_name = ""
        self._loading_combo = False  # Guard combo signal during programmatic refresh
        self._active_conn_task = None
        self._pending_auto_test = False
        self.setup_ui()
        self._load_all_profiles()
        self._populate_connection_combo()
        self._apply_active_profile()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        # === Connection group ===
        conn_group = QGroupBox("Connexion PostgreSQL")
        conn_form = QFormLayout()
        conn_form.setContentsMargins(8, 8, 8, 8)
        conn_form.setVerticalSpacing(4)
        conn_form.setRowWrapPolicy(FormWrapLongRows)
        conn_form.setFieldGrowthPolicy(FormAllNonFixedFieldsGrow)

        # Profile selector row
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setSizeAdjustPolicy(ComboAdjustMinContentsIcon)
        self.profile_combo.setMinimumContentsLength(12)
        self.profile_combo.setAccessibleName("Profil de connexion PostgreSQL")
        self.profile_combo.setToolTip("Choisir un profil de connexion enregistré")
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_combo, 1)

        save_as_btn = QPushButton("Enregistrer &sous…")
        save_as_btn.setAccessibleName("Enregistrer un nouveau profil de connexion")
        save_as_btn.setToolTip("Enregistrer la connexion sous un nouveau nom")
        save_as_btn.clicked.connect(self._save_current_as_profile)
        profile_row.addWidget(save_as_btn)

        delete_btn = QPushButton("Supprimer")
        delete_btn.setAccessibleName("Supprimer le profil de connexion sélectionné")
        delete_btn.setToolTip("Supprimer ce profil enregistré ; la base est conservée.")
        delete_btn.clicked.connect(self._delete_current_profile)
        profile_row.addWidget(delete_btn)

        profile_label = QLabel("&Profil :")
        profile_label.setBuddy(self.profile_combo)
        conn_form.addRow(profile_label, profile_row)

        # Connection fields (public attributes, used by other widgets)
        self.host_edit = QLineEdit("localhost")
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(5432)
        self.database_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(PasswordEchoMode)

        for label, name, control in (
            ("&Hôte :", "Hôte PostgreSQL", self.host_edit),
            ("P&ort :", "Port PostgreSQL", self.port_edit),
            ("&Base :", "Base de données PostgreSQL", self.database_edit),
            ("&Utilisateur :", "Utilisateur PostgreSQL", self.username_edit),
            ("&Mot de passe :", "Mot de passe PostgreSQL", self.password_edit),
        ):
            control.setAccessibleName(name)
            conn_form.addRow(label, control)
        self.password_edit.setToolTip("À l'enregistrement, le secret est confié au gestionnaire d'authentification QGIS. Aucun mot de passe n'est écrit dans le fichier des profils.")
        credentials_note = QLabel("Les mots de passe enregistrés sont protégés par le gestionnaire d'authentification QGIS.")
        credentials_note.setWordWrap(True)
        conn_form.addRow(credentials_note)
        self.setTabOrder(self.profile_combo, self.host_edit)
        self.setTabOrder(self.host_edit, self.port_edit)
        self.setTabOrder(self.port_edit, self.database_edit)
        self.setTabOrder(self.database_edit, self.username_edit)
        self.setTabOrder(self.username_edit, self.password_edit)

        # Status row (LED + label)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_indicator = _StatusLed()
        self.status_label = QLabel("Connexion non testée")
        self.status_label.setAccessibleName("État de la connexion PostgreSQL")
        self.status_label.setWordWrap(True)
        font = self.status_label.font()
        font.setItalic(True)
        self.status_label.setFont(font)
        status_row.addWidget(self.status_indicator)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        conn_form.addRow("État :", status_row)

        # Action buttons row
        actions_row = QHBoxLayout()
        test_btn = QPushButton("&Tester la connexion")
        test_btn.setAccessibleName("Tester la connexion PostgreSQL")
        test_btn.clicked.connect(lambda _checked=False: self.test_connection(silent=False))
        actions_row.addWidget(test_btn)

        save_current_btn = QPushButton("&Enregistrer")
        save_current_btn.setAccessibleName("Enregistrer le profil de connexion sélectionné")
        save_current_btn.setToolTip("Enregistrer les changements du profil sélectionné")
        save_current_btn.clicked.connect(self._save_current_profile)
        actions_row.addWidget(save_current_btn)

        actions_row.addStretch()

        help_btn = QPushButton("&Aide")
        help_btn.clicked.connect(self.show_help)
        actions_row.addWidget(help_btn)

        conn_form.addRow("", actions_row)

        conn_group.setLayout(conn_form)
        outer.addWidget(conn_group)

        # Keep widget compact - mapping panel below should claim leftover space
        self.setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Maximum)

    # ------------------------------------------------------------------
    # Profile storage
    # ------------------------------------------------------------------

    def _connections_path(self):
        return os.path.join(self._config_dir, CONNECTIONS_FILE_NAME)

    def _legacy_path(self):
        return os.path.join(self._config_dir, LEGACY_CONFIG_FILE_NAME)

    def _normalize_profile(self, raw):
        return {
            "host": str(raw.get("host", "localhost")),
            "port": int(raw.get("port", 5432) or 5432),
            "database": str(raw.get("database", "")),
            "username": str(raw.get("username", "")),
            "authcfg": str(raw.get("authcfg", "")),
            "_session_password": str(raw.get("_session_password") or raw.get("password", "")),
        }

    def _current_form_as_profile(self):
        previous = self._connections.get(self._active_name, {})
        return {
            "host": self.host_edit.text(),
            "port": self.port_edit.value(),
            "database": self.database_edit.text(),
            "username": self.username_edit.text(),
            "authcfg": previous.get("authcfg", ""),
            "_session_password": self.password_edit.text(),
        }

    def _load_all_profiles(self):
        try:
            path = self._connections_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                self._connections = {
                    str(k): self._normalize_profile(v or {})
                    for k, v in (data.get("connections") or {}).items()
                }
                self._active_name = str(data.get("active") or "")

            # Migrate legacy single-config file
            legacy = self._legacy_path()
            if not self._connections and os.path.exists(legacy):
                try:
                    with open(legacy, 'r', encoding='utf-8') as f:
                        old = json.load(f) or {}
                    if old.get("host") or old.get("database"):
                        self._connections["Default"] = self._normalize_profile(old)
                        self._active_name = "Default"
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        f"Legacy PostgreSQL config migration skipped: {exc}",
                        "Transformer", MsgWarning,
                    )

            if not self._active_name and self._connections:
                self._active_name = next(iter(self._connections))
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"PostgreSQL profiles load error: {exc}",
                "Transformer", MsgWarning,
            )
            self._connections = {}
            self._active_name = ""

    def _write_all_profiles(self):
        """Persist only credential references; preserve old files on failure."""
        import tempfile

        try:
            safe_profiles = {}
            for name, profile in self._connections.items():
                authcfg = profile.get("authcfg", "")
                password = profile.get("_session_password", "")
                if password:
                    authcfg = self._protect_credentials(name, profile, password)
                    if not authcfg:
                        raise RuntimeError("Le coffre QGIS est verrouillé ou indisponible.")
                safe_profiles[name] = {
                    key: profile.get(key, default)
                    for key, default in (
                        ("host", "localhost"), ("port", 5432), ("database", ""), ("username", "")
                    )
                }
                safe_profiles[name]["authcfg"] = authcfg
            data = {"active": self._active_name, "connections": safe_profiles}
            handle, temporary = tempfile.mkstemp(
                prefix="postgresql-profiles-", suffix=".tmp", dir=self._config_dir,
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, indent=2, ensure_ascii=False)
                os.replace(temporary, self._connections_path())
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            for name, profile in safe_profiles.items():
                self._connections[name]["authcfg"] = profile["authcfg"]
            try:
                legacy = self._legacy_path()
                if legacy and os.path.exists(legacy):
                    os.unlink(legacy)
            except Exception as exc:
                log_warning(f"Purge du fichier PostgreSQL legacy ignorée : {exc}")
            pool_mgr = globals().get("PgConnectionPoolManager")
            if pool_mgr is not None:
                pool_mgr.close_all()
            return True
        except Exception:
            # A legacy plaintext file is not overwritten if its credential
            # has not first been recovered successfully into the secure store.
            log_warning(
                "Profil non enregistré : déverrouillez le gestionnaire d'authentification QGIS. "
                "Les réglages précédents sont conservés ; le mot de passe reste en mémoire."
            )
            return False

    @staticmethod
    def _auth_result(result, config):
        if isinstance(result, tuple):
            return bool(result[0]), result[1]
        return bool(result), config

    def _protect_credentials(self, name, profile, password):
        from qgis.core import QgsAuthMethodConfig

        manager = QgsApplication.authManager()
        if manager.isDisabled():
            return ""
        config = QgsAuthMethodConfig()
        authcfg = profile.get("authcfg", "")
        if authcfg:
            ok, config = self._auth_result(
                manager.loadAuthenticationConfig(authcfg, config, True), config,
            )
            if ok and config.config("username") == profile.get("username", "") and config.config("password") == password:
                return authcfg
        # A changed credential gets its own configuration so another profile
        # referencing the former authcfg cannot be altered accidentally.
        config = QgsAuthMethodConfig()
        config.setName(f"Transformer / {name}")
        config.setMethod("Basic")
        config.setConfig("username", profile.get("username", ""))
        config.setConfig("password", password)
        ok, config = self._auth_result(manager.storeAuthenticationConfig(config), config)
        return config.id() if ok else ""

    def _profile_password(self, profile):
        password = profile.get("_session_password", "")
        if password or not profile.get("authcfg"):
            return password
        from qgis.core import QgsAuthMethodConfig

        try:
            config = QgsAuthMethodConfig()
            manager = QgsApplication.authManager()
            if manager.isDisabled():
                return ""
            ok, config = self._auth_result(
                manager.loadAuthenticationConfig(profile["authcfg"], config, True), config,
            )
            return config.config("password") if ok else ""
        except Exception:
            log_warning("Déverrouillez l'authentification QGIS pour utiliser ce profil.")
            return ""

    # ------------------------------------------------------------------
    # Profile combo
    # ------------------------------------------------------------------

    def _populate_connection_combo(self):
        self._loading_combo = True
        try:
            self.profile_combo.clear()
            for name in sorted(self._connections.keys()):
                self.profile_combo.addItem(name)
            if self._active_name and self._active_name in self._connections:
                idx = self.profile_combo.findText(self._active_name)
                if idx >= 0:
                    self.profile_combo.setCurrentIndex(idx)
        finally:
            self._loading_combo = False

    def _apply_active_profile(self):
        if not self._active_name or self._active_name not in self._connections:
            return
        prof = self._connections[self._active_name]
        self.host_edit.setText(str(prof.get("host", "localhost")))
        self.port_edit.setValue(int(prof.get("port", 5432) or 5432))
        self.database_edit.setText(str(prof.get("database", "")))
        self.username_edit.setText(str(prof.get("username", "")))
        self.password_edit.setText(self._profile_password(prof))
        if self.isVisible():
            QTimer.singleShot(250, self.auto_test_connection)
        else:
            self._pending_auto_test = True

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_pending_auto_test", False):
            self._pending_auto_test = False
            QTimer.singleShot(250, self.auto_test_connection)

    def _on_profile_selected(self, name):
        if self._loading_combo or not name:
            return
        if name in self._connections:
            pool_mgr = globals().get("PgConnectionPoolManager")
            if pool_mgr is not None:
                pool_mgr.close_all()
            self._active_name = name
            self._apply_active_profile()

    def _save_current_as_profile(self):
        suggested = self._active_name or "Default"
        name, ok = QInputDialog.getText(
            self, "Enregistrer un profil de connexion",
            "Nom du profil :",
        )
        if not ok:
            return
        name = (name or "").strip() or suggested
        if not name:
            QMessageBox.warning(self, "Nom de profil requis", "Saisissez un nom pour retrouver cette connexion.")
            return
        if name in self._connections:
            reply = QMessageBox.question(
                self, "Remplacer le profil",
                f"Le profil '{name}' existe déjà. Remplacer ses paramètres de connexion ?",
                MsgBoxYes | MsgBoxNo,
            )
            if reply != MsgBoxYes:
                return
        self._connections[name] = self._current_form_as_profile()
        self._active_name = name
        if not self._write_all_profiles():
            return
        self._populate_connection_combo()
        log_info(f"Profil PostgreSQL '{name}' enregistré")

    def _save_current_profile(self):
        if not self._active_name:
            self._save_current_as_profile()
            return
        self._connections[self._active_name] = self._current_form_as_profile()
        if not self._write_all_profiles():
            return
        log_info(f"Profil PostgreSQL '{self._active_name}' mis à jour")

    def _delete_current_profile(self):
        name = self.profile_combo.currentText()
        if not name or name not in self._connections:
            return
        reply = QMessageBox.question(
            self, "Supprimer le profil",
            f"Supprimer le profil de connexion '{name}' ? Les données de la base seront conservées.",
            MsgBoxYes | MsgBoxNo,
        )
        if reply != MsgBoxYes:
            return
        previous_profile = self._connections.pop(name)
        previous_active = self._active_name
        if self._active_name == name:
            self._active_name = next(iter(self._connections), "")
        if not self._write_all_profiles():
            self._connections[name] = previous_profile
            self._active_name = previous_active
            return
        self._populate_connection_combo()
        if self._active_name:
            self._apply_active_profile()

    # ------------------------------------------------------------------
    # Status (LED)
    # ------------------------------------------------------------------

    def update_status(self, status):
        """status in {'connected','error','failed','not_tested','testing'}"""
        labels = {
            "connected": "Connexion établie",
            "error": "Connexion à vérifier",
            "failed": "Échec de connexion : vérifiez les paramètres puis relancez le test.",
            "not_tested": "Connexion non testée",
            "testing": "Test en cours…",
        }
        self.status_indicator.set_state(status)
        self.status_label.setText(labels.get(status, ""))

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self, silent=False):
        """Launch non-blocking connection test via QgsTask.

        Returns None immediately. The result is delivered via
        ``_on_connection_tested`` on the main thread.
        """
        if not POSTGRESQL_AVAILABLE:
            if not silent:
                log_warning("Le pilote PostgreSQL psycopg2 est absent. Installez les dépendances du plugin puis réessayez.")
            self.update_status("failed")
            return

        host = self.host_edit.text()
        port = self.port_edit.value()
        database = self.database_edit.text()
        username = self.username_edit.text()
        password = self.password_edit.text()

        if not all([host, database, username, password]):
            if not silent:
                log_warning("Complétez l'hôte, la base, l'utilisateur et le mot de passe, puis relancez le test.")
            self.update_status("not_tested")
            return

        conn_params = {
            'host': host,
            'port': port,
            'database': database,
            'user': username,
            'password': password,
        }

        self.update_status("testing")
        log_info(
            f"test_connection: launching background task "
            f"host={host} port={port} db={database} user={username}"
        )

        if self._active_conn_task:
            self._active_conn_task.cancel()
        task = PgConnectionTask(
            conn_params,
            description=f"Test PostgreSQL {database}@{host}:{port}",
        )
        self._active_conn_task = task
        task.taskCompleted.connect(
            lambda: self._on_connection_tested(task, silent, host, port, database, username)
        )
        task.taskTerminated.connect(
            lambda: self._on_connection_tested(task, silent, host, port, database, username)
        )
        QgsApplication.taskManager().addTask(task)

    def _on_connection_tested(self, task, silent, host, port, database, username):
        """Main-thread callback when PgConnectionTask finishes."""
        if self._active_conn_task is not task:
            return
        self._active_conn_task = None
        if task.isCanceled():
            return
        if task.success:
            self.update_status("connected")
            if not silent:
                log_success(
                    f"Connexion PostgreSQL établie : {database}@{host}:{port} "
                    f"(utilisateur : {username}) durée_ms={task.elapsed_ms}"
                )
            self.trigger_schema_refresh()
        else:
            self.update_status("failed")
            if not silent:
                log_critical(
                    f"Échec de connexion PostgreSQL : {task.message}. "
                    f"Vérifiez les paramètres, l'accès réseau et l'authentification QGIS, puis relancez le test. durée_ms={task.elapsed_ms}"
                )

    def trigger_schema_refresh(self):
        try:
            parent_widget = self.parent()
            if hasattr(parent_widget, 'mapping_widget'):
                QTimer.singleShot(1000, parent_widget.mapping_widget.refresh_schemas)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Schema refresh trigger skipped: {exc}",
                "Transformer", MsgInfo,
            )

    def show_help(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Aide à la publication PostgreSQL")
        msg.setIcon(MsgBoxIconInfo)
        help_text = """Connexion et publication PostgreSQL

Enregistrez un profil nommé puis testez la connexion. Les mots de passe enregistrés sont confiés au gestionnaire d'authentification QGIS ; déverrouillez-le si nécessaire.

Ajoutez une destination : couche source, schéma et table. Les noms du schéma, de la table et des champs restent ceux de vos données. Une nouvelle table est seulement proposée à cette étape.

« Analyser et publier » vérifie les destinations sans modifier la base. Le dialogue suivant permet de corriger les correspondances, de choisir l'ajout ou le remplacement, puis de confirmer la publication.

L'ajout conserve les lignes existantes ; un rejeu peut créer des doublons. Le remplacement supprime toutes les lignes de la table avant de les réinsérer. Chaque table est validée séparément ; les tables déjà validées restent publiées si une autre échoue.

En cas d'échec, corrigez la cause et consultez le bilan avant de relancer. Annuler le dialogue de confirmation ne modifie aucune table.
"""
        msg.setText(help_text)
        msg.setTextFormat(PlainText)
        msg.setStandardButtons(MsgBoxOk)
        msg.resize(500, 400)
        msg.exec()

    # ------------------------------------------------------------------
    # Backward-compatible API (callers in older code)
    # ------------------------------------------------------------------

    def auto_load_config(self):
        self._apply_active_profile()

    def auto_test_connection(self):
        try:
            if all([
                self.host_edit.text().strip(),
                self.database_edit.text().strip(),
                self.username_edit.text().strip(),
                self.password_edit.text(),
            ]):
                self.test_connection(silent=True)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Auto-test connection skipped: {exc}",
                "Transformer", MsgInfo,
            )

    def save_config(self):
        self._save_current_profile()

    def load_config(self):
        self._apply_active_profile()


class PostgreSQLMappingWidget(QWidget):
    """Widget pour le mapping des couches vers PostgreSQL"""

    publication_finished = pyqtSignal(dict)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == EventFontChange and hasattr(self, 'mapping_table'):
            self.mapping_table.verticalHeader().setDefaultSectionSize(max(32, self.fontMetrics().height() + 16))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_widget = None
        self.available_schemas = []
        self.available_tables = {}
        self.auto_connect = True  # Enable auto-connect functionality
        self._active_conn_task = None
        self._active_schema_task = None
        self._active_table_task = None
        self._active_export_task = None
        self._active_compat_task = None
        self._compat_generation = 0
        self._layers_dirty = False
        self.setup_ui()
        self.setup_qgis_signals()

        # Essayer de charger automatiquement les mappings existants au démarrage
        self.auto_load_existing_mappings()

    def setup_ui(self):
        """Setup native QGIS mapping interface"""
        layout = QVBoxLayout(self)

        # Title with native QGIS font
        title = QLabel("Destinations PostgreSQL")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        instruction = QLabel("Associez chaque couche à un schéma et une table. L'analyse suivante sera en lecture seule ; vous confirmerez les colonnes et le mode avant publication.")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        # Toolbar
        toolbar_layout = QHBoxLayout()

        # Add mapping button
        add_btn = QPushButton("&Ajouter une destination")
        add_btn.setAccessibleName("Ajouter une destination PostgreSQL")
        add_btn.clicked.connect(self.add_mapping)
        toolbar_layout.addWidget(add_btn)

        # Remove mapping button
        remove_btn = QPushButton("&Retirer la sélection")
        remove_btn.setAccessibleName("Retirer la destination sélectionnée")
        remove_btn.clicked.connect(self.remove_selected)
        toolbar_layout.addWidget(remove_btn)

        # Refresh schemas button
        refresh_btn = QPushButton("Actualiser les &schémas")
        refresh_btn.setAccessibleName("Actualiser les schémas PostgreSQL")
        refresh_btn.clicked.connect(self.refresh_schemas)
        toolbar_layout.addWidget(refresh_btn)

        # Add separator
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)
        delivery_layout = QHBoxLayout()

        # Save Mapping button
        save_mapping_btn = QPushButton("&Enregistrer les destinations")
        save_mapping_btn.setAccessibleName("Enregistrer les destinations PostgreSQL")
        save_mapping_btn.clicked.connect(self.save_mappings)
        delivery_layout.addWidget(save_mapping_btn)

        # Load Mapping button
        load_mapping_btn = QPushButton("&Charger les destinations")
        load_mapping_btn.setAccessibleName("Charger des destinations PostgreSQL enregistrées")
        load_mapping_btn.clicked.connect(self.load_mappings)
        delivery_layout.addWidget(load_mapping_btn)
        delivery_layout.addStretch()

        # Export PostgreSQL button
        export_btn = QPushButton("&Analyser et publier…")
        export_btn.setAccessibleName("Analyser les destinations avant de confirmer la publication PostgreSQL")
        export_btn.setToolTip("Analyser sans écriture, puis ouvrir la confirmation du plan de publication.")
        export_btn.clicked.connect(self.export_to_postgresql)
        delivery_layout.addWidget(export_btn)

        layout.addLayout(delivery_layout)

        # Mapping table
        self.mapping_table = QTableWidget()
        self.mapping_table.setAccessibleName("Couches sources et destinations PostgreSQL")
        self.mapping_table.setColumnCount(3)
        self.mapping_table.setHorizontalHeaderLabels(["Couche QGIS", "Schéma", "Table"])
        self.mapping_table.setSelectionBehavior(SelectRows)
        self.mapping_table.verticalHeader().setDefaultSectionSize(max(32, self.fontMetrics().height() + 16))
        self.mapping_table.setMinimumHeight(self.fontMetrics().height() * 8)

        # Set column widths
        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(HeaderStretch)
        header.setStretchLastSection(True)

        layout.addWidget(self.mapping_table)

    def setup_qgis_signals(self):
        """Setup QGIS project layer signals for auto-update"""
        try:
            project = QgsProject.instance()
            project.layersAdded.connect(self.on_layers_added)
            project.layersRemoved.connect(self.on_layers_removed)
            project.layerWillBeRemoved.connect(self.on_layer_will_be_removed)
            log_info("PostgreSQL widget connected to QGIS project signals")
        except Exception as e:
            log_error(f"Error connecting PostgreSQL widget to QGIS signals: {str(e)}")

    def teardown_qgis_signals(self):
        """Disconnect QGIS project signals before widget destruction."""
        try:
            project = QgsProject.instance()
            for name, slot in (
                ("layersAdded", self.on_layers_added),
                ("layersRemoved", self.on_layers_removed),
                ("layerWillBeRemoved", self.on_layer_will_be_removed),
            ):
                try:
                    getattr(project, name).disconnect(slot)
                except (TypeError, RuntimeError, AttributeError):
                    pass
        except (RuntimeError, AttributeError):
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_layers_dirty", False):
            self._layers_dirty = False
            self.refresh_layer_lists()

    def on_layers_added(self, layers):
        """Handle when new layers are added to QGIS project"""
        vector_layers = [layer for layer in layers if isinstance(layer, QgsVectorLayer) and layer.isValid()]
        if vector_layers:
            if not self.isVisible():
                self._layers_dirty = True
                return
            self.refresh_layer_lists()

    def on_layers_removed(self, layer_ids):
        """Handle when layers are removed from QGIS project"""
        if layer_ids:
            if not self.isVisible():
                self._layers_dirty = True
                return
            self.refresh_layer_lists()

    def on_layer_will_be_removed(self, layer_id):
        """Handle when a layer is about to be removed"""
        # Check if any of our mappings reference this layer
        for row in range(self.mapping_table.rowCount()):
            layer_combo = self.mapping_table.cellWidget(row, 0)
            if isinstance(layer_combo, QComboBox):
                current_text = layer_combo.currentText()
                project = QgsProject.instance()
                for layer in project.mapLayers().values():
                    if hasattr(layer, 'name') and layer.name() == current_text and layer.id() == layer_id:
                        log_warning(f"PostgreSQL mapping: Layer '{current_text}' is being removed from mapping row {row + 1}")
                        break

    def refresh_layer_lists(self):
        """Refresh layer lists in all combo boxes"""
        try:
            # Get current layers
            layer_names = [""]
            project = QgsProject.instance()
            if project:
                layers = [layer for layer in project.mapLayers().values() if isinstance(layer, QgsVectorLayer) and layer.isValid()]
                for layer in layers:
                    if hasattr(layer, 'name') and layer.name():
                        layer_names.append(layer.name())

            # Update all layer combo boxes
            for row in range(self.mapping_table.rowCount()):
                layer_combo = self.mapping_table.cellWidget(row, 0)
                if isinstance(layer_combo, QComboBox):
                    current_selection = layer_combo.currentText()
                    layer_combo.clear()
                    layer_combo.addItems(layer_names)

                    # Restore selection if still valid
                    if current_selection in layer_names:
                        layer_combo.setCurrentText(current_selection)

        except Exception as e:
            log_error(f"Error refreshing PostgreSQL layer lists: {str(e)}")

    def add_mapping(self):
        """Ajoute une nouvelle ligne de mapping"""
        try:
            row = self.mapping_table.rowCount()
            self.mapping_table.insertRow(row)

            # Obtenir les couches du projet
            layer_names = [""]
            project = QgsProject.instance()
            if project:
                layers = [layer for layer in project.mapLayers().values() if hasattr(layer, 'name')]
                for layer in layers:
                    if hasattr(layer, 'name') and layer.name():
                        layer_names.append(layer.name())

            layer_combo = QComboBox()
            layer_combo.setAccessibleName(f"Couche source de la destination {row + 1}")
            layer_combo.addItems(layer_names)
            self.mapping_table.setCellWidget(row, 0, layer_combo)

            # Colonne 1: ComboBox avec les schémas PostgreSQL
            schema_combo = QComboBox()
            schema_combo.setAccessibleName(f"Schéma de la destination {row + 1}")
            schema_combo.setEditable(True)

            # Charger les schémas si possible
            if not self.available_schemas and self.config_widget:
                try:
                    self.refresh_schemas()
                except Exception as exc:
                    log_warning(f"add_mapping: schema refresh failed: {exc}")

            # Remplir la combobox des schémas
            schema_items = [""]
            if self.available_schemas:
                schema_items.extend(self.available_schemas)
            else:
                schema_items.append("public")

            schema_combo.addItems(schema_items)
            self.mapping_table.setCellWidget(row, 1, schema_combo)

            # Colonne 2: ComboBox avec les tables (avec option de création)
            table_combo = QComboBox()
            table_combo.setAccessibleName(f"Table de la destination {row + 1}")
            table_combo.setEditable(True)
            table_combo.addItems(["", "+ Nouvelle table..."])
            self.mapping_table.setCellWidget(row, 2, table_combo)

            # Connecter les signaux
            # 1. Signal de changement de schéma pour mettre à jour les tables
            schema_combo.currentTextChanged.connect(lambda text, r=row: self.update_table_combo_simple(r, text))
            # 2. Signal de création de nouvelle table
            table_combo.currentTextChanged.connect(lambda text, r=row: self.handle_table_selection(r, text))

            QgsMessageLog.logMessage(f"Nouveau mapping ajouté à la ligne {row}", "Transformer", MsgInfo)

        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur lors de l'ajout du mapping: {str(e)}", "Transformer", MsgCritical)
            QMessageBox.critical(self, "Destination non ajoutée", f"Impossible d'ajouter la destination :\n{str(e)}\nRéessayez après avoir vérifié la couche source.")

    def remove_selected(self):
        """Supprime le mapping sélectionné"""
        current_row = self.mapping_table.currentRow()
        if current_row >= 0:
            self.mapping_table.removeRow(current_row)

    def _insert_saved_destination(self, layer_name, schema, table):
        """Restaurer une destination utilisable avec ses identifiants littéraux."""
        row = self.mapping_table.rowCount()
        self.mapping_table.insertRow(row)
        layer_names = [layer.name() for layer in QgsProject.instance().mapLayers().values()]
        values = (
            ("Couche source", list(dict.fromkeys([layer_name] + layer_names)), layer_name),
            ("Schéma", list(dict.fromkeys([schema] + list(self.available_schemas or []))), schema),
            ("Table", list(dict.fromkeys([table] + list(self.available_tables.get(schema, [])) + ["+ Nouvelle table..."])), table),
        )
        for column, (label, choices, selected) in enumerate(values):
            combo = QComboBox()
            combo.setEditable(column > 0)
            combo.setAccessibleName(f"{label} de la destination {row + 1}")
            combo.addItems(choices)
            combo.setCurrentText(selected)
            self.mapping_table.setCellWidget(row, column, combo)
        self.mapping_table.cellWidget(row, 1).currentTextChanged.connect(
            lambda text, r=row: self.update_table_combo_simple(r, text)
        )
        self.mapping_table.cellWidget(row, 2).currentTextChanged.connect(
            lambda text, r=row: self.handle_table_selection(r, text)
        )
        return row

    def handle_table_selection(self, row, text):
        """Gère la sélection de table, incluant la création de nouvelles tables"""
        try:
            if text == "+ Nouvelle table...":
                table_name, ok = QInputDialog.getText(
                    self,
                    "Nouvelle table",
                    "Nom de la nouvelle table:",
                    text=""
                )

                if ok and table_name.strip():
                    table_name = table_name.strip()

                    # Mettre à jour la combobox avec le nom de la nouvelle table
                    table_combo = self.mapping_table.cellWidget(row, 2)
                    if table_combo:
                        # Sauvegarder l'état actuel
                        current_items = [table_combo.itemText(i) for i in range(table_combo.count())]

                        # Ajouter la nouvelle table si elle n'existe pas
                        if table_name not in current_items:
                            table_combo.insertItem(table_combo.count() - 1, table_name)  # Insérer avant "+ Nouvelle table..."

                        # Sélectionner la nouvelle table
                        table_combo.setCurrentText(table_name)

                        QgsMessageLog.logMessage(f"Nouvelle table '{table_name}' ajoutée au mapping ligne {row}", "Transformer", MsgInfo)
                else:
                    # Annuler - remettre à vide
                    table_combo = self.mapping_table.cellWidget(row, 2)
                    if table_combo:
                        table_combo.setCurrentIndex(0)  # Remettre à l'index vide
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in handle_table_selection: {str(e)}", "Transformer", MsgWarning)

    def update_table_combo_simple(self, row, schema_name):
        """Met à jour les tables disponibles selon le schéma sélectionné"""
        try:
            table_combo = self.mapping_table.cellWidget(row, 2)
            if not table_combo or not schema_name:
                return

            # If tables for this schema are already available, use them
            if schema_name in self.available_tables:
                current_text = table_combo.currentText()
                table_combo.clear()
                table_combo.addItem("")  # Option vide

                # Ajouter toutes les tables existantes
                for table in self.available_tables[schema_name]:
                    table_combo.addItem(table)

                # Ajouter l'option pour nouvelle table à la fin
                table_combo.addItem("+ Nouvelle table...")

                # Restaurer la sélection si possible
                if current_text in self.available_tables[schema_name] or current_text == "":
                    table_combo.setCurrentText(current_text)
                elif current_text == "+ Nouvelle table...":
                    table_combo.setCurrentText("+ Nouvelle table...")

                log_success(f"Tables chargées pour schéma '{schema_name}': {len(self.available_tables[schema_name])} tables disponibles")
            else:
                # Chargement automatique des tables pour ce schéma
                log_info(f"Chargement automatique des tables pour le schéma '{schema_name}'...")
                self.load_tables_for_schema(schema_name, table_combo)

        except Exception as e:
            log_critical(f"Erreur mise à jour combo tables: {str(e)}")

    def refresh_schemas(self):
        """Launch non-blocking schema discovery via QgsTask.

        UI remains responsive. Results are applied in
        ``_on_schemas_discovered`` on the main thread.
        """
        if not POSTGRESQL_AVAILABLE:
            log_warning("Le pilote PostgreSQL psycopg2 est absent. Installez les dépendances du plugin puis réessayez.")
            return

        if not self.config_widget:
            log_warning("Renseignez la connexion PostgreSQL avant de charger les schémas.")
            return

        conn_params = {
            'host': self.config_widget.host_edit.text() or 'localhost',
            'port': self.config_widget.port_edit.value(),
            'database': self.config_widget.database_edit.text(),
            'user': self.config_widget.username_edit.text(),
            'password': self.config_widget.password_edit.text(),
        }

        if not conn_params['database']:
            log_warning("Saisissez le nom de la base puis actualisez les schémas.")
            return
        if not conn_params['user']:
            log_warning("Saisissez l'utilisateur PostgreSQL puis actualisez les schémas.")
            return

        log_info(
            f"refresh_schemas: launching background task "
            f"host={conn_params['host']} db={conn_params['database']}"
        )

        if self._active_schema_task:
            self._active_schema_task.cancel()
        task = PgSchemaTask(
            conn_params,
            fetch_tables_for=None,
            description=f"PG schema discovery {conn_params['database']}@{conn_params['host']}",
        )
        self._active_schema_task = task
        task.taskCompleted.connect(lambda: self._on_schemas_discovered(task, conn_params))
        task.taskTerminated.connect(lambda: self._on_schemas_discovered(task, conn_params))
        QgsApplication.taskManager().addTask(task)

    def _on_schemas_discovered(self, task, conn_params):
        """Main-thread callback when PgSchemaTask finishes."""
        if self._active_schema_task is not task:
            return
        context_current = not task.isCanceled() and self._discovery_context_matches(task)
        self._active_schema_task = None
        if not context_current:
            return
        if task.error:
            log_critical(f"Schémas indisponibles : {task.error}. Vérifiez la connexion puis actualisez les schémas.")
            return

        self.available_schemas = task.schemas
        self.available_tables = task.tables_by_schema

        schemas_info = (
            f"Connexion à {conn_params['database']}@{conn_params['host']} : "
            f"{len(task.schemas)} schéma(s) chargé(s)"
        )
        if 'public' in task.schemas:
            tables_count = len(task.tables_by_schema.get('public', []))
            schemas_info += f" (public: {tables_count} tables)"
        log_success(f"{schemas_info} elapsed_ms={task.elapsed_ms}")

        self.update_all_schema_combos()
        self.auto_load_existing_mappings()

        try:
            parent_dialog = self.parent()
            while parent_dialog and not hasattr(parent_dialog, 'update_statistics'):
                parent_dialog = parent_dialog.parent()
            if parent_dialog and hasattr(parent_dialog, 'update_statistics'):
                parent_dialog.update_statistics()
        except Exception as exc:
            log_warning(f"update_statistics trigger failed: {exc}")

    def auto_load_existing_mappings(self):
        """Charge automatiquement les mappings pour les layers existants dans QGIS"""
        try:
            # Path to the detailed mappings file
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")

            if not os.path.exists(config_path):
                return

            # Load all mappings
            with open(config_path, 'r') as f:
                all_mappings = json.load(f)

            if not all_mappings:
                return

            # Get current QGIS project layers
            project = QgsProject.instance()
            layer_names = [layer.name() for layer in project.mapLayers().values()]

            loaded_count = 0
            for mapping in all_mappings:
                layer_name = mapping.get("layer_name", "")
                schema = mapping.get("schema", "")
                table = mapping.get("table", "")

                # Check if this layer exists in QGIS and is not already mapped
                if layer_name in layer_names:
                    # Check if mapping already exists in table
                    already_mapped = False
                    for row in range(self.mapping_table.rowCount()):
                        layer_widget = self.mapping_table.cellWidget(row, 0)
                        if layer_widget and hasattr(layer_widget, 'currentText'):
                            if layer_widget.currentText() == layer_name:
                                already_mapped = True
                                break

                    if not already_mapped:
                        # Add this mapping to the table
                        row = self.mapping_table.rowCount()
                        self.mapping_table.insertRow(row)

                        # Layer combo
                        layer_combo = QComboBox()
                        layer_combo.setAccessibleName(f"Couche source de la destination {row + 1}")
                        layer_combo.setEditable(True)
                        layer_combo.addItem("")
                        layer_combo.addItems(layer_names)
                        layer_combo.setCurrentText(layer_name)
                        self.mapping_table.setCellWidget(row, 0, layer_combo)

                        # Schema combo
                        schema_combo = QComboBox()
                        schema_combo.setAccessibleName(f"Schéma de la destination {row + 1}")
                        schema_combo.setEditable(True)
                        schema_combo.addItem("")
                        if self.available_schemas:
                            schema_combo.addItems(self.available_schemas)
                        schema_combo.setCurrentText(schema)
                        schema_combo.currentTextChanged.connect(
                            lambda text, r=row: self.update_table_combo_simple(r, text)
                        )
                        self.mapping_table.setCellWidget(row, 1, schema_combo)

                        # Table combo
                        table_combo = QComboBox()
                        table_combo.setAccessibleName(f"Table de la destination {row + 1}")
                        table_combo.setEditable(True)
                        table_combo.addItem("")

                        # Load tables for this schema if necessary
                        # Pass target_combo so the async callback can populate it
                        if schema and schema not in self.available_tables:
                            self.load_tables_for_schema(schema, table_combo)

                        # Add available tables (if already cached from a previous load)
                        if schema in self.available_tables:
                            table_combo.addItems(self.available_tables[schema])

                        table_combo.setCurrentText(table)
                        self.mapping_table.setCellWidget(row, 2, table_combo)

                        loaded_count += 1

            if loaded_count > 0:
                QgsMessageLog.logMessage(
                    f"Auto-loaded {loaded_count} existing mapping(s) for layers in current project",
                    "Transformer",
                    MsgSuccess
                )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error auto-loading existing mappings: {str(e)}",
                "Transformer",
                MsgWarning
            )

    def update_all_schema_combos(self):
        """Update all schema ComboBoxes in table w/ complete schema list"""
        if not self.available_schemas:
            return

        try:
            # Browse all table rows
            for row in range(self.mapping_table.rowCount()):
                # Get schema ComboBox for this row
                schema_combo = self.mapping_table.cellWidget(row, 1)
                if not schema_combo:
                    continue

                # Save current selection
                current_schema = schema_combo.currentText()

                # Update ComboBox with available schemas
                schema_combo.clear()
                schema_combo.addItems(self.available_schemas)

                # Update completion model if present
                completer = schema_combo.completer()
                if completer is not None:
                    model = QStringListModel(self.available_schemas, completer)
                    completer.setModel(model)

                # Restaurer la sélection précédente si possible
                if current_schema and current_schema in self.available_schemas:
                    schema_combo.setCurrentText(current_schema)
                elif "public" in self.available_schemas:
                    # Select 'public' by default
                    schema_combo.setCurrentText("public")

            QgsMessageLog.logMessage(
                f"All schema ComboBoxes updated with {len(self.available_schemas)} schemas",
                "Transformer",
                MsgInfo
            )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating schema ComboBoxes: {str(e)}",
                "Transformer",
                MsgWarning
            )

    def load_tables_for_schema(self, schema_name, target_combo=None):
        """Launch non-blocking table discovery for a schema via QgsTask.

        UI remains responsive. Results are applied in
        ``_on_tables_discovered`` on the main thread.

        Args:
            schema_name: PostgreSQL schema name
            target_combo: QComboBox to update (optional, stored for callback)
        """
        if not POSTGRESQL_AVAILABLE:
            log_warning("Le pilote PostgreSQL psycopg2 est absent. Installez les dépendances du plugin puis réessayez.")
            return

        if not self.config_widget:
            log_warning("Renseignez la connexion PostgreSQL avant de charger les tables.")
            return

        if not schema_name:
            log_warning("Choisissez un schéma avant de charger ses tables.")
            return

        conn_params = {
            'host': self.config_widget.host_edit.text() or 'localhost',
            'port': self.config_widget.port_edit.value(),
            'database': self.config_widget.database_edit.text(),
            'user': self.config_widget.username_edit.text(),
            'password': self.config_widget.password_edit.text(),
        }

        if not conn_params['database'] or not conn_params['user']:
            return

        log_info(
            f"load_tables_for_schema: launching background task "
            f"schema={schema_name} db={conn_params['database']}"
        )

        if self._active_table_task:
            self._active_table_task.cancel()
        task = PgSchemaTask(
            conn_params,
            fetch_tables_for=schema_name,
            description=f"PG tables for {schema_name} @ {conn_params['database']}",
        )
        self._active_table_task = task
        task.taskCompleted.connect(
            lambda: self._on_tables_discovered(task, schema_name, target_combo)
        )
        task.taskTerminated.connect(
            lambda: self._on_tables_discovered(task, schema_name, target_combo)
        )
        QgsApplication.taskManager().addTask(task)

    def _on_tables_discovered(self, task, schema_name, target_combo):
        """Main-thread callback when PgSchemaTask (tables) finishes."""
        if self._active_table_task is not task:
            return
        context_current = (
            not task.isCanceled()
            and self._discovery_context_matches(task)
            and self._table_target_current(schema_name, target_combo)
        )
        self._active_table_task = None
        if not context_current:
            return
        if task.error:
            log_critical(f"Tables du schéma '{schema_name}' indisponibles : {task.error}. Vérifiez la connexion puis actualisez les schémas.")
            return

        tables = task.tables_by_schema.get(schema_name, [])
        self.available_tables[schema_name] = tables

        if target_combo:
            current_text = target_combo.currentText()
            target_combo.clear()
            target_combo.addItem("")
            for table in tables:
                target_combo.addItem(table)
            target_combo.addItem("+ Nouvelle table...")
            if current_text in tables or current_text == "":
                target_combo.setCurrentText(current_text)
            elif current_text == "+ Nouvelle table...":
                target_combo.setCurrentText("+ Nouvelle table...")
            else:
                target_combo.setCurrentText(current_text)

        log_info(
            f"Tables loaded for schema '{schema_name}': "
            f"{len(tables)} tables/views elapsed_ms={task.elapsed_ms}"
        )

    def _discovery_context_matches(self, task):
        """Comparer la connexion courante sans exposer ni persister son secret."""
        if self.config_widget is None:
            return False
        current = self._build_conn_params()
        requested = getattr(task, 'conn_params', {})
        return all(current[key] == requested.get(key)
                   for key in ('host', 'port', 'database', 'user', 'password'))

    def _table_target_current(self, schema_name, target_combo):
        """Un résultat tardif ne doit pas repeupler une autre destination."""
        if target_combo is None:
            return True
        for row in range(self.mapping_table.rowCount()):
            if self.mapping_table.cellWidget(row, 2) is target_combo:
                schema_combo = self.mapping_table.cellWidget(row, 1)
                return bool(schema_combo and schema_combo.currentText() == schema_name)
        return False

    def handle_table_creation(self, table_name):
        """Gère la création d'une nouvelle table dans PostgreSQL"""
        try:
            # Récupérer le schéma courant
            current_row = self.mapping_table.currentRow()
            schema = 'public'  # défaut

            if current_row >= 0:
                schema_combo = self.mapping_table.cellWidget(current_row, 1)
                if schema_combo and schema_combo.currentText().strip():
                    schema = schema_combo.currentText().strip()

            # Récupérer la couche source pour analyser sa structure
            layer_combo = self.mapping_table.cellWidget(current_row, 0)
            if not layer_combo:
                QgsMessageLog.logMessage("Aucune couche source sélectionnée", "Transformer", MsgWarning)
                return

            layer_name = layer_combo.currentText().strip()
            if not layer_name:
                QgsMessageLog.logMessage("Nom de couche vide", "Transformer", MsgWarning)
                return

            # Traitement de la création de table pour la couche sélectionnée
            QgsMessageLog.logMessage(f"Création de table '{table_name}' pour la couche '{layer_name}' dans le schéma '{schema}'", "Transformer", MsgInfo)

            # Log du résultat
            QgsMessageLog.logMessage(f"Table creation handled for {table_name}", "Transformer", MsgInfo)

        except Exception as e:
            QMessageBox.critical(self, "Association impossible", f"L'association automatique a échoué : {str(e)}. Choisissez la couche et la destination manuellement.")

    def get_current_mappings(self):
        """Récupère les mappings actuels depuis les ComboBox"""
        mappings = []
        row_count = self.mapping_table.rowCount()

        for row in range(row_count):
            # Récupérer les valeurs des ComboBox
            layer_combo = self.mapping_table.cellWidget(row, 0)
            schema_combo = self.mapping_table.cellWidget(row, 1)
            table_combo = self.mapping_table.cellWidget(row, 2)

            if (isinstance(layer_combo, QComboBox) and isinstance(schema_combo, QComboBox) and isinstance(table_combo, QComboBox)):

                transformed = layer_combo.currentText().strip()
                schema = schema_combo.currentText().strip()
                table = table_combo.currentText().strip()

                # Vérifier que toutes les valeurs sont renseignées (et exclure les valeurs spéciales)
                if (transformed and schema and table and table != "+ Nouvelle table..." and transformed != "" and schema != ""):
                    mapping = {
                        "transformed": transformed,
                        "schema": schema,
                        "table": table
                    }
                    mappings.append(mapping)

        return mappings

    def _dispatch_async_export(self, compatibility_info, conn_params, export_mode):
        """Build PgExportTask jobs on main thread and launch in background.

        Returns True if task was launched, False if no eligible jobs.
        """
        if self._active_export_task is not None:
            log_warning("Une publication est déjà en cours ; ce plan n'est pas lancé.")
            return False
        from qgis.core import QgsVectorLayer

        params = dict(conn_params)
        params.setdefault("connect_timeout", 10)

        jobs = []
        for info in compatibility_info:
            layer_name = info["layer"]
            schema = info["schema"]
            table = info["table"]

            # Prefer the identity analyzed earlier; names alone may be ambiguous.
            source_layer = self._resolve_export_layer(info)
            if not source_layer or not isinstance(source_layer, QgsVectorLayer):
                log_warning(f"Couche '{layer_name}' introuvable. Rétablissez la source puis relancez l'analyse.")
                continue

            jobs.append({
                "schema": schema,
                "table": table,
                "layer": source_layer,
                "srid": source_layer.crs().postgisSrid(),
                "target_srid": info.get("target_srid"),
                "geometry_column": info.get("geometry_column"),
                "field_mapping": info.get("field_mapping"),
                "allow_create": bool(info.get("allow_create")),
                "layer_name": layer_name,
            })

        if not jobs:
            return False

        # Build and launch task
        task = PgExportTask(
            params,
            jobs,
            export_mode=export_mode,
            description=f"Publication PostgreSQL ({len(jobs)} table(s), mode={export_mode})",
        )

        # Track active task to prevent garbage collection
        self._active_export_task = task

        # Connect signals for progress feedback
        task.progressChanged.connect(
            lambda p: log_info(f"Publication PostgreSQL : {int(p)} %")
        )
        task.taskCompleted.connect(lambda: self._on_export_finished(task))
        task.taskTerminated.connect(lambda: self._on_export_finished(task))

        log_info(f"Publication de {len(jobs)} table(s) en arrière-plan")
        QgsApplication.taskManager().addTask(task)
        return True

    def _on_export_finished(self, task):
        """Display only committed rows and preserve the cancellation state."""
        if getattr(task, "_publication_receipt_emitted", False):
            return
        task._publication_receipt_emitted = True
        if getattr(self, "_active_export_task", None) is task:
            self._active_export_task = None
        status = getattr(task, "status", "failed")
        if status == "cancelled":
            log_warning(
                f"Publication annulée : {task.total_inserted} écriture(s) déjà validée(s) "
                "dans les tables précédentes ; la table en cours a été annulée."
            )
        elif status == "success":
            log_success(
                f"Publication terminée : {task.success_count} table(s), "
                f"{task.total_inserted} écriture(s) validée(s)."
            )
        elif status == "partial":
            log_warning(
                f"Publication partielle : {task.success_count} table(s) validée(s), "
                f"{task.fail_count} échec(s). Consultez le bilan."
            )
        else:
            log_critical("Publication échouée : aucune réussite n'est annoncée.")
        for error in task.errors[:10]:
            log_critical(error)
        self.publication_finished.emit({
            **getattr(task, "result_summary", {}),
            "kind": "postgresql", "status": status,
            "plan": [
                {"schema": job["schema"], "table": job["table"], "layer": job.get("layer_name", "")}
                for job in task.jobs
            ],
        })

    def _dispatch_update_export(self, compatibility_info, conn_params, update_config):
        """Dispatch update (UPSERT) export via PgExportTask in background.

        Resolves source layers on main thread, builds jobs with update_config
        attached, and launches PgExportTask with export_mode='update'.
        """
        if self._active_export_task is not None:
            log_warning("Une publication est déjà en cours ; ce plan n'est pas lancé.")
            return False
        from qgis.core import QgsVectorLayer

        params = dict(conn_params)
        params.setdefault("connect_timeout", 10)

        jobs = []
        for info in compatibility_info:
            layer_name = info.get("layer", "")
            schema = info.get("schema", "")
            table = info.get("table", "")

            source_layer = self._resolve_export_layer(info)
            if not source_layer or not isinstance(source_layer, QgsVectorLayer):
                log_warning(f"Update export: layer '{layer_name}' not resolvable, skipping")
                continue

            jobs.append({
                "schema": schema,
                "table": table,
                "layer": source_layer,
                "srid": source_layer.crs().postgisSrid(),
                "update_config": update_config,
                "layer_name": layer_name,
                "target_srid": info.get("target_srid"),
                "geometry_column": info.get("geometry_column"),
                "field_mapping": info.get("field_mapping"),
                "allow_create": bool(info.get("allow_create")),
            })

        if not jobs:
            log_warning("Update export: no eligible jobs")
            return

        task = PgExportTask(
            params,
            jobs,
            export_mode="update",
            description=f"PostgreSQL UPSERT ({len(jobs)} table(s))",
        )
        self._active_export_task = task
        task.progressChanged.connect(
            lambda p: log_info(f"Update export progress: {int(p)}%")
        )
        task.taskCompleted.connect(lambda: self._on_export_finished(task))
        task.taskTerminated.connect(lambda: self._on_export_finished(task))

        log_info(f"Launching async UPSERT of {len(jobs)} table(s)")
        QgsApplication.taskManager().addTask(task)

    def export_to_postgresql(self):
        """Export vers PostgreSQL - async compatibility analysis via QgsTask.

        Launches PgCompatibilityTask in background. The confirmation dialog
        and export dispatch happen in _on_export_compatibility_analyzed (main thread).
        """
        try:
            mappings = self.get_current_mappings()

            if not mappings:
                QMessageBox.warning(self, "Destination requise", "Ajoutez une destination avec sa couche source, son schéma et sa table, puis relancez l'analyse.")
                return

            if not POSTGRESQL_AVAILABLE:
                QMessageBox.critical(self, "Pilote PostgreSQL absent", "Installez les dépendances PostgreSQL du plugin (psycopg2), puis relancez l'analyse.")
                return

            if not self.config_widget:
                QMessageBox.critical(self, "Connexion requise", "Renseignez la connexion PostgreSQL et testez-la avant de relancer l'analyse.")
                return

            if self._active_export_task:
                log_warning("Une publication est déjà en cours. Consultez son bilan avant de relancer.")
                return

            resolved = self._resolve_mappings_for_task(mappings)
            if not resolved:
                QMessageBox.warning(
                    self, "Destinations à compléter",
                    "Aucune destination complète n'a été trouvée. Vérifiez la couche source, le schéma et la table de chaque ligne, puis relancez l'analyse.",
                )
                return

            conn_params = self._build_conn_params()

            log_info(
                f"Analyse en lecture seule de {len(resolved)} destination(s) PostgreSQL"
            )
            task = PgCompatibilityTask(
                conn_params,
                resolved,
                description=f"Analyse PostgreSQL ({len(resolved)} table(s))",
            )
            self._compat_generation = getattr(self, "_compat_generation", 0) + 1
            task._request_generation = self._compat_generation
            previous = self._active_compat_task
            self._active_compat_task = task
            if previous:
                previous.cancel()
            task.taskCompleted.connect(
                lambda: self._on_export_compatibility_analyzed(task, conn_params)
            )
            task.taskTerminated.connect(
                lambda: self._on_export_compatibility_analyzed(task, conn_params)
            )
            QgsApplication.taskManager().addTask(task)

        except Exception as e:
            log_critical(f"Erreur de préparation PostgreSQL : {str(e)}")
            QMessageBox.critical(self, "Publication non lancée", f"La préparation a échoué : {str(e)}. Corrigez la destination ou la connexion, puis relancez l'analyse.")

    def _resolve_mappings_for_task(self, mappings):
        """Resolve QGIS layer references on main thread for PgCompatibilityTask.

        Returns a list of dicts with keys: layer_name, schema, table, layer.
        Layers not found or not vector are skipped with a warning log.
        """
        from qgis.core import QgsVectorLayer

        resolved = []
        for mapping in mappings:
            layer_name = mapping.get('transformed', '')
            schema = mapping.get('schema', '')
            table = mapping.get('table', '')

            matches = [layer for layer in QgsProject.instance().mapLayers().values()
                       if layer.name() == layer_name]
            if len(matches) > 1:
                raise ValueError(f"Plusieurs couches portent le nom '{layer_name}'. Renommez-les avant publication.")
            source_layer = matches[0] if matches else None
            if not source_layer:
                log_warning(f"Layer '{layer_name}' not found in project, skipping")
                continue
            if not isinstance(source_layer, QgsVectorLayer):
                log_warning(f"Layer '{layer_name}' is not a vector layer, skipping")
                continue

            resolved.append({
                'layer_name': layer_name,
                'schema': schema,
                'table': table,
                'layer': source_layer,
            })
        return resolved

    def _resolve_export_layer(self, info):
        project = QgsProject.instance()
        layer_id = info.get("layer_id")
        if layer_id:
            layer = project.mapLayer(layer_id)
            if layer is None:
                raise ValueError("La couche analysée a été retirée du projet. Relancez l'analyse.")
            return layer
        matches = [layer for layer in project.mapLayers().values()
                   if layer.name() == info.get("layer")]
        if len(matches) != 1:
            raise ValueError("Le nom de couche est absent ou ambigu. Renommez les couches homonymes.")
        return matches[0]

    def _build_conn_params(self):
        """Build psycopg2 connection params from config widget."""
        return {
            'host': self.config_widget.host_edit.text() or 'localhost',
            'port': self.config_widget.port_edit.value(),
            'database': self.config_widget.database_edit.text(),
            'user': self.config_widget.username_edit.text(),
            'password': self.config_widget.password_edit.text(),
            'connect_timeout': 10,
        }

    def _compat_result_current(self, task):
        return (
            getattr(self, "_active_compat_task", None) is task
            and getattr(task, "_request_generation", 0) == getattr(self, "_compat_generation", 0)
            and getattr(self, "_active_export_task", None) is None
            and not task.isCanceled()
        )

    def _on_export_compatibility_analyzed(self, task, conn_params):
        """Only the current analysis may confirm and dispatch a publication."""
        if getattr(self, "_active_compat_task", None) is not task:
            return
        if not self._compat_result_current(task):
            if getattr(task, "_request_generation", 0) == getattr(self, "_compat_generation", 0):
                self._active_compat_task = None
            return
        dialog = None
        try:
            compatibility_info = task.compatibility_info
            if task.errors or not compatibility_info:
                detail = task.errors[0] if task.errors else "Aucune table à publier."
                QMessageBox.warning(self, "Analyse incomplète", detail)
                return
            incompatible = [
                info for info in compatibility_info
                if not info.get("geometry_compatible") or not info.get("crs_compatible")
            ]
            if incompatible:
                detail = "\n".join(
                    f"{info['schema']}.{info['table']} : "
                    f"{info.get('decision') or info.get('crs_info')}"
                    for info in incompatible
                )
                QMessageBox.warning(
                    self, "Choisissez une autre destination",
                    detail + "\n\nAucune table n'a été modifiée.",
                )
                return
            dialog = IntegrationConfirmationDialog(
                compatibility_info, list(self.available_schemas or []), self,
            )
            self.confirmation_dialog = dialog
            if dialog.exec() != DialogAccepted:
                log_info("Publication annulée avant toute écriture.")
                return
            # A modal dialog processes events. Another request or publication
            # may have become current while this plan was being reviewed.
            if not self._compat_result_current(task) or self.confirmation_dialog is not dialog:
                return
            plans = dialog.get_execution_plans()
            if len(plans) != len(compatibility_info):
                raise ValueError("Le plan confirmé ne correspond plus à l'analyse. Relancez-la.")
            for info, plan in zip(compatibility_info, plans):
                if any(plan.get(key) != info.get(key) for key in ("layer_id", "schema", "table")):
                    raise ValueError("La destination du plan a changé. Relancez l'analyse.")
                info["field_mapping"] = plan["field_mapping"]
                info["allow_create"] = bool(info.get("requires_creation"))
                info["confirmed"] = True
            mode = dialog.get_selected_export_mode()
            update_config = dialog.get_update_configuration()
            if not self._compat_result_current(task) or self.confirmation_dialog is not dialog:
                return
            if mode == "update":
                self._dispatch_update_export(compatibility_info, conn_params, update_config)
            else:
                self._dispatch_async_export(compatibility_info, conn_params, mode)
        except ValueError as exc:
            QMessageBox.warning(self, "Correspondances à corriger", str(exc))
        finally:
            if dialog is not None and getattr(self, "confirmation_dialog", None) is dialog:
                self.confirmation_dialog = None
            if getattr(self, "_active_compat_task", None) is task:
                self._active_compat_task = None

    def _perform_integration(self, table_info, export_mode="append", update_config=None):
        """Compatibility entry point; use the same confirmed transaction engine."""
        if getattr(self, "_active_export_task", None) is not None:
            log_warning("Une publication est déjà en cours ; ce plan n'est pas lancé.")
            return False
        if not table_info.get("confirmed"):
            log_critical("Confirmez le plan de publication avant toute écriture.")
            return False
        layer = self._resolve_export_layer(table_info)
        job = {
            "schema": table_info["schema"], "table": table_info["table"], "layer": layer,
            "srid": layer.crs().postgisSrid(), "target_srid": table_info.get("target_srid"),
            "geometry_column": table_info.get("geometry_column"),
            "field_mapping": table_info.get("field_mapping"),
            "allow_create": bool(table_info.get("allow_create")), "update_config": update_config,
        }
        task = PgExportTask(self._build_conn_params(), [job], export_mode=export_mode)
        task.run()
        self._on_export_finished(task)
        return task.status == "success"

    def _analyze_table_compatibility(self, layer_name, schema, table):
        """Legacy read-only entry point, sharing the current analysis contract."""
        layer = self._resolve_export_layer({"layer": layer_name})
        task = PgCompatibilityTask(self._build_conn_params(), [{
            "layer_name": layer_name, "schema": schema, "table": table, "layer": layer,
        }])
        if task.run() and task.compatibility_info:
            return task.compatibility_info[0]
        return None

    def _get_postgresql_table_info(self, schema, table):
        """Récupère les informations d'une table PostgreSQL"""
        conn = None
        cur = None
        try:
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 5
            }

            conn = psycopg2.connect(**conn_params)
            cur = conn.cursor()

            # Vérifier d'abord si la table existe
            table_exists_query = """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            """
            cur.execute(table_exists_query, (schema, table))
            if cur.fetchone()[0] == 0:
                return None

            # Récupérer les informations géométriques depuis geometry_columns
            geom_query = """
                SELECT f_geometry_column, type, srid
                FROM geometry_columns
                WHERE f_table_schema = %s AND f_table_name = %s
            """
            cur.execute(geom_query, (schema, table))
            geom_info = cur.fetchone()

            # If no entry in geometry_columns, search in the table structure
            geom_column = None
            geom_type = 'Unknown'
            srid = 0

            if not geom_info:
                # Search for geometry columns
                geom_columns_query = """
                    SELECT column_name, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    AND udt_name = 'geometry'
                """
                cur.execute(geom_columns_query, (schema, table))
                geom_columns = cur.fetchall()

                if geom_columns:
                    geom_column = geom_columns[0][0]  # Take the first geometry column

                    # Try to retrieve the type and SRID from PostGIS
                    try:
                        postgis_query = sql.SQL(
                            """
                            SELECT ST_GeometryType({geom}), ST_SRID({geom})
                            FROM {schema}.{table}
                            WHERE {geom} IS NOT NULL
                            LIMIT 1
                            """
                        ).format(
                            geom=sql.Identifier(geom_column),
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table),
                        )
                        cur.execute(postgis_query)
                        postgis_result = cur.fetchone()
                        if postgis_result:
                            # Convert ST_Point -> POINT, etc.
                            st_geom_type = postgis_result[0]
                            if st_geom_type:
                                geom_type = st_geom_type.replace('ST_', '').upper()
                            srid = postgis_result[1] or 0
                    except Exception as exc:
                        QgsMessageLog.logMessage(f"PostGIS geometry type query failed (table may be empty): {exc}", "Transformer", MsgWarning)
            else:
                geom_column = geom_info[0]
                geom_type = geom_info[1]
                srid = geom_info[2]

            # Retrieve the information of the fields (except geometry)
            fields_query = """
                SELECT column_name, data_type, is_nullable, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                AND column_name != %s
                ORDER BY ordinal_position
            """
            cur.execute(fields_query, (schema, table, geom_column or 'geom'))
            fields_info = cur.fetchall()

            # Build the result
            table_info = {
                'geometry_column': geom_column,
                'geometry_type': geom_type,
                'srid': srid,
                'fields': [{
                    'name': field[0],
                    'type': field[1],
                    'nullable': field[2] == 'YES',
                    'length': field[3]
                } for field in fields_info if field[0] not in ['id', 'gid']]  # Exclure les clés primaires auto
            }

            QgsMessageLog.logMessage(
                f"Table {schema}.{table}: géom={geom_type}, SRID={srid}, champs={len(table_info['fields'])}",
                "Transformer",
                MsgInfo
            )

            return table_info

        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur récupération info table {schema}.{table}: {str(e)}", "Transformer", MsgWarning)
            return None
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception as close_exc:
                    log_warning(f"_get_postgresql_table_info: cursor close warning: {close_exc}")
            if conn is not None:
                try:
                    conn.close()
                except Exception as close_exc:
                    log_warning(f"_get_postgresql_table_info: conn close warning: {close_exc}")

    def _check_geometry_compatibility(self, source_layer, target_geom_type):
        """Check the exact compatibility between geometry types"""
        # Get the exact WKB type of the source layer
        wkb_type = source_layer.wkbType()

        # Mapping of WKB types to PostGIS
        wkb_type_map = {
            QgsWkbTypes.Type.Point: 'POINT',
            QgsWkbTypes.Type.MultiPoint: 'MULTIPOINT',
            QgsWkbTypes.Type.LineString: 'LINESTRING',
            QgsWkbTypes.Type.MultiLineString: 'MULTILINESTRING',
            QgsWkbTypes.Type.Polygon: 'POLYGON',
            QgsWkbTypes.Type.MultiPolygon: 'MULTIPOLYGON',
            QgsWkbTypes.Type.Point25D: 'POINTZ',
            QgsWkbTypes.Type.MultiPoint25D: 'MULTIPOINTZ',
            QgsWkbTypes.Type.LineString25D: 'LINESTRINGZ',
            QgsWkbTypes.Type.MultiLineString25D: 'MULTILINESTRINGZ',
            QgsWkbTypes.Type.Polygon25D: 'POLYGONZ',
            QgsWkbTypes.Type.MultiPolygon25D: 'MULTIPOLYGONZ'
        }

        # Get the expected PostgreSQL type
        expected_pg_type = wkb_type_map.get(wkb_type)

        # Geometry compatibility check (no debug log)

        # Strict verification: the type must match exactly
        if expected_pg_type:
            compatible = expected_pg_type.upper() == target_geom_type.upper()
        else:
            # Fallback to generic types for compatibility
            geom_type = source_layer.geometryType()
            expected_pg_type = get_pg_geom_type(geom_type)
            compatible = expected_pg_type.upper() == target_geom_type.upper()

        # Compatibility result (no debug log)

        return compatible

    def _create_postgresql_table(self, schema, table_name, source_layer):
        log_warning("La création doit passer par un plan de publication confirmé.")
        return False

    def _drop_and_recreate_table(self, schema, table_name, source_layer):
        log_critical("La suppression automatique est interdite. Choisissez une autre destination.")
        return False

    def _find_field_match(self, source_field_name, target_fields):
        """Find a field match between source and target"""
        source_lower = source_field_name.lower()

        # Exact match first
        for target_field in target_fields:
            if target_field['name'].lower() == source_lower:
                return target_field

        # Approximate match (contains)
        for target_field in target_fields:
            if source_lower in target_field['name'].lower() or target_field['name'].lower() in source_lower:
                return target_field

        return None

    def _generate_mapping_key(self, compatibility_info):
        """Generate a unique key for this set of mappings"""
        # Créer une clé basée sur les tables de destination
        tables = [f"{info['schema']}.{info['table']}" for info in compatibility_info]
        tables.sort()  # Assurer l'ordre pour cohérence
        return "|".join(tables)

    def _should_show_confirmation_for_mapping(self, mapping_key):
        """Determine if the confirmation window should be displayed for this specific mapping"""
        try:
            plugin_dir = os.path.dirname(os.path.realpath(__file__))
            config_path = os.path.join(plugin_dir, "transformer_postgresql_preferences.json")

            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    prefs = json.load(f)
                    # Vérifier si ce mapping spécifique a été désactivé
                    mapping_prefs = prefs.get('mapping_confirmations', {})
                    return mapping_prefs.get(mapping_key, True)  # Par défaut: afficher
            else:
                return True  # Default to showing confirmation
        except Exception as exc:
            QgsMessageLog.logMessage(f"Error reading confirmation preference: {exc}", "Transformer", MsgWarning)
            return True

    def _save_confirmation_preference_for_mapping(self, mapping_key, show_confirmation):
        """Save the confirmation preference for a specific mapping"""
        try:
            plugin_dir = os.path.dirname(os.path.realpath(__file__))
            config_path = os.path.join(plugin_dir, "transformer_postgresql_preferences.json")

            # Charger les préférences existantes
            prefs = {}
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    prefs = json.load(f)

            # Assurer que la section mapping_confirmations existe
            if 'mapping_confirmations' not in prefs:
                prefs['mapping_confirmations'] = {}

            # Sauvegarder la préférence pour ce mapping spécifique
            prefs['mapping_confirmations'][mapping_key] = show_confirmation

            with open(config_path, 'w') as f:
                json.dump(prefs, f, indent=2)

            log_info(f"Mapping confirmation preference saved for: {mapping_key}")
        except Exception as e:
            log_warning(f"Error saving mapping preference: {str(e)}")

    def save_mappings(self, checked=None):
        """Save basic table mappings (layer_name, schema, table) to postgresql_detailed_mappings.json

        Args:
            checked: Optional parameter that can be passed by a signal (e.g: QPushButton.clicked)
        """
        try:
            # Get current mappings from the UI table
            basic_mappings = self.get_current_mappings()

            if not basic_mappings:
                QgsMessageLog.logMessage("No mappings to save", "Transformer", MsgWarning)
                return False

            # Path to the detailed mappings file (single source of truth)
            plugin_dir = os.path.dirname(__file__)
            detailed_config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")

            # Load existing detailed mappings
            existing_detailed = []
            if os.path.exists(detailed_config_path):
                try:
                    with open(detailed_config_path, 'r') as f:
                        existing_detailed = json.load(f)
                        if not isinstance(existing_detailed, list):
                            existing_detailed = []
                except Exception:
                    existing_detailed = []

            # Update existing mappings or add new ones
            for new_mapping in basic_mappings:
                layer = new_mapping.get('layer') or new_mapping.get('transformed')
                schema = new_mapping['schema']
                table = new_mapping['table']

                # Check if this mapping already exists
                found = False
                for existing_mapping in existing_detailed:
                    if (existing_mapping.get('layer') == layer and existing_mapping.get('schema') == schema and existing_mapping.get('table') == table):
                        found = True
                        break

                # Add if not found
                if not found:
                    existing_detailed.append({
                        'layer': layer,
                        'schema': schema,
                        'table': table
                    })

            # Save updated mappings
            with open(detailed_config_path, 'w') as f:
                json.dump(existing_detailed, f, indent=2)

            QgsMessageLog.logMessage(
                f"Saved {len(basic_mappings)} mapping(s) to {detailed_config_path}",
                "Transformer", MsgSuccess
            )

            return True

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error saving mappings: {str(e)}",
                "Transformer", MsgWarning
            )
            return False

    def check_auto_connect(self, specific_layers=None):
        """Check if existing transformed layers have saved mappings

        Args:
            specific_layers (list, optional): Liste des noms de couches spécifiques à vérifier.
                                             Si None, vérifie toutes les couches du projet.
        """
        if not self.auto_connect:
            return

        # Get all layers from the project or specific layers
        project = QgsProject.instance()
        if specific_layers:
            # Vérifier uniquement les couches spécifiées
            all_project_layers = project.mapLayers().values()
            layers = [layer for layer in all_project_layers
                      if hasattr(layer, 'name') and layer.name() in specific_layers]
            QgsMessageLog.logMessage(f"Checking auto-connect for specific layers: {specific_layers}", "Transformer", MsgInfo)
        else:
            # Vérifier toutes les couches du projet
            layers = [layer for layer in project.mapLayers().values() if hasattr(layer, 'name')]

        # Compter les mappings trouvés et chargés
        mappings_found = 0
        mappings_loaded = 0

        # Search for a mapping for each layer
        for layer in layers:
            if not hasattr(layer, 'name'):
                continue

            layer_name = layer.name()

            # Path to detailed mappings file
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")

            if not os.path.exists(config_path):
                continue

            try:
                with open(config_path, 'r') as f:
                    all_mappings = json.load(f)

                # Search for mapping for this layer
                for mapping in all_mappings:
                    if mapping.get('layer') == layer_name:
                        schema = mapping.get('schema')
                        table = mapping.get('table')

                        if schema and table:
                            self._insert_saved_destination(layer_name, schema, table)

                            mappings_found += 1
                            mappings_loaded += 1
                            break
            except Exception as e:
                QgsMessageLog.logMessage(f"Error loading mapping for {layer_name}: {str(e)}", "Transformer", MsgWarning)

        return mappings_loaded

    def load_mappings(self):
        """Load saved mappings and allow selection by table"""
        try:
            # Path to the detailed mappings file (single source of truth)
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")

            if not os.path.exists(config_path):
                QgsMessageLog.logMessage("No detailed mappings file found", "Transformer", MsgWarning)
                return

            # Load all detailed mappings
            with open(config_path, 'r') as f:
                all_mappings = json.load(f)

            if not all_mappings:
                QgsMessageLog.logMessage("The detailed mappings file exists but contains no mappings", "Transformer", MsgWarning)
                return

            # Organize mappings by table to facilitate selection
            tables_dict = {}
            for mapping in all_mappings:
                layer_name = mapping.get("layer_name", "")
                schema = mapping.get("schema", "")
                table = mapping.get("table", "")

                if not all([layer_name, schema, table]):
                    continue  # Skip incomplete mappings

                # Create unique key and label
                label = f"{layer_name} : {schema}.{table}"
                tables_dict[label] = mapping

            # Sort the keys for better presentation
            sorted_labels = sorted(tables_dict.keys())

            if not sorted_labels:
                QgsMessageLog.logMessage("No valid mappings found in file", "Transformer", MsgWarning)
                return

            # Champ de sélection avec QMessageBox personnalisée
            from qgis.PyQt.QtWidgets import QInputDialog

            label, ok = QInputDialog.getItem(
                self,
                "Charger une destination enregistrée",
                "Choisissez la destination :",
                sorted_labels,
                0,
                False
            )

            if ok and label:
                # Load the selected mapping
                mapping = tables_dict[label]

                # Clear existing mappings in the UI
                self.mapping_table.setRowCount(0)

                # Add the selected mapping to the UI
                layer_name = mapping.get("layer_name")
                schema = mapping.get("schema")
                table = mapping.get("table")

                self._insert_saved_destination(layer_name, schema, table)

                QgsMessageLog.logMessage(f"Destination chargée : {label}", "Transformer", MsgSuccess)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading mappings: {str(e)}", "Transformer", MsgCritical)


class PostgreSQLIntegrationWidget(QWidget):
    """Widget principal d'intégration PostgreSQL with splitter"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Configuration de l'interface (compact vertical layout, no splitter gap)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(FrameNoFrame)
        scroll.setAccessibleName("Connexion et destinations PostgreSQL")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Configuration widget on top (size policy = Maximum vertical, takes only what it needs)
        self.config_widget = PostgreSQLConfigWidget()

        # Mapping widget below (claims remaining vertical space)
        self.mapping_widget = PostgreSQLMappingWidget()
        self.mapping_widget.setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Expanding)

        # Link widgets so mapping can access config
        self.mapping_widget.config_widget = self.config_widget
        # Le déclencheur historique de rafraîchissement utilise le parent du
        # formulaire. Le contenu défilable expose le même destinataire.
        content.mapping_widget = self.mapping_widget

        content_layout.addWidget(self.config_widget)
        content_layout.addWidget(self.mapping_widget, 1)

    def get_config_widget(self):
        """Return config widget reference"""
        return self.config_widget

    def get_mapping_widget(self):
        """Return mapping widget reference"""
        return self.mapping_widget

    def trigger_auto_mapping_check(self, layer_names=None):
        """Trigger automatic check of mappings for transformed layers

        Args:
            layer_names (list, optional): List of layer names to check.
                                         If None, checks all layers.
        Returns:
            int: Number of mappings loaded successfully
        """
        if hasattr(self.mapping_widget, 'check_auto_connect'):
            return self.mapping_widget.check_auto_connect(layer_names)
        return 0

    def teardown_resources(self):
        """Cancel active PostgreSQL tasks and disconnect project signals."""
        config_w = getattr(self, 'config_widget', None)
        conn_task = getattr(config_w, '_active_conn_task', None) if config_w is not None else None
        if conn_task is not None and hasattr(conn_task, 'cancel'):
            try:
                conn_task.cancel()
            except Exception as exc:
                QgsMessageLog.logMessage(f"PG conn task cancel warning: {exc}", "Transformer", MsgWarning)
        mapping_w = getattr(self, 'mapping_widget', None)
        if mapping_w is not None:
            for attr in ('_active_export_task', '_active_compat_task', '_active_schema_task', '_active_table_task'):
                task = getattr(mapping_w, attr, None)
                if task is not None and hasattr(task, 'cancel'):
                    try:
                        task.cancel()
                    except Exception as exc:
                        QgsMessageLog.logMessage(f"PG mapping task cancel warning: {exc}", "Transformer", MsgWarning)
            if hasattr(mapping_w, 'teardown_qgis_signals'):
                mapping_w.teardown_qgis_signals()
