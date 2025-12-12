# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import pyqtSignal, Qt, QSize, QSettings
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QMessageBox, QDialog, QListWidget, QDialogButtonBox
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsMessageLog, Qgis, QgsExpression, 
    QgsExpressionContext, QgsExpressionContextUtils
)

# Import QTimer with fallback
try:
    from qgis.PyQt.QtCore import QTimer
except ImportError:
    try:
        from PyQt5.QtCore import QTimer
    except ImportError:
        class QTimer:
            @staticmethod
            def singleShot(msec, func):
                try:
                    func()
                except:
                    pass

# Import QToolBar with fallback
try:
    from qgis.PyQt.QtWidgets import QToolBar, QAction
except ImportError:
    try:
        from PyQt5.QtWidgets import QToolBar, QAction
    except ImportError:
        class QToolBar:
            def __init__(self, text="", parent=None):
                pass
            def setToolButtonStyle(self, style):
                pass
            def setIconSize(self, size):
                pass
            def addAction(self, action):
                pass
        
        class QAction:
            def __init__(self, icon=None, text="", parent=None):
                pass
            def setToolTip(self, tip):
                pass
            def triggered(self):
                class Signal:
                    def connect(self, func):
                        pass
                return Signal()

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
from qgis.gui import QgsExpressionBuilderWidget


