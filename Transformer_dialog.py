# -*- coding: utf-8 -*-
"""
 Interface for Transformer - Elite Version
Developed by YADDA

Native QGIS interface with advanced features and optimal ergonomics
"""

import os
import sys
import json
import traceback
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

# Centralized logger for the plugin
from .logger import logger as plugin_logger, log_info, log_warning, log_error, log_success

# Define enums and dataclasses here to avoid circular imports
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

# Smooth config selector (optional import)
try:
    from .config_selector import SmoothConfigSelector
except ImportError:
    SmoothConfigSelector = None

from qgis.PyQt.QtCore import (
    Qt, pyqtSignal, QSettings, QSize, QEvent, QRect
)

# Import QTimer with fallback
try:
    from qgis.PyQt.QtCore import QTimer
except ImportError:
    try:
        from PyQt5.QtCore import QTimer
    except ImportError:
        class QTimer:
            def __init__(self, parent=None):
                pass
            def timeout(self):
                class Signal:
                    def connect(self, func):
                        pass
                return Signal()
            def setSingleShot(self, single):
                pass
            def start(self, msec=None):
                pass
            def stop(self):
                pass
            @staticmethod
            def singleShot(msec, func):
                try:
                    func()
                except:
                    pass

from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QPlainTextEdit, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QSlider, QProgressBar, QTabWidget, QWidget,
    QGroupBox, QFrame, QSplitter, QScrollArea, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpacerItem, QToolButton, QMenu, QAction, QActionGroup,
    QButtonGroup, QRadioButton, QStatusBar, QMenuBar,
    QFileDialog, QMessageBox, QInputDialog, QColorDialog, QFontDialog,
    QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem, QMainWindow, QDockWidget, QDialogButtonBox
)

# Import QToolBar with fallback
try:
    from qgis.PyQt.QtWidgets import QToolBar
except ImportError:
    try:
        from PyQt5.QtWidgets import QToolBar
    except ImportError:
        class QToolBar:
            def __init__(self, text="", parent=None):
                pass
            def setToolButtonStyle(self, style):
                pass
            def setIconSize(self, size):
                pass
            def setFloatable(self, floatable):
                pass
            def addAction(self, action):
                pass
            def setStyleSheet(self, style):
                pass

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

from qgis.PyQt.QtGui import (
    QIcon, QColor, QPalette, QPixmap, QPainter, QBrush, QPen, QFontMetrics,
    QKeySequence, QDesktopServices, QClipboard, QDrag, QValidator,
    QIntValidator, QDoubleValidator, QRegExpValidator, QStandardItemModel,
    QStandardItem, QMovie, QCursor, QPolygon, QLinearGradient, QRadialGradient,
    QConicalGradient, QTextCharFormat, QTextCursor, QTextDocument, QSyntaxHighlighter,
    QTextBlockFormat, QFontDatabase, QTransform, QPainterPath, QRegion,
    QBitmap, QImageReader, QImageWriter, QPaintEvent, QResizeEvent, QShowEvent,
    QHideEvent, QCloseEvent, QKeyEvent, QMouseEvent, QWheelEvent, QContextMenuEvent,
    QFocusEvent, QMoveEvent, QDropEvent, QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent
)

# Import QShortcut with multi-version compatibility
QShortcut = None
try:
    from qgis.PyQt.QtWidgets import QShortcut  # Recent versions
except ImportError:
    try:
        from qgis.PyQt.QtGui import QShortcut  # Older versions  
    except ImportError:
        try:
            from PyQt5.QtWidgets import QShortcut  # Direct PyQt5
        except ImportError:
            try:
                from PyQt5.QtGui import QShortcut  # PyQt5 legacy
            except ImportError:
                # Fallback class if QShortcut unavailable
                class QShortcut:
                    def __init__(self, key_sequence, parent):
                        self.key_sequence = key_sequence
                        self.parent = parent
                        print(f"QShortcut not available - shortcut {key_sequence} disabled")
                    
                    def setContext(self, context):
                        pass
                        
                    class MockSignal:
                        def connect(self, callback):
                            pass
                            
                    @property 
                    def activated(self):
                        return self.MockSignal()

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
            class Normal:
                pass

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
    QgsNewHttpConnection, QgsProjectionSelectionDialog,
    QgsHighlight, QgsAttributeTableModel, QgsAttributeTableView, QgsAttributeTableDelegate,
    QgsAttributeTableFilterModel, QgsFeatureSelectionModel, QgsIFeatureSelectionManager,
    QgsActionMenu, QgsAttributeForm, QgsAttributeDialog,
    QgsFieldValidator, QgsEditorWidgetWrapper, QgsEditorWidgetFactory, QgsEditorWidgetRegistry,


)

