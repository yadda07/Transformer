"""
Secure export module for Transformer plugin
QGIS compat across versions
"""

import os
import re
from enum import Enum

# Secure imports w/ error handling
EXPORT_AVAILABLE = False
try:
    # QGIS core
    from qgis.core import (QgsProject, QgsVectorLayer, QgsVectorFileWriter, 
                           QgsMessageLog, QgsWkbTypes, QgsApplication)
    from qgis.gui import QgsMessageBar
    
    # Qt
    from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                                     QTreeWidget, QTreeWidgetItem, QPushButton, 
                                     QComboBox, QLabel, QMessageBox, QFileDialog,
                                     QRadioButton, QButtonGroup, QCheckBox)
    
    EXPORT_AVAILABLE = True
    from ..shared.compat import UserRole, MsgBoxYes, MsgBoxNo, MultiSelection, MsgInfo, MsgWarning, MsgCritical, MsgSuccess, WriterNoError
    from ..shared.icons import icon as ui_icon

    def _vector_file_action(*names, fallback_int=None):
        """Resolve QgsVectorFileWriter.ActionOnExistingFile across QGIS versions."""
        scoped = getattr(QgsVectorFileWriter, 'ActionOnExistingFile', QgsVectorFileWriter)
        for name in names:
            value = getattr(scoped, name, None)
            if value is not None:
                return value
            value = getattr(QgsVectorFileWriter, name, None)
            if value is not None:
                return value
        if fallback_int is not None:
            return fallback_int
        raise AttributeError(f"QgsVectorFileWriter action not found: {', '.join(names)}")

    GPKG_ACTION_CREATE_FILE = _vector_file_action('CreateOrOverwriteFile', fallback_int=0)
    GPKG_ACTION_ADD_LAYER = _vector_file_action('CreateOrOverwriteLayer', fallback_int=1)

except Exception as import_error:
    # Empty classes for compat
    class QObject:
        def __init__(self): pass
    class QWidget:
        def __init__(self, parent=None): pass
    
    def pyqtSignal(*args, **kwargs):
        return lambda: None


class ExportFormat(Enum):
    """EFs w/ native QGIS API"""
    SHAPEFILE = "ESRI Shapefile"
    GEOPACKAGE = "GeoPackage"
    GEOJSON = "GeoJSON"
    KML = "Keyhole Markup Language"
    CSV = "Comma Separated Values"
    XLSX = "MS Excel (xlsx)"
    DXF = "AutoCAD DXF"
    TAB = "MapInfo TAB"
    GML = "Geography Markup Language"
    SQLITE = "SQLite/SpatiaLite"
    FLATGEOBUF = "FlatGeobuf"