class ExpressionHistoryDialog(QDialog):
    """Dialog for selecting from expression history"""
    
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Expression History")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)
        self.selected_expression = None
        
        layout = QVBoxLayout(self)
        
        # List widget
        self.list_widget = QListWidget()
        for expr in history:
            self.list_widget.addItem(expr[:100] + "..." if len(expr) > 100 else expr)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)
        
        # Store full expressions
        self.history = history
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
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
        expr_toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        expr_toolbar.setIconSize(QSize(16, 16))
        
        # Expression actions
        self.validate_action = QAction(QIcon(":/images/themes/default/mIconSuccess.svg"), "Validate", self)
        self.validate_action.setToolTip("Validate expression syntax")
        self.validate_action.triggered.connect(self.validate_expression)
        
        self.clear_action = QAction(QIcon(":/images/themes/default/mActionDeleteSelected.svg"), "Clear", self)
        self.clear_action.setToolTip("Clear expression")
        self.clear_action.triggered.connect(self.clear_expression)
        
        self.history_action = QAction(QIcon(":/images/themes/default/mActionHistory.svg"), "History", self)
        self.history_action.setToolTip("Expression history")
        self.history_action.triggered.connect(self.show_history)
        
        self.help_action = QAction(QIcon(":/images/themes/default/mActionHelpContents.svg"), "Help", self)
        self.help_action.setToolTip("Expression help")
        self.help_action.triggered.connect(self.show_help)
        
        expr_toolbar.addAction(self.validate_action)
        expr_toolbar.addAction(self.clear_action)
        expr_toolbar.addSeparator()
        expr_toolbar.addAction(self.history_action)
        expr_toolbar.addAction(self.help_action)
        
        layout.addWidget(expr_toolbar)
        
        # Expression builder main
        self.expression_builder = QgsExpressionBuilderWidget()
        self.expression_builder.setMinimumHeight(300)
        
        # Configuration pour redimensionnement fluide des panneaux internes
        self.expression_builder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Custom CSS style to reduce the width of arithmetic buttons + fluidité des panneaux
        custom_style = """
        QgsExpressionBuilderWidget {
            qproperty-resizeMode: "ResizeToContents";
        }
        QgsExpressionBuilderWidget QSplitter {
            background: transparent;
        }
        QgsExpressionBuilderWidget QSplitter::handle {
            background: #cccccc;
            width: 2px;
            height: 2px;
        }
        QgsExpressionBuilderWidget QTreeWidget {
            min-width: 150px;
            max-width: none;
        }
        QgsExpressionBuilderWidget QTextEdit {
            min-width: 100px;
        }
        QgsExpressionBuilderWidget QPushButton {
            max-width: 30px !important;
            min-width: 25px !important;
            padding: 1px 2px !important;
            margin: 1px !important;
            font-size: 9px !important;
        }
        QgsExpressionBuilderWidget QPushButton[text="+"], 
        QgsExpressionBuilderWidget QPushButton[text="-"], 
        QgsExpressionBuilderWidget QPushButton[text="*"], 
        QgsExpressionBuilderWidget QPushButton[text="/"], 
        QgsExpressionBuilderWidget QPushButton[text="%"], 
        QgsExpressionBuilderWidget QPushButton[text="^"],
        QgsExpressionBuilderWidget QPushButton[text="("], 
        QgsExpressionBuilderWidget QPushButton[text=")"], 
        QgsExpressionBuilderWidget QPushButton[text="||"],
        QgsExpressionBuilderWidget QPushButton[text="&&"],
        QgsExpressionBuilderWidget QPushButton[text="\n"],
        QgsExpressionBuilderWidget QPushButton[text="<"], 
        QgsExpressionBuilderWidget QPushButton[text=">"],
        QgsExpressionBuilderWidget QPushButton[text="<="], 
        QgsExpressionBuilderWidget QPushButton[text=">="], 
        QgsExpressionBuilderWidget QPushButton[text="!="],
        QgsExpressionBuilderWidget QPushButton[text="<>"], 
        QgsExpressionBuilderWidget QPushButton[text="="] {
            max-width: 25px !important;
            min-width: 20px !important;
            padding: 0px 1px !important;
            font-size: 8px !important;
        }
        """
        self.expression_builder.setStyleSheet(custom_style)
        
        # Appliquer le style après un délai pour s'assurer que le widget est chargé
        QTimer.singleShot(100, lambda: self.expression_builder.setStyleSheet(custom_style))
        
        layout.addWidget(self.expression_builder)
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure the signal connections"""
        self.expression_builder.expressionParsed.connect(self.on_expression_parsed)
        self.expression_builder.evalErrorChanged.connect(self.on_eval_error_changed)
        self.expression_builder.parserErrorChanged.connect(self.on_parser_error_changed)
    
    def set_layer(self, layer):
        """Set the context layer"""
        self.layer = layer
        if layer:
            self.expression_builder.setLayer(layer)
            
            # Configuration du contexte d'expression
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
            
            if layer.featureCount() > 0:
                feature = next(layer.getFeatures())
                context.setFeature(feature)
            
            self.expression_builder.setExpressionContext(context)
    
    def set_expression(self, expression):
        """Set the expression"""
        
        # CORRECTION: Sauvegarder l'expression originale
        self._original_expression = expression
        
        self.expression_builder.setExpressionText(expression)
        
        
        self.validate_expression()
    
    def get_expression(self):
        """Get the current expression"""
        expression = self.expression_builder.expressionText()
        
        # CORRECTION: Si l'expression a été tronquée, retourner l'originale
        if hasattr(self, '_original_expression') and self._original_expression and len(expression) < len(self._original_expression):
            # Vérifier si c'est une troncature de paramètres (même début)
            if self._original_expression.startswith(expression.rstrip(')')):
                return self._original_expression
        
        return expression
    
    def validate_expression(self):
        """Validate the current expression"""
        expression_text = self.get_expression().strip()
        
        if not expression_text:
            self.expression_validated.emit(False, "Empty expression")
            return
        
        try:
            expression = QgsExpression(expression_text)
            
            if expression.hasParserError():
                error_msg = expression.parserErrorString()
                self.expression_validated.emit(False, error_msg)
                return
            
            # Test d'évaluation
            if self.layer and self.layer.featureCount() > 0:
                context = QgsExpressionContext()
                context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(self.layer))
                
                feature = next(self.layer.getFeatures())
                context.setFeature(feature)
                context.setFields(self.layer.fields())
                
                result = expression.evaluate(context)
                
                if expression.hasEvalError():
                    error_msg = expression.evalErrorString()
                    self.expression_validated.emit(False, error_msg)
                    return
                
                # Expression valide
                self.expression_validated.emit(True, "Valid expression")
            else:
                # Pas de couche pour tester - syntaxe valide
                self.expression_validated.emit(True, "Syntax valid")
                
        except Exception as e:
            self.expression_validated.emit(False, str(e))
    
    def clear_expression(self):
        """Clear the expression"""
        self.expression_builder.setExpressionText("")
        self.validate_expression()
    
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
            QMessageBox.information(self, "History", "No expression history available")
            return
        
        dialog = ExpressionHistoryDialog(self.expression_history, self)
        if dialog.exec_() == QDialog.Accepted:
            selected_expression = dialog.get_selected_expression()
            if selected_expression:
                self.set_expression(selected_expression)
    
    def show_help(self):
        """Show expression help"""
        help_html = """
