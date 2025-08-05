# -*- coding: utf-8 -*-
"""
 Interface for Transformer - Elite Version
Developed by YADDA

Native QGIS interface with advanced features and optimal ergonomics
"""

import os
import json
import copy
import re
from pathlib import Path

from datetime import datetime
from dataclasses import dataclass
from enum import Enum

# Centralized logger for the plugin
from .logger import logger as plugin_logger, log_info, log_warning, log_error, log_success

from qgis.PyQt.QtCore import (
    Qt, pyqtSignal, QTimer, QSettings, QSize
)

from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QPlainTextEdit, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QSlider, QProgressBar, QTabWidget, QWidget,
    QGroupBox, QFrame, QSplitter, QScrollArea, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy, QSpacerItem, QToolButton, QMenu, QAction, QActionGroup,
    QButtonGroup, QRadioButton, QToolBar, QStatusBar, QMenuBar,
    QFileDialog, QMessageBox, QInputDialog, QColorDialog, QFontDialog,
    QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem, QMainWindow, QDockWidget, QDialogButtonBox
)

from qgis.PyQt.QtGui import (
    QIcon, QFont, QColor, QPalette, QPixmap, QPainter, QBrush, QPen, QFontMetrics,
    QKeySequence, QShortcut, QDesktopServices, QClipboard, QDrag, QValidator,
    QIntValidator, QDoubleValidator, QRegExpValidator, QStandardItemModel,
    QStandardItem, QMovie, QCursor, QPolygon, QLinearGradient, QRadialGradient,
    QConicalGradient, QTextCharFormat, QTextCursor, QTextDocument, QSyntaxHighlighter,
    QTextBlockFormat, QFontDatabase, QTransform, QPainterPath, QRegion,
    QBitmap, QImageReader, QImageWriter, QPaintEvent, QResizeEvent, QShowEvent,
    QHideEvent, QCloseEvent, QKeyEvent, QMouseEvent, QWheelEvent, QContextMenuEvent,
    QFocusEvent, QMoveEvent, QDropEvent, QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent
)

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsMessageLog, Qgis, QgsDataSourceUri, QgsCoordinateTransform, QgsWkbTypes,
    QgsFeatureRequest, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
    QgsFields, QgsField, QgsFeature, QgsGeometry, QgsRectangle, QgsMapLayer,
    QgsVectorDataProvider, QgsDataProvider, QgsProviderRegistry, QgsApplication,
    QgsTask, QgsTaskManager, QgsNetworkAccessManager, QgsSettings, QgsProject,
    QgsCoordinateTransformContext, QgsFieldConstraints, QgsLayerTreeGroup,
    QgsLayerTreeLayer, QgsLayerTreeNode, QgsMemoryProviderUtils, QgsProcessingFeedback,
    QgsProcessingContext, QgsProcessingAlgorithm, QgsProcessingUtils, QgsPointXY,
    QgsFeatureIterator, QgsDistanceArea, QgsUnitTypes, QgsCoordinateFormatter,
    QgsLayerMetadata, QgsAbstractMetadataBase, QgsLayerMetadataFormatter,
    QgsProviderMetadata, QgsDataItemProvider, QgsDataItem, QgsLayerItem,
    QgsDefaultValue, QgsFieldFormatter, QgsFieldFormatterRegistry, QgsValueMapFieldFormatter,
    QgsValueRelationFieldFormatter, QgsRelationReferenceFieldFormatter, QgsDateTimeFieldFormatter,
    QgsRangeFieldFormatter, QgsCheckBoxFieldFormatter,  # Importés depuis qgis.core au lieu de qgis.gui pour QGIS 3.42+
    QgsProjectStorage, QgsReadWriteContext, QgsMapLayerStore, 
    QgsPluginLayer, QgsPluginLayerRegistry, QgsDataDefinedSizeLegend,
    QgsLegendRenderer, QgsLayerTreeModel, QgsLayerTree, QgsLayerTreeUtils,
    QgsSymbol, QgsSymbolLayer, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsRendererCategory, QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsNullSymbolRenderer,
    QgsInvertedPolygonRenderer, QgsPointPatternFillSymbolLayer, QgsSimpleMarkerSymbolLayer
)

from qgis.gui import (
    QgsExpressionBuilderDialog, QgsExpressionLineEdit, QgsFieldExpressionWidget,
    QgsProjectionSelectionWidget, QgsExtentGroupBox, QgsCollapsibleGroupBox,
    QgsColorButton, QgsFontButton, QgsSpinBox, QgsDoubleSpinBox, QgsFilterLineEdit,
    QgsFileWidget, QgsAuthConfigSelect, QgsEncodingFileDialog, QgsMapCanvas,
    QgsMapToolIdentify, QgsMapTool, QgsRubberBand, QgsVertexMarker, QgsMapToolPan,
    QgsMapToolZoom, QgsMapToolEmitPoint, QgsMapToolExtent,
    QgsSymbolButton, QgsUnitSelectionWidget, QgsScaleWidget,
    QgsOpacityWidget, QgsBlendModeComboBox, QgsPropertyOverrideButton,
    QgsExpressionBuilderWidget, QgsCodeEditorPython, QgsCodeEditorSQL, QgsCodeEditorExpression,
    QgsCompoundColorWidget, QgsColorDialog, QgsColorRampButton, 
    QgsColorSwatchGridAction, QgsDateTimeEdit, QgsDateEdit, QgsTimeEdit,
    QgsExtentWidget, QgsRasterBandComboBox, QgsFieldComboBox, QgsMapLayerComboBox,
    QgsCheckableComboBox, QgsLayerTreeView, QgsLayerTreeMapCanvasBridge,
    QgsMapLayerAction, QgsRasterLayerSaveAsDialog,
    QgsMessageBar, QgsMessageBarItem, QgsMessageViewer, QgsCredentialDialog,
    QgsNewHttpConnection, 
    QgsProjectionSelectionDialog, QgsCoordinateReferenceSystemProxyModel,
    QgsHighlight, QgsAttributeTableModel, QgsAttributeTableView, QgsAttributeTableDelegate,
    QgsAttributeTableFilterModel, QgsFeatureSelectionModel, QgsIFeatureSelectionManager,
    QgsActionMenu, QgsAttributeForm, QgsAttributeDialog,
    QgsFieldValidator, QgsEditorWidgetWrapper, QgsEditorWidgetFactory, QgsEditorWidgetRegistry,


)

# Support conditionnel for different QGIS versions
try:
    # Try importing classes specific to QGIS < 3.42
    from qgis.gui import QgsVectorLayerSelectionManager
    HAS_OLD_SELECTION_MANAGER = True
except ImportError:
    # Utiliser les classes modernes pour QGIS >= 3.42
    HAS_OLD_SELECTION_MANAGER = False
    # QgsVectorLayerSelectionManager est remplacé par QgsIFeatureSelectionManager dans les versions récentes
    # QgsLayerTreeModel n'est plus nécessaire car QgsLayerTreeView l'intègre directement
    # Note: nous utilisons déjà QgsIFeatureSelectionManager qui est l'interface moderne

# Import conditionnel du module d'export développé par l'équipe
try:
    from .export_module import ExportWidget, ExportManager, ExportFormat, EXPORT_AVAILABLE
    EXPORT_CLASSES_AVAILABLE = True and EXPORT_AVAILABLE
except ImportError as e:
    ExportWidget = None
    ExportManager = None
    ExportFormat = None
    EXPORT_CLASSES_AVAILABLE = False

# Import of the PostgreSQL integration module
try:
    from .postgresql_integration import PostgreSQLIntegrationWidget
    POSTGRESQL_INTEGRATION_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"PostgreSQL integration import failed: {str(e)}", "Transformer", Qgis.Critical)
    POSTGRESQL_INTEGRATION_AVAILABLE = False
    PostgreSQLIntegrationWidget = None
except Exception as e:
    QgsMessageLog.logMessage(f"PostgreSQL integration error: {str(e)}", "Transformer", Qgis.Critical)
    POSTGRESQL_INTEGRATION_AVAILABLE = False
    PostgreSQLIntegrationWidget = None

# Global variables from the main module will be imported in the methods that need them
# to avoid circular imports


class InterfaceTheme(Enum):
    """Available interface themes"""
    LIGHT = "light"
    DARK = "dark"
    QGIS_NATIVE = "qgis_native"
    PROFESSIONAL = "professional"
    HIGH_CONTRAST = "high_contrast"


class PanelMode(Enum):
    """Panel display modes"""
    COMPACT = "compact"
    STANDARD = "standard"
    EXTENDED = "extended"
    DOCKED = "docked"


@dataclass
class InterfaceSettings:
    """Interface configuration"""
    theme: InterfaceTheme = InterfaceTheme.QGIS_NATIVE
    panel_mode: PanelMode = PanelMode.STANDARD
    auto_save_config: bool = True
    show_tooltips: bool = True
    enable_animations: bool = True
    compact_toolbar: bool = False
    show_preview_panel: bool = True
    enable_live_preview: bool = True
    expression_syntax_highlighting: bool = True
    auto_complete_expressions: bool = True
    show_field_types: bool = True
    group_similar_operations: bool = True
    enable_undo_redo: bool = True
    max_undo_steps: int = 50
    auto_backup_interval: int = 300  # secondes
    show_performance_stats: bool = False
    enable_debugging: bool = False


class ExpressionSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighting for QGIS expressions"""
    
    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []
        self.setup_rules()
    
    def setup_rules(self):
        """Configure highlighting rules"""
        # QGIS functions
        function_format = QTextCharFormat()
        function_format.setColor(QColor(0, 100, 200))
        function_format.setFontWeight(QFont.Bold)
        
        functions = [
            'area', 'perimeter', 'length', 'distance', 'centroid', 'bounds',
            'buffer', 'convex_hull', 'difference', 'intersection', 'union',
            'contains', 'crosses', 'disjoint', 'equals', 'intersects', 'overlaps',
            'touches', 'within', 'relate', 'transform', 'translate', 'rotate',
            'scale', 'geometry', 'geom_from_wkt', 'geom_to_wkt', 'x', 'y', 'z',
            'xmin', 'xmax', 'ymin', 'ymax', 'num_points', 'num_rings', 'num_geometries',
            'is_valid', 'make_point', 'make_line', 'make_polygon', 'nodes_to_points',
            'point_n', 'exterior_ring', 'interior_ring_n', 'geometry_n',
            'start_point', 'end_point', 'concat', 'substr', 'lower', 'upper',
            'title', 'trim', 'ltrim', 'rtrim', 'length', 'regexp_match', 'regexp_replace',
            'regexp_substr', 'strpos', 'left', 'right', 'rpad', 'lpad', 'format',
            'format_number', 'format_date', 'now', 'age', 'year', 'month', 'week',
            'day', 'hour', 'minute', 'second', 'epoch', 'datetime_from_epoch',
            'to_date', 'to_time', 'to_datetime', 'to_interval', 'day_of_week',
            'abs', 'acos', 'asin', 'atan', 'atan2', 'ceil', 'cos', 'degrees',
            'exp', 'floor', 'ln', 'log', 'log10', 'max', 'min', 'pi', 'power',
            'radians', 'rand', 'randf', 'round', 'sin', 'sqrt', 'tan', 'clamp',
            'coalesce', 'if', 'try', 'attribute', 'get_feature', 'get_feature_by_id'
        ]
        
        for func in functions:
            pattern = f'\\b{func}\\b'
            self.highlighting_rules.append((pattern, function_format))
        
        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setColor(QColor(150, 0, 150))
        keyword_format.setFontWeight(QFont.Bold)
        
        keywords = ['AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END']
        for keyword in keywords:
            pattern = f'\\b{keyword}\\b'
            self.highlighting_rules.append((pattern, keyword_format))
        
        # Strings
        string_format = QTextCharFormat()
        string_format.setColor(QColor(0, 150, 0))
        self.highlighting_rules.append(("'[^']*'", string_format))
        self.highlighting_rules.append(('"[^"]*"', string_format))
        
        # Numbers
        number_format = QTextCharFormat()
        number_format.setColor(QColor(200, 100, 0))
        self.highlighting_rules.append(("\\b\\d+\\.?\\d*\\b", number_format))
        
        # Fields (double quoted)
        field_format = QTextCharFormat()
        field_format.setColor(QColor(0, 0, 200))
        field_format.setFontItalic(True)
        self.highlighting_rules.append(('"[^"]*"', field_format))
        
        # Comments
        comment_format = QTextCharFormat()
        comment_format.setColor(QColor(128, 128, 128))
        comment_format.setFontItalic(True)
        self.highlighting_rules.append(("--[^\n]*", comment_format))
    
    def highlightBlock(self, text):
        """Apply syntax highlighting to text block"""
        for pattern, format_obj in self.highlighting_rules:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.span()
                self.setFormat(start, end - start, format_obj)


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
        
        # Custom CSS style to reduce the width of arithmetic buttons
        custom_style = """
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
        # DEBUG: Log l'expression reçue
        QgsMessageLog.logMessage(f"DEBUG: AdvancedExpressionWidget.set_expression() received: '{expression}' (length: {len(expression)})", "Transformer", Qgis.Info)
        
        # CORRECTION: Sauvegarder l'expression originale
        self._original_expression = expression
        
        self.expression_builder.setExpressionText(expression)
        
        # DEBUG: Vérifier ce que le widget a réellement stocké
        stored_expression = self.expression_builder.expressionText()
        QgsMessageLog.logMessage(f"DEBUG: After setExpressionText(), widget contains: '{stored_expression}' (length: {len(stored_expression)})", "Transformer", Qgis.Info)
        
        self.validate_expression()
    
    def get_expression(self):
        """Get the current expression"""
        expression = self.expression_builder.expressionText()
        
        # CORRECTION: Si l'expression a été tronquée, retourner l'originale
        if hasattr(self, '_original_expression') and self._original_expression and len(expression) < len(self._original_expression):
            # Vérifier si c'est une troncature de paramètres (même début)
            if self._original_expression.startswith(expression.rstrip(')')):
                QgsMessageLog.logMessage(f"DEBUG: Expression was truncated, returning original: '{self._original_expression}'", "Transformer", Qgis.Info)
                return self._original_expression
        
        # DEBUG: Log l'expression retournée
        QgsMessageLog.logMessage(f"DEBUG: AdvancedExpressionWidget.get_expression() returning: '{expression}' (length: {len(expression)})", "Transformer", Qgis.Info)
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
        help_text = """
QGIS Expression Help

Common Functions:
• Geometry: area($geometry), perimeter($geometry), centroid($geometry)
• Math: round(value, decimals), abs(value), sqrt(value)
• Text: upper(text), lower(text), concat(text1, text2)
• Conditional: if(condition, true_value, false_value)
• Fields: "field_name" or attribute('field_name')

Examples:
• Area in hectares: area($geometry) / 10000
• Centroid coordinates: x(centroid($geometry))
• Conditional text: if("TYPE" = 'Building', 'Bâtiment', 'Autre')
• String formatting: concat("NAME", ' - ', "CODE")

Operators:
• Arithmetic: +, -, *, /, %, ^
• Comparison: =, !=, <>, <, >, <=, >=
• Logical: AND, OR, NOT
• Pattern: LIKE, ILIKE, ~, !~

For complete documentation, visit:
https://docs.qgis.org/latest/en/docs/user_manual/working_with_vector/expression.html
        """
        
        QMessageBox.information(self, "Expression Help", help_text)
    
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


class ExpressionHistoryDialog(QDialog):
    """Expression history dialog"""
    
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.selected_expression = None
        
        self.setWindowTitle("Expression History")
        self.setModal(True)
        self.resize(600, 400)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Liste d'historique
        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)
        self.history_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        for expression in self.history:
            item = QListWidgetItem(expression)
            item.setToolTip(expression)
            self.history_list.addItem(item)
        
        layout.addWidget(QLabel("Select an expression from history:"))
        layout.addWidget(self.history_list)
        
        # Boutons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def on_item_double_clicked(self, item):
        """Double-click item management"""
        self.selected_expression = item.text()
        self.accept()
    
    def accept(self):
        """Accept the dialog"""
        current_item = self.history_list.currentItem()
        if current_item:
            self.selected_expression = current_item.text()
        super().accept()
    
    def get_selected_expression(self):
        """Get the selected expression"""
        return self.selected_expression


