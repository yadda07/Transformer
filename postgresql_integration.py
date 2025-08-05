# -*- coding: utf-8 -*-
"""
PostgreSQL integration module for Transformer
Mapping & export of transformed tables to PostgreSQL
"""

import os
import json
from typing import Dict, List, Optional, Any
from pathlib import Path

from qgis.PyQt.QtCore import Qt, pyqtSignal, QVariant
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QCheckBox, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QSplitter,
    QFrame, QScrollArea, QTabWidget, QTreeWidget, QTreeWidgetItem, QGridLayout,
    QApplication, QDesktopWidget, QPlainTextEdit, QProgressBar, QSlider, QCompleter,
    QInputDialog, QSizePolicy
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QTimer, QStringListModel
from qgis.PyQt.QtGui import QFont, QPixmap, QIcon, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsDataSourceUri, QgsCredentials, QgsMessageLog, Qgis,
    QgsApplication, QgsAuthManager, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsField, QgsFields, QgsFeature, QgsGeometry, QgsPointXY, QgsWkbTypes, QgsExpression,
    QgsExpressionContext, QgsExpressionContextUtils, QgsFeatureRequest, QgsSettings,
    QgsCoordinateTransform, QgsCoordinateTransformContext, QgsVectorLayerExporter
)
from qgis.gui import QgsMessageBar
from qgis.utils import iface
import json
import os
import logging
from datetime import datetime

# Import PostgreSQL dependencies
try:
    import psycopg2
    from psycopg2 import sql
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    QgsMessageLog.logMessage("psycopg2 not available. PostgreSQL features will be limited.", "Transformer", Qgis.Warning)


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
        self.setWindowTitle("PostgreSQL Mapping")
        self.setModal(True)
        
        # Optimized size for the mapping table
        self.resize(1100, 750)
        self.setMinimumSize(1000, 650)
        
        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(15)
        
        # Title and instructions
        title_label = QLabel("<h2 style='color: #2c3e50; margin-bottom: 5px;'>Mapping fields for PostgreSQL integration</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        subtitle_label = QLabel("<p style='color: #7f8c8d; font-size: 11pt; margin-top: 0;'>Verify and modify the automatic field mapping if necessary</p>")
        subtitle_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # Tabs for each layer
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #bdc3c7;
                border-radius: 5px;
            }
            QTabBar::tab {
                background-color: #ecf0f1;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        
        # Create a tab for each layer
        for i, info in enumerate(self.compatibility_info):
            tab_widget = self._create_field_mapping_table(info)
            self.tabs.addTab(tab_widget, f"{info['layer']}")
        
        layout.addWidget(self.tabs)
        
        # Statistiques de mapping
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 5px;
                padding: 8px 12px;
                font-size: 11pt;
                color: #495057;
            }
        """)
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        
        # Quick action buttons
        self.auto_map_btn = QPushButton("Auto-mapping")
        self.clear_btn = QPushButton("Clear all")
        self.add_field_btn = QPushButton("Add custom field")
        
        # Native QGIS style for all buttons
        qgis_button_style = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8f9fa, stop:1 #e9ecef);
                color: #495057;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 9pt;
                font-weight: 500;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #adb5bd;
            }
            QPushButton:pressed {
                background-color: #dee2e6;
                border-color: #adb5bd;
            }
        """
        
        self.auto_map_btn.setStyleSheet(qgis_button_style)
        self.clear_btn.setStyleSheet(qgis_button_style)
        self.add_field_btn.setStyleSheet(qgis_button_style)
        
        stats_layout.addWidget(self.auto_map_btn)
        stats_layout.addWidget(self.clear_btn)
        stats_layout.addWidget(self.add_field_btn)
        layout.addLayout(stats_layout)
        
        # Case à cocher "Ne plus afficher"
        checkbox_container = QHBoxLayout()
        self.dont_show_checkbox = QCheckBox("Do not show this window for future integrations")
        self.dont_show_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 10pt;
                color: #34495e;
                padding: 5px;
            }
        """)
        checkbox_container.addWidget(self.dont_show_checkbox)
        checkbox_container.addStretch()
        layout.addLayout(checkbox_container)
        
        # Main buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        self.reset_btn = QPushButton("Reset")
        self.cancel_btn = QPushButton("Cancel")
        self.proceed_btn = QPushButton("Apply mapping")
        
        # Native QGIS style for main buttons
        self.reset_btn.setMinimumSize(130, 35)
        self.cancel_btn.setMinimumSize(120, 35)
        self.proceed_btn.setMinimumSize(180, 35)
        
        # Native QGIS style for main buttons
        main_button_style = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8f9fa, stop:1 #e9ecef);
                color: #495057;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 10pt;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #adb5bd;
            }
            QPushButton:pressed {
                background-color: #dee2e6;
            }
        """
        
        self.reset_btn.setStyleSheet(main_button_style)
        self.cancel_btn.setStyleSheet(main_button_style)
        self.proceed_btn.setStyleSheet(main_button_style)
        
        buttons_layout.addWidget(self.reset_btn)
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
        
        # En-tête avec informations sur la couche
        header_layout = QHBoxLayout()
        
        layer_info = QLabel(f"<b>Couche:</b> {info['layer']} → <b>Destination:</b> {info['schema']}.{info['table']}")
        layer_info.setStyleSheet("""
            QLabel {
                background-color: #e8f4fd;
                border: 1px solid #bee5eb;
                border-radius: 5px;
                padding: 8px 12px;
                font-size: 12pt;
                color: #0c5460;
            }
        """)
        header_layout.addWidget(layer_info)
        layout.addLayout(header_layout)
        
        # Table for field mapping
        table = QTableWidget()
        table.setColumnCount(7)  # Add a column for deletion
        table.setHorizontalHeaderLabels([
            "Source field", 
            "Source type", 
            "Destination field", 
            "Destination type", 
            "Forced type", 
            "Status",
            "Action"
        ])
        
        # Table style
        table.setStyleSheet("""
            QTableWidget {
                gridline-color: #bdc3c7;
                background-color: white;
                alternate-background-color: #f8f9fa;
                selection-background-color: #3498db;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #ecf0f1;
            }
            QHeaderView::section {
                background-color: #34495e;
                color: white;
                padding: 10px;
                border: none;
                font-weight: bold;
            }
        """)
        
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        
        # Column configuration
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Source field
        header.setSectionResizeMode(1, QHeaderView.Fixed)  # Source type
        header.setSectionResizeMode(2, QHeaderView.Stretch) # Destination field (modifiable)
        header.setSectionResizeMode(3, QHeaderView.Fixed)  # Destination type
        header.setSectionResizeMode(4, QHeaderView.Fixed)  # Forced type
        header.setSectionResizeMode(5, QHeaderView.Fixed)  # Status
        header.setSectionResizeMode(6, QHeaderView.Fixed)  # Action
        
        # Column widths
        table.setColumnWidth(0, 160)  # Source field
        table.setColumnWidth(1, 90)   # Source type
        table.setColumnWidth(3, 110)  # Destination type
        table.setColumnWidth(4, 110)  # Forced type
        table.setColumnWidth(5, 60)   # Status
        table.setColumnWidth(6, 70)   # Action
        
        # Field source and destination retrieval
        source_fields = info.get('source_fields', [])
        dest_fields = info.get('dest_fields', [])
        field_matches = info.get('field_matches', {})
        
        # Add rows for each source field
        table.setRowCount(len(source_fields))
        
        for row, source_field in enumerate(source_fields):
            # Source field (read-only)
            source_item = QTableWidgetItem(source_field['name'])
            source_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            
            # Set icon only if it exists
            icon = self._get_field_icon(source_field['type'])
            if icon:
                source_item.setIcon(icon)
                
            table.setItem(row, 0, source_item)
            
            # Source type (read-only)
            type_item = QTableWidgetItem(source_field['type'])
            type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
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
            dest_type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self._update_dest_type(dest_type_item, dest_combo.currentData(), dest_fields)
            table.setItem(row, 3, dest_type_item)
            
            # Forced type (ComboBox modifiable)
            forced_type_combo = QComboBox()
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
            status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self._update_compatibility_status(status_item, source_field, dest_combo.currentData(), dest_fields)
            table.setItem(row, 5, status_item)
            
            # Delete button (only for non-essential fields)
            delete_btn = QPushButton("Suppr")
            delete_btn.setMaximumSize(60, 25)
            delete_btn.setToolTip("Supprimer ce champ du mapping")
            delete_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8f9fa, stop:1 #e9ecef);
                    color: #495057;
                    border: 1px solid #ced4da;
                    border-radius: 3px;
                    font-size: 9pt;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e9ecef, stop:1 #dee2e6);
                    border-color: #dc3545;
                }
            """)
            
            # For normal source fields, allow deletion
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
        """Return an appropriate icon for the field type"""
        # This method could be extended with real icons
        return None
    
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
            f"<b>{layer_key}:</b> "
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
        source_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        source_item.setBackground(QColor(255, 255, 200))  # Jaune clair pour les champs personnalisés
        table.setItem(row, 0, source_item)
        
        # Type source
        type_item = QTableWidgetItem("Custom")
        type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
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
        dest_type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
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
        status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        status_item.setToolTip(f"Custom field: {field_name} = '{default_value}' ({pg_type})")
        status_item.setBackground(QColor(255, 255, 200))
        table.setItem(row, 5, status_item)
        
        # Delete button for custom fields
        delete_btn = QPushButton("Suppr")
        delete_btn.setMaximumSize(60, 25)
        delete_btn.setToolTip("Delete this custom field")
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border-color: #aaa;
            }
        """)
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
        
        QMessageBox.information(self, "Field added", 
            f"Custom field '{field_name}' added successfully!\n"
            f"Default value: '{default_value}'\n"
            f"Type: {pg_type}")
    
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
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
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
    
    def get_complete_mapping_info(self):
        """Récupère toutes les informations de mapping : champs, types forcés, champs personnalisés"""
        complete_info = {}
        
        for layer_key, widgets in self.mapping_widgets.items():
            table = widgets['table']
            
            mapping_info = {
                'field_mapping': {},
                'forced_types': {},
                'custom_fields': getattr(widgets, 'custom_fields', [])
            }
            
            for row in range(table.rowCount()):
                # Retrieve the widgets of the row
                source_item = table.item(row, 0)
                dest_combo = table.cellWidget(row, 2)
                forced_type_combo = table.cellWidget(row, 4)
                
                if source_item and dest_combo and dest_combo.currentData():
                    source_field_name = source_item.text()
                    # Clean the name for custom fields
                    if source_field_name.startswith("[CUSTOM] "):
                        source_field_name = source_field_name.replace("[CUSTOM] ", "")
                    
                    dest_field_name = dest_combo.currentData()
                    mapping_info['field_mapping'][source_field_name] = dest_field_name
                    
                    # Retrieve the forced type if defined
                    if forced_type_combo and forced_type_combo.currentText() != "<Auto>":
                        mapping_info['forced_types'][source_field_name] = forced_type_combo.currentText()
            
            complete_info[layer_key] = mapping_info
        
        return complete_info
    
    def _on_dont_show_toggled(self, checked):
        """Handle the 'do not show again' checkbox"""
        self.dont_show_again = checked
        
    def _format_compatibility_info(self):
        """Format compatibility information in HTML"""
        html = """
        <div style='font-family: Arial, sans-serif; font-size: 12pt; line-height: 1.4;'>
        <style>
            .compatibility-item {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .item-header {
                color: #2c3e50;
                font-size: 14pt;
                font-weight: bold;
                margin-bottom: 15px;
                padding-bottom: 8px;
                border-bottom: 2px solid #3498db;
            }
            .status-row {
                margin: 8px 0;
                padding: 8px 0;
                display: flex;
                align-items: center;
            }
            .status-icon {
                font-size: 16px;
                margin-right: 8px;
                min-width: 20px;
            }
            .status-label {
                font-weight: bold;
                margin-right: 8px;
                min-width: 120px;
            }
            .field-details {
                margin-top: 15px;
                padding: 10px;
                background-color: #f8f9fa;
                border-left: 4px solid #3498db;
                border-radius: 4px;
            }
            .field-list {
                list-style: none;
                padding: 0;
                margin: 10px 0;
            }
            .field-list li {
                padding: 5px 0;
                border-bottom: 1px dotted #bdc3c7;
            }
            .field-list li:last-child {
                border-bottom: none;
            }
        </style>
        """
        
        for table_info in self.compatibility_info:
            layer_name = table_info.get('layer_name', 'Unknown')
            schema = table_info.get('schema', 'Unknown')
            table = table_info.get('table', 'Unknown')
            
            html += f"<div class='compatibility-item'>"
            html += f"<div class='item-header'>{layer_name} → {schema}.{table}</div>"
            
            # Geometry compatibility
            geom_compatible = table_info.get('geometry_compatible', False)
            geom_icon = "✅" if geom_compatible else "❌"
            html += f"<div class='status-row'>"
            html += f"<span class='status-icon'>{geom_icon}</span>"
            html += f"<span class='status-label'>Geometry:</span>"
            html += f"<span>{table_info.get('geometry_info', 'Not verified')}</span>"
            html += f"</div>"
            
            # CRS compatibility
            crs_compatible = table_info.get('crs_compatible', False)
            crs_icon = "✅" if crs_compatible else "⚠️"
            html += f"<div class='status-row'>"
            html += f"<span class='status-icon'>{crs_icon}</span>"
            html += f"<span class='status-label'>CRS:</span>"
            html += f"<span>{table_info.get('crs_info', 'Not verified')}</span>"
            html += f"</div>"
            
            # Correspondance des champs
            matching_fields = table_info.get('matching_fields', 0)
            total_fields = table_info.get('total_fields', 0)
            field_percentage = (matching_fields / total_fields * 100) if total_fields > 0 else 0
            
            if field_percentage >= 80:
                field_icon = "✅"
            elif field_percentage >= 50:
                field_icon = "⚠️"
            else:
                field_icon = "❌"
                
            html += f"<div class='status-row'>"
            html += f"<span class='status-icon'>{field_icon}</span>"
            html += f"<span class='status-label'>Champs correspondants:</span>"
            html += f"<span>{matching_fields}/{total_fields} ({field_percentage:.1f}%)</span>"
            html += f"</div>"
            
            # Détails des champs
            field_details = table_info.get('field_details', [])
            if field_details:
                html += "<div class='field-details'>"
                html += "<strong style='color: #2c3e50;'>📋 Détails des champs:</strong>"
                html += "<ul class='field-list'>"
                for field in field_details:
                    status_icon = "✅" if field.get('compatible', False) else "❌"
                    html += f"<li><span class='status-icon'>{status_icon}</span><strong>{field.get('source_name', '')}:</strong> {field.get('status', '')}</li>"
                html += "</ul></div>"
                
            html += "</div>"  # End of compatibility-item
            
        html += "</div>"
        return html
        
    def _on_dont_show_toggled(self, checked):
        """Handle the change of the 'Do not show again' checkbox"""
        self.dont_show_again = checked
    
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
                QgsMessageLog.logMessage("Table de mapping non trouvée dans l'onglet", "Transformer", Qgis.Warning)
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
                forced_type = "<Auto>"  # Valeur par défaut
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
                "Transformer", Qgis.Info
            )
            
            return {
                'field_mapping': field_mapping,
                'forced_types': forced_types,
                'custom_fields': custom_fields  # À implémenter plus tard si nécessaire
            }
            
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Erreur lors de l'extraction des informations de mapping: {str(e)}", 
                "Transformer", Qgis.Warning
            )
            return {'field_mapping': {}, 'forced_types': {}, 'custom_fields': {}}

