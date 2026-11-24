# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
from qgis.PyQt.QtCore import pyqtSignal, QSize, QSettings
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QMessageBox, QDialog, QListWidget, QDialogButtonBox
)
from qgis.core import QgsExpressionContext, QgsMessageLog
from qgis.PyQt.QtCore import QTimer
from qgis.gui import QgsExpressionBuilderWidget
from qgis.PyQt.QtWidgets import QToolBar
from ..shared.compat import (
    FocusStrongFocus,
    MsgBoxIconInfo,
    MsgBoxOk,
    MsgWarning,
    QAction,
    RichText,
    ToolButtonTextBesideIcon,
    _DialogCode,
    _SizePolicy,
)
from ..shared.helpers import create_layer_expression_context
from ..shared.icons import icon as ui_icon, IconTone
from ..shared.expression_utils import validate_expression_syntax, evaluate_expression


class ExpressionHistoryDialog(QDialog):
    """Dialog for selecting from expression history"""

    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historique des expressions")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)
        self.selected_expression = None

        layout = QVBoxLayout(self)

        # List widget
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("Expressions enregistrées")
        self.list_widget.setAccessibleDescription("Choisissez une expression avec les flèches, puis appuyez sur Entrée pour l'utiliser.")
        for expr in history:
            self.list_widget.addItem(expr)
            self.list_widget.item(self.list_widget.count() - 1).setToolTip(expr)
        if history:
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        # Store full expressions
        self.history = history

        # Buttons
        from ..shared.compat import DlgBtnOk, DlgBtnCancel
        buttons = QDialogButtonBox(DlgBtnOk | DlgBtnCancel)
        buttons.button(DlgBtnOk).setText("&Utiliser cette expression")
        buttons.button(DlgBtnOk).setEnabled(bool(history))
        buttons.button(DlgBtnCancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setTabOrder(self.list_widget, buttons.button(DlgBtnOk))
        self.list_widget.setFocus()

    def get_selected_expression(self):
        """Return selected expression"""
        row = self.list_widget.currentRow()
        if row >= 0 and row < len(self.history):
            return self.history[row]
        return None


class AdvancedExpressionWidget(QWidget):
    """Advanced expression widget with native QGIS features"""

    expression_changed = pyqtSignal(str)
    expression_validated = pyqtSignal(bool, str)

    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.expression_history = []
        self.current_history_index = -1
        self._original_expression = ""  # Sauvegarde de l'expression originale
        self._setting_expression = False
        self._last_emitted_expression = None

        self.setup_ui()
        self.setup_connections()
        self.load_expression_history()

    def setup_ui(self):
        """Configure the expression widget interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        # Expression toolbar
        expr_toolbar = QToolBar()
        expr_toolbar.setAccessibleName("Actions de la règle du champ")
        expr_toolbar.setToolButtonStyle(ToolButtonTextBesideIcon)
        expr_toolbar.setIconSize(QSize(16, 16))

        # Expression actions
        self.validate_action = QAction(ui_icon("validate"), "Vérifier", self)
        self.validate_action.setToolTip("Vérifier la syntaxe et un objet de la couche")
        self.validate_action.triggered.connect(self.validate_expression)

        self.clear_action = QAction(ui_icon("clear"), "Effacer", self)
        self.clear_action.setToolTip("Effacer la règle courante")
        self.clear_action.triggered.connect(self.clear_expression)

        self.history_action = QAction(ui_icon("history"), "Historique", self)
        self.history_action.setToolTip("Retrouver une expression déjà utilisée")
        self.history_action.triggered.connect(self.show_history)

        self.help_action = QAction(ui_icon("help"), "Aide", self)
        self.help_action.setToolTip("Fonctions et exemples d'expressions QGIS")
        self.help_action.triggered.connect(self.show_help)

        expr_toolbar.addAction(self.validate_action)
        expr_toolbar.addAction(self.clear_action)
        expr_toolbar.addSeparator()
        expr_toolbar.addAction(self.history_action)
        expr_toolbar.addAction(self.help_action)
        action_buttons = []
        for action in (self.validate_action, self.clear_action, self.history_action, self.help_action):
            button = expr_toolbar.widgetForAction(action)
            button.setAccessibleName(action.text())
            button.setAccessibleDescription(action.toolTip())
            button.setFocusPolicy(FocusStrongFocus)
            action_buttons.append(button)

        layout.addWidget(expr_toolbar)

        # Expression builder main
        self.expression_builder = QgsExpressionBuilderWidget()
        self.expression_builder.setAccessibleName("Éditeur de la règle du champ")
        self.expression_builder.setMinimumHeight(150)

        # Configuration pour redimensionnement fluide des panneaux internes
        self.expression_builder.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)

        layout.addWidget(self.expression_builder)

        self.setLayout(layout)
        self.setFocusProxy(self.expression_builder)
        for previous, following in zip(action_buttons, action_buttons[1:]):
            self.setTabOrder(previous, following)

    def setup_connections(self):
        """Configure the signal connections"""
        self.expression_builder.expressionParsed.connect(self.on_expression_parsed)
        self.expression_builder.evalErrorChanged.connect(self.on_eval_error_changed)
        self.expression_builder.parserErrorChanged.connect(self.on_parser_error_changed)

    def set_layer(self, layer):
        """Set or detach the context layer cleanly (prevents dangling C++ pointers on Qt 5)."""
        self.layer = layer
        if layer:
            self.expression_builder.setLayer(layer)

            # Configuration du contexte d'expression
            context = create_layer_expression_context(layer)

            if layer.featureCount() > 0:
                feature = next(layer.getFeatures())
                context.setFeature(feature)

            self.expression_builder.setExpressionContext(context)
        else:
            self.expression_builder.setLayer(None)
            self.expression_builder.setExpressionContext(QgsExpressionContext())

    def set_expression(self, expression):
        """Set the expression"""
        self._original_expression = str(expression or "")
        self._last_emitted_expression = self._original_expression
        self._setting_expression = True
        try:
            self.expression_builder.setExpressionText(self._original_expression)
        finally:
            self._setting_expression = False
        self.validate_expression()

    def get_expression(self):
        """Get the current expression"""
        return self.expression_builder.expressionText()

    def _set_validate_icon(self, is_valid):
        if is_valid is True:
            self.validate_action.setIcon(ui_icon("validate", IconTone.SUCCESS))
        elif is_valid is False:
            self.validate_action.setIcon(ui_icon("validate", IconTone.WARNING))
        else:
            self.validate_action.setIcon(ui_icon("validate"))

    def validate_expression(self):
        """Validate the current expression"""
        expression_text = self.get_expression().strip()

        if not expression_text:
            self._set_validate_icon(False)
            self.expression_validated.emit(False, "Règle vide : saisissez une expression.")
            return

        try:
            is_valid, error_msg, expression = validate_expression_syntax(expression_text)
            if not is_valid:
                self._set_validate_icon(False)
                self.expression_validated.emit(False, f"Syntaxe à corriger dans l'éditeur : {error_msg}")
                return

            # Test d'évaluation
            if self.layer and self.layer.featureCount() > 0:
                context = create_layer_expression_context(self.layer)

                feature = next(self.layer.getFeatures())
                context.setFeature(feature)

                success, result, eval_error = evaluate_expression(expression, context)

                if not success:
                    self._set_validate_icon(False)
                    self.expression_validated.emit(False, f"Évaluation impossible sur cet objet : {eval_error}")
                    return

                # Expression valide
                self._set_validate_icon(True)
                self.expression_validated.emit(True, "Syntaxe et un objet vérifiés ; le reste de la couche reste à contrôler.")
            else:
                # Pas de couche pour tester - syntaxe valide
                self._set_validate_icon(True)
                self.expression_validated.emit(True, "Syntaxe vérifiée ; aucune couche disponible pour évaluer la règle.")

        except Exception as e:
            self._set_validate_icon(False)
            self.expression_validated.emit(False, f"Contrôle interrompu. Vérifiez la règle et la couche : {e}")

    def clear_expression(self):
        """Clear the expression"""
        self._original_expression = ""
        self.expression_builder.setExpressionText("")
        self.validate_expression()
        self._emit_expression_changed()

    def _emit_expression_changed(self):
        expression = self.get_expression()
        if expression != self._last_emitted_expression:
            self._last_emitted_expression = expression
            self.expression_changed.emit(expression)

    def add_to_history(self, expression):
        """Add an expression to the history"""
        if expression and expression not in self.expression_history:
            self.expression_history.insert(0, expression)
            if len(self.expression_history) > 50:  # Limit the history
                self.expression_history = self.expression_history[:50]
            self.save_expression_history()

    def show_history(self):
        """Show expression history"""
        if not self.expression_history:
            QMessageBox.information(self, "Historique", "Aucune expression enregistrée dans cet historique.")
            return

        dialog = ExpressionHistoryDialog(self.expression_history, self)
        result = dialog.exec()
        self.expression_builder.setFocus()
        if result == _DialogCode.Accepted:
            selected_expression = dialog.get_selected_expression()
            if selected_expression:
                self.set_expression(selected_expression)

    def show_help(self):
        """Show expression help"""
        help_html = """
<h2 style="margin-bottom: 15px;">Expressions QGIS</h2>

<h3 style="margin-top: 20px; margin-bottom: 10px;">Fonctions courantes</h3>
<ul style="margin-left: 10px;">
<li><b>Géométrie :</b> <code>area($geometry)</code>, <code>perimeter($geometry)</code>, <code>centroid($geometry)</code></li>
<li><b>Calcul :</b> <code>round(value, decimals)</code>, <code>abs(value)</code>, <code>sqrt(value)</code></li>
<li><b>Texte :</b> <code>concat(string1, string2)</code>, <code>upper("field")</code>, <code>lower("field")</code></li>
<li><b>Date:</b> <code>now()</code>, <code>year($now)</code>, <code>format_date($now, 'yyyy-MM-dd')</code></li>
<li><b>Champs :</b> <code>"field_name"</code> ou <code>attribute('field_name')</code></li>
</ul>

<h3 style="margin-top: 20px; margin-bottom: 10px;">Exemples à adapter aux champs de votre couche</h3>
<ul style="margin-left: 10px;">
<li><b>Surface en hectares, dans un SCR projeté en mètres :</b> <code>area($geometry) / 10000</code></li>
<li><b>Abscisse du centroïde :</b> <code>x(centroid($geometry))</code></li>
<li><b>Texte conditionnel :</b> <code>if("TYPE" = 'Building', 'Bâtiment', 'Autre')</code></li>
<li><b>Assemblage de texte :</b> <code>concat("NAME", ' - ', "CODE")</code></li>
</ul>

<h3 style="margin-top: 20px; margin-bottom: 10px;">Opérateurs</h3>
<ul style="margin-left: 10px;">
<li><b>Calcul :</b> <code>+ - * / % ^</code></li>
<li><b>Comparaison :</b> <code>= != &lt;&gt; &lt; &gt; &lt;= &gt;=</code></li>
<li><b>Logique :</b> <code>AND OR NOT</code></li>
<li><b>Motifs de texte :</b> <code>LIKE ILIKE ~ !~</code></li>
</ul>

<p style="margin-top: 20px;">
<b>Documentation complète :</b><br/>
<a href="https://docs.qgis.org/latest/fr/docs/user_manual/working_with_vector/expression.html">Manuel des expressions QGIS en français</a>
</p>
        """

        # Créer une QMessageBox personnalisée avec formatage HTML
        msg = QMessageBox(self)
        msg.setWindowTitle("Aide sur les expressions")
        msg.setTextFormat(RichText)
        msg.setText(help_html)
        msg.setIcon(MsgBoxIconInfo)
        msg.setStandardButtons(MsgBoxOk)
        msg.exec()
        self.expression_builder.setFocus()

    def load_expression_history(self):
        """Load expression history"""
        try:
            settings = QSettings()
            history = settings.value("Transformer/expression_history", [])
            if isinstance(history, list):
                self.expression_history = history
        except Exception as exc:
            QgsMessageLog.logMessage(f"Historique des expressions indisponible : {exc}", "Transformer", MsgWarning)
            self.expression_history = []

    def save_expression_history(self):
        """Save expression history"""
        try:
            settings = QSettings()
            settings.setValue("Transformer/expression_history", self.expression_history)
        except Exception as exc:
            QgsMessageLog.logMessage(f"Historique des expressions non enregistré : {exc}", "Transformer", MsgWarning)

    def on_expression_parsed(self, valid):
        """Expression parsing management"""
        if valid:
            self.validate_expression()
        else:
            self._set_validate_icon(False)
            self.expression_validated.emit(False, "Règle à corriger : ouvrez le détail dans l'éditeur.")
        if not self._setting_expression:
            self._emit_expression_changed()

    def on_eval_error_changed(self):
        """Evaluation error management"""
        QTimer.singleShot(100, self.validate_expression)

    def on_parser_error_changed(self):
        """Parsing error management"""
        QTimer.singleShot(100, self.validate_expression)