<h2 style="margin-bottom: 15px;">QGIS Expression Help</h2>

<h3 style="margin-top: 20px; margin-bottom: 10px;">Common Functions</h3>
<ul style="margin-left: 10px;">
<li><b>Geometry:</b> <code>area($geometry)</code>, <code>perimeter($geometry)</code>, <code>centroid($geometry)</code></li>
<li><b>Math:</b> <code>round(value, decimals)</code>, <code>abs(value)</code>, <code>sqrt(value)</code></li>
<li><b>String:</b> <code>concat(string1, string2)</code>, <code>upper("field")</code>, <code>lower("field")</code></li>
<li><b>Date:</b> <code>now()</code>, <code>year($now)</code>, <code>format_date($now, 'yyyy-MM-dd')</code></li>
<li><b>Fields:</b> <code>"field_name"</code> or <code>attribute('field_name')</code></li>
</ul>

<h3 style="margin-top: 20px; margin-bottom: 10px;">Examples</h3>
<ul style="margin-left: 10px;">
<li><b>Area in hectares:</b> <code>area($geometry) / 10000</code></li>
<li><b>Centroid coordinates:</b> <code>x(centroid($geometry))</code></li>
<li><b>Conditional text:</b> <code>if("TYPE" = 'Building', 'Bâtiment', 'Autre')</code></li>
<li><b>String formatting:</b> <code>concat("NAME", ' - ', "CODE")</code></li>
</ul>

<h3 style="margin-top: 20px; margin-bottom: 10px;">Operators</h3>
<ul style="margin-left: 10px;">
<li><b>Arithmetic:</b> <code>+ - * / % ^</code></li>
<li><b>Comparison:</b> <code>= != <> < > <= >=</code></li>
<li><b>Logical:</b> <code>AND OR NOT</code></li>
<li><b>Pattern:</b> <code>LIKE ILIKE ~ !~</code></li>
</ul>

<p style="margin-top: 20px; font-size: 11px;">
<b>Complete documentation:</b><br/>
<a href="https://docs.qgis.org/latest/en/docs/user_manual/working_with_vector/expression.html">https://docs.qgis.org/latest/en/docs/user_manual/working_with_vector/expression.html</a>
</p>
        """
        
        # Créer une QMessageBox personnalisée avec formatage HTML
        msg = QMessageBox(self)
        msg.setWindowTitle("Expression Help")
        msg.setTextFormat(Qt.RichText)
        msg.setText(help_html)
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    
    def load_expression_history(self):
        """Load expression history"""
        try:
            settings = QSettings()
            history = settings.value("Transformer/expression_history", [])
            if isinstance(history, list):
                self.expression_history = history
        except:
            self.expression_history = []
    
    def save_expression_history(self):
        """Save expression history"""
        try:
            settings = QSettings()
            settings.setValue("Transformer/expression_history", self.expression_history)
        except:
            pass
    
    def on_expression_parsed(self, valid):
        """Expression parsing management"""
        if valid:
            self.validate_expression()
            expression_text = self.get_expression()
            self.expression_changed.emit(expression_text)
    
    def on_eval_error_changed(self):
        """Evaluation error management"""
        QTimer.singleShot(100, self.validate_expression)
    
    def on_parser_error_changed(self):
        """Parsing error management"""
        QTimer.singleShot(100, self.validate_expression)