class PostgreSQLConfigWidget(QWidget):
    """Minimal PostgreSQL configuration"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Basic PostgreSQL setup"""
        layout = QVBoxLayout()
        
        # Config group
        config_group = QGroupBox("PostgreSQL Configuration")
        config_layout = QFormLayout()
        
        # Config fields
        self.host_edit = QLineEdit("localhost")
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(5432)
        self.database_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        
        config_layout.addRow("Host:", self.host_edit)
        config_layout.addRow("Port:", self.port_edit)
        config_layout.addRow("Database:", self.database_edit)
        config_layout.addRow("Username:", self.username_edit)
        config_layout.addRow("Password:", self.password_edit)
        
        # Connection status indicator
        status_layout = QHBoxLayout()
        self.status_indicator = QLabel("●")
        self.status_indicator.setFixedSize(12, 12)
        self.status_indicator.setAlignment(Qt.AlignCenter)
        self.status_indicator.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: bold;
                color: #999999;
                border-radius: 8px;
                background-color: rgba(153, 153, 153, 0.1);
            }
        """)
        
        self.status_label = QLabel("Not tested")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #666666;
                font-style: italic;
                padding-left: 5px;
            }
        """)
        
        status_layout.addWidget(self.status_indicator)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        
        config_layout.addRow("Status:", status_layout)
        
        # Boutons
        buttons_layout = QHBoxLayout()
        self.test_connection_btn = QPushButton("Test Connection")
        self.save_config_btn = QPushButton("Save Config")
        self.load_config_btn = QPushButton("Load Config")
        
        buttons_layout.addWidget(self.test_connection_btn)
        buttons_layout.addWidget(self.save_config_btn)
        buttons_layout.addWidget(self.load_config_btn)
        buttons_layout.addStretch()
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        
        # Connexions
        self.test_connection_btn.clicked.connect(self.test_connection)
        self.save_config_btn.clicked.connect(self.save_config)
        self.load_config_btn.clicked.connect(self.load_config)
        
        # Initialize status
        self.update_connection_status("not_tested")
    
    def update_connection_status(self, status):
        """Update connection status indicator
        
        Args:
            status (str): 'connected' (green), 'error' (orange), 'failed' (red), 'not_tested' (gray)
        """
        if status == "connected":
            self.status_indicator.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #28a745;
                }
            """)
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    color: #28a745;
                    font-weight: bold;
                    padding-left: 5px;
                }
            """)
        elif status == "error":
            self.status_indicator.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #ff8c00;
                }
            """)
            self.status_label.setText("Connection issue")
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    color: #ff8c00;
                    font-weight: bold;
                    padding-left: 5px;
                }
            """)
        elif status == "failed":
            self.status_indicator.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #dc3545;
                }
            """)
            self.status_label.setText("Invalid credentials")
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    color: #dc3545;
                    font-weight: bold;
                    padding-left: 5px;
                }
            """)
        else:  # not_tested
            self.status_indicator.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #999999;
                }
            """)
            self.status_label.setText("Not tested")
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    color: #666666;
                    font-style: italic;
                    padding-left: 5px;
                }
            """)
    
    def test_connection(self):
        """Quick PostgreSQL connection test with visual feedback"""
        if not POSTGRESQL_AVAILABLE:
            self.update_connection_status("failed")
            QgsMessageLog.logMessage("psycopg2 is not installed", "Transformer", Qgis.Warning)
            return False
        
        try:
            # Paramètres de connexion
            conn_params = {
                'host': self.host_edit.text() or 'localhost',
                'port': self.port_edit.value(),
                'database': self.database_edit.text(),
                'user': self.username_edit.text(),
                'password': self.password_edit.text(),
                'connect_timeout': 3  # Quick timeout
            }
            
            # Required fields validation
            if not conn_params['database'] or not conn_params['user']:
                self.update_connection_status("failed")
                QgsMessageLog.logMessage("Database name and username are required", "Transformer", Qgis.Warning)
                return False
            
            # Quick connection test - just open/close
            conn = psycopg2.connect(**conn_params)
            conn.close()
            
            # Update status to connected
            self.update_connection_status("connected")
            
            # Success log & minimal visual feedback
            QgsMessageLog.logMessage(f"PostgreSQL connection successful to {conn_params['database']}@{conn_params['host']}:{conn_params['port']}", "Transformer", Qgis.Success)
            
            # Quick visual feedback in QGIS status bar
            from qgis.utils import iface
            if iface:
                iface.messageBar().pushMessage("PostgreSQL", "Connection successful!", level=Qgis.Success, duration=2)
            
            # Auto-trigger schema refresh
            self.auto_refresh_schemas()
            
            return True
            
        except psycopg2.Error as e:
            # Check if it's an authentication/credentials error or connection issue
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ['authentication', 'password', 'role', 'does not exist', 'permission denied']):
                self.update_connection_status("failed")
            else:
                self.update_connection_status("error")
            
            QgsMessageLog.logMessage(f"PostgreSQL connection failed: {str(e)}", "Transformer", Qgis.Critical)
            # Visual feedback for error
            from qgis.utils import iface
            if iface:
                iface.messageBar().pushMessage("PostgreSQL", f"Connection failed: {str(e)}", level=Qgis.Critical, duration=5)
            return False
        except Exception as e:
            self.update_connection_status("error")
            QgsMessageLog.logMessage(f"Connection error: {str(e)}", "Transformer", Qgis.Critical)
            from qgis.utils import iface
            if iface:
                iface.messageBar().pushMessage("PostgreSQL", f"Error: {str(e)}", level=Qgis.Critical, duration=5)
            return False
    
    def auto_refresh_schemas(self):
        """Auto refresh schemas after conn test"""
        # Trigger schema refresh in mapping widget
        # Find parent PostgreSQLIntegrationWidget
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'mapping_widget') and hasattr(parent_widget.mapping_widget, 'refresh_schemas'):
                parent_widget.mapping_widget.refresh_schemas()
                break
            parent_widget = parent_widget.parent()
    
    def save_config(self):
        """Save the conf"""
        config = {
            "host": self.host_edit.text(),
            "port": self.port_edit.value(),
            "database": self.database_edit.text(),
            "username": self.username_edit.text(),
            "password": self.password_edit.text()
        }
        
        # Save in plugin folder
        try:
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "transformer_postgresql.json")
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(self, "Success", "Configuration saved successfully")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save config: {str(e)}")
    
    def load_config(self):
        """Load saved configuration"""
        try:
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "transformer_postgresql.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
                self.host_edit.setText(config.get("host", "localhost"))
                self.port_edit.setValue(config.get("port", 5432))
                self.database_edit.setText(config.get("database", ""))
                self.username_edit.setText(config.get("username", ""))
                self.password_edit.setText(config.get("password", ""))
                
                QMessageBox.information(self, "Success", "Config loaded successfully")
            else:
                QMessageBox.warning(self, "Warning", "No saved conf found")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load config: {str(e)}")


