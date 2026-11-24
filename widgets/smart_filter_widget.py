
# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
from qgis.PyQt.QtCore import pyqtSignal, QSignalBlocker

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QLabel, QPushButton,
    QCheckBox, QMessageBox
)
from qgis.core import QgsFeatureRequest
from qgis.gui import QgsExpressionBuilderDialog
from ..shared.compat import DialogAccepted
from ..shared.expression_utils import validate_expression_syntax, evaluate_expression
from ..shared.helpers import create_layer_expression_context


class SmartFilterWidget(QWidget):
    """Smart filter widget with suggestions"""

    filter_changed = pyqtSignal(str)
    filter_applied = pyqtSignal(str, bool)  # expression, enabled
    PREVIEW_LIMIT = 500

    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.last_test_result = None

        self.setup_ui()
        self.setup_connections()

    def setup_ui(self):
        """Configure the filter widget interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)

        # Header with activation
        header_layout = QHBoxLayout()

        self.enable_filter_cb = QCheckBox("Appliquer le filtre")
        self.enable_filter_cb.setAccessibleDescription(
            "Désactiver le filtre conserve l'expression pour la prochaine utilisation."
        )
        font = self.enable_filter_cb.font()
        font.setBold(True)
        self.enable_filter_cb.setFont(font)
        header_layout.addWidget(self.enable_filter_cb)

        header_layout.addStretch()

        # Info filtre intégrée - apparaît seulement quand nécessaire
        self.filter_status_label = QLabel()
        self.filter_status_label.setWordWrap(True)
        self.filter_status_label.setVisible(False)
        header_layout.addWidget(self.filter_status_label)

        self.filter_count_label = QLabel()
        self.filter_count_label.setWordWrap(True)
        self.filter_count_label.setVisible(False)
        header_layout.addWidget(self.filter_count_label)

        # Espacement avant les boutons
        header_layout.addSpacing(10)

        # Action buttons - version compacte
        self.test_filter_btn = QPushButton("Vérifier")
        self.test_filter_btn.setEnabled(False)
        self.test_filter_btn.setToolTip("Évaluer au plus 500 objets ; le bilan complet sera établi à l'exécution")
        self.test_filter_btn.setAccessibleName("Vérifier le filtre")
        self.test_filter_btn.setAccessibleDescription(self.test_filter_btn.toolTip())

        self.builder_btn = QPushButton("Éditeur…")
        self.builder_btn.setAccessibleName("Ouvrir l'éditeur du filtre")
        self.builder_btn.setEnabled(False)

        header_layout.addWidget(self.test_filter_btn)
        header_layout.addWidget(self.builder_btn)

        layout.addLayout(header_layout)

        # Filter expression with auto-completion
        filter_layout = QHBoxLayout()

        self.filter_expression = QLineEdit()
        self.filter_expression.setPlaceholderText('Exemple : "TYPE" = \'Bâtiment\'')
        self.filter_expression.setAccessibleName("Expression du filtre")
        self.filter_expression.setEnabled(False)

        label = QLabel("&Règle :")
        label.setBuddy(self.filter_expression)
        filter_layout.addWidget(label)
        filter_layout.addWidget(self.filter_expression)

        layout.addLayout(filter_layout)

        # Templates and suggestions
        templates_layout = QGridLayout()
        templates_layout.addWidget(QLabel("Insérer :"), 0, 0, 1, 2)

        # Quick templates buttons
        self.template_buttons = []
        templates = [
            ("Géométrie valide", "is_valid($geometry)"),
            ("Valeur renseignée", '"CHAMP" IS NOT NULL'),
            ("Par type", '"TYPE" = \'VALEUR\''),
            ("À partir d'une date", '"DATE" >= make_date(2026, 1, 1)')
        ]

        for index, (name, template) in enumerate(templates):
            btn = QPushButton(name)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, t=template: self.apply_template(t))
            self.template_buttons.append(btn)
            templates_layout.addWidget(btn, 1 + index // 2, index % 2)

        templates_layout.setColumnStretch(0, 1)
        templates_layout.setColumnStretch(1, 1)
        layout.addLayout(templates_layout)

        # Les labels de statut/compteur sont maintenant dans le header
        # Plus besoin du panel séparé - économise de l'espace !

        self.setLayout(layout)
        self.setFocusProxy(self.enable_filter_cb)
        focus_order = [self.enable_filter_cb, self.filter_expression,
                       self.builder_btn, self.test_filter_btn, *self.template_buttons]
        for first, second in zip(focus_order, focus_order[1:]):
            QWidget.setTabOrder(first, second)

    def setup_connections(self):
        """Configure the signal connections"""
        self.enable_filter_cb.toggled.connect(self.on_filter_enabled_changed)
        self.filter_expression.textChanged.connect(self.on_filter_expression_changed)
        self.test_filter_btn.clicked.connect(self.test_filter)
        self.builder_btn.clicked.connect(self.open_filter_builder)

    def set_layer(self, layer):
        """Set the context layer"""
        self.layer = layer
        self.update_template_buttons()
        self._invalidate_preview()

    def update_template_buttons(self):
        """Update template buttons based on the layer"""
        specs = [
            ("Géométrie valide", "is_valid($geometry)"),
            ("Valeur renseignée", '"CHAMP" IS NOT NULL'),
            ("Par type", '"TYPE" = \'VALEUR\''),
            ("À partir d'une date", '"DATE" >= make_date(2026, 1, 1)'),
        ]
        field_names = [field.name() for field in self.layer.fields()] if self.layer else []
        type_fields = [name for name in field_names if 'type' in name.lower() or 'class' in name.lower()]
        date_fields = [name for name in field_names if 'date' in name.lower() or 'time' in name.lower()]
        if type_fields:
            quoted = '"' + type_fields[0].replace('"', '""') + '"'
            specs[2] = (f"Par {type_fields[0]}", f"{quoted} = 'VALEUR'")
        if date_fields:
            quoted = '"' + date_fields[0].replace('"', '""') + '"'
            specs[3] = (f"Date : {date_fields[0]}", f"{quoted} >= make_date(2026, 1, 1)")
        for button, (label, template) in zip(self.template_buttons, specs):
            button.setText(label)
            try:
                button.clicked.disconnect()
            except TypeError:
                pass
            button.clicked.connect(lambda checked=False, value=template: self.apply_template(value))

    def on_filter_enabled_changed(self, enabled):
        """Filter activation/deactivation management"""
        self.filter_expression.setEnabled(enabled)
        self.builder_btn.setEnabled(enabled)
        self.test_filter_btn.setEnabled(enabled)

        for btn in self.template_buttons:
            btn.setEnabled(enabled)

        self._invalidate_preview()
        self.emit_filter_changed()

    def on_filter_expression_changed(self):
        """Filter expression change management"""
        self.filter_changed.emit(self.get_filter_expression())
        self.emit_filter_changed()  # Emit filter_applied signal to update configuration
        self._invalidate_preview()

    def apply_template(self, template):
        """Apply a filter template"""
        if self.enable_filter_cb.isChecked():
            current_text = self.filter_expression.text().strip()

            if current_text:
                # Combiner avec l'expression existante
                combined = f"({current_text}) AND ({template})"
                self.filter_expression.setText(combined)
            else:
                self.filter_expression.setText(template)

    def test_filter(self):
        """Test the filter expression"""
        if not self.layer:
            QMessageBox.warning(self, "Source absente", "Reliez une couche à la recette avant de vérifier le filtre.")
            return

        filter_expr = self.get_filter_expression()
        if not filter_expr:
            QMessageBox.warning(self, "Règle manquante", "Activez le filtre et saisissez une expression à vérifier.")
            return

        try:
            # Test expression
            is_valid, error_msg, expression = validate_expression_syntax(filter_expr)
            if not is_valid:
                self.update_filter_status(False, 0, 0)
                QMessageBox.warning(self, "Filtre à corriger", f"Corrigez la syntaxe avant l'exécution :\n{error_msg}")
                return

            # Bound source reads, including a filter that matches no features.
            # CASE uses the same NULL/boolean semantics as the expression engine.
            _, _, expression = validate_expression_syntax(f"CASE WHEN ({filter_expr}) THEN 1 ELSE 0 END")
            context = create_layer_expression_context(self.layer)
            if not expression.prepare(context):
                raise ValueError(expression.evalErrorString() or "La règle utilise un champ absent de la source.")
            request = QgsFeatureRequest().setLimit(self.PREVIEW_LIMIT + 1)
            sampled = matched = 0
            truncated = False
            iterator = self.layer.getFeatures(request)
            try:
                for feature in iterator:
                    if sampled >= self.PREVIEW_LIMIT:
                        truncated = True
                        break
                    context.setFeature(feature)
                    success, value, error = evaluate_expression(expression, context)
                    if not success:
                        raise ValueError(f"Objet {feature.id()} : {error}")
                    sampled += 1
                    matched += bool(value)
            finally:
                if hasattr(iterator, "close"):
                    iterator.close()
            self.last_test_result = {"sampled": sampled, "matched": matched,
                                     "truncated": truncated, "expression": filter_expr}
            self.update_filter_status(True, matched, sampled)
            self.filter_count_label.setText(f"{matched:,} retenus / {sampled:,} examinés")
            scope = "Échantillon limité aux 500 premiers objets." if truncated else "Tous les objets lus dans cette source ont été examinés."
            QMessageBox.information(self, "Contrôle du filtre", f"{matched:,} objets retenus sur {sampled:,} examinés.\n\n{scope}\nLe contrôle du filtre ne vérifie pas les règles de champs ni la destination.")

        except Exception as e:
            self.last_test_result = None
            self.update_filter_status(False, 0, 0)
            QMessageBox.warning(self, "Filtre à corriger", f"Le contrôle n'a pas abouti. Corrigez la règle ou la source :\n{e}")

    def open_filter_builder(self):
        """Open the expression builder for the filter"""
        if not self.layer:
            QMessageBox.warning(self, "Source absente", "Reliez une couche à la recette avant d'ouvrir l'éditeur du filtre.")
            return

        current_expr = self.filter_expression.text().strip()

        dialog = QgsExpressionBuilderDialog(self.layer, current_expr, self)
        dialog.setWindowTitle("Définir le filtre de la recette")

        if dialog.exec() == DialogAccepted:
            new_expr = dialog.expressionText()
            self.filter_expression.setText(new_expr)

        self.filter_expression.setFocus()

    def get_filter_expression(self):
        """Get the current filter expression"""
        if self.enable_filter_cb.isChecked():
            return self.filter_expression.text().strip()
        return ""

    def get_filter_config(self):
        """Get the filter configuration"""
        return {
            "enabled": self.enable_filter_cb.isChecked(),
            "expression": self.filter_expression.text().strip()
        }

    def set_filter_config(self, config):
        """Set the filter configuration"""
        if isinstance(config, dict):
            enabled = config.get("enabled", False)
            expression = config.get("expression", "")

            with QSignalBlocker(self.enable_filter_cb), QSignalBlocker(self.filter_expression):
                self.enable_filter_cb.setChecked(bool(enabled))
                self.filter_expression.setText(str(expression or ""))
            self.on_filter_enabled_changed(bool(enabled))

    def clear_filter(self):
        """Clear the filter expression and disable filtering"""
        with QSignalBlocker(self.enable_filter_cb), QSignalBlocker(self.filter_expression):
            self.enable_filter_cb.setChecked(False)
            self.filter_expression.clear()
        self.on_filter_enabled_changed(False)
        self.filter_changed.emit("")

    def set_filter_expression(self, expression):
        """Set filter expression and enable filtering if expression is provided"""
        if expression and expression.strip():
            self.enable_filter_cb.setChecked(True)
            self.filter_expression.setText(expression.strip())
        else:
            self.clear_filter()

    def emit_filter_changed(self):
        """Emit the filter change signal"""
        config = self.get_filter_config()
        self.filter_applied.emit(config.get("expression", ""), config.get("enabled", False))

    def update_filter_info(self):
        """Update filter information - affichage intégré dans le header"""
        if not self.enable_filter_cb.isChecked():
            # Masquer les informations si le filtre est désactivé
            self.filter_status_label.setVisible(False)
            self.filter_count_label.setVisible(False)
            return

        filter_expr = self.get_filter_expression()
        if filter_expr:
            self.filter_status_label.setText("À vérifier")
            self.filter_status_label.setVisible(True)
        else:
            self.filter_status_label.setText("Règle manquante")
            self.filter_status_label.setVisible(True)
            self.filter_count_label.setVisible(False)

    def update_filter_status(self, valid, filtered_count, total_count):
        """Update filter status - affichage intégré dans le header"""
        if valid:
            self.filter_status_label.setText("Échantillon vérifié")
            self.filter_count_label.setText(f"({filtered_count:,}/{total_count:,})")
            # Rendre visible les informations
            self.filter_status_label.setVisible(True)
            self.filter_count_label.setVisible(True)
        else:
            self.filter_status_label.setText("À corriger")
            self.filter_count_label.clear()
            # Rendre visible l'erreur, masquer le compteur
            self.filter_status_label.setVisible(True)
            self.filter_count_label.setVisible(False)

    def _invalidate_preview(self):
        self.last_test_result = None
        self.update_filter_info()
        if self.enable_filter_cb.isChecked() and self.filter_expression.text().strip():
            self.filter_count_label.setText("À actualiser")
            self.filter_count_label.setVisible(True)
