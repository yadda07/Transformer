# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
import os
from copy import deepcopy
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QLabel, QMessageBox, QStyledItemDelegate,
)

from ..shared.field_icons import field_type_icon
from ..shared.compat import (
    EventKeyPress,
    FocusStrongFocus,
    GeomNull,
    HeaderInteractive,
    KeyDelete,
    KeyEnter,
    KeyF2,
    KeyReturn,
    MsgBoxNo,
    MsgBoxYes,
    PlainText,
    SelectRows,
    SingleSelection,
    UserRole,
    _DialogCode,
    _SizePolicy,
    meta_type_name,
)
from ..shared.field_classification import (
    classify_field,
    FIELD_CATEGORY_ROLE,
)

# Import classes directly to avoid circular imports
from .field_definition_dialog import (
    FieldDefinitionDialog, FIELD_TYPE_LABELS, normalize_field_definition,
)


class _FieldRowDelegate(QStyledItemDelegate):
    """Garder la hauteur des lignes liée à la police du poste."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height() + 12))
        return size


class FieldWidget(QWidget):
    """Widget for managing calculated fields"""

    field_added = pyqtSignal(str, str)  # name, expression
    field_removed = pyqtSignal(str)
    field_modified = pyqtSignal(str, str, str)  # old_name, new_name, expression

    def __init__(self, expression_widget=None, parent=None):
        super().__init__(parent)
        self.calculated_fields = {}
        self.field_definitions = {}
        self._loading_expression = False
        self.expression_widget = expression_widget
        self.current_layer = None

        self.setup_ui()
        self.setup_connections()

    def setup_ui(self):
        """Configure the interface of the simplified fields widget"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(12)

        header_label = QLabel("Colonnes du résultat")
        header_font = header_label.font()
        header_font.setBold(True)
        header_label.setFont(header_font)
        layout.addWidget(header_label)
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        # Column management actions
        # Note: "Copy All" button removed - fields now auto-populate when a table is selected.
        # The copy_all_fields() method is kept available for programmatic use.

        self.add_field_btn = QPushButton("Ajouter…")
        self.add_field_btn.setAccessibleName("Ajouter un champ de sortie")
        self.add_field_btn.setToolTip("Ajouter une règle à partir de l'expression courante")

        self.edit_field_btn = QPushButton("Définir…")
        self.edit_field_btn.setAccessibleName("Définir le champ de sortie sélectionné")
        self.edit_field_btn.setEnabled(False)
        self.edit_field_btn.setToolTip("Modifier le nom, le type et la description du champ choisi")

        self.remove_field_btn = QPushButton("Exclure")
        self.remove_field_btn.setAccessibleName("Exclure le champ de sortie sélectionné")
        self.remove_field_btn.setEnabled(False)
        self.remove_field_btn.setToolTip("Exclure ce champ de la sortie ; la couche source reste intacte")

        # Clear all fields button
        self.clear_all_btn = QPushButton("Tout exclure")
        self.clear_all_btn.setFlat(True)
        self.clear_all_btn.setAccessibleName("Exclure tous les champs de sortie du brouillon")
        self.clear_all_btn.setToolTip("Exclure les champs du brouillon courant sans supprimer les recettes enregistrées")

        for button in (self.add_field_btn, self.edit_field_btn,
                       self.remove_field_btn, self.clear_all_btn):
            button.setAutoDefault(False)
            button.setAutoRepeat(False)
            button.setSizePolicy(_SizePolicy.Maximum, _SizePolicy.Fixed)
            actions_layout.addWidget(button)
        actions_layout.addStretch()

        # Liste simple des champs - EXPANSION VERTICALE PRIORITAIRE
        self.fields_tree = QTreeWidget()
        self.fields_tree.setHeaderLabels(["Colonne du résultat", "Source / règle", "Type", "État"])
        self.fields_tree.setAccessibleName("Matrice des champs de sortie")
        header_label.setBuddy(self.fields_tree)
        self.fields_tree.setAccessibleDescription("Choisissez une colonne. Double-clic, Entrée ou F2 ouvre son nom et son type. Suppr l'exclut uniquement du résultat.")
        self.fields_tree.setFocusPolicy(FocusStrongFocus)
        self.fields_tree.setSelectionBehavior(SelectRows)
        self.fields_tree.setSelectionMode(SingleSelection)
        self.fields_tree.header().setSectionResizeMode(HeaderInteractive)
        self.fields_tree.header().setStretchLastSection(False)
        self.fields_tree.header().setMinimumSectionSize(70)
        for column, width in enumerate((170, 260, 110, 120)):
            self.fields_tree.setColumnWidth(column, width)
        self.fields_tree.setAlternatingRowColors(True)
        self.fields_tree.setRootIsDecorated(False)
        self.fields_tree.setUniformRowHeights(True)
        self.fields_tree.setItemDelegate(_FieldRowDelegate(self.fields_tree))
        self.fields_tree.setMinimumHeight(100)  # Hauteur minimum seulement

        # Configurer pour expansion verticale optimale
        self.fields_tree.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)

        layout.addWidget(self.fields_tree, 1)  # stretch=1 pour expansion prioritaire
        layout.addLayout(actions_layout)

        self.selection_help = QLabel("Choisissez une colonne. Double-clic ou F2 pour son nom et son type ; la source reste intacte.")
        self.selection_help.setTextFormat(PlainText)
        self.selection_help.setWordWrap(True)
        self.selection_help.setProperty("role", "detail")
        layout.addWidget(self.selection_help)

        self.setLayout(layout)
        self.setFocusProxy(self.fields_tree)
        self.setTabOrder(self.fields_tree, self.add_field_btn)
        self.setTabOrder(self.add_field_btn, self.edit_field_btn)
        self.setTabOrder(self.edit_field_btn, self.remove_field_btn)
        self.setTabOrder(self.remove_field_btn, self.clear_all_btn)
        self.clear_all_btn.setEnabled(False)

    def setup_connections(self):
        """Configure the signal connections"""
        self.fields_tree.itemSelectionChanged.connect(self.on_field_selection_changed)
        self.fields_tree.itemDoubleClicked.connect(self.edit_selected_field)
        self.fields_tree.installEventFilter(self)

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
                QMessageBox.warning(self, "Règle manquante", "Saisissez une expression dans l'éditeur avant d'ajouter ce champ.")
                return

        dialog = FieldDefinitionDialog(self, existing_names=self.calculated_fields)
        result = dialog.exec()
        self.add_field_btn.setFocus()
        if result == _DialogCode.Accepted:
            name, description = dialog.get_field_info()
            self.add_calculated_field(name, expression, description, dialog.get_field_definition())

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
            QMessageBox.warning(self, "Source manquante", "Sélectionnez une ou plusieurs couches vectorielles avant de copier leurs champs.")
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

                if layer.geometryType() != GeomNull:
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
                    parent_widget.log_message(f"Recette « {table_name} » créée avec {len(layer_fields)} champs", "Success")
                else:
                    parent_widget.log_message(f"Impossible de créer la recette de « {filename} »", "Error")

            except Exception as e:
                parent_widget.log_message(f"Création de la recette de « {filename} » impossible : {e}", "Error")

        # Save all configurations to calculated_fields_config.json
        first_table_name = None
        if configs_created > 0:
            parent_widget.config_manager.save_config()

            # Enhanced feedback with configuration names
            config_list = "', '".join(created_configs)
            parent_widget.log_message(f"Copie terminée : {configs_created} recettes créées : '{config_list}'", "Success")

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
            self.field_definitions.clear()
            self.refresh_fields_list()

    def clear_all_fields(self):
        """Exclude only the current draft fields; saved recipes are never deleted."""
        removed = list(self.calculated_fields)
        self.calculated_fields.clear()
        self.field_definitions.clear()
        self.refresh_fields_list()
        for name in removed:
            self.field_removed.emit(name)
        return bool(removed)

    def add_quick_field(self, name, expression):
        """Add a quick field"""
        # Check if the name already exists
        counter = 1
        original_name = name
        while name in self.calculated_fields:
            name = f"{original_name}_{counter}"
            counter += 1

        self.add_calculated_field(name, expression)

    def add_calculated_field(self, name, expression, description="", field_definition=None):
        """Add a calculated field"""
        name = str(name).strip()
        if not name:
            QMessageBox.warning(self, "Nom manquant", "Donnez un nom au champ à ajouter.")
            return False
        if name.casefold() == "geometry":
            QMessageBox.warning(self, "Nom réservé", "Le nom « geometry » est réservé. Utilisez l'étape Géométrie, ou nommez cet attribut autrement, par exemple geometry_attribut.")
            return False
        if any(value.casefold() == name.casefold() for value in self.calculated_fields):
            QMessageBox.warning(self, "Nom déjà utilisé", f"Le champ « {name} » existe déjà. Choisissez un autre nom.")
            return False

        definition = normalize_field_definition(field_definition or self._infer_definition(name, expression))
        if description:
            definition["description"] = description
        self.field_definitions[name] = definition

        self.calculated_fields[name] = {
            "expression": expression,
            "description": definition["description"]
        }

        self.refresh_fields_list()
        self.field_added.emit(name, expression)
        return True

    def edit_selected_field(self):
        """Edit the selected field"""
        current_item = self.fields_tree.currentItem()
        if not current_item:
            return

        field_name = current_item.text(0)
        field_info = self.calculated_fields.get(field_name, {})

        # Pre-fill the expression in the calculator if available
        if self.expression_widget and field_info.get("expression"):
            self._loading_expression = True
            try:
                self.expression_widget.set_expression(field_info.get("expression"))
            finally:
                self._loading_expression = False

        dialog = FieldDefinitionDialog(self, existing_names=self.calculated_fields, original_name=field_name)
        dialog.set_field_info(field_name, field_info.get("description", ""))
        dialog.set_field_definition(self.field_definitions.get(field_name))

        result = dialog.exec()
        self.fields_tree.setFocus()
        if result == _DialogCode.Accepted:
            new_name, new_description = dialog.get_field_info()
            if new_name.casefold() == "geometry":
                QMessageBox.warning(self, "Nom réservé", "Le nom « geometry » est réservé. Utilisez l'étape Géométrie, ou choisissez un autre nom pour cet attribut.")
                return False
            if any(name != field_name and name.casefold() == new_name.casefold()
                   for name in self.calculated_fields):
                QMessageBox.warning(self, "Nom déjà utilisé", f"Le champ « {new_name} » existe déjà. Aucune règle n'a été remplacée.")
                return False

            # Get the current expression from the calculator
            expression = field_info.get("expression", "")
            if self.expression_widget:
                expression = self.expression_widget.get_expression().strip()

            updated_info = {
                "expression": expression,
                "description": new_description,
                "is_geometry": field_info.get("is_geometry", False),
            }
            self.calculated_fields = {
                (new_name if name == field_name else name):
                (updated_info if name == field_name else info)
                for name, info in self.calculated_fields.items()
            }
            self.field_definitions.pop(field_name, None)
            if not updated_info["is_geometry"]:
                self.field_definitions[new_name] = dialog.get_field_definition()

            self.refresh_fields_list()
            self.field_modified.emit(field_name, new_name, expression)
            return True
        return False

    def apply_guided_rule(self, field_name, expression, field_definition=None):
        """Modifier une règle existante par le même signal que l'éditeur expert."""
        info = self.calculated_fields.get(field_name)
        if (info is None or field_name == "geometry" or info.get("is_geometry", False)
                or not str(expression or "").strip()):
            return False
        definition = normalize_field_definition(
            field_definition if field_definition is not None else
            self.field_definitions.get(field_name) or self._infer_definition(field_name, info["expression"]))
        self.calculated_fields[field_name] = dict(
            info, expression=expression, description=definition["description"])
        self.field_definitions[field_name] = definition
        self.refresh_fields_list()
        self.field_modified.emit(field_name, field_name, expression)
        return True

    def remove_selected_field(self):
        """Remove the selected field"""
        current_item = self.fields_tree.currentItem()
        if not current_item:
            return False

        field_name = current_item.text(0)

        reply = QMessageBox.question(
            self, "Exclure le champ",
            f"Exclure « {field_name} » de la sortie ? La couche source reste intacte.",
            MsgBoxYes | MsgBoxNo, MsgBoxNo
        )

        if reply == MsgBoxYes:
            del self.calculated_fields[field_name]
            self.field_definitions.pop(field_name, None)
            self.refresh_fields_list()
            self.field_removed.emit(field_name)
            return True
        return False

    def eventFilter(self, watched, event):
        if watched is self.fields_tree and event.type() == EventKeyPress:
            if event.key() in (KeyReturn, KeyEnter, KeyF2):
                if not event.isAutoRepeat():
                    self.edit_selected_field()
                return True
            if event.key() == KeyDelete:
                if not event.isAutoRepeat():
                    self.remove_selected_field()
                return True
        return super().eventFilter(watched, event)

    def _infer_definition(self, field_name, expression):
        """Preserve source metadata for direct references, without reading features."""
        source_name = str(expression or "").strip()
        if source_name.startswith('"') and source_name.endswith('"'):
            source_name = source_name[1:-1].replace('""', '"')
        definition = {"type": "Text", "length": 0, "precision": 0, "description": ""}
        layer = self.current_layer
        if layer is None:
            return definition
        fields = layer.fields()
        index = fields.lookupField(source_name)
        if index < 0:
            return definition
        field = fields.at(index)
        type_name = field.typeName().lower()
        native_type = meta_type_name(field.type()).lower()
        if "bool" in type_name or native_type == "bool":
            field_type = "Boolean"
        elif "datetime" in type_name or "timestamp" in type_name or native_type == "qdatetime":
            field_type = "DateTime"
        elif type_name == "date" or native_type == "qdate":
            field_type = "Date"
        elif any(value in type_name for value in ("int8", "int64", "bigint", "longlong")) or native_type in ("longlong", "ulonglong"):
            field_type = "Integer64"
        elif "int" in type_name or native_type in ("int", "uint", "short", "ushort"):
            field_type = "Integer"
        elif any(value in type_name for value in ("real", "double", "float", "numeric", "decimal")) or native_type in ("double", "float"):
            field_type = "Real"
        else:
            field_type = "Text"
        definition.update(type=field_type, length=max(0, field.length()),
                          precision=max(0, field.precision()), description=field.comment())
        return normalize_field_definition(definition)

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

        definition = self.field_definitions.get(field_name) or self._infer_definition(field_name, expression)
        type_label = "Géométrie" if is_geometry_field else FIELD_TYPE_LABELS[definition["type"]]
        state = "Géométrie" if is_geometry_field else ("Conservé" if expression.strip() in (field_name, f'"{field_name}"') else "Calculé")
        if not expression.strip():
            state = "À renseigner"
        item.setText(1, expression)
        item.setText(2, type_label)
        item.setText(3, state)
        description = definition.get("description", field_info.get("description", ""))
        tooltip = f"{field_name}\nType : {type_label}\n{state}\n{expression}"
        if description:
            tooltip += f"\n{description}"
        for column in range(4):
            item.setToolTip(column, tooltip)

        icon_type = "geometry" if is_geometry_field else {
            "Text": "string", "Integer": "int", "Integer64": "int",
            "Real": "double", "Date": "datetime", "DateTime": "datetime", "Boolean": "bool",
        }[definition["type"]]
        item.setIcon(0, field_type_icon(icon_type))

    def refresh_fields_list(self):
        """Refresh the list of fields"""
        current = self.fields_tree.currentItem()
        selected_name = current.text(0) if current else None
        blocked = self.fields_tree.blockSignals(True)
        try:
            self.fields_tree.clear()
            for field_name, field_info in self.calculated_fields.items():
                item = QTreeWidgetItem(self.fields_tree)
                item.setText(0, field_name)
                self._apply_field_item_style(item, field_name, field_info)
                if field_name == selected_name:
                    self.fields_tree.setCurrentItem(item)
        finally:
            self.fields_tree.blockSignals(blocked)
        self.on_field_selection_changed()

    def on_field_selection_changed(self):
        """Handle field selection change"""
        selected_items = self.fields_tree.selectedItems()
        has_selection = len(selected_items) > 0

        self.edit_field_btn.setEnabled(has_selection)
        self.remove_field_btn.setEnabled(has_selection)
        self.clear_all_btn.setEnabled(bool(self.calculated_fields))
        current_item = self.fields_tree.currentItem()
        if has_selection and current_item is not None:
            name = current_item.text(0)
            self.selection_help.setText(f"« {name} » sélectionnée. Double-clic ou F2 pour changer son nom et son type.")
        else:
            self.selection_help.setText("Choisissez une colonne pour la définir ou l'exclure. La source reste intacte.")
        self.edit_field_btn.setToolTip("Modifier le nom, le type et la description de la colonne choisie"
                                      if has_selection else "Choisissez d'abord une colonne dans la matrice")
        self.remove_field_btn.setToolTip("Exclure cette colonne du résultat ; la couche source reste intacte"
                                        if has_selection else "Choisissez d'abord la colonne à exclure du résultat")

        # Load selected field expression into calculator
        if has_selection and self.expression_widget:
            current_item = self.fields_tree.currentItem()
            if current_item:
                field_name = current_item.text(0)
                if field_name in self.calculated_fields:
                    expression = self.calculated_fields[field_name]["expression"]
                    self._loading_expression = True
                    try:
                        self.expression_widget.set_expression(expression)
                    finally:
                        self._loading_expression = False

    def get_calculated_fields(self):
        """Get all calculated fields"""
        return {name: info["expression"] for name, info in self.calculated_fields.items()}

    def get_field_definitions(self):
        """Explicit output metadata, independent of expression strings and geometry."""
        return {name: deepcopy(self.field_definitions.get(name) or self._infer_definition(name, info["expression"]))
                for name, info in self.calculated_fields.items()
                if not info.get("is_geometry", False) and name != "geometry"}

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

    def set_calculated_fields(self, fields_dict, geometry_expression=None, field_definitions=None):
        """Set calculated fields with optional geometry expression"""
        if any(str(name).strip().casefold() == "geometry" for name in fields_dict):
            raise ValueError("Un attribut importé porte le nom réservé « geometry ». Renommez-le, par exemple geometry_attribut, en conservant sa référence source. Utilisez geometry_expression pour la géométrie.")
        # Get parent widget for logging
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'log_message'):
                break
            parent_widget = parent_widget.parent()

        previous_fields = self.calculated_fields
        previous_definitions = self.field_definitions
        self.calculated_fields = {}
        self.field_definitions = {}

        # Add geometry field if provided
        if geometry_expression:
            self.calculated_fields["geometry"] = {
                "expression": geometry_expression,
                "description": "Géométrie de sortie",
                "is_geometry": True
            }

        # Add attribute fields
        for name, expression in fields_dict.items():
            if isinstance(expression, dict):
                expression = expression.get("expression", "")
            supplied = (field_definitions or {}).get(name)
            if supplied is None and field_definitions is None and previous_fields.get(name, {}).get("expression") == expression:
                supplied = previous_definitions.get(name)
            definition = normalize_field_definition(supplied or self._infer_definition(name, expression))
            self.field_definitions[name] = definition
            self.calculated_fields[name] = {
                "expression": expression,
                "description": definition["description"],
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
        if not self.expression_widget or self._loading_expression:
            return

        current_item = self.fields_tree.currentItem()
        if not current_item:
            return

        field_name = current_item.text(0)
        new_expression = self.expression_widget.get_expression().strip()

        if field_name in self.calculated_fields:
            if self.calculated_fields[field_name]["expression"] == new_expression:
                return
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
