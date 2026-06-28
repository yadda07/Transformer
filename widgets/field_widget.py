# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QTreeWidget, 
    QTreeWidgetItem, QGroupBox, QLabel, QMessageBox, QDialog
)

from qgis.PyQt.QtWidgets import QSizePolicy
from qgis.PyQt.QtGui import QFont, QColor
from ..shared.field_icons import field_icon_for_definition, field_type_label, resolve_field_output_type
from qgis.core import QgsMessageLog, Qgis, QgsWkbTypes
from ..shared.compat import FontBold, MsgBoxNo, MsgBoxYes, UserRole, _DialogCode, _SizePolicy
from ..shared.field_classification import (
    classify_field,
    category_background,
    category_label,
    legend_categories,
    FIELD_CATEGORY_ROLE,
)

from ..shared.helpers import apply_compact_button

# Import classes directly to avoid circular imports
from .field_definition_dialog import FieldDefinitionDialog

class FieldWidget(QWidget):
    """Widget for managing calculated fields"""
    
    field_added = pyqtSignal(str, str)  # name, expression
    field_removed = pyqtSignal(str)
    field_modified = pyqtSignal(str, str, str)  # old_name, new_name, expression
    
    def __init__(self, expression_widget=None, parent=None):
        super().__init__(parent)
        self.calculated_fields = {}
        self.expression_widget = expression_widget
        self.current_layer = None
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """Configure the interface of the simplified fields widget"""
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header with actions
        header_layout = QHBoxLayout()
        
        header_label = QLabel("Calculated Fields")
        header_font = header_label.font()
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_layout.addWidget(header_label)
        
        header_layout.addStretch()
        
        # Column management actions
        # Note: "Copy All" button removed - fields now auto-populate when a table is selected.
        # The copy_all_fields() method is kept available for programmatic use.
        
        self.add_field_btn = QPushButton("Add field...")
        self.add_field_btn.setToolTip("Add a new calculated field (column) to the output table")
        apply_compact_button(self.add_field_btn)
        
        self.edit_field_btn = QPushButton("Edit field...")
        self.edit_field_btn.setEnabled(False)
        self.edit_field_btn.setToolTip("Edit the selected field")
        apply_compact_button(self.edit_field_btn)
        
        self.remove_field_btn = QPushButton("Remove")
        self.remove_field_btn.setEnabled(False)
        self.remove_field_btn.setToolTip("Remove the selected field")
        apply_compact_button(self.remove_field_btn)
        
        # Clear all fields button
        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.setToolTip("Clear all configured fields and reset manual configuration")
        apply_compact_button(self.clear_all_btn)
        
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
        self.fields_tree.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)
        
        layout.addWidget(self.fields_tree, 1)  # stretch=1 pour expansion prioritaire

        legend_layout = QHBoxLayout()
        legend_layout.setContentsMargins(0, 2, 0, 0)
        legend_layout.setSpacing(6)

        for category in legend_categories():
            chip = QLabel(category_label(category))
            chip_font = chip.font()
            chip_font.setPointSize(max(chip_font.pointSize() - 1, 7))
            chip.setFont(chip_font)
            chip.setContentsMargins(6, 2, 6, 2)
            bg = category_background(category, self.palette())
            if bg:
                chip.setStyleSheet(
                    f"background-color: {bg.name()}; border-radius: 3px; padding: 1px 4px;"
                )
            else:
                chip.setStyleSheet("padding: 1px 4px;")
            legend_layout.addWidget(chip)

        legend_layout.addStretch()
        layout.addLayout(legend_layout)
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure the signal connections"""
        self.fields_tree.itemSelectionChanged.connect(self.on_field_selection_changed)
        self.fields_tree.itemDoubleClicked.connect(self.edit_selected_field)
        
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
        if dialog.exec() == _DialogCode.Accepted:
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
                for item in selected_items:
                    item_data = item.data(0, UserRole)
                    if isinstance(item_data, dict):
                        filename = item_data.get('source_file')
                    else:
                        filename = item_data
                    
                    if filename and filename in parent_widget.loaded_shapefiles:
                        layer = parent_widget.loaded_shapefiles[filename]['layer']
                        selected_layers.append((filename, layer))
                break
            parent_widget = parent_widget.parent()
        
        if not selected_layers:
            QMessageBox.warning(self, "Warning", "No vector files selected. Please select one or more vector files first.")
            return
        
        # Create separate configuration for each selected file
        configs_created = 0
        created_configs = []  # Store created configuration names for feedback
        
        
        for filename, layer in selected_layers:
            try:
                # Get fields from this specific layer
                layer_fields = {}
                
                # Add all attribute fields
                for field in layer.fields():
                    field_name = field.name()
                    layer_fields[field_name] = f'"{field_name}"'
                
                # Add geometry field - always use $geometry without automatic transformation
                geometry_expression = "$geometry"
                
                if layer.geometryType() != QgsWkbTypes.NullGeometry:
                    layer_fields["geometry"] = geometry_expression
                
                # Create table name with _transformed suffix
                base_name = os.path.splitext(filename)[0]
                table_name = f"{base_name}_transformed"
                
                # Get source file path
                source_file_path = parent_widget.loaded_shapefiles[filename]['path']
                
                # Create filter config (empty by default)
                filter_config = {"enabled": False, "expression": ""}
                
                # No automatic CRS transformation in Copy All
                target_crs = None
                
                # Save configuration via config_manager
                result = parent_widget.config_manager.add_table_config(
                    table_name,
                    source_file_path,
                    layer_fields,
                    filter_config,
                    target_crs,
                    geometry_expression,
                    force_replace=True
                )
                success = result.get('success', False)
                
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
                
                
                for item in selected_items:
                    item_data = item.data(0, UserRole)
                    # Handle both dict and string formats
                    if isinstance(item_data, dict):
                        filename = item_data.get('source_file', '')
                    else:
                        filename = item_data if item_data else ""
                    
                    if filename and filename in parent_widget.loaded_shapefiles:
                        selected_files.append(filename)
                        
                        # Check for saved configurations for this file
                        if hasattr(parent_widget, 'config_manager'):
                            tables = parent_widget.config_manager.get_tables_for_source(filename)
                            configurations_to_clear.extend(tables)
                break
            parent_widget = parent_widget.parent()
        
        
        # If no files selected, clear current fields only
        if not selected_files:
            reply = QMessageBox.question(
                self, "Clear All Fields",
                "This will remove all configured fields.\n\nContinue?",
                MsgBoxYes | MsgBoxNo,
                MsgBoxNo
            )
            
            if reply == MsgBoxYes:
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
            MsgBoxYes | MsgBoxNo,
            MsgBoxNo
        )
        
        if reply == MsgBoxYes:
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
        
        if dialog.exec() == _DialogCode.Accepted:
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
            MsgBoxYes | MsgBoxNo
        )
        
        if reply == MsgBoxYes:
            del self.calculated_fields[field_name]
            self.refresh_fields_list()
            self.field_removed.emit(field_name)
    
    def _apply_field_item_style(self, item, field_name, field_info):
        """Apply icon, tooltip and color code to a field tree item."""
        expression = field_info.get("expression", "")
        is_geometry_field = field_info.get("is_geometry", False) or field_name == "geometry"

        category = classify_field(
            field_name,
            expression,
            source_layer=getattr(self, "current_layer", None),
            is_geometry_field=is_geometry_field,
        )
        item.setData(0, FIELD_CATEGORY_ROLE, category.value)

        label = category_label(category)
        output_type = resolve_field_output_type(
            field_name,
            expression,
            getattr(self, "current_layer", None),
            is_geometry_field,
        )
        type_label = field_type_label(output_type)
        item.setToolTip(0, f"{field_name}\nType: {type_label}\n{label}\n{expression}")

        bg = category_background(category, self.palette())
        if bg:
            item.setBackground(0, bg)
        else:
            item.setBackground(0, QColor())

        item.setIcon(0, field_icon_for_definition(
            field_name,
            expression,
            getattr(self, "current_layer", None),
            is_geometry_field,
        ))

    def refresh_fields_list(self):
        """Refresh the list of fields"""
        self.fields_tree.clear()
        
        for field_name, field_info in self.calculated_fields.items():
            item = QTreeWidgetItem(self.fields_tree)
            item.setText(0, field_name)
            self._apply_field_item_style(item, field_name, field_info)
    
    def on_field_selection_changed(self):
        """Handle field selection change"""
        selected_items = self.fields_tree.selectedItems()
        has_selection = len(selected_items) > 0
        
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
        
        # Return $geometry by default if no geometry field was found
        if geometry_field is None:
            geometry_field = "$geometry"
            
        return result, geometry_field
    
    def set_calculated_fields(self, fields_dict, geometry_expression=None):
        """Set calculated fields with optional geometry expression"""
        # Get parent widget for logging
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'log_message'):
                break
            parent_widget = parent_widget.parent()
        
        
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
        
        
        self.refresh_fields_list()
        
        # Auto-show Fields Management dock if hidden
        if parent_widget and hasattr(parent_widget, 'fields_dock'):
            if not parent_widget.fields_dock.isVisible():
                parent_widget.fields_dock.setVisible(True)
    
    def set_layer(self, layer):
        """Set the layer for the field widget"""
        self.current_layer = layer
        
        # If we have an expression widget, configure it with the layer
        if hasattr(self, 'expression_widget') and self.expression_widget:
            if hasattr(self.expression_widget, 'set_layer'):
                self.expression_widget.set_layer(layer)

        if self.calculated_fields:
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
        
        
        if field_name in self.calculated_fields:
            
            self.calculated_fields[field_name]["expression"] = new_expression
            
            
            if field_name == "geometry":
                self.calculated_fields[field_name]["is_geometry"] = True
            
            self._apply_field_item_style(
                current_item,
                field_name,
                self.calculated_fields[field_name],
            )

            # Emit signal for ALL field changes (not just geometry)
            self.field_modified.emit(field_name, field_name, new_expression)