class ExportManager(QObject):
    """Export mgr"""
    
    def __init__(self):
        super().__init__()
        
        if not EXPORT_AVAILABLE:
            return
            
        # File exts for all formats
        self.format_extensions = {
            ExportFormat.SHAPEFILE: ".shp",
            ExportFormat.GEOPACKAGE: ".gpkg",
            ExportFormat.GEOJSON: ".geojson",
            ExportFormat.KML: ".kml",
            ExportFormat.CSV: ".csv",
            ExportFormat.XLSX: ".xlsx",
            ExportFormat.DXF: ".dxf",
            ExportFormat.TAB: ".tab",
            ExportFormat.GML: ".gml",
            ExportFormat.SQLITE: ".sqlite",
            ExportFormat.FLATGEOBUF: ".fgb"
        }
        
        # Mapping to native QGIS drivers
        self.driver_mapping = {
            ExportFormat.SHAPEFILE: "ESRI Shapefile",
            ExportFormat.GEOPACKAGE: "GPKG",
            ExportFormat.GEOJSON: "GeoJSON",
            ExportFormat.KML: "KML",
            ExportFormat.CSV: "CSV",
            ExportFormat.XLSX: "XLSX",
            ExportFormat.DXF: "DXF",
            ExportFormat.TAB: "MapInfo File",
            ExportFormat.GML: "GML",
            ExportFormat.SQLITE: "SQLite",
            ExportFormat.FLATGEOBUF: "FlatGeobuf"
        }
        
        # Formats supporting geometry
        self.geometry_formats = {
            ExportFormat.SHAPEFILE, ExportFormat.GEOPACKAGE, ExportFormat.GEOJSON,
            ExportFormat.KML, ExportFormat.DXF, ExportFormat.TAB,
            ExportFormat.GML, ExportFormat.SQLITE, ExportFormat.FLATGEOBUF
        }
        
        # Formats attribute only
        self.attribute_only_formats = {ExportFormat.CSV, ExportFormat.XLSX}
    
    def get_transformed_layers(self):
        """Get transformed layers"""
        if not EXPORT_AVAILABLE:
            return []
            
        layers = []
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                layers.append(layer)
        return sorted(layers, key=lambda x: x.name())
    
    def export_layer(self, layer, output_path, export_format, selected_features_only=False, encoding="utf-8"):
        """Export layer w/ complete QGIS API"""
        if not EXPORT_AVAILABLE:
            return False, "Module d'export non disponible"
            
        try:
            # Prep
            if not layer or not layer.isValid():
                return False, "Couche invalide"
                
            # Get driver for fmt
            driver_name = self.driver_mapping.get(export_format)
            if not driver_name:
                return False, f"Format {export_format.value} not supported"
            
            # Count features
            if selected_features_only and layer.selectedFeatureCount() > 0:
                feature_count = layer.selectedFeatureCount()
            else:
                feature_count = layer.featureCount()
            
            if feature_count == 0:
                return False, "No features to export"
                
            # Config export opts
            export_options = QgsVectorFileWriter.SaveVectorOptions()
            export_options.driverName = driver_name
            export_options.fileEncoding = encoding  # Use provided enc
            export_options.onlySelectedFeatures = selected_features_only and layer.selectedFeatureCount() > 0
            
            # Fmt specific opts
            self._configure_format_options(export_format, export_options, layer)
            
            # Execute export w/ native QGIS API
            if export_format in self.attribute_only_formats:
                # Tabular fmts, export w/o geom
                success, message = self._export_attributes_only(layer, output_path, export_format, export_options)
            else:
                # Std export w/ geom
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, output_path, QgsProject.instance().transformContext(), export_options
                )
                error_code = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"
                
                if error_code == WriterNoError:
                    success, message = True, f"Export réussi : {feature_count} entité(s)"
                else:
                    success, message = False, f"Erreur d'export : {error_message}"
            
            # Log detail
            if success:
                QgsMessageLog.logMessage(
                    f" Export successful - Layer: {layer.name()}, Format: {export_format.value}, "
                    f"Features: {feature_count}, Size: {self._get_file_size(output_path)} Ko",
                    "Transformer", MsgSuccess
                )
            else:
                QgsMessageLog.logMessage(
                    f" Export failed - Layer: {layer.name()}, Error: {message}",
                    "Transformer", MsgCritical
                )
            
            return success, message
                
        except Exception as e:
            error_msg = f"Unexpected error during export : {str(e)}"
            QgsMessageLog.logMessage(f" {error_msg}", "Transformer", MsgCritical)
            return False, error_msg

    def export_layers_to_single_geopackage(self, layers, output_path, encoding="utf-8",
                                           selected_features_only=False):
        """Export several layers into one GeoPackage file."""
        if not EXPORT_AVAILABLE:
            return False, "Module d'export non disponible", 0, 0

        if not layers:
            return False, "Aucune couche à exporter", 0, 0

        exported_count = 0
        failed_count = 0
        total_features = 0
        used_table_names = set()
        errors = []

        for layer in layers:
            if not layer or not layer.isValid():
                failed_count += 1
                layer_label = layer.name() if layer else "Couche"
                errors.append(f"{layer_label} : couche invalide")
                continue

            if selected_features_only and layer.selectedFeatureCount() > 0:
                feature_count = layer.selectedFeatureCount()
            else:
                feature_count = layer.featureCount()

            if feature_count == 0:
                failed_count += 1
                errors.append(f"{layer.name()} : aucune entité à exporter")
                continue

            table_name = self._sanitize_gpkg_table_name(layer.name(), used_table_names)

            export_options = QgsVectorFileWriter.SaveVectorOptions()
            export_options.driverName = "GPKG"
            export_options.fileEncoding = encoding
            export_options.onlySelectedFeatures = (
                selected_features_only and layer.selectedFeatureCount() > 0
            )
            if hasattr(export_options, "layerName"):
                export_options.layerName = table_name
            export_options.layerOptions = [
                f"IDENTIFIER={table_name}",
                f"LAYERNAME={table_name}",
            ]
            export_options.actionOnExistingFile = (
                GPKG_ACTION_ADD_LAYER
                if os.path.exists(output_path)
                else GPKG_ACTION_CREATE_FILE
            )

            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, output_path, QgsProject.instance().transformContext(), export_options
            )
            error_code = result[0]
            error_message = result[1] if len(result) > 1 else "Erreur inconnue"

            if error_code == WriterNoError:
                exported_count += 1
                total_features += feature_count
                QgsMessageLog.logMessage(
                    f" Export GeoPackage - {layer.name()} "
                    f"→ table '{table_name}' ({feature_count} entité(s))",
                    "Transformer", MsgSuccess
                )
            else:
                failed_count += 1
                errors.append(f"{layer.name()} : {error_message}")
                QgsMessageLog.logMessage(
                    f" Export GeoPackage échoué - {layer.name()} : {error_message}",
                    "Transformer", MsgCritical
                )

        if exported_count == 0:
            detail = errors[0] if len(errors) == 1 else "; ".join(errors[:3])
            return False, f"Aucune couche exportée ({detail})", exported_count, failed_count

        if failed_count == 0:
            return (
                True,
                f"{exported_count} couche(s) exportée(s) ({total_features} entité(s)) "
                f"dans {os.path.basename(output_path)}",
                exported_count,
                failed_count,
            )

        return (
            False,
            f"{exported_count} couche(s) exportée(s), {failed_count} échec(s) : "
            f"{'; '.join(errors[:3])}",
            exported_count,
            failed_count,
        )

    @staticmethod
    def _sanitize_gpkg_table_name(name, used_names):
        """Normalize layer names for GeoPackage table identifiers."""
        sanitized = re.sub(r"[^\w]", "_", name, flags=re.UNICODE)
        if not sanitized or sanitized[0].isdigit():
            sanitized = f"layer_{sanitized}"
        sanitized = sanitized[:63]

        base = sanitized
        counter = 1
        while sanitized.lower() in {existing.lower() for existing in used_names}:
            suffix = f"_{counter}"
            sanitized = f"{base[:63 - len(suffix)]}{suffix}"
            counter += 1

        used_names.add(sanitized)
        return sanitized
    
    def _configure_format_options(self, export_format, options, layer):
        """Config fmt specific opts"""
        if export_format == ExportFormat.SHAPEFILE:
            options.layerOptions = ['ENCODING=UTF-8']
        elif export_format == ExportFormat.GEOPACKAGE:
            options.layerOptions = ['IDENTIFIER=' + layer.name()]
        elif export_format == ExportFormat.GEOJSON:
            options.layerOptions = ['RFC7946=YES', 'WRITE_BBOX=YES']
        elif export_format == ExportFormat.KML:
            options.layerOptions = ['NameField=' + (layer.fields().names()[0] if layer.fields().count() > 0 else '')]
        elif export_format == ExportFormat.DXF:
            options.layerOptions = ['MODE=OGR_STYLE']
        elif export_format == ExportFormat.GML:
            options.layerOptions = ['FORMAT=GML3', 'GML3_LONGSRS=YES']
        elif export_format == ExportFormat.SQLITE:
            options.layerOptions = ['SPATIALITE=YES']
    
    def _export_attributes_only(self, layer, output_path, export_format, options):
        """Export specialized for attr-only fmts (CSV, XLSX)"""
        try:
            if export_format == ExportFormat.CSV:
                # CSV export - config optimized
                options.layerOptions = [
                    'GEOMETRY=AS_WKT',  # Geom in WKT fmt
                    'CREATE_CSVT=YES',  # Create type file
                    'SEPARATOR=COMMA',  # Std comma sep
                    'STRING_QUOTING=IF_NEEDED'  # Quotes if needed
                ]
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, output_path, QgsProject.instance().transformContext(), options
                )
                error_code = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"
            elif export_format == ExportFormat.XLSX:
                # Excel export - config optimized
                options.layerOptions = [
                    'FIELD_TYPES=AUTO',  # Auto field types
                    'GEOMETRY=AS_WKT'    # Geom in WKT for Excel
                ]
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer, output_path, QgsProject.instance().transformContext(), options
                )
                error_code = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"
            else:
                return False, f"Format attributaire {export_format.value} not implemented"
            
            if error_code == WriterNoError:
                return True, f"Export tabular successful : {layer.featureCount()} records"
            else:
                return False, f"Export tabular error : {error_message}"
                
        except Exception as e:
            return False, f"Export tabular error : {str(e)}"
    
    def _get_file_size(self, file_path):
        """File size in Ko"""
        try:
            return os.path.getsize(file_path) // 1024
        except Exception:
            return 0


