"""
Secure export module for Transformer plugin
QGIS compat across versions
"""

import os
from enum import Enum

# Secure imports w/ error handling
EXPORT_AVAILABLE = False
try:
    # QGIS core
    from qgis.core import (QgsProject, QgsVectorLayer, QgsVectorFileWriter, 
                           QgsMessageLog, Qgis, QgsWkbTypes, QgsApplication)
    from qgis.gui import QgsMessageBar
    
    # Qt
    try:
        from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt
        from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                                         QTreeWidget, QTreeWidgetItem, QPushButton, 
                                         QComboBox, QLabel, QMessageBox, QFileDialog)
    except ImportError:
        from PyQt5.QtCore import QObject, pyqtSignal, Qt
        from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                                     QTreeWidget, QTreeWidgetItem, QPushButton, 
                                     QComboBox, QLabel, QMessageBox, QFileDialog)
    
    EXPORT_AVAILABLE = True
    
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
    GPKG = "GeoPackage (GPKG)"
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
            ExportFormat.GPKG: ".gpkg",
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
            ExportFormat.GPKG: "GPKG",
            ExportFormat.DXF: "DXF",
            ExportFormat.TAB: "MapInfo File",
            ExportFormat.GML: "GML",
            ExportFormat.SQLITE: "SQLite",
            ExportFormat.FLATGEOBUF: "FlatGeobuf"
        }
        
        # Formats supporting geometry
        self.geometry_formats = {
            ExportFormat.SHAPEFILE, ExportFormat.GEOPACKAGE, ExportFormat.GEOJSON,
            ExportFormat.KML, ExportFormat.GPKG, ExportFormat.DXF, ExportFormat.TAB,
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
                
                if error_code == QgsVectorFileWriter.NoError:
                    success, message = True, f"Export réussi : {feature_count} entité(s)"
                else:
                    success, message = False, f"Erreur d'export : {error_message}"
            
            # Log detail
            if success:
                QgsMessageLog.logMessage(
                    f" Export successful - Layer: {layer.name()}, Format: {export_format.value}, "
                    f"Features: {feature_count}, Size: {self._get_file_size(output_path)} Ko",
                    "Transformer", Qgis.Success
                )
            else:
                QgsMessageLog.logMessage(
                    f" Export failed - Layer: {layer.name()}, Error: {message}",
                    "Transformer", Qgis.Critical
                )
            
            return success, message
                
        except Exception as e:
            error_msg = f"Unexpected error during export : {str(e)}"
            QgsMessageLog.logMessage(f" {error_msg}", "Transformer", Qgis.Critical)
            return False, error_msg
    
    def _configure_format_options(self, export_format, options, layer):
        """Config fmt specific opts"""
        if export_format == ExportFormat.SHAPEFILE:
            options.layerOptions = ['ENCODING=UTF-8']
        elif export_format == ExportFormat.GEOPACKAGE or export_format == ExportFormat.GPKG:
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
            
            if error_code == QgsVectorFileWriter.NoError:
                return True, f"Export tabular successful : {layer.featureCount()} records"
            else:
                return False, f"Export tabular error : {error_message}"
                
        except Exception as e:
            return False, f"Export tabular error : {str(e)}"
    
    def _get_file_size(self, file_path):
        """File size in Ko"""
        try:
            import os
            return os.path.getsize(file_path) // 1024
        except:
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
            self.refresh_layers()
    
    def setup_fallback_ui(self):
        """Fallback interface if the module is not available"""
        layout = QVBoxLayout()
        
        label = QLabel("Export functionality not available")
        label.setStyleSheet("color: red; font-weight: bold;")
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
        self.layers_tree.setSelectionMode(QTreeWidget.MultiSelection)
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
        remove_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; font-weight: bold; }")
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
                          ExportFormat.KML, ExportFormat.GPKG, ExportFormat.GML, ExportFormat.FLATGEOBUF]
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
        
        # Export buttons
        export_layout = QHBoxLayout()
        
        export_single_btn = QPushButton("Export single layer")
        export_single_btn.clicked.connect(self.export_single_layer)
        export_layout.addWidget(export_single_btn)
        
        export_multiple_btn = QPushButton("Export multiple layers")
        export_multiple_btn.clicked.connect(self.export_multiple_layers)
        export_multiple_btn.setStyleSheet("background-color: #4ecdc4; color: white; font-weight: bold;")
        export_layout.addWidget(export_multiple_btn)
        
        # Export selection features button
        export_selection_btn = QPushButton("Export selection features")
        export_selection_btn.clicked.connect(self.export_selected_features)
        export_selection_btn.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold;")
        export_layout.addWidget(export_selection_btn)
        
        layout.addLayout(export_layout)
        
        # Message bar
        self.message_bar = QgsMessageBar()
        layout.addWidget(self.message_bar)
        
        self.setLayout(layout)
    
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
            item.setData(0, Qt.UserRole, layer)
            
            # Native QGIS icons based on geometry type
            try:
                if 'Point' in geom_type:
                    # Native QGIS point layer icon
                    icon = QgsApplication.getThemeIcon("/mIconPointLayer.svg")
                    if not icon.isNull():
                        item.setIcon(0, icon)
                elif 'Line' in geom_type:
                    # Native QGIS line layer icon
                    icon = QgsApplication.getThemeIcon("/mIconLineLayer.svg")
                    if not icon.isNull():
                        item.setIcon(0, icon)
                elif 'Polygon' in geom_type:
                    # Native QGIS polygon layer icon
                    icon = QgsApplication.getThemeIcon("/mIconPolygonLayer.svg")
                    if not icon.isNull():
                        item.setIcon(0, icon)
                else:
                    # Generic geometry (ex: GeometryCollection)
                    icon = QgsApplication.getThemeIcon("/mIconLayer.svg")
                    if not icon.isNull():
                        item.setIcon(0, icon)
            except (AttributeError, Exception):
                # If QGIS icons are not available, continue without icon
                pass
            
            # Color according to layer status
            if not layer.isValid():
                for col in range(8):
                    item.setBackground(col, Qt.red)
            elif layer.featureCount() == 0:
                for col in range(8):
                    item.setBackground(col, Qt.yellow)
    
    def get_selected_layers(self):
        """Return selected layers"""
        selected_layers = []
        for item in self.layers_tree.selectedItems():
            layer = item.data(0, Qt.UserRole)
            if layer and layer.isValid():
                selected_layers.append(layer)
        return selected_layers
    
    def export_single_layer(self):
        """Export a single layer"""
        layers = self.get_selected_layers()
        if not layers:
            self.message_bar.pushWarning("Attention", "Veuillez sélectionner une couche")
            return
        
        # Export of the single layer with selected encoding
        self.export_layer_to_file(layers[0])
    
    def export_layer_to_file(self, layer):
        """Export a single layer to a selected file"""
        if not EXPORT_AVAILABLE:
            return
            
        export_format = self.format_combo.currentData()
        if not export_format:
            self.message_bar.pushWarning("Attention", "Veuillez sélectionner un format d'export valide")
            return
        
        # Dialog de sauvegarde
        ext = self.export_manager.format_extensions.get(export_format, ".shp")
        filter_text = f"{export_format.value} (*{ext})"
        
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la couche", f"{layer.name()}{ext}", filter_text
        )
        
        if not output_path:
            return
        
        # Message de progression
        self.message_bar.clearWidgets()
        self.message_bar.pushInfo(
            "Export en cours",
            f"Export de '{layer.name()}' vers {os.path.basename(output_path)}..."
        )
        QgsApplication.processEvents()
        
        # Export avec encodage sélectionné
        selected_encoding = self.get_selected_encoding()
        success, message = self.export_manager.export_layer(
            layer, output_path, export_format, selected_features_only=False, encoding=selected_encoding
        )
        
        if success:
            self.message_bar.pushSuccess(
                "Export successful",
                f" {message} - {os.path.basename(output_path)}"
            )
        else:
            self.message_bar.pushCritical("Export error", f" {message}")
    
    def export_multiple_layers(self):
        """Export multiple layers"""
        layers = self.get_selected_layers()
        if not layers:
            self.message_bar.pushWarning("Attention", "Veuillez sélectionner au moins une couche")
            return
        
        # Choisir le dossier
        output_dir = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier d'export")
        if not output_dir:
            return
        
        format_type = self.format_combo.currentData()
        if not format_type:
            return
        
        # Exporter chaque couche
        exported_count = 0
        failed_count = 0
        
        for i, layer in enumerate(layers, 1):
            self.message_bar.clearWidgets()
            self.message_bar.pushInfo("Export en cours", f"[{i}/{len(layers)}] {layer.name()}...")
            QgsApplication.processEvents()
            
            ext = self.export_manager.format_extensions.get(format_type, ".shp")
            output_path = os.path.join(output_dir, f"{layer.name()}{ext}")
            
            # Export with selected encoding
            selected_encoding = self.get_selected_encoding()
            success, message = self.export_manager.export_layer(layer, output_path, format_type, selected_features_only=False, encoding=selected_encoding)
            
            if success:
                exported_count += 1
            else:
                failed_count += 1
        
        # Final report
        self.message_bar.clearWidgets()
        if failed_count == 0:
            self.message_bar.pushSuccess("Export completed", f"{exported_count} layer(s) exported")
        else:
            self.message_bar.pushWarning("Export completed", f"{exported_count} successful, {failed_count} failed")
    
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
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            project = QgsProject.instance()
            removed_count = 0
            
            for layer in selected_layers:
                # Store layer name before deletion to avoid RuntimeError
                layer_name = layer.name()
                layer_id = layer.id()
                
                try:
                    project.removeMapLayer(layer_id)
                    removed_count += 1
                    QgsMessageLog.logMessage(f"Layer removed: {layer_name}", "Transformer", Qgis.Info)
                except Exception as e:
                    QgsMessageLog.logMessage(f"Error removing layer {layer_name}: {str(e)}", "Transformer", Qgis.Warning)
            
            # Refresh the list
            self.refresh_layers()
            
            # Message of success
            self.message_bar.pushSuccess(
                "Deletion successful", 
                f"{removed_count} layer(s) removed from the project"
            )
    
    def export_selected_features(self):
        """Export only selected features from the active layer"""
        if not EXPORT_AVAILABLE:
            return
            
        selected_layers = self.get_selected_layers()
        
        if not selected_layers:
            self.message_bar.pushWarning("Attention", "Please select a layer")
            return
            
        if len(selected_layers) > 1:
            self.message_bar.pushWarning("Attention", "Export of selection: only one layer at a time")
            return
            
        layer = selected_layers[0]
        
        if layer.selectedFeatureCount() == 0:
            self.message_bar.pushWarning("Attention", "No features selected in the layer")
            return
        
        export_format = self.format_combo.currentData()
        if not export_format:
            self.message_bar.pushWarning("Attention", "Please select a valid export format")
            return
        
        # Save dialog
        ext = self.export_manager.format_extensions.get(export_format, ".shp")
        filter_text = f"{export_format.value} (*{ext})"
        
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save selected features", f"{layer.name()}_selection{ext}", filter_text
        )
        
        if not output_path:
            return
        
        # Message of progress
        selected_count = layer.selectedFeatureCount()
        self.message_bar.clearWidgets()
        self.message_bar.pushInfo(
            "Export of selection in progress",
            f"Export of {selected_count} selected feature(s) from '{layer.name()}'..."
        )
        QgsApplication.processEvents()
        
        # Export with selection only and selected encoding
        selected_encoding = self.get_selected_encoding()
        success, message = self.export_manager.export_layer(layer, output_path, export_format, selected_features_only=True, encoding=selected_encoding)
        
        if success:
            self.message_bar.pushSuccess(
                "Export of selection successful",
                f" {message} - {os.path.basename(output_path)}"
            )
        else:
            self.message_bar.pushCritical("Export of selection error", message)
    
    def export_single_layer(self):
        """Export a single layer with format selection"""
        if not EXPORT_AVAILABLE:
            return
            
        selected_layers = self.get_selected_layers()
        
        if not selected_layers:
            self.message_bar.pushWarning("Attention", "Please select a layer")
            return
            
        if len(selected_layers) > 1:
            self.message_bar.pushWarning("Attention", "Please select a single layer for the single layer export")
            return
            
        layer = selected_layers[0]
        export_format = self.format_combo.currentData()
        
        if not export_format:
            self.message_bar.pushWarning("Attention", "Please select a valid export format")
            return
        
        # Determine the extension and file filter
        ext = self.export_manager.format_extensions.get(export_format, ".shp")
        filter_text = f"{export_format.value} (*{ext})"
        
        # Save dialog with appropriate format
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save export", f"{layer.name()}{ext}", filter_text
        )
        
        if not output_path:
            return
        
        # Message of progress
        self.message_bar.clearWidgets()
        self.message_bar.pushInfo("Export in progress", f"Export of '{layer.name()}' in {export_format.value}...")
        QgsApplication.processEvents()
        
        # Execute the export
        success, message = self.export_manager.export_layer(layer, output_path, export_format)
        
        # Display the result
        if success:
            self.message_bar.pushSuccess("Export successful", f"{message} - {os.path.basename(output_path)}")
        else:
            self.message_bar.pushCritical("Export error", message)
    
    def export_multiple_layers(self):
        """Export multiple layers to a folder with chosen format"""
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
            QgsApplication.processEvents()
            
            # Execute the export with the new API
            success, message = self.export_manager.export_layer(layer, output_path, export_format)
            
            if success:
                exported_count += 1
                total_features += layer.featureCount()
                QgsMessageLog.logMessage(
                    f"Export batch [{i}/{len(selected_layers)}] - {layer.name()} → {os.path.basename(output_path)}",
                    "Transformer", Qgis.Info
                )
            else:
                failed_count += 1
                QgsMessageLog.logMessage(
                    f" Failed export batch [{i}/{len(selected_layers)}] - {layer.name()}: {message}",
                    "Transformer", Qgis.Warning
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
                    "Transformer", Qgis.Info
                )
                
        except (ImportError, Exception) as e:
            # In case of save error, continue without crashing
            QgsMessageLog.logMessage(
                f"Encoding save error: {str(e)}",
                "Transformer", Qgis.Warning
            )
    
    def get_selected_encoding(self):
        """Return the selected encoding by the user"""
        return self.encoding_combo.currentData() or "utf-8"