class SmartFilterWidget(QWidget):
    """Smart filter widget with suggestions"""
    
    filter_changed = pyqtSignal(str)
    filter_applied = pyqtSignal(str, bool)  # expression, enabled
    
    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.filter_templates = self.load_filter_templates()
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """Configure the filter widget interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header with activation
        header_layout = QHBoxLayout()
        
        self.enable_filter_cb = QCheckBox("Enable Filter")
        self.enable_filter_cb.setFont(QFont("Segoe UI", 9, QFont.Bold))
        header_layout.addWidget(self.enable_filter_cb)
        
        header_layout.addStretch()
        
        # Action buttons
        self.test_filter_btn = QPushButton("Test")
        self.test_filter_btn.setMaximumWidth(60)
        self.test_filter_btn.setMaximumHeight(28)
        self.test_filter_btn.setEnabled(False)
        
        self.builder_btn = QPushButton("Builder")
        self.builder_btn.setMaximumWidth(70)
        self.builder_btn.setMaximumHeight(28)
        self.builder_btn.setEnabled(False)
        
        header_layout.addWidget(self.test_filter_btn)
        header_layout.addWidget(self.builder_btn)
        
        layout.addLayout(header_layout)
        
        # Filter expression with auto-completion
        filter_layout = QHBoxLayout()
        
        self.filter_expression = QLineEdit()
        self.filter_expression.setPlaceholderText('e.g., "TYPE" = \'Building\' AND area($geometry) > 1000')
        self.filter_expression.setEnabled(False)
        
        filter_layout.addWidget(QLabel("Filter:"))
        filter_layout.addWidget(self.filter_expression)
        
        layout.addLayout(filter_layout)
        
        # Templates and suggestions
        templates_layout = QHBoxLayout()
        templates_layout.addWidget(QLabel("Quick:"))
        
        # Quick templates buttons
        self.template_buttons = []
        templates = [
            ("Area > 100", "area($geometry) > 100"),
            ("Valid Geom", "is_valid($geometry)"),
            ("Not NULL", '"FIELD" IS NOT NULL'),
            ("By Type", '"TYPE" = \'VALUE\''),
            ("Date Range", '"DATE" >= \'2023-01-01\'')
        ]

        for name, template in templates:
            btn = QPushButton(name)
            btn.setMaximumWidth(65)
            btn.setMaximumHeight(24)
            btn.setEnabled(False)
            btn.setStyleSheet("QPushButton { font-size: 9px; }")
            btn.clicked.connect(lambda checked, t=template: self.apply_template(t))
            self.template_buttons.append(btn)
            templates_layout.addWidget(btn)
        
        templates_layout.addStretch()
        layout.addLayout(templates_layout)
        
        # Filter info panel
        self.filter_info_panel = QFrame()
        self.filter_info_panel.setFrameStyle(QFrame.StyledPanel)
        self.filter_info_panel.setMaximumHeight(40)
        self.filter_info_panel.setVisible(False)
        
        info_layout = QHBoxLayout(self.filter_info_panel)
        info_layout.setContentsMargins(6, 4, 6, 4)
        
        self.filter_status_label = QLabel()
        self.filter_count_label = QLabel()
        
        info_layout.addWidget(self.filter_status_label)
        info_layout.addStretch()
        info_layout.addWidget(self.filter_count_label)
        
        layout.addWidget(self.filter_info_panel)
        
        self.setLayout(layout)
    
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
    
    def update_template_buttons(self):
        """Update template buttons based on the layer"""
        if not self.layer:
            return
        
        # Adapt templates based on available fields
        fields = self.layer.fields()
        field_names = [field.name() for field in fields]
        
        # Search for common fields
        type_fields = [name for name in field_names if 'type' in name.lower() or 'class' in name.lower()]
        status_fields = [name for name in field_names if 'status' in name.lower() or 'state' in name.lower()]
        date_fields = [name for name in field_names if 'date' in name.lower() or 'time' in name.lower()]
        
        # Update templates
        if len(self.template_buttons) >= 4:
            if type_fields:
                self.template_buttons[3].setText(f'By {type_fields[0][:6]}')
                self.template_buttons[3].clicked.disconnect()
                self.template_buttons[3].clicked.connect(
                    lambda: self.apply_template(f'"{type_fields[0]}" = \'VALUE\'')
                )
            
            if date_fields:
                self.template_buttons[4].setText(f'{date_fields[0][:6]} >')
                self.template_buttons[4].clicked.disconnect()
                self.template_buttons[4].clicked.connect(
                    lambda: self.apply_template(f'"{date_fields[0]}" >= \'2023-01-01\'')
                )
    
    def on_filter_enabled_changed(self, enabled):
        """Filter activation/deactivation management"""
        self.filter_expression.setEnabled(enabled)
        self.builder_btn.setEnabled(enabled)
        self.test_filter_btn.setEnabled(enabled)
        
        for btn in self.template_buttons:
            btn.setEnabled(enabled)
        
        self.filter_info_panel.setVisible(enabled)
        
        if not enabled:
            self.filter_expression.clear()
        
        self.emit_filter_changed()
    
    def on_filter_expression_changed(self):
        """Filter expression change management"""
        self.filter_changed.emit(self.get_filter_expression())
        self.update_filter_info()
    
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
            QMessageBox.warning(self, "Warning", "No layer context available")
            return
        
        filter_expr = self.get_filter_expression()
        if not filter_expr:
            QMessageBox.warning(self, "Warning", "No filter expression to test")
            return
        
        try:
            # Test expression
            expression = QgsExpression(filter_expr)
            
            if expression.hasParserError():
                QMessageBox.warning(self, "Filter Error", f"Syntax error: {expression.parserErrorString()}")
                return
            
            # Count matching features
            request = QgsFeatureRequest()
            request.setFilterExpression(filter_expr)
            
            filtered_features = list(self.layer.getFeatures(request))
            total_features = self.layer.featureCount()
            filtered_count = len(filtered_features)
            
            # Display results
            reduction_percent = ((total_features - filtered_count) / total_features * 100) if total_features > 0 else 0
            
            result_message = f"""Filter Test Results

Expression: {filter_expr}

Results:
• Total features: {total_features:,}
• Filtered features: {filtered_count:,}
• Reduction: {reduction_percent:.1f}%

