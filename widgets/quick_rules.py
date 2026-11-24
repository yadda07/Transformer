# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Préparer une règle de texte, puis l'appliquer explicitement au brouillon."""

from copy import deepcopy

from qgis.core import QgsExpression
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QLabel, QComboBox,
    QLineEdit, QPushButton,
)

from ..shared.compat import ComboAdjustMinContentsIcon, PlainText


class QuickRules(QFrame):
    """Les choix guidés utilisent la même recette que la matrice des champs."""

    changed = pyqtSignal()

    def __init__(self, field_widget, parent=None, button_factory=None):
        super().__init__(parent)
        self.field_widget = field_widget
        self._source = None
        self._undo = None
        self._refreshing = False
        self.setObjectName("quick_rules")
        self.setProperty("fluentCard", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        title = QLabel("Nettoyer :", self)
        title.setProperty("role", "section")
        title.setProperty("fluentRole", "section")
        top_row.addWidget(title)
        col_label = QLabel("&Colonne :", self)
        self.field_combo = QComboBox(self)
        self.field_combo.setObjectName("quick_rules_field")
        self.field_combo.setAccessibleName("Colonne à nettoyer")
        self.field_combo.setMinimumContentsLength(10)
        self.field_combo.setSizeAdjustPolicy(ComboAdjustMinContentsIcon)
        col_label.setBuddy(self.field_combo)
        top_row.addWidget(col_label)
        top_row.addWidget(self.field_combo, 1)
        op_label = QLabel("&Changement :", self)
        self.operation_combo = QComboBox(self)
        self.operation_combo.setObjectName("quick_rules_operation")
        self.operation_combo.setAccessibleName("Changement à préparer")
        for text, key in (("Retirer les espaces autour", "trim"),
                          ("Mettre en majuscules", "upper"),
                          ("Mettre en minuscules", "lower"),
                          ("Compléter les textes vides", "fill")):
            self.operation_combo.addItem(text, key)
        op_label.setBuddy(self.operation_combo)
        top_row.addWidget(op_label)
        top_row.addWidget(self.operation_combo, 1)
        self.replacement_edit = QLineEdit(self)
        self.replacement_edit.setAccessibleName("Texte à mettre à la place d'une valeur vide")
        self.replacement_edit.setPlaceholderText("Par exemple : Non renseigné")
        self.replacement_label = QLabel("&Remplacer par :", self)
        self.replacement_label.setBuddy(self.replacement_edit)
        top_row.addWidget(self.replacement_label)
        top_row.addWidget(self.replacement_edit, 1)
        layout.addLayout(top_row)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        self.reason_label = QLabel(self)
        self.reason_label.setObjectName("quick_rules_reason")
        self.reason_label.setWordWrap(True)
        self.reason_label.setTextFormat(PlainText)
        self.reason_label.setProperty("fluentRole", "detail")
        self.reason_label.setAccessibleName("Effet et disponibilité du changement")
        bottom_row.addWidget(self.reason_label, 1)
        self.result_label = QLabel(self)
        self.result_label.setTextFormat(PlainText)
        self.result_label.setWordWrap(True)
        bottom_row.addWidget(self.result_label)
        factory = button_factory or QPushButton
        self.apply_button = factory("Appliquer à cette colonne", self)
        self.apply_button.setObjectName("quick_rules_apply")
        self.apply_button.setAccessibleName("Appliquer le changement à la colonne du résultat")
        self.apply_button.setAutoDefault(False)
        self.undo_button = factory("Annuler ce changement", self)
        self.undo_button.setAccessibleName("Annuler le dernier nettoyage préparé")
        self.undo_button.setAutoDefault(False)
        bottom_row.addWidget(self.apply_button)
        bottom_row.addWidget(self.undo_button)
        layout.addLayout(bottom_row)
        self.field_combo.currentIndexChanged.connect(self._selection_changed)
        self.operation_combo.currentIndexChanged.connect(self._describe)
        self.replacement_edit.textChanged.connect(self._describe)
        self.apply_button.clicked.connect(self.apply)
        self.undo_button.clicked.connect(self.undo)
        for signal in (field_widget.field_added, field_widget.field_removed, field_widget.field_modified):
            signal.connect(self._refresh_fields)
        field_widget.fields_tree.itemSelectionChanged.connect(self._matrix_selection_changed)
        self.setTabOrder(self.field_combo, self.operation_combo)
        self.setTabOrder(self.operation_combo, self.replacement_edit)
        self.setTabOrder(self.replacement_edit, self.apply_button)
        self.setTabOrder(self.apply_button, self.undo_button)
        self.set_source(None)

    def set_source(self, layer_or_none):
        """Actualiser les choix sans créer ni appliquer la moindre règle."""
        self._source = layer_or_none
        self._undo = None
        self.result_label.clear()
        self._refresh_fields()

    def _refresh_fields(self, *args):
        self._refreshing = True
        selected = self.field_combo.currentData()
        blocked = self.field_combo.blockSignals(True)
        try:
            self.field_combo.clear()
            for name, info in self.field_widget.calculated_fields.items():
                if name != "geometry" and not info.get("is_geometry", False):
                    self.field_combo.addItem(name, name)
            index = self.field_combo.findData(selected)
            if index >= 0:
                self.field_combo.setCurrentIndex(index)
        finally:
            self.field_combo.blockSignals(blocked)
            self._refreshing = False
        self._describe()

    def _matrix_selection_changed(self):
        if self._refreshing:
            return
        current = self.field_widget.fields_tree.currentItem()
        index = self.field_combo.findData(current.text(0)) if current else -1
        if index >= 0:
            self.field_combo.setCurrentIndex(index)

    def _selection_changed(self, *args):
        name = self.field_combo.currentData()
        tree = self.field_widget.fields_tree
        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if item.text(0) == name:
                tree.setCurrentItem(item)
                break
        self._describe()

    def _definition(self, name):
        return self.field_widget.get_field_definitions().get(name, {})

    def _source_available(self):
        try:
            return self._source is not None and self._source.isValid()
        except RuntimeError:
            return False

    def _unavailable_reason(self):
        if not self._source_available():
            return "Choisissez une couche disponible pour préparer ses colonnes."
        if self.field_widget.current_layer is not self._source:
            return "La couche a changé. Choisissez de nouveau une colonne de cette préparation."
        name = self.field_combo.currentData()
        if not name:
            return "Aucune colonne dans le résultat. Ajoutez ou conservez d'abord une colonne."
        if self._definition(name).get("type") != "Text":
            return "Ce nettoyage concerne le texte. Choisissez une colonne de texte ; les nombres et dates gardent leur type."
        if not self.field_widget.calculated_fields.get(name, {}).get("expression", "").strip():
            return "Cette colonne n'a pas encore de règle. Définissez sa source dans la matrice."
        if self.operation_combo.currentData() == "fill" and not self.replacement_edit.text().strip():
            return "Saisissez le texte qui remplacera les valeurs absentes, vides ou composées d'espaces."
        return ""

    def _describe(self, *args):
        fill = self.operation_combo.currentData() == "fill"
        self.replacement_label.setVisible(fill)
        self.replacement_edit.setVisible(fill)
        reason = self._unavailable_reason()
        self.apply_button.setEnabled(not reason)
        explanation = ("Les valeurs absentes, vides ou composées d'espaces recevront le texte choisi."
                       if fill else "Le changement s'ajoute aux règles déjà préparées. Les valeurs absentes restent absentes.")
        self.reason_label.setText(reason or explanation + " La couche source reste intacte.")
        self.apply_button.setToolTip(reason or "Modifier uniquement cette colonne de la préparation courante")
        self.apply_button.setAccessibleDescription(self.reason_label.text())
        self.undo_button.setEnabled(self._can_undo())

    def _can_undo(self):
        if self._undo is None:
            return False
        name, before_info, before_definition, expected_info, expected_definition = self._undo
        return (self._source_available() and self.field_widget.current_layer is self._source
                and self.field_widget.calculated_fields.get(name) == expected_info
                and self._definition(name) == expected_definition)

    def apply(self):
        """Appliquer une seule règle au champ existant, sans lire les objets."""
        if self._unavailable_reason():
            self._describe()
            return False
        name = self.field_combo.currentData()
        info = deepcopy(self.field_widget.calculated_fields[name])
        definition = deepcopy(self._definition(name))
        base = "(" + info["expression"] + ")"
        operation = self.operation_combo.currentData()
        if operation == "fill":
            replacement = QgsExpression.quotedValue(self.replacement_edit.text())
            expression = f"CASE WHEN {base} IS NULL OR trim({base}) = '' THEN {replacement} ELSE {base} END"
        else:
            expression = f"{operation}({base})"
        parsed = QgsExpression(expression)
        if parsed.hasParserError():
            self.result_label.setText("La règle existante ne peut pas être complétée. Vérifiez-la dans l'éditeur d'expressions.")
            return False
        updated_definition = dict(definition, length=0, precision=0)
        if not self.field_widget.apply_guided_rule(name, expression, updated_definition):
            return False
        expected_info = deepcopy(self.field_widget.calculated_fields[name])
        self._undo = (name, info, definition, expected_info, deepcopy(self._definition(name)))
        self.result_label.setText(f"« {name} » : changement préparé. Calculez l'aperçu pour voir le résultat.")
        self._describe()
        self.changed.emit()
        return True

    def undo(self):
        """Restaurer le dernier état seulement si personne ne l'a modifié depuis."""
        if not self._can_undo():
            self._describe()
            return False
        name, info, definition, expected_info, expected_definition = self._undo
        self._undo = None
        if not self.field_widget.apply_guided_rule(name, info["expression"], definition):
            return False
        self.result_label.setText(f"« {name} » : dernier nettoyage annulé.")
        self._describe()
        self.changed.emit()
        return True
