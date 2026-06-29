# -*- coding: utf-8 -*-
"""
PostgreSQL integration module for Transformer
Mapping & export of transformed tables to PostgreSQL
"""

import os
import json
from typing import Dict, List, Optional, Any
from pathlib import Path

from qgis.PyQt.QtCore import Qt, pyqtSignal, QVariant, QThread, QStringListModel
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QSplitter,
    QFrame, QScrollArea, QTabWidget, QTreeWidget, QTreeWidgetItem, QGridLayout,
    QApplication, QPlainTextEdit, QProgressBar, QSlider, QCompleter,
    QInputDialog, QStyle, QRadioButton
)

from qgis.PyQt.QtWidgets import QSizePolicy
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import (
    QPixmap, QIcon, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor, QFont,
    QPainter, QPen, QBrush,
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsWkbTypes,
    QgsExpression, QgsFeatureRequest, QgsSettings,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCoordinateTransformContext, QgsMessageLog, QgsApplication
)
from qgis.gui import QgsMessageBar
from qgis.utils import iface
from datetime import datetime
from ..shared.logger import log_info, log_success, log_warning, log_error, log_critical
from ..shared.helpers import apply_compact_button
from ..shared.field_icons import field_type_icon
from ..shared.geom_types import get_pg_geom_type
from ..shared.compat import (
    AlignCenter, Vertical, PlainText, FrameBox, FrameStyledPanel, FrameRaised,
    HeaderStretch, HeaderFixed, MsgBoxOk, MsgBoxYes, MsgBoxNo, MsgBoxIconInfo,
    DialogAccepted, ItemIsEnabled, ItemIsSelectable, PasswordEchoMode,
    SelectRows, _SizePolicy,
    MsgInfo, MsgWarning, MsgCritical, MsgSuccess,
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
from .connection_task import PgConnectionTask, PgSchemaTask, PgCompatibilityTask

class IntegrationConfirmationDialog(QDialog):
    """Interactive dialog for PostgreSQL mapping confirmation"""
    
    def __init__(self, compatibility_info, available_schemas=None, parent=None):
        super().__init__(parent)
        self.compatibility_info = compatibility_info
        self.available_schemas = available_schemas or []
        self.modified_mappings = {} # Stockage des modifications
        self.original_mappings = {} # Mappings originaux pour comparaison
        self.mapping_widgets = {} # Widgets de mapping pour chaque couche
        self.dont_show_again = False # Attribut manquant
        
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
        self.setWindowTitle("PostgreSQL Field Mapping")
        self.setModal(True)
        
        # Optimized size for the mapping table
        self.resize(1100, 750)
        self.setMinimumSize(1000, 650)
        
        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(15)
        
        # Title and instructions - NATIVE QGIS STYLE
        title_label = QLabel("Mapping fields for PostgreSQL integration")
        title_label.setAlignment(AlignCenter)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        subtitle_label = QLabel("Verify and modify the automatic field mapping if necessary")
        subtitle_label.setAlignment(AlignCenter)
        subtitle_font = QFont()
        subtitle_font.setPointSize(10)
        subtitle_label.setFont(subtitle_font)
        layout.addWidget(subtitle_label)
        
        # Tabs for each layer - NATIVE QGIS STYLE
        self.tabs = QTabWidget()
        # Remove all custom CSS - use native QGIS styling
        
        # Create a tab for each layer
        for i, info in enumerate(self.compatibility_info):
            tab_widget = self._create_field_mapping_table(info)
            self.tabs.addTab(tab_widget, f"{info['layer']}")
        
        layout.addWidget(self.tabs)
        
        # Statistiques de mapping - NATIVE QGIS STYLE
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel()
        # Create native frame for stats
        stats_frame = QFrame()
        stats_frame.setFrameStyle(FrameBox | FrameRaised)
        stats_frame.setLineWidth(1)
        stats_frame_layout = QHBoxLayout(stats_frame)
        stats_frame_layout.addWidget(self.stats_label)
        stats_layout.addWidget(stats_frame)
        stats_layout.addStretch()
        
        # Quick action buttons - NATIVE QGIS STYLE
        self.auto_map_btn = QPushButton("Auto-mapping")
        self.clear_btn = QPushButton("Clear all")
        self.add_field_btn = QPushButton("Add custom field")
        
        apply_compact_button(self.auto_map_btn)
        apply_compact_button(self.clear_btn)
        apply_compact_button(self.add_field_btn)
        
        stats_layout.addWidget(self.auto_map_btn)
        stats_layout.addWidget(self.clear_btn)
        stats_layout.addWidget(self.add_field_btn)
        layout.addLayout(stats_layout)
        
        # **NOUVELLEMENT AJOUTÉ** - Section Mode d'Export
        export_mode_frame = QFrame()
        export_mode_frame.setFrameStyle(FrameBox | FrameRaised)
        export_mode_frame.setLineWidth(1)
        export_mode_layout = QVBoxLayout(export_mode_frame)
        
        # Titre section
        mode_title = QLabel("Export Mode (Table Handling)")
        mode_title_font = QFont()
        mode_title_font.setBold(True)
        mode_title.setFont(mode_title_font)
        export_mode_layout.addWidget(mode_title)
        
        # Radio buttons pour les modes
        mode_buttons_layout = QHBoxLayout()
        
        self.append_mode = QRadioButton("Append")
        self.append_mode.setToolTip("Add new records to existing table (safe)")
        self.append_mode.setChecked(True) # Mode par défaut
        
        self.replace_mode = QRadioButton("Replace") 
        self.replace_mode.setToolTip("DELETE ALL existing data and replace with new data (DANGEROUS)")
        
        self.update_mode = QRadioButton("Update")
        self.update_mode.setToolTip("Update existing records based on key field (advanced)")
        
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
        join_type_layout.addWidget(QLabel("Join Type:"))
        
        self.attribute_join = QRadioButton("Attribute-based")
        self.attribute_join.setToolTip("Join using a common field (ID, code, etc.)")
        self.attribute_join.setChecked(True)
        
        self.spatial_join = QRadioButton("Spatial-based") 
        self.spatial_join.setToolTip("Join using spatial intersection/proximity")
        
        join_type_layout.addWidget(self.attribute_join)
        join_type_layout.addWidget(self.spatial_join)
        join_type_layout.addStretch()
        update_config_layout.addLayout(join_type_layout)
        
        # Configuration clé attributaire
        self.attribute_config = QWidget()
        attr_layout = QHBoxLayout(self.attribute_config)
        attr_layout.addWidget(QLabel("Key Field:"))
        
        self.source_key_combo = QComboBox()
        self.source_key_combo.setToolTip("Source layer key field")
        self.target_key_combo = QComboBox() 
        self.target_key_combo.setToolTip("Target table key field")
        
        attr_layout.addWidget(QLabel("Source:"))
        attr_layout.addWidget(self.source_key_combo)
        attr_layout.addWidget(QLabel("Target:"))
        attr_layout.addWidget(self.target_key_combo)
        attr_layout.addStretch()
        update_config_layout.addWidget(self.attribute_config)
        
        # Configuration clé spatiale
        self.spatial_config = QWidget()
        spatial_layout = QHBoxLayout(self.spatial_config)
        spatial_layout.addWidget(QLabel("Spatial Method:"))
        
        self.spatial_method_combo = QComboBox()
        self.spatial_method_combo.addItems([
            "Intersects", "Contains", "Within", 
            "Touches", "Overlaps", "Nearest (buffer)"
        ])
        self.spatial_method_combo.setToolTip("Spatial relationship for matching records")
        
        self.buffer_distance = QDoubleSpinBox()
        self.buffer_distance.setRange(0, 10000)
        self.buffer_distance.setValue(0.1)
        self.buffer_distance.setSuffix(" m")
        self.buffer_distance.setToolTip("Buffer distance for spatial matching")
        
        spatial_layout.addWidget(self.spatial_method_combo)
        spatial_layout.addWidget(QLabel("Buffer:"))
        spatial_layout.addWidget(self.buffer_distance)
        spatial_layout.addStretch()
        update_config_layout.addWidget(self.spatial_config)
        
        self.update_config_widget.setVisible(False) # Masqué par défaut
        export_mode_layout.addWidget(self.update_config_widget)
        
        # Message d'avertissement pour Replace mode
        self.warning_label = QLabel("WARNING: Replace mode will DELETE ALL existing data in target tables!")
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
        
        # Case à cocher "Ne plus afficher" - NATIVE QGIS STYLE
        checkbox_container = QHBoxLayout()
        self.dont_show_checkbox = QCheckBox("Do not show this window for future integrations")
        # Use native QGIS checkbox styling - no custom CSS
        checkbox_container.addWidget(self.dont_show_checkbox)
        checkbox_container.addStretch()
        layout.addLayout(checkbox_container)
        
        # Main buttons - NATIVE QGIS STYLE
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        self.reset_btn = QPushButton("Reset")
        self.save_column_config_btn = QPushButton("Save Column Config")
        self.cancel_btn = QPushButton("Cancel")
        self.proceed_btn = QPushButton("Apply mapping")
        
        # Native QGIS button sizes - no custom styling
        self.reset_btn.setMinimumSize(130, 35)
        self.save_column_config_btn.setMinimumSize(160, 35)
        self.cancel_btn.setMinimumSize(120, 35)
        self.proceed_btn.setMinimumSize(180, 35)
        
        # Make proceed button the default
        self.proceed_btn.setDefault(True)
        
        buttons_layout.addWidget(self.reset_btn)
        buttons_layout.addWidget(self.save_column_config_btn)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_btn)
        buttons_layout.addWidget(self.proceed_btn)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
        
        # Connexions
        self.tabs.currentChanged.connect(self._update_stats)
        self.auto_map_btn.clicked.connect(self._auto_map_current_layer)
        self.clear_btn.clicked.connect(self._clear_current_mapping)
        self.add_field_btn.clicked.connect(self._add_custom_field)
        self.reset_btn.clicked.connect(self._reset_mappings)
        self.save_column_config_btn.clicked.connect(self._save_column_config)
        self.cancel_btn.clicked.connect(self.reject)
        self.proceed_btn.clicked.connect(self.accept)
        self.dont_show_checkbox.toggled.connect(self._on_dont_show_toggled)
        
        # Update initial stats
        self._update_stats()
        
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
        
        layer_info = QLabel(f"Layer: {info['layer']} → Destination: {info['schema']}.{info['table']}")
        layer_font = QFont()
        layer_font.setBold(True)
        layer_font.setPointSize(11)
        layer_info.setFont(layer_font)
        header_layout.addWidget(layer_info)
        layout.addWidget(header_frame)
        
        # Table for field mapping
        table = QTableWidget()
        table.setColumnCount(7) # Add a column for deletion
        table.setHorizontalHeaderLabels([
            "Source field", 
            "Source type", 
            "Destination field", 
            "Destination type", 
            "Forced type", 
            "Status",
            "Action"
        ])
        
        # Use native QGIS table styling - remove all custom CSS
        
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(SelectRows)
        table.verticalHeader().setVisible(False)
        
        # Column configuration
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, HeaderFixed) # Source field
        header.setSectionResizeMode(1, HeaderFixed) # Source type
        header.setSectionResizeMode(2, HeaderStretch) # Destination field (modifiable)
        header.setSectionResizeMode(3, HeaderFixed) # Destination type
        header.setSectionResizeMode(4, HeaderFixed) # Forced type
        header.setSectionResizeMode(5, HeaderFixed) # Status
        header.setSectionResizeMode(6, HeaderFixed) # Action
        
        # Column widths
        table.setColumnWidth(0, 160) # Source field
        table.setColumnWidth(1, 90) # Source type
        table.setColumnWidth(3, 110) # Destination type
        table.setColumnWidth(4, 110) # Forced type
        table.setColumnWidth(5, 60) # Status
        table.setColumnWidth(6, 70) # Action
        
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
            dest_combo.addItem("<Non mappé>", "")
            
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
            forced_type_combo.addItems([
                "<Auto>", # Default value - uses the destination type
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
            delete_btn = QPushButton("Delete")
            delete_btn.setMaximumSize(60, 25)
            delete_btn.setToolTip("Delete this field mapping")
            # Use native QGIS button styling - no custom CSS
            delete_btn.clicked.connect(lambda checked, r=row: self._delete_field_mapping(r))
            table.setCellWidget(row, 6, delete_btn)
        
        layout.addWidget(table)
        
        # Save table reference
        layer_key = info['layer']
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
            item.setToolTip("Field not mapped")
            return
            
        # Search for the destination field
        dest_field = None
        for field in dest_fields:
            if field['name'] == dest_field_name:
                dest_field = field
                break
        
        if not dest_field:
            item.setText("ERR")
            item.setToolTip("Destination field not found")
            return
        
        # Check type compatibility
        if self._are_types_compatible(source_field['type'], dest_field['type']):
            item.setText("OK")
            item.setToolTip("Types compatible")
        else:
            item.setText("WARN")
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
            item.setToolTip("Field not mapped")
            return
            
        # If a forced type is defined, always compatible (force conversion)
        if forced_type != "<Auto>":
            item.setText("FORCE")
            item.setToolTip(f"Conversion forcée: {source_field['type']} -> {forced_type}")
            return
            
        # Otherwise, use normal logic
        dest_field = None
        for field in dest_fields:
            if field['name'] == dest_field_name:
                dest_field = field
                break
        
        if not dest_field:
            item.setText("ERR")
            item.setToolTip("Destination field not found")
            return
        
        # Check type compatibility
        if self._are_types_compatible(source_field['type'], dest_field['type']):
            item.setText("OK")
            item.setToolTip("Types compatibles")
        else:
            item.setText("WARN")
            item.setToolTip(f"Attention: {source_field['type']} -> {dest_field['type']} - Utilisez Type Forcé si nécessaire")
    
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
                return # Impossible de traiter cette ligne
        
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
            status_item = table.item(row, 5) # Statut en colonne 5 maintenant
            
            if combo and combo.currentData():
                mapped_fields += 1
                
                if status_item and status_item.text() in ["OK", "FORCE"]:
                    compatible_fields += 1
        
        mapping_percentage = (mapped_fields / total_fields * 100) if total_fields > 0 else 0
        compatibility_percentage = (compatible_fields / mapped_fields * 100) if mapped_fields > 0 else 0
        
        stats_text = (
            f"{layer_key}: "
            f"{mapped_fields}/{total_fields} champs mappés ({mapping_percentage:.1f}%) | "
            f"{compatible_fields}/{mapped_fields} compatibles ({compatibility_percentage:.1f}%)"
        )
        
        self.stats_label.setText(stats_text)
    
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
                combo.setCurrentIndex(0) # "<Non mappé>"
    
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
            QMessageBox.warning(self, "Warning", "Please select a layer")
            return
            
        # Dialogue for entering the custom field name and default value
        field_name, ok1 = QInputDialog.getText(self, 
            "Field name", 
            "Enter the name of the custom field:")
            
        if not ok1 or not field_name.strip():
            return
            
        field_name = field_name.strip()
        
        # Dialogue for entering the default value
        default_value, ok2 = QInputDialog.getText(self, 
            "Default value", 
            f"Enter the default value for '{field_name}':")
            
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
        source_item.setBackground(QColor(255, 255, 200)) # Jaune clair pour les champs personnalisés
        table.setItem(row, 0, source_item)
        
        # Type source
        type_item = QTableWidgetItem("Custom")
        type_item.setFlags(ItemIsEnabled | ItemIsSelectable)
        type_item.setBackground(QColor(255, 255, 200))
        table.setItem(row, 1, type_item)
        
        # Destination field (modifiable - user can choose)
        dest_combo = QComboBox()
        dest_combo.addItem("<Non mappé>", "")
        
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
        forced_type_combo.setEnabled(False) # Non modifiable
        table.setCellWidget(row, 4, forced_type_combo)
        
        # Custom status
        status_item = QTableWidgetItem("CUSTOM")
        status_item.setFlags(ItemIsEnabled | ItemIsSelectable)
        status_item.setToolTip(f"Custom field: {field_name} = '{default_value}' ({pg_type})")
        status_item.setBackground(QColor(255, 255, 200))
        table.setItem(row, 5, status_item)
        
        # Delete button for custom fields - NATIVE QGIS STYLE
        delete_btn = QPushButton("Delete")
        delete_btn.setMaximumSize(60, 25)
        delete_btn.setToolTip("Delete this custom field")
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
                "Confirmer la suppression",
                f"Voulez-vous vraiment supprimer le mapping pour '{field_name}' ?",
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
            source_fields = widgets['source_fields']
            
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
    
    def _on_export_mode_changed(self):
        """Gère l'affichage du message d'avertissement et de la config selon le mode sélectionné"""
        if self.replace_mode.isChecked():
            self.warning_label.setVisible(True)
            self.update_config_widget.setVisible(False)
        elif self.update_mode.isChecked():
            self.warning_label.setVisible(False)
            self.update_config_widget.setVisible(True)
            self._populate_key_fields()
        else: # append mode
            self.warning_label.setVisible(False)
            self.update_config_widget.setVisible(False)
    
    def _on_join_type_changed(self):
        """Gère l'affichage des configurations selon le type de jointure"""
        if self.attribute_join.isChecked():
            self.attribute_config.setVisible(True)
            self.spatial_config.setVisible(False)
        else: # spatial join
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
            schema = first_table.get('schema', '')
            table = first_table.get('table', '')
            
            try:
                # Récupérer les champs de la table PostgreSQL
                # (Code de connexion similaire à celui utilisé ailleurs)
                self.target_key_combo.addItem("id") # Champ ID généralement présent
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
            return "append" # Par défaut
    
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
        else: # spatial
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
                    if (existing.get("layer_name") == layer_name and
                        existing.get("schema") == schema and
                        existing.get("table") == table):
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
                if child.columnCount() >= 7: # Notre table a 7 colonnes
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
                dest_field = dest_combo.currentData() or dest_combo.currentText().strip()
                
                # Colonne 4: Type forcé (ComboBox)
                forced_type_combo = mapping_table.cellWidget(row, 4)
                forced_type = "<Auto>" # Valeur par défaut
                if isinstance(forced_type_combo, QComboBox):
                    forced_type = forced_type_combo.currentText().strip()
                
                # Seulement ajouter si il y a un mapping valide
                if source_field and dest_field and dest_field != "<Non mappé>":
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
                'custom_fields': custom_fields # À implémenter plus tard si nécessaire
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
        "not_tested": "Connection not tested",
        "connected": "Connected",
        "error": "Connection issue",
        "failed": "Connection failed",
        "testing": "Testing connection...",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._state = "not_tested"
        self.setToolTip(self._TOOLTIPS[self._state])

    def set_state(self, state: str):
        if state not in self._COLORS:
            state = "not_tested"
        self._state = state
        self.setToolTip(self._TOOLTIPS[state])
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
        conn_group = QGroupBox("PostgreSQL Connection")
        conn_form = QFormLayout()
        conn_form.setContentsMargins(8, 8, 8, 8)
        conn_form.setVerticalSpacing(4)

        # Profile selector row
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.setToolTip("Saved connection profiles")
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_combo, 1)

        save_as_btn = QPushButton("Save As...")
        save_as_btn.setToolTip("Save current settings as a new named profile")
        save_as_btn.clicked.connect(self._save_current_as_profile)
        profile_row.addWidget(save_as_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Delete the selected profile")
        delete_btn.clicked.connect(self._delete_current_profile)
        profile_row.addWidget(delete_btn)

        conn_form.addRow("Profile:", profile_row)

        # Connection fields (public attributes, used by other widgets)
        self.host_edit = QLineEdit("localhost")
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(5432)
        self.database_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(PasswordEchoMode)

        conn_form.addRow("Host:", self.host_edit)
        conn_form.addRow("Port:", self.port_edit)
        conn_form.addRow("Database:", self.database_edit)
        conn_form.addRow("Username:", self.username_edit)
        conn_form.addRow("Password:", self.password_edit)

        # Status row (LED + label)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_indicator = _StatusLed()
        self.status_label = QLabel("Not tested")
        font = self.status_label.font()
        font.setItalic(True)
        font.setPointSize(9)
        self.status_label.setFont(font)
        palette = self.status_label.palette()
        palette.setColor(self.status_label.foregroundRole(), QColor(120, 120, 120))
        self.status_label.setPalette(palette)
        status_row.addWidget(self.status_indicator)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        conn_form.addRow("Status:", status_row)

        # Action buttons row
        actions_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self.test_connection)
        actions_row.addWidget(test_btn)

        save_current_btn = QPushButton("Save")
        save_current_btn.setToolTip("Save changes back to the selected profile")
        save_current_btn.clicked.connect(self._save_current_profile)
        actions_row.addWidget(save_current_btn)

        actions_row.addStretch()

        help_btn = QPushButton("Help")
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
            "password": str(raw.get("password", "")),
        }

    def _current_form_as_profile(self):
        return {
            "host": self.host_edit.text(),
            "port": self.port_edit.value(),
            "database": self.database_edit.text(),
            "username": self.username_edit.text(),
            "password": self.password_edit.text(),
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
                        self._write_all_profiles()
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
        try:
            data = {"active": self._active_name, "connections": self._connections}
            with open(self._connections_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"PostgreSQL profiles save error: {exc}",
                "Transformer", MsgCritical,
            )

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
        self.password_edit.setText(str(prof.get("password", "")))
        QTimer.singleShot(500, self.auto_test_connection)

    def _on_profile_selected(self, name):
        if self._loading_combo or not name:
            return
        if name in self._connections:
            self._active_name = name
            self._apply_active_profile()
            self._write_all_profiles()

    def _save_current_as_profile(self):
        suggested = self._active_name or "Default"
        name, ok = QInputDialog.getText(
            self, "Save Connection Profile",
            "Profile name:",
        )
        if not ok:
            return
        name = (name or "").strip() or suggested
        if not name:
            QMessageBox.warning(self, "Save Profile", "Profile name cannot be empty.")
            return
        if name in self._connections:
            reply = QMessageBox.question(
                self, "Overwrite Profile",
                f"Profile '{name}' already exists. Overwrite it?",
                MsgBoxYes | MsgBoxNo,
            )
            if reply != MsgBoxYes:
                return
        self._connections[name] = self._current_form_as_profile()
        self._active_name = name
        self._write_all_profiles()
        self._populate_connection_combo()
        log_info(f"PostgreSQL profile '{name}' saved")

    def _save_current_profile(self):
        if not self._active_name:
            self._save_current_as_profile()
            return
        self._connections[self._active_name] = self._current_form_as_profile()
        self._write_all_profiles()
        log_info(f"PostgreSQL profile '{self._active_name}' updated")

    def _delete_current_profile(self):
        name = self.profile_combo.currentText()
        if not name or name not in self._connections:
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete connection profile '{name}'?",
            MsgBoxYes | MsgBoxNo,
        )
        if reply != MsgBoxYes:
            return
        del self._connections[name]
        if self._active_name == name:
            self._active_name = next(iter(self._connections), "")
        self._write_all_profiles()
        self._populate_connection_combo()
        if self._active_name:
            self._apply_active_profile()

    # ------------------------------------------------------------------
    # Status (LED)
    # ------------------------------------------------------------------

    def update_status(self, status):
        """status in {'connected','error','failed','not_tested','testing'}"""
        labels = {
            "connected": "Connection OK",
            "error": "Connection issue",
            "failed": "Connection failed",
            "not_tested": "Not tested",
            "testing": "Testing...",
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
                log_warning("psycopg2 is not installed")
            self.update_status("failed")
            return

        host = self.host_edit.text()
        port = self.port_edit.value()
        database = self.database_edit.text()
        username = self.username_edit.text()
        password = self.password_edit.text()

        if not all([host, database, username, password]):
            if not silent:
                log_warning("Please fill in all connection fields")
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
            description=f"PG connect test {database}@{host}:{port}",
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
        self._active_conn_task = None
        if task.success:
            self.update_status("connected")
            if not silent:
                log_success(
                    f"PostgreSQL connection established: {database}@{host}:{port} "
                    f"(user: {username}) elapsed_ms={task.elapsed_ms}"
                )
            self.trigger_schema_refresh()
        else:
            self.update_status("failed")
            if not silent:
                log_critical(
                    f"PostgreSQL connection failed: {task.message} "
                    f"elapsed_ms={task.elapsed_ms}"
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
        msg.setWindowTitle("PostgreSQL Help")
        msg.setIcon(MsgBoxIconInfo)
        help_text = """PostgreSQL Connection

Profile management
- Save your connection settings under a name (Save As...)
- Switch between saved profiles via the Profile dropdown
- The selected profile becomes the default on next start

Status indicator
- Gray: not tested
- Green: connection OK
- Orange: connection issue
- Red: connection failed

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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_widget = None
        self.available_schemas = []
        self.available_tables = {}
        self.auto_connect = True # Enable auto-connect functionality
        self._active_conn_task = None
        self._active_schema_task = None
        self._active_table_task = None
        self._active_export_task = None
        self._active_compat_task = None
        self.setup_ui()
        self.setup_qgis_signals()
        
        # Essayer de charger automatiquement les mappings existants au démarrage
        self.auto_load_existing_mappings()
    
    def setup_ui(self):
        """Setup native QGIS mapping interface"""
        layout = QVBoxLayout(self)
        
        # Title with native QGIS font
        title = QLabel("Layer to PostgreSQL")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Toolbar
        toolbar_layout = QHBoxLayout()
        
        # Add mapping button
        add_btn = QPushButton("Add Mapping")
        add_btn.clicked.connect(self.add_mapping)
        toolbar_layout.addWidget(add_btn)
        
        # Remove mapping button
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_selected)
        toolbar_layout.addWidget(remove_btn)
        
        # Refresh schemas button
        refresh_btn = QPushButton("Refresh Schemas")
        refresh_btn.clicked.connect(self.refresh_schemas)
        toolbar_layout.addWidget(refresh_btn)
        
        # Add separator
        toolbar_layout.addWidget(QWidget()) # Spacer
        
        # Save Mapping button
        save_mapping_btn = QPushButton("Save Mapping")
        save_mapping_btn.clicked.connect(self.save_mappings)
        toolbar_layout.addWidget(save_mapping_btn)
        
        # Load Mapping button
        load_mapping_btn = QPushButton("Load Mapping")
        load_mapping_btn.clicked.connect(self.load_mappings)
        toolbar_layout.addWidget(load_mapping_btn)
        
        # Export PostgreSQL button
        export_btn = QPushButton("Export PostgreSQL")
        export_btn.clicked.connect(self.export_to_postgresql)
        toolbar_layout.addWidget(export_btn)
        
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)
        
        # Mapping table
        self.mapping_table = QTableWidget()
        self.mapping_table.setColumnCount(3)
        self.mapping_table.setHorizontalHeaderLabels(["QGIS Layer", "Schema", "Table"])
        
        # Set column widths
        header = self.mapping_table.horizontalHeader()
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
    
    def on_layers_added(self, layers):
        """Handle when new layers are added to QGIS project"""
        vector_layers = [layer for layer in layers if isinstance(layer, QgsVectorLayer) and layer.isValid()]
        if vector_layers:
            self.refresh_layer_lists()
            # PostgreSQL mapping updated (silent)
            
    def on_layers_removed(self, layer_ids):
        """Handle when layers are removed from QGIS project"""
        if layer_ids:
            self.refresh_layer_lists()
            # PostgreSQL mapping updated (silent)
            
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
            layer_combo.addItems(layer_names)
            self.mapping_table.setCellWidget(row, 0, layer_combo)
            
            # Colonne 1: ComboBox avec les schémas PostgreSQL
            schema_combo = QComboBox()
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
            QMessageBox.critical(self, "Erreur", f"Impossible d'ajouter le mapping:\n{str(e)}")
    
    def remove_selected(self):
        """Supprime le mapping sélectionné"""
        current_row = self.mapping_table.currentRow()
        if current_row >= 0:
            self.mapping_table.removeRow(current_row)
    
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
                            table_combo.insertItem(table_combo.count() - 1, table_name) # Insérer avant "+ Nouvelle table..."
                        
                        # Sélectionner la nouvelle table
                        table_combo.setCurrentText(table_name)
                        
                        QgsMessageLog.logMessage(f"Nouvelle table '{table_name}' ajoutée au mapping ligne {row}", "Transformer", MsgInfo)
                else:
                    # Annuler - remettre à vide
                    table_combo = self.mapping_table.cellWidget(row, 2)
                    if table_combo:
                        table_combo.setCurrentIndex(0) # Remettre à l'index vide
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
                table_combo.addItem("") # Option vide
                
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
            log_warning("psycopg2 is not installed")
            return

        if not self.config_widget:
            log_warning("No configuration widget available")
            return

        conn_params = {
            'host': self.config_widget.host_edit.text() or 'localhost',
            'port': self.config_widget.port_edit.value(),
            'database': self.config_widget.database_edit.text(),
            'user': self.config_widget.username_edit.text(),
            'password': self.config_widget.password_edit.text(),
        }

        if not conn_params['database']:
            log_warning("Database name is required")
            return
        if not conn_params['user']:
            log_warning("Username is required")
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
        self._active_schema_task = None
        if task.error:
            log_critical(f"Failed to refresh schemas: {task.error}")
            return

        self.available_schemas = task.schemas
        self.available_tables = task.tables_by_schema

        schemas_info = (
            f"Connected to {conn_params['database']}@{conn_params['host']} - "
            f"Loaded {len(task.schemas)} schemas"
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
                        layer_combo.setEditable(True)
                        layer_combo.addItem("")
                        layer_combo.addItems(layer_names)
                        layer_combo.setCurrentText(layer_name)
                        self.mapping_table.setCellWidget(row, 0, layer_combo)
                        
                        # Schema combo
                        schema_combo = QComboBox()
                        schema_combo.setEditable(True)
                        schema_combo.addItem("")
                        if self.available_schemas:
                            schema_combo.addItems(self.available_schemas)
                        schema_combo.setCurrentText(schema)
                        schema_combo.currentTextChanged.connect(
                            lambda text, r=row: self.on_schema_changed(r, text)
                        )
                        self.mapping_table.setCellWidget(row, 1, schema_combo)
                        
                        # Table combo
                        table_combo = QComboBox()
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
                
                # Determine ComboBox type and update accordingly
                if isinstance(schema_combo, SearchableComboBox):
                    # For ComboBoxes with advanced search
                    schema_combo.clear()
                    schema_combo.addItems(self.available_schemas)
                    
                    # Configure completion model
                    if hasattr(schema_combo, 'completer'):
                        model = QStringListModel(self.available_schemas)
                        schema_combo.completer.setModel(model)
                else:
                    # Pour les ComboBox standard
                    schema_combo.clear()
                    schema_combo.addItems(self.available_schemas)
                
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
            log_warning("psycopg2 is not installed")
            return

        if not self.config_widget:
            log_warning("PostgreSQL configuration not available")
            return

        if not schema_name:
            log_warning("Empty schema name")
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
        self._active_table_task = None
        if task.error:
            log_critical(f"Error loading tables for schema '{schema_name}': {task.error}")
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
    

    
    def handle_table_creation(self, table_name):
        """Gère la création d'une nouvelle table dans PostgreSQL"""
        try:
            # Récupérer le schéma courant
            current_row = self.mapping_table.currentRow()
            schema = 'public' # défaut
            
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
            QMessageBox.critical(self, "Auto Map Error", f"Failed to auto-map: {str(e)}")
    
    def get_current_mappings(self):
        """Récupère les mappings actuels depuis les ComboBox"""
        mappings = []
        row_count = self.mapping_table.rowCount()
        
        for row in range(row_count):
            # Récupérer les valeurs des ComboBox
            layer_combo = self.mapping_table.cellWidget(row, 0)
            schema_combo = self.mapping_table.cellWidget(row, 1)
            table_combo = self.mapping_table.cellWidget(row, 2)
            
            if (isinstance(layer_combo, QComboBox) and 
                isinstance(schema_combo, QComboBox) and 
                isinstance(table_combo, QComboBox)):
                
                transformed = layer_combo.currentText().strip()
                schema = schema_combo.currentText().strip()
                table = table_combo.currentText().strip()
                
                # Vérifier que toutes les valeurs sont renseignées (et exclure les valeurs spéciales)
                if (transformed and schema and table and 
                    table != "+ Nouvelle table..." and
                    transformed != "" and schema != ""):
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
        from qgis.core import QgsProject, QgsVectorLayer

        params = dict(conn_params)
        params.setdefault("connect_timeout", 10)

        jobs = []
        for info in compatibility_info:
            layer_name = info["layer"]
            schema = info["schema"]
            table = info["table"]

            # Resolve layer on main thread (thread-safe: read-only)
            source_layer = None
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.name() == layer_name:
                    source_layer = lyr
                    break
            if not source_layer or not isinstance(source_layer, QgsVectorLayer):
                log_warning(f"Layer '{layer_name}' not resolvable, skipping")
                continue

            jobs.append({
                "schema": schema,
                "table": table,
                "layer": source_layer,
                "srid": source_layer.crs().postgisSrid(),
            })
        
        if not jobs:
            return False
        
        # Build and launch task
        task = PgExportTask(
            params,
            jobs,
            export_mode=export_mode,
            description=f"PostgreSQL export ({len(jobs)} table(s), mode={export_mode})",
        )
        
        # Track active task to prevent garbage collection
        self._active_export_task = task
        
        # Connect signals for progress feedback
        task.progressChanged.connect(
            lambda p: log_info(f"Export progress: {int(p)}%")
        )
        task.taskCompleted.connect(lambda: self._on_export_finished(task))
        task.taskTerminated.connect(lambda: self._on_export_finished(task))
        
        log_info(f"Launching async export of {len(jobs)} table(s)")
        QgsApplication.taskManager().addTask(task)
        return True
    
    def _on_export_finished(self, task):
        """Main thread callback when PgExportTask completes."""
        self._active_export_task = None
        if task.success_count > 0:
            log_success(
                f"PostgreSQL export complete: {task.success_count} table(s), "
                f"{task.total_inserted} record(s) inserted"
            )
        if task.fail_count > 0:
            log_critical(f"PostgreSQL export: {task.fail_count} table(s) failed")
        for err in task.errors[:10]:
            log_critical(err)
        # Save mappings after async completion
        try:
            self.save_mappings()
        except Exception as e:
            log_warning(f"Mapping save error: {e}")

    def _dispatch_update_export(self, compatibility_info, conn_params, update_config):
        """Dispatch update (UPSERT) export via PgExportTask in background.

        Resolves source layers on main thread, builds jobs with update_config
        attached, and launches PgExportTask with export_mode='update'.
        """
        from qgis.core import QgsProject, QgsVectorLayer

        params = dict(conn_params)
        params.setdefault("connect_timeout", 10)

        jobs = []
        for info in compatibility_info:
            layer_name = info.get("layer", "")
            schema = info.get("schema", "")
            table = info.get("table", "")

            source_layer = None
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.name() == layer_name:
                    source_layer = lyr
                    break
            if not source_layer or not isinstance(source_layer, QgsVectorLayer):
                log_warning(f"Update export: layer '{layer_name}' not resolvable, skipping")
                continue

            jobs.append({
                "schema": schema,
                "table": table,
                "layer": source_layer,
                "srid": source_layer.crs().postgisSrid(),
                "update_config": update_config,
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
        """Export vers PostgreSQL — async compatibility analysis via QgsTask.

        Launches PgCompatibilityTask in background. The confirmation dialog
        and export dispatch happen in _on_export_compatibility_analyzed (main thread).
        """
        try:
            mappings = self.get_current_mappings()

            if not mappings:
                QMessageBox.warning(self, "Warning", "Aucun mapping défini")
                return

            if not POSTGRESQL_AVAILABLE:
                QMessageBox.critical(self, "Erreur", "psycopg2 n'est pas installé")
                return

            if not self.config_widget:
                QMessageBox.critical(self, "Erreur", "Configuration PostgreSQL non disponible")
                return

            if self._active_export_task:
                log_warning("Export already in progress, skipping")
                return

            resolved = self._resolve_mappings_for_task(mappings)
            if not resolved:
                QMessageBox.warning(
                    self, "No Mappings",
                    "No valid table mappings could be resolved for export.",
                )
                return

            conn_params = self._build_conn_params()

            log_info(
                f"Launching async compatibility analysis for {len(resolved)} mapping(s)"
            )
            task = PgCompatibilityTask(
                conn_params,
                resolved,
                description=f"PG compatibility ({len(resolved)} table(s))",
            )
            if self._active_compat_task:
                self._active_compat_task.cancel()
            self._active_compat_task = task
            task.taskCompleted.connect(
                lambda: self._on_export_compatibility_analyzed(task, conn_params)
            )
            task.taskTerminated.connect(
                lambda: self._on_export_compatibility_analyzed(task, conn_params)
            )
            QgsApplication.taskManager().addTask(task)

        except Exception as e:
            log_critical(f"PostgreSQL export error: {str(e)}")
            QMessageBox.critical(self, "Export error", f"Export failed: {str(e)}")

    def _resolve_mappings_for_task(self, mappings):
        """Resolve QGIS layer references on main thread for PgCompatibilityTask.

        Returns a list of dicts with keys: layer_name, schema, table, layer.
        Layers not found or not vector are skipped with a warning log.
        """
        from qgis.core import QgsProject, QgsVectorLayer

        resolved = []
        for mapping in mappings:
            layer_name = mapping.get('transformed', '')
            schema = mapping.get('schema', '')
            table = mapping.get('table', '')

            source_layer = None
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.name() == layer_name:
                    source_layer = lyr
                    break

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

    def _on_export_compatibility_analyzed(self, task, conn_params):
        """Main-thread callback after PgCompatibilityTask finishes for export_to_postgresql."""
        self._active_compat_task = None

        if task.errors and not task.compatibility_info:
            log_critical(f"Compatibility analysis failed: {task.errors}")
            QMessageBox.critical(
                self, "Integration Error",
                f"Compatibility analysis failed:\n\n{task.errors[0]}",
            )
            return

        compatibility_info = task.compatibility_info
        if not compatibility_info:
            QMessageBox.warning(
                self, "Integration Error",
                "No tables could be prepared for integration.\n\n"
                "Possible causes:\n"
                "• Layer not found in QGIS project\n"
                "• PostgreSQL connection failed\n"
                "• Insufficient database permissions\n"
                "• Invalid schema/table names",
            )
            return

        for err in task.errors[:10]:
            log_warning(f"Compatibility: {err}")

        # Show confirmation dialog
        mapping_key = self._generate_mapping_key(compatibility_info)
        show_confirmation = self._should_show_confirmation_for_mapping(mapping_key)

        export_mode = "append"
        update_config = None

        if show_confirmation:
            available_schemas = list(self.available_schemas) if self.available_schemas else []
            confirm_dialog = IntegrationConfirmationDialog(compatibility_info, available_schemas, self)
            self.confirmation_dialog = confirm_dialog

            if confirm_dialog.exec() != DialogAccepted:
                QgsMessageLog.logMessage(
                    "Intégration annulée par l'utilisateur",
                    "Transformer", MsgInfo,
                )
                self.confirmation_dialog = None
                return

            export_mode = confirm_dialog.get_selected_export_mode()
            update_config = confirm_dialog.get_update_configuration()
            log_info(f"Export mode selected: {export_mode}")

            if update_config:
                log_info(f"Update configuration: {update_config}")

            self.dont_show_integration_mapping = confirm_dialog.dont_show_checkbox.isChecked()

            self._temp_detailed_mappings = []
            try:
                for tab_index in range(confirm_dialog.tabs.count()):
                    confirm_dialog.tabs.setCurrentIndex(tab_index)
                    complete_info = confirm_dialog.get_complete_mapping_info()
                    detailed = complete_info.get('mappings', [])
                    if detailed:
                        self._temp_detailed_mappings.extend(detailed)
            except Exception as e:
                log_warning(f"Error extracting detailed mappings: {str(e)}")

            if confirm_dialog.dont_show_again:
                self._save_confirmation_preference_for_mapping(mapping_key, False)

        # Dispatch based on mode
        if export_mode in ("append", "replace"):
            if self._dispatch_async_export(compatibility_info, conn_params, export_mode):
                log_info("Async export launched - UI remains responsive")
            else:
                log_warning("No eligible jobs for async export")
        elif export_mode == "update":
            self._dispatch_update_export(compatibility_info, conn_params, update_config)

        # Save mappings
        try:
            self.save_mappings()
        except Exception as e:
            log_warning(f"Mapping save error: {e}")

        if hasattr(self, 'confirmation_dialog'):
            self.confirmation_dialog = None
        if hasattr(self, '_temp_detailed_mappings'):
            self._temp_detailed_mappings = []
    
    def _perform_integration(self, table_info, export_mode="append", update_config=None):
        """Perform the actual table integration with detailed ETL logging
        
        Args:
            table_info: Information about the table to integrate
            export_mode: Export mode - "append", "replace", or "update"
            update_config: Configuration for update mode (join keys, spatial settings)
        """
        try:
            layer_name = table_info['layer']
            schema = table_info['schema']
            table = table_info['table']
            
            # Start integration with clear table identification
            log_info(f"Integrating table {schema}.{table} from layer '{layer_name}' (mode: {export_mode})")
            
            # Get the QGIS source layer
            project = QgsProject.instance()
            source_layer = None
            
            for layer in project.mapLayers().values():
                if layer.name() == layer_name:
                    source_layer = layer
                    break
                    
            if not source_layer:
                log_critical(f"Source layer '{layer_name}' not found in project")
                return False
                
            if not isinstance(source_layer, QgsVectorLayer):
                log_critical(f"Layer '{layer_name}' is not a vector layer")
                return False
            
            # Get source layer details for final summary
            feature_count = source_layer.featureCount()
            field_count = len(source_layer.fields())
            geom_type = QgsWkbTypes.geometryDisplayString(source_layer.geometryType())
            
            # Connect to PostgreSQL
            if not self.config_widget:
                log_critical("PostgreSQL configuration not available")
                return False
                
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 10,
            }
            
            # Test connection before integration
            try:
                conn = psycopg2.connect(**conn_params)
                cursor = conn.cursor()
            except psycopg2.Error as e:
                log_critical(f"Database connection failed: {str(e)}")
                return False
            
            # Check if table exists and prepare for data insertion
            try:
                cursor.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s", (schema, table))
                table_exists = cursor.fetchone()[0] > 0
                
                if not table_exists:
                    log_warning(f"Table {schema}.{table} does not exist - creating automatically")
                    cursor.close()
                    conn.close()
                    
                    # Auto-create table based on source layer structure
                    if not self._create_postgresql_table(schema, table, source_layer):
                        log_critical(f"Failed to create table {schema}.{table}")
                        return False
                    
                    # Reconnect after table creation
                    try:
                        conn = psycopg2.connect(**conn_params)
                        cursor = conn.cursor()
                        log_success(f"Table {schema}.{table} created successfully")
                    except psycopg2.Error as e:
                        log_critical(f"Reconnection failed after table creation: {str(e)}")
                        return False
                    
            except psycopg2.Error as e:
                log_critical(f"Failed to check target table: {str(e)}")
                cursor.close()
                conn.close()
                return False
            
            # **ARCHITECTURE CORRIGÉE** - Utiliser psycopg2 direct pour tous les modes
            
            # Mode Update : Utilise UPSERT SQL
            if export_mode == "update":
                log_info(f"Mode Update: Using UPSERT with join configuration")
                join_config = self._convert_existing_config_to_new_format(update_config)
                cursor.close()
                conn.close()
                return self._perform_flexible_upsert(table_info, conn_params, join_config)
            
            # Mode Replace : DELETE puis INSERT
            if export_mode == "replace":
                log_warning(f"Mode Replace: DELETING all records from {schema}.{table}")
                try:
                    cursor.execute(
                        sql.SQL("DELETE FROM {}.{}").format(
                            sql.Identifier(schema), sql.Identifier(table),
                        )
                    )
                    conn.commit()
                    log_info(f"All existing data deleted, inserting {source_layer.featureCount()} new records")
                except psycopg2.Error as e:
                    log_critical(f"Failed to delete existing records: {str(e)}")
                    cursor.close()
                    conn.close()
                    return False
            
            # Mode Append : INSERT direct (pas de DELETE)
            elif export_mode == "append":
                log_info(f"Mode Append: Adding {source_layer.featureCount()} new records to {schema}.{table}")
            
            # INSERT des features via psycopg2 (commun à Append et Replace)
            try:
                # Récupérer les champs de la table PostgreSQL
                cursor.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    AND column_name != 'geom'
                    ORDER BY ordinal_position
                """, (schema, table))
                
                pg_fields = [row[0] for row in cursor.fetchall()]
                source_fields = [f.name() for f in source_layer.fields()]
                
                # Champs valides (intersection)
                valid_fields = [f for f in source_fields if f in pg_fields]
                
                if not valid_fields:
                    log_critical(f"No matching fields between source and target table")
                    cursor.close()
                    conn.close()
                    return False
                
                # Construire la requête INSERT (safe: psycopg2.sql.Identifier)
                field_list = sql.SQL(', ').join(
                    [sql.Identifier(f) for f in valid_fields]
                )
                placeholders = sql.SQL(', ').join(
                    [sql.Placeholder()] * (len(valid_fields) + 1)
                )
                insert_query = sql.SQL(
                    "INSERT INTO {}.{} ({}, geom) VALUES ({})"
                ).format(
                    sql.Identifier(schema), sql.Identifier(table),
                    field_list, placeholders,
                )
                
                # Insérer les features
                inserted_count = 0
                for feat in source_layer.getFeatures():
                    geom = feat.geometry()
                    if not geom or geom.isNull():
                        continue
                    
                    # Valeurs des attributs (convertir QVariant -> Python native)
                    values = []
                    for f in valid_fields:
                        val = feat[f]
                        # Convert QVariant to Python native type
                        if val is None:
                            values.append(None)
                        elif isinstance(val, (int, float, str, bool)):
                            values.append(val)
                        else:
                            # QVariant or other QGIS types - convert to Python
                            try:
                                values.append(val if val else None)
                            except Exception:
                                values.append(str(val) if val else None)
                    
                    # Géométrie en WKT
                    geom_wkt = geom.asWkt()
                    
                    # Exécuter INSERT
                    cursor.execute(insert_query, values + [f'SRID={source_layer.crs().postgisSrid()};{geom_wkt}'])
                    inserted_count += 1
                
                conn.commit()
                log_success(f"Table {schema}.{table}: {inserted_count} records integrated successfully")
                cursor.close()
                conn.close()
                return True
                
            except psycopg2.Error as e:
                conn.rollback()
                log_critical(f"PostgreSQL error during INSERT: {str(e)}")
                cursor.close()
                conn.close()
                return False
                
        except Exception as e:
            log_critical(f"Integration error for {layer_name}: {str(e)}")
            return False
    
    def _analyze_table_compatibility(self, layer_name, schema, table):
        """Analyse the compatibility between a QGIS layer and a PostgreSQL table"""
        try:
            # Get the QGIS layer
            project = QgsProject.instance()
            source_layer = None
            
            for layer in project.mapLayers().values():
                if layer.name() == layer_name:
                    source_layer = layer
                    break
                    
            if not source_layer:
                QgsMessageLog.logMessage(f" Layer '{layer_name}' not found in QGIS project", "Transformer", MsgWarning)
                return None
                
            if not isinstance(source_layer, QgsVectorLayer):
                QgsMessageLog.logMessage(f" Layer '{layer_name}' is not a vector layer (type: {type(source_layer).__name__})", "Transformer", MsgWarning)
                return None
                
            # Informations de base
            table_info = {
                'layer': layer_name, # Clé changée pour correspondre à l'interface
                'schema': schema,
                'table': table,
                'geometry_compatible': False,
                'crs_compatible': False,
                'geometry_info': '',
                'crs_info': '',
                'matching_fields': 0,
                'total_fields': 0,
                'field_details': [],
                'source_fields': [],
                'dest_fields': [],
                'field_matches': {}
            }
            
            # Analyse the geometry and CRS of the source
            source_geom_type = source_layer.geometryType()
            source_crs = source_layer.crs()
            
            # Connect to PostgreSQL to analyze the target table
            target_info = self._get_postgresql_table_info(schema, table)
            
            # If the table does not exist, it's a new table to create
            if not target_info:
                QgsMessageLog.logMessage(f" Table {schema}.{table} does not exist - creating automatically for layer '{layer_name}'", "Transformer", MsgInfo)
                
                # Create the table based on the source layer structure
                if self._create_postgresql_table(schema, table, source_layer):
                    QgsMessageLog.logMessage(f"Table {schema}.{table} created successfully", "Transformer", MsgSuccess)
                    
                    # Now retrieve the information of the newly created table
                    target_info = self._get_postgresql_table_info(schema, table)
                    
                    if not target_info:
                        QgsMessageLog.logMessage(f" Failed to retrieve info for newly created table {schema}.{table}", "Transformer", MsgCritical)
                        return None
                else:
                    QgsMessageLog.logMessage(f" Failed to create table {schema}.{table} - check permissions and connection", "Transformer", MsgCritical)
                    return None
            
            if target_info:
                # Comparaison géométrique
                target_geom_type = target_info.get('geometry_type', '')
                source_geom_name = QgsWkbTypes.geometryDisplayString(source_geom_type)
                
                # Vérification de compatibilité géométrique
                geom_compatible = self._check_geometry_compatibility(source_layer, target_geom_type)
                
                # If the geometry types do not match, recreate the table
                if not geom_compatible:
                    QgsMessageLog.logMessage(
                        f"Incompatibility detected for {schema}.{table}: {source_geom_name} vs {target_geom_type}",
                        "Transformer", MsgWarning
                    )
                    QgsMessageLog.logMessage(
                        f"Suppression et recréation de la table {schema}.{table} avec le bon type géométrique",
                        "Transformer", MsgInfo
                    )
                    
                    # Supprimer et recréer la table
                    if self._drop_and_recreate_table(schema, table, source_layer):
                        QgsMessageLog.logMessage(f"Table {schema}.{table} recreated successfully", "Transformer", MsgSuccess)
                        
                        # Retrieve the new information
                        target_info = self._get_postgresql_table_info(schema, table)
                        if target_info:
                            target_geom_type = target_info.get('geometry_type', '')
                            geom_compatible = True # Now compatible
                    else:
                        QgsMessageLog.logMessage(f"Failed to recreate table {schema}.{table}", "Transformer", MsgCritical)
                        return None
                
                table_info['geometry_compatible'] = geom_compatible
                table_info['geometry_info'] = f"Source: {source_geom_name}, Cible: {target_geom_type}"
                    
                # Comparaison CRS
                target_srid = target_info.get('srid', 0)
                source_srid = source_crs.postgisSrid()
                
                crs_compatible = (source_srid == target_srid) or target_srid == 0
                table_info['crs_compatible'] = crs_compatible
                table_info['crs_info'] = f"Source SRID: {source_srid}, Cible SRID: {target_srid}"
                
                # Comparaison fields - detailed format for the mapping interface
                source_fields_list = []
                for field in source_layer.fields():
                    source_fields_list.append({
                        'name': field.name(),
                        'type': field.typeName()
                    })
                    
                target_fields = target_info.get('fields', [])
                
                table_info['total_fields'] = len(source_fields_list)
                table_info['source_fields'] = source_fields_list
                table_info['dest_fields'] = target_fields
                
                # Automatic field mapping
                field_matches = {}
                matching_fields = 0
                field_details = []
                
                for source_field in source_fields_list:
                    source_field_name = source_field['name']
                    # Find a match in the target fields
                    field_match = self._find_field_match(source_field_name, target_fields)
                    
                    if field_match:
                        matching_fields += 1
                        field_matches[source_field_name] = field_match['name']
                        field_details.append({
                            'source_name': source_field_name,
                            'compatible': True,
                            'status': f"Correspond à '{field_match['name']}' ({field_match['type']})"
                        })
                    else:
                        field_details.append({
                            'source_name': source_field_name,
                            'compatible': False,
                            'status': "Aucune correspondance trouvée"
                        })
                        
                table_info['matching_fields'] = matching_fields
                table_info['field_details'] = field_details
                table_info['field_matches'] = field_matches
            else:
                table_info['geometry_info'] = "Table cible inaccessible"
                table_info['crs_info'] = "CRS non vérifiable"
                
            return table_info
            
        except Exception as e:
            import traceback
            QgsMessageLog.logMessage(f"Compatibility analysis failed for layer '{layer_name}' -> {schema}.{table}: {str(e)}", "Transformer", MsgCritical)
            QgsMessageLog.logMessage(f"Full error trace: {traceback.format_exc()}", "Transformer", MsgCritical)
            return None
            
    def _get_postgresql_table_info(self, schema, table):
        """Récupère les informations d'une table PostgreSQL"""
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
                cur.close()
                conn.close()
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
                    geom_column = geom_columns[0][0] # Take the first geometry column
                    
                    # Try to retrieve the type and SRID from PostGIS
                    try:
                        postgis_query = f"""
                            SELECT ST_GeometryType("{geom_column}"), ST_SRID("{geom_column}")
                            FROM "{schema}"."{table}" 
                            WHERE "{geom_column}" IS NOT NULL 
                            LIMIT 1
                        """
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
                } for field in fields_info if field[0] not in ['id', 'gid']] # Exclure les clés primaires auto
            }
            
            cur.close()
            conn.close()
            
            QgsMessageLog.logMessage(
                f"Table {schema}.{table}: géom={geom_type}, SRID={srid}, champs={len(table_info['fields'])}",
                "Transformer",
                MsgInfo
            )
            
            return table_info
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur récupération info table {schema}.{table}: {str(e)}", "Transformer", MsgWarning)
            return None
            
    def _check_geometry_compatibility(self, source_layer, target_geom_type):
        """Check the exact compatibility between geometry types"""
        # Get the exact WKB type of the source layer
        wkb_type = source_layer.wkbType()
        
        # Mapping of WKB types to PostGIS
        wkb_type_map = {
            QgsWkbTypes.Point: 'POINT',
            QgsWkbTypes.MultiPoint: 'MULTIPOINT',
            QgsWkbTypes.LineString: 'LINESTRING',
            QgsWkbTypes.MultiLineString: 'MULTILINESTRING',
            QgsWkbTypes.Polygon: 'POLYGON',
            QgsWkbTypes.MultiPolygon: 'MULTIPOLYGON',
            QgsWkbTypes.Point25D: 'POINTZ',
            QgsWkbTypes.MultiPoint25D: 'MULTIPOINTZ',
            QgsWkbTypes.LineString25D: 'LINESTRINGZ',
            QgsWkbTypes.MultiLineString25D: 'MULTILINESTRINGZ',
            QgsWkbTypes.Polygon25D: 'POLYGONZ',
            QgsWkbTypes.MultiPolygon25D: 'MULTIPOLYGONZ'
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
        """Crée une table PostgreSQL basée sur la structure d'une couche QGIS"""
        try:
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 10
            }
            
            conn = psycopg2.connect(**conn_params)
            cur = conn.cursor()
            
            # Analyze the real content of geometries to detect the exact type
            actual_geom_types = set()
            feature_count = 0
            
            for feature in source_layer.getFeatures():
                if feature_count >= 10: # Limiter à 10 features pour l'analyse
                    break
                    
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        actual_wkb_type = geom.wkbType()
                        actual_geom_types.add(actual_wkb_type)
                        feature_count += 1
            
            # Get the declared WKB type and the detected type
            wkb_type = source_layer.wkbType()
            detected_wkb_type = wkb_type
            
            # Detect MultiLineString cases even if the layer is declared LineString
            if QgsWkbTypes.MultiLineString in actual_geom_types or QgsWkbTypes.MultiLineString25D in actual_geom_types:
                detected_wkb_type = QgsWkbTypes.MultiLineString
                QgsMessageLog.logMessage(f" CORRECTION: Type déclaré={QgsWkbTypes.displayString(wkb_type)}, Type réel détecté=MultiLineString", "Transformer", MsgInfo)
            elif QgsWkbTypes.MultiPoint in actual_geom_types or QgsWkbTypes.MultiPoint25D in actual_geom_types:
                detected_wkb_type = QgsWkbTypes.MultiPoint
                QgsMessageLog.logMessage(f" CORRECTION: Type déclaré={QgsWkbTypes.displayString(wkb_type)}, Type réel détecté=MultiPoint", "Transformer", MsgInfo)
            elif QgsWkbTypes.MultiPolygon in actual_geom_types or QgsWkbTypes.MultiPolygon25D in actual_geom_types:
                detected_wkb_type = QgsWkbTypes.MultiPolygon
                QgsMessageLog.logMessage(f" CORRECTION: Type déclaré={QgsWkbTypes.displayString(wkb_type)}, Type réel détecté=MultiPolygon", "Transformer", MsgInfo)
            
            # Override the declared type with the detected real type
            if detected_wkb_type != wkb_type:
                wkb_type = detected_wkb_type
                QgsMessageLog.logMessage(f"Using the real geometry type: {QgsWkbTypes.displayString(wkb_type)}", "Transformer", MsgSuccess)
            
            # Map WKB types to PostgreSQL with exact types
            wkb_type_map = {
                QgsWkbTypes.Point: 'POINT',
                QgsWkbTypes.MultiPoint: 'MULTIPOINT',
                QgsWkbTypes.LineString: 'LINESTRING',
                QgsWkbTypes.MultiLineString: 'MULTILINESTRING',
                QgsWkbTypes.Polygon: 'POLYGON',
                QgsWkbTypes.MultiPolygon: 'MULTIPOLYGON',
                QgsWkbTypes.Point25D: 'POINTZ',
                QgsWkbTypes.MultiPoint25D: 'MULTIPOINTZ',
                QgsWkbTypes.LineString25D: 'LINESTRINGZ',
                QgsWkbTypes.MultiLineString25D: 'MULTILINESTRINGZ',
                QgsWkbTypes.Polygon25D: 'POLYGONZ',
                QgsWkbTypes.MultiPolygon25D: 'MULTIPOLYGONZ'
            }
            
            pg_geom_type = wkb_type_map.get(wkb_type)
            
            # Fallback to types MULTI if the exact type is not found
            if not pg_geom_type:
                geom_type = source_layer.geometryType()
                pg_geom_type = get_pg_geom_type(geom_type)
            
            # Get the SRID
            srid = source_layer.crs().postgisSrid()
            
            # Build the CREATE TABLE query (safe: psycopg2.sql.Identifier)
            col_defs = [sql.SQL('id SERIAL PRIMARY KEY')]
            
            # Add the fields
            fields = source_layer.fields()
            
            for field in fields:
                field_name = field.name()
                field_type = field.type()
                
                # Mapping QGIS types to PostgreSQL (typeName-based for Qt5/Qt6 compat)
                type_name = field.typeName().lower()
                if type_name in ('string', 'varchar', 'text', 'char'):
                    declared_length = field.length() if field.length() > 0 else 50
                    max_real_length = 0
                    
                    sample_count = 0
                    for feature in source_layer.getFeatures():
                        if sample_count >= 100:
                            break
                        val = feature[field_name]
                        if val and isinstance(val, str):
                            max_real_length = max(max_real_length, len(val))
                        sample_count += 1
                    
                    optimal_length = max(declared_length, max_real_length, 50)
                    
                    if max_real_length > declared_length * 2 and max_real_length > 100:
                        pg_type = 'TEXT'
                        QgsMessageLog.logMessage(
                            f"Field '{field_name}': Using TEXT (real data: {max_real_length} chars, declared: {declared_length})",
                            "Transformer", MsgInfo
                        )
                    else:
                        pg_type = f'VARCHAR({optimal_length})'
                elif type_name in ('integer', 'int', 'int4', 'int2'):
                    pg_type = 'INTEGER'
                elif type_name in ('integer64', 'int8', 'longlong'):
                    pg_type = 'BIGINT'
                elif type_name in ('real', 'double', 'float', 'numeric'):
                    pg_type = 'DOUBLE PRECISION'
                elif type_name == 'date':
                    pg_type = 'DATE'
                elif type_name in ('datetime', 'timestamp'):
                    pg_type = 'TIMESTAMP'
                elif type_name in ('bool', 'boolean'):
                    pg_type = 'BOOLEAN'
                else:
                    pg_type = 'TEXT'
                
                col_defs.append(
                    sql.SQL('{} ' + pg_type).format(sql.Identifier(field_name))
                )
            
            # Add the geometry column
            if srid > 0:
                geom_col = sql.SQL(f'geom GEOMETRY({pg_geom_type}, {srid})')
            else:
                geom_col = sql.SQL(f'geom GEOMETRY({pg_geom_type})')
            col_defs.append(geom_col)
            
            create_sql = sql.SQL(
                'CREATE TABLE IF NOT EXISTS {}.{} (\n{}\n)'
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table_name),
                sql.SQL(',\n').join(col_defs),
            )
            
            # Create the table
            cur.execute(create_sql)
            
            # Create the spatial index
            index_name = f'idx_{table_name}_geom'
            index_sql = sql.SQL(
                'CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST (geom)'
            ).format(
                sql.Identifier(index_name),
                sql.Identifier(schema),
                sql.Identifier(table_name),
            )
            cur.execute(index_sql)
            
            conn.commit()
            cur.close()
            conn.close()
            
            QgsMessageLog.logMessage(
                f"Table {schema}.{table_name} created with {len(col_defs) - 2} fields and geometry {pg_geom_type} (SRID: {srid})",
                "Transformer", MsgSuccess
            )
            
            return True
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur creation table {schema}.{table_name}: {str(e)}", "Transformer", MsgCritical)
            try:
                conn.rollback()
                cur.close()
                conn.close()
            except Exception as cleanup_exc:
                QgsMessageLog.logMessage(f"Connection cleanup failed after table creation error: {cleanup_exc}", "Transformer", MsgWarning)
            return False
    
    def _drop_and_recreate_table(self, schema, table_name, source_layer):
        """Drop and recreate a PostgreSQL table with the correct structure"""
        try:
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 10
            }
            
            conn = psycopg2.connect(**conn_params)
            cur = conn.cursor()
            
            # Drop the existing table (safe: psycopg2.sql.Identifier)
            drop_sql = sql.SQL(
                'DROP TABLE IF EXISTS {}.{} CASCADE'
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table_name),
            )
            cur.execute(drop_sql)
            
            QgsMessageLog.logMessage(f" Table {schema}.{table_name} dropped", "Transformer", MsgInfo)
            
            conn.commit()
            cur.close()
            conn.close()
            
            # Recreate the table with the correct structure
            return self._create_postgresql_table(schema, table_name, source_layer)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error dropping table {schema}.{table_name}: {str(e)}", "Transformer", MsgCritical)
            try:
                conn.rollback()
                cur.close()
                conn.close()
            except Exception as cleanup_exc:
                QgsMessageLog.logMessage(f"Connection cleanup failed after table drop error: {cleanup_exc}", "Transformer", MsgWarning)
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
        tables.sort() # Assurer l'ordre pour cohérence
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
                    return mapping_prefs.get(mapping_key, True) # Par défaut: afficher
            else:
                return True # Default to showing confirmation
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
                layer = new_mapping['layer']
                schema = new_mapping['schema']
                table = new_mapping['table']
                
                # Check if this mapping already exists
                found = False
                for existing_mapping in existing_detailed:
                    if (existing_mapping.get('layer') == layer and 
                        existing_mapping.get('schema') == schema and 
                        existing_mapping.get('table') == table):
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
                            # Add mapping to UI
                            row = self.mapping_table.rowCount()
                            self.mapping_table.insertRow(row)
                            
                            self.mapping_table.setItem(row, 0, QTableWidgetItem(layer_name))
                            
                            schema_combo = QComboBox()
                            schema_combo.addItems(self.available_schemas)
                            schema_combo.setCurrentText(schema)
                            self.mapping_table.setCellWidget(row, 1, schema_combo)
                            
                            table_combo = QComboBox()
                            table_combo.setCurrentText(table)
                            self.mapping_table.setCellWidget(row, 2, table_combo)
                            
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
                    continue # Skip incomplete mappings
                
                # Create unique key and label
                label = f"{layer_name} → {schema}.{table}"
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
                "Select Mapping to Load",
                "Choose a table mapping:",
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
                
                row = self.mapping_table.rowCount()
                self.mapping_table.insertRow(row)
                
                self.mapping_table.setItem(row, 0, QTableWidgetItem(layer_name))
                
                # Schema combo
                schema_combo = QComboBox()
                schema_combo.addItems(self.available_schemas)
                schema_combo.setCurrentText(schema)
                self.mapping_table.setCellWidget(row, 1, schema_combo)
                
                # Table combo
                table_combo = QComboBox()
                table_combo.setCurrentText(table)
                self.mapping_table.setCellWidget(row, 2, table_combo)
                
                QgsMessageLog.logMessage(f"Loaded mapping: {label}", "Transformer", MsgSuccess)
                
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

        # Configuration widget on top (size policy = Maximum vertical, takes only what it needs)
        self.config_widget = PostgreSQLConfigWidget()

        # Mapping widget below (claims remaining vertical space)
        self.mapping_widget = PostgreSQLMappingWidget()
        self.mapping_widget.setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Expanding)

        # Link widgets so mapping can access config
        self.mapping_widget.config_widget = self.config_widget

        layout.addWidget(self.config_widget)
        layout.addWidget(self.mapping_widget, 1)
    
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