class ExportWidget(QWidget):
    """Widget for simple secure export mgr"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        if not EXPORT_AVAILABLE:
            self.setup_fallback_ui()
        else:
            self.export_manager = ExportManager()
            self.setup_ui()
            self.setup_qgis_signals()
            self.refresh_layers()
    
    def setup_fallback_ui(self):
        """Fallback interface if the module is not available"""
        layout = QVBoxLayout()
        
        label = QLabel("Export functionality not available")
        label_font = label.font()
        label_font.setBold(True)
        label.setFont(label_font)
        layout.addWidget(label)
        
        detail_label = QLabel("The export module could not be loaded.")
        layout.addWidget(detail_label)
        
        info_label = QLabel("You can still use the basic transformation features.")
        layout.addWidget(info_label)
        
        self.setLayout(layout)
    
    def setup_ui(self):
        """Configure the main interface"""
        layout = QVBoxLayout()
        
        # Layers available
        layers_group = QGroupBox("Layers available")
        layers_layout = QVBoxLayout()
        
        # Tree of layers with enriched columns
        self.layers_tree = QTreeWidget()
        self.layers_tree.setHeaderLabels([
            "Layer name", "Features", "Geometry type", "CRS", 
            "Source", "Encoding", "Size (Ko)", "Extent"
        ])
        self.layers_tree.setSelectionMode(MultiSelection)
        self.layers_tree.setAlternatingRowColors(True)
        self.layers_tree.setSortingEnabled(True)
        
        # Column widths optimized
        self.layers_tree.setColumnWidth(0, 200)  # Layer name
        self.layers_tree.setColumnWidth(1, 80)   # Features
        self.layers_tree.setColumnWidth(2, 100)  # Type
        self.layers_tree.setColumnWidth(3, 120)  # CRS
        self.layers_tree.setColumnWidth(4, 150)  # Source
        self.layers_tree.setColumnWidth(5, 80)   # Encoding
        self.layers_tree.setColumnWidth(6, 80)   # Size
        self.layers_tree.setColumnWidth(7, 200)  # Extent
        
        layers_layout.addWidget(self.layers_tree)
        
        # Management buttons
        buttons_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_layers)
        buttons_layout.addWidget(refresh_btn)
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self.layers_tree.selectAll())
        buttons_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self.layers_tree.clearSelection())
        buttons_layout.addWidget(deselect_all_btn)
        
        # Remove button
        remove_btn = QPushButton("Remove from project")
        remove_btn.clicked.connect(self.remove_selected_layers)
        buttons_layout.addWidget(remove_btn)
        
        layers_layout.addLayout(buttons_layout)
        layers_group.setLayout(layers_layout)
        layout.addWidget(layers_group)
        
        # Export format - Single line compact
        format_group = QGroupBox("Export format")
        format_layout = QHBoxLayout()  # Single horizontal line
        
        # File format
        format_layout.addWidget(QLabel("Format:"))
        
        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(250)  # Slightly wider
        
        # Group formats by category
        self.format_combo.addItem("=== Spatial formats ===", None)
        spatial_formats = [ExportFormat.SHAPEFILE, ExportFormat.GEOPACKAGE, ExportFormat.GEOJSON, 
                          ExportFormat.KML, ExportFormat.GML, ExportFormat.FLATGEOBUF]
        for fmt in spatial_formats:
            self.format_combo.addItem(f"{fmt.value} (*{self.export_manager.format_extensions[fmt]})", fmt)
        
        self.format_combo.addItem("=== CAD Formats ===", None)
        cad_formats = [ExportFormat.DXF, ExportFormat.TAB]
        for fmt in cad_formats:
            self.format_combo.addItem(f"{fmt.value} (*{self.export_manager.format_extensions[fmt]})", fmt)
        
        self.format_combo.addItem("=== Tabular Formats ===", None)
        table_formats = [ExportFormat.CSV, ExportFormat.XLSX, ExportFormat.SQLITE]
        for fmt in table_formats:
            self.format_combo.addItem(f"{fmt.value} (*{self.export_manager.format_extensions[fmt]})", fmt)
        
        # Select Shapefile by default
        self.format_combo.setCurrentIndex(1)
        self.format_combo.currentIndexChanged.connect(self._on_export_format_changed)
        format_layout.addWidget(self.format_combo)
        
        # Spacing
        format_layout.addSpacing(20)
        
        # Encoding on the same line
        format_layout.addWidget(QLabel("Encoding:"))
        
        self.encoding_combo = QComboBox()
        self.encoding_combo.setMinimumWidth(150)  # More compact
        
        # Common encodings for export
        encodings = [
            ("UTF-8", "utf-8"),
            ("ISO-8859-1 (Latin-1)", "iso-8859-1"),
            ("Windows-1252", "cp1252"),
            ("ISO-8859-15 (Latin-9)", "iso-8859-15"),
            ("UTF-16", "utf-16"),
            ("ASCII", "ascii")
        ]
        
        for display_name, encoding_value in encodings:
            self.encoding_combo.addItem(display_name, encoding_value)
        
        # Load encoding from configuration or default UTF-8
        self._load_encoding_config()
        
        # Automatically save when encoding changes
        self.encoding_combo.currentTextChanged.connect(self._save_encoding_config)
        
        format_layout.addWidget(self.encoding_combo)
        
        # Final spacing to push to the left
        format_layout.addStretch()
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        # GeoPackage options for multi-layer export
        self.gpkg_options_group = QGroupBox("GeoPackage options")
        gpkg_layout = QHBoxLayout()

        self.gpkg_mode_group = QButtonGroup(self)
        self.gpkg_per_layer_radio = QRadioButton("Un GeoPackage par couche")
        self.gpkg_single_file_radio = QRadioButton("Un seul GeoPackage contenant toutes les couches")
        self.gpkg_per_layer_radio.setChecked(True)

        self.gpkg_mode_group.addButton(self.gpkg_per_layer_radio, 0)
        self.gpkg_mode_group.addButton(self.gpkg_single_file_radio, 1)

        gpkg_layout.addWidget(self.gpkg_per_layer_radio)
        gpkg_layout.addWidget(self.gpkg_single_file_radio)
        gpkg_layout.addStretch()

        self.gpkg_options_group.setLayout(gpkg_layout)
        self.gpkg_options_group.setVisible(False)
        self.gpkg_mode_group.buttonToggled.connect(self._save_gpkg_mode_config)
        layout.addWidget(self.gpkg_options_group)

        # Export scope + single action (conventional GIS pattern)
        export_group = QGroupBox("Export")
        export_layout = QHBoxLayout()

        self.selected_features_only_cb = QCheckBox("Selected features only")
        self.selected_features_only_cb.setToolTip(
            "Export only the features selected on the map (one layer at a time)"
        )
        export_layout.addWidget(self.selected_features_only_cb)

        export_layout.addStretch()

        export_btn = QPushButton("Export…")
        export_btn.setToolTip(
            "Export the layer(s) selected in the list above to the chosen format"
        )
        export_btn.clicked.connect(self.export_layers)
        export_layout.addWidget(export_btn)

        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        self.layers_tree.itemSelectionChanged.connect(self._update_export_scope_state)
        
        # Message bar
        self.message_bar = QgsMessageBar()
        layout.addWidget(self.message_bar)
        
        self.setLayout(layout)
        self._load_gpkg_mode_config()
        self._on_export_format_changed()
        self._update_export_scope_state()

    def _update_export_scope_state(self):
        """Disable feature-scope option when several layers are selected."""
        if not hasattr(self, "selected_features_only_cb"):
            return

        multi_layer = len(self.get_selected_layers()) > 1
        self.selected_features_only_cb.setEnabled(not multi_layer)
        if multi_layer:
            self.selected_features_only_cb.setChecked(False)

    def _on_export_format_changed(self):
        """Show GeoPackage options only when GeoPackage is selected."""
        if not hasattr(self, "format_combo"):
            return

        export_format = self.format_combo.currentData()
        is_geopackage = export_format == ExportFormat.GEOPACKAGE
        if hasattr(self, "gpkg_options_group"):
            self.gpkg_options_group.setVisible(is_geopackage)

    def _load_gpkg_mode_config(self):
        """Load GeoPackage multi-export mode from QGIS settings."""
        if not hasattr(self, "gpkg_single_file_radio"):
            return

        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            saved_value = settings.value("Transformer/export_gpkg_single_file", "false")
            single_file = str(saved_value).lower() in ("true", "1", "yes")
            if single_file:
                self.gpkg_single_file_radio.setChecked(True)
            else:
                self.gpkg_per_layer_radio.setChecked(True)
        except (ImportError, Exception):
            self.gpkg_per_layer_radio.setChecked(True)

    def _save_gpkg_mode_config(self):
        """Save GeoPackage multi-export mode in QGIS settings."""
        if not hasattr(self, "gpkg_single_file_radio"):
            return

        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            settings.setValue(
                "Transformer/export_gpkg_single_file",
                self.gpkg_single_file_radio.isChecked(),
            )
        except (ImportError, Exception):
            pass

    def _use_single_geopackage_export(self):
        """Return True when multi-export should produce one combined GeoPackage."""
        return (
            hasattr(self, "gpkg_single_file_radio")
            and self.gpkg_single_file_radio.isChecked()
        )
    
    def setup_qgis_signals(self):
        """Setup QGIS project layer signals for auto-update"""
        if not EXPORT_AVAILABLE:
            return
            
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            project.layersAdded.connect(self.on_layers_added)
            project.layersRemoved.connect(self.on_layers_removed)
            project.layerWillBeRemoved.connect(self.on_layer_will_be_removed)
        except Exception as e:
            # Fallback si les signaux ne sont pas disponibles
            pass
    
    def on_layers_added(self, layers):
        """Handle when new layers are added to QGIS project"""
        if not EXPORT_AVAILABLE:
            return
            
        vector_layers = [layer for layer in layers if hasattr(layer, 'isValid') and layer.isValid()]
        if vector_layers:
            try:
                from qgis.core import QgsVectorLayer
                vector_layers = [layer for layer in vector_layers if isinstance(layer, QgsVectorLayer)]
                if vector_layers:
                    self.refresh_layers()
                    if hasattr(self, 'message_bar') and self.message_bar:
                        self.message_bar.pushInfo("Export", f"{len(vector_layers)} new layer(s) available for export")
            except Exception:
                pass
                
    def on_layers_removed(self, layer_ids):
        """Handle when layers are removed from QGIS project"""
        if not EXPORT_AVAILABLE:
            return
            
        if layer_ids:
            self.refresh_layers()
            if hasattr(self, 'message_bar') and self.message_bar:
                self.message_bar.pushInfo("Export", f"Layer list updated after removal")
            
    def on_layer_will_be_removed(self, layer_id):
        """Handle when a layer is about to be removed"""
        if not EXPORT_AVAILABLE:
            return
            
        # Clear selection if the layer being removed is currently selected
        if hasattr(self, 'layers_tree') and self.layers_tree:
            try:
                for item in self.layers_tree.selectedItems():
                    layer = item.data(0, hasattr(item, 'UserRole') and item.UserRole or 256)  # UserRole fallback
                    if layer and hasattr(layer, 'id') and layer.id() == layer_id:
                        item.setSelected(False)
            except Exception:
                pass
    
    def refresh_layers(self):
        """Refresh the list of layers with detailed information"""  
        if not EXPORT_AVAILABLE:
            return
            
        self.layers_tree.clear()
        layers = self.export_manager.get_transformed_layers()
        
        for layer in layers:
            item = QTreeWidgetItem(self.layers_tree)
            
            # Layer name
            item.setText(0, layer.name())
            
            # Number of features
            item.setText(1, str(layer.featureCount()))
            
            # Geometry type
            geom_type = QgsWkbTypes.displayString(layer.wkbType())
            item.setText(2, geom_type)
            
            # CRS with EPSG code
            crs = layer.crs()
            if crs.isValid():
                crs_text = f"{crs.authid()} - {crs.description()}"
                if len(crs_text) > 50:
                    crs_text = f"{crs.authid()} - {crs.description()[:47]}..."
            else:
                crs_text = "CRS invalide"
            item.setText(3, crs_text)
            
            # Source of data
            source = layer.source()
            if len(source) > 50:
                source_text = f"...{source[-47:]}"
            else:
                source_text = source
            item.setText(4, source_text)
            
            # Encoding
            encoding = layer.dataProvider().encoding()
            item.setText(5, encoding if encoding else "UTF-8")
            
            # Approximate size (estimation based on features)
            feature_count = layer.featureCount()
            field_count = len(layer.fields())
            estimated_size = (feature_count * field_count * 50) // 1024  # Estimation en Ko
            item.setText(6, f"{estimated_size}")
            
            # Geographic extent
            extent = layer.extent()
            if extent.isNull():
                extent_text = "Invalid extent"
            else:
                extent_text = f"X: {extent.xMinimum():.2f} à {extent.xMaximum():.2f}, Y: {extent.yMinimum():.2f} à {extent.yMaximum():.2f}"
                if len(extent_text) > 80:
                    extent_text = f"X: {extent.xMinimum():.1f}→{extent.xMaximum():.1f}, Y: {extent.yMinimum():.1f}→{extent.yMaximum():.1f}"
            item.setText(7, extent_text)
            
            # Store layer reference
            item.setData(0, UserRole, layer)
            
            # Plugin Tabler icons based on geometry type
            try:
                if 'Point' in geom_type:
                    item.setIcon(0, ui_icon("point_layer"))
                elif 'Line' in geom_type:
                    item.setIcon(0, ui_icon("line_layer"))
                elif 'Polygon' in geom_type:
                    item.setIcon(0, ui_icon("polygon_layer"))
                else:
                    item.setIcon(0, ui_icon("layer"))
            except (AttributeError, Exception):
                # If QGIS icons are not available, continue without icon
                pass
            
            # Color according to layer status
            if not layer.isValid():
                for col in range(8):
                    item.setBackground(col, QColor(255, 0, 0))
            elif layer.featureCount() == 0:
                for col in range(8):
                    item.setBackground(col, QColor(255, 255, 0))
    
    def get_selected_layers(self):
        """Return selected layers"""
        selected_layers = []
        for item in self.layers_tree.selectedItems():
            layer = item.data(0, UserRole)
            if layer and layer.isValid():
                selected_layers.append(layer)
        return selected_layers
    
    def remove_selected_layers(self):
        """Remove selected layers from QGIS project"""
        if not EXPORT_AVAILABLE:
            return
            
        selected_layers = self.get_selected_layers()
        
        if not selected_layers:
            self.message_bar.pushWarning("Attention", "Please select at least one layer")
            return
        
        # Ask for confirmation
        layer_names = ", ".join([layer.name() for layer in selected_layers])
        reply = QMessageBox.question(
            self, 
            "Confirmation of deletion",
            f"Do you really want to remove these {len(selected_layers)} layer(s) from the project?\n\n{layer_names}",
            MsgBoxYes | MsgBoxNo,
            MsgBoxNo
        )
        
        if reply == MsgBoxYes:
            project = QgsProject.instance()
            removed_count = 0
            
            for layer in selected_layers:
                # Store layer name before deletion to avoid RuntimeError
                layer_name = layer.name()
                layer_id = layer.id()
                
                try:
                    project.removeMapLayer(layer_id)
                    removed_count += 1
                    QgsMessageLog.logMessage(f"Layer removed: {layer_name}", "Transformer", MsgInfo)
                except Exception as e:
                    QgsMessageLog.logMessage(f"Error removing layer {layer_name}: {str(e)}", "Transformer", MsgWarning)
            
            # Refresh the list
            self.refresh_layers()
            
            # Message of success
            self.message_bar.pushSuccess(
                "Deletion successful", 
                f"{removed_count} layer(s) removed from the project"
            )
    
    def export_layers(self):
        """Export selected layer(s) using the current format and scope options."""
        if not EXPORT_AVAILABLE:
            return

        selected_layers = self.get_selected_layers()
        if not selected_layers:
            self.message_bar.pushWarning("Attention", "Please select at least one layer")
            return

        export_format = self.format_combo.currentData()
        if not export_format:
            self.message_bar.pushWarning("Attention", "Please select a valid export format")
            return

        selected_features_only = (
            hasattr(self, "selected_features_only_cb")
            and self.selected_features_only_cb.isChecked()
        )

        if selected_features_only:
            if len(selected_layers) > 1:
                self.message_bar.pushWarning(
                    "Attention",
                    "Selected features only: choose a single layer",
                )
                return
            layer = selected_layers[0]
            if layer.selectedFeatureCount() == 0:
                self.message_bar.pushWarning(
                    "Attention", "No features selected on the map for this layer"
                )
                return
            self._export_single_layer_file(layer, selected_features_only=True)
            return

        if len(selected_layers) == 1:
            self._export_single_layer_file(selected_layers[0], selected_features_only=False)
        else:
            self._export_multiple_layers(selected_layers)

    def _export_single_layer_file(self, layer, selected_features_only=False):
        """Export one layer to a file chosen by the user."""
        export_format = self.format_combo.currentData()
        ext = self.export_manager.format_extensions.get(export_format, ".shp")
        filter_text = f"{export_format.value} (*{ext})"

        default_name = layer.name()
        if selected_features_only:
            default_name = f"{layer.name()}_selection"
        dialog_title = (
            "Save selected features" if selected_features_only else "Save layer"
        )

        output_path, _ = QFileDialog.getSaveFileName(
            self, dialog_title, f"{default_name}{ext}", filter_text
        )
        if not output_path:
            return

        self.message_bar.clearWidgets()
        if selected_features_only:
            selected_count = layer.selectedFeatureCount()
            progress_msg = (
                f"Exporting {selected_count} selected feature(s) from '{layer.name()}'..."
            )
        else:
            progress_msg = f"Exporting '{layer.name()}' to {os.path.basename(output_path)}..."
        self.message_bar.pushInfo("Export in progress", progress_msg)

        selected_encoding = self.get_selected_encoding()
        success, message = self.export_manager.export_layer(
            layer,
            output_path,
            export_format,
            selected_features_only=selected_features_only,
            encoding=selected_encoding,
        )

        if success:
            self.message_bar.pushSuccess(
                "Export successful",
                f"{message} — {os.path.basename(output_path)}",
            )
        else:
            self.message_bar.pushCritical("Export error", message)

    def _export_multiple_layers(self, selected_layers):
        """Export several layers to a folder or a single GeoPackage file."""
        export_format = self.format_combo.currentData()
        selected_encoding = self.get_selected_encoding()

        if export_format == ExportFormat.GEOPACKAGE and self._use_single_geopackage_export():
            default_name = "export.gpkg"
            if len(selected_layers) == 1:
                default_name = f"{selected_layers[0].name()}.gpkg"

            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "Enregistrer le GeoPackage",
                default_name,
                "GeoPackage (*.gpkg)",
            )

            if not output_path:
                return

            if not output_path.lower().endswith(".gpkg"):
                output_path += ".gpkg"

            self.message_bar.clearWidgets()
            self.message_bar.pushInfo(
                "Export GeoPackage en cours",
                f"Export de {len(selected_layers)} couche(s) vers {os.path.basename(output_path)}...",
            )

            success, message, exported_count, failed_count = (
                self.export_manager.export_layers_to_single_geopackage(
                    selected_layers, output_path, encoding=selected_encoding
                )
            )

            self.message_bar.clearWidgets()
            if success:
                self.message_bar.pushSuccess("Export GeoPackage terminé", message)
            elif exported_count > 0:
                self.message_bar.pushWarning("Export GeoPackage partiel", message)
            else:
                self.message_bar.pushCritical("Export GeoPackage échoué", message)
            return
        
        # Select the destination folder
        output_dir = QFileDialog.getExistingDirectory(
            self, f"Select the folder for export in {export_format.value}"
        )
        
        if not output_dir:
            return
        
        # Export statistics
        exported_count = 0
        failed_count = 0
        total_features = 0
        
        # Export each layer
        for i, layer in enumerate(selected_layers, 1):
            # Output file name with appropriate extension
            ext = self.export_manager.format_extensions.get(export_format, ".shp")
            output_path = os.path.join(output_dir, f"{layer.name()}{ext}")
            
            # Detailed progress message
            self.message_bar.clearWidgets()
            self.message_bar.pushInfo(
                "Export batch in progress",
                f"[{i}/{len(selected_layers)}] {layer.name()} ({layer.featureCount()} features) → {export_format.value}..."
            )
            # Execute the export with encoding support
            success, message = self.export_manager.export_layer(
                layer, output_path, export_format, 
                selected_features_only=False, encoding=selected_encoding
            )
            
            if success:
                exported_count += 1
                total_features += layer.featureCount()
                QgsMessageLog.logMessage(
                    f"Export batch [{i}/{len(selected_layers)}] - {layer.name()} → {os.path.basename(output_path)}",
                    "Transformer", MsgInfo
                )
            else:
                failed_count += 1
                QgsMessageLog.logMessage(
                    f" Failed export batch [{i}/{len(selected_layers)}] - {layer.name()}: {message}",
                    "Transformer", MsgWarning
                )
        
        # Final report
        self.message_bar.clearWidgets()
        if failed_count == 0:
            self.message_bar.pushSuccess(
                "Export batch completed",
                f" {exported_count} layer(s) exported ({total_features} features) to {output_dir}"
            )
        elif exported_count > 0:
            self.message_bar.pushWarning(
                "Export batch completed with errors",
                f" {exported_count} successes, {failed_count} failures - Total: {total_features} features"
            )
        else:
            self.message_bar.pushCritical(
                "Export batch failed",
                f" All exports failed ({failed_count}/{len(selected_layers)})"
            )
    
    def _load_encoding_config(self):
        """Load encoding configuration from QGIS settings"""
        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            
            # Key for this plugin configuration
            config_key = "Transformer/export_encoding"
            saved_encoding = settings.value(config_key, "utf-8")
            
            # Find the corresponding index in the combobox
            for i in range(self.encoding_combo.count()):
                if self.encoding_combo.itemData(i) == saved_encoding:
                    self.encoding_combo.setCurrentIndex(i)
                    break
            else:
                # If the saved encoding is not found, use UTF-8 (index 0)
                self.encoding_combo.setCurrentIndex(0)
                
        except (ImportError, Exception):
            # In case of error, use UTF-8 by default
            self.encoding_combo.setCurrentIndex(0)
    
    def _save_encoding_config(self):
        """Save encoding configuration in QGIS settings"""
        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            
            # Get the selected encoding
            current_encoding = self.encoding_combo.currentData()
            if current_encoding:
                config_key = "Transformer/export_encoding"
                settings.setValue(config_key, current_encoding)
                
                # Log for debugging
                QgsMessageLog.logMessage(
                    f"Export encoding saved: {current_encoding}",
                    "Transformer", MsgInfo
                )
                
        except (ImportError, Exception) as e:
            # In case of save error, continue without crashing
            QgsMessageLog.logMessage(
                f"Encoding save error: {str(e)}",
                "Transformer", MsgWarning
            )
    
    def get_selected_encoding(self):
        """Return the selected encoding by the user"""
        return self.encoding_combo.currentData() or "utf-8"