# Import QgsCoordinateReferenceSystemProxyModel with fallback
try:
    from qgis.gui import QgsCoordinateReferenceSystemProxyModel
except ImportError:
    try:
        from qgis.core import QgsCoordinateReferenceSystemProxyModel
    except ImportError:
        # Fallback class if not available
        class QgsCoordinateReferenceSystemProxyModel:
            def __init__(self, parent=None):
                self.parent = parent
                print("QgsCoordinateReferenceSystemProxyModel not available - using fallback")

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


# Import des classes extraites dans des fichiers séparés
try:
    from .EnhancedTransformerDialog import EnhancedTransformerDialog
    ENHANCED_DIALOG_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"EnhancedTransformerDialog import failed: {str(e)}", "Transformer", Qgis.Critical)
    ENHANCED_DIALOG_AVAILABLE = False
    EnhancedTransformerDialog = None

try:
    from .FieldWidget import FieldWidget
    FIELD_WIDGET_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"FieldWidget import failed: {str(e)}", "Transformer", Qgis.Critical)
    FIELD_WIDGET_AVAILABLE = False
    FieldWidget = None

try:
    from .PreferencesDialog import PreferencesDialog
    PREFERENCES_DIALOG_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"PreferencesDialog import failed: {str(e)}", "Transformer", Qgis.Warning)
    PREFERENCES_DIALOG_AVAILABLE = False
    PreferencesDialog = None

try:
    from .ExpressionTesterDialog import ExpressionTesterDialog
    EXPRESSION_TESTER_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"ExpressionTesterDialog import failed: {str(e)}", "Transformer", Qgis.Warning)
    EXPRESSION_TESTER_AVAILABLE = False
    ExpressionTesterDialog = None

try:
    from .FieldDefinitionDialog import FieldDefinitionDialog
    FIELD_DEFINITION_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"FieldDefinitionDialog import failed: {str(e)}", "Transformer", Qgis.Warning)
    FIELD_DEFINITION_AVAILABLE = False
    FieldDefinitionDialog = None

# Import des widgets spécialisés (à créer si nécessaire)
try:
    from .AdvancedExpressionWidget import AdvancedExpressionWidget
    ADVANCED_EXPRESSION_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"AdvancedExpressionWidget import failed: {str(e)}", "Transformer", Qgis.Warning)
    ADVANCED_EXPRESSION_AVAILABLE = False
    AdvancedExpressionWidget = None

try:
    from .SmartFilterWidget import SmartFilterWidget
    SMART_FILTER_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"SmartFilterWidget import failed: {str(e)}", "Transformer", Qgis.Warning)
    SMART_FILTER_AVAILABLE = False
    SmartFilterWidget = None

# Global variables from the main module will be imported in the methods that need them
# to avoid circular imports


# Classe complexe supprimée - on utilise le système Qt natif

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


# Main interface function for compatibility
def MinimalTransformerDialog(config_manager, transformer, parent=None):
    """Main entry point for the improved interface"""
    if EnhancedTransformerDialog is None:
        QgsMessageLog.logMessage("EnhancedTransformerDialog is None, cannot create interface", "Transformer", Qgis.Critical)
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel
        
        class EmergencyDialog(QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Transformer - Import Error")
                layout = QVBoxLayout()
                layout.addWidget(QLabel("Error: Could not load interface components.\nCheck QGIS log for details."))
                self.setLayout(layout)
        
        return EmergencyDialog(parent)
    
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