class SearchableComboBox(QComboBox):
    """ComboBox w/ integrated search & QGIS native autocompletion"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(15)  # More visible items
        
        # Setup native QGIS autocompletion
        self.completer = QCompleter()
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)  # Search by content
        self.completer.setModelSorting(QCompleter.UnsortedModel)  # Keep original order
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        
        # Always show list on click
        self.setCompleter(self.completer)
        self.completer.setMaxVisibleItems(15)  # Same number as ComboBox
        
        # Store all available items
        self.all_items = []
        
        # Init completer & model safely
        self.completer = None
        self.model = None
        
        # Init completer after widget ready
        self._init_completer()
        
        # Connect signals for real-time search
        if self.lineEdit():
            self.lineEdit().textChanged.connect(self.on_text_changed)
    
    def _init_completer(self):
        """Safe completer initialization"""
        try:
            # Create model w/ empty list
            self.model = QStringListModel([])
            
            # Create completer with model
            self.completer = QCompleter(self.model)
            self.completer.setCompletionMode(QCompleter.PopupCompletion)
            self.completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.completer.setFilterMode(Qt.MatchContains)
            
            # Assign completer to widget
            self.setCompleter(self.completer)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Completer initialization error: {str(e)}", "Transformer", Qgis.Warning)
            # Fallback: no completer
            self.completer = None
            self.model = None
        
    def set_items(self, items):
        """Set available items"""
        self.all_items = items[:]
        self.clear()
        self.addItems(items)
        
        # Update model if available
        if self.model:
            try:
                self.model.setStringList(items)
            except Exception as e:
                QgsMessageLog.logMessage(f"Model update error: {str(e)}", "Transformer", Qgis.Warning)
        
    def on_text_changed(self, text):
        """Handle text changes for search"""
        if not text:
            # Empty text = show all items
            self.clear()
            self.addItems(self.all_items)
            return
            
        # Filter items containing text (case insensitive)
        filtered_items = [item for item in self.all_items if text.lower() in item.lower()]
        
        # Update dropdown list
        self.clear()
        self.addItems(filtered_items)
        
        # Update completer if available
        if self.model:
            try:
                self.model.setStringList(filtered_items)
            except Exception as e:
                QgsMessageLog.logMessage(f"Completer update error: {str(e)}", "Transformer", Qgis.Warning)
        
        # Reopen popup if needed
        if self.completer and filtered_items:
            try:
                if not self.completer.popup().isVisible():
                    self.completer.complete()
            except Exception as e:
                QgsMessageLog.logMessage(f"Popup open error: {str(e)}", "Transformer", Qgis.Warning)


class TableCreationComboBox(SearchableComboBox):
    """ComboBox w/ option to create new table & integrated search"""
    
    # Signal emitted when new table requested
    table_creation_requested = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)  # Inherits from SearchableComboBox (advanced search)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        
        # Existing tables list
        self.existing_tables = []
        self.addItem("")  # Default empty selection
        self.addItem("+ New table...")  # Creation option
        
        # Var to avoid auto-trigger
        self.user_interaction = False
        
        # Connect signal
        self.currentTextChanged.connect(self.on_text_changed)
        
        # Also connect activated signal (user click)
        self.activated[str].connect(self.on_user_selection)
        
    def set_tables(self, tables):
        """Set available tables"""
        self.existing_tables = tables[:]
        self.clear()
        self.addItem("")  # Empty selection by default
        self.addItem("+ New table...")  # Creation option
        self.addItems(tables)
        
    def on_user_selection(self, text):
        """Handle user selections (click on an option)"""
        if text == "+ New table...":
            # Ask for new table name
            self.create_new_table()
            
    def on_text_changed(self, text):
        """Handle text changes (keyboard input)"""
        if text and text not in ["+ New table...", ""]:
            # Check if it's new table name entered directly
            existing_tables = [self.itemText(i) for i in range(2, self.count())]
            if text not in existing_tables and text.strip():
                # New table name entered directly
                self.table_creation_requested.emit(text.strip())
                
    def create_new_table(self):
        """Open dialog to create new table"""
        table_name, ok = QInputDialog.getText(
            self, 
            "New table", 
            "New table name:",
            text=""
        )
        
        if ok and table_name.strip():
            # Add new table to list
            self.addItem(table_name.strip())
            self.setCurrentText(table_name.strip())
            self.table_creation_requested.emit(table_name.strip())
        else:
            # Revert to empty selection (first element)
            self.setCurrentIndex(0)


class PostgreSQLMappingWidget(QWidget):
    """Widget de mapping des tables transformées vers PostgreSQL"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_widget = None  # Référence vers le widget de config
        self.available_schemas = []
        self.available_tables = {}
        self.auto_connect = True  # Connexion automatique activée par défaut
        self.confirmation_dialog = None  # Boîte de dialogue de confirmation
        self._temp_detailed_mappings = []  # Cache temporaire pour les mappings détaillés
        self.setup_ui()
        # Vérifier si des mappings sont disponibles pour les couches actuelles
        QTimer.singleShot(500, self.check_auto_connect)
        self.mappings = []
    
    def setup_ui(self):
        """Interface de mapping"""
        layout = QVBoxLayout()
        
        # Titre
        title = QLabel("Table Mapping")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Option de connexion automatique
        self.auto_connect_check = QCheckBox("Connexion et mapping automatiques")
        self.auto_connect_check.setChecked(True)
        self.auto_connect_check.setToolTip("Active/désactive la connexion automatique à PostgreSQL et le chargement des mappings")
        layout.addWidget(self.auto_connect_check)
        self.auto_connect_check.toggled.connect(lambda state: setattr(self, 'auto_connect', state))
        
        # Tableau de mapping
        self.mapping_table = QTableWidget()
        self.mapping_table.setColumnCount(3)
        self.mapping_table.setHorizontalHeaderLabels(["Transformed", "Schema", "Table"])
        
        # Configuration du tableau
        header = self.mapping_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Stretch)
        
        layout.addWidget(self.mapping_table)
        
        # Boutons de contrôle
        buttons_layout = QHBoxLayout()
        self.add_mapping_btn = QPushButton("Add Mapping")
        self.remove_mapping_btn = QPushButton("Remove Selected")
        self.refresh_schemas_btn = QPushButton("Refresh Schemas")
        self.save_mappings_btn = QPushButton("Save Current")
        self.load_mappings_btn = QPushButton("Load Saved")
        self.export_btn = QPushButton("Export to PostgreSQL")
        
        buttons_layout.addWidget(self.add_mapping_btn)
        buttons_layout.addWidget(self.remove_mapping_btn)
        buttons_layout.addWidget(self.refresh_schemas_btn)
        buttons_layout.addWidget(self.save_mappings_btn)
        buttons_layout.addWidget(self.load_mappings_btn)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.export_btn)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
        
        # Connexions
        self.add_mapping_btn.clicked.connect(self.add_mapping)
        self.remove_mapping_btn.clicked.connect(self.remove_selected)
        self.refresh_schemas_btn.clicked.connect(self.refresh_schemas)
        self.save_mappings_btn.clicked.connect(self.save_mappings)
        self.load_mappings_btn.clicked.connect(self.load_mappings)
        self.export_btn.clicked.connect(self.export_to_postgresql)
    
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
            
            # Colonne 1: ComboBox avec les schémas PostgreSQL (Recherchable)
            schema_combo = SearchableComboBox()
            
            # Charger les schémas si possible
            if not self.available_schemas and self.config_widget:
                try:
                    self.refresh_schemas()
                except Exception:
                    pass  # Ignore les erreurs de connexion
            
            # Remplir la combobox des schémas avec modèle de recherche
            schema_items = [""]
            if self.available_schemas:
                schema_items.extend(self.available_schemas)
            else:
                schema_items.append("public")
            
            schema_combo.addItems(schema_items)
            model = QStringListModel(schema_items)
            schema_combo.completer.setModel(model)
            self.mapping_table.setCellWidget(row, 1, schema_combo)
            
            # Colonne 2: ComboBox avec les tables (Recherchable et avec option de création)
            table_combo = TableCreationComboBox()
            table_combo.addItems([""])
            self.mapping_table.setCellWidget(row, 2, table_combo)
            
            # Connecter les signaux
            # 1. Signal de changement de schéma pour mettre à jour les tables
            schema_combo.currentTextChanged.connect(lambda text, r=row: self.update_table_combo_simple(r, text))
            # 2. Signal de création de nouvelle table
            table_combo.table_creation_requested.connect(self.handle_table_creation)
            
            QgsMessageLog.logMessage(f"Nouveau mapping ajouté à la ligne {row}", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur lors de l'ajout du mapping: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(self, "Erreur", f"Impossible d'ajouter le mapping:\n{str(e)}")
    
    def remove_selected(self):
        """Supprime le mapping sélectionné"""
        current_row = self.mapping_table.currentRow()
        if current_row >= 0:
            self.mapping_table.removeRow(current_row)
    

    

    
    def refresh_schemas(self):
        """Rafraîchit la liste des schémas et tables PostgreSQL (silencieux)"""
        if not POSTGRESQL_AVAILABLE:
            QgsMessageLog.logMessage("psycopg2 is not installed", "Transformer", Qgis.Warning)
            return
        
        if not self.config_widget:
            QgsMessageLog.logMessage("No configuration widget available", "Transformer", Qgis.Warning)
            return
        
        try:
            # Paramètres de connexion depuis le widget de config
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 5  # Timeout pour éviter les attentes trop longues
            }
            
            # Validation des paramètres essentiels
            if not conn_params['database']:
                QgsMessageLog.logMessage("Database name is required", "Transformer", Qgis.Warning)
                return
            
            if not conn_params['user']:
                QgsMessageLog.logMessage("Username is required", "Transformer", Qgis.Warning)
                return
            
            # Connexion à PostgreSQL
            conn = psycopg2.connect(**conn_params)
            cursor = conn.cursor()
            
            # Récupérer TOUS les schémas (sans LIMIT)
            cursor.execute("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
                  AND schema_name NOT LIKE 'pg_temp%'
                  AND schema_name NOT LIKE 'pg_toast%'
                ORDER BY schema_name
            """)
            schemas = [row[0] for row in cursor.fetchall()]
            
            # Pour les tables, ne charger que si nécessaire (pas automatiquement)
            tables_by_schema = {}
            # On n'initialise que 'public' par défaut
            if 'public' in schemas:
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """)
                tables_by_schema['public'] = [row[0] for row in cursor.fetchall()]
                
                # Récupérer aussi les vues pour le schéma public
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_type = 'VIEW'
                    ORDER BY table_name
                """)
                views = [row[0] for row in cursor.fetchall()]
                if views:
                    tables_by_schema['public'].extend([f"[Vue] {view}" for view in views])
            
            cursor.close()
            conn.close()
            
            # Stocker les résultats
            self.available_schemas = schemas
            self.available_tables = tables_by_schema
            
            # Log du résultat
            QgsMessageLog.logMessage(
                f"PostgreSQL schemas loaded: {len(schemas)} schemas available", 
                "Transformer", 
                Qgis.Success
            )
            
            # Mettre à jour les ComboBox dans le tableau si nécessaire
            self.update_all_schema_combos()
            
            # Notify main dialog to update stats
            try:
                parent_dialog = self.parent()
                while parent_dialog and not hasattr(parent_dialog, 'update_statistics'):
                    parent_dialog = parent_dialog.parent()
                if parent_dialog and hasattr(parent_dialog, 'update_statistics'):
                    parent_dialog.update_statistics()
            except Exception:
                pass  # Ignore notification errors
                
        except psycopg2.Error as e:
            QgsMessageLog.logMessage(f"Failed to refresh schemas: {str(e)}", "Transformer", Qgis.Critical)
        except Exception as e:
            QgsMessageLog.logMessage(f"Schema refresh error: {str(e)}", "Transformer", Qgis.Critical)
    
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
                Qgis.Info
            )
                
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating schema ComboBoxes: {str(e)}",
                "Transformer",
                Qgis.Warning
            )
    
    def update_table_combo_simple(self, row, schema):
        """Update table combo when schema changes - improved version with automatic loading"""
        table_combo = self.mapping_table.cellWidget(row, 2)
        if not table_combo:
            return
        
        if not schema:
            return
        
        # If tables for this schema are already available, use them
        if schema in self.available_tables:
            if isinstance(table_combo, TableCreationComboBox):
                table_combo.set_tables(self.available_tables[schema])
                # Connect table creation signal (always, just in case)
                try:
                    table_combo.table_creation_requested.disconnect()
                except TypeError:
                    pass  # No existing connection
                table_combo.table_creation_requested.connect(self.handle_table_creation)
            elif isinstance(table_combo, SearchableComboBox):
                # ComboBox with advanced search
                current_text = table_combo.currentText()
                table_combo.clear()
                tables_for_combo = [""]
                tables_for_combo.extend(self.available_tables[schema])
                table_combo.addItems(tables_for_combo)
                
                # Restaurer la sélection précédente si possible
                if current_text in tables_for_combo:
                    table_combo.setCurrentText(current_text)
                
                # Configure completer model
                if hasattr(table_combo, 'completer'):
                    model = QStringListModel(tables_for_combo)
                    table_combo.completer.setModel(model)
                        
                    # Pour TableCreationComboBox, connecter le signal de création
                    if isinstance(table_combo, TableCreationComboBox):
                        if hasattr(self, 'handle_table_creation') and not table_combo.receivers(table_combo.table_creation_requested.signal):
                            table_combo.table_creation_requested.connect(self.handle_table_creation)
            else:
                # Standard ComboBox
                current_text = table_combo.currentText()
                table_combo.clear()
                table_combo.addItem("")
                table_combo.addItems(self.available_tables[schema])
                if current_text in self.available_tables[schema]:
                    table_combo.setCurrentText(current_text)
            
            QgsMessageLog.logMessage(
                f"Tables updated for schema {schema}: {len(self.available_tables[schema])} tables available", 
                "Transformer", 
                Qgis.Info
            )
        else:
            # Automatic loading of tables for this schema
            QgsMessageLog.logMessage(
                f"Automatic loading of tables for schema {schema}...", 
                "Transformer", 
                Qgis.Info
            )
            self.load_tables_for_schema(schema, table_combo)
    
    def load_tables_for_schema(self, schema_name, target_combo=None):
        """Load tables for a specific schema
        
        Args:
            schema_name (str): PostgreSQL schema name
            target_combo (QComboBox, optional): ComboBox to update with loaded tables. None if only loading in memory.
        """
        if not POSTGRESQL_AVAILABLE:
            QgsMessageLog.logMessage(f"PostgreSQL not available. psycopg2 module missing.", "Transformer", Qgis.Warning)
            return
        
        if not self.config_widget:
            QgsMessageLog.logMessage(f"PostgreSQL configuration not available.", "Transformer", Qgis.Warning)
            return
            
        if not schema_name:
            QgsMessageLog.logMessage(f"Empty schema name.", "Transformer", Qgis.Warning)
            return
            
        try:
            # Paramètres de connexion
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 5
            }
            
            # Validation minimale
            if not conn_params['database'] or not conn_params['user']:
                return
            
            # Connexion
            conn = psycopg2.connect(**conn_params)
            cursor = conn.cursor()
            
            # Récupérer TOUTES les tables pour ce schéma (pas de LIMIT)
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """, (schema_name,))
            
            tables = [row[0] for row in cursor.fetchall()]
            
            # Récupérer aussi les vues (utiles pour intégration)
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_type = 'VIEW'
                ORDER BY table_name
            """, (schema_name,))
            
            views = [row[0] for row in cursor.fetchall()]
            if views:
                # Ajouter les vues avec un préfixe pour les distinguer
                tables.extend([f"[Vue] {view}" for view in views])
            
            cursor.close()
            conn.close()
            
            # Stocker les tables
            self.available_tables[schema_name] = tables
            
            # Mettre à jour le combo si fourni
            if target_combo:
                if isinstance(target_combo, TableCreationComboBox):
                    target_combo.set_tables(tables)
                else:
                    # Pour les ComboBox standard
                    current_text = target_combo.currentText()
                    target_combo.clear()
                    tables_for_combo = [""]
                    tables_for_combo.extend(tables)
                    target_combo.addItems(tables_for_combo)
                    
                    # Restaurer la sélection si possible
                    if current_text in tables_for_combo:
                        target_combo.setCurrentText(current_text)
            
            QgsMessageLog.logMessage(
                f"Tables chargées pour le schéma '{schema_name}': {len(tables)} tables/vues disponibles", 
                "Transformer", 
                Qgis.Info
            )
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading tables for schema '{schema_name}': {str(e)}", "Transformer", Qgis.Critical)
    

    
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
                QgsMessageLog.logMessage("Aucune couche source sélectionnée", "Transformer", Qgis.Warning)
                return
                
            layer_name = layer_combo.currentText().strip()
            if not layer_name:
                QgsMessageLog.logMessage("Nom de couche vide", "Transformer", Qgis.Warning)
                return
                
            # Traitement de la création de table pour la couche sélectionnée
            QgsMessageLog.logMessage(f"Création de table '{table_name}' pour la couche '{layer_name}' dans le schéma '{schema}'", "Transformer", Qgis.Info)
            
            # Log du résultat
            QgsMessageLog.logMessage(f"Table creation handled for {table_name}", "Transformer", Qgis.Info)
            
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
    
    def export_to_postgresql(self):
        """Export vers PostgreSQL avec vérifications de compatibilité"""
        try:
            mappings = self.get_current_mappings()
            
            if not mappings:
                QMessageBox.warning(self, "Warning", "Aucun mapping défini")
                return
            
            # Vérification de la disponibilité de PostgreSQL
            if not POSTGRESQL_AVAILABLE:
                QMessageBox.critical(self, "Erreur", "psycopg2 n'est pas installé")
                return
                
            # Vérification de la configuration PostgreSQL
            if not self.config_widget:
                QMessageBox.critical(self, "Erreur", "Configuration PostgreSQL non disponible")
                return
                
            # Analyser la compatibilité de chaque mapping
            QgsMessageLog.logMessage("Analyse de compatibilité en cours...", "Transformer", Qgis.Info)
            compatibility_info = []
            
            for mapping in mappings:
                layer_name = mapping['transformed']
                schema = mapping['schema']
                table = mapping['table']
                
                # Analyser ce mapping spécifique
                table_compatibility = self._analyze_table_compatibility(layer_name, schema, table)
                if table_compatibility:
                    compatibility_info.append(table_compatibility)
                    
            if not compatibility_info:
                QMessageBox.warning(self, "Avertissement", "Aucune table compatible trouvée pour l'intégration")
                return
                
            # Vérifier les préférences utilisateur pour la fenêtre de confirmation
            show_confirmation = self._should_show_confirmation()
            
            if show_confirmation:
                # Afficher la fenêtre de mapping interactif avec les détails
                available_schemas = list(self.available_schemas) if self.available_schemas else []
                confirm_dialog = IntegrationConfirmationDialog(compatibility_info, available_schemas, self)
                
                # Stocker la référence pour la sauvegarde des mappings
                self.confirmation_dialog = confirm_dialog
                
                if confirm_dialog.exec() != QDialog.Accepted:
                    QgsMessageLog.logMessage("Intégration annulée par l'utilisateur", "Transformer", Qgis.Info)
                    # Nettoyer la référence
                    self.confirmation_dialog = None
                    return
                    
                # Save the preference if the user checked "Do not show again"
                if confirm_dialog.dont_show_again:
                    self._save_confirmation_preference(False)
                    
                # Extract and store temporarily the detailed mappings
                temp_detailed_mappings = []
                try:
                    for tab_index in range(confirm_dialog.tabs.count()):
                        tab_widget = confirm_dialog.tabs.widget(tab_index)
                        tab_text = confirm_dialog.tabs.tabText(tab_index)
                        
                        if tab_widget:
                            # Select temporarily this tab to extract its data
                            current_tab = confirm_dialog.tabs.currentIndex()
                            confirm_dialog.tabs.setCurrentIndex(tab_index)
                            
                            # Extract mapping information from the dialog
                            complete_info = confirm_dialog.get_complete_mapping_info()
                            
                            # Restore the previously selected tab
                            confirm_dialog.tabs.setCurrentIndex(current_tab)
                            
                            # Find the base mapping corresponding to this tab
                            base_mapping = None
                            for mapping in mappings:
                                if mapping['transformed'] in tab_text:
                                    base_mapping = mapping
                                    break
                            
                            if base_mapping:
                                detailed_mapping = {
                                    "layer_name": base_mapping['transformed'],
                                    "schema": base_mapping['schema'],
                                    "table": base_mapping['table'],
                                    "field_mappings": complete_info.get('field_mapping', {}),
                                    "forced_types": complete_info.get('forced_types', {}),
                                    "custom_fields": complete_info.get('custom_fields', {}),
                                    "timestamp": datetime.now().isoformat()
                                }
                                temp_detailed_mappings.append(detailed_mapping)
                                
                                # Log for debug
                                QgsMessageLog.logMessage(
                                    f"Mapping detailed extracted for {base_mapping['transformed']}: "
                                    f"{len(complete_info.get('field_mapping', {}))} fields, "
                                    f"{len(complete_info.get('forced_types', {}))} forced types",
                                    "Transformer", Qgis.Info
                                )
                                 
                    # Stocker dans le cache temporaire pour la sauvegarde
                    self._temp_detailed_mappings = temp_detailed_mappings
                    QgsMessageLog.logMessage(f"Stockage temporaire de {len(temp_detailed_mappings)} mappings détaillés", "Transformer", Qgis.Info)
                    
                except Exception as e:
                    QgsMessageLog.logMessage(f"Erreur lors de l'extraction des mappings détaillés: {str(e)}", "Transformer", Qgis.Warning)
                    self._temp_detailed_mappings = []
                        
            # Procéder à l'intégration réelle
            success_count = 0
            error_count = 0
            
            for table_info in compatibility_info:
                try:
                    result = self._perform_integration(table_info)
                    if result:
                        success_count += 1
                        QgsMessageLog.logMessage(
                            f"Intégration réussie: {table_info['layer']} → {table_info['schema']}.{table_info['table']}",
                            "Transformer", Qgis.Success
                        )
                    else:
                        error_count += 1
                except Exception as e:
                    error_count += 1
                    QgsMessageLog.logMessage(
                        f"Erreur intégration {table_info['layer']}: {str(e)}",
                        "Transformer", Qgis.Critical
                    )
                    
            # Save mappings for reuse (detailed mappings are in _temp_detailed_mappings)
            self.save_mappings()
            
            # Clean temporary references
            if hasattr(self, 'confirmation_dialog'):
                self.confirmation_dialog = None
            if hasattr(self, '_temp_detailed_mappings'):
                self._temp_detailed_mappings = []
                
            # Final report
            if success_count > 0 or error_count > 0:
                message = f"Integration completed:\n {success_count} table(s) integrated successfully"
                if error_count > 0:
                    message += f"\n {error_count} error(s)"
                    
                QMessageBox.information(self, "Integration completed", message)
            else:
                QMessageBox.warning(self, "Warning", "No integration performed")
            
        except Exception as e:
            QgsMessageLog.logMessage(f"General error during export: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(self, "Export error", f"Export failed: {str(e)}")
    
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
                    
            if not source_layer or not isinstance(source_layer, QgsVectorLayer):
                QgsMessageLog.logMessage(f"Couche '{layer_name}' introuvable ou non vectorielle", "Transformer", Qgis.Warning)
                return None
                
            # Informations de base
            table_info = {
                'layer': layer_name,  # Clé changée pour correspondre à l'interface
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
                QgsMessageLog.logMessage(f"Table {schema}.{table} does not exist - automatic creation", "Transformer", Qgis.Info)
                
                # Create the table based on the source layer structure
                if self._create_postgresql_table(schema, table, source_layer):
                    QgsMessageLog.logMessage(f"Table {schema}.{table} created successfully", "Transformer", Qgis.Success)
                    
                    # Now retrieve the information of the newly created table
                    target_info = self._get_postgresql_table_info(schema, table)
                    
                    if not target_info:
                        QgsMessageLog.logMessage(f"Impossible de récupérer les infos de la table créée {schema}.{table}", "Transformer", Qgis.Critical)
                        return None
                else:
                    QgsMessageLog.logMessage(f"Échec de la création de la table {schema}.{table}", "Transformer", Qgis.Critical)
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
                        "Transformer", Qgis.Warning
                    )
                    QgsMessageLog.logMessage(
                        f"Suppression et recréation de la table {schema}.{table} avec le bon type géométrique",
                        "Transformer", Qgis.Info
                    )
                    
                    # Supprimer et recréer la table
                    if self._drop_and_recreate_table(schema, table, source_layer):
                        QgsMessageLog.logMessage(f"Table {schema}.{table} recreated successfully", "Transformer", Qgis.Success)
                        
                        # Retrieve the new information
                        target_info = self._get_postgresql_table_info(schema, table)
                        if target_info:
                            target_geom_type = target_info.get('geometry_type', '')
                            geom_compatible = True  # Now compatible
                    else:
                        QgsMessageLog.logMessage(f"Failed to recreate table {schema}.{table}", "Transformer", Qgis.Critical)
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
            QgsMessageLog.logMessage(f"Erreur analyse compatibilité {layer_name}: {str(e)}", "Transformer", Qgis.Critical)
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
                    geom_column = geom_columns[0][0]  # Take the first geometry column
                    
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
                    except:
                        pass  # Ign0rer les erreurs si la table est vide ou autre
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
            
            cur.close()
            conn.close()
            
            QgsMessageLog.logMessage(
                f"Table {schema}.{table}: géom={geom_type}, SRID={srid}, champs={len(table_info['fields'])}",
                "Transformer",
                Qgis.Info
            )
            
            return table_info
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur récupération info table {schema}.{table}: {str(e)}", "Transformer", Qgis.Warning)
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
        
        # Debug log
        QgsMessageLog.logMessage(
            f"DEBUG: Geometry compatibility - WKB={wkb_type}, Expected={expected_pg_type}, Target={target_geom_type}",
            "Transformer", Qgis.Info
        )
        
        # Strict verification: the type must match exactly
        if expected_pg_type:
            compatible = expected_pg_type.upper() == target_geom_type.upper()
        else:
            # Fallback to generic types for compatibility
            geom_type = source_layer.geometryType()
            fallback_mapping = {
                QgsWkbTypes.PointGeometry: 'MULTIPOINT',
                QgsWkbTypes.LineGeometry: 'MULTILINESTRING',
                QgsWkbTypes.PolygonGeometry: 'MULTIPOLYGON'
            }
            expected_pg_type = fallback_mapping.get(geom_type, 'GEOMETRY')
            compatible = expected_pg_type.upper() == target_geom_type.upper()
        
        QgsMessageLog.logMessage(
            f"DEBUG: Compatible={compatible} ({expected_pg_type} vs {target_geom_type})",
            "Transformer", Qgis.Info
        )
        
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
            QgsMessageLog.logMessage(f"ANALYSE: Checking the real geometry type on {min(10, source_layer.featureCount())} features...", "Transformer", Qgis.Info)
            
            for feature in source_layer.getFeatures():
                if feature_count >= 10:  # Limiter à 10 features pour l'analyse
                    break
                    
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        actual_wkb_type = geom.wkbType()
                        actual_geom_types.add(actual_wkb_type)
                        QgsMessageLog.logMessage(f"Feature #{feature_count + 1}: WKB={actual_wkb_type} ({QgsWkbTypes.displayString(actual_wkb_type)})", "Transformer", Qgis.Info)
                        feature_count += 1
            
            # Get the declared WKB type and the detected type
            wkb_type = source_layer.wkbType()
            detected_wkb_type = wkb_type
            
            # Detect MultiLineString cases even if the layer is declared LineString
            if QgsWkbTypes.MultiLineString in actual_geom_types or QgsWkbTypes.MultiLineString25D in actual_geom_types:
                detected_wkb_type = QgsWkbTypes.MultiLineString
                QgsMessageLog.logMessage(f"🔧 CORRECTION: Type déclaré={QgsWkbTypes.displayString(wkb_type)}, Type réel détecté=MultiLineString", "Transformer", Qgis.Info)
            elif QgsWkbTypes.MultiPoint in actual_geom_types or QgsWkbTypes.MultiPoint25D in actual_geom_types:
                detected_wkb_type = QgsWkbTypes.MultiPoint
                QgsMessageLog.logMessage(f"🔧 CORRECTION: Type déclaré={QgsWkbTypes.displayString(wkb_type)}, Type réel détecté=MultiPoint", "Transformer", Qgis.Info)
            elif QgsWkbTypes.MultiPolygon in actual_geom_types or QgsWkbTypes.MultiPolygon25D in actual_geom_types:
                detected_wkb_type = QgsWkbTypes.MultiPolygon
                QgsMessageLog.logMessage(f"🔧 CORRECTION: Type déclaré={QgsWkbTypes.displayString(wkb_type)}, Type réel détecté=MultiPolygon", "Transformer", Qgis.Info)
            
            # Override the declared type with the detected real type
            if detected_wkb_type != wkb_type:
                wkb_type = detected_wkb_type
                QgsMessageLog.logMessage(f"Using the real geometry type: {QgsWkbTypes.displayString(wkb_type)}", "Transformer", Qgis.Success)
            
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
                fallback_mapping = {
                    QgsWkbTypes.PointGeometry: 'MULTIPOINT',
                    QgsWkbTypes.LineGeometry: 'MULTILINESTRING',
                    QgsWkbTypes.PolygonGeometry: 'MULTIPOLYGON'
                }
                pg_geom_type = fallback_mapping.get(geom_type, 'GEOMETRY')
            
            # Get the SRID
            srid = source_layer.crs().postgisSrid()
            
            # Build the CREATE TABLE query
            create_sql = f'CREATE TABLE IF NOT EXISTS "{schema}"."{table_name}" (\n'
            create_sql += '  id SERIAL PRIMARY KEY,\n'
            
            # Add the fields
            fields = source_layer.fields()
            field_definitions = []
            
            for field in fields:
                field_name = field.name()
                field_type = field.type()
                
                # Mapping QGIS types to PostgreSQL
                if field_type == QVariant.String:
                    pg_type = f'VARCHAR({field.length() if field.length() > 0 else 255})'
                elif field_type == QVariant.Int:
                    pg_type = 'INTEGER'
                elif field_type == QVariant.LongLong:
                    pg_type = 'BIGINT'
                elif field_type == QVariant.Double:
                    pg_type = 'DOUBLE PRECISION'
                elif field_type == QVariant.Date:
                    pg_type = 'DATE'
                elif field_type == QVariant.DateTime:
                    pg_type = 'TIMESTAMP'
                elif field_type == QVariant.Bool:
                    pg_type = 'BOOLEAN'
                else:
                    pg_type = 'TEXT'
                
                field_definitions.append(f'  "{field_name}" {pg_type}')
            
            create_sql += ',\n'.join(field_definitions)
            
            # Add the geometry column
            if srid > 0:
                create_sql += f',\n  geom GEOMETRY({pg_geom_type}, {srid})'
            else:
                create_sql += f',\n  geom GEOMETRY({pg_geom_type})'
            
            create_sql += '\n);'
            
            # Create the table
            cur.execute(create_sql)
            
            # Create the spatial index
            index_sql = f'CREATE INDEX IF NOT EXISTS idx_{table_name}_geom ON "{schema}"."{table_name}" USING GIST (geom);'
            cur.execute(index_sql)
            
            conn.commit()
            cur.close()
            conn.close()
            
            QgsMessageLog.logMessage(
                f"Table {schema}.{table_name} created with {len(field_definitions)} fields and geometry {pg_geom_type} (SRID: {srid})",
                "Transformer", Qgis.Success
            )
            
            return True
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur creation table {schema}.{table_name}: {str(e)}", "Transformer", Qgis.Critical)
            try:
                conn.rollback()
                cur.close()
                conn.close()
            except:
                pass
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
            
            # Drop the existing table
            drop_sql = f'DROP TABLE IF EXISTS "{schema}"."{table_name}" CASCADE'
            cur.execute(drop_sql)
            
            QgsMessageLog.logMessage(f"🗑️ Table {schema}.{table_name} dropped", "Transformer", Qgis.Info)
            
            conn.commit()
            cur.close()
            conn.close()
            
            # Recreate the table with the correct structure
            return self._create_postgresql_table(schema, table_name, source_layer)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error dropping table {schema}.{table_name}: {str(e)}", "Transformer", Qgis.Critical)
            try:
                conn.rollback()
                cur.close()
                conn.close()
            except:
                pass
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
        
    def _should_show_confirmation(self):
        """Determine if the confirmation window should be displayed"""
        try:
            plugin_dir = os.path.dirname(os.path.realpath(__file__))
            config_path = os.path.join(plugin_dir, "transformer_postgresql_preferences.json")
            
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    prefs = json.load(f)
                    return prefs.get('show_confirmation', True)
            else:
                return True  # Default to showing confirmation
        except:
            return True
            
    def _save_confirmation_preference(self, show_confirmation):
        """Save the confirmation preference"""
        try:
            plugin_dir = os.path.dirname(os.path.realpath(__file__))
            config_path = os.path.join(plugin_dir, "transformer_postgresql_preferences.json")
            
            prefs = {'show_confirmation': show_confirmation}
            
            with open(config_path, 'w') as f:
                json.dump(prefs, f, indent=2)
                
            QgsMessageLog.logMessage(f"Preference saved: show_confirmation = {show_confirmation}", "Transformer", Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error saving preferences: {str(e)}", "Transformer", Qgis.Warning)
            
    def _perform_integration(self, table_info):
        """Perform the actual table integration"""
        layer_name = table_info.get('layer', 'Unknown')
        try:
            schema = table_info['schema']
            table = table_info['table']
            
            QgsMessageLog.logMessage(
                f"Starting integration: {layer_name} → {schema}.{table}",
                "Transformer", Qgis.Info
            )
            
            # Get the source layer
            project = QgsProject.instance()
            source_layer = None
            
            for layer in project.mapLayers().values():
                if layer.name() == layer_name:
                    source_layer = layer
                    break
                    
            if not source_layer:
                raise Exception(f"Couche '{layer_name}' introuvable")
                
            QgsMessageLog.logMessage(
                f"Couche trouvée: {source_layer.featureCount()} features",
                "Transformer", Qgis.Info
            )
            
            # Paramètres de connexion PostgreSQL
            conn_params = {
                'host': self.config_widget.host_edit.text() or 'localhost',
                'port': self.config_widget.port_edit.value(),
                'database': self.config_widget.database_edit.text(),
                'user': self.config_widget.username_edit.text(),
                'password': self.config_widget.password_edit.text(),
                'connect_timeout': 5
            }
            
            QgsMessageLog.logMessage(
                f"Connexion PostgreSQL: {conn_params['host']}:{conn_params['port']}/{conn_params['database']}",
                "Transformer", Qgis.Info
            )
            
            # Connexion directe pour copier les données
            conn = psycopg2.connect(**conn_params)
            cur = conn.cursor()
            
            # Vérifier si la table existe, la créer si nécessaire
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
                existing_count = cur.fetchone()[0]
                
                QgsMessageLog.logMessage(
                    f"Table {schema}.{table} exists already with {existing_count} records",
                    "Transformer", Qgis.Info
                )
                
                # Critical verification: Geometry type of the existing table
                table_info_check = self._get_postgresql_table_info(schema, table)
                if table_info_check:
                    current_geom_type = table_info_check.get('geometry_type', '')
                    
                    # Verify compatibility with our source layer
                    geom_compatible = self._check_geometry_compatibility(source_layer, current_geom_type)
                    
                    QgsMessageLog.logMessage(
                        f"Verification: Table geometry={current_geom_type}, Compatible={geom_compatible}",
                        "Transformer", Qgis.Info
                    )
                    
                    if not geom_compatible:
                        QgsMessageLog.logMessage(
                            f"Forced deletion of table with wrong geometry type {current_geom_type}",
                            "Transformer", Qgis.Warning
                        )
                        
                        # Forcer suppression et recréation
                        cur.close()
                        conn.close()
                        
                        # Recréer avec bon type
                        if self._drop_and_recreate_table(schema, table, source_layer):
                            QgsMessageLog.logMessage(f"Table {schema}.{table} recreated with correct geometry type", "Transformer", Qgis.Success)
                            
                            # Reconnecter
                            conn = psycopg2.connect(**conn_params)
                            cur = conn.cursor()
                            cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
                            existing_count = cur.fetchone()[0]
                        else:
                            raise Exception(f"Failed to recreate table {schema}.{table}")
                
            except psycopg2.Error as e:
                # Table does not exist, create it
                QgsMessageLog.logMessage(
                    f"Table {schema}.{table} does not exist - automatic creation",
                    "Transformer", Qgis.Info
                )
                
                # Rollback of failed transaction
                conn.rollback()
                
                # Create the table
                if not self._create_postgresql_table(schema, table, source_layer):
                    raise Exception(f"Failed to create table {schema}.{table}")
                
                # Verify that the table exists
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
                existing_count = cur.fetchone()[0]
                
                QgsMessageLog.logMessage(
                    f"Table {schema}.{table} created successfully",
                    "Transformer", Qgis.Success
                )
                
            if existing_count > 0:
                QgsMessageLog.logMessage(
                    f"Table {schema}.{table} already contains {existing_count} records - deletion",
                    "Transformer", Qgis.Warning
                )
                cur.execute(f'DELETE FROM "{schema}"."{table}"')
                conn.commit()
            
            # Copy features
            feature_count = 0
            error_count = 0
            
            # Get list of source layer fields
            source_fields = [field.name() for field in source_layer.fields()]
            
            QgsMessageLog.logMessage(
                f"Champs à copier: {', '.join(source_fields)}",
                "Transformer", Qgis.Info
            )
            
            # Build the INSERT query (simplified version)
            field_names = '"' + '", "'.join(source_fields) + '"'
            placeholders = ', '.join(['%s'] * len(source_fields))
            
            # Query with optional geometry (no geometry parameter)
            insert_query = f'INSERT INTO "{schema}"."{table}" ({field_names}, geom) VALUES ({placeholders}, {{}})'
            
            QgsMessageLog.logMessage(
                f"Requête INSERT: {insert_query}",
                "Transformer", Qgis.Info
            )
            
            # Iterate over all features
            for feature in source_layer.getFeatures():
                try:
                    # Extract attribute values with appropriate conversion
                    values = []
                    for field_name in source_fields:
                        # Use QGIS native API to get the converted value
                        field_value = feature.attribute(field_name)
                        
                        # Safe conversion for psycopg2
                        if field_value is None:
                            values.append(None)
                        else:
                            # Convert according to type
                            try:
                                if isinstance(field_value, (int, float, str, bool)):
                                    values.append(field_value)
                                elif hasattr(field_value, 'toPyObject'):
                                    # Qt method for conversion
                                    py_value = field_value.toPyObject()
                                    values.append(py_value if py_value is not None else None)
                                else:
                                    # Conversion finale en string
                                    values.append(str(field_value))
                                    
                            except Exception as conv_error:
                                # Fallback sûr
                                values.append(str(field_value) if field_value is not None else None)
                                QgsMessageLog.logMessage(
                                    f"Conversion '{field_name}': {str(conv_error)} - utilisé str()",
                                    "Transformer", Qgis.Warning
                                )
                    
                    # Handle geometry
                    geom = feature.geometry()
                    if geom and not geom.isEmpty():
                        # Convert to WKT (Well-Known Text) for PostgreSQL
                        wkt_geom = geom.asWkt()
                        srid = source_layer.crs().postgisSrid()
                        
                        # Create the PostgreSQL geometry with SRID
                        if srid > 0:
                            geom_sql = f"ST_GeomFromText('{wkt_geom}', {srid})"
                        else:
                            geom_sql = f"ST_GeomFromText('{wkt_geom}')"
                    else:
                        # Insert a null geometry
                        geom_sql = "NULL"
                    
                    # Build the complete query with the geometry
                    final_query = insert_query.format(geom_sql)
                    
                    # Execute the insertion (only with field values)
                    cur.execute(final_query, values)
                    feature_count += 1
                    
                    # Log periodically
                    if feature_count % 50 == 0:
                        QgsMessageLog.logMessage(
                            f"📊 {feature_count} features copied...",
                            "Transformer", Qgis.Info
                        )
                        
                except Exception as feature_error:
                    error_count += 1
                    QgsMessageLog.logMessage(
                        f"Erreur feature #{feature_count + error_count}: {str(feature_error)}",
                        "Transformer", Qgis.Critical
                    )
                    if error_count > 10:
                        raise Exception(f"Too many errors ({error_count}) - integration stopped")
                    continue
            
            # Commit the changes
            conn.commit()
            
            # Verify the result
            cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            final_count = cur.fetchone()[0]
            
            cur.close()
            conn.close()
            
            QgsMessageLog.logMessage(
                f"INTÉGRATION TERMINÉE: {final_count} enregistrements dans {schema}.{table}",
                "Transformer", Qgis.Success
            )
            
            if final_count == 0:
                raise Exception("Aucun enregistrement inséré dans la table")
                
            return True
            
        except Exception as e:
            QgsMessageLog.logMessage(
                f"ERREUR INTÉGRATION {layer_name}: {str(e)}",
                "Transformer", Qgis.Critical
            )
            return False
    
    def save_mappings(self, checked=None):
        """Enregistre les mappings courants dans un fichier JSON avec tous les détails
        
        Args:
            checked: Optional parameter that can be passed by a signal (e.g: QPushButton.clicked)
        """
        try:
            QgsMessageLog.logMessage("Saving complete PostgreSQL mappings...", "Transformer", Qgis.Info)
            
            # Use the existing method to extract mappings (with debug logs)
            basic_mappings = self.get_current_mappings()
            
            # Extract ALL field mapping details for each layer
            detailed_mappings = []
            
            # First look for confirmation dialog if it exists
            if hasattr(self, 'confirmation_dialog') and self.confirmation_dialog:
                for tab_index in range(self.confirmation_dialog.tabs.count()):
                    tab_widget = self.confirmation_dialog.tabs.widget(tab_index)
                    tab_text = self.confirmation_dialog.tabs.tabText(tab_index)
                    
                    if tab_widget and hasattr(tab_widget, 'get_complete_mapping_info'):
                        complete_info = tab_widget.get_complete_mapping_info()
                        
                        # Find the corresponding base mapping
                        base_mapping = None
                        for bm in basic_mappings:
                            if bm['transformed'] in tab_text:
                                base_mapping = bm
                                break
                        
                        if base_mapping:
                            detailed_mapping = {
                                "layer_name": base_mapping['transformed'],
                                "schema": base_mapping['schema'],
                                "table": base_mapping['table'],
                                "field_mappings": complete_info.get('field_mapping', {}),
                                "forced_types": complete_info.get('forced_types', {}),
                                "custom_fields": complete_info.get('custom_fields', {}),
                                "timestamp": datetime.now().isoformat()
                            }
                            detailed_mappings.append(detailed_mapping)
            
            # If no detailed mappings in the confirmation dialog, check the temporary cache
            if not detailed_mappings and hasattr(self, '_temp_detailed_mappings'):
                detailed_mappings = self._temp_detailed_mappings
                QgsMessageLog.logMessage(f"Récupération de {len(detailed_mappings)} mappings détaillés depuis le cache temporaire", "Transformer", Qgis.Info)
            
            # If still no detailed mappings, automatically generate from the base mappings
            if not detailed_mappings and basic_mappings:
                detailed_mappings = self._generate_detailed_mappings_from_basic(basic_mappings)
                QgsMessageLog.logMessage(f"Génération automatique de {len(detailed_mappings)} mappings détaillés", "Transformer", Qgis.Info)
            
            # Save the base mappings (compatibility)
            plugin_dir = os.path.dirname(__file__)
            basic_config_path = os.path.join(plugin_dir, "transformer_postgresql_mappings.json")
            
            # Save the detailed mappings (new file)
            detailed_config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")
            
            # Read existing detailed mappings
            existing_detailed = []
            if os.path.exists(detailed_config_path):
                try:
                    with open(detailed_config_path, 'r') as f:
                        existing_detailed = json.load(f)
                except json.JSONDecodeError:
                    existing_detailed = []
            
            # Merge the detailed mappings (replace if same layer/schema/table)
            updated_detailed = list(existing_detailed)  # Copy to avoid in-place modifications
            
            # Add/update the new detailed mappings
            for new_detailed in detailed_mappings:
                # Remove old mappings for this combination
                updated_detailed = [ed for ed in updated_detailed 
                                   if not (ed.get('layer_name') == new_detailed.get('layer_name') and
                                          ed.get('schema') == new_detailed.get('schema') and
                                          ed.get('table') == new_detailed.get('table'))]
                updated_detailed.append(new_detailed)
            
            # Save the base mappings for compatibility
            with open(basic_config_path, 'w') as f:
                json.dump(basic_mappings, f, indent=2)
            
            # Save the detailed mappings
            with open(detailed_config_path, 'w') as f:
                json.dump(updated_detailed, f, indent=2)
            
            saved_count = len(basic_mappings)
            detailed_count = len(detailed_mappings)
            
            QgsMessageLog.logMessage(f"{saved_count} base mappings + {detailed_count} detailed mappings saved", "Transformer", Qgis.Success)
            QMessageBox.information(self, "Mappings saved", 
                                  f"{saved_count} base mappings and {detailed_count} detailed mappings saved successfully.\n\n"
                                  "Detailed mappings include:\n"
                                  "• Field correspondences\n"
                                  "• Forced types\n"
                                  "• Champs personnalisés")
            
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Failed to save mappings: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(self, "Error", f"Failed to save mappings:\n{str(e)}")
            return False

    def find_detailed_mapping(self, layer_name, schema, table):
        """Find a saved detailed mapping for a layer/schema/table combination"""
        try:
            plugin_dir = os.path.dirname(__file__)
            detailed_config_path = os.path.join(plugin_dir, "postgresql_detailed_mappings.json")
            
            if not os.path.exists(detailed_config_path):
                return None
            
            # Load all detailed mappings
            with open(detailed_config_path, 'r') as f:
                all_detailed_mappings = json.load(f)
            
            if not all_detailed_mappings:
                return None
            
            # Rechercher un mapping détaillé pour cette combinaison
            for detailed_mapping in all_detailed_mappings:
                if (detailed_mapping.get("layer_name", "") == layer_name and
                    detailed_mapping.get("schema", "") == schema and
                    detailed_mapping.get("table", "") == table):
                    return detailed_mapping
            
            return None
        except Exception as e:
            QgsMessageLog.logMessage(f"Failed to find detailed mapping: {str(e)}", "Transformer", Qgis.Warning)
            return None
    
    def auto_load_detailed_mapping(self, layer_name, schema, table):
        """Automatically load a detailed mapping if available"""
        detailed_mapping = self.find_detailed_mapping(layer_name, schema, table)
        
        if detailed_mapping:
            QgsMessageLog.logMessage(
                f"✨ Detailed mapping found for {layer_name} → {schema}.{table}",
                "Transformer", Qgis.Info
            )
            
            # Apply the detailed mapping automatically
            self.apply_detailed_mapping_to_dialog(detailed_mapping)
            return True
        
        return False
    
    def apply_detailed_mapping_to_dialog(self, detailed_mapping):
        """Apply a detailed mapping to the confirmation dialog"""
        if not hasattr(self, 'confirmation_dialog') or not self.confirmation_dialog:
            return
        
        try:
            layer_name = detailed_mapping.get('layer_name', '')
            field_mappings = detailed_mapping.get('field_mappings', {})
            forced_types = detailed_mapping.get('forced_types', {})
            custom_fields = detailed_mapping.get('custom_fields', {})
            
            QgsMessageLog.logMessage(
                f"🔄 APPLICATION MAPPING: {len(field_mappings)} champs, {len(forced_types)} types forcés, {len(custom_fields)} champs personnalisés",
                "Transformer", Qgis.Info
            )
            
            # Trouver l'onglet correspondant à la couche
            for tab_index in range(self.confirmation_dialog.tabs.count()):
                tab_text = self.confirmation_dialog.tabs.tabText(tab_index)
                if layer_name in tab_text:
                    tab_widget = self.confirmation_dialog.tabs.widget(tab_index)
                    
                    if tab_widget and hasattr(tab_widget, 'apply_detailed_mapping'):
                        tab_widget.apply_detailed_mapping(field_mappings, forced_types, custom_fields)
                        
                        # Select this tab
                        self.confirmation_dialog.tabs.setCurrentIndex(tab_index)
                        
                        QgsMessageLog.logMessage(
                            f"Detailed mapping applied successfully for {layer_name}",
                            "Transformer", Qgis.Success
                        )
                        break
            
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Failed to apply detailed mapping: {str(e)}",
                "Transformer", Qgis.Warning
            )
    
    def _generate_detailed_mappings_from_basic(self, basic_mappings):
        """Generate automatically detailed mappings from base mappings"""
        detailed_mappings = []
        
        try:
            project = QgsProject.instance()
            
            for basic_mapping in basic_mappings:
                layer_name = basic_mapping['transformed']
                schema = basic_mapping['schema']
                table = basic_mapping['table']
                
                # Find the corresponding QGIS layer
                source_layer = None
                for layer in project.mapLayers().values():
                    if layer.name() == layer_name:
                        source_layer = layer
                        break
                        
                if not source_layer or not isinstance(source_layer, QgsVectorLayer):
                    QgsMessageLog.logMessage(
                        f"Layer '{layer_name}' not found for detailed mapping generation",
                        "Transformer", Qgis.Warning
                    )
                    continue
                
                # Retrieve PostgreSQL table information
                table_info = self._get_postgresql_table_info(schema, table)
                
                if not table_info:
                    QgsMessageLog.logMessage(
                        f"Unable to retrieve table info for {schema}.{table}",
                        "Transformer", Qgis.Warning
                    )
                    continue
                
                # Generate automatic field mappings
                field_mappings = {}
                source_fields = source_layer.fields()
                target_fields = table_info.get('fields', [])
                
                for field in source_fields:
                    source_field_name = field.name()
                    # Find a match in the target fields
                    field_match = self._find_field_match(source_field_name, target_fields)
                    
                    if field_match:
                        field_mappings[source_field_name] = field_match['name']
                    else:
                        # If no match, map to the same name (create field)
                        field_mappings[source_field_name] = source_field_name
                
                # Create the detailed mapping
                detailed_mapping = {
                    "layer_name": layer_name,
                    "schema": schema,
                    "table": table,
                    "field_mappings": field_mappings,
                    "forced_types": {},  # No forced types by default
                    "custom_fields": {},  # No custom fields by default
                    "timestamp": datetime.now().isoformat(),
                    "auto_generated": True  # Mark as automatically generated
                }
                
                detailed_mappings.append(detailed_mapping)
                
                QgsMessageLog.logMessage(
                    f"Detailed mapping generated for {layer_name}: {len(field_mappings)} fields mapped",
                    "Transformer", Qgis.Info
                )
                
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Failed to generate detailed mappings: {str(e)}",
                "Transformer", Qgis.Warning
            )
            
        return detailed_mappings
            
    def find_mapping_for_layer(self, layer_name):
        """Find a saved mapping for a specific layer (compatibility)"""
        try:
            # Path to the mappings file
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "transformer_postgresql_mappings.json")
            
            if not os.path.exists(config_path):
                return None
            
            # Load all mappings
            with open(config_path, 'r') as f:
                all_mappings = json.load(f)
            
            if not all_mappings:
                return None
            
            # Search for a mapping for this layer
            for mapping in all_mappings:
                if mapping.get("transformed", "") == layer_name:
                    return mapping
            
            return None
        except Exception as e:
            QgsMessageLog.logMessage(f"Failed to find mapping for layer: {str(e)}", "Transformer", Qgis.Warning)
            return None
    
    def auto_connect_for_layer(self, layer_name):
        """Auto-connect to PostgreSQL and load the mapping for a layer"""
        if not self.auto_connect:
            return False
            
        QgsMessageLog.logMessage(f"Auto-connect to PostgreSQL and load the mapping for a layer {layer_name}", "Transformer", Qgis.Info)
        
        # Search for a mapping for this layer
        mapping = self.find_mapping_for_layer(layer_name)
        if not mapping:
            QgsMessageLog.logMessage(f"No mapping found for layer {layer_name}", "Transformer", Qgis.Info)
            return False
        
        # Load the PostgreSQL configuration
        if self.config_widget:
            QgsMessageLog.logMessage("Auto-loading PostgreSQL configuration", "Transformer", Qgis.Info)
            self.config_widget.load_config()
            
            # Test the connection and refresh schemas
            if self.config_widget.test_connection():
                # The connection test will automatically trigger refresh_schemas()
                
                # Add the mapping to the table
                schema = mapping.get("schema", "")
                table = mapping.get("table", "")
                
                QgsMessageLog.logMessage(f"Mapping automatically loaded: {layer_name} → {schema}.{table}", "Transformer", Qgis.Success)
                
                # Add a row to the table
                row = self.mapping_table.rowCount()
                self.mapping_table.insertRow(row)
                
                # Colonne 0: ComboBox avec la couche transformée
                layer_combo = QComboBox()
                project = QgsProject.instance()
                layers = [layer for layer in project.mapLayers().values() if hasattr(layer, 'name')]
                
                layer_names = [""]
                for layer in layers:
                    layer_names.append(layer.name())
                
                layer_combo.addItems(layer_names)
                layer_combo.setCurrentText(layer_name)
                self.mapping_table.setCellWidget(row, 0, layer_combo)
                
                # Colonne 1: ComboBox avec le schéma PostgreSQL
                schema_combo = QComboBox()
                schema_items = [""]
                if self.available_schemas:
                    schema_items.extend(self.available_schemas)
                
                schema_combo.addItems(schema_items)
                schema_combo.setCurrentText(schema)
                self.mapping_table.setCellWidget(row, 1, schema_combo)
                
                # Colonne 2: ComboBox with the table
                table_combo = QComboBox()
                table_combo.setEditable(True)
                
                # Load tables for this schema if necessary
                if schema not in self.available_tables:
                    self.load_tables_for_schema(schema)
                
                table_items = [""]
                if schema in self.available_tables:
                    table_items.extend(self.available_tables[schema])
                
                table_combo.addItems(table_items)
                table_combo.setCurrentText(table)
                self.mapping_table.setCellWidget(row, 2, table_combo)
                
                # Connect the schema change
                schema_combo.currentTextChanged.connect(lambda text, r=row: self.update_table_combo_simple(r, text))
                
                from qgis.utils import iface
                if iface:
                    iface.messageBar().pushMessage("PostgreSQL", f"Mapping automatically loaded: {layer_name} → {schema}.{table}", level=Qgis.Info, duration=5)
                
                return True
        
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
            QgsMessageLog.logMessage(f"Checking auto-connect for specific layers: {specific_layers}", "Transformer", Qgis.Info)
        else:
            # Vérifier toutes les couches du projet
            layers = [layer for layer in project.mapLayers().values() if hasattr(layer, 'name')]
        
        # Compter les mappings trouvés et chargés
        mappings_found = 0
        mappings_loaded = 0
        
        # Search for a mapping for each layer
        for layer in layers:
            mapping = self.find_mapping_for_layer(layer.name())
            if mapping:
                mappings_found += 1
                QgsMessageLog.logMessage(f"Mapping found for {layer.name()} - Auto-connecting", "Transformer", Qgis.Info)
                success = self.auto_connect_for_layer(layer.name())
                if success:
                    mappings_loaded += 1
                    
        # Afficher un message récapitulatif si des mappings ont été trouvés
        if mappings_found > 0:
            from qgis.utils import iface
            if iface:
                if mappings_loaded > 0:
                    message = f"🔗 {mappings_loaded} mapping(s) PostgreSQL chargé(s) automatiquement"
                    iface.messageBar().pushMessage("PostgreSQL Auto-Load", message, level=Qgis.Success, duration=8)
                else:
                    message = f"⚠️ {mappings_found} mapping(s) trouvé(s) mais aucun chargé"
                    iface.messageBar().pushMessage("PostgreSQL Auto-Load", message, level=Qgis.Warning, duration=5)
                    
        return mappings_loaded
    
    def load_mappings(self):
        """Load saved mappings and allow selection by table"""
        try:
            # Path to the mappings file
            plugin_dir = os.path.dirname(__file__)
            config_path = os.path.join(plugin_dir, "transformer_postgresql_mappings.json")
            
            if not os.path.exists(config_path):
                QMessageBox.warning(self, "No mappings", "The mappings file does not exist.")
                return
            
            # Load all mappings
            with open(config_path, 'r') as f:
                all_mappings = json.load(f)
            
            if not all_mappings:
                QMessageBox.warning(self, "No mappings", "The mappings file exists but contains no mappings.")
                return
            
            # Organize mappings by table to facilitate selection
            tables_dict = {}
            for mapping in all_mappings:
                transformed = mapping.get("transformed", "")
                schema = mapping.get("schema", "")
                table = mapping.get("table", "")
                
                # Créer une clé unique qui inclut schema et table
                key = f"{schema}.{table}"
                label = f"{transformed} → {schema}.{table}"
                
                tables_dict[label] = mapping
            
            # Sort the keys for better presentation
            sorted_labels = sorted(tables_dict.keys())
            
            if not sorted_labels:
                QMessageBox.warning(self, "No valid mappings", "The saved mappings are incomplete or invalid.")
                return
            
            # Ask the user to select a mapping
            selected_label, ok = QInputDialog.getItem(
                self, "Load a mapping", 
                "Select a mapping to load:", 
                sorted_labels, 0, False
            )
            
            if not ok or not selected_label:
                return  # User cancelled
            
            # Get the selected mapping
            selected_mapping = tables_dict.get(selected_label)
            if not selected_mapping:
                QMessageBox.critical(self, "Error", "Unable to find the selected mapping.")
                return
            
            # Add the selected mapping to the table
            row = self.mapping_table.rowCount()
            self.mapping_table.insertRow(row)
            
            # Column 0: ComboBox with transformed layers
            layer_combo = QComboBox()
            project = QgsProject.instance()
            layers = [layer for layer in project.mapLayers().values() if hasattr(layer, 'name')]
            
            layer_combo.addItem("")  # Option vide
            for layer in layers:
                layer_combo.addItem(layer.name())
            
            # Select the layer from the mapping
            layer_name = selected_mapping.get("transformed", "")
            if layer_name:
                layer_combo.setCurrentText(layer_name)
            
            self.mapping_table.setCellWidget(row, 0, layer_combo)
            
            # Column 1: ComboBox with PostgreSQL schemas
            schema_combo = QComboBox()
            schema_items = [""]
            if self.available_schemas:
                schema_items.extend(self.available_schemas)
            else:
                schema_items.append("public")
            
            schema_combo.addItems(schema_items)
            schema_name = selected_mapping.get("schema", "")
            if schema_name:
                schema_combo.setCurrentText(schema_name)
            
            self.mapping_table.setCellWidget(row, 1, schema_combo)
            
            # Column 2: ComboBox with tables
            table_combo = QComboBox()
            table_combo.setEditable(True)
            table_combo.addItems([""])  # Start with an empty option
            
            # If the schema is available, load the corresponding tables
            if schema_name in self.available_tables:
                for table_name in self.available_tables[schema_name]:
                    table_combo.addItem(table_name)
            
            # Select the table from the mapping
            table_name = selected_mapping.get("table", "")
            if table_name:
                table_combo.setCurrentText(table_name)
            
            self.mapping_table.setCellWidget(row, 2, table_combo)
            
            # Connect the schema change to update the tables
            schema_combo.currentTextChanged.connect(lambda text, r=row: self.update_table_combo_simple(r, text))
            
            QgsMessageLog.logMessage(
                f"Mapping loaded successfully: {layer_name} → {schema_name}.{table_name}",
                "Transformer", Qgis.Success
            )
            QMessageBox.information(
                self, "Mapping loaded", 
                f"The following mapping has been loaded:\n\n{layer_name} → {schema_name}.{table_name}"
            )
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading mappings: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(self, "Error", f"Unable to load mappings:\n{str(e)}")
    
    def trigger_auto_mapping_check(self, layer_names=None):
        """Méthode publique pour déclencher la vérification automatique des mappings
        
        Args:
            layer_names (list, optional): Liste des noms de couches à vérifier.
                                         Si None, vérifie toutes les couches.
        Returns:
            int: Nombre de mappings chargés avec succès
        """
        try:
            QgsMessageLog.logMessage(
                f"Triggering auto-mapping check for layers: {layer_names or 'all layers'}", 
                "Transformer", Qgis.Info
            )
            
            # Déclencher la vérification automatique
            mappings_loaded = self.check_auto_connect(layer_names)
            
            QgsMessageLog.logMessage(
                f"Auto-mapping check completed: {mappings_loaded} mapping(s) loaded", 
                "Transformer", Qgis.Info
            )
            
            return mappings_loaded
            
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error during auto-mapping check: {str(e)}", 
                "Transformer", Qgis.Warning
            )
            return 0



class PostgreSQLIntegrationWidget(QWidget):
    """Widget principal d'intégration PostgreSQL with splitter"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Configuration de l'interface"""
        layout = QVBoxLayout(self)
        
        # Vertical splitter to divide config and mapping
        splitter = QSplitter(Qt.Vertical)
        
        # Configuration widget (1/3 of the space)
        self.config_widget = PostgreSQLConfigWidget()
        
        # Mapping widget (2/3 of the space)
        self.mapping_widget = PostgreSQLMappingWidget()
        
        # Link widgets so mapping can access config
        self.mapping_widget.config_widget = self.config_widget
        
        # Add to splitter
        splitter.addWidget(self.config_widget)
        splitter.addWidget(self.mapping_widget)
        
        # Distribution: 1/3 config, 2/3 mapping
        splitter.setSizes([100, 200])
        
        layout.addWidget(splitter)
    
    def trigger_auto_mapping_check(self, layer_names=None):
        """Trigger automatic check of mappings for transformed layers
        
        Args:
            layer_names (list, optional): List of layer names to check.
                                         If None, checks all layers.
        Returns:
            int: Number of mappings loaded successfully
        """
        if hasattr(self, 'mapping_widget') and self.mapping_widget:
            return self.mapping_widget.trigger_auto_mapping_check(layer_names)
        return 0
