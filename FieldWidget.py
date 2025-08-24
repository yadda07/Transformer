# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QTreeWidget, 
    QTreeWidgetItem, QGroupBox, QLabel, QMessageBox, QDialog
)

# Import QSizePolicy with fallback
try:
    from qgis.PyQt.QtWidgets import QSizePolicy
except ImportError:
    try:
        from PyQt5.QtWidgets import QSizePolicy
    except ImportError:
        class QSizePolicy:
            Expanding = 7
            Preferred = 5
            def __init__(self, h=None, v=None):
                pass
from qgis.PyQt.QtGui import QIcon

# Import QFont with fallback
try:
    from qgis.PyQt.QtGui import QFont
except ImportError:
    try:
        from PyQt5.QtGui import QFont
    except ImportError:
        class QFont:
            def __init__(self, family="Arial", size=9, weight=None):
                pass
            class Bold:
                pass
from qgis.core import QgsMessageLog, Qgis, QgsWkbTypes

# Import classes directly to avoid circular imports
from .FieldDefinitionDialog import FieldDefinitionDialog

class FieldWidget(QWidget):
    """Widget for managing calculated fields"""
    
    field_added = pyqtSignal(str, str)  # name, expression
    field_removed = pyqtSignal(str)
    field_modified = pyqtSignal(str, str, str)  # old_name, new_name, expression
    
    def __init__(self, expression_widget=None, parent=None):
        super().__init__(parent)
        self.calculated_fields = {}
        self.expression_widget = expression_widget
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """Configure the interface of the simplified fields widget"""
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header with actions
        header_layout = QHBoxLayout()
        
        header_label = QLabel("Calculated Fields")
        header_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        header_layout.addWidget(header_label)
        
        header_layout.addStretch()
        
        # Column management actions - Enhanced visibility
        self.copy_all_btn = QPushButton("Copy All")
        self.copy_all_btn.setMinimumWidth(80)
        self.copy_all_btn.setMinimumHeight(32)
        self.copy_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(highlight);
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
        """)
        self.copy_all_btn.setToolTip("Copy all existing fields from ALL selected vector files")
        
        self.add_field_btn = QPushButton("➕ Add Column")
        self.add_field_btn.setMinimumWidth(100)
        self.add_field_btn.setMinimumHeight(32)
        self.add_field_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(highlight);
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
        """)
        self.add_field_btn.setToolTip("Add a new calculated field (column) to the output table")
        
        self.edit_field_btn = QPushButton("✏️ Edit")
        self.edit_field_btn.setMinimumWidth(70)
        self.edit_field_btn.setMinimumHeight(32)
        self.edit_field_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(highlight);
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
            QPushButton:disabled {
                background-color: palette(button);
                color: palette(disabled-text);
                border: 1px solid palette(disabled-text);
            }
        """)
        self.edit_field_btn.setEnabled(False)
        self.edit_field_btn.setToolTip("Edit the selected field")
        
        self.remove_field_btn = QPushButton("🗑️ Remove")
        self.remove_field_btn.setMinimumWidth(80)
        self.remove_field_btn.setMinimumHeight(32)
        self.remove_field_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(highlight);
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
            QPushButton:disabled {
                background-color: palette(button);
                color: palette(disabled-text);
                border: 1px solid palette(disabled-text);
            }
        """)
        self.remove_field_btn.setEnabled(False)
        self.remove_field_btn.setToolTip("Remove the selected field")
        
        # Clear all fields button
        self.clear_all_btn = QPushButton("🗑️ Clear All")
        self.clear_all_btn.setMinimumWidth(90)
        self.clear_all_btn.setMinimumHeight(32)
        self.clear_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid palette(highlight);
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
        """)
        self.clear_all_btn.setToolTip("Clear all configured fields and reset manual configuration")
        
        header_layout.addWidget(self.copy_all_btn)
        header_layout.addWidget(self.add_field_btn)
        header_layout.addWidget(self.edit_field_btn)
        header_layout.addWidget(self.remove_field_btn)
        header_layout.addWidget(self.clear_all_btn)
        
        layout.addLayout(header_layout)
        
        # Liste simple des champs - EXPANSION VERTICALE PRIORITAIRE
        self.fields_tree = QTreeWidget()
        self.fields_tree.setHeaderLabels(["Field"])
        self.fields_tree.setAlternatingRowColors(True)
        self.fields_tree.setRootIsDecorated(False)
        # SUPPRIMER la limitation de hauteur pour permettre l'expansion
        # self.fields_tree.setMaximumHeight(150)  # <- SUPPRIMÉ
        self.fields_tree.setMinimumHeight(100)  # Hauteur minimum seulement
        
        # Configurer pour expansion verticale optimale
        self.fields_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        layout.addWidget(self.fields_tree, 1)  # stretch=1 pour expansion prioritaire
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure the signal connections"""
        self.fields_tree.itemSelectionChanged.connect(self.on_field_selection_changed)
        self.fields_tree.itemDoubleClicked.connect(self.edit_selected_field)
        
        self.copy_all_btn.clicked.connect(self.copy_all_fields)
        self.add_field_btn.clicked.connect(self.add_field)
        self.edit_field_btn.clicked.connect(self.edit_selected_field)
        self.remove_field_btn.clicked.connect(self.remove_selected_field)
        self.clear_all_btn.clicked.connect(self.clear_all_fields)
        
        # Connect expression widget changes 
        if self.expression_widget:
            # Try to connect to the expression changed signal
            try:
                self.expression_widget.expression_changed.connect(self.on_expression_changed)
            except AttributeError:
                try:
                    self.expression_widget.textChanged.connect(self.on_expression_changed)
                except AttributeError:
                    try:
                        self.expression_widget.expressionChanged.connect(self.on_expression_changed)
                    except AttributeError:
                        pass  # No suitable signal found
    
    def add_field(self):
        """Add a new calculated field"""
        # Get the expression from the QGIS native expression builder
        expression = ""
        if self.expression_widget:
            expression = self.expression_widget.get_expression().strip()
            if not expression:
                QMessageBox.warning(self, "Warning", "No expression found in the Expression Builder.\nPlease create an expression first.")
                return
        
        dialog = FieldDefinitionDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            name, description = dialog.get_field_info()
            self.add_calculated_field(name, expression, description)
    
    def copy_all_fields(self):
        """Create separate configurations for each selected vector file with their own table names"""
        # Get all selected layers from the parent interface
        selected_layers = []
        
        # Search for the parent interface (EnhancedTransformerDialog)
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'shp_tree') and hasattr(parent_widget, 'loaded_shapefiles'):
                # Get all selected vector files from the tree
                selected_items = parent_widget.shp_tree.selectedItems()
                parent_widget.log_message(f"DEBUG Copy All: Found {len(selected_items)} selected items", "Info")
                for item in selected_items:
                    filename = item.data(0, Qt.UserRole)
                    if filename in parent_widget.loaded_shapefiles:
                        layer = parent_widget.loaded_shapefiles[filename]['layer']
                        selected_layers.append((filename, layer))
                        parent_widget.log_message(f"DEBUG Copy All: Added layer {filename}", "Info")
                    else:
                        parent_widget.log_message(f"DEBUG Copy All: Filename {filename} not in loaded_shapefiles", "Warning")
                break
            parent_widget = parent_widget.parent()
        
        if not selected_layers:
            QMessageBox.warning(self, "Warning", "No vector files selected. Please select one or more vector files first.")
            return
        
        # Create separate configuration for each selected file
        configs_created = 0
        created_configs = []  # Store created configuration names for feedback
        
        parent_widget.log_message(f"Starting Copy All: creating {len(selected_layers)} separate configurations...", "Info")
        
        for filename, layer in selected_layers:
            try:
                # Get fields from this specific layer
                layer_fields = {}
                
                # Add all attribute fields
                for field in layer.fields():
                    field_name = field.name()
                    layer_fields[field_name] = f'"{field_name}"'
                
                # Add geometry field with reprojection if configured
                geometry_expression = "$geometry"
                # Check for target_crs in current widget or parent widget
                target_crs_obj = None
                if hasattr(self, 'target_crs') and self.target_crs:
                    target_crs_obj = self.target_crs
                elif hasattr(parent_widget, 'target_crs') and parent_widget.target_crs:
                    target_crs_obj = parent_widget.target_crs
                
                if target_crs_obj:
                    # Get the source CRS from the layer
                    source_crs = layer.crs().authid()
                    if hasattr(target_crs_obj, 'authid'):
                        target_crs_code = target_crs_obj.authid()
                        geometry_expression = f"transform($geometry, '{source_crs}', '{target_crs_code}')"
                    elif isinstance(target_crs_obj, str):
                        geometry_expression = f"transform($geometry, '{source_crs}', '{target_crs_obj}')"
                
                if layer.geometryType() != QgsWkbTypes.NullGeometry:
                    layer_fields["geometry"] = geometry_expression
                
                # Create table name with _transformed suffix
                base_name = os.path.splitext(filename)[0]
                table_name = f"{base_name}_transformed"
                
                # Get source file path
                source_file_path = parent_widget.loaded_shapefiles[filename]['path']
                
                # Create filter config (empty by default)
                filter_config = {"enabled": False, "expression": ""}
                
                # Get target CRS if configured (same logic as geometry expression)
                target_crs = None
                if target_crs_obj:
                    if hasattr(target_crs_obj, 'authid'):
                        target_crs = target_crs_obj.authid()
                    elif isinstance(target_crs_obj, str):
                        target_crs = target_crs_obj
                
                # Save configuration via config_manager
                success = parent_widget.config_manager.add_table_config(
                    table_name,
                    source_file_path,
                    layer_fields,
                    filter_config,
                    target_crs,
                    geometry_expression,
                    force_replace=True
                )
                
                if success:
                    configs_created += 1
                    created_configs.append(table_name)
                    parent_widget.log_message(f"Created configuration '{table_name}' with {len(layer_fields)} fields", "Success")
                else:
                    parent_widget.log_message(f"Failed to create configuration for '{filename}'", "Error")
                    
            except Exception as e:
                parent_widget.log_message(f"Error creating configuration for '{filename}': {str(e)}", "Error")
        
        # Save all configurations to calculated_fields_config.json
        first_table_name = None
        if configs_created > 0:
            parent_widget.config_manager.save_config()
            
            # Enhanced feedback with configuration names
            config_list = "', '".join(created_configs)
            parent_widget.log_message(f"Copy All completed! Created {configs_created} configurations: '{config_list}'", "Success")
            
            # Store the first table name to load it automatically
            if created_configs:
                first_table_name = created_configs[0]
        
        # Update the configuration list UI in parent
        if hasattr(parent_widget, 'update_configuration_dropdown'):
            parent_widget.update_configuration_dropdown()
        
        # Auto-load the first configuration created to keep interface active
        if first_table_name and hasattr(parent_widget, 'load_table_config_by_name'):
            parent_widget.load_table_config_by_name(first_table_name)
            parent_widget.log_message(f"Auto-loaded configuration '{first_table_name}' - Use dropdown to switch between {configs_created} configurations", "Info")
        elif configs_created == 0:
            # Only clear if no configs were created (error case)
            self.calculated_fields.clear()
            self.refresh_fields_list()
    
    def clear_all_fields(self):
        """Clear all configured fields and reset manual configuration - supports multiple selection"""
        # Get all selected files from the parent interface
        selected_files = []
        configurations_to_clear = []
        
        # Search for the parent interface (EnhancedTransformerDialog)
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'shp_tree') and hasattr(parent_widget, 'loaded_shapefiles'):
                # Get all selected vector files from the tree
                selected_items = parent_widget.shp_tree.selectedItems()
                
                # Debug: Log selection info
                if hasattr(parent_widget, 'log_message'):
                    parent_widget.log_message(f"DEBUG: Found {len(selected_items)} selected items", "Info")
                
                for item in selected_items:
                    filename = item.data(0, Qt.UserRole)
                    if hasattr(parent_widget, 'log_message'):
                        parent_widget.log_message(f"DEBUG: Processing item: {filename}", "Info")
                    
                    if filename in parent_widget.loaded_shapefiles:
                        selected_files.append(filename)
                        
                        # Check for saved configurations for this file
                        if hasattr(parent_widget, 'config_manager'):
                            tables = parent_widget.config_manager.get_tables_for_source(filename)
                            if hasattr(parent_widget, 'log_message'):
                                parent_widget.log_message(f"DEBUG: Found {len(tables)} tables for {filename}: {tables}", "Info")
                            configurations_to_clear.extend(tables)
                break
            parent_widget = parent_widget.parent()
        
        # Debug: Log final selection
        if hasattr(parent_widget, 'log_message'):
            parent_widget.log_message(f"DEBUG: Selected files: {selected_files}", "Info")
            parent_widget.log_message(f"DEBUG: Configurations to clear: {configurations_to_clear}", "Info")
        
        # If no files selected, clear current fields only
        if not selected_files:
            reply = QMessageBox.question(
                self, "Clear All Fields",
                "This will remove all configured fields.\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Clear all fields
                self.calculated_fields.clear()
                self.refresh_fields_list()
                
                # Reset the manual configuration flag in parent
                parent_widget = self.parent()
                while parent_widget:
                    if hasattr(parent_widget, '_manual_fields_configured'):
                        parent_widget._manual_fields_configured = False
                        # Force configuration preview update
                        if hasattr(parent_widget, 'update_configuration_preview'):
                            parent_widget.update_configuration_preview()
                        if hasattr(parent_widget, 'log_message'):
                            parent_widget.log_message("All fields cleared - auto-configuration restored", "Info")
                        break
                    parent_widget = parent_widget.parent()
            return
        
        # Multiple files selected - show confirmation for clearing configurations
        files_count = len(selected_files)
        configs_count = len(configurations_to_clear)
        
        config_info = f" and {configs_count} saved configuration(s)" if configs_count > 0 else ""
        
        reply = QMessageBox.question(
            self, "Clear Configurations",
            f"This will clear configurations for {files_count} selected file(s){config_info}:\n\n"
            f"Files: {', '.join([f[:20] + '...' if len(f) > 20 else f for f in selected_files[:3]])}"
            f"{'...' if len(selected_files) > 3 else ''}\n\n"
            f"• Current calculated fields will be cleared\n"
            f"• Saved configurations will be removed{config_info}\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Clear current fields
            self.calculated_fields.clear()
            self.refresh_fields_list()
            
            # Remove saved configurations
            removed_configs = 0
            if configurations_to_clear and hasattr(parent_widget, 'config_manager'):
                for table_name in configurations_to_clear:
                    if parent_widget.config_manager.remove_table_config(table_name):
                        removed_configs += 1
                
                # Save the updated configuration
                parent_widget.config_manager.save_config()
            
            # Reset the manual configuration flag in parent
            parent_widget = self.parent()
            while parent_widget:
                if hasattr(parent_widget, '_manual_fields_configured'):
                    parent_widget._manual_fields_configured = False
                    # Force configuration preview update
                    if hasattr(parent_widget, 'update_configuration_preview'):
                        parent_widget.update_configuration_preview()
                    if hasattr(parent_widget, 'log_message'):
                        message = f"Cleared configurations for {files_count} file(s)"
                        if removed_configs > 0:
                            message += f" - {removed_configs} saved configuration(s) removed"
                        parent_widget.log_message(message, "Info")
                    break
                parent_widget = parent_widget.parent()
    
    def add_quick_field(self, name, expression):
        """Add a quick field"""
        # Check if the name already exists
        counter = 1
        original_name = name
        while name in self.calculated_fields:
            name = f"{original_name}_{counter}"
            counter += 1
        
        self.add_calculated_field(name, expression)
    
    def add_calculated_field(self, name, expression, description=""):
        """Add a calculated field"""
        if name in self.calculated_fields:
            QMessageBox.warning(self, "Warning", f"Field '{name}' already exists")
            return
        
        self.calculated_fields[name] = {
            "expression": expression,
            "description": description
        }
        
        self.refresh_fields_list()
        self.field_added.emit(name, expression)
    
    def edit_selected_field(self):
        """Edit the selected field"""
        current_item = self.fields_tree.currentItem()
        if not current_item:
            return
        
        field_name = current_item.text(0)
        field_info = self.calculated_fields.get(field_name, {})
        
        # Pre-fill the expression in the calculator if available
        if self.expression_widget and field_info.get("expression"):
            self.expression_widget.set_expression(field_info.get("expression"))
        
        dialog = FieldDefinitionDialog(self)
        dialog.set_field_info(field_name, field_info.get("description", ""))
        
        if dialog.exec_() == QDialog.Accepted:
            new_name, new_description = dialog.get_field_info()
            
            # Get the current expression from the calculator
            expression = ""
            if self.expression_widget:
                expression = self.expression_widget.get_expression().strip()
            
            # Remove the old field
            del self.calculated_fields[field_name]
            
            # Add the new field
            self.calculated_fields[new_name] = {
                "expression": expression,
                "description": new_description
            }
            
            self.refresh_fields_list()
            self.field_modified.emit(field_name, new_name, expression)
    
    def remove_selected_field(self):
        """Remove the selected field"""
        current_item = self.fields_tree.currentItem()
        if not current_item:
            return
        
        field_name = current_item.text(0)
        
        reply = QMessageBox.question(
            self, "Confirm Removal",
            f"Remove field '{field_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            del self.calculated_fields[field_name]
            self.refresh_fields_list()
            self.field_removed.emit(field_name)
    
    def refresh_fields_list(self):
        """Refresh the list of fields"""
        self.fields_tree.clear()
        
        for field_name, field_info in self.calculated_fields.items():
            item = QTreeWidgetItem(self.fields_tree)
            item.setText(0, field_name)
            
            expression = field_info.get("expression", "")
            
            # Tooltip with complete expression
            item.setToolTip(0, f"{field_name}: {expression}")
            
            # Icon according to type
            if "geometry" in expression.lower():
                item.setIcon(0, QIcon(":/images/themes/default/mIconGeometry.svg"))
            elif any(func in expression.lower() for func in ["now(", "date", "time"]):
                item.setIcon(0, QIcon(":/images/themes/default/mIconDateTime.svg"))
            elif any(func in expression.lower() for func in ["area", "length", "distance", "+"]):
                item.setIcon(0, QIcon(":/images/themes/default/mIconNumber.svg"))
            else:
                item.setIcon(0, QIcon(":/images/themes/default/mIconText.svg"))
    
    def guess_field_type(self, expression):
        """Guess the field type based on the expression"""
        expression_lower = expression.lower()
        
        if any(func in expression_lower for func in ["area(", "perimeter(", "length(", "distance("]):
            return "Number"
        elif any(func in expression_lower for func in ["x(", "y(", "z(", "+", "-", "*", "/"]):
            return "Number"
        elif any(func in expression_lower for func in ["now(", "age(", "year(", "month(", "day("]):
            return "DateTime"
        elif any(func in expression_lower for func in ["date", "time"]):
            return "DateTime"
        elif any(func in expression_lower for func in ["upper(", "lower(", "concat(", "substr("]):
            return "Text"
        elif "if(" in expression_lower:
            return "Conditional"
        elif any(op in expression for op in ["=", "<", ">", "AND", "OR"]):
            return "Boolean"
        else:
            return "Mixed"
    
    def on_field_selection_changed(self):
        """Handle the change of selection in the fields list"""
        has_selection = bool(self.fields_tree.currentItem())
        self.edit_field_btn.setEnabled(has_selection)
        self.remove_field_btn.setEnabled(has_selection)
        
        # Load selected field expression into calculator
        if has_selection and self.expression_widget:
            current_item = self.fields_tree.currentItem()
            if current_item:
                field_name = current_item.text(0)
                if field_name in self.calculated_fields:
                    expression = self.calculated_fields[field_name]["expression"]
                    self.expression_widget.set_expression(expression)
    
    def get_calculated_fields(self):
        """Get all calculated fields"""
        return {name: info["expression"] for name, info in self.calculated_fields.items()}
    
    def get_calculated_fields_with_geometry_info(self):
        """Get calculated fields with geometry information for config saving"""
        result = {}
        geometry_field = None
        
        for name, info in self.calculated_fields.items():
            # Check if it's a geometry field (by flag or by name)
            is_geometry_flag = info.get("is_geometry", False)
            is_geometry_name = (name == "geometry")
            
            if is_geometry_flag or is_geometry_name:
                geometry_field = info["expression"]
            else:
                result[name] = info["expression"]
        return result, geometry_field
    
    def set_calculated_fields(self, fields_dict, geometry_expression=None):
        """Set calculated fields with optional geometry expression"""
        # Get parent widget for logging
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'log_message'):
                break
            parent_widget = parent_widget.parent()
        
        if parent_widget and hasattr(parent_widget, 'log_message'):
            parent_widget.log_message(f"DEBUG: FieldWidget.set_calculated_fields called with {len(fields_dict)} fields and geometry_expression: {geometry_expression}", "Info")
        
        self.calculated_fields = {}
        
        # Add geometry field if provided
        if geometry_expression:
            self.calculated_fields["geometry"] = {
                "expression": geometry_expression,
                "description": "Geometry field",
                "is_geometry": True
            }
        
        # Add attribute fields
        for name, expression in fields_dict.items():
            self.calculated_fields[name] = {
                "expression": expression,
                "description": "",
                "is_geometry": False
            }
        
        if parent_widget and hasattr(parent_widget, 'log_message'):
            parent_widget.log_message(f"DEBUG: FieldWidget now has {len(self.calculated_fields)} total fields", "Info")
        
        self.refresh_fields_list()
        
        if parent_widget and hasattr(parent_widget, 'log_message'):
            parent_widget.log_message(f"DEBUG: FieldWidget.refresh_fields_list() completed", "Info")
            # Check if the Fields Management dock is visible
            if hasattr(parent_widget, 'fields_dock'):
                is_visible = parent_widget.fields_dock.isVisible()
                parent_widget.log_message(f"DEBUG: Fields Management dock visible: {is_visible}", "Info")
                if not is_visible:
                    parent_widget.fields_dock.setVisible(True)
                    parent_widget.log_message("DEBUG: Made Fields Management dock visible", "Info")
    
    def clear_all_fields(self):
        """Clear all fields"""
        self.calculated_fields.clear()
        self.refresh_fields_list()
    
    def on_expression_changed(self):
        """Called when expression in calculator changes - update selected field"""
        if not self.expression_widget:
            return
            
        current_item = self.fields_tree.currentItem()
        if not current_item:
            return
            
        field_name = current_item.text(0)
        new_expression = self.expression_widget.get_expression().strip()
        
        # DEBUG: Log the full expression received from widget
        QgsMessageLog.logMessage(f"DEBUG: Expression widget returned: '{new_expression}' (length: {len(new_expression)})", "Transformer", Qgis.Info)
        
        if field_name in self.calculated_fields:
            # DEBUG: Log before storing
            QgsMessageLog.logMessage(f"DEBUG: About to store expression for '{field_name}': '{new_expression}'", "Transformer", Qgis.Info)
            
            self.calculated_fields[field_name]["expression"] = new_expression
            
            # DEBUG: Log after storing
            stored_expression = self.calculated_fields[field_name]["expression"]
            QgsMessageLog.logMessage(f"DEBUG: Stored expression for '{field_name}': '{stored_expression}' (length: {len(stored_expression)})", "Transformer", Qgis.Info)
            
            if field_name == "geometry":
                self.calculated_fields[field_name]["is_geometry"] = True
            
            # Update tree display
            current_item.setText(1, new_expression)
            
            # DEBUG: Log tree display
            tree_expression = current_item.text(1)
            QgsMessageLog.logMessage(f"DEBUG: Tree displays: '{tree_expression}' (length: {len(tree_expression)})", "Transformer", Qgis.Info)
            
            # Emit signal for ALL field changes (not just geometry)
            self.field_modified.emit(field_name, field_name, new_expression)