Filter is valid and ready to use!"""
            
            QMessageBox.information(self, "Filter Test", result_message)
            
            # Update display
            self.update_filter_status(True, filtered_count, total_features)
            
        except Exception as e:
            QMessageBox.critical(self, "Filter Error", f"Error testing filter: {str(e)}")
    
    def open_filter_builder(self):
        """Open the expression builder for the filter"""
        if not self.layer:
            QMessageBox.warning(self, "Warning", "No layer context available")
            return
        
        current_expr = self.filter_expression.text().strip()
        
        dialog = QgsExpressionBuilderDialog(self.layer, current_expr, self)
        dialog.setWindowTitle("Filter Expression Builder")
        
        if dialog.exec_() == QDialog.Accepted:
            new_expr = dialog.expressionText()
            self.filter_expression.setText(new_expr)
            
            # Automatic test after construction
            QTimer.singleShot(100, self.test_filter)
    
    def get_filter_expression(self):
        """Get the current filter expression"""
        if self.enable_filter_cb.isChecked():
            return self.filter_expression.text().strip()
        return ""
    
    def get_filter_config(self):
        """Get the filter configuration"""
        return {
            "enabled": self.enable_filter_cb.isChecked(),
            "expression": self.get_filter_expression()
        }
    
    def set_filter_config(self, config):
        """Set the filter configuration"""
        if config and isinstance(config, dict):
            enabled = config.get("enabled", False)
            expression = config.get("expression", "")
            
            self.enable_filter_cb.setChecked(enabled)
            self.filter_expression.setText(expression)
    
    def emit_filter_changed(self):
        """Emit the filter change signal"""
        config = self.get_filter_config()
        self.filter_applied.emit(config.get("expression", ""), config.get("enabled", False))
    
    def update_filter_info(self):
        """Update filter information"""
        if not self.enable_filter_cb.isChecked():
            return
        
        filter_expr = self.get_filter_expression()
        if filter_expr:
            self.filter_status_label.setText("Filter active")
            self.filter_status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
        else:
            self.filter_status_label.setText("Filter enabled - no expression")
            self.filter_status_label.setStyleSheet("color: #f44336;")
    
    def update_filter_status(self, valid, filtered_count, total_count):
        """Update filter status"""
        if valid:
            self.filter_status_label.setText("✓ Filter valid")
            self.filter_status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            self.filter_count_label.setText(f"{filtered_count:,} / {total_count:,} features")
        else:
            self.filter_status_label.setText("✗ Filter invalid")
            self.filter_status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            self.filter_count_label.clear()
    
    def load_filter_templates(self):
        """Load filter templates"""
        return {
            "geometry": [
                ("Valid geometries", "is_valid($geometry)"),
                ("Area greater than", "area($geometry) > 1000"),
                ("Perimeter less than", "perimeter($geometry) < 500"),
                ("Contains point", "contains($geometry, make_point(x, y))"),
                ("Intersects extent", "intersects($geometry, geom_from_wkt('POLYGON((...))'))")
            ],
            "attributes": [
                ("Not null", '"FIELD" IS NOT NULL'),
                ("Equals value", '"FIELD" = \'VALUE\''),
                ("Contains text", '"FIELD" LIKE \'%TEXT%\''),
                ("Numeric range", '"FIELD" BETWEEN 10 AND 100'),
                ("In list", '"FIELD" IN (\'A\', \'B\', \'C\')')
            ],
            "temporal": [
                ("After date", '"DATE_FIELD" >= \'2023-01-01\''),
                ("Between dates", '"DATE_FIELD" BETWEEN \'2023-01-01\' AND \'2023-12-31\''),
                ("Recent features", '"DATE_FIELD" >= (now() - interval \'30 days\')'),
                ("This year", 'year("DATE_FIELD") = year(now())'),
                ("This month", 'month("DATE_FIELD") = month(now()) AND year("DATE_FIELD") = year(now())')
            ]
        }


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
                background-color: #E3F2FD;
                border: 1px solid #2196F3;
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #BBDEFB;
            }
        """)
        self.copy_all_btn.setToolTip("Copy all existing fields from the selected vector file")
        
        self.add_field_btn = QPushButton("➕ Add Column")
        self.add_field_btn.setMinimumWidth(100)
        self.add_field_btn.setMinimumHeight(32)
        self.add_field_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8F5E8;
                border: 1px solid #4CAF50;
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
                color: #2E7D32;
            }
            QPushButton:hover {
                background-color: #C8E6C9;
            }
        """)
        self.add_field_btn.setToolTip("Add a new calculated field (column) to the output table")
        
        self.edit_field_btn = QPushButton("✏️ Edit")
        self.edit_field_btn.setMinimumWidth(70)
        self.edit_field_btn.setMinimumHeight(32)
        self.edit_field_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF3E0;
                border: 1px solid #FF9800;
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FFE0B2;
            }
            QPushButton:disabled {
                background-color: #F5F5F5;
                color: #9E9E9E;
                border: 1px solid #E0E0E0;
            }
        """)
        self.edit_field_btn.setEnabled(False)
        self.edit_field_btn.setToolTip("Edit the selected field")
        
        self.remove_field_btn = QPushButton("🗑️ Remove")
        self.remove_field_btn.setMinimumWidth(80)
        self.remove_field_btn.setMinimumHeight(32)
        self.remove_field_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFEBEE;
                border: 1px solid #F44336;
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FFCDD2;
            }
            QPushButton:disabled {
                background-color: #F5F5F5;
                color: #9E9E9E;
                border: 1px solid #E0E0E0;
            }
        """)
        self.remove_field_btn.setEnabled(False)
        self.remove_field_btn.setToolTip("Remove the selected field")
        
        header_layout.addWidget(self.copy_all_btn)
        header_layout.addWidget(self.add_field_btn)
        header_layout.addWidget(self.edit_field_btn)
        header_layout.addWidget(self.remove_field_btn)
        
        layout.addLayout(header_layout)
        
        # Liste simple des champs
        self.fields_tree = QTreeWidget()
        self.fields_tree.setHeaderLabels(["Field"])
        self.fields_tree.setAlternatingRowColors(True)
        self.fields_tree.setRootIsDecorated(False)
        self.fields_tree.setMaximumHeight(150)
        
        layout.addWidget(self.fields_tree)
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure the signal connections"""
        self.fields_tree.itemSelectionChanged.connect(self.on_field_selection_changed)
        self.fields_tree.itemDoubleClicked.connect(self.edit_selected_field)
        
        self.copy_all_btn.clicked.connect(self.copy_all_fields)
        self.add_field_btn.clicked.connect(self.add_field)
        self.edit_field_btn.clicked.connect(self.edit_selected_field)
        self.remove_field_btn.clicked.connect(self.remove_selected_field)
        
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
        """Copy all fields from the selected vector file"""
        # Get the active layer from the parent interface
        current_layer = None
        
        # Search for the parent interface (EnhancedTransformerDialog)
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'shp_tree') and hasattr(parent_widget, 'loaded_shapefiles'):
                # Get the selected vector file from the tree
                current_item = parent_widget.shp_tree.currentItem()
                if current_item:
                    filename = current_item.data(0, Qt.UserRole)
                    if filename in parent_widget.loaded_shapefiles:
                        current_layer = parent_widget.loaded_shapefiles[filename]['layer']
                        break
            parent_widget = parent_widget.parent()
        
        if not current_layer:
            QMessageBox.warning(self, "Warning", "No vector file selected. Please select a vector file first.")
            return
        
        # Check if the layer has fields
        if not current_layer.fields():
            QMessageBox.warning(self, "Warning", "Selected layer has no fields to copy.")
            return
        
        # Ask for confirmation before copying
        existing_fields = len(self.calculated_fields)
        total_fields = len(current_layer.fields())
        
        reply = QMessageBox.question(
            self, "Confirm Copy All",
            f"This will copy {total_fields} field(s) from the selected layer.\n"
            f"Current calculated fields: {existing_fields}\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Copy all fields
        fields_added = 0
        
        # Add geometry field first if layer has geometry
        if current_layer.geometryType() != QgsWkbTypes.NullGeometry:
            geometry_field_name = "geometry"
            if geometry_field_name not in self.calculated_fields:
                # Default geometry expression (preserves original geometry)
                geometry_expression = "$geometry"
                geometry_description = f"Geometry field ({QgsWkbTypes.displayString(current_layer.wkbType())})"
                
                self.calculated_fields[geometry_field_name] = {
                    "expression": geometry_expression,
                    "description": geometry_description,
                    "is_geometry": True  # Mark as geometry field
                }
                
                fields_added += 1
                self.field_added.emit(geometry_field_name, geometry_expression)
        
        # Copy attribute fields
        for field in current_layer.fields():
            field_name = field.name()
            
            # Avoid duplicates
            if field_name in self.calculated_fields:
                continue
            
            # Create a simple expression for the field (field name between quotes)
            expression = f'"{field_name}"'
            
            # Add the field with a description based on its type
            field_type = field.typeName()
            description = f"Copied from original field ({field_type})"
            
            self.calculated_fields[field_name] = {
                "expression": expression,
                "description": description,
                "is_geometry": False  # Mark as attribute field
            }
            
            fields_added += 1
            self.field_added.emit(field_name, expression)
        
        # Refresh the display
        self.refresh_fields_list()
    
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
    
    def on_field_selection_changed(self):
        """Handle the change of selection in the fields list"""
        has_selection = self.fields_tree.currentItem() is not None
        self.edit_field_btn.setEnabled(has_selection)
        self.remove_field_btn.setEnabled(has_selection)
    
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
        
        QgsMessageLog.logMessage(f"DEBUG: Processing {len(self.calculated_fields)} calculated fields", "Transformer", Qgis.Info)
        
        for name, info in self.calculated_fields.items():
            # Check if it's a geometry field (by flag or by name)
            is_geometry_flag = info.get("is_geometry", False)
            is_geometry_name = (name == "geometry")
            
            QgsMessageLog.logMessage(f"DEBUG: Field '{name}': is_geometry={is_geometry_flag}, name_match={is_geometry_name}, expression='{info['expression']}'")
            
            if is_geometry_flag or is_geometry_name:
                geometry_field = info["expression"]
                QgsMessageLog.logMessage(f"DEBUG: Setting geometry_expression to '{geometry_field}'", "Transformer", Qgis.Info)
            else:
                result[name] = info["expression"]
        
        QgsMessageLog.logMessage(f"DEBUG: Final geometry_expression = '{geometry_field}'", "Transformer", Qgis.Info)
        return result, geometry_field
    
    def set_calculated_fields(self, fields_dict, geometry_expression=None):
        """Set calculated fields with optional geometry expression"""
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


class FieldDefinitionDialog(QDialog):
    """Field definition dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Field Definition")
        self.setModal(True)
        self.resize(400, 200)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Formulaire
        form_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter field name...")
        form_layout.addRow("Field Name:", self.name_edit)
        
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional description...")
        form_layout.addRow("Description:", self.description_edit)
        
        layout.addLayout(form_layout)
        
        # Boutons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
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
    
    def accept(self):
        """Validation avant acceptation"""
        name = self.name_edit.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Warning", "Field name is required")
            return
        
        super().accept()


class EnhancedTransformerDialog(QMainWindow):
    """Enhanced main interface with native QGIS features"""
    
    transformation_requested = pyqtSignal(str)
    
    def __init__(self, config_manager, transformer, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.transformer = transformer
        self.loaded_shapefiles = {}
        self.current_table_config = {}
        self.interface_settings = InterfaceSettings()
        
        self.setup_main_window()
        self.setup_central_widget()
        self.setup_dockwidgets()
        self.setup_toolbar()
        self.setup_statusbar()
        self.setup_menubar()
        self.setup_connections()
        
        # Configure the centralized logger after creating the docks
        self.setup_centralized_logger()
        
        # Test the centralized logger
        self.test_centralized_logger()
        
        self.apply_theme()
        self.restore_window_state()
        
        # Configure default tabs (after restore_window_state to avoid interference)
        self.config_dock.raise_()  # Configuration Preview par défaut
        
        self.auto_load_configs()
        
        # Initialize statistics with real values
        QTimer.singleShot(100, self.update_statistics)  # Delay to allow complete initialization
        
    def setup_main_window(self):
        """Configure the main window"""
        self.setWindowTitle("Transformer")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)
        
        # Application icon
        self.setWindowIcon(QIcon(":/images/themes/default/mActionTransform.svg"))
        
        # Autoriser l'ancrage
        self.setDockOptions(
            QMainWindow.AllowNestedDocks |
            QMainWindow.AllowTabbedDocks |
            QMainWindow.AnimatedDocks
        )
    
    def setup_central_widget(self):
        """Configure the central widget"""
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(4, 4, 4, 4)
        
        # Main tabs
        self.main_tabs = QTabWidget()
        self.main_tabs.setTabPosition(QTabWidget.North)
        self.main_tabs.setMovable(True)
        self.main_tabs.setTabsClosable(False)
        
        # Configuration tab
        config_tab = self.create_configuration_tab()
        self.main_tabs.addTab(config_tab, QIcon(":/images/themes/default/mActionConfig.svg"), "Configuration")
        
        # Export tab (integrated) - Using local imports
        QgsMessageLog.logMessage(f" Création onglet Export - EXPORT_CLASSES_AVAILABLE: {EXPORT_CLASSES_AVAILABLE}", "Transformer", Qgis.Info)
        
        if EXPORT_CLASSES_AVAILABLE and ExportWidget is not None:
            try:
                self.export_widget = ExportWidget()
                self.main_tabs.addTab(self.export_widget, QIcon(":/images/themes/default/mActionExport.svg"), "Export")
                QgsMessageLog.logMessage("Export tab created successfully!", "Transformer", Qgis.Success)
            except Exception as e:
                QgsMessageLog.logMessage(f"Error creating ExportWidget: {str(e)}", "Transformer", Qgis.Critical)
                self.export_widget = None
                self._create_fallback_export_tab()
        else:
            QgsMessageLog.logMessage("Export module not available - Creating fallback tab", "Transformer", Qgis.Warning)
            self.export_widget = None
            self._create_fallback_export_tab()
        
        # PostgreSQL Integration tab
        if POSTGRESQL_INTEGRATION_AVAILABLE and PostgreSQLIntegrationWidget is not None:
            try:
                self.postgresql_widget = PostgreSQLIntegrationWidget()
                self.main_tabs.addTab(self.postgresql_widget, QIcon(":/images/themes/default/mActionPostgreSQL.svg"), "PostgreSQL")
                QgsMessageLog.logMessage("PostgreSQL integration loaded successfully", "Transformer", Qgis.Info)
            except Exception as e:
                QgsMessageLog.logMessage(f"PostgreSQL widget creation error: {str(e)}", "Transformer", Qgis.Critical)
                # Fallback widget
                postgresql_fallback = QWidget()
                postgresql_layout = QVBoxLayout()
                postgresql_layout.addWidget(QLabel("PostgreSQL integration error"))
                postgresql_layout.addWidget(QLabel(f"Error creating PostgreSQL widget: {str(e)}"))
                postgresql_layout.addWidget(QLabel("Please check the logs for more details."))
                postgresql_fallback.setLayout(postgresql_layout)
                self.main_tabs.addTab(postgresql_fallback, QIcon(":/images/themes/default/mActionPostgreSQL.svg"), "PostgreSQL")
                self.postgresql_widget = None
        else:
            # Widget de fallback si le module PostgreSQL n'est pas disponible
            postgresql_fallback = QWidget()
            postgresql_layout = QVBoxLayout()
            postgresql_layout.addWidget(QLabel("PostgreSQL integration not available"))
            postgresql_layout.addWidget(QLabel("The PostgreSQL integration module could not be loaded."))
            postgresql_layout.addWidget(QLabel("Check your PostgreSQL configuration and dependencies."))
            if not POSTGRESQL_INTEGRATION_AVAILABLE:
                postgresql_layout.addWidget(QLabel("Missing psycopg2 dependency or import error."))
            postgresql_fallback.setLayout(postgresql_layout)
            self.main_tabs.addTab(postgresql_fallback, QIcon(":/images/themes/default/mActionPostgreSQL.svg"), "PostgreSQL")
            self.postgresql_widget = None
        
        # Finalize the central layout
        central_layout.addWidget(self.main_tabs)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)
    
    def _create_fallback_export_tab(self):
        """Create fallback export tab"""    
        export_fallback = QWidget()
        export_layout = QVBoxLayout()
        export_layout.addWidget(QLabel("Export functionality not available"))
        export_layout.addWidget(QLabel("The advanced export module could not be loaded."))
        export_layout.addWidget(QLabel("You can still use the basic transformation features."))
        export_layout.addWidget(QLabel("\nTroubleshooting:"))
        export_layout.addWidget(QLabel("1. Restart QGIS completely"))
        export_layout.addWidget(QLabel("2. Check QGIS logs for detailed information"))
        export_layout.addWidget(QLabel("3. Contact support if the issue persists"))
        export_fallback.setLayout(export_layout)
        self.main_tabs.addTab(export_fallback, QIcon(":/images/themes/default/mActionExport.svg"), "Export")
    
    def create_configuration_tab(self):
        """Create main configuration tab"""
        tab_widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        
        # Panel central - Expression Builder
        center_panel = self.create_expression_panel()
        center_panel.setMinimumWidth(500)
        
        main_splitter.addWidget(center_panel)
        
        # Proportions
        main_splitter.setStretchFactor(0, 1)
        
        layout.addWidget(main_splitter)
        tab_widget.setLayout(layout)
        
        return tab_widget
    
    def create_expression_panel(self):
        """Create main expression panel"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.NoFrame)
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Table configuration
        config_group = QGroupBox("Table Configuration")
        config_layout = QFormLayout()
        
        self.table_name_edit = QLineEdit()
        self.table_name_edit.setPlaceholderText("Enter output table name...")
        config_layout.addRow("Table Name:", self.table_name_edit)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Smart filter widget
        filter_group = QGroupBox("Smart Filter")
        filter_layout = QVBoxLayout()
        
        self.smart_filter = SmartFilterWidget()
        filter_layout.addWidget(self.smart_filter)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # Advanced expression builder
        expr_group = QGroupBox("Expression Builder")
        expr_layout = QVBoxLayout()
        
        self.advanced_expression = AdvancedExpressionWidget()
        expr_layout.addWidget(self.advanced_expression)
        
        expr_group.setLayout(expr_layout)
        layout.addWidget(expr_group)
        
        # Smart fields widget - Improved visibility
        fields_group = QGroupBox("Field Management (Column Configuration)")
        fields_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #2E7D32;
                border: 2px solid #4CAF50;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        fields_layout = QVBoxLayout()
        
        # Add explanatory label
        info_label = QLabel("Add, edit and manage calculated fields (columns) for your output table:")
        info_label.setStyleSheet("color: #1976D2; font-style: italic; margin-bottom: 5px;")
        fields_layout.addWidget(info_label)
        
        self.smart_fields = FieldWidget(self.advanced_expression)
        fields_layout.addWidget(self.smart_fields)
        
        fields_group.setLayout(fields_layout)
        layout.addWidget(fields_group)
        
        panel.setLayout(layout)
        return panel
    
    def setup_dockwidgets(self):
        """Configure the dock widgets"""
        # Shapefiles panel
        self.shapefiles_dock = QDockWidget("Source Files", self)
        self.shapefiles_dock.setWidget(self.create_shapefiles_widget())
        self.shapefiles_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.shapefiles_dock)
        
        # Panel Configuration
        self.config_dock = QDockWidget("Configuration Preview", self)
        self.config_dock.setWidget(self.create_config_preview_widget())
        self.config_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.config_dock)
        
        # Panel Logs
        self.logs_dock = QDockWidget("Activity Log", self)
        self.logs_dock.setWidget(self.create_logs_widget())
        self.logs_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.logs_dock)
        
        # Panel Help
        self.help_dock = QDockWidget("Quick Help", self)
        self.help_dock.setWidget(self.create_help_widget())
        self.help_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.help_dock)
        
        # Group certain docks
        self.tabifyDockWidget(self.config_dock, self.help_dock)
        
        # Activity Log disabled by default (but not the tab selection which will be done later)
        self.logs_dock.setVisible(False)
    
    def create_shapefiles_widget(self):
        """Create shapefiles management widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Toolbar avec case à cocher
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar avec boutons d'action
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        
        load_action = QAction(QIcon(":/images/themes/default/mActionAdd.svg"), "Load Vector Files", self)
        load_action.triggered.connect(self.load_shapefile)
        toolbar.addAction(load_action)
        
        refresh_action = QAction(QIcon(":/images/themes/default/mActionRefresh.svg"), "Refresh", self)
        refresh_action.triggered.connect(self.refresh_shapefile_list)
        toolbar.addAction(refresh_action)
        
        remove_action = QAction(QIcon(":/images/themes/default/mActionRemove.svg"), "Remove", self)
        remove_action.triggered.connect(self.remove_selected_shapefile)
        toolbar.addAction(remove_action)
        
        toolbar_layout.addWidget(toolbar)
        
        # Case à cocher pour afficher les couches QGIS
        self.show_qgis_layers_checkbox = QCheckBox("Show QGIS Layers")
        self.show_qgis_layers_checkbox.setToolTip("Toggle display of vector files already loaded in QGIS project")
        self.show_qgis_layers_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 10px;
                font-weight: normal;
                color: #1976D2;
                margin-left: 8px;
                spacing: 4px;
            }
            QCheckBox::indicator {
                width: 12px;
                height: 12px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #BDBDBD;
                background-color: #FAFAFA;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #1976D2;
                background-color: #1976D2;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #1565C0;
                border-color: #1565C0;
            }
            QCheckBox::indicator:unchecked:hover {
                border-color: #757575;
                background-color: #F5F5F5;
            }
        """)
        self.show_qgis_layers_checkbox.stateChanged.connect(self.on_show_qgis_layers_changed)
        
        toolbar_layout.addWidget(self.show_qgis_layers_checkbox)
        toolbar_layout.addStretch()  # Pousse la checkbox vers la droite
        
        layout.addLayout(toolbar_layout)
        
        # Shapefiles list with detailed information
        self.shp_tree = QTreeWidget()
        self.shp_tree.setHeaderLabels(["File", "Features", "Type", "CRS"])
        self.shp_tree.setAlternatingRowColors(True)
        self.shp_tree.setRootIsDecorated(False)
        
        # Configure columns
        header = self.shp_tree.header()
        header.resizeSection(0, 180)
        header.resizeSection(1, 80)
        header.resizeSection(2, 80)
        header.setStretchLastSection(True)
        
        layout.addWidget(self.shp_tree)
        
        # Légende pour les couleurs
        legend_layout = QHBoxLayout()
        legend_layout.setContentsMargins(10, 2, 10, 2)
        
        # Légende QGIS layers
        qgis_legend = QLabel("🟦 QGIS Layers")
        qgis_legend.setStyleSheet("""
            QLabel {
                color: #1976D2;
                font-weight: bold;
                font-size: 10px;
                padding: 2px 5px;
                border-radius: 3px;
                background-color: #E3F2FD;
            }
        """)
        
        # Légende External files
        external_legend = QLabel("🟩 External Files")
        external_legend.setStyleSheet("""
            QLabel {
                color: #2E7D32;
                font-weight: bold;
                font-size: 10px;
                padding: 2px 5px;
                border-radius: 3px;
                background-color: #E8F5E8;
            }
        """)
        
        legend_layout.addWidget(qgis_legend)
        legend_layout.addWidget(external_legend)
        legend_layout.addStretch()
        
        layout.addLayout(legend_layout)
        
        # Selection information
        info_group = QGroupBox("Selection Info")
        info_layout = QFormLayout()
        
        self.selection_info_label = QLabel("No selection")
        self.features_count_label = QLabel("0")
        self.geometry_type_label = QLabel("Unknown")
        self.crs_info_label = QLabel("Unknown")
        
        info_layout.addRow("Layer:", self.selection_info_label)
        info_layout.addRow("Features:", self.features_count_label)
        info_layout.addRow("Geometry:", self.geometry_type_label)
        info_layout.addRow("CRS:", self.crs_info_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Reprojection system
        reprojection_group = QGroupBox("Reprojection")
        reprojection_layout = QVBoxLayout()
        
        # Current projection
        current_crs_layout = QHBoxLayout()
        current_crs_layout.addWidget(QLabel("Current CRS:"))
        self.current_crs_label = QLabel("Unknown")
        self.current_crs_label.setStyleSheet("font-weight: bold; color: #2E7D32;")
        current_crs_layout.addWidget(self.current_crs_label)
        current_crs_layout.addStretch()
        reprojection_layout.addLayout(current_crs_layout)
        
        # Target CRS selection
        target_crs_layout = QHBoxLayout()
        target_crs_layout.addWidget(QLabel("Target CRS:"))
        
        # Search field
        self.crs_search_edit = QLineEdit()
        self.crs_search_edit.setPlaceholderText("Search EPSG code or name...")
        self.crs_search_edit.textChanged.connect(self.filter_crs_list)
        target_crs_layout.addWidget(self.crs_search_edit)
        
        # CRS selection button
        self.crs_selection_button = QPushButton("Select CRS")
        self.crs_selection_button.clicked.connect(self.open_crs_dialog)
        target_crs_layout.addWidget(self.crs_selection_button)
        
        reprojection_layout.addLayout(target_crs_layout)
        
        # Target CRS selected display
        self.target_crs_label = QLabel("No target CRS selected")
        self.target_crs_label.setStyleSheet("font-weight: bold; color: #1976D2;")
        reprojection_layout.addWidget(self.target_crs_label)
        
        # List of recently used CRS
        favorites_layout = QHBoxLayout()
        favorites_layout.addWidget(QLabel("Quick Access:"))
        
        # Recent CRS buttons (dynamically created)
        self.quick_crs_buttons = []
        self.recent_crs_list = []  # List of recently used CRS
        
        # Create empty buttons that will be filled dynamically
        for i in range(4):  # Maximum 4 recent buttons
            btn = QPushButton("---")
            btn.setMaximumWidth(80)
            btn.setStyleSheet("QPushButton { font-size: 10px; padding: 2px; }")
            btn.setEnabled(False)
            btn.setVisible(False)
            favorites_layout.addWidget(btn)
            self.quick_crs_buttons.append(btn)
        
        favorites_layout.addStretch()
        reprojection_layout.addLayout(favorites_layout)
        
        # Note: The reprojection is automatically done with the main transformation button
        
        reprojection_group.setLayout(reprojection_layout)
        layout.addWidget(reprojection_group)
        
        # Initialisation
        self.target_crs = None
        self.current_crs = None
        
        # Connection to update the current CRS when a shapefile is selected
        self.shp_tree.currentItemChanged.connect(self.update_current_crs)
        
        widget.setLayout(layout)
        return widget
    
    def create_config_preview_widget(self):
        """Create the configuration preview widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Preview toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        
        validate_action = QAction(QIcon(":/images/themes/default/mIconSuccess.svg"), "Validate", self)
        validate_action.triggered.connect(self.validate_configuration)
        toolbar.addAction(validate_action)
        
        save_action = QAction(QIcon(":/images/themes/default/mActionFileSave.svg"), "Save", self)
        save_action.triggered.connect(self.save_current_table_config)
        toolbar.addAction(save_action)
        
        test_action = QAction(QIcon(":/images/themes/default/mActionPlay.svg"), "Test", self)
        test_action.triggered.connect(self.test_configuration)
        toolbar.addAction(test_action)
        
        initialize_action = QAction(QIcon(":/images/themes/default/mActionNew.svg"), "Initialize", self)
        initialize_action.triggered.connect(self.initialize_configuration)
        toolbar.addAction(initialize_action)
        
        layout.addWidget(toolbar)
        
        # JSON preview
        self.config_preview = QPlainTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setFont(QFont("Consolas", 9))
        self.config_preview.setMaximumHeight(200)
        
        layout.addWidget(QLabel("Configuration Preview:"))
        layout.addWidget(self.config_preview)
        
        # Statistics
        stats_group = QGroupBox("Statistics")
        stats_layout = QFormLayout()
        
        self.total_fields_label = QLabel("0")
        self.total_tables_label = QLabel("0")
        self.filter_status_label = QLabel("Disabled")
        
        stats_layout.addRow("Fields:", self.total_fields_label)
        stats_layout.addRow("Tables:", self.total_tables_label)
        stats_layout.addRow("Filter:", self.filter_status_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Transformation actions
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout()
        
        self.transform_selected_btn = QPushButton("Transform Selected")
        self.transform_selected_btn.setIcon(QIcon(":/images/themes/default/mActionStart.svg"))
        self.transform_selected_btn.clicked.connect(self.transform_selected_shapefile)
        
        self.transform_all_btn = QPushButton("Transform All")
        self.transform_all_btn.setIcon(QIcon(":/images/themes/default/mActionBatch.svg"))
        self.transform_all_btn.clicked.connect(self.transform_all_shapefiles)
        
        actions_layout.addWidget(self.transform_selected_btn)
        actions_layout.addWidget(self.transform_all_btn)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)
        
        widget.setLayout(layout)
        return widget
    
    def create_logs_widget(self):
        """Create the logs widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Logs toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        
        clear_action = QAction(QIcon(":/images/themes/default/mActionDeleteSelected.svg"), "Clear", self)
        clear_action.triggered.connect(self.clear_logs)
        toolbar.addAction(clear_action)
        
        export_logs_action = QAction(QIcon(":/images/themes/default/mActionExport.svg"), "Export", self)
        export_logs_action.triggered.connect(self.export_logs)
        toolbar.addAction(export_logs_action)
        
        layout.addWidget(toolbar)
        
        # Zone de logs
        self.logs_text = QPlainTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setFont(QFont("Consolas", 8))
        self.logs_text.setMaximumHeight(150)
        
        layout.addWidget(self.logs_text)
        
        widget.setLayout(layout)
        return widget
    
    def create_help_widget(self):
        """Create the help widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Help tabs
        help_tabs = QTabWidget()
        help_tabs.setTabPosition(QTabWidget.South)
        
        # Expression help
        expr_help = QTextEdit()
        expr_help.setReadOnly(True)
        expr_help.setMaximumHeight(200)
        expr_help.setHtml("""
        <h3>Expression Help</h3>
        <p><b>Geometry Functions:</b></p>
        <ul>
        <li><code>area($geometry)</code> - Feature area</li>
        <li><code>perimeter($geometry)</code> - Feature perimeter</li>
        <li><code>centroid($geometry)</code> - Feature centroid</li>
        </ul>
        
        <p><b>Math Functions:</b></p>
        <ul>
        <li><code>round(value, decimals)</code> - Round number</li>
        <li><code>abs(value)</code> - Absolute value</li>
        <li><code>sqrt(value)</code> - Square root</li>
        </ul>
        
        <p><b>Text Functions:</b></p>
        <ul>
        <li><code>upper(text)</code> - Uppercase</li>
        <li><code>concat(text1, text2)</code> - Concatenate</li>
        </ul>
        """)
        help_tabs.addTab(expr_help, "Expressions")
        
        # Filter help
        filter_help = QTextEdit()
        filter_help.setReadOnly(True)
        filter_help.setMaximumHeight(200)
        filter_help.setHtml("""
        <h3>Filter Help</h3>
        <p><b>Common Filters:</b></p>
        <ul>
        <li><code>area($geometry) > 1000</code> - Area greater than 1000</li>
        <li><code>"TYPE" = 'Building'</code> - Type equals Building</li>
        <li><code>is_valid($geometry)</code> - Valid geometries only</li>
        </ul>
        
        <p><b>Operators:</b></p>
        <ul>
        <li><code>=, !=, <, >, <=, >=</code> - Comparison</li>
        <li><code>AND, OR, NOT</code> - Logical</li>
        <li><code>LIKE, ILIKE</code> - Pattern matching</li>
        </ul>
        """)
        help_tabs.addTab(filter_help, "Filters")
        
        layout.addWidget(help_tabs)
        
        widget.setLayout(layout)
        return widget
    
    def setup_toolbar(self):
        """Configure the toolbar"""
        toolbar = self.addToolBar("Main")
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setIconSize(QSize(24, 24))
        
        # Main actions
        load_action = QAction(QIcon(":/images/themes/default/mActionAdd.svg"), "Load\nVector Files", self)
        load_action.setToolTip("Load vector files for transformation (Shapefile, GeoJSON, GeoPackage, KML, etc.)")
        load_action.triggered.connect(self.load_shapefile)
        toolbar.addAction(load_action)
        
        toolbar.addSeparator()
        
        validate_action = QAction(QIcon(":/images/themes/default/mIconSuccess.svg"), "Validate\nConfig", self)
        validate_action.setToolTip("Validate current configuration")
        validate_action.triggered.connect(self.validate_configuration)
        toolbar.addAction(validate_action)
        
        save_action = QAction(QIcon(":/images/themes/default/mActionFileSave.svg"), "Save\nConfig", self)
        save_action.setToolTip("Save current configuration")
        save_action.triggered.connect(self.save_current_table_config)
        toolbar.addAction(save_action)
        
        toolbar.addSeparator()
        
        transform_action = QAction(QIcon(":/images/themes/default/mActionStart.svg"), "Transform\nSelected", self)
        transform_action.setToolTip("Transform selected vector file")
        transform_action.triggered.connect(self.transform_selected_shapefile)
        toolbar.addAction(transform_action)
        
        batch_action = QAction(QIcon(":/images/themes/default/mActionBatch.svg"), "Transform\nAll", self)
        batch_action.setToolTip("Transform all loaded vector files")
        batch_action.triggered.connect(self.transform_all_shapefiles)
        toolbar.addAction(batch_action)
        
        toolbar.addSeparator()
        
        # Switch vers export
        export_action = QAction(QIcon(":/images/themes/default/mActionExport.svg"), "Export\nMode", self)
        export_action.setToolTip("Switch to export mode")
        export_action.triggered.connect(lambda: self.main_tabs.setCurrentIndex(1))
        toolbar.addAction(export_action)
    
    def setup_statusbar(self):
        """Configure the status bar"""
        self.status_bar = self.statusBar()
        
        # Main status label
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Statistics
        self.stats_label = QLabel("0 tables | 0 vector files")
        self.status_bar.addPermanentWidget(self.stats_label)
        
        # Current mode
        self.mode_label = QLabel("Configuration Mode")
        self.mode_label.setStyleSheet("font-weight: bold; color: #007bff;")
        self.status_bar.addPermanentWidget(self.mode_label)
    
    def setup_menubar(self):
        """Configure the menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction(QIcon(":/images/themes/default/mActionNew.svg"), "&New Configuration", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_configuration)
        file_menu.addAction(new_action)
        
        open_action = QAction(QIcon(":/images/themes/default/mActionOpen.svg"), "&Open Configuration", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_configuration)
        file_menu.addAction(open_action)
        
        save_action = QAction(QIcon(":/images/themes/default/mActionFileSave.svg"), "&Save Configuration", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_configuration)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        import_action = QAction("&Import Configuration", self)
        import_action.triggered.connect(self.import_configuration)
        file_menu.addAction(import_action)
        
        export_action = QAction("&Export Configuration", self)
        export_action.triggered.connect(self.export_configuration)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        undo_action = QAction(QIcon(":/images/themes/default/mActionUndo.svg"), "&Undo", self)
        undo_action.setShortcut(QKeySequence.Undo)
        edit_menu.addAction(undo_action)
        
        redo_action = QAction(QIcon(":/images/themes/default/mActionRedo.svg"), "&Redo", self)
        redo_action.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(redo_action)
        
        edit_menu.addSeparator()
        
        preferences_action = QAction("&Preferences", self)
        preferences_action.triggered.connect(self.show_preferences)
        edit_menu.addAction(preferences_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        # Add docks to the View menu
        view_menu.addAction(self.shapefiles_dock.toggleViewAction())
        view_menu.addAction(self.config_dock.toggleViewAction())
        view_menu.addAction(self.logs_dock.toggleViewAction())
        view_menu.addAction(self.help_dock.toggleViewAction())
        
        view_menu.addSeparator()
        
        # Themes menu
        themes_menu = view_menu.addMenu("&Themes")
        theme_group = QActionGroup(self)
        
        for theme in InterfaceTheme:
            theme_action = QAction(theme.value.replace("_", " ").title(), self)
            theme_action.setCheckable(True)
            theme_action.setChecked(theme == self.interface_settings.theme)
            theme_action.triggered.connect(lambda checked, t=theme: self.change_theme(t))
            theme_group.addAction(theme_action)
            themes_menu.addAction(theme_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        validate_action = QAction("&Validate All Configurations", self)
        validate_action.triggered.connect(self.validate_all_configurations)
        tools_menu.addAction(validate_action)
        
        cleanup_action = QAction("&Cleanup Missing Sources", self)
        cleanup_action.triggered.connect(self.cleanup_missing_sources)
        tools_menu.addAction(cleanup_action)
        
        tools_menu.addSeparator()
        
        expression_tester_action = QAction("Expression &Tester", self)
        expression_tester_action.triggered.connect(self.open_expression_tester)
        tools_menu.addAction(expression_tester_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        help_action = QAction("&Help Contents", self)
        help_action.setShortcut(QKeySequence.HelpContents)
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_connections(self):
        """Configure les connexions de signaux"""
        # Shapefile selection
        self.shp_tree.itemSelectionChanged.connect(self.on_shapefile_selection_changed)
        
        # Configuration changes
        self.table_name_edit.textChanged.connect(self.update_configuration_preview)
        self.smart_filter.filter_applied.connect(self.on_filter_changed)
        self.smart_fields.field_added.connect(self.on_field_added)
        self.smart_fields.field_removed.connect(self.on_field_removed)
        self.smart_fields.field_modified.connect(self.on_field_modified)
        
        # Tab change
        self.main_tabs.currentChanged.connect(self.on_tab_changed)
        
        # Connections with export
        self.transformation_requested.connect(self.on_transformation_completed)
    
    def setup_centralized_logger(self):
        """Configure le logger centralisé avec le widget Activity Log"""
        try:
            # Check if the logs dock and logs text exist
            if hasattr(self, 'logs_dock') and hasattr(self, 'logs_text'):
                # Connect the logger to the Activity Log widget
                plugin_logger.set_activity_log_widget(self.logs_text)
                log_info("Centralized logger configured successfully")
                log_info(f"Logger connected to Activity Log panel: {type(self.logs_text).__name__}")
            else:
                log_warning("Activity Log widget not found - logger will only send to QGIS Message Log")
                
        except Exception as e:
            error_msg = f"Error setting up centralized logger: {str(e)}"
            # Fallback to QgsMessageLog if the centralized logger fails
            QgsMessageLog.logMessage(error_msg, "Transformer", Qgis.Critical)
    
    def test_centralized_logger(self):
        """Test the centralized logger with all log levels"""
        log_info("Testing centralized logger - Info message")
        log_warning("Testing centralized logger - Warning message")
        log_error("Testing centralized logger - Error message")
        log_success("Testing centralized logger - Success message")
        log_info("Centralized logger test completed")
    
    def apply_theme(self):
        """Apply the selected theme"""
        try:
            # Load styles from external CSS file
            css_file = os.path.join(os.path.dirname(__file__), 'styles.css')
            
            if os.path.exists(css_file):
                with open(css_file, 'r', encoding='utf-8') as f:
                    css_content = f.read()
                self.setStyleSheet(css_content)
                log_info("Theme applied from CSS file")
            else:
                # Fallback to simple integrated styles
                self.apply_fallback_theme()
                
        except Exception as e:
            log_warning(f"Error applying theme: {str(e)}")
            self.apply_fallback_theme()

    def apply_fallback_theme(self):
        """Apply a simple fallback theme"""
        try:
            if self.interface_settings.theme == InterfaceTheme.QGIS_NATIVE:
                # Simple and safe QGIS native style
                style = """
                QMainWindow {
                    background-color: #f0f0f0;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #c0c0c0;
                    border-radius: 4px;
                    margin-top: 6px;
                    padding-top: 6px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 8px;
                    padding: 0 4px 0 4px;
                }
                QPushButton {
                    background-color: #e1e1e1;
                    border: 1px solid #adadad;
                    border-radius: 3px;
                    padding: 4px 8px;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background-color: #d4d4d4;
                }
                QTreeWidget, QListWidget, QTableWidget {
                    border: 1px solid #c0c0c0;
                    background-color: white;
                    alternate-background-color: #f5f5f5;
                }
                QLineEdit {
                    border: 1px solid #c0c0c0;
                    border-radius: 2px;
                    padding: 2px;
                    background-color: white;
                }
                """
                self.setStyleSheet(style)
            
            elif self.interface_settings.theme == InterfaceTheme.PROFESSIONAL:
                # style
                style = """
                QWidget {
                    font-family: 'Segoe UI', Arial, sans-serif;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #007bff;
                    border-radius: 6px;
                    margin-top: 8px;
                    padding-top: 8px;
                    color: #007bff;
                }
                QPushButton {
                    background-color: #007bff;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: 500;
                    min-height: 24px;
                }
                QPushButton:hover {
                    background-color: #0056b3;
                }
                """
                self.setStyleSheet(style)
            
            else:
                # Default minimal style
                self.setStyleSheet("")
                
            QgsMessageLog.logMessage("Fallback theme applied", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error applying fallback theme: {str(e)}", "Transformer", Qgis.Warning)
            # In last resort, no style
            self.setStyleSheet("")

        
    def restore_window_state(self):
        """Restore the window state"""
        try:
            settings = QSettings()
            geometry = settings.value("Transformer/geometry")
            if geometry:
                self.restoreGeometry(geometry)
            
            window_state = settings.value("Transformer/windowState")
            if window_state:
                self.restoreState(window_state)
                
            # Restaurer les paramètres d'interface
            theme_value = settings.value("Transformer/theme", InterfaceTheme.QGIS_NATIVE.value)
            try:
                self.interface_settings.theme = InterfaceTheme(theme_value)
            except:
                self.interface_settings.theme = InterfaceTheme.QGIS_NATIVE
                
        except Exception as e:
            self.log_message(f"Error restoring window state: {str(e)}", "Warning")
    
    def save_window_state(self):
        """Save the window state"""
        try:
            settings = QSettings()
            settings.setValue("Transformer/geometry", self.saveGeometry())
            settings.setValue("Transformer/windowState", self.saveState())
            settings.setValue("Transformer/theme", self.interface_settings.theme.value)
        except Exception as e:
            self.log_message(f"Error saving window state: {str(e)}", "Warning")
    
    def auto_load_configs(self):
        """Auto load configurations at startup"""
        try:
            all_configs = self.config_manager.get_all_tables()
            loaded_count = 0
            
            for table_name, config in all_configs.items():
                source_file = config.get('source_file')
                if source_file and os.path.exists(source_file):
                    self.add_shapefile(source_file)
                    loaded_count += 1
            
            self.refresh_shapefile_list()
            
            if loaded_count > 0:
                self.log_message(f"Auto-loaded {loaded_count} vector files with existing configurations", "Info")
                
        except Exception as e:
            self.log_message(f"Error auto-loading configurations: {str(e)}", "Warning")
    
    # === VECTOR FILES MANAGEMENT METHODS ===
    
    def _build_vector_file_filter(self) -> str:
        """Build comprehensive file filter for all QGIS-supported vector formats"""
        # Core vector formats supported by QGIS
        filters = [
            "All Vector Files (*.shp *.geojson *.json *.gpkg *.sqlite *.gml *.kml *.kmz *.csv *.txt *.tab *.mif *.mid *.dxf *.dgn *.gdb *.gpx)",
            "Shapefile (*.shp)",
            "GeoJSON (*.geojson *.json)", 
            "GeoPackage (*.gpkg)",
            "SQLite/SpatiaLite (*.sqlite *.db)",
            "Geography Markup Language (*.gml)",
            "Keyhole Markup Language (*.kml *.kmz)",
            "Comma Separated Values (*.csv *.txt)",
            "MapInfo TAB (*.tab)",
            "MapInfo MIF/MID (*.mif *.mid)",
            "AutoCAD DXF (*.dxf)",
            "MicroStation DGN (*.dgn)",
            "ESRI File Geodatabase (*.gdb)",
            "GPS Exchange Format (*.gpx)",
            "ESRI Personal Geodatabase (*.mdb)",
            "Open Street Map (*.osm *.pbf)",
            "PostGIS Database Layers",
            "All Files (*.*)"
        ]
        return ";;".join(filters)
    
    def _is_supported_vector_format(self, file_path: str) -> bool:
        """Check if file format is supported by QGIS vector layer provider"""
        try:
            # Use QGIS to test if the file can be opened as a vector layer
            test_layer = QgsVectorLayer(file_path, "test", "ogr")
            is_valid = test_layer.isValid()
            
            # Additional check for common extensions
            file_ext = os.path.splitext(file_path)[1].lower()
            supported_extensions = {
                '.shp', '.geojson', '.json', '.gpkg', '.sqlite', '.db',
                '.gml', '.kml', '.kmz', '.csv', '.txt', '.tab', 
                '.mif', '.mid', '.dxf', '.dgn', '.gdb', '.gpx', 
                '.mdb', '.osm', '.pbf'
            }
            
            # If QGIS validation fails, check if it's a known extension
            if not is_valid and file_ext in supported_extensions:
                self.log_message(f"File {os.path.basename(file_path)} has supported extension but failed QGIS validation", "Warning")
            
            return is_valid
            
        except Exception as e:
            self.log_message(f"Error validating format for {os.path.basename(file_path)}: {str(e)}", "Warning")
            return False
    
    def _detect_vector_format(self, file_path: str) -> str:
        """Detect vector file format and return human-readable name"""
        try:
            layer = QgsVectorLayer(file_path, "temp", "ogr")
            if layer.isValid():
                provider = layer.dataProvider()
                storage_type = provider.storageType()
                
                # Map storage types to user-friendly names
                format_mapping = {
                    'ESRI Shapefile': 'Shapefile',
                    'GeoJSON': 'GeoJSON',
                    'GPKG': 'GeoPackage', 
                    'SQLite/SpatiaLite': 'SQLite',
                    'GML': 'Geography Markup Language',
                    'KML': 'Keyhole Markup Language',
                    'CSV': 'Comma Separated Values',
                    'MapInfo File': 'MapInfo TAB',
                    'DXF': 'AutoCAD DXF'
                }
                
                return format_mapping.get(storage_type, storage_type)
        except:
            pass
        
        # Fallback to file extension
        ext = os.path.splitext(file_path)[1].lower()
        ext_mapping = {
            '.shp': 'Shapefile',
            '.geojson': 'GeoJSON', 
            '.json': 'GeoJSON',
            '.gpkg': 'GeoPackage',
            '.sqlite': 'SQLite',
            '.gml': 'GML',
            '.kml': 'KML',
            '.csv': 'CSV',
            '.tab': 'MapInfo TAB',
            '.dxf': 'AutoCAD DXF'
        }
        return ext_mapping.get(ext, 'Unknown')
    
    def load_shapefile(self):
        """Load one or multiple vector files (supports all QGIS-compatible formats)"""
        # Get supported vector formats from QGIS
        file_filter = self._build_vector_file_filter()
        
        files, _ = QFileDialog.getOpenFileNames(
            self, "Load Vector Files", "", file_filter
        )
        
        if files:
            loaded_count = 0
            failed_count = 0
            
            for file_path in files:
                # Validate file format before loading
                if self._is_supported_vector_format(file_path):
                    if self.add_vector_file(file_path):
                        loaded_count += 1
                    else:
                        failed_count += 1
                else:
                    self.log_message(f"Unsupported format: {os.path.basename(file_path)}", "Warning")
                    failed_count += 1
            
            self.refresh_shapefile_list()
            
            # Enhanced status message
            if loaded_count > 0:
                self.log_message(f"✅ Successfully loaded {loaded_count} vector file(s)", "Info")
            if failed_count > 0:
                self.log_message(f"⚠️ Failed to load {failed_count} file(s)", "Warning")
    
    def add_vector_file(self, file_path: str) -> bool:
        """Add a vector file (supports all QGIS-compatible formats)"""
        try:
            # Detect format first
            file_format = self._detect_vector_format(file_path)
            
            # Create layer with appropriate provider
            layer = QgsVectorLayer(file_path, os.path.basename(file_path), "ogr")
            
            if layer.isValid():
                filename = os.path.basename(file_path)
                
                # Avoid duplicates
                if filename in self.loaded_shapefiles:
                    self.log_message(f"Vector file {filename} already loaded", "Warning")
                    return False
                
                # Enhanced metadata collection
                provider = layer.dataProvider()
                encoding = provider.encoding()
                
                # Get field information
                fields = layer.fields()
                field_count = len(fields)
                field_types = [field.typeName() for field in fields]
                
                # Store comprehensive information
                self.loaded_shapefiles[filename] = {
                    'layer': layer,
                    'path': file_path,
                    'format': file_format,
                    'provider': 'ogr',
                    'encoding': encoding,
                    'feature_count': layer.featureCount(),
                    'field_count': field_count,
                    'field_types': field_types,
                    'geometry_type': QgsWkbTypes.displayString(layer.wkbType()),
                    'geometry_dimension': QgsWkbTypes.coordDimensions(layer.wkbType()),
                    'crs': layer.crs().authid(),
                    'crs_description': layer.crs().description(),
                    'extent': layer.extent(),
                    'storage_type': provider.storageType(),
                    'capabilities': provider.capabilities()
                }
                
                # Enhanced logging with format information
                geometry_info = f"{layer.featureCount()} features, {field_count} fields"
                crs_info = layer.crs().authid() if layer.crs().isValid() else "No CRS"
                
                self.log_message(
                    f"✅ Added {file_format}: {filename} ({geometry_info}, {crs_info})", 
                    "Info"
                )
                
                # Log additional details for complex formats
                if file_format not in ['Shapefile', 'GeoJSON']:
                    self.log_message(
                        f"📋 Format details: {provider.storageType()}, encoding: {encoding}",
                        "Info"
                    )
                
                return True
            else:
                # Enhanced error reporting
                error_msg = "Unknown error"
                if hasattr(layer, 'error') and layer.error().message():
                    error_msg = layer.error().message()
                
                self.log_message(
                    f"❌ Invalid vector file: {os.path.basename(file_path)} ({file_format}) - {error_msg}", 
                    "Error"
                )
                return False
                
        except Exception as e:
            self.log_message(
                f"💥 Error loading vector file {os.path.basename(file_path)}: {str(e)}", 
                "Error"
            )
            return False
    
    def add_shapefile(self, file_path: str) -> bool:
        """Legacy method - redirects to add_vector_file for backward compatibility"""
        return self.add_vector_file(file_path)
    
    def refresh_shapefile_list(self):
        """Refresh the shapefile list"""
        self.shp_tree.clear()
        
        for filename, data in self.loaded_shapefiles.items():
            item = QTreeWidgetItem(self.shp_tree)
            item.setText(0, filename)
            item.setText(1, str(data['feature_count']))
            item.setText(2, data.get('geometry_type', 'Unknown'))
            item.setText(3, data.get('crs', 'Unknown'))
            item.setData(0, Qt.UserRole, filename)
            
            # Vérifier si c'est une couche QGIS
            is_qgis_layer = data.get('is_qgis_layer', False)
            
            # Icône selon le type de géométrie et la source
            geom_type = data.get('geometry_type', '').lower()
            if is_qgis_layer:
                # Style spécial pour les couches QGIS
                item.setForeground(0, QColor("#1976D2"))  # Bleu pour les couches QGIS
                item.setFont(0, QFont("Arial", 9, QFont.Bold))
                # Préfixe avec icône QGIS
                if 'point' in geom_type:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconPointLayer.svg"))
                elif 'line' in geom_type:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconLineLayer.svg"))
                elif 'polygon' in geom_type:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconPolygonLayer.svg"))
                else:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconTableLayer.svg"))
            else:
                # Style normal pour les fichiers externes
                item.setForeground(0, QColor("#2E7D32"))  # Vert pour les fichiers externes
                if 'point' in geom_type:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconPointLayer.svg"))
                elif 'line' in geom_type:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconLineLayer.svg"))
                elif 'polygon' in geom_type:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconPolygonLayer.svg"))
                else:
                    item.setIcon(0, QIcon(":/images/themes/default/mIconTableLayer.svg"))
            
            # Enhanced tooltip with format information
            source_type = "QGIS Layer" if is_qgis_layer else "External File"
            file_format = data.get('format', 'Unknown')
            field_count = data.get('field_count', 0)
            encoding = data.get('encoding', 'Unknown')
            storage_type = data.get('storage_type', 'Unknown')
            
            tooltip = f"""📁 Source: {source_type}
🏷️ Format: {file_format}
📄 Name: {filename}
📊 Features: {data['feature_count']:,}
📝 Fields: {field_count}
🔷 Geometry: {data.get('geometry_type', 'Unknown')}
🗺️ CRS: {data.get('crs', 'Unknown')}
💾 Encoding: {encoding}
📂 Storage: {storage_type}
📍 Path: {data['path']}"""
            item.setToolTip(0, tooltip)
        
        # Redimensionner les colonnes
        for i in range(self.shp_tree.columnCount()):
            self.shp_tree.resizeColumnToContents(i)
        
        # Mettre à jour les statistiques
        self.update_statistics()
    
    def remove_selected_shapefile(self):
        """Remove the selected shapefile"""
        current_item = self.shp_tree.currentItem()
        if not current_item:
            QMessageBox.information(self, "Information", "Please select a shapefile to remove")
            return
        
        filename = current_item.data(0, Qt.UserRole)
        
        # Vérifier si c'est une couche QGIS
        data = self.loaded_shapefiles.get(filename, {})
        is_qgis_layer = data.get('is_qgis_layer', False)
        
        if is_qgis_layer:
            message = f"Remove QGIS layer '{filename}' from the source files list?\n\nNote: This will only remove it from the Transformer list, not from the QGIS project."
            title = "Remove QGIS Layer"
        else:
            message = f"Remove external file '{filename}' from the list?\n\nThis will not delete the file from disk."
            title = "Remove External File"
        
        reply = QMessageBox.question(
            self, title, message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if filename in self.loaded_shapefiles:
                del self.loaded_shapefiles[filename]
                self.refresh_shapefile_list()
                
                if is_qgis_layer:
                    self.log_message(f"Removed QGIS layer from list: {filename}", "Info")
                else:
                    self.log_message(f"Removed external file from list: {filename}", "Info")
    
    def on_shapefile_selection_changed(self):
        """Handle shapefile selection change"""
        current = self.shp_tree.currentItem()
        if current:
            filename = current.data(0, Qt.UserRole)
            data = self.loaded_shapefiles.get(filename, {})
            
            # Update selection information
            self.selection_info_label.setText(filename)
            self.features_count_label.setText(f"{data.get('feature_count', 0):,}")
            self.geometry_type_label.setText(data.get('geometry_type', 'Unknown'))
            self.crs_info_label.setText(data.get('crs', 'Unknown'))
            
            # Update the current CRS automatically
            self.update_current_crs(current)
            
            # Configure widgets with the new layer
            layer = data.get('layer')
            if layer:
                self.smart_filter.set_layer(layer)
                self.advanced_expression.set_layer(layer)
            
            # Auto load existing configuration
            self.auto_load_table_config_for_shapefile(filename)
            
        else:
            self.selection_info_label.setText("No selection")
            self.features_count_label.setText("0")
            self.geometry_type_label.setText("Unknown")
            self.crs_info_label.setText("Unknown")
            # Reset the current CRS
            self.current_crs_label.setText("Unknown")
    
    def auto_load_table_config_for_shapefile(self, filename: str):
        """Auto load table configuration for a shapefile"""
        try:
            table_names = self.config_manager.get_tables_for_source(filename)
            if table_names:
                # Auto load the first configuration found
                first_table = table_names[0]
                config = self.config_manager.get_table_config(first_table)
                
                if config:
                    self.table_name_edit.setText(first_table)
                    
                    # Auto load calculated fields and geometry expression
                    calculated_fields = config.get('calculated_fields', {})
                    geometry_expression = config.get('geometry_expression')
                    self.smart_fields.set_calculated_fields(calculated_fields, geometry_expression)
                    
                    # Auto load filter configuration
                    filter_config = config.get('filter', {})
                    self.smart_filter.set_filter_config(filter_config)
                    
                    # Auto load target CRS if defined
                    target_crs_str = config.get('target_crs')
                    if target_crs_str:
                        try:
                            from qgis.core import QgsCoordinateReferenceSystem
                            target_crs = QgsCoordinateReferenceSystem(target_crs_str)
                            if target_crs.isValid():
                                # Update the interface with set_target_crs
                                crs_description = target_crs.description()
                                self.set_target_crs(target_crs_str, crs_description)
                                self.log_message(f"Target CRS loaded: {target_crs_str} - {crs_description}", "Info")
                            else:
                                self.log_message(f"Invalid CRS in configuration: {target_crs_str}", "Warning")
                                self.target_crs = None
                        except Exception as e:
                            self.log_message(f"Error loading CRS {target_crs_str}: {str(e)}", "Warning")
                            self.target_crs = None
                    else:
                        # Reset the target CRS if none is defined
                        self.target_crs = None
                        # Clean up the CRS interface
                        if hasattr(self, 'target_crs_label'):
                            self.target_crs_label.setText("Not set")
                        if hasattr(self, 'crs_search_edit'):
                            self.crs_search_edit.setText("")
                        if hasattr(self, 'apply_reprojection_button'):
                            self.apply_reprojection_button.setEnabled(False)
                    
                    self.log_message(f"Loaded existing configuration for {first_table}", "Info")
                else:
                    self.reset_configuration()
            else:
                # No existing configuration, propose a default name
                base_name = os.path.splitext(filename)[0]
                self.table_name_edit.setText(f"{base_name}_transformed")
                self.reset_configuration()
                
            self.update_configuration_preview()
            
        except Exception as e:
            self.log_message(f"Error loading configuration for {filename}: {str(e)}", "Warning")
            self.reset_configuration()
    
    def reset_configuration(self):
        """Reset the configuration"""
        self.smart_fields.clear_all_fields()
        self.smart_filter.set_filter_config({"enabled": False, "expression": ""})
        # Reset the CRS target
        self.target_crs = None
        self.update_configuration_preview()
    
    def on_show_qgis_layers_changed(self, state):
        """Handle the toggle of QGIS layers display"""
        try:
            if state == Qt.Checked:
                # Ajouter les couches QGIS à la liste
                self.load_qgis_layers_to_list()
                self.log_message("QGIS layers added to source files list", "Info")
            else:
                # Retirer les couches QGIS de la liste et garder seulement les fichiers externes
                self.remove_qgis_layers_from_list()
                self.log_message("QGIS layers removed from source files list", "Info")
                
            self.refresh_shapefile_list()
            
        except Exception as e:
            self.log_message(f"Error toggling QGIS layers display: {str(e)}", "Warning")
    
    def load_qgis_layers_to_list(self):
        """Load vector layers from QGIS project to the source files list (supports all formats)"""
        try:
            project = QgsProject.instance()
            loaded_qgis_count = 0
            
            for layer_id, layer in project.mapLayers().items():
                # Only add vector layers
                if isinstance(layer, QgsVectorLayer) and layer.isValid():
                    # Use enhanced format detection
                    provider_type = layer.dataProvider().name().lower()
                    source_path = layer.source()
                    
                    # Support all OGR-compatible vector formats
                    if provider_type in ['ogr', 'gdal']:
                        # Detect format using our enhanced method
                        file_format = self._detect_vector_format(source_path)
                        
                        layer_name = layer.name()
                        
                        # Avoid duplicates if layer is already in the list
                        if layer_name not in self.loaded_shapefiles:
                            # Enhanced metadata collection
                            provider = layer.dataProvider()
                            encoding = provider.encoding()
                            fields = layer.fields()
                            field_count = len(fields)
                            field_types = [field.typeName() for field in fields]
                            
                            # Store comprehensive information (same as add_vector_file)
                            self.loaded_shapefiles[layer_name] = {
                                'layer': layer,
                                'path': source_path,
                                'format': file_format,
                                'provider': provider_type,
                                'encoding': encoding,
                                'feature_count': layer.featureCount(),
                                'field_count': field_count,
                                'field_types': field_types,
                                'geometry_type': QgsWkbTypes.displayString(layer.wkbType()),
                                'geometry_dimension': QgsWkbTypes.coordDimensions(layer.wkbType()),
                                'crs': layer.crs().authid(),
                                'crs_description': layer.crs().description(),
                                'extent': layer.extent(),
                                'storage_type': provider.storageType(),
                                'capabilities': provider.capabilities(),
                                'is_qgis_layer': True  # Special flag to identify QGIS layers
                            }
                            
                            loaded_qgis_count += 1
                            
                            # Log each loaded layer with format info
                            self.log_message(
                                f"📥 Added from QGIS: {file_format} - {layer_name} ({layer.featureCount()} features)",
                                "Info"
                            )
            
            # Summary message
            if loaded_qgis_count > 0:
                self.log_message(
                    f"✅ Loaded {loaded_qgis_count} vector layer(s) from QGIS project", 
                    "Info"
                )
            else:
                self.log_message("ℹ️ No compatible vector layers found in QGIS project", "Info")
                            
        except Exception as e:
            self.log_message(f"Error loading QGIS layers: {str(e)}", "Warning")
    
    def remove_qgis_layers_from_list(self):
        """Remove QGIS layers from the source files list, keeping only external files"""
        try:
            # Create a new dictionary without QGIS layers
            external_shapefiles = {}
            for filename, data in self.loaded_shapefiles.items():
                if not data.get('is_qgis_layer', False):
                    external_shapefiles[filename] = data
            
            removed_count = len(self.loaded_shapefiles) - len(external_shapefiles)
            self.loaded_shapefiles = external_shapefiles
            
            if removed_count > 0:
                self.log_message(f"Removed {removed_count} QGIS layers from list", "Info")
                
        except Exception as e:
            self.log_message(f"Error removing QGIS layers: {str(e)}", "Warning")
    
    # === CONFIGURATION MANAGEMENT METHODS ===
    
    def update_configuration_preview(self):
        """Update the configuration preview"""
        try:
            table_name = self.table_name_edit.text().strip()
            
            current_item = self.shp_tree.currentItem()
            source_file = ""
            if current_item:
                source_file = current_item.data(0, Qt.UserRole)
            
            # Get calculated fields separated from geometry
            QgsMessageLog.logMessage(f"DEBUG: About to call get_calculated_fields_with_geometry_info(), smart_fields exists: {hasattr(self, 'smart_fields')}", "Transformer", Qgis.Info)
            if hasattr(self, 'smart_fields') and self.smart_fields:
                calculated_fields, geometry_expression = self.smart_fields.get_calculated_fields_with_geometry_info()
                QgsMessageLog.logMessage(f"DEBUG: After calling method, geometry_expression = '{geometry_expression}'", "Transformer", Qgis.Info)
            else:
                QgsMessageLog.logMessage(f"ERROR: smart_fields not available!", "Transformer", Qgis.Critical)
                calculated_fields, geometry_expression = {}, None
            filter_config = self.smart_filter.get_filter_config()
            
            # add the CRS target if defined
            target_crs_str = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs_str = self.target_crs.authid()
            
            preview_config = {
                "table_name": table_name,
                "source_file": source_file,
                "calculated_fields": calculated_fields,
                "filter": filter_config,
                "target_crs": target_crs_str,
                "geometry_expression": geometry_expression,
                "created": datetime.now().isoformat(),
                "plugin_version": "1.0.0"
            }
            
            json_text = json.dumps(preview_config, indent=2, ensure_ascii=False)
            self.config_preview.setPlainText(json_text)
            
            # Update statistics
            self.total_fields_label.setText(str(len(calculated_fields)))
            
            filter_status = "Enabled" if filter_config.get("enabled", False) else "Disabled"
            if filter_config.get("enabled", False) and filter_config.get("expression", ""):
                filter_status += f" ({len(filter_config['expression'])} chars)"
            self.filter_status_label.setText(filter_status)
            
        except Exception as e:
            self.config_preview.setPlainText(f"Configuration preview error: {str(e)}")
            self.log_message(f"Error updating configuration preview: {str(e)}", "Warning")
    
    def on_filter_changed(self, expression, enabled):
        """Handle filter change"""
        self.update_configuration_preview()
        if enabled and expression:
            self.log_message(f"Filter updated: {expression[:50]}{'...' if len(expression) > 50 else ''}", "Info")
    
    def on_field_added(self, name, expression):
        """Handle field addition"""
        self.update_configuration_preview()
        self.log_message(f"Field added: {name} = {expression[:30]}{'...' if len(expression) > 30 else ''}", "Info")
    
    def on_field_removed(self, name):
        """Handle field removal"""
        self.update_configuration_preview()
        self.log_message(f"Field removed: {name}", "Info")
    
    def on_field_modified(self, old_name, new_name, expression):
        """Handle field modification"""
        self.update_configuration_preview()
        self.log_message(f"Field modified: {old_name} -> {new_name}", "Info")
    
    def validate_configuration(self):
        """Validate the current configuration"""
        try:
            table_name = self.table_name_edit.text().strip()
            if not table_name:
                QMessageBox.warning(self, "Validation Error", "Table name is required")
                return False
            
            current_item = self.shp_tree.currentItem()
            if not current_item:
                QMessageBox.warning(self, "Validation Error", "Please select a shapefile")
                return False
            
            filename = current_item.data(0, Qt.UserRole)
            layer = self.loaded_shapefiles[filename]['layer']
            
            calculated_fields = self.smart_fields.get_calculated_fields()
            if not calculated_fields:
                QMessageBox.warning(self, "Validation Error", "At least one calculated field is required")
                return False
            
            # Validate expressions
            errors = []
            successes = []
            
            # Validate filter
            filter_config = self.smart_filter.get_filter_config()
            if filter_config.get("enabled", False):
                filter_expr = filter_config.get("expression", "")
                if filter_expr:
                    is_valid, message, filtered_count = self.transformer.test_filter_expression(filter_expr, layer)
                    if is_valid:
                        total_count = layer.featureCount()
                        successes.append(f"FILTER: {filtered_count}/{total_count} features match")
                    else:
                        errors.append(f"FILTER ERROR: {message}")
            
            # Validate calculated fields
            for field_name, expression in calculated_fields.items():
                is_valid, message = self.transformer.validate_expression(expression, layer)
                if is_valid:
                    successes.append(f"FIELD '{field_name}': Valid")
                else:
                    errors.append(f"FIELD '{field_name}': {message}")
            
            # Only display results if there are errors
            if errors:
                result_text = f"Configuration Validation Errors for '{table_name}'\n"
                result_text += "=" * 60 + "\n\n"
                result_text += "ERRORS DETECTED:\n"
                for error in errors:
                    result_text += f"  {error}\n"
                result_text += "\nPlease fix the errors before proceeding."
                
                QMessageBox.warning(self, "Validation Errors", result_text)
                self.log_message(f"Configuration validation failed: {len(errors)} errors", "Warning")
                return False
            else:
                # No errors - validation passed silently
                self.log_message(f"Configuration validated successfully: {table_name} ({len(successes)} fields validated)", "Info")
                return True
                
        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            QMessageBox.critical(self, "Validation Error", error_msg)
            self.log_message(error_msg, "Error")
            return False
    
    def initialize_configuration(self):
        """Initialize the configuration with a confirmation window"""
        try:
            # Confirmation window
            reply = QMessageBox.question(
                self, 
                "Initialize Configuration", 
                "This will reset all current configurations:\n\n"
                "• Clear all calculated fields\n"
                "• Reset table name\n"
                "• Clear expression builder\n"
                "• Disable filters\n\n"
                "Are you sure you want to proceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Reset the table name
                self.table_name_edit.clear()
                
                # Reset calculated fields
                if hasattr(self, 'smart_fields'):
                    self.smart_fields.clear_all_fields()
                
                # Reset filter
                if hasattr(self, 'smart_filter'):
                    self.smart_filter.set_filter_config({"enabled": False, "expression": ""})
                
                # Reset expression builder
                if hasattr(self, 'advanced_expression'):
                    self.advanced_expression.clear_expression()
                
                # Update configuration preview
                self.update_configuration_preview()
                
                # Confirmation messages
                QMessageBox.information(
                    self, 
                    "Configuration Initialized", 
                    "Configuration has been successfully reset.\n\n"
                    "You can now start configuring your transformation from scratch."
                )
                
                self.log_message("Configuration initialized successfully", "Info")
                
        except Exception as e:
            error_msg = f"Error initializing configuration: {str(e)}"
            QMessageBox.critical(self, "Initialization Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def save_current_table_config(self, skip_validation=False):
        """Save the current table configuration with duplicate check"""
        try:
            if not skip_validation and not self.validate_configuration():
                return
            
            table_name = self.table_name_edit.text().strip()
            current_item = self.shp_tree.currentItem()
            filename = current_item.data(0, Qt.UserRole)
            
            # Get calculated fields separated from geometry expression
            calculated_fields, geometry_expression = self.smart_fields.get_calculated_fields_with_geometry_info()
            filter_config = self.smart_filter.get_filter_config()
            
            QgsMessageLog.logMessage(f"DEBUG: About to save config with geometry_expression = '{geometry_expression}'", "Transformer", Qgis.Info)
            
            # Get target CRS if defined
            target_crs = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs = self.target_crs.authid()
            
            # Check if a configuration already exists for this table
            if self.config_manager.has_table_config(table_name):
                existing_config = self.config_manager.get_table_config(table_name)
                existing_source = existing_config.get("source_file", "")
                
                # Dialogue de confirmation pour remplacer la configuration existante
                reply = QMessageBox.question(
                    self,
                    "Configuration Already Exists",
                    f"A configuration already exists for table '{table_name}'\n"
                    f"(Source: {os.path.basename(existing_source)})\n\n"
                    f"Do you want to replace the existing configuration?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                
                if reply == QMessageBox.No:
                    self.log_message(f"Save cancelled - configuration for '{table_name}' already exists", "Info")
                    return
                
                # Replace existing configuration
                success = self.config_manager.add_table_config(table_name, filename, calculated_fields, filter_config, target_crs, geometry_expression, force_replace=True)
            else:
                # Add new configuration
                success = self.config_manager.add_table_config(table_name, filename, calculated_fields, filter_config, target_crs, geometry_expression)
            
            if success and self.config_manager.save_config():
                action = "updated" if self.config_manager.has_table_config(table_name) else "saved"
                QMessageBox.information(self, "Success", f"Configuration {action} for table '{table_name}'")
                self.log_message(f"Configuration {action}: {table_name}", "Info")
                self.update_statistics()
            else:
                QMessageBox.critical(self, "Error", "Failed to save configuration")
                
        except Exception as e:
            error_msg = f"Error saving configuration: {str(e)}"
            QMessageBox.critical(self, "Save Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def test_configuration(self):
        """Test the current configuration"""
        try:
            self.status_label.setText("Testing configuration...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Mode indéterminé
            
            if self.validate_configuration():
                # Test with a sample of data
                current_item = self.shp_tree.currentItem()
                filename = current_item.data(0, Qt.UserRole)
                layer = self.loaded_shapefiles[filename]['layer']
                
                calculated_fields = self.smart_fields.get_calculated_fields()
                filter_config = self.smart_filter.get_filter_config()
                
                # Créer une couche de test temporaire avec un échantillon
                test_result = self.create_test_layer(layer, calculated_fields, filter_config)
                
                if test_result['success']:
                    result_msg = f"""Test Configuration Results

Table: {self.table_name_edit.text()}
Source: {filename}

✅ Test completed successfully!

Results:
• Source features: {test_result['source_count']:,}
• Filtered features: {test_result['filtered_count']:,}
• Calculated fields: {len(calculated_fields)}
• Test features processed: {test_result['processed_count']:,}

The configuration is working correctly and ready for full transformation."""
                    
                    QMessageBox.information(self, "Test Results", result_msg)
                    self.log_message("Configuration test passed", "Info")
                else:
                    QMessageBox.warning(self, "Test Failed", f"Test failed: {test_result['error']}")
                    self.log_message(f"Configuration test failed: {test_result['error']}", "Warning")
            
        except Exception as e:
            error_msg = f"Test error: {str(e)}"
            QMessageBox.critical(self, "Test Error", error_msg)
            self.log_message(error_msg, "Error")
        finally:
            self.progress_bar.setVisible(False)
            self.status_label.setText("Ready")
    
    def create_test_layer(self, layer, calculated_fields, filter_config, max_features=100):
        """Create a test layer with a sample of data"""
        try:
            source_count = layer.featureCount()
            
            # Apply filter if enabled
            if filter_config.get("enabled", False):
                filter_expr = filter_config.get("expression", "")
                if filter_expr:
                    request = QgsFeatureRequest()
                    request.setFilterExpression(filter_expr)
                    filtered_features = list(layer.getFeatures(request))
                    filtered_count = len(filtered_features)
                else:
                    filtered_features = list(layer.getFeatures())
                    filtered_count = len(filtered_features)
            else:
                filtered_features = list(layer.getFeatures())
                filtered_count = len(filtered_features)
            
            # Limiter à un échantillon
            test_features = filtered_features[:max_features]
            processed_count = len(test_features)
            
            # Tester les expressions sur l'échantillon
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
            context.setFields(layer.fields())
            
            for feature in test_features:
                context.setFeature(feature)
                
                for field_name, expression_text in calculated_fields.items():
                    expression = QgsExpression(expression_text)
                    result = expression.evaluate(context)
                    
                    if expression.hasEvalError():
                        raise Exception(f"Expression error in field '{field_name}': {expression.evalErrorString()}")
            
            return {
                'success': True,
                'source_count': source_count,
                'filtered_count': filtered_count,
                'processed_count': processed_count
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'source_count': 0,
                'filtered_count': 0,
                'processed_count': 0
            }
    
    # === TRANSFORMATION METHODS ===
    
    def transform_selected_shapefile(self):
        """Transform the selected shapefile"""
        try:
            current_item = self.shp_tree.currentItem()
            if not current_item:
                QMessageBox.warning(self, "Warning", "Please select a shapefile to transform")
                return
            
            if not self.validate_configuration():
                return
            
            filename = current_item.data(0, Qt.UserRole)
            shapefile_info = self.loaded_shapefiles[filename]
            
            self.status_label.setText("Transforming...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            
            # Save the configuration before transformation
            self.save_current_table_config(skip_validation=True)
            
            # Get the target CRS if selected
            target_crs = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs = self.target_crs
                self.log_message(f"Reprojection to {target_crs.authid()} will be applied", "Info")
            
            # Detect source type and use appropriate transformation method
            if shapefile_info.get('is_qgis_layer', False):
                # Transform QGIS layer directly from layer object
                layer_obj = shapefile_info['layer']
                self.log_message(f"🔄 Transforming QGIS layer: {filename}", "Info")
                
                layers = self.transformer.transform_qgis_layer_to_memory_layers(
                    layer_obj, 
                    filename,
                    target_crs
                )
            else:
                # Transform external shapefile from file path
                shp_path = shapefile_info['path']
                self.log_message(f"🔄 Transforming external shapefile: {filename}", "Info")
                layers = self.transformer.transform_shapefile_to_memory_layers(shp_path, target_crs)
            
            if layers:
                self.transformer.add_layers_to_project(layers, "Transformed Layers")
                self.status_label.setText(f"{len(layers)} layer(s) created")
                
                # Emit the transformation completed signal - use consistent identifier
                source_identifier = shapefile_info['path'] if not shapefile_info.get('is_qgis_layer', False) else filename
                self.transformation_requested.emit(source_identifier)
                
                # Log transformation completion without dialog popup
                self.log_message(f"Transformation completed successfully: {len(layers)} layers created from {filename}", "Success")
                
                # Add a brief status message without interrupting the workflow
                self.status_label.setText(f"Transformation completed: {len(layers)} layer(s) created")
                
                # Déclencher automatiquement la vérification des mappings PostgreSQL
                self._trigger_postgresql_auto_mapping([layer.name() for layer in layers])
            else:
                QMessageBox.warning(self, "Warning", "No layers were created during transformation")
                self.log_message("Transformation completed but no layers were created", "Warning")
                
        except Exception as e:
            error_msg = f"Transformation failed: {str(e)}"
            QMessageBox.critical(self, "Transformation Error", error_msg)
            self.log_message(error_msg, "Error")
        finally:
            self.progress_bar.setVisible(False)
            self.status_label.setText("Ready")
    
    def transform_all_shapefiles(self):
        """Transform all loaded shapefiles"""
        try:
            if not self.loaded_shapefiles:
                QMessageBox.warning(self, "Warning", "No shapefiles loaded")
                return
            
            reply = QMessageBox.question(
                self, "Confirm Batch Transformation",
                f"Transform all {len(self.loaded_shapefiles)} loaded shapefiles?\n\n"
                "This will use their existing configurations or default settings.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            self.status_label.setText("Batch transformation in progress...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, len(self.loaded_shapefiles))
            
            total_layers = 0
            processed = 0
            errors = []
            
            for filename, data in self.loaded_shapefiles.items():
                try:
                    self.progress_bar.setValue(processed)
                    QApplication.processEvents()
                    
                    layers = self.transformer.transform_shapefile_to_memory_layers(data['path'])
                    if layers:
                        self.transformer.add_layers_to_project(layers, "Transformed Layers")
                        total_layers += len(layers)
                        self.log_message(f"Transformed {filename}: {len(layers)} layers", "Info")
                    else:
                        self.log_message(f"No layers created for {filename}", "Warning")
                        
                except Exception as e:
                    error_msg = f"Error transforming {filename}: {str(e)}"
                    errors.append(error_msg)
                    self.log_message(error_msg, "Error")
                
                processed += 1
            
            # Emit the transformation completed signal
            if total_layers > 0:
                self.transformation_requested.emit("batch_transform")
            
            # Display the results
            result_msg = f"""Batch Transformation Results

Processed: {processed}/{len(self.loaded_shapefiles)} shapefiles
Total layers created: {total_layers}
Errors: {len(errors)}

"""
            
            if errors:
                result_msg += "Errors encountered:\n"
                for error in errors[:5]:  # Limiter à 5 erreurs
                    result_msg += f"• {error}\n"
                if len(errors) > 5:
                    result_msg += f"• ... and {len(errors) - 5} more errors"
            
            if total_layers > 0:
                result_msg += "\nWould you like to switch to Export mode?"
                reply = QMessageBox.question(self, "Batch Transformation Complete", result_msg)
                if reply == QMessageBox.Yes:
                    self.main_tabs.setCurrentIndex(1)
            else:
                QMessageBox.information(self, "Batch Transformation Complete", result_msg)
                
        except Exception as e:
            error_msg = f"Batch transformation error: {str(e)}"
            QMessageBox.critical(self, "Batch Transformation Error", error_msg)
            self.log_message(error_msg, "Error")
        finally:
            self.progress_bar.setVisible(False)
            self.status_label.setText("Ready")
    
    # === INTERFACE METHODS ===
    
    def on_tab_changed(self, index):
        """Handle tab change"""
        if index == 0:
            self.mode_label.setText("Configuration Mode")
            self.mode_label.setStyleSheet("font-weight: bold; color: #007bff;")
        elif index == 1:
            self.mode_label.setText("Export Mode")
            self.mode_label.setStyleSheet("font-weight: bold; color: #28a745;")
            # Refresh layers in the export tab if available - Import local to avoid circular import
            try:
                from .main_plugin import EXPORT_MODULE_AVAILABLE
                if EXPORT_MODULE_AVAILABLE and hasattr(self, 'export_widget') and self.export_widget:
                    QTimer.singleShot(100, self.export_widget.refresh_layers)
            except (ImportError, AttributeError):
                pass  # Module d'export non disponible, ignorer
    
    def on_transformation_completed(self, shapefile_path):
        """Handle transformation completion"""
        # Refresh layers in the export tab if available - Import local to avoid circular import
        try:
            from .main_plugin import EXPORT_MODULE_AVAILABLE
            if EXPORT_MODULE_AVAILABLE and hasattr(self, 'export_widget') and self.export_widget:
                QTimer.singleShot(500, self.export_widget.refresh_layers)
        except (ImportError, AttributeError):
            pass  # Module d'export non disponible, ignorer
    
    def update_statistics(self):
        """Update global statistics with real data"""
        try:
            # Count real vector layers in the QGIS project
            project = QgsProject.instance()
            vector_layers = [layer for layer in project.mapLayers().values() 
                           if isinstance(layer, QgsVectorLayer) and layer.isValid()]
            qgis_layer_count = len(vector_layers)
            
            # Count the vector files loaded in the interface
            vector_file_count = len(self.loaded_shapefiles)
            
            # Count the PostgreSQL tables available if the PostgreSQL tab is active
            postgresql_table_count = 0
            try:
                # Check if there is an active PostgreSQL connection
                if hasattr(self, 'postgresql_integration_widget'):
                    pg_widget = getattr(self.postgresql_integration_widget, 'mapping_widget', None)
                    if pg_widget and hasattr(pg_widget, 'available_tables'):
                        # Count all tables in all schemas
                        for schema_tables in pg_widget.available_tables.values():
                            postgresql_table_count += len(schema_tables)
                        
                        # Display with PostgreSQL tables
                        if postgresql_table_count > 0:
                            self.stats_label.setText(
                                f"{qgis_layer_count} QGIS layers | {postgresql_table_count} PG tables | {vector_file_count} vector files"
                            )
                            return
            except (AttributeError, Exception):
                # Ignore PostgreSQL errors
                pass
            
            # Display standard without PostgreSQL
            self.stats_label.setText(f"{qgis_layer_count} QGIS layers | {vector_file_count} vector files")
            
            # Update the Statistics panel with real data
            self._update_statistics_panel(qgis_layer_count, postgresql_table_count)
                
        except Exception as e:
            self.log_message(f"Error updating statistics: {str(e)}", "Warning")
            # Fallback vers des valeurs par défaut
            self.stats_label.setText("Statistics unavailable")
            # Fallback pour le panneau Statistics aussi
            self._update_statistics_panel(0, 0)
    
    def _update_statistics_panel(self, qgis_layer_count, postgresql_table_count):
        """Update the Statistics panel with real data"""
        try:
            # Count the fields of the selected layer
            total_fields = 0
            current_item = self.shp_tree.currentItem()
            if current_item:
                filename = current_item.data(0, Qt.UserRole)
                if filename and filename in self.loaded_shapefiles:
                    # Load the shapefile temporarily to count the fields
                    shapefile_path = self.loaded_shapefiles[filename]['path']
                    try:
                        temp_layer = QgsVectorLayer(shapefile_path, "temp", "ogr")
                        if temp_layer.isValid():
                            total_fields = len(temp_layer.fields())
                            # Add the calculated fields configured
                            if hasattr(self, 'smart_fields'):
                                calculated_fields = self.smart_fields.get_calculated_fields()
                                total_fields += len(calculated_fields)
                    except Exception:
                        total_fields = 0
            
            # Update the Fields label with the real number of fields
            if hasattr(self, 'total_fields_label'):
                self.total_fields_label.setText(str(total_fields))
            
            # Update the Tables label with the real data
            if hasattr(self, 'total_tables_label'):
                if postgresql_table_count > 0:
                    # Prioritize PostgreSQL tables if available
                    self.total_tables_label.setText(str(postgresql_table_count))
                else:
                    # Use the number of QGIS layers as fallback
                    self.total_tables_label.setText(str(qgis_layer_count))
            
            # Update the filter status
            if hasattr(self, 'filter_status_label') and hasattr(self, 'smart_filter'):
                try:
                    filter_config = self.smart_filter.get_filter_config()
                    if filter_config and filter_config.get('enabled', False):
                        filter_expr = filter_config.get('expression', '').strip()
                        if filter_expr:
                            self.filter_status_label.setText("Enabled")
                        else:
                            self.filter_status_label.setText("Disabled")
                    else:
                        self.filter_status_label.setText("Disabled")
                except Exception:
                    self.filter_status_label.setText("Disabled")
                    
        except Exception as e:
            # In case of error, use default values
            if hasattr(self, 'total_fields_label'):
                self.total_fields_label.setText("0")
            if hasattr(self, 'total_tables_label'):
                self.total_tables_label.setText(str(qgis_layer_count) if qgis_layer_count > 0 else "0")
            if hasattr(self, 'filter_status_label'):
                self.filter_status_label.setText("Disabled")
    
    def log_message(self, message, level="Info"):
        """Add a message to the log"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            level_prefix = {
                "Info": "ℹ",
                "Warning": "⚠",
                "Error": "✗",
                "Success": "✓"
            }.get(level, "•")
            
            log_entry = f"[{timestamp}] {level_prefix} {message}"
            
            # Add to the logs widget
            self.logs_text.appendPlainText(log_entry)
            
            # Log also to QGIS
            qgis_level = {
                "Info": Qgis.Info,
                "Warning": Qgis.Warning,
                "Error": Qgis.Critical,
                "Success": Qgis.Info
            }.get(level, Qgis.Info)
            
            QgsMessageLog.logMessage(message, "Transformer", qgis_level)
            
        except Exception:
            pass  # Avoid cascading errors
    
    def clear_logs(self):
        """Clear the logs"""
        self.logs_text.clear()
        self.log_message("Logs cleared", "Info")
    
    def _trigger_postgresql_auto_mapping(self, layer_names=None):
        """Trigger automatic check of mappings for transformed layers
        
        Args:
            layer_names (list, optional): List of layer names to check.
                                         If None, checks all layers.
        """
        try:
            # Vérifier si le widget PostgreSQL est disponible et initialisé
            if not hasattr(self, 'postgresql_widget') or not self.postgresql_widget:
                QgsMessageLog.logMessage(
                    "PostgreSQL widget not available - skipping auto-mapping check", 
                    "Transformer", Qgis.Info
                )
                return
            
            # Déclencher la vérification automatique des mappings
            QgsMessageLog.logMessage(
                f"Triggering PostgreSQL auto-mapping check for layers: {layer_names}", 
                "Transformer", Qgis.Info
            )
            
            # Utiliser un léger délai pour permettre aux couches d'être complètement chargées
            QTimer.singleShot(1000, lambda: self._perform_auto_mapping_check(layer_names))
            
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error triggering PostgreSQL auto-mapping: {str(e)}", 
                "Transformer", Qgis.Warning
            )
    
    def _perform_auto_mapping_check(self, layer_names=None):
        """Effectue la vérification automatique des mappings (appelée avec délai)
        
        Args:
            layer_names (list, optional): Liste des noms de couches à vérifier.
        """
        try:
            # Appeler la méthode de vérification automatique du widget PostgreSQL
            mappings_loaded = self.postgresql_widget.trigger_auto_mapping_check(layer_names)
            
            if mappings_loaded > 0:
                QgsMessageLog.logMessage(
                    f"Auto-mapping successful: {mappings_loaded} mapping(s) loaded automatically", 
                    "Transformer", Qgis.Success
                )
                
                # Optionnellement, switcher vers l'onglet PostgreSQL si des mappings ont été chargés
                # Rechercher l'index de l'onglet PostgreSQL
                for i in range(self.main_tabs.count()):
                    if self.main_tabs.tabText(i) == "PostgreSQL":
                        # Afficher une notification subtile au lieu de switcher automatiquement
                        self.log_message(
                            f"🔗 {mappings_loaded} mapping(s) PostgreSQL prêt(s) pour export (onglet PostgreSQL)", 
                            "Success"
                        )
                        break
            else:
                QgsMessageLog.logMessage(
                    "Auto-mapping check completed: no matching mappings found", 
                    "Transformer", Qgis.Info
                )
                
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error during auto-mapping check: {str(e)}", 
                "Transformer", Qgis.Warning
            )
    
    def export_logs(self):
        """Export the logs"""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Logs", 
                f"shape_transformer_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                "Text Files (*.txt);;All Files (*.*)"
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.logs_text.toPlainText())
                
                QMessageBox.information(self, "Success", f"Logs exported to:\n{filename}")
                self.log_message(f"Logs exported to {filename}", "Info")
                
        except Exception as e:
            error_msg = f"Error exporting logs: {str(e)}"
            QMessageBox.critical(self, "Export Error", error_msg)
            self.log_message(error_msg, "Error")
    
    # === MENU METHODS ===
    
    def new_configuration(self):
        """Create a new configuration"""
        reply = QMessageBox.question(
            self, "New Configuration",
            "Create a new configuration?\n\nThis will clear the current configuration.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.table_name_edit.clear()
            self.reset_configuration()
            self.log_message("New configuration created", "Info")
    
    def open_configuration(self):
        """Open a configuration"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Configuration", "",
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if filename:
            if self.config_manager.import_config(filename):
                self.auto_load_configs()
                QMessageBox.information(self, "Success", f"Configuration imported from:\n{filename}")
                self.log_message(f"Configuration imported from {filename}", "Info")
            else:
                QMessageBox.critical(self, "Error", "Failed to import configuration")
    
    def save_configuration(self):
        """Save the global configuration"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", 
            f"shape_transformer_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if filename:
            if self.config_manager.export_config(filename):
                QMessageBox.information(self, "Success", f"Configuration exported to:\n{filename}")
                self.log_message(f"Configuration exported to {filename}", "Info")
            else:
                QMessageBox.critical(self, "Error", "Failed to export configuration")
    
    def import_configuration(self):
        """Import a configuration"""
        self.open_configuration()
    
    def export_configuration(self):
        """Export the configuration"""
        self.save_configuration()
    
    def show_preferences(self):
        """Show preferences"""
        dialog = PreferencesDialog(self.interface_settings, self)
        if dialog.exec_() == QDialog.Accepted:
            self.interface_settings = dialog.get_settings()
            self.apply_theme()
            self.log_message("Preferences updated", "Info")
    
    def change_theme(self, theme):
        """Change the interface theme"""
        self.interface_settings.theme = theme
        self.apply_theme()
        self.log_message(f"Theme changed to {theme.value}", "Info")
    
    def validate_all_configurations(self):
        """Validate all configurations"""
        try:
            issues = self.config_manager.validate_config()
            
            if not issues:
                QMessageBox.information(self, "Validation Results", "All configurations are valid!")
            else:
                issues_text = "\n".join([f"• {issue}" for issue in issues])
                QMessageBox.warning(self, "Validation Results", f"Issues found:\n\n{issues_text}")
            
            self.log_message(f"Configuration validation: {len(issues)} issues found", "Info" if not issues else "Warning")
            
        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            QMessageBox.critical(self, "Validation Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def cleanup_missing_sources(self):
        """Cleanup missing sources"""
        try:
            removed_count = self.config_manager.cleanup_missing_sources()
            
            if removed_count > 0:
                QMessageBox.information(
                    self, "Cleanup Complete", 
                    f"Removed {removed_count} configuration(s) with missing source files."
                )
                self.auto_load_configs()
            else:
                QMessageBox.information(self, "Cleanup Complete", "No missing sources found.")
            
            self.log_message(f"Cleanup completed: {removed_count} configurations removed", "Info")
            
        except Exception as e:
            error_msg = f"Cleanup error: {str(e)}"
            QMessageBox.critical(self, "Cleanup Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def open_expression_tester(self):
        """Open the expression tester"""
        current_item = self.shp_tree.currentItem()
        if current_item:
            filename = current_item.data(0, Qt.UserRole)
            layer = self.loaded_shapefiles[filename]['layer']
        else:
            layer = None
        
        dialog = ExpressionTesterDialog(layer, self)
        dialog.exec_()
    
    def show_help(self):
        """Show help"""
        help_text = """
Transformer - Bash Edition

This plugin allows you to transform shapefiles using QGIS calculated fields with advanced filtering capabilities.

Key Features:
• Filter system with templates and suggestions
• Expression builder with syntax highlighting
• Field management with quick templates
• Real-time validation and testing
• Enhanced export capabilities

Getting Started:
1. Load shapefiles using the toolbar or File menu
2. Select a shapefile from the list
3. Configure filters and calculated fields
4. Validate and test your configuration
5. Transform to create new layers
6. Export results in various formats

For detailed documentation, visit:
https://github.com/yadda07/Transformer
        """
        
        QMessageBox.information(self, "Help - Transformer", help_text)
    
    def show_about(self):
        """Show about information"""
        about_text = """
<h2>Transformer</h2>
<h3>Bash Edition v1.0.0</h3>

<p><b>Developed by NGEDEV TEAM</b></p>
<p>QGIS plugin for shapefile transformation with calculated fields and filtering.</p>

<p>Built with <i>love</i> using QGIS API 3.10+, PyQt5/6, Python 3.6+, and the native QGIS Expression Engine.</p>

<p><b>Contact:</b> yadda@ext.nge.fr</p>
<p><b>License:</b> GPL v2+</p>
        """
        
        QMessageBox.about(self, "About Transformer", about_text)
    
    # === CLOSE METHODS ===
    
    def closeEvent(self, event):
        """Handle the window close event"""
        try:
            # Save the window state
            self.save_window_state()
            
            # Check for unsaved changes
            if self.has_unsaved_changes():
                reply = QMessageBox.question(
                    self, "Unsaved Changes",
                    "You have unsaved configuration changes.\n\nSave before closing?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save
                )
                
                if reply == QMessageBox.Save:
                    self.save_current_table_config()
                elif reply == QMessageBox.Cancel:
                    event.ignore()
                    return
            
            self.log_message("Application closing", "Info")
            event.accept()
            
        except Exception as e:
            self.log_message(f"Error during application close: {str(e)}", "Error")
            event.accept()
    
    def has_unsaved_changes(self) -> bool:
        """Check for unsaved changes"""
        try:
            table_name = self.table_name_edit.text().strip()
            if not table_name:
                return False
            
            current_config = self.config_manager.get_table_config(table_name)
            if not current_config:
                # New configuration not saved
                calculated_fields = self.smart_fields.get_calculated_fields()
                return bool(calculated_fields)
            
            # Compare with the current configuration
            current_fields = current_config.get('calculated_fields', {})
            new_fields = self.smart_fields.get_calculated_fields()
            
            return current_fields != new_fields
            
        except Exception as e:
            self.log_message(f"Error checking unsaved changes: {str(e)}", "Error")
            return False
    
    def filter_crs_list(self, text):
        """Filter the CRS list based on search text"""
        if not text or len(text) < 2:
            return
        
        # Search in the list of available CRS
        # This method can be used to filter a dropdown list
        # ou pour afficher des suggestions dans un tooltip
        try:
            # Recherche par code EPSG
            if text.isdigit():
                crs_code = f"EPSG:{text}"
                crs = QgsCoordinateReferenceSystem(crs_code)
                if crs.isValid():
                    self.crs_search_edit.setToolTip(f"Found: {crs.description()} ({crs.authid()})")
                    return
            
            # Search by name or description
            # Use a simple approach for now
            common_crs = [
                ("4326", "WGS 84"),
                ("3857", "WGS 84 / Pseudo-Mercator"),
                ("2154", "RGF93 / Lambert-93"),
                ("4171", "RGF93"),
                ("32631", "WGS 84 / UTM zone 31N"),
                ("32632", "WGS 84 / UTM zone 32N"),
                ("3395", "WGS 84 / World Mercator"),
            ]
            
            matches = []
            text_lower = text.lower()
            for code, name in common_crs:
                if text_lower in name.lower() or text_lower in code:
                    matches.append(f"EPSG:{code} - {name}")
            
            if matches:
                tooltip = "Suggestions:\n" + "\n".join(matches[:5])  # Limite à 5 suggestions
                self.crs_search_edit.setToolTip(tooltip)
            else:
                self.crs_search_edit.setToolTip("No matches found")
                
        except Exception as e:
            self.log_message(f"Error filtering CRS list: {str(e)}")
    
    def open_crs_dialog(self):
        """Open the QGIS native CRS selection dialog"""
        try:
            from qgis.gui import QgsProjectionSelectionDialog
            dialog = QgsProjectionSelectionDialog(self)
            dialog.setWindowTitle("Select Target CRS")
            
            if dialog.exec_() == QDialog.Accepted:
                crs = dialog.crs()
                if crs.isValid():
                    self.set_target_crs(crs.authid(), crs.description())
                    
        except Exception as e:
            self.log_message(f"Error opening CRS dialog: {str(e)}", "Error")
    
    def set_target_crs(self, crs_code, crs_name):
        """Set the target CRS"""
        try:
            self.target_crs = QgsCoordinateReferenceSystem(crs_code)
            if self.target_crs.isValid():
                self.target_crs_label.setText(f"{crs_name} ({crs_code})")
                self.crs_search_edit.setText(crs_code)
                
                # Add to the recent CRS list
                self.add_to_recent_crs(crs_code, crs_name)
                
                self.apply_reprojection_button.setEnabled(True)
                self.log_message(f"Target CRS set to: {crs_code}", "Info")
            else:
                self.log_message(f"Invalid CRS: {crs_code}", "Error")
        except Exception as e:
            self.log_message(f"Error setting target CRS: {str(e)}", "Error")
    
    def add_to_recent_crs(self, crs_code, crs_name):
        """Add a CRS to the recent list"""
        # Create a tuple (code, name) for the CRS
        new_crs = (crs_code, crs_name)
        
        # Remove the CRS if it already exists in the list
        if new_crs in self.recent_crs_list:
            self.recent_crs_list.remove(new_crs)
        
        # Add the CRS to the beginning of the list
        self.recent_crs_list.insert(0, new_crs)
        
        # Limit to 4 recent CRS maximum
        if len(self.recent_crs_list) > 4:
            self.recent_crs_list = self.recent_crs_list[:4]
        
        # Update the buttons
        self.update_recent_crs_buttons()
    
    def update_recent_crs_buttons(self):
        """Update the Quick Access buttons with recent CRS"""
        for i, btn in enumerate(self.quick_crs_buttons):
            if i < len(self.recent_crs_list):
                crs_code, crs_name = self.recent_crs_list[i]
                # Shorten the name if too long
                display_name = crs_name if len(crs_name) <= 10 else crs_name[:10] + "..."
                btn.setText(display_name)
                btn.setEnabled(True)
                btn.setVisible(True)
                btn.setToolTip(f"{crs_name} ({crs_code})")
                
                # Remove previous connections to avoid duplicates
                btn.clicked.disconnect()
                btn.clicked.connect(lambda checked, c=crs_code, n=crs_name: self.set_target_crs(c, n))
            else:
                btn.setText("---")
                btn.setEnabled(False)
                btn.setVisible(False)
                btn.setToolTip("")
    
    def apply_reprojection(self):
        """Apply reprojection to the selected shapefile"""
        try:
            if not hasattr(self, 'target_crs') or not self.target_crs.isValid():
                QMessageBox.warning(self, "Warning", "Please select a valid target CRS first.")
                return
            
            # Récupérer le shapefile sélectionné
            current_item = self.shp_tree.currentItem()
            if not current_item:
                QMessageBox.warning(self, "Warning", "Please select a shapefile first.")
                return
            
            shapefile_path = current_item.data(0, Qt.UserRole)
            if not shapefile_path:
                QMessageBox.warning(self, "Warning", "No shapefile path found.")
                return
            
            # Créer le nom du fichier de sortie
            input_path = Path(shapefile_path)
            output_path = input_path.parent / f"{input_path.stem}_reprojected.shp"
            
            # Effectuer la reprojection
            layer = QgsVectorLayer(shapefile_path, "temp", "ogr")
            if not layer.isValid():
                QMessageBox.critical(self, "Error", "Failed to load shapefile.")
                return
            
            # Options de sauvegarde
            save_options = QgsVectorFileWriter.SaveVectorOptions()
            save_options.driverName = "ESRI Shapefile"
            save_options.fileEncoding = "UTF-8"
            
            # Transformer CRS
            transform_context = QgsCoordinateTransformContext()
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, str(output_path), transform_context, save_options, 
                self.target_crs, None
            )
            
            if error[0] == QgsVectorFileWriter.NoError:
                QMessageBox.information(self, "Success", 
                    f"Reprojection completed successfully!\nOutput: {output_path}")
                self.log_message(f"Reprojection completed: {output_path}", "Info")
                
                # Reload the shapefiles list
                self.load_shapefiles()
            else:
                QMessageBox.critical(self, "Error", f"Reprojection failed: {error[1]}")
                self.log_message(f"Reprojection failed: {error[1]}", "Error")
                
        except Exception as e:
            error_msg = f"Error during reprojection: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def update_current_crs(self, item):
        """Update the current CRS display"""
        if item:
            filename = item.data(0, Qt.UserRole)
            if filename and filename in self.loaded_shapefiles:
                # Use the already loaded information
                data = self.loaded_shapefiles[filename]
                
                # Try first with the layer for complete description
                layer = data.get('layer')
                if layer and layer.isValid():
                    crs = layer.crs()
                    if crs.isValid():
                        self.current_crs_label.setText(f"{crs.description()} ({crs.authid()})")
                        return
                
                # Fallback: use the stored CRS directly
                crs_authid = data.get('crs', '')
                if crs_authid and crs_authid != 'Unknown':
                    # Try to create a CRS from the authid for description
                    try:
                        crs = QgsCoordinateReferenceSystem(crs_authid)
                        if crs.isValid():
                            self.current_crs_label.setText(f"{crs.description()} ({crs.authid()})")
                        else:
                            self.current_crs_label.setText(crs_authid)
                    except:
                        self.current_crs_label.setText(crs_authid)
                    return
        
        self.current_crs_label.setText("Unknown")


class PreferencesDialog(QDialog):
    """Preferences dialog"""
    
    def __init__(self, settings: InterfaceSettings, parent=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.resize(500, 400)
        
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Preferences tabs
        tabs = QTabWidget()
        
        # Appearance tab
        appearance_tab = QWidget()
        appearance_layout = QFormLayout()
        
        # Theme
        self.theme_combo = QComboBox()
        for theme in InterfaceTheme:
            self.theme_combo.addItem(theme.value.replace("_", " ").title(), theme)
        appearance_layout.addRow("Theme:", self.theme_combo)
        
        # Interface options
        self.animations_cb = QCheckBox("Enable animations")
        self.tooltips_cb = QCheckBox("Show tooltips")
        self.compact_toolbar_cb = QCheckBox("Compact toolbar")
        
        appearance_layout.addRow("", self.animations_cb)
        appearance_layout.addRow("", self.tooltips_cb)
        appearance_layout.addRow("", self.compact_toolbar_cb)
        
        appearance_tab.setLayout(appearance_layout)
        tabs.addTab(appearance_tab, "Appearance")
        
        # Editing tab
        editing_tab = QWidget()
        editing_layout = QFormLayout()
        
        self.auto_save_cb = QCheckBox("Auto-save configurations")
        self.syntax_highlighting_cb = QCheckBox("Expression syntax highlighting")
        self.auto_complete_cb = QCheckBox("Auto-complete expressions")
        
        editing_layout.addRow("", self.auto_save_cb)
        editing_layout.addRow("", self.syntax_highlighting_cb)
        editing_layout.addRow("", self.auto_complete_cb)
        
        self.undo_steps_spin = QSpinBox()
        self.undo_steps_spin.setRange(10, 100)
        editing_layout.addRow("Max undo steps:", self.undo_steps_spin)
        
        editing_tab.setLayout(editing_layout)
        tabs.addTab(editing_tab, "Editing")
        
        # Advanced tab
        advanced_tab = QWidget()
        advanced_layout = QFormLayout()
        
        self.show_performance_cb = QCheckBox("Show performance statistics")
        self.enable_debug_cb = QCheckBox("Enable debugging")
        
        advanced_layout.addRow("", self.show_performance_cb)
        advanced_layout.addRow("", self.enable_debug_cb)
        
        self.backup_interval_spin = QSpinBox()
        self.backup_interval_spin.setRange(60, 3600)
        self.backup_interval_spin.setSuffix(" seconds")
        advanced_layout.addRow("Auto-backup interval:", self.backup_interval_spin)
        
        advanced_tab.setLayout(advanced_layout)
        tabs.addTab(advanced_tab, "Advanced")
        
        layout.addWidget(tabs)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        
        layout.addWidget(buttons)
        self.setLayout(layout)
    
    def load_settings(self):
        """Load settings into the interface"""
        # Appearance
        theme_index = self.theme_combo.findData(self.settings.theme)
        if theme_index >= 0:
            self.theme_combo.setCurrentIndex(theme_index)
        
        self.animations_cb.setChecked(self.settings.enable_animations)
        self.tooltips_cb.setChecked(self.settings.show_tooltips)
        self.compact_toolbar_cb.setChecked(self.settings.compact_toolbar)
        
        # Editing
        self.auto_save_cb.setChecked(self.settings.auto_save_config)
        self.syntax_highlighting_cb.setChecked(self.settings.expression_syntax_highlighting)
        self.auto_complete_cb.setChecked(self.settings.auto_complete_expressions)
        self.undo_steps_spin.setValue(self.settings.max_undo_steps)
        
        # Advanced
        self.show_performance_cb.setChecked(self.settings.show_performance_stats)
        self.enable_debug_cb.setChecked(self.settings.enable_debugging)
        self.backup_interval_spin.setValue(self.settings.auto_backup_interval)
    
    def save_settings(self):
        """Save settings from the interface"""
        # Appearance
        self.settings.theme = self.theme_combo.currentData()
        self.settings.enable_animations = self.animations_cb.isChecked()
        self.settings.show_tooltips = self.tooltips_cb.isChecked()
        self.settings.compact_toolbar = self.compact_toolbar_cb.isChecked()
        
        # Editing
        self.settings.auto_save_config = self.auto_save_cb.isChecked()
        self.settings.expression_syntax_highlighting = self.syntax_highlighting_cb.isChecked()
        self.settings.auto_complete_expressions = self.auto_complete_cb.isChecked()
        self.settings.max_undo_steps = self.undo_steps_spin.value()
        
        # Advanced
        self.settings.show_performance_stats = self.show_performance_cb.isChecked()
        self.settings.enable_debugging = self.enable_debug_cb.isChecked()
        self.settings.auto_backup_interval = self.backup_interval_spin.value()
    
    def restore_defaults(self):
        """Restore default settings"""
        self.settings = InterfaceSettings()
        self.load_settings()
    
    def accept(self):
        """Accept with saving"""
        self.save_settings()
        super().accept()
    
    def get_settings(self) -> InterfaceSettings:
        """Get configured settings"""
        return self.settings


class ExpressionTesterDialog(QDialog):
    """Expression tester dialog"""
    
    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        
        self.setWindowTitle("Expression Tester")
        self.setModal(True)
        self.resize(800, 600)
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Layer selection
        if not self.layer:
            layer_layout = QHBoxLayout()
            layer_layout.addWidget(QLabel("Layer:"))
            
            self.layer_combo = QgsMapLayerComboBox()
            # Configuration pour couches vectorielles uniquement - approche moderne QGIS
            self.layer_combo.setShowCrs(True)
            self.layer_combo.setAllowEmptyLayer(False)
            layer_layout.addWidget(self.layer_combo)
            
            layout.addLayout(layer_layout)
        
        # Expression builder
        self.expression_widget = AdvancedExpressionWidget(self.layer)
        layout.addWidget(self.expression_widget)
        
        # Résultats
        results_group = QGroupBox("Test Results")
        results_layout = QVBoxLayout()
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Feature ID", "Result", "Type"])
        self.results_table.setMaximumHeight(200)
        
        results_layout.addWidget(self.results_table)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        # Actions
        actions_layout = QHBoxLayout()
        
        self.test_btn = QPushButton("Test Expression")
        self.test_btn.clicked.connect(self.test_expression)
        
        self.test_sample_btn = QPushButton("Test Sample (10 features)")
        self.test_sample_btn.clicked.connect(lambda: self.test_expression(sample_size=10))
        
        actions_layout.addWidget(self.test_btn)
        actions_layout.addWidget(self.test_sample_btn)
        actions_layout.addStretch()
        
        layout.addLayout(actions_layout)
        
        # Close buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure connections"""
        if hasattr(self, 'layer_combo'):
            self.layer_combo.layerChanged.connect(self.on_layer_changed)
    
    def on_layer_changed(self, layer):
        """Handle layer change"""
        self.layer = layer
        self.expression_widget.set_layer(layer)
        self.results_table.setRowCount(0)
    
    def test_expression(self, sample_size=None):
        """Test expression on features"""
        try:
            if not self.layer:
                QMessageBox.warning(self, "Warning", "No layer selected")
                return
            
            expression_text = self.expression_widget.get_expression().strip()
            if not expression_text:
                QMessageBox.warning(self, "Warning", "No expression to test")
                return
            
            expression = QgsExpression(expression_text)
            if expression.hasParserError():
                QMessageBox.warning(self, "Expression Error", f"Syntax error: {expression.parserErrorString()}")
                return
            
            # Prepare the context
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(self.layer))
            context.setFields(self.layer.fields())
            
            # Get features
            if sample_size:
                features = list(self.layer.getFeatures())[:sample_size]
            else:
                features = list(self.layer.getFeatures())
            
            # Configure the table
            self.results_table.setRowCount(len(features))
            
            # Test on each feature
            for i, feature in enumerate(features):
                context.setFeature(feature)
                
                try:
                    result = expression.evaluate(context)
                    
                    if expression.hasEvalError():
                        result_text = f"ERROR: {expression.evalErrorString()}"
                        result_type = "Error"
                    else:
                        result_text = str(result) if result is not None else "NULL"
                        result_type = type(result).__name__
                    
                except Exception as e:
                    result_text = f"EXCEPTION: {str(e)}"
                    result_type = "Exception"
                
                # Fill the table
                self.results_table.setItem(i, 0, QTableWidgetItem(str(feature.id())))
                self.results_table.setItem(i, 1, QTableWidgetItem(result_text))
                self.results_table.setItem(i, 2, QTableWidgetItem(result_type))
            
            # Adjust columns
            self.results_table.resizeColumnsToContents()
            
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"Error testing expression: {str(e)}")


# Main interface function for compatibility
def MinimalTransformerDialog(config_manager, transformer, parent=None):
    """Main entry point for the improved interface"""
    return EnhancedTransformerDialog(config_manager, transformer, parent)


# Export main classes
__all__ = [
    'EnhancedTransformerDialog',
    'MinimalTransformerDialog',
    'AdvancedExpressionWidget', 
    'SmartFilterWidget',
    'FieldWidget',
    'ExpressionTesterDialog',
    'PreferencesDialog',
    'InterfaceSettings',
    'InterfaceTheme',
    'PanelMode'
]
