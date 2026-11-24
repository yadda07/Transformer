
# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QMessageBox, QDialogButtonBox,
    QComboBox, QSpinBox, QLabel
)
from ..shared.compat import FormAllNonFixedFieldsGrow, FormWrapLongRows
from ..shared.helpers import get_plugin_icon


FIELD_TYPE_LABELS = {
    "Text": "Texte", "Integer": "Entier", "Integer64": "Entier long",
    "Real": "Décimal", "Date": "Date", "DateTime": "Date et heure",
    "Boolean": "Booléen",
}


def normalize_field_definition(definition=None):
    """Return a serializable, explicit definition without mutating its input."""
    definition = definition if isinstance(definition, dict) else {}
    field_type = definition.get("type", "Text")
    if field_type not in FIELD_TYPE_LABELS:
        field_type = "Text"
    def nonnegative(value, maximum):
        try:
            return min(maximum, max(0, int(value)))
        except (ValueError, TypeError, OverflowError):
            return 0
    return {
        "type": field_type,
        "length": nonnegative(definition.get("length", 0), 65535),
        "precision": nonnegative(definition.get("precision", 0), 30),
        "description": str(definition.get("description", "") or ""),
    }


class FieldDefinitionDialog(QDialog):
    """Field definition dialog"""

    def __init__(self, parent=None, existing_names=None, original_name=""):
        super().__init__(parent)
        self.existing_names = set(existing_names or ())
        self.original_name = original_name
        self.setWindowTitle("Définir le champ de sortie")
        self.setModal(True)
        self.resize(460, 300)

        self.setWindowIcon(get_plugin_icon())

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        introduction = QLabel("Choisissez le nom et le type de cette colonne dans le résultat. La colonne source n'est pas modifiée.")
        introduction.setWordWrap(True)
        layout.addWidget(introduction)

        # Formulaire
        form_layout = QFormLayout()
        form_layout.setRowWrapPolicy(FormWrapLongRows)
        form_layout.setFieldGrowthPolicy(FormAllNonFixedFieldsGrow)
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nom dans la livraison préparée")
        self.name_edit.setAccessibleName("Nom du champ de sortie")
        self.name_edit.setToolTip("Un nom lisible pour la colonne livrée ; sa règle conserve la référence au champ source.")
        form_layout.addRow("Champ de &sortie :", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.setAccessibleName("Type du champ de sortie")
        for value, label in FIELD_TYPE_LABELS.items():
            self.type_combo.addItem(label, value)
        form_layout.addRow("&Type :", self.type_combo)

        self.length_spin = QSpinBox()
        self.length_spin.setRange(0, 65535)
        self.length_spin.setSpecialValueText("Valeur du format")
        self.length_spin.setAccessibleName("Longueur du champ de sortie")
        self.length_spin.setToolTip("0 laisse le format de sortie choisir la longueur.")
        form_layout.addRow("&Longueur :", self.length_spin)
        self.precision_spin = QSpinBox()
        self.precision_spin.setRange(0, 30)
        self.precision_spin.setAccessibleName("Nombre de décimales du champ de sortie")
        form_layout.addRow("&Décimales :", self.precision_spin)
        self.type_combo.currentIndexChanged.connect(self._update_type_controls)

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Sens métier, unité ou consigne, facultatif")
        self.description_edit.setAccessibleName("Description du champ de sortie, facultative")
        form_layout.addRow("&Description :", self.description_edit)

        layout.addLayout(form_layout)
        self.type_help = QLabel()
        self.type_help.setWordWrap(True)
        self.type_help.setAccessibleName("Conseil pour choisir le type de la colonne")
        layout.addWidget(self.type_help)
        note = QLabel("Le type sera conservé dans la recette. Une valeur incompatible sera signalée lors du contrôle.")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Boutons
        from ..shared.compat import DlgBtnOk, DlgBtnCancel
        buttons = QDialogButtonBox(DlgBtnOk | DlgBtnCancel)
        buttons.button(DlgBtnOk).setText("&Valider")
        buttons.button(DlgBtnCancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self.setTabOrder(self.name_edit, self.type_combo)
        self.setTabOrder(self.type_combo, self.length_spin)
        self.setTabOrder(self.length_spin, self.precision_spin)
        self.setTabOrder(self.precision_spin, self.description_edit)
        self.setTabOrder(self.description_edit, buttons.button(DlgBtnOk))
        self.name_edit.setFocus()
        self._update_type_controls()

    def _update_type_controls(self):
        field_type = self.type_combo.currentData()
        self.length_spin.setEnabled(field_type in ("Text", "Real"))
        self.precision_spin.setEnabled(field_type == "Real")
        self.length_spin.setToolTip("0 laisse le format de sortie choisir la longueur."
                                   if self.length_spin.isEnabled() else "Ce type n'utilise pas de longueur configurable.")
        self.precision_spin.setToolTip("Nombre de décimales du résultat ; une valeur incompatible sera signalée."
                                      if field_type == "Real" else "Les décimales ne concernent que le type Décimal.")
        self.type_help.setText({
            "Text": "Pour un nom, un code ou un identifiant : le texte conserve les zéros au début.",
            "Integer": "Pour un compte sans décimales. Une valeur fractionnaire est refusée, jamais tronquée en silence.",
            "Integer64": "Pour de grands nombres entiers. Un identifiant avec des zéros au début doit rester en texte.",
            "Real": "Pour les mesures avec décimales. Vérifiez l'unité et la précision attendues avant de livrer.",
            "Date": "Pour une date sans heure. Le contrôle signalera les valeurs incompatibles.",
            "DateTime": "Pour une date accompagnée d'une heure. Vérifiez le résultat dans l'aperçu.",
            "Boolean": "Pour une réponse oui ou non. Une valeur absente reste distincte de non.",
        }.get(field_type, ""))

    def set_field_info(self, name, description=""):
        """Set field information"""
        self.name_edit.setText(name)
        self.description_edit.setText(description)

    def get_field_info(self):
        """Get field information"""
        return (
            self.name_edit.text().strip(),
            self.description_edit.text().strip()
        )

    def set_field_definition(self, definition):
        definition = normalize_field_definition(definition)
        self.type_combo.setCurrentIndex(self.type_combo.findData(definition["type"]))
        self.length_spin.setValue(definition["length"])
        self.precision_spin.setValue(definition["precision"])
        self.description_edit.setText(definition["description"])

    def get_field_definition(self):
        return normalize_field_definition({
            "type": self.type_combo.currentData(),
            "length": self.length_spin.value() if self.length_spin.isEnabled() else 0,
            "precision": self.precision_spin.value() if self.precision_spin.isEnabled() else 0,
            "description": self.description_edit.text().strip(),
        })

    def accept(self):
        """Validation avant acceptation"""
        name = self.name_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Nom manquant", "Donnez un nom au champ de sortie.")
            self.name_edit.setFocus()
            return

        if name.casefold() == "geometry":
            QMessageBox.warning(self, "Nom réservé", "Le nom « geometry » est réservé à la géométrie. Utilisez l'étape Géométrie pour la forme des objets, ou choisissez un autre nom pour cet attribut, par exemple geometry_attribut.")
            self.name_edit.setFocus()
            return

        collision = next((value for value in self.existing_names
                          if value.casefold() == name.casefold()
                          and value != self.original_name), None)
        if collision:
            QMessageBox.warning(self, "Nom déjà utilisé", f"Le champ « {collision} » existe déjà. Choisissez un autre nom pour conserver les deux règles.")
            self.name_edit.setFocus()
            return

        super().accept()
