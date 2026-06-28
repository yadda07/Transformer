
# -*- coding: utf-8 -*-
"""
Enhanced Transformer Dialog - Interface principale
"""

import os
import json
import copy
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import (
    Qt, pyqtSignal, QSettings, QSize, QTimer
)

from qgis.PyQt.QtGui import QPixmap, QIcon, QColor, QKeySequence, QCursor, QFont
from qgis.PyQt.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QPlainTextEdit, QComboBox, QCheckBox,
    QSpinBox, QTabWidget, QGroupBox, QFrame, QSplitter, QScrollArea, 
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView,
    QToolButton, QMenu, QAction, QActionGroup, QStatusBar, QMenuBar, QProgressBar,
    QFileDialog, QMessageBox, QInputDialog, QListWidget, QListWidgetItem,
    QDockWidget, QAbstractItemView, QApplication, QDialog
)

from qgis.PyQt.QtWidgets import QToolBar, QSizePolicy, QShortcut

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem,
    QgsMessageLog, Qgis, QgsWkbTypes, QgsFeatureRequest, QgsExpression,
    QgsFields, QgsField, QgsFeature, QgsGeometry, QgsSettings, QgsApplication,
    QgsVectorFileWriter, QgsCoordinateTransformContext
)

from qgis.gui import (
    QgsExpressionBuilderDialog, QgsProjectionSelectionWidget, QgsMapLayerComboBox,
    QgsProjectionSelectionDialog, QgsMessageBar
)

# Import QgsCoordinateReferenceSystemProxyModel - optional
QgsCoordinateReferenceSystemProxyModel = None
try:
    from qgis.gui import QgsCoordinateReferenceSystemProxyModel
except ImportError:
    try:
        from qgis.core import QgsCoordinateReferenceSystemProxyModel
    except ImportError:
        # Cette classe n'est pas disponible dans toutes les versions QGIS
        pass

# Import des widgets directement pour éviter les imports circulaires
from ..widgets.advanced_expression_widget import AdvancedExpressionWidget
from ..widgets.smart_filter_widget import SmartFilterWidget
from ..widgets.field_widget import FieldWidget
from ..widgets.expression_tester_dialog import ExpressionTesterDialog

# Import des fonctions de logging
from ..shared.logger import logger as plugin_logger, log_info, log_warning, log_error, log_success

# Import interface configuration classes
from ..shared.interface_config import InterfaceTheme, PanelMode, InterfaceSettings
from ..shared.constants import VECTOR_EXTENSIONS
from ..shared.helpers import (
    create_layer_expression_context,
    is_filter_enabled,
    get_filter_expression,
    apply_compact_button,
)
from ..shared.icons import (
    IconTone,
    icon as ui_icon,
    clear_icon_cache,
    set_action_outcome,
    set_actions_outcome,
    svg_html,
)
from ..shared.expression_utils import validate_expression_syntax, evaluate_expression
from ..shared.field_classification import is_dark_palette

# Import additional modules with error handling
try:
    from ..export.export_module import ExportWidget
    EXPORT_CLASSES_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"Export module import error: {e}", "Transformer", Qgis.Warning)
    ExportWidget = None
    EXPORT_CLASSES_AVAILABLE = False

try:
    from ..pg.postgresql_integration import PostgreSQLIntegrationWidget
    POSTGRESQL_INTEGRATION_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"PostgreSQL module import error: {e}", "Transformer", Qgis.Warning)
    PostgreSQLIntegrationWidget = None
    POSTGRESQL_INTEGRATION_AVAILABLE = False

# Qt5/Qt6 enum compatibility
from ..shared.compat import (
    AlignCenter, AlignTop, AlignVCenter,
    ApplicationShortcut, BackgroundRole, ForegroundRole,
    FontBold, FontNormal, Horizontal, KeepAspectRatio,
    PointingHandCursor, RichText, ScrollBarAsNeeded,
    SmoothTransformation, ToolButtonTextBesideIcon, UserRole, Vertical,
    CustomContextMenu, WrapWidgetWidth, InstantPopup,
    KeyNew, KeyOpen, KeySave, KeyQuit, KeyUndo, KeyRedo, KeyHelpContents,
    _AlignmentFlag, _DialogCode,
    _DockOption, _DockWidgetArea, _DockWidgetFeature,
    _FrameShape, FrameNoFrame, FrameHLine, _HeaderResizeMode, _ItemDataRole,
    _MsgBoxButton, _MsgBoxIcon, _Orientation,
    _ScrollBarPolicy, _SelectionBehavior, _SelectionMode,
    _SizePolicy, _TabPosition, _TextFormat,
    _ToolBarArea, _ToolButtonStyle, _WidgetAttribute,
    palette_color, TextSelectableByMouse,
)
# Background task for async transformations (keeps UI responsive)
from ..core.transform_task import TransformTask
from ..widgets.log_monitor_widget import LogMonitorWidget

from ..shared.logger import logger as _global_logger

class EnhancedTransformerDialog(QMainWindow):
    """Enhanced main interface with native QGIS features"""
    
    transformation_requested = pyqtSignal(str)
    window_closed = pyqtSignal()
    
    def __init__(self, config_manager, transformer, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.transformer = transformer
        self._active_transform_task = None
        self.loaded_shapefiles = {}
        self.current_table_config = {}
        self.interface_settings = InterfaceSettings()
        self._manual_fields_configured = False # Flag to preserve manually configured fields
        self._draft_config_source = None  # layer with auto-populated preview, not yet edited
        self._config_modified_by_user = False
        self._suppress_table_name_side_effects = False
        
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
        self.config_dock.raise_() # Configuration Preview par défaut
        
        # Auto-load QGIS layers and their existing configurations
        self.auto_load_qgis_layers()
        self.refresh_shapefile_list()
        self.auto_load_configs() # Load configurations for existing layers
        
        # Initialize statistics with real values
        QTimer.singleShot(100, self.update_statistics) # Delay to allow complete initialization
        
    def setup_main_window(self):
        """Configure the main window"""
        self.setWindowTitle("Transformer")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)
        
        # Application icon - logo du plugin
        import os
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
        else:
            # Fallback vers l'icône par défaut si le logo n'est pas trouvé
            self.setWindowIcon(ui_icon("window"))
        
        # Configuration avancée pour repositionnement et redimensionnement fluide
        try:
            # Qt6: enums under QMainWindow.DockOption; Qt5: directly on QMainWindow
            dock_options = (
                _DockOption.AllowNestedDocks |
                _DockOption.AllowTabbedDocks |
                _DockOption.AnimatedDocks |
                _DockOption.GroupedDragging
            )
            
            if hasattr(_DockOption, 'VerticalTabs'):
                dock_options |= _DockOption.VerticalTabs
                
            self.setDockOptions(dock_options)
            self.setTabPosition(_DockWidgetArea.AllDockWidgetAreas, _TabPosition.North)
            
            if hasattr(self, 'setDockNestingEnabled'):
                self.setDockNestingEnabled(True)
            
            self.setAttribute(_WidgetAttribute.WA_TranslucentBackground, False)
            
            log_info("Native Qt dock drop zones activated (like QGIS)")
            
        except Exception as e:
            log_error(f"Error setting dock options: {str(e)}")
    
    def setup_central_widget(self):
        """Configure the central widget"""
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(4, 4, 4, 4)
        
        # Main tabs
        self.main_tabs = QTabWidget()
        self.main_tabs.setTabPosition(_TabPosition.North)
        self.main_tabs.setMovable(True)
        self.main_tabs.setTabsClosable(False)
        
        # Configuration tab
        config_tab = self.create_configuration_tab()
        self.main_tabs.addTab(config_tab, ui_icon("config"), "Configuration")
        
        # Export tab (integrated) - Using local imports
        if EXPORT_CLASSES_AVAILABLE and ExportWidget is not None:
            try:
                self.export_widget = ExportWidget()
                self.main_tabs.addTab(self.export_widget, ui_icon("export"), "Export")
                self.log_message("Export tab created", "Success") # Internal log only
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
                self.main_tabs.addTab(self.postgresql_widget, ui_icon("postgresql"), "PostgreSQL")
            except Exception as e:
                QgsMessageLog.logMessage(f"PostgreSQL widget creation error: {str(e)}", "Transformer", Qgis.Critical)
                # Fallback widget
                postgresql_fallback = QWidget()
                postgresql_layout = QVBoxLayout()
                postgresql_layout.addWidget(QLabel("PostgreSQL integration error"))
                postgresql_layout.addWidget(QLabel(f"Error creating PostgreSQL widget: {str(e)}"))
                postgresql_layout.addWidget(QLabel("Please check the logs for more details."))
                postgresql_fallback.setLayout(postgresql_layout)
                self.main_tabs.addTab(postgresql_fallback, ui_icon("postgresql"), "PostgreSQL")
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
            self.main_tabs.addTab(postgresql_fallback, ui_icon("postgresql"), "PostgreSQL")
            self.postgresql_widget = None

        # Ready for core transformation components
        
        # Finalize the central layout
        central_layout.addWidget(self.main_tabs)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)
    
    def create_configuration_tab(self):
        """Create main configuration tab"""
        tab_widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Main splitter
        main_splitter = QSplitter(_Orientation.Horizontal)
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
        """Create main expression panel with dynamic resizing and toggleable components"""
        panel = QFrame()
        panel.setFrameStyle(_FrameShape.NoFrame)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        # Components visibility toolbar
        visibility_toolbar = QToolBar("Components Visibility")
        visibility_toolbar.setToolButtonStyle(_ToolButtonStyle.ToolButtonTextBesideIcon)
        visibility_toolbar.setIconSize(QSize(16, 16))
        visibility_toolbar.setFloatable(False)
        visibility_toolbar.setMovable(False)
        
        # Visibility toggle actions 
        self.table_config_action = QAction(ui_icon("table_config"), "Table Configuration", self)
        self.table_config_action.setCheckable(True)
        self.table_config_action.setChecked(True)
        self.table_config_action.setToolTip("Toggle Table Configuration visibility")
        self.table_config_action.toggled.connect(lambda checked: self.toggle_component_visibility('table_config', checked))
        
        self.filter_action = QAction(ui_icon("filter"), "Smart Filter", self)
        self.filter_action.setCheckable(True)
        self.filter_action.setChecked(True)
        self.filter_action.setToolTip("Toggle Smart Filter visibility")
        self.filter_action.toggled.connect(lambda checked: self.toggle_component_visibility('smart_filter', checked))
        
        self.expression_action = QAction(ui_icon("expression"), "Expression Builder", self)
        self.expression_action.setCheckable(True)
        self.expression_action.setChecked(True)
        self.expression_action.setToolTip("Toggle Expression Builder visibility")
        self.expression_action.toggled.connect(lambda checked: self.toggle_component_visibility('expression_builder', checked))
        
        self.fields_action = QAction(ui_icon("fields"), "Field Management", self)
        self.fields_action.setCheckable(True)
        self.fields_action.setChecked(True)
        self.fields_action.setToolTip("Toggle Field Management visibility")
        self.fields_action.toggled.connect(lambda checked: self.toggle_component_visibility('field_management', checked))
        
        visibility_toolbar.addAction(self.table_config_action)
        visibility_toolbar.addAction(self.filter_action)
        visibility_toolbar.addAction(self.expression_action)
        visibility_toolbar.addAction(self.fields_action)
        
        # Separator and reset button
        visibility_toolbar.addSeparator()
        reset_visibility_action = QAction(ui_icon("show_all"), "Show All", self)
        reset_visibility_action.setToolTip("Show all components")
        reset_visibility_action.triggered.connect(self.show_all_components)
        visibility_toolbar.addAction(reset_visibility_action)
        
        # Apply highlight color only to checked/selected buttons
        visibility_toolbar.setStyleSheet("QToolButton:checked { background-color: palette(highlight); color: palette(highlighted-text); }")
        
        main_layout.addWidget(visibility_toolbar)
        
        # Create vertical splitter for dynamic resizing between components
        self.config_splitter = QSplitter(_Orientation.Vertical)
        self.config_splitter.setChildrenCollapsible(False) # Prevent complete collapse
        
        # Store component references for visibility management
        self.config_components = {}
        
        # Table configuration - compact version
        self.config_components['table_config'] = QGroupBox("Table Configuration")
        config_layout = QFormLayout()
        config_layout.setVerticalSpacing(8) # Espacement vertical confortable
        config_layout.setContentsMargins(10, 12, 10, 8) # Marges améliorées (haut augmenté)
        
        self.table_name_edit = QLineEdit()
        self.table_name_edit.setPlaceholderText("Enter output table name...")
        self.table_name_edit.setMaximumHeight(24) # Hauteur fixe pour le champ
        config_layout.addRow("Table Name:", self.table_name_edit)
        
        self.config_components['table_config'].setLayout(config_layout)
        self.config_components['table_config'].setMinimumHeight(55) # Minimum suffisant pour éviter l'écrasement
        self.config_components['table_config'].setMaximumHeight(85) # Hauteur max légèrement augmentée
        # Définir une hauteur par défaut confortable
        self.config_components['table_config'].resize(self.config_components['table_config'].width(), 75)
        self.config_components['table_config'].setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Preferred)
        self.config_splitter.addWidget(self.config_components['table_config'])
        
        # Smart filter widget
        self.config_components['smart_filter'] = QGroupBox("Smart Filter")
        filter_layout = QVBoxLayout()
        
        self.smart_filter = SmartFilterWidget()
        filter_layout.addWidget(self.smart_filter)
        
        self.config_components['smart_filter'].setLayout(filter_layout)
        self.config_components['smart_filter'].setMinimumHeight(120)
        self.config_splitter.addWidget(self.config_components['smart_filter'])
        
        # Advanced expression builder
        self.config_components['expression_builder'] = QGroupBox("Expression Builder")
        expr_layout = QVBoxLayout()
        
        self.advanced_expression = AdvancedExpressionWidget()
        expr_layout.addWidget(self.advanced_expression)
        
        self.config_components['expression_builder'].setLayout(expr_layout)
        self.config_components['expression_builder'].setMinimumHeight(200)
        self.config_splitter.addWidget(self.config_components['expression_builder'])
        
        # Smart fields widget
        self.config_components['field_management'] = QGroupBox("Field Management (Column Configuration)")
        fields_layout = QVBoxLayout()
        
        # Add explanatory label
        info_label = QLabel("Add, edit and manage calculated fields (columns) for your output table:")
        info_font = info_label.font()
        info_font.setItalic(True)
        info_label.setFont(info_font)
        fields_layout.addWidget(info_label)
        
        self.smart_fields = FieldWidget(self.advanced_expression)
        # Configurer pour expansion verticale optimale
        self.smart_fields.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)
        fields_layout.addWidget(self.smart_fields)
        
        self.config_components['field_management'].setLayout(fields_layout)
        self.config_components['field_management'].setMinimumHeight(150)
        self.config_splitter.addWidget(self.config_components['field_management'])
        
        # Set proportional sizes - Field Management prioritaire pour expansion
        self.config_splitter.setStretchFactor(0, 1) # Table Configuration
        self.config_splitter.setStretchFactor(1, 1) # Smart Filter 
        self.config_splitter.setStretchFactor(2, 2) # Expression Builder
        self.config_splitter.setStretchFactor(3, 5) # Field Management (prioritaire pour l'expansion)
        
        main_layout.addWidget(self.config_splitter)
        panel.setLayout(main_layout)
        
        # Load saved component visibility states
        QTimer.singleShot(100, self.restore_component_visibility)
        
        return panel
    
    def toggle_component_visibility(self, component_name, visible):
        """Toggle visibility of a configuration component"""
        try:
            if component_name in self.config_components:
                component = self.config_components[component_name]
                component.setVisible(visible)
                
                # Update corresponding toolbar action
                if hasattr(self, 'config_toolbar_actions'):
                    action = self.config_toolbar_actions.get(component_name)
                    if action:
                        action.setChecked(visible)
                
                # Update corresponding menu action
                if hasattr(self, 'component_menu_actions'):
                    menu_action = self.component_menu_actions.get(component_name)
                    if menu_action:
                        # Temporarily block signals to prevent recursive calls
                        menu_action.blockSignals(True)
                        menu_action.setChecked(visible)
                        menu_action.blockSignals(False)
                
                # Save visibility state
                self.save_component_visibility_state(component_name, visible)
                
                # Log the action
                display_names = {
                    'table_config': 'Table Configuration',
                    'smart_filter': 'Smart Filter', 
                    'expression_builder': 'Expression Builder',
                    'field_management': 'Field Management'
                }
                display_name = display_names.get(component_name, component_name)
                status = "shown" if visible else "hidden"
                self.log_message(f"Component '{display_name}' {status}", "Info")
                
        except Exception as e:
            self.log_message(f"Error toggling component visibility: {str(e)}", "Error")
    
    def show_all_components(self):
        """Show all configuration components"""
        try:
            for component_name in self.config_components.keys():
                self.toggle_component_visibility(component_name, True)
            self.log_message("All configuration components shown", "Info")
        except Exception as e:
            self.log_message(f"Error showing all components: {str(e)}", "Warning")
    
    def save_component_visibility_state(self, component_name, visible):
        """Save component visibility state to settings"""
        try:
            settings = QSettings()
            settings.setValue(f"Transformer/component_{component_name}_visible", visible)
        except Exception as e:
            self.log_message(f"Error saving component visibility state: {str(e)}", "Warning")
    
    def restore_component_visibility(self):
        """Restore saved component visibility states from QSettings"""
        try:
            settings = QSettings()
            for component_name in self.config_components.keys():
                # Default to True (visible) if no setting exists
                visible = settings.value(f"Transformer/component_{component_name}_visible", True, type=bool)
                
                # Set component visibility without triggering menu synchronization
                # (to avoid recursive calls during initialization)
                component = self.config_components[component_name]
                component.setVisible(visible)
                
                # Update menu action state if available
                if hasattr(self, 'component_menu_actions'):
                    menu_action = self.component_menu_actions.get(component_name)
                    if menu_action:
                        menu_action.setChecked(visible)
                        
                # Update toolbar action state if available
                if hasattr(self, 'config_toolbar_actions'):
                    action = self.config_toolbar_actions.get(component_name)
                    if action:
                        action.setChecked(visible)
            
        except Exception as e:
            self.log_message(f"Error restoring component visibility: {str(e)}", "Warning")
    
    def _create_fallback_export_tab(self):
        """Create a fallback export tab when the export module is not available."""
        fallback = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Export module not available"))
        layout.addWidget(QLabel("The export module could not be loaded."))
        layout.addWidget(QLabel("Check your QGIS installation and dependencies."))
        fallback.setLayout(layout)
        self.main_tabs.addTab(
            fallback,
            ui_icon("export"),
            "Export",
        )
    
    def setup_dockwidgets(self):
        """Configure modern fluid dock widgets with enhanced UX"""
        try:
            # Dock options are already set in setup_main_window()
            # Just ensure they are properly configured
            if not (self.dockOptions() & _DockOption.GroupedDragging):
                self.setDockOptions(
                    _DockOption.AnimatedDocks | 
                    _DockOption.AllowNestedDocks | 
                    _DockOption.AllowTabbedDocks |
                    _DockOption.GroupedDragging
                )
            
            # === PRIMARY DOCKS (existants) ===
            
            # Vector Sources (Left)
            self.source_dock = self._create_modern_dock(
                "Vector Sources", 
                "source_dock",
                self.create_shapefiles_widget()
            )
            
            # Configuration Preview (Right)
            self.config_dock = self._create_modern_dock(
                "Configuration Preview", 
                "config_dock",
                self.create_config_preview_widget()
            )
            
            # Activity Monitor (Bottom Right)
            self.log_dock = self._create_modern_dock(
                "Activity Monitor", 
                "log_dock",
                self.create_logs_widget()
            )
            
            # Quick Help (Tabbed with Config)
            self.help_dock = self._create_modern_dock(
                "Quick Help", 
                "help_dock",
                self.create_help_widget()
            )
            
            # === NOUVEAUX DOCKS MODULAIRES (ex-blocs centraux) ===
            
            # Note: Table Configuration reste intégrée dans le bloc central Configuration
            
            # Note: Smart Filter reste intégré dans le bloc central Configuration
            
            # Note: Expression Builder reste intégré dans le bloc central Configuration
            
            # Note: Field Management reste intégré dans le bloc central Configuration
            
            # === DOCK LAYOUT ===
            self._arrange_fluid_layout()
            
            # === ENHANCED FEATURES ===
            self._setup_dock_signals()
            self._setup_dock_styling()
            self._setup_layout_presets()
            
            # === FINALIZE SETUP ===
            # Le système Qt natif gère déjà parfaitement le drag & drop
            # Il suffit de s'assurer que tout est correctement configuré
            QTimer.singleShot(100, self._finalize_dock_setup)
            
        except Exception as e:
            log_error(f"Error setting up modern dock widgets: {str(e)}")
            self._setup_fallback_docks()
    
    def _setup_fallback_docks(self):
        """Minimal fallback dock layout when modern setup fails."""
        try:
            self.source_dock = QDockWidget("Vector Sources", self)
            self.source_dock.setWidget(QLabel("Sources unavailable"))
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)

            self.config_dock = QDockWidget("Configuration Preview", self)
            self.config_dock.setWidget(QLabel("Config preview unavailable"))
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)

            self.log_dock = QDockWidget("Activity Monitor", self)
            self.log_dock.setWidget(QLabel("Activity monitor unavailable"))
            self.addDockWidget(_DockWidgetArea.BottomDockWidgetArea, self.log_dock)

            self.help_dock = QDockWidget("Quick Help", self)
            self.help_dock.setWidget(QLabel("Help unavailable"))
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.help_dock)

            log_info("Fallback dock layout applied")
        except Exception as e:
            log_error(f"Fallback dock setup also failed: {str(e)}")
    
    def _setup_layout_presets(self):
        """Setup quick layout presets for different processing needs"""
        try:
            # Add layout dropdown to toolbar if it exists
            if hasattr(self, 'toolbar'):
                # Create layout menu button
                layout_menu = QMenu("Layouts", self)
                layout_menu.setIcon(ui_icon("options"))
                
                # Add layout actions
                default_action = QAction("Default Layout", self)
                default_action.triggered.connect(self._layout_default)
                layout_menu.addAction(default_action)
                
                vertical_action = QAction("Vertical Split", self)
                vertical_action.triggered.connect(self._layout_vertical)
                layout_menu.addAction(vertical_action)
                
                horizontal_action = QAction("Horizontal Layout", self)
                horizontal_action.triggered.connect(self._layout_horizontal)
                layout_menu.addAction(horizontal_action)
                
                layout_menu.addSeparator()
                
                focus_config_action = QAction("Focus Configuration", self)
                focus_config_action.triggered.connect(self._layout_focus_config)
                layout_menu.addAction(focus_config_action)
                
                focus_monitor_action = QAction("Focus Activity Monitor", self)
                focus_monitor_action.triggered.connect(self._layout_focus_monitor)
                layout_menu.addAction(focus_monitor_action)
                
                # Add menu to toolbar
                layout_button = QToolButton()
                layout_button.setMenu(layout_menu)
                layout_button.setPopupMode(InstantPopup)
                layout_button.setIcon(ui_icon("options"))
                layout_button.setText("Layouts")
                layout_button.setToolTip("Quick layout presets for different processing needs")
                self.toolbar.addWidget(layout_button)
                
        except Exception as e:
            log_error(f"Error setting up layout presets: {str(e)}")
    
    def _setup_dock_signals(self):
        """Setup enhanced dock signals for user feedback"""
        try:
            docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            for dock in docks:
                if dock:
                    dock.dockLocationChanged.connect(lambda area, d=dock: self._on_dock_moved(d, area))
                    dock.visibilityChanged.connect(lambda visible, d=dock: self._on_dock_visibility_changed(d, visible))
                    dock.topLevelChanged.connect(lambda floating, d=dock: self._on_dock_floating_changed(d, floating))
        except Exception as e:
            log_error(f"Error setting up dock signals: {str(e)}")
    
    def _on_dock_moved(self, dock, area):
        """Handle dock movement with user feedback"""
        try:
            dock_name = dock.windowTitle()
            area_names = {
                _DockWidgetArea.LeftDockWidgetArea: "left",
                _DockWidgetArea.RightDockWidgetArea: "right", 
                _DockWidgetArea.TopDockWidgetArea: "top",
                _DockWidgetArea.BottomDockWidgetArea: "bottom"
            }
            area_name = area_names.get(area, "unknown")
            self.log_message(f"Moved '{dock_name}' to {area_name} area")
        except Exception as e:
            log_error(f"Error handling dock movement: {str(e)}")
    
    def _on_dock_visibility_changed(self, dock, visible):
        """Handle dock visibility changes"""
        try:
            dock_name = dock.windowTitle()
            status = "visible" if visible else "hidden"
            self.log_message(f"'{dock_name}' is now {status}")
        except Exception as e:
            log_error(f"Error handling dock visibility: {str(e)}")
    
    def _on_dock_floating_changed(self, dock, floating):
        """Handle dock floating state changes"""
        try:
            dock_name = dock.windowTitle()
            status = "floating" if floating else "docked"
            self.log_message(f"'{dock_name}' is now {status}")
        except Exception as e:
            log_error(f"Error handling dock floating: {str(e)}")
    
    def _layout_default(self):
        """Default layout: Sources left, Config+Monitor right, Help tabbed"""
        try:
            # Reset all docks
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
            
            # Split config and log vertically on the right
            self.splitDockWidget(self.config_dock, self.log_dock, _Orientation.Vertical)
            
            # Tab help with config
            self.tabifyDockWidget(self.config_dock, self.help_dock)
            self.config_dock.raise_()
            
            # Show all docks
            for dock in [self.source_dock, self.config_dock, self.log_dock, self.help_dock]:
                dock.setVisible(True)
                
            self.log_message("Applied default layout")
        except Exception as e:
            log_error(f"Error applying default layout: {str(e)}")
    
    def _layout_vertical(self):
        """Vertical layout: Config top, Monitor bottom"""
        try:
            # Left: Sources
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
            
            # Right top: Config
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
            
            # Right bottom: Log
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
            self.splitDockWidget(self.config_dock, self.log_dock, _Orientation.Vertical)
            
            # Tab help with config
            self.tabifyDockWidget(self.config_dock, self.help_dock)
            self.config_dock.raise_()
            
            # Adjust sizes - Config larger than log
            self.resizeDocks([self.config_dock], [300], _Orientation.Vertical)
            
            self.log_message("Applied vertical layout")
        except Exception as e:
            log_error(f"Error applying vertical layout: {str(e)}")
    
    def _layout_horizontal(self):
        """Horizontal layout: All panels side by side"""
        try:
            # Arrange all docks horizontally
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
            
            # Split horizontally
            self.splitDockWidget(self.config_dock, self.log_dock, _Orientation.Horizontal)
            
            # Add help at bottom
            self.addDockWidget(_DockWidgetArea.BottomDockWidgetArea, self.help_dock)
            
            self.log_message("Applied horizontal layout")
        except Exception as e:
            log_error(f"Error applying horizontal layout: {str(e)}")
    
    def _layout_focus_config(self):
        """Focus on configuration: Large config panel"""
        try:
            # Config takes most space
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
            
            # Sources on left
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
            
            # Log and help tabbed at bottom
            self.addDockWidget(_DockWidgetArea.BottomDockWidgetArea, self.log_dock)
            self.tabifyDockWidget(self.log_dock, self.help_dock)
            self.log_dock.raise_()
            
            # Resize to focus on config
            self.resizeDocks([self.config_dock], [500], _Orientation.Horizontal)
            
            self.log_message("Applied configuration focus layout")
        except Exception as e:
            log_error(f"Error applying config focus layout: {str(e)}")
    
    def _layout_focus_monitor(self):
        """Focus on monitoring: Large activity monitor"""
        try:
            # Monitor takes most space
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
            
            # Sources on left
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
            
            # Config and help tabbed at bottom
            self.addDockWidget(_DockWidgetArea.BottomDockWidgetArea, self.config_dock)
            self.tabifyDockWidget(self.config_dock, self.help_dock)
            self.config_dock.raise_()
            
            # Resize to focus on monitor
            self.resizeDocks([self.log_dock], [500], _Orientation.Horizontal)
            
            self.log_message("Applied activity monitor focus layout")
        except Exception as e:
            log_error(f"Error applying monitor focus layout: {str(e)}")
    
    def _setup_dock_styling(self):
        """Setup dock widget styling - laisser le thème QGIS par défaut"""
        pass
    
    def _create_modern_dock(self, title, object_name, widget):
        """Create a modern dock widget with enhanced repositioning and resizing"""
        try:
            dock = QDockWidget(title, self)
            dock.setObjectName(object_name)
            
            # Ensure widget is valid
            if widget is None:
                widget = QLabel(f"Error: No widget for {title}")
                
            dock.setWidget(widget)
            
            # Features complètes comme les docks QGIS natifs
            dock.setFeatures(
                _DockWidgetFeature.DockWidgetMovable | # Déplaçable
                _DockWidgetFeature.DockWidgetFloatable | # Flottant 
                _DockWidgetFeature.DockWidgetClosable # Fermable
            )
            
            # PAS de custom title bar - utiliser titre natif
            
            # Zones autorisées : TOUTES pour flexibilité maximale comme QGIS
            dock.setAllowedAreas(_DockWidgetArea.AllDockWidgetAreas)
            
            # PAS d'attributs custom qui peuvent bloquer les drop zones natives
            # dock.setProperty("dragEnabled", True) # <- Inutile, Qt le fait déjà
            # dock.setAttribute(Qt.WA_DeleteOnClose, False) # <- Peut interférer
            
            # Tailles optimales pour redimensionnement
            dock.setMinimumSize(250, 180) # Taille minimum plus généreuse
            dock.setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Preferred)
            
            # Tailles par défaut selon le type de dock
            if 'source' in object_name.lower():
                dock.resize(350, 400) # Sources plus larges
            elif 'config' in object_name.lower():
                dock.resize(400, 300) # Config plus carrée
            elif 'log' in object_name.lower():
                dock.resize(450, 250) # Log plus large
            else:
                dock.resize(300, 200) # Taille par défaut
            
            # SIMPLE : Laisser Qt gérer les animations nativement
            # dock.setProperty("animated", True) # <- Inutile, Qt le fait déjà
            
            # Visible et actif (nécessaire)
            dock.setVisible(True)
            dock.setEnabled(True)
            
            return dock
            
        except Exception as e:
            log_error(f"Error creating modern dock '{title}': {str(e)}")
            # Fallback: create basic dock with all features
            dock = QDockWidget(title, self)
            dock.setWidget(widget if widget else QLabel(f"Error loading {title}"))
            dock.setFeatures(
                _DockWidgetFeature.DockWidgetMovable |
                _DockWidgetFeature.DockWidgetFloatable |
                _DockWidgetFeature.DockWidgetClosable
            ) # Full features restored
            dock.setAllowedAreas(_DockWidgetArea.AllDockWidgetAreas) # Allow all areas
            return dock
    
    def _arrange_fluid_layout(self):
        """Arrange docks with intelligent positioning and resizing"""
        try:
            # === POSITIONNEMENT INTELLIGENT ===
            
            # Gauche: Vector Sources (zone principale pour les fichiers)
            self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
            
            # Droite: Configuration Preview (zone de travail principale)
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
            
            # Droite: Activity Monitor (monitoring en continu)
            self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
            
            # === SPLITS INTELLIGENTS ===
            # Split vertical pour séparer config (haut) et log (bas)
            self.splitDockWidget(self.config_dock, self.log_dock, _Orientation.Vertical)
            
            # Tabifier Help avec Config pour économiser l'espace
            self.tabifyDockWidget(self.config_dock, self.help_dock)
            
            # Mettre Config en avant par défaut
            self.config_dock.raise_()
            
            # === REDIMENSIONNEMENT INTELLIGENT ===
            
            # Calculer les tailles optimales selon la taille de fenêtre
            window_width = self.width()
            window_height = self.height()
            
            # Proportions optimales
            source_width = int(window_width * 0.25) # 25% pour sources
            config_height = int(window_height * 0.55) # 55% pour config
            log_height = int(window_height * 0.35) # 35% pour log
            
            # Appliquer les tailles avec gestion d'erreur
            QTimer.singleShot(50, lambda: self._apply_intelligent_sizing(
                source_width, config_height, log_height))
            
            # === VISIBILITÉ ET ACTIVATION ===
            for dock in [self.source_dock, self.config_dock, self.log_dock, self.help_dock]:
                if dock:
                    dock.setVisible(True)
                    dock.activateWindow() # S'assurer que le dock est actif
            
            # === CONFIGURATION FINALE ===
            # Activer la sauvegarde automatique des positions
            self.setDockNestingEnabled(True) if hasattr(self, 'setDockNestingEnabled') else None
            
            log_info("Dock layout configured with intelligent positioning")
                
        except Exception as e:
            log_error(f"Error arranging fluid layout: {str(e)}")
    
    def _apply_intelligent_sizing(self, source_width, config_height, log_height):
        """Apply intelligent sizing to dock widgets with error handling"""
        try:
            # === REDIMENSIONNEMENT HORIZONTAL ===
            # Réduire la largeur du panneau source pour plus d'espace central
            if self.source_dock and self.source_dock.isVisible():
                try:
                    self.resizeDocks([self.source_dock], [source_width], _Orientation.Horizontal)
                except Exception as e:
                    log_error(f"Error resizing source dock horizontally: {str(e)}")
            
            # === REDIMENSIONNEMENT VERTICAL ===
            # Optimiser la répartition config/log
            docks_to_resize = []
            heights = []
            
            if self.config_dock and self.config_dock.isVisible():
                docks_to_resize.append(self.config_dock)
                heights.append(config_height)
            
            if self.log_dock and self.log_dock.isVisible():
                docks_to_resize.append(self.log_dock)
                heights.append(log_height)
            
            if docks_to_resize:
                try:
                    self.resizeDocks(docks_to_resize, heights, _Orientation.Vertical)
                except Exception as e:
                    log_error(f"Error resizing docks vertically: {str(e)}")
            
            # === OPTIMISATIONS SUPPLÉMENTAIRES ===
            
            # S'assurer que les splitters sont visibles et redimensionnables
            for dock in [self.source_dock, self.config_dock, self.log_dock, self.help_dock]:
                if dock and dock.isVisible():
                    try:
                        # Optimiser la politique de taille
                        dock.setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Preferred)
                        
                        # S'assurer que le widget interne peut se redimensionner
                        widget = dock.widget()
                        if widget:
                            widget.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)
                            
                    except Exception as e:
                        log_error(f"Error optimizing dock {dock.objectName()}: {str(e)}")
            
            log_info(f"Applied intelligent sizing - Source: {source_width}px, Config: {config_height}px, Log: {log_height}px")
            
        except Exception as e:
            log_error(f"Error applying intelligent sizing: {str(e)}")
    
    def _finalize_dock_setup(self):
        """Finalize dock setup with QGIS-native features and repositioning enhancements"""
        try:
            # === VÉRIFICATIONS FINALES ===
            all_docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            
            for dock in all_docks:
                if dock:
                    # S'assurer que toutes les fonctionnalités sont activées
                    dock.setFeatures(
                        _DockWidgetFeature.DockWidgetMovable |
                        _DockWidgetFeature.DockWidgetFloatable |
                        _DockWidgetFeature.DockWidgetClosable
                    )
                    dock.setAllowedAreas(_DockWidgetArea.AllDockWidgetAreas)
                    
                    # Vérifier la visibilité et l'état actif
                    if not dock.isVisible():
                        dock.setVisible(True)
                    if not dock.isEnabled():
                        dock.setEnabled(True)
                    
                    # PAS de propriétés custom qui bloquent les drop zones natives !
                    # dock.setProperty("dragEnabled", True) # <- Qt le fait déjà
                    # dock.setAttribute(Qt.WA_Hover, True) # <- Peut interférer
            
            # === CONFIGURATION NATIVE QT COMME QGIS ===
            
            # S'assurer que les options sont exactement comme QGIS (PAS ForceTabbedDocks !)
            current_options = self.dockOptions()
            if not (current_options & _DockOption.GroupedDragging):
                self.setDockOptions(
                    _DockOption.AnimatedDocks | 
                    _DockOption.AllowNestedDocks | 
                    _DockOption.AllowTabbedDocks |
                    _DockOption.GroupedDragging
                )
            
            # Activer les fonctionnalités de redimensionnement avancé
            if hasattr(self, 'setDockNestingEnabled'):
                self.setDockNestingEnabled(True)
            
            # === OPTIMISATIONS DE PERFORMANCE ===
            
            # Créer des splitters redimensionnables
            for dock in all_docks:
                if dock and dock.isVisible():
                    try:
                        # Optimiser les widgets internes pour le redimensionnement
                        widget = dock.widget()
                        if widget and hasattr(widget, 'setSizePolicy'):
                            widget.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)
                        
                        # S'assurer que le dock peut être redimensionné
                        dock.setMinimumSize(200, 150)
                        dock.setMaximumSize(16777215, 16777215) # Pas de limite max
                        
                    except Exception as e:
                        log_error(f"Error optimizing dock {dock.objectName()}: {str(e)}")
            
            # === FINALISATION ===
            
            # Configurer les menus contextuels pour repositionnement
            self._setup_dock_context_menus()
            
            # Vérifier que le layout est stable
            self.update()
            
            # Test final : vérifier que les drop zones natives fonctionnent
            self._validate_native_drop_zones()
            
            # === RACCOURCIS CLAVIER ===
            # Configurer les raccourcis maintenant que tous les docks sont initialisés
            self._setup_dock_shortcuts()
            
            # Message de confirmation
            log_info("Dock system finalized with QGIS native repositioning, resizing features, context menus, and keyboard shortcuts")
            
        except Exception as e:
            log_error(f"Error finalizing dock setup: {str(e)}")
    
    def _validate_native_drop_zones(self):
        """Validate that Qt native drop zones are properly configured"""
        try:
            # Vérifier les options critiques
            options = self.dockOptions()
            
            required_options = [
                (_DockOption.AllowNestedDocks, "AllowNestedDocks"),
                (_DockOption.AllowTabbedDocks, "AllowTabbedDocks"),
                (_DockOption.AnimatedDocks, "AnimatedDocks"),
                (_DockOption.GroupedDragging, "GroupedDragging")
            ]
            
            missing_options = []
            for option, name in required_options:
                if not (options & option):
                    missing_options.append(name)
            
            if missing_options:
                log_error(f"Missing dock options for native drop zones: {', '.join(missing_options)}")
            
            # Vérifier que ForceTabbedDocks n'est PAS activé (bloquerait les drop zones)
            if options & _DockOption.ForceTabbedDocks:
                log_error("WARNING: ForceTabbedDocks is enabled - this blocks native drop zones!")
                # Corriger automatiquement
                corrected_options = options & ~_DockOption.ForceTabbedDocks
                self.setDockOptions(corrected_options)
                log_info("ForceTabbedDocks removed - native drop zones should now work")
            
            # Vérifier les features des docks
            all_docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            for dock in all_docks:
                if dock:
                    features = dock.features()
                    if not (features & _DockWidgetFeature.DockWidgetMovable):
                        log_error(f"Dock {dock.objectName()} is not movable - drag & drop won't work!")
            
            log_info("Native Qt drop zones validation completed - should work like QGIS now")
            
        except Exception as e:
            log_error(f"Error validating native drop zones: {str(e)}")
    
    def save_dock_state(self):
        """Save current dock positions and sizes for restoration"""
        try:
            # Utiliser le système QSettings natif de Qt/QGIS
            from qgis.core import QgsSettings
            
            settings = QgsSettings()
            settings.beginGroup("transformer_plugin")
            
            # Sauvegarder l'état complet des docks (positions, tailles, visibilité)
            dock_state = self.saveState()
            settings.setValue("dock_state", dock_state)
            
            # Sauvegarder la géométrie de la fenêtre
            settings.setValue("window_geometry", self.saveGeometry())
            
            # Sauvegarder les positions individuelles pour debug
            for dock_name in ['source_dock', 'config_dock', 'log_dock', 'help_dock']:
                dock = getattr(self, dock_name, None)
                if dock:
                    settings.setValue(f"{dock_name}_visible", dock.isVisible())
                    settings.setValue(f"{dock_name}_floating", dock.isFloating())
                    if dock.isFloating():
                        settings.setValue(f"{dock_name}_floating_geometry", dock.geometry())
            
            settings.endGroup()
            log_info("Dock positions and window state saved")
            
        except Exception as e:
            log_error(f"Error saving dock state: {str(e)}")
    
    def restore_dock_state(self):
        """Restore previously saved dock positions and sizes"""
        try:
            from qgis.core import QgsSettings
            
            settings = QgsSettings()
            settings.beginGroup("transformer_plugin")
            
            # Restaurer l'état complet des docks
            dock_state = settings.value("dock_state")
            if dock_state:
                self.restoreState(dock_state)
                log_info("Dock state restored from previous session")
            
            # Restaurer la géométrie de la fenêtre
            window_geometry = settings.value("window_geometry")
            if window_geometry:
                self.restoreGeometry(window_geometry)
            
            # Fallback: vérifier la visibilité individuelle
            for dock_name in ['source_dock', 'config_dock', 'log_dock', 'help_dock']:
                dock = getattr(self, dock_name, None)
                if dock:
                    visible = settings.value(f"{dock_name}_visible", True, type=bool)
                    dock.setVisible(visible)
            
        except Exception as e:
            log_error(f"Error setting up dock styling: {str(e)}")

    def closeEvent(self, event):
        """Override close event to save dock positions automatically"""
        try:
            # Sauvegarder automatiquement les positions avant fermeture
            self.save_dock_state()
            
            # Appeler la méthode parent pour fermer proprement
            super().closeEvent(event)
            
        except Exception as e:
            log_error(f"Error during close event: {str(e)}")
            # S'assurer que la fenêtre se ferme même en cas d'erreur
            event.accept()
    
    def showEvent(self, event):
        """Override show event to restore dock positions when window opens"""
        try:
            # Appeler la méthode parent d'abord
            super().showEvent(event)

            self.ensure_project_layer_signals()
            QTimer.singleShot(100, self.sync_layers_from_project)
            
            # Restaurer les positions des docks après affichage
            if hasattr(self, 'source_dock'): # S'assurer que les docks sont créés
                QTimer.singleShot(200, self.restore_dock_state)
            
        except Exception as e:
            log_error(f"Error during show event: {str(e)}")
    
    def reset_dock_layout(self):
        """Reset all docks to default positions and sizes"""
        try:
            # Supprimer la configuration sauvegardée
            from qgis.core import QgsSettings
            settings = QgsSettings()
            settings.beginGroup("transformer_plugin")
            settings.remove("dock_state")
            settings.remove("window_geometry")
            settings.endGroup()
            
            # Appliquer le layout par défaut
            self._layout_default()
            
            log_info("Dock layout reset to default configuration")
            
        except Exception as e:
            log_error(f"Error resetting dock layout: {str(e)}")
    
    def move_dock_to_area(self, dock_name, area):
        """Move a specific dock to a different area programmatically"""
        try:
            dock = getattr(self, dock_name, None)
            if not dock:
                log_error(f"Dock '{dock_name}' not found")
                return False
            
            # Convertir l'area si nécessaire
            area_map = {
                'left': _DockWidgetArea.LeftDockWidgetArea,
                'right': _DockWidgetArea.RightDockWidgetArea,
                'top': _DockWidgetArea.TopDockWidgetArea,
                'bottom': _DockWidgetArea.BottomDockWidgetArea
            }
            
            if isinstance(area, str):
                area = area_map.get(area.lower(), area)
            
            # Déplacer le dock
            self.addDockWidget(area, dock)
            dock.setVisible(True)
            
            log_info(f"Dock '{dock_name}' moved to {area}")
            return True
            
        except Exception as e:
            log_error(f"Error moving dock '{dock_name}': {str(e)}")
            return False
    
    def resize_dock_to_percentage(self, dock_name, width_percent=None, height_percent=None):
        """Resize a dock to a percentage of the window size"""
        try:
            dock = getattr(self, dock_name, None)
            if not dock:
                log_error(f"Dock '{dock_name}' not found")
                return False
            
            window_size = self.size()
            
            # Calculer les nouvelles tailles
            new_width = int(window_size.width() * width_percent / 100) if width_percent else dock.width()
            new_height = int(window_size.height() * height_percent / 100) if height_percent else dock.height()
            
            # Appliquer le redimensionnement
            if width_percent:
                self.resizeDocks([dock], [new_width], _Orientation.Horizontal)
            if height_percent:
                self.resizeDocks([dock], [new_height], _Orientation.Vertical)
            
            log_info(f"Dock '{dock_name}' resized - Width: {new_width}px, Height: {new_height}px")
            return True
            
        except Exception as e:
            log_error(f"Error resizing dock '{dock_name}': {str(e)}")
            return False
    
    def toggle_dock_floating(self, dock_name):
        """Toggle a dock between docked and floating state"""
        try:
            dock = getattr(self, dock_name, None)
            if not dock:
                log_error(f"Dock '{dock_name}' not found")
                return False
            
            # Basculer l'état flottant
            dock.setFloating(not dock.isFloating())
            
            state = "floating" if dock.isFloating() else "docked"
            log_info(f"Dock '{dock_name}' is now {state}")
            return True
            
        except Exception as e:
            log_error(f"Error toggling dock '{dock_name}' floating state: {str(e)}")
            return False
    
    def reset_dock_layout(self):
        """Reset all dock widgets to their default positions"""
        try:
            # Réinitialiser à la configuration par défaut
            # D'abord, s'assurer que tous les docks sont visibles et ancrés
            all_docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            
            for dock in all_docks:
                if dock:
                    dock.setVisible(True)
                    dock.setFloating(False)
            
            # Supprimer tous les dock widgets du layout
            for dock in all_docks:
                if dock:
                    self.removeDockWidget(dock)
            
            # Réapliquer l'arrangement par défaut
            self._arrange_fluid_layout()
            self._apply_intelligent_sizing()
            
            self.log_message("Dock layout reset to default configuration", "Success")
            
        except Exception as e:
            log_error(f"Error resetting dock layout: {str(e)}")
    
    def toggle_all_docks(self):
        """Toggle visibility of all dock widgets"""
        try:
            all_docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            
            # Déterminer l'action : si au moins un dock est visible, cacher tous, sinon afficher tous
            visible_count = sum(1 for dock in all_docks if dock and dock.isVisible())
            show_all = visible_count == 0
            
            for dock in all_docks:
                if dock:
                    dock.setVisible(show_all)
            
            action = "shown" if show_all else "hidden"
            self.log_message(f" All dock widgets {action}", "Info")
            
        except Exception as e:
            log_error(f"Error toggling all docks visibility: {str(e)}")
    
    def _setup_dock_shortcuts(self):
        """Setup keyboard shortcuts for dock repositioning and management"""
        try:
            # Vérifier que les docks existent avant de configurer les raccourcis
            dock_mapping = {
                'F1': 'help_dock',
                'F2': 'source_dock', 
                'F3': 'config_dock',
                'F4': 'log_dock'
            }
            
            # Vérifier l'existence des docks
            missing_docks = []
            for key, dock_name in dock_mapping.items():
                dock = getattr(self, dock_name, None)
                if not dock:
                    missing_docks.append(dock_name)
                    log_error(f"Dock '{dock_name}' not found for shortcut {key}")
            
            if missing_docks:
                log_error(f"Cannot setup shortcuts - missing docks: {missing_docks}")
                return
            
            # Configurer les raccourcis pour les docks
            for key, dock_name in dock_mapping.items():
                try:
                    shortcut = QShortcut(QKeySequence(key), self)
                    shortcut.setContext(ApplicationShortcut) # Assure le contexte global
                    
                    # Créer une fonction de callback spécifique
                    def make_toggle_callback(dn):
                        return lambda: self._toggle_dock_visibility(dn)
                    
                    shortcut.activated.connect(make_toggle_callback(dock_name))
                    
                    # Ajouter tooltip avec le raccourci
                    dock = getattr(self, dock_name)
                    current_tooltip = dock.toolTip()
                    new_tooltip = f"{current_tooltip}\n\nShortcut: {key}" if current_tooltip else f"Shortcut: {key}"
                    dock.setToolTip(new_tooltip)
                    
                    log_info(f"Shortcut {key} configured for {dock_name}")
                    
                except Exception as e:
                    log_error(f"Error creating shortcut {key} for {dock_name}: {str(e)}")
            
            # Raccourcis spéciaux
            special_shortcuts = {
                'F9': ('Reset dock layout to default', self.reset_dock_layout),
                'F10': ('Save current dock layout', self.save_dock_state),
                'F11': ('Toggle all docks visibility', self._toggle_all_docks_visibility)
            }
            
            for key, (description, callback) in special_shortcuts.items():
                try:
                    shortcut = QShortcut(QKeySequence(key), self)
                    shortcut.setContext(ApplicationShortcut)
                    shortcut.activated.connect(callback)
                    log_info(f"Special shortcut {key} configured: {description}")
                except Exception as e:
                    log_error(f"Error creating special shortcut {key}: {str(e)}")
            
            log_info("All dock keyboard shortcuts configured successfully")
            
        except Exception as e:
            log_error(f"Error setting up dock shortcuts: {str(e)}")
    
    def _toggle_dock_visibility(self, dock_name):
        """Toggle visibility of a specific dock"""
        try:
            log_info(f"Attempting to toggle visibility of dock '{dock_name}'")
            dock = getattr(self, dock_name, None)
            if dock:
                current_state = dock.isVisible()
                dock.setVisible(not current_state)
                new_state = dock.isVisible()
                state_text = "visible" if new_state else "hidden"
                log_info(f"Dock '{dock_name}' toggled: {current_state} -> {new_state} ({state_text})")
                
                # Forcer la mise à jour de l'affichage
                dock.raise_()
                if new_state:
                    dock.activateWindow()
                self.update()
            else:
                log_error(f"Dock '{dock_name}' not found - cannot toggle visibility")
        except Exception as e:
            log_error(f"Error toggling visibility of dock '{dock_name}': {str(e)}")
    
    def _toggle_all_docks_visibility(self):
        """Toggle visibility of all docks at once"""
        try:
            all_docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            
            # Vérifier si au moins un dock est visible
            any_visible = any(dock and dock.isVisible() for dock in all_docks)
            
            # Si au moins un est visible, cacher tous, sinon afficher tous
            for dock in all_docks:
                if dock:
                    dock.setVisible(not any_visible)
            
            state = "visible" if not any_visible else "hidden"
            log_info(f"All docks are now {state}")
            
        except Exception as e:
            log_error(f"Error toggling all docks visibility: {str(e)}")
    
    def _setup_dock_context_menus(self):
        """Setup context menus for dock widgets to facilitate repositioning"""
        try:
            all_docks = {
                'source_dock': 'Source Files',
                'config_dock': 'Configuration Preview',
                'log_dock': 'Activity Monitor',
                'help_dock': 'Quick Help'
            }
            
            for dock_name, dock_title in all_docks.items():
                dock = getattr(self, dock_name, None)
                if dock:
                    self._add_context_menu_to_dock(dock, dock_name, dock_title)
            
            log_info("Context menus added to all docks")
            
        except Exception as e:
            log_error(f"Error setting up dock context menus: {str(e)}")
    
    def _add_context_menu_to_dock(self, dock, dock_name, dock_title):
        """Add a context menu to a specific dock widget"""
        try:
            # Activer le menu contextuel
            dock.setContextMenuPolicy(CustomContextMenu)
            dock.customContextMenuRequested.connect(
                lambda pos, dn=dock_name, dt=dock_title: self._show_dock_context_menu(pos, dock, dn, dt)
            )
            
        except Exception as e:
            log_error(f"Error adding context menu to dock '{dock_name}': {str(e)}")
    
    def _show_dock_context_menu(self, position, dock, dock_name, dock_title):
        """Show context menu for dock repositioning and management"""
        try:
            menu = QMenu(f"{dock_title} Options", self)
            
            # === ACTIONS DE POSITIONNEMENT ===
            move_menu = QMenu("Move to Area", menu)
            move_menu.setIcon(ui_icon("move"))
            
            areas = [
                ('Left', _DockWidgetArea.LeftDockWidgetArea),
                ('Right', _DockWidgetArea.RightDockWidgetArea),
                ('Top', _DockWidgetArea.TopDockWidgetArea),
                ('Bottom', _DockWidgetArea.BottomDockWidgetArea)
            ]
            
            for area_name, area_const in areas:
                action = QAction(f"Move to {area_name}", move_menu)
                action.triggered.connect(
                    lambda checked, area=area_const: self.move_dock_to_area(dock_name, area)
                )
                move_menu.addAction(action)
            
            menu.addMenu(move_menu)
            
            # === ACTIONS DE REDIMENSIONNEMENT ===
            resize_menu = QMenu("Resize", menu)
            resize_menu.setIcon(ui_icon("resize"))
            
            resize_options = [
                ('Small (20%)', 20, 20),
                ('Medium (30%)', 30, 30),
                ('Large (40%)', 40, 40),
                ('Extra Large (50%)', 50, 50)
            ]
            
            for size_name, width_pct, height_pct in resize_options:
                action = QAction(size_name, resize_menu)
                action.triggered.connect(
                    lambda checked, w=width_pct, h=height_pct: 
                    self.resize_dock_to_percentage(dock_name, w, h)
                )
                resize_menu.addAction(action)
            
            menu.addMenu(resize_menu)
            menu.addSeparator()
            
            # === ACTIONS GÉNÉRALES ===
            
            # Flottant/Ancré
            float_text = "Dock" if dock.isFloating() else "Float"
            float_action = QAction(f"{float_text} Window", menu)
            float_action.setIcon(ui_icon("float"))
            float_action.triggered.connect(lambda: self.toggle_dock_floating(dock_name))
            menu.addAction(float_action)
            
            # Masquer/Afficher
            visibility_text = "Hide" if dock.isVisible() else "Show"
            visibility_action = QAction(f"{visibility_text} Panel", menu)
            visibility_action.setIcon(ui_icon("show_all_layers"))
            visibility_action.triggered.connect(lambda: self._toggle_dock_visibility(dock_name))
            menu.addAction(visibility_action)
            
            menu.addSeparator()
            
            # === ACTIONS DE LAYOUT ===
            layout_action = QAction("Reset All Docks Layout", menu)
            layout_action.setIcon(ui_icon("refresh"))
            layout_action.triggered.connect(self.reset_dock_layout)
            menu.addAction(layout_action)
            
            save_action = QAction("Save Current Layout", menu)
            save_action.setIcon(ui_icon("save"))
            save_action.triggered.connect(self.save_dock_state)
            menu.addAction(save_action)
            
            # Afficher le menu à la position du clic
            global_pos = dock.mapToGlobal(position)
            menu.exec(global_pos)
            
        except Exception as e:
            log_error(f"Error showing context menu for dock '{dock_name}': {str(e)}")

    def _debug_dock_properties(self):
        """Debug dock properties to identify drag & drop issues"""
        try:
            docks = {
                'Vector Sources': self.source_dock,
                'Configuration Preview': self.config_dock,
                'Activity Monitor': self.log_dock,
                'Quick Help': self.help_dock
            }
            
            for name, dock in docks.items():
                if dock:
                    features = dock.features()
                    areas = dock.allowedAreas()
                    
                    movable = bool(features & _DockWidgetFeature.DockWidgetMovable)
                    floatable = bool(features & _DockWidgetFeature.DockWidgetFloatable)
                    closable = bool(features & _DockWidgetFeature.DockWidgetClosable)
                    
                    self.log_message(f"DEBUG {name}: Movable={movable}, Floatable={floatable}, Closable={closable}")
                    self.log_message(f"DEBUG {name}: Allowed areas={areas}, Visible={dock.isVisible()}, Enabled={dock.isEnabled()}")
                else:
                    self.log_message(f"DEBUG {name}: DOCK IS NULL!")
                    
            # Debug main window dock options
            options = self.dockOptions()
            animated = bool(options & _DockOption.AnimatedDocks)
            nested = bool(options & _DockOption.AllowNestedDocks)
            tabbed = bool(options & _DockOption.AllowTabbedDocks)
            grouped = bool(options & _DockOption.GroupedDragging)
            
            self.log_message(f"DEBUG MainWindow: Animated={animated}, Nested={nested}, Tabbed={tabbed}, Grouped={grouped}")
            
        except Exception as e:
            self.log_message(f"DEBUG ERROR: {str(e)}")
    
    def _finalize_dock_setup(self):
        """Finalize dock setup - Qt native system handles the rest"""
        try:
            # S'assurer que tous les docks sont visibles et activés
            docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            
            for dock in docks:
                if dock:
                    # S'assurer que le dock est visible et activé
                    dock.setVisible(True)
                    dock.setEnabled(True)
                    
                    # Vérifier les features - Qt gère automatiquement le drag & drop
                    features = dock.features()
                    if not (features & _DockWidgetFeature.DockWidgetMovable):
                        dock.setFeatures(
                            _DockWidgetFeature.DockWidgetMovable |
                            _DockWidgetFeature.DockWidgetFloatable |
                            _DockWidgetFeature.DockWidgetClosable
                        )
            
            # Message de succès
            
            # Forcer une mise à jour de l'interface
            self.update()
            
        except Exception as e:
            self.log_message(f"Error in dock finalization: {str(e)}")
    
    def _force_dock_drop_zones(self):
        """Force activation of dock drop zones"""
        try:
            # Forcer la mise à jour du layout
            self.update()
            
            # S'assurer que tous les docks sont correctement enregistrés
            docks = [self.source_dock, self.config_dock, self.log_dock, self.help_dock]
            
            for dock in docks:
                if dock:
                    # Forcer la mise à jour des propriétés
                    dock.update()
                    
                    # Réactiver les fonctionnalités si elles ont été désactivées
                    current_features = dock.features()
                    if not (current_features & _DockWidgetFeature.DockWidgetMovable):
                        dock.setFeatures(
                            _DockWidgetFeature.DockWidgetMovable |
                            _DockWidgetFeature.DockWidgetFloatable
                        )
                        self.log_message(f"FIXED: Re-enabled features for {dock.windowTitle()}")
            
            # Forcer la recalculation du layout du QMainWindow
            QTimer.singleShot(100, self._delayed_layout_update)
            
        except Exception as e:
            self.log_message(f"ERROR forcing dock drop zones: {str(e)}")
    
    def _delayed_layout_update(self):
        """Delayed layout update to ensure proper dock zone activation"""
        try:
            # Forcer une mise à jour complète du layout
            self.centralWidget().update()
            self.update()
            
            # Log de confirmation
            self.log_message("Layout update completed - dock drop zones should now be active")
            
        except Exception as e:
            self.log_message(f"ERROR in delayed layout update: {str(e)}")
    
    # Méthodes d'overlay supprimées - on utilise le système Qt natif
    
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
        
        # Removed Load Vector Files - working with QGIS layers only
        
        refresh_action = QAction(ui_icon("refresh"), "Refresh", self)
        refresh_action.triggered.connect(self.refresh_shapefile_list)
        toolbar.addAction(refresh_action)
        
        remove_action = QAction(ui_icon("remove"), "Remove", self)
        remove_action.triggered.connect(self.remove_selected_shapefile)
        toolbar.addAction(remove_action)
        
        # Bouton Duplicate Configuration
        self.duplicate_action = QAction(ui_icon("duplicate"), "Duplicate Configuration", self)
        self.duplicate_action.triggered.connect(self.duplicate_current_configuration)
        self.duplicate_action.setEnabled(False) # Désactivé par défaut
        toolbar.addAction(self.duplicate_action)
        
        toolbar_layout.addWidget(toolbar)
        toolbar_layout.addStretch() # Stretch to right align toolbar
        
        layout.addLayout(toolbar_layout)
        
        # Shapefiles list with detailed information
        self.shp_tree = QTreeWidget()
        self.shp_tree.setHeaderLabels(["File", "Features", "Type", "CRS"])
        self.shp_tree.setAlternatingRowColors(True)
        self.shp_tree.setRootIsDecorated(False)
        self.shp_tree.setSelectionMode(_SelectionMode.ExtendedSelection) # Enable multiple selection
        
        # Configure columns
        header = self.shp_tree.header()
        header.resizeSection(0, 180)
        header.resizeSection(1, 80)
        header.resizeSection(2, 80)
        header.setStretchLastSection(True)
        
        layout.addWidget(self.shp_tree)
        
        # Legend removed - no longer needed since we only show QGIS layers automatically
        
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
        crs_font = self.current_crs_label.font()
        crs_font.setBold(True)
        self.current_crs_label.setFont(crs_font)
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
        tcrs_font = self.target_crs_label.font()
        tcrs_font.setBold(True)
        self.target_crs_label.setFont(tcrs_font)
        reprojection_layout.addWidget(self.target_crs_label)
        
        # List of recently used CRS
        favorites_layout = QHBoxLayout()
        favorites_layout.addWidget(QLabel("Quick Access:"))
        
        # Recent CRS buttons (dynamically created)
        self.quick_crs_buttons = []
        self.recent_crs_list = [] # List of recently used CRS
        
        # Create empty buttons that will be filled dynamically
        for i in range(4): # Maximum 4 recent buttons
            btn = QPushButton("---")
            btn.setMaximumWidth(80)
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
        """Create the configuration preview widget with modern styling"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        # Preview toolbar with modern icons
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(_ToolButtonStyle.ToolButtonTextBesideIcon)
        
        validate_action = QAction("Validate", self)
        validate_action.setIcon(ui_icon("validate"))
        validate_action.setToolTip("Validate current configuration")
        validate_action.triggered.connect(self.validate_configuration)
        toolbar.addAction(validate_action)
        self._preview_validate_action = validate_action
        
        save_action = QAction("Save Current", self)
        save_action.setIcon(ui_icon("save"))
        save_action.setToolTip("Save current configuration shown in preview")
        save_action.triggered.connect(self.save_current_table_config)
        toolbar.addAction(save_action)
        
        test_action = QAction("Test", self)
        test_action.setIcon(ui_icon("play"))
        test_action.setToolTip("Test current configuration")
        test_action.triggered.connect(self.test_configuration)
        toolbar.addAction(test_action)
        
        toolbar.addSeparator()
        
        apply_changes_action = QAction("Apply Changes", self)
        apply_changes_action.setIcon(ui_icon("refresh"))
        apply_changes_action.setToolTip("Apply manual JSON changes to configuration")
        apply_changes_action.triggered.connect(self.apply_json_changes)
        toolbar.addAction(apply_changes_action)
        
        layout.addWidget(toolbar)
        
        # JSON preview with syntax highlighting
        preview_label = QLabel("Configuration Preview:")
        pv_font = preview_label.font()
        pv_font.setBold(True)
        preview_label.setFont(pv_font)
        layout.addWidget(preview_label)
        
        self.config_preview = QPlainTextEdit()
        self.config_preview.setReadOnly(False) # Allow direct editing
        self.config_preview.setFont(QFont("Consolas", 9))
        
        # Configuration pour redimensionnement fluide et maximisation de l'espace
        self.config_preview.setMinimumHeight(120) # Hauteur minimum pour bonne lisibilité
        self.config_preview.setMinimumWidth(200) # Largeur minimum pour éviter les problèmes
        # Pas de hauteur maximum pour permettre l'expansion complète
        
        # Politique de taille optimisée pour expansion maximale
        self.config_preview.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Expanding)
        
        # Options de scrolling fluides
        self.config_preview.setHorizontalScrollBarPolicy(_ScrollBarPolicy.ScrollBarAsNeeded)
        self.config_preview.setVerticalScrollBarPolicy(_ScrollBarPolicy.ScrollBarAsNeeded)
        self.config_preview.setLineWrapMode(WrapWidgetWidth) # Retour à la ligne automatique
        
        self.config_preview.setPlaceholderText("Edit configuration JSON directly here...")
        
        # Add with stretch factor maximal pour utiliser tout l'espace disponible
        layout.addWidget(self.config_preview, 1) # stretch factor = 1 pour expansion maximale
        
        # Enhanced statistics - Compact version to save space
        stats_group = QGroupBox("Statistics")
        stats_group.setMaximumHeight(85) # Limite la hauteur pour économiser l'espace
        stats_layout = QFormLayout()
        stats_layout.setVerticalSpacing(4) # Espacement réduit
        stats_layout.setContentsMargins(8, 6, 8, 6) # Marges réduites
        
        self.total_fields_label = QLabel("0")
        sf = self.total_fields_label.font()
        sf.setBold(True)
        self.total_fields_label.setFont(sf)
        
        self.total_tables_label = QLabel("0")
        st = self.total_tables_label.font()
        st.setBold(True)
        self.total_tables_label.setFont(st)
        
        self.filter_status_label = QLabel("Disabled")
        sfl = self.filter_status_label.font()
        sfl.setBold(True)
        self.filter_status_label.setFont(sfl)
        
        stats_layout.addRow("Fields:", self.total_fields_label)
        stats_layout.addRow("Tables:", self.total_tables_label)
        stats_layout.addRow("Filter:", self.filter_status_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group, 0) # Pas de stretch pour les statistiques
        
        # Enhanced action buttons - Compact version to save space
        actions_group = QGroupBox("Transform Actions")
        actions_group.setMaximumHeight(72)
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(4) # Espacement réduit entre les boutons
        actions_layout.setContentsMargins(8, 6, 8, 6) # Marges réduites
        
        self.transform_selected_btn = QPushButton("Transform Selected")
        self.transform_selected_btn.setIcon(ui_icon("transform"))
        apply_compact_button(self.transform_selected_btn)
        self.transform_selected_btn.clicked.connect(self.transform_selected_shapefile)
        
        self.transform_all_btn = QPushButton("Transform All")
        self.transform_all_btn.setIcon(ui_icon("batch"))
        apply_compact_button(self.transform_all_btn)
        self.transform_all_btn.clicked.connect(self.transform_all_shapefiles)
        
        actions_layout.addWidget(self.transform_selected_btn)
        actions_layout.addWidget(self.transform_all_btn)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group, 0) # Pas de stretch pour les boutons - ils restent en bas
        
        # PAS de layout.addStretch() pour éliminer l'espace vide
        widget.setLayout(layout)
        return widget
    
    def create_logs_widget(self):
        """Create the enterprise log monitor widget (FM-style structured viewer)."""
        # Hidden legacy widget kept for compat with code paths that still write to it
        self.logs_text = QPlainTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setVisible(False)
        
        # Filter map kept for legacy compat (filter_combo no longer used)
        self.log_filters = {
            "Success": True, "Info": True, "Warning": True, "Error": True, "Panel": False,
        }
        
        # New enterprise log monitor widget, wired to the global structured logger
        self.log_monitor = LogMonitorWidget(transformer_logger=_global_logger, parent=self)
        return self.log_monitor
    

    def _help_content_styles(self):
        """Palette-aware tokens for Quick Help widgets."""
        dark = is_dark_palette(self.palette())
        if dark:
            return {
                'title': '#E8EAED',
                'body': '#BDC1C6',
                'body_muted': '#9AA0A6',
                'code': '#AECBFA',
                'divider': '#3C4043',
                'row_alt': 'rgba(255, 255, 255, 0.03)',
                'accent_1': '#8AB4F8',
                'accent_2': '#78D9EC',
                'accent_3': '#C58AF9',
                'accent_4': '#FDD663',
                'accent_5': '#F28B82',
                'tab_bg': 'transparent',
                'tab_fg': '#9AA0A6',
                'tab_selected_fg': '#E8EAED',
                'tab_indicator': '#8AB4F8',
            }
        return {
            'title': '#202124',
            'body': '#3C4043',
            'body_muted': '#5F6368',
            'code': '#174EA6',
            'divider': '#DADCE0',
            'row_alt': 'rgba(0, 0, 0, 0.03)',
            'accent_1': '#1A73E8',
            'accent_2': '#007B83',
            'accent_3': '#9334E6',
            'accent_4': '#E37400',
            'accent_5': '#D93025',
            'tab_bg': 'transparent',
            'tab_fg': '#5F6368',
            'tab_selected_fg': '#202124',
            'tab_indicator': '#1A73E8',
        }

    def _help_mono_font(self, point_size=10):
        font = QFont('Consolas')
        if not font.exactMatch():
            font = QFont('Courier New')
        font.setPointSize(point_size)
        return font

    def _help_code_row(self, code, description, styles, alternate=False):
        row = QWidget()
        bg = styles['row_alt'] if alternate else 'transparent'
        row.setStyleSheet(f"background-color: {bg}; border-radius: 6px;")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(3)

        code_label = QLabel(code)
        code_label.setFont(self._help_mono_font(10))
        code_label.setStyleSheet(f"color: {styles['code']}; background: transparent;")
        code_label.setTextInteractionFlags(TextSelectableByMouse)
        code_label.setWordWrap(True)
        layout.addWidget(code_label)

        desc_label = QLabel(description)
        desc_font = desc_label.font()
        desc_font.setPointSize(9)
        desc_label.setFont(desc_font)
        desc_label.setStyleSheet(f"color: {styles['body']}; background: transparent;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        return row

    def _help_text_row(self, html, styles, alternate=False):
        row = QWidget()
        bg = styles['row_alt'] if alternate else 'transparent'
        row.setStyleSheet(f"background-color: {bg}; border-radius: 6px;")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(0)

        label = QLabel(html)
        label.setTextFormat(RichText)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {styles['body']}; background: transparent;")
        layout.addWidget(label)
        return row

    def _help_section_widget(self, title, accent, items, styles):
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_font = title_label.font()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {accent}; background: transparent;")
        layout.addWidget(title_label)

        divider = QFrame()
        divider.setFrameShape(FrameHLine)
        divider.setStyleSheet(f"color: {styles['divider']}; background: {styles['divider']}; max-height: 1px;")
        layout.addWidget(divider)

        for index, item in enumerate(items):
            if isinstance(item, tuple):
                row = self._help_code_row(item[0], item[1], styles, alternate=index % 2 == 1)
            else:
                row = self._help_text_row(item, styles, alternate=index % 2 == 1)
            layout.addWidget(row)

        return section

    def _make_help_page(self, page_title, sections, styles):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(FrameNoFrame)
        scroll.setHorizontalScrollBarPolicy(_ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {styles['divider']};
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(18)

        title_label = QLabel(page_title)
        title_font = title_label.font()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {styles['title']}; background: transparent;")
        layout.addWidget(title_label)

        accents = [
            styles['accent_1'], styles['accent_2'], styles['accent_3'],
            styles['accent_4'], styles['accent_5'],
        ]
        for index, section in enumerate(sections):
            accent = section.get('accent', accents[index % len(accents)])
            layout.addWidget(self._help_section_widget(
                section['title'], accent, section['items'], styles,
            ))

        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _expression_help_sections(self):
        return [
            {
                'title': 'Geometry Functions',
                'items': [
                    ('area($geometry)', 'Calculate feature area'),
                    ('perimeter($geometry)', 'Calculate perimeter'),
                    ('centroid($geometry)', 'Get feature centroid'),
                    ('buffer($geometry, distance)', 'Create buffer'),
                    ('bounds($geometry)', 'Get bounding box'),
                ],
            },
            {
                'title': 'Math Functions',
                'items': [
                    ('round(value, decimals)', 'Round number'),
                    ('abs(value)', 'Absolute value'),
                    ('sqrt(value)', 'Square root'),
                    ('min(val1, val2)', 'Minimum value'),
                    ('max(val1, val2)', 'Maximum value'),
                ],
            },
            {
                'title': 'Text Functions',
                'items': [
                    ('upper(text)', 'Convert to uppercase'),
                    ('lower(text)', 'Convert to lowercase'),
                    ('concat(text1, text2)', 'Concatenate text'),
                    ('regexp_replace(text, pattern, replacement)', 'Replace with regex'),
                ],
            },
        ]

    def _filter_help_sections(self):
        return [
            {
                'title': 'Common Filters',
                'items': [
                    ('area($geometry) > 1000', 'Area greater than 1000'),
                    ('"TYPE" = \'Building\'', 'Type equals Building'),
                    ('is_valid($geometry)', 'Valid geometries only'),
                    ('"POPULATION" BETWEEN 1000 AND 5000', 'Range filter'),
                ],
            },
            {
                'title': 'Operators',
                'items': [
                    ('=, !=, <, >, <=, >=', 'Comparison operators'),
                    ('AND, OR, NOT', 'Logical operators'),
                    ('LIKE, ILIKE', 'Pattern matching (case sensitive/insensitive)'),
                    ("IN ('value1', 'value2')", 'Multiple value matching'),
                ],
            },
            {
                'title': 'Advanced Examples',
                'items': [
                    ('"NAME" ILIKE \'%house%\'', 'Contains "house" (case insensitive)'),
                    ('length($geometry) > 500 AND "TYPE" = \'Road\'', 'Combined conditions'),
                    ("touches($geometry, geom_from_wkt('POLYGON(...)'))", 'Spatial filter'),
                ],
            },
        ]

    def _processing_help_sections(self, styles):
        emphasis = styles['title']
        code = styles['code']
        return [
            {
                'title': 'Step-by-Step Process',
                'items': [
                    f'1. Load your data using the <span style="color:{emphasis}; font-weight:600;">Configuration</span> tab',
                    f'2. Transform data in the <span style="color:{emphasis}; font-weight:600;">Transformation</span> tab',
                    f'3. Export results using the <span style="color:{emphasis}; font-weight:600;">Export</span> tab',
                ],
            },
            {
                'title': 'Tips & Shortcuts',
                'items': [
                    f'Use <span style="color:{code}; font-family:Consolas,monospace;">Ctrl+Z</span> to undo changes',
                    'Right-click for context menus',
                    'Drag dock panels to reorganize your workspace',
                    'Use layout presets for different processing needs',
                ],
            },
            {
                'title': 'Layout Presets',
                'items': [
                    f'<span style="color:{emphasis}; font-weight:600;">Default:</span> Balanced layout for general use',
                    f'<span style="color:{emphasis}; font-weight:600;">Data Processing:</span> Focus on transformation tools',
                    f'<span style="color:{emphasis}; font-weight:600;">Analysis:</span> Emphasis on filters and joins',
                    f'<span style="color:{emphasis}; font-weight:600;">Export:</span> Output-focused layout',
                ],
            },
        ]

    def _help_pages_spec(self, styles):
        filter_sections = self._filter_help_sections()
        filter_sections[2]['accent'] = styles['accent_5']
        return [
            ('Expressions', 'Expression Quick Reference', self._expression_help_sections()),
            ('Filters', 'Filter Quick Reference', filter_sections),
            ('Processing', 'Processing Guide', self._processing_help_sections(styles)),
        ]

    def _style_help_tabs(self, help_tabs, styles):
        help_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: transparent;
                top: -1px;
            }}
            QTabBar::tab {{
                background: {styles['tab_bg']};
                color: {styles['tab_fg']};
                border: none;
                border-bottom: 2px solid transparent;
                border-radius: 0px;
                padding: 8px 16px;
                margin: 0 2px;
                min-width: 72px;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                color: {styles['tab_selected_fg']};
                font-weight: 600;
                border-bottom: 2px solid {styles['tab_indicator']};
            }}
            QTabBar::tab:hover:!selected {{
                color: {styles['title']};
            }}
        """)

    def _refresh_help_content(self):
        """Rebuild Quick Help pages from the active palette."""
        if not getattr(self, '_help_tabs', None):
            return
        try:
            styles = self._help_content_styles()
            current_index = max(0, self._help_tabs.currentIndex())
            pages = []
            for tab_label, page_title, sections in self._help_pages_spec(styles):
                pages.append((tab_label, self._make_help_page(page_title, sections, styles)))
            while self._help_tabs.count():
                self._help_tabs.removeTab(0)
            for tab_label, page in pages:
                self._help_tabs.addTab(page, tab_label)
            if 0 <= current_index < self._help_tabs.count():
                self._help_tabs.setCurrentIndex(current_index)
            self._style_help_tabs(self._help_tabs, styles)
        except Exception as e:
            log_error(f"Quick Help refresh failed: {e}")

    def create_help_widget(self):
        """Create the modern quick help widget"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        help_tabs = QTabWidget()
        help_tabs.setTabPosition(_TabPosition.South)
        help_tabs.setDocumentMode(True)

        self._help_tabs = help_tabs
        self._refresh_help_content()

        layout.addWidget(help_tabs)
        widget.setLayout(layout)
        return widget
    
# ... (rest of the code remains the same)
    def _create_modern_dock(self, title, object_name, widget):
        """Create a modern dock widget with enhanced properties"""
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        
        # Enable all dock features for maximum flexibility
        dock.setFeatures(
            _DockWidgetFeature.DockWidgetMovable |
            _DockWidgetFeature.DockWidgetFloatable |
            _DockWidgetFeature.DockWidgetClosable
        )
        
        # Create custom title bar with proper spacing
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(8, 3, 8, 3)
        title_layout.setSpacing(10)
        
        title_label = QLabel(title)
        tl_font = title_label.font()
        tl_font.setBold(True)
        title_label.setFont(tl_font)
        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        
        spacer = QWidget()
        spacer.setMinimumWidth(30)
        title_layout.addWidget(spacer)
        
        # Add float button
        float_btn = QPushButton("⧉")
        float_btn.setFixedSize(18, 18)
        float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        title_layout.addWidget(float_btn)
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(18, 18)
        close_btn.clicked.connect(dock.close)
        title_layout.addWidget(close_btn)
        
        dock.setTitleBarWidget(title_widget)
        
        # Allow docking in all areas
        dock.setAllowedAreas(_DockWidgetArea.AllDockWidgetAreas)
        
        return dock
    
    def _arrange_fluid_layout(self):
        """Arrange docks in modern fluid layout"""
        # Add docks to main window
        self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.help_dock)
        
        # Create vertical split: Config (top) | Activity Monitor (bottom)
        self.splitDockWidget(self.config_dock, self.log_dock, _Orientation.Vertical)
        
        # Create tab group: Configuration + Quick Help
        self.tabifyDockWidget(self.config_dock, self.help_dock)
        
        # Set default active tab (Configuration)
        self.config_dock.raise_()
    
    def _setup_dock_signals(self):
        """Setup enhanced dock signals for user feedback"""
        # Track dock movements for user feedback
        for dock in [self.source_dock, self.config_dock, self.log_dock, self.help_dock]:
            dock.dockLocationChanged.connect(
                lambda area, dock=dock: self._on_dock_moved(dock, area)
            )
            dock.visibilityChanged.connect(
                lambda visible, dock=dock: self._on_dock_visibility_changed(dock, visible)
            )
            dock.topLevelChanged.connect(
                lambda floating, dock=dock: self._on_dock_floating_changed(dock, floating)
            )
    
    def _setup_layout_presets(self):
        """Setup quick layout presets for different processing needs"""
        # This will be connected to toolbar buttons
        self.layout_presets = {
            'default': self._layout_default,
            'vertical': self._layout_vertical, 
            'horizontal': self._layout_horizontal,
            'focus_config': self._layout_focus_config,
            'focus_monitor': self._layout_focus_monitor
        }
    
    def _on_dock_moved(self, dock, area):
        """Handle dock movement with user feedback"""
        area_names = {
            _DockWidgetArea.LeftDockWidgetArea: 'Left',
            _DockWidgetArea.RightDockWidgetArea: 'Right', 
            _DockWidgetArea.TopDockWidgetArea: 'Top',
            _DockWidgetArea.BottomDockWidgetArea: 'Bottom'
        }
        area_name = area_names.get(area, 'Unknown')

    # === LAYOUT PRESETS ===
    
    def _layout_default(self):
        """Default layout: Sources left, Config+Monitor right, Help tabbed"""
        self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.splitDockWidget(self.config_dock, self.log_dock, _Orientation.Vertical)
        self.tabifyDockWidget(self.config_dock, self.help_dock)
        self.config_dock.raise_()
        self.log_message("Layout reset to default", "Success")
    
    def _layout_vertical(self):
        """Vertical layout: Config top, Monitor bottom"""
        self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
        self.addDockWidget(_DockWidgetArea.TopDockWidgetArea, self.config_dock)
        self.addDockWidget(_DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.help_dock)
        self.log_message("Applied vertical layout", "Success")
    
    def _layout_horizontal(self):
        """Horizontal layout: All panels side by side"""
        self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.help_dock)
        self.log_message("Applied horizontal layout", "Success")
    
    def _layout_focus_config(self):
        """Focus on configuration: Large config panel"""
        self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.config_dock)
        self.tabifyDockWidget(self.config_dock, self.log_dock)
        self.tabifyDockWidget(self.config_dock, self.help_dock)
        self.config_dock.raise_()
        self.log_message("Configuration focus mode activated", "Success")
    
    def _layout_focus_monitor(self):
        """Focus on monitoring: Large activity monitor"""
        self.addDockWidget(_DockWidgetArea.LeftDockWidgetArea, self.source_dock)
        self.addDockWidget(_DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.tabifyDockWidget(self.log_dock, self.config_dock)
        self.tabifyDockWidget(self.log_dock, self.help_dock)
        self.log_dock.raise_()
        self.log_message("Activity monitor focus mode activated", "Success")
    
    
    def setup_toolbar(self):
        """Configure a clean, sectioned toolbar.
        
        Sections (left to right):
        1. SOURCE     - Add layers, reload project layers
        2. DESIGN     - Validate, Save active config
        3. RUN        - Transform selected (primary), Transform all
        4. NAVIGATE   - Quick tab switch (Configuration / Export / PG)
        5. LAYOUT     - Preset menu
        Right-aligned : environment label (version) - appears on idle.
        """
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("transformer_main_toolbar")
        toolbar.setToolButtonStyle(_ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(True)
        toolbar.setFloatable(True)
        toolbar.setAllowedAreas(
            _ToolBarArea.TopToolBarArea | _ToolBarArea.LeftToolBarArea |
            _ToolBarArea.RightToolBarArea | _ToolBarArea.BottomToolBarArea
        )
        toolbar.setSizePolicy(_SizePolicy.Preferred, _SizePolicy.Preferred)
        toolbar.orientationChanged.connect(self._on_toolbar_orientation_changed)
        
        # === SECTION 1 : SOURCE =========================================
        add_layer_action = QAction(
            ui_icon("add_layer"),
            "Add Layers",
            self,
        )
        add_layer_action.setToolTip("Add vector files (Shapefile, GeoPackage, GeoJSON, KML)")
        add_layer_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        add_layer_action.triggered.connect(self.add_shapefiles_dialog)
        toolbar.addAction(add_layer_action)
        
        reload_action = QAction(
            ui_icon("refresh"),
            "Reload",
            self,
        )
        reload_action.setToolTip("Reload layers from the QGIS project (F5)")
        reload_action.setShortcut(QKeySequence("F5"))
        reload_action.triggered.connect(self._reload_project_layers)
        toolbar.addAction(reload_action)
        
        toolbar.addSeparator()
        
        # === SECTION 2 : DESIGN =========================================
        validate_action = QAction(
            ui_icon("validate"),
            "Validate",
            self,
        )
        validate_action.setToolTip("Validate the active configuration")
        validate_action.triggered.connect(self.validate_configuration)
        toolbar.addAction(validate_action)
        self._toolbar_validate_action = validate_action
        
        save_action = QAction(
            ui_icon("save"),
            "Save",
            self,
        )
        save_action.setToolTip("Save configurations of all selected vector files")
        save_action.triggered.connect(self.save_selected_configurations)
        toolbar.addAction(save_action)
        
        toolbar.addSeparator()
        
        # === SECTION 3 : RUN (primary actions) =========================
        self.transform_action = QAction(
            ui_icon("transform"),
            "Transform",
            self,
        )
        self.transform_action.setToolTip("Transform the selected vector file(s) (background task)")
        self.transform_action.triggered.connect(self.transform_selected_shapefile)
        toolbar.addAction(self.transform_action)
        
        self.batch_action = QAction(
            ui_icon("batch"),
            "Transform All",
            self,
        )
        self.batch_action.setToolTip("Transform all loaded vector files (background task)")
        self.batch_action.triggered.connect(self.transform_all_shapefiles)
        toolbar.addAction(self.batch_action)

        toolbar.addSeparator()
        
        # === SECTION 4 : LAYOUT presets ================================
        layout_preset_button = QToolButton(self)
        layout_preset_button.setText("Layouts")
        layout_preset_button.setIcon(ui_icon("layout"))
        layout_preset_button.setToolButtonStyle(_ToolButtonStyle.ToolButtonTextBesideIcon)
        layout_preset_button.setToolTip("Quick layout presets")
        layout_preset_button.setPopupMode(InstantPopup)
        
        layout_preset_menu = QMenu("Layouts", self)
        layout_preset_menu.addAction(self._mk_action("Default", self._layout_default, "Standard arrangement of all panels"))
        layout_preset_menu.addAction(self._mk_action("Vertical Stack", self._layout_vertical, "Stacked layout for wide screens"))
        layout_preset_menu.addAction(self._mk_action("Horizontal", self._layout_horizontal, "All panels side by side"))
        layout_preset_menu.addSeparator()
        layout_preset_menu.addAction(self._mk_action("Focus: Configuration", self._layout_focus_config, "Maximize the configuration area"))
        layout_preset_menu.addAction(self._mk_action("Focus: Activity Monitor", self._layout_focus_monitor, "Maximize the activity monitor"))
        
        layout_preset_button.setMenu(layout_preset_menu)
        toolbar.addWidget(layout_preset_button)
        
        # === Spacer to push environment label to the right =============
        spacer = QWidget()
        spacer.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Preferred)
        toolbar.addWidget(spacer)
        
        # === Environment label (version) ===============================
        try:
            from ..shared.compat import version_summary
            env_label = QLabel(version_summary())
            env_label.setObjectName("env_label")
            ef = env_label.font()
            ef.setPointSize(max(ef.pointSize() - 1, 8))
            env_label.setFont(ef)
            env_label.setToolTip("Runtime environment (QGIS / Qt / PyQt)")
            env_label.setContentsMargins(8, 0, 8, 0)
            toolbar.addWidget(env_label)
        except Exception as exc:
            log_warning(f"env label setup failed: {exc}")
        
        self.main_toolbar = toolbar
    

    def _on_toolbar_orientation_changed(self, orientation):
        """Adapter automatiquement le style de la toolbar selon son orientation"""
        try:
            if orientation == _Orientation.Horizontal:
                # Orientation horizontale: texte à côté des icônes
                self.main_toolbar.setToolButtonStyle(_ToolButtonStyle.ToolButtonTextBesideIcon)
                log_info("Toolbar orientation: horizontal")
            else:
                # Orientation verticale: texte sous les icônes
                self.main_toolbar.setToolButtonStyle(_ToolButtonStyle.ToolButtonTextUnderIcon)
                log_info("Toolbar orientation: vertical")
        except Exception as e:
            log_error(f"Error adapting toolbar orientation: {str(e)}")
    
    def setup_statusbar(self):
        """Configure the status bar with task indicator and counters."""
        self.status_bar = self.statusBar()
        
        # Left: status label
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label)
        
        # Left: active task indicator (hidden when idle)
        self.task_indicator = QLabel("")
        ti_font = self.task_indicator.font()
        ti_font.setItalic(True)
        self.task_indicator.setFont(ti_font)
        self.status_bar.addWidget(self.task_indicator)
        
        # Right: progress bar (used by transform tasks)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setTextVisible(True)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Right: counters
        self.stats_label = QLabel("0 tables | 0 vector files")
        self.status_bar.addPermanentWidget(self.stats_label)
        
        # Right: mode label (bold)
        self.mode_label = QLabel("Configuration Mode")
        ml2_font = self.mode_label.font()
        ml2_font.setBold(True)
        self.mode_label.setFont(ml2_font)
        self.status_bar.addPermanentWidget(self.mode_label)
    
    def set_active_task(self, name: str = ""):
        """Show or clear the active background task name in the status bar.
        
        Call with empty string to clear.
        """
        try:
            if hasattr(self, 'task_indicator'):
                self.task_indicator.setText(f"  *  {name}" if name else "")
        except Exception as exc:
            log_warning(f"update_task_indicator failed: {exc}")
    

    def setup_menubar(self):
        """Configure the menu bar with curated, useful actions only.
        
        Design rules:
        - Every action must be wired to a real handler.
        - Disabled actions for unimplemented features (clear visual signal).
        - No filler. No duplicates with toolbar without reason.
        - QGIS HIG: standard accelerators, separators between groups.
        """
        menubar = self.menuBar()
        
        # =====================================================
        # File menu
        # =====================================================
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction(ui_icon("new"), "&New Configuration", self)
        new_action.setShortcut(KeyNew)
        new_action.setStatusTip("Start a new configuration (clears current settings)")
        new_action.triggered.connect(self.new_configuration)
        file_menu.addAction(new_action)
        
        open_action = QAction(ui_icon("open"), "&Open Configuration...", self)
        open_action.setShortcut(KeyOpen)
        open_action.setStatusTip("Load a saved configuration file")
        open_action.triggered.connect(self.open_configuration)
        file_menu.addAction(open_action)
        
        save_action = QAction(ui_icon("save"), "&Save Configuration", self)
        save_action.setShortcut(KeySave)
        save_action.setStatusTip("Save the current configuration")
        save_action.triggered.connect(self.save_configuration)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        # Add layers submenu
        add_layer_action = QAction(ui_icon("add_layer"), "&Add Shapefile/Vector...", self)
        add_layer_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        add_layer_action.setStatusTip("Add one or more vector files to transform")
        add_layer_action.triggered.connect(self.add_shapefiles_dialog)
        file_menu.addAction(add_layer_action)
        
        reload_action = QAction(ui_icon("refresh"), "&Reload Project Layers", self)
        reload_action.setShortcut(QKeySequence("F5"))
        reload_action.setStatusTip("Reload layers from the current QGIS project")
        reload_action.triggered.connect(self._reload_project_layers)
        file_menu.addAction(reload_action)
        
        file_menu.addSeparator()
        
        import_action = QAction("&Import Configuration...", self)
        import_action.setStatusTip("Import a configuration from JSON")
        import_action.triggered.connect(self.import_configuration)
        file_menu.addAction(import_action)
        
        export_action = QAction("&Export Configuration...", self)
        export_action.setStatusTip("Export the current configuration as JSON")
        export_action.triggered.connect(self.export_configuration)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        close_action = QAction("&Close Window", self)
        close_action.setShortcut(QKeySequence("Ctrl+W"))
        close_action.setStatusTip("Close the Transformer window")
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)
        
        # =====================================================
        # Edit menu
        # =====================================================
        edit_menu = menubar.addMenu("&Edit")
        
        copy_config_action = QAction("&Copy Active Configuration", self)
        copy_config_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_config_action.setStatusTip("Copy active table configuration to clipboard as JSON")
        copy_config_action.triggered.connect(self._copy_active_config_to_clipboard)
        edit_menu.addAction(copy_config_action)
        
        paste_config_action = QAction("&Paste Configuration", self)
        paste_config_action.setShortcut(QKeySequence("Ctrl+V"))
        paste_config_action.setStatusTip("Paste a configuration JSON from the clipboard")
        paste_config_action.triggered.connect(self._paste_config_from_clipboard)
        edit_menu.addAction(paste_config_action)
        
        edit_menu.addSeparator()
        
        clear_fields_action = QAction("Clear All &Fields", self)
        clear_fields_action.setStatusTip("Remove all configured fields from the active table")
        clear_fields_action.triggered.connect(self._clear_all_fields)
        edit_menu.addAction(clear_fields_action)
        
        clear_filter_action = QAction("Clear &Filter", self)
        clear_filter_action.setStatusTip("Reset the smart filter for the active table")
        clear_filter_action.triggered.connect(self._clear_active_filter)
        edit_menu.addAction(clear_filter_action)
        
        edit_menu.addSeparator()
        
        preferences_action = QAction(ui_icon("preferences"), "&Preferences...", self)
        preferences_action.setShortcut(QKeySequence("Ctrl+,"))
        preferences_action.setStatusTip("Open the Preferences dialog")
        preferences_action.triggered.connect(self.show_preferences)
        edit_menu.addAction(preferences_action)
        
        # =====================================================
        # View menu
        # =====================================================
        view_menu = menubar.addMenu("&View")
        
        # Dock toggles
        for dock_attr, label in [
            ('source_dock', 'Source Files'),
            ('config_dock', 'Configuration Preview'),
            ('log_dock', 'Activity Monitor'),
            ('help_dock', 'Quick Help'),
        ]:
            dock = getattr(self, dock_attr, None)
            if dock is not None:
                view_menu.addAction(dock.toggleViewAction())
        
        view_menu.addSeparator()
        
        # Configuration components submenu
        components_menu = view_menu.addMenu("Configuration &Components")
        
        table_config_menu_action = QAction("&Table Configuration", self)
        table_config_menu_action.setCheckable(True)
        table_config_menu_action.setChecked(True)
        table_config_menu_action.setShortcut(QKeySequence("Ctrl+1"))
        table_config_menu_action.toggled.connect(lambda checked: self.toggle_component_visibility('table_config', checked))
        components_menu.addAction(table_config_menu_action)
        
        filter_menu_action = QAction("Smart &Filter", self)
        filter_menu_action.setCheckable(True)
        filter_menu_action.setChecked(True)
        filter_menu_action.setShortcut(QKeySequence("Ctrl+2"))
        filter_menu_action.toggled.connect(lambda checked: self.toggle_component_visibility('smart_filter', checked))
        components_menu.addAction(filter_menu_action)
        
        expression_menu_action = QAction("&Expression Builder", self)
        expression_menu_action.setCheckable(True)
        expression_menu_action.setChecked(True)
        expression_menu_action.setShortcut(QKeySequence("Ctrl+3"))
        expression_menu_action.toggled.connect(lambda checked: self.toggle_component_visibility('expression_builder', checked))
        components_menu.addAction(expression_menu_action)
        
        fields_menu_action = QAction("Field &Management", self)
        fields_menu_action.setCheckable(True)
        fields_menu_action.setChecked(True)
        fields_menu_action.setShortcut(QKeySequence("Ctrl+4"))
        fields_menu_action.toggled.connect(lambda checked: self.toggle_component_visibility('field_management', checked))
        components_menu.addAction(fields_menu_action)
        
        components_menu.addSeparator()
        
        show_all_components_action = QAction("Show &All Components", self)
        show_all_components_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        show_all_components_action.triggered.connect(self.show_all_components)
        components_menu.addAction(show_all_components_action)
        
        self.component_menu_actions = {
            'table_config': table_config_menu_action,
            'smart_filter': filter_menu_action,
            'expression_builder': expression_menu_action,
            'field_management': fields_menu_action,
        }
        
        view_menu.addSeparator()
        
        # Layout presets
        layout_menu = view_menu.addMenu("&Layout")
        layout_menu.addAction(self._mk_action("Default Layout", self._layout_default, "Reset docks to default arrangement"))
        layout_menu.addAction(self._mk_action("Configuration Focus", self._layout_focus_config, "Maximize the configuration area"))
        layout_menu.addAction(self._mk_action("Activity Monitor Focus", self._layout_focus_monitor, "Maximize the activity monitor"))
        layout_menu.addSeparator()
        reset_layout_action = QAction("&Reset Window Layout", self)
        reset_layout_action.setStatusTip("Reset window geometry and dock state to defaults")
        reset_layout_action.triggered.connect(self._reset_window_layout)
        layout_menu.addAction(reset_layout_action)
        
        # =====================================================
        # Tools menu
        # =====================================================
        tools_menu = menubar.addMenu("&Tools")
        
        validate_action = QAction(ui_icon("validate"), "&Validate All Configurations", self)
        validate_action.setStatusTip("Check every loaded configuration for errors")
        validate_action.triggered.connect(self.validate_all_configurations)
        tools_menu.addAction(validate_action)
        
        cleanup_action = QAction("&Cleanup Missing Sources", self)
        cleanup_action.setStatusTip("Remove configurations whose source file no longer exists")
        cleanup_action.triggered.connect(self.cleanup_missing_sources)
        tools_menu.addAction(cleanup_action)
        
        tools_menu.addSeparator()
        
        expression_tester_action = QAction(ui_icon("expression"), "Expression &Tester...", self)
        expression_tester_action.setShortcut(QKeySequence("Ctrl+T"))
        expression_tester_action.setStatusTip("Open the QGIS expression tester")
        expression_tester_action.triggered.connect(self.open_expression_tester)
        tools_menu.addAction(expression_tester_action)
        
        tools_menu.addSeparator()
        
        open_qgis_log_action = QAction("Open QGIS &Message Log", self)
        open_qgis_log_action.setStatusTip("Toggle the native QGIS Message Log panel")
        open_qgis_log_action.triggered.connect(self._open_qgis_message_log)
        tools_menu.addAction(open_qgis_log_action)
        
        # =====================================================
        # Help menu
        # =====================================================
        help_menu = menubar.addMenu("&Help")
        
        help_action = QAction(ui_icon("help"), "&Help Contents", self)
        help_action.setShortcut(KeyHelpContents)
        help_action.setStatusTip("Show plugin help")
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)
        
        report_issue_action = QAction("Report &Issue...", self)
        report_issue_action.setStatusTip("Open the project bug tracker in your browser")
        report_issue_action.triggered.connect(self._open_issue_tracker)
        help_menu.addAction(report_issue_action)
        
        help_menu.addSeparator()
        
        about_action = QAction(ui_icon("about"), "&About Transformer", self)
        about_action.setStatusTip("Show plugin version and credits")
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    # ----------------------------------------------------------
    # Menu helpers (P3)
    # ----------------------------------------------------------
    def _mk_action(self, text, slot, status_tip=None, icon=None, shortcut=None):
        """Build a QAction with sensible defaults."""
        act = QAction(text, self)
        if icon:
            if isinstance(icon, QIcon):
                act.setIcon(icon)
            else:
                act.setIcon(ui_icon(icon))
        if shortcut:
            act.setShortcut(shortcut)
        if status_tip:
            act.setStatusTip(status_tip)
        act.triggered.connect(slot)
        return act
    
    def _reload_project_layers(self):
        """Re-import vector layers from the QGIS project."""
        try:
            self.auto_load_qgis_layers()
            self.refresh_shapefile_list()
            self.log_message("Project layers reloaded", "Info")
        except Exception as e:
            self.log_message(f"Reload failed: {e}", "Error")
    
    def _copy_active_config_to_clipboard(self):
        """Copy the active table configuration as JSON to clipboard."""
        try:
            data = self.current_table_config or {}
            QApplication.clipboard().setText(json.dumps(data, indent=2, ensure_ascii=False))
            self.log_message("Configuration copied to clipboard", "Info")
        except Exception as e:
            self.log_message(f"Copy failed: {e}", "Error")
    
    def _paste_config_from_clipboard(self):
        """Paste a JSON configuration from the clipboard into active table."""
        try:
            text = QApplication.clipboard().text()
            if not text.strip():
                self.log_message("Clipboard is empty", "Warning")
                return
            data = json.loads(text)
            if not isinstance(data, dict):
                self.log_message("Clipboard content is not a JSON object", "Warning")
                return
            self.current_table_config = data
            self.log_message("Configuration pasted from clipboard", "Info")
        except json.JSONDecodeError as e:
            self.log_message(f"Invalid JSON in clipboard: {e}", "Error")
        except Exception as e:
            self.log_message(f"Paste failed: {e}", "Error")
    
    def _clear_all_fields(self):
        """Remove all configured fields from the smart fields widget."""
        try:
            if hasattr(self, 'smart_fields'):
                # Best effort: try common API names
                if hasattr(self.smart_fields, 'clear_fields'):
                    self.smart_fields.clear_fields()
                elif hasattr(self.smart_fields, 'clear'):
                    self.smart_fields.clear()
                self.log_message("All fields cleared", "Info")
        except Exception as e:
            self.log_message(f"Clear fields failed: {e}", "Error")
    
    def _clear_active_filter(self):
        """Reset the smart filter for the active table."""
        try:
            if hasattr(self, 'smart_filter'):
                if hasattr(self.smart_filter, 'reset_filter'):
                    self.smart_filter.reset_filter()
                elif hasattr(self.smart_filter, 'clear'):
                    self.smart_filter.clear()
                self.log_message("Filter cleared", "Info")
        except Exception as e:
            self.log_message(f"Clear filter failed: {e}", "Error")
    
    def _reset_window_layout(self):
        """Reset window geometry, dock state, and layout to defaults."""
        try:
            settings = QSettings("Transformer", "EnhancedDialog")
            settings.remove("window_state")
            settings.remove("window_geometry")
            self._layout_default()
            self.resize(1600, 1000)
            self.log_message("Window layout reset to defaults", "Info")
        except Exception as e:
            self.log_message(f"Reset layout failed: {e}", "Error")
    
    def _open_qgis_message_log(self):
        """Toggle the native QGIS Message Log panel."""
        try:
            from qgis.utils import iface
            if iface and hasattr(iface, 'openMessageLog'):
                iface.openMessageLog()
            else:
                # Fallback: use messageBar
                self.log_message("QGIS Message Log not available in this context", "Warning")
        except Exception as e:
            self.log_message(f"Open QGIS log failed: {e}", "Error")
    
    def _open_issue_tracker(self):
        """Open the project issue tracker in the user's browser."""
        try:
            from qgis.PyQt.QtCore import QUrl
            from qgis.PyQt.QtGui import QDesktopServices
            url = QUrl("https://github.com/yadadev/Transformer/issues")
            QDesktopServices.openUrl(url)
        except Exception as e:
            self.log_message(f"Failed to open issue tracker: {e}", "Error")
    
    def add_shapefiles_dialog(self):
        """Open file dialog to add shapefiles/vector files."""
        try:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Add vector layers",
                "",
                "Vector files (*.shp *.gpkg *.geojson *.kml);;All files (*)"
            )
            for path in files:
                try:
                    layer = QgsVectorLayer(path, os.path.basename(path), "ogr")
                    if layer.isValid():
                        QgsProject.instance().addMapLayer(layer)
                except Exception as exc:
                    self.log_message(f"Failed to load {path}: {exc}", "Error")
            if files:
                self.refresh_shapefile_list()
                self.log_message(f"{len(files)} file(s) added", "Info")
        except Exception as e:
            self.log_message(f"Add layers failed: {e}", "Error")
    

    def setup_connections(self):
        """Configure les connexions de signaux"""
        # Shapefile selection
        self.shp_tree.itemSelectionChanged.connect(self.on_shapefile_selection_changed)
        
        # Configuration changes
        self.table_name_edit.textChanged.connect(self.update_configuration_preview)
        self.table_name_edit.textChanged.connect(self.on_table_name_changed)
        self.smart_filter.filter_applied.connect(self.on_filter_changed)
        self.smart_fields.field_added.connect(self.on_field_added)
        self.smart_fields.field_removed.connect(self.on_field_removed)
        self.smart_fields.field_modified.connect(self.on_field_modified)
        
        # Tab change
        self.main_tabs.currentChanged.connect(self.on_tab_changed)
        
        # Connections with export
        self.transformation_requested.connect(self.on_transformation_completed)
        
        self.ensure_project_layer_signals()
    
    def setup_centralized_logger(self):
        """Configure le logger centralisé avec le widget Activity Log"""
        try:
            # Check if the logs text widget exists
            if hasattr(self, 'logs_text') and self.logs_text is not None:
                # Connect the logger to the Activity Log widget
                plugin_logger.set_activity_log_widget(self.logs_text)
                log_info("Centralized logger configured successfully")
                log_info(f"Logger connected to Activity Log panel: {type(self.logs_text).__name__}")
            else:
                # Fallback message to QGIS log only
                QgsMessageLog.logMessage("Activity Log widget not found - logger will only send to QGIS Message Log", "Transformer", Qgis.Warning)
                
        except Exception as e:
            error_msg = f"Error setting up centralized logger: {str(e)}"
            # Fallback to QgsMessageLog if the centralized logger fails
            QgsMessageLog.logMessage(error_msg, "Transformer", Qgis.Critical)
    
    def test_centralized_logger(self):
        """Test the centralized logger with a simple confirmation message"""
        log_info("Activity Monitor ready")
    
    def apply_theme(self):
        """Apply the selected theme.

        QGIS_NATIVE: no custom CSS, let QGIS/Qt theme drive all styling.
        PROFESSIONAL: load styles.css if present, else inline fallback.
        Other themes (LIGHT, DARK, HIGH_CONTRAST): no custom CSS for now.
        """
        try:
            theme = self.interface_settings.theme

            if theme == InterfaceTheme.QGIS_NATIVE:
                self.setStyleSheet("")
                clear_icon_cache()
                self._refresh_toolbar_icons()
                log_info("Theme: QGIS native (no custom CSS)")
                self._refresh_help_content()
                return

            if theme == InterfaceTheme.PROFESSIONAL:
                css_file = os.path.join(os.path.dirname(__file__), 'styles.css')
                if os.path.exists(css_file):
                    with open(css_file, 'r', encoding='utf-8') as f:
                        css_content = f.read()
                    self.setStyleSheet(css_content)
                    clear_icon_cache()
                    self._refresh_toolbar_icons()
                    log_info("Theme: Professional (styles.css applied)")
                else:
                    log_warning("Theme: Professional requested but styles.css not found, using native")
                    self.setStyleSheet("")
                self._refresh_help_content()
                return

            self.setStyleSheet("")
            clear_icon_cache()
            self._refresh_toolbar_icons()
            log_info(f"Theme: {theme.value} (no custom CSS, native fallback)")

            self._refresh_help_content()

        except Exception as e:
            log_error(f"Error applying theme: {str(e)}")
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
            except ValueError:
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
    
    def _apply_table_config(self, table_name: str, config: dict, filename: str = None):
        """Apply a specific table configuration only if corresponding layer exists"""
        if not config:
            return
            
        # Check if corresponding layer exists in QGIS before applying config
        source_file = config.get('source_file', filename)
        if source_file and not self._is_layer_present_in_qgis(source_file):
            self.log_message(f"Skipped loading config '{table_name}' - no corresponding layer in QGIS", "Info")
            return
            
        try:
            self.table_name_edit.setText(table_name)
            
            # Auto load calculated fields and geometry expression
            calculated_fields = config.get('calculated_fields', {})
            geometry_expression = config.get('geometry_expression', '$geometry')
            self.smart_fields.set_calculated_fields(calculated_fields, geometry_expression)
            
            # Auto load filter configuration
            filter_config = config.get('filter', {})
            self.smart_filter.set_filter_config(filter_config)
            
            # Auto load target CRS if saved
            target_crs_str = config.get('target_crs')
            if target_crs_str:
                try:
                    from qgis.core import QgsCoordinateReferenceSystem
                    target_crs = QgsCoordinateReferenceSystem(target_crs_str)
                    if target_crs.isValid():
                        crs_description = target_crs.description()
                        self.set_target_crs(target_crs_str, crs_description)
                        self.log_message(f"Restored saved CRS: {target_crs_str}", "Info")
                    else:
                        self.log_message(f"Invalid saved CRS: {target_crs_str}", "Warning")
                        self.target_crs = None
                except Exception as e:
                    self.log_message(f"Error loading saved CRS: {str(e)}", "Warning")
                    self.target_crs = None
            else:
                # No saved CRS - preserve current target_crs if user has set one
                if not hasattr(self, 'target_crs') or self.target_crs is None:
                    self.target_crs = None
            
            self.log_message(f"Loaded configuration '{table_name}'", "Info")
            self.update_configuration_preview()
            
        except Exception as e:
            self.log_message(f"Error applying config '{table_name}': {str(e)}", "Warning")
    
    def _show_config_selector(self, table_names: list, filename: str):
        """Show config selector (fallback to first configuration)"""
        try:
            # Use fallback method - load first config automatically
            first_table = table_names[0]
            config = self.config_manager.get_table_config(first_table)
            self._apply_table_config(first_table, config)
            self.log_message(f"Multiple configurations found, loaded first: '{first_table}'", "Info")
            
        except Exception as e:
            self.log_message(f"Error showing config selector: {str(e)}", "Warning")
            # Fallback to first config
            first_table = table_names[0]
            config = self.config_manager.get_table_config(first_table)
            self._apply_table_config(first_table, config)
    
    
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
        except Exception as exc:
            log_warning(f"Format detection failed for {file_path}: {exc}")
        
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
        """Refresh QGIS layers - no external file loading"""
        # This method now only refreshes QGIS layers
        self.auto_load_qgis_layers()
        self.refresh_shapefile_list()
        self.log_message("Refreshed QGIS layers", "Info")
    
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
                    f"Added {file_format}: {filename} ({geometry_info}, {crs_info})", 
                    "Info"
                )
                
                # Log additional details for complex formats
                if file_format not in ['Shapefile', 'GeoJSON']:
                    self.log_message(
                        f" Format details: {provider.storageType()}, encoding: {encoding}",
                        "Info"
                    )
                
                return True
            else:
                # Enhanced error reporting
                error_msg = "Unknown error"
                if hasattr(layer, 'error') and layer.error().message():
                    error_msg = layer.error().message()
                
                self.log_message(
                    f" Invalid vector file: {os.path.basename(file_path)} ({file_format}) - {error_msg}", 
                    "Error"
                )
                return False
                
        except Exception as e:
            self.log_message(
                f" Error loading vector file {os.path.basename(file_path)}: {str(e)}", 
                "Error"
            )
            return False
    
    def add_shapefile(self, file_path: str) -> bool:
        """Legacy method - redirects to add_vector_file for backward compatibility"""
        return self.add_vector_file(file_path)
    
    def refresh_shapefile_list(self):
        """Refresh the shapefile list with multiple configurations per source file"""
        self.shp_tree.clear()
        
        # Group configurations by source_file
        source_file_configs = self._group_configurations_by_source_file()
        
        # Display each source file with its configurations
        for source_file, configs in source_file_configs.items():
            # CRITICAL: Only show mappings if the corresponding layer exists in QGIS
            if not self._is_layer_present_in_qgis(source_file):
                # Layer not found in QGIS - skip all configurations for this source file
                continue
            
            # Get source file data from loaded_shapefiles
            data = self.loaded_shapefiles.get(source_file, {})
            
            if not data:
                # Source file not loaded, create from configuration data
                data = self._create_data_from_config(configs[0])
            
            # Only show QGIS layers and their configurations
            is_qgis_layer = data.get('is_qgis_layer', False)
            if not is_qgis_layer:
                # Skip external files - only work with QGIS layers
                continue
            
            # Create items for each configuration of this source file
            for config in configs:
                table_name = config['table_name']
                display_name = f"{source_file} → {table_name}"
                
                item = QTreeWidgetItem(self.shp_tree)
                item.setText(0, display_name)
                item.setText(1, str(data.get('feature_count', 0)))
                item.setText(2, data.get('geometry_type', 'Unknown'))
                item.setText(3, data.get('crs', 'Unknown'))
                
                # Store both source_file and table_name for identification
                item.setData(0, _ItemDataRole.UserRole, {'source_file': source_file, 'table_name': table_name})
                
                # Vérifier si c'est une couche QGIS
                is_qgis_layer = data.get('is_qgis_layer', False)
                
                # Icône selon le type de géométrie et la source
                geom_type = data.get('geometry_type', '').lower()
                
                # Style selon la source
                if is_qgis_layer:
                    # Couches QGIS : palette Link color + gras
                    palette = QApplication.palette()
                    blue_color = palette_color(palette, None, 'Link')
                    bold_font = QFont("Arial", 9, FontBold)
                    for col in range(4): # Appliquer à toutes les colonnes
                        item.setForeground(col, blue_color)
                        item.setFont(col, bold_font)
                else:
                    # Fichiers externes : palette LinkVisited color + normale
                    green_color = palette_color(palette, None, 'LinkVisited')
                    normal_font = QFont("Arial", 9, FontNormal)
                    for col in range(4): # Appliquer à toutes les colonnes
                        item.setForeground(col, green_color)
                        item.setFont(col, normal_font)
                
                # Icône selon le type de géométrie (une seule fois)
                if 'point' in geom_type:
                    item.setIcon(0, ui_icon("point_layer"))
                elif 'line' in geom_type or 'string' in geom_type:
                    item.setIcon(0, ui_icon("line_layer"))
                elif 'polygon' in geom_type:
                    item.setIcon(0, ui_icon("polygon_layer"))
                else:
                    item.setIcon(0, ui_icon("table_layer"))
                
                # Enhanced tooltip with configuration information
                source_type = "QGIS Layer" if is_qgis_layer else "External File"
                file_format = data.get('format', 'Unknown')
                field_count = data.get('field_count', 0)
                encoding = data.get('encoding', 'Unknown')
                storage_type = data.get('storage_type', 'Unknown')
                
                tooltip = f"""Source: {source_type}
Format: {file_format}
Source File: {source_file}
Target Table: {table_name}
Features: {data.get('feature_count', 0):,}
Fields: {field_count}
Geometry: {data.get('geometry_type', 'Unknown')}
CRS: {data.get('crs', 'Unknown')}
Encoding: {encoding}
Storage: {storage_type}
Path: {data.get('path', 'N/A')}"""
                item.setToolTip(0, tooltip)
        
        # Add pure source files (loaded but no configuration) - QGIS layers only
        for filename, data in self.loaded_shapefiles.items():
            if filename not in source_file_configs:
                # Only show QGIS layers - skip external files
                is_qgis_layer = data.get('is_qgis_layer', False)
                if not is_qgis_layer:
                    continue # Skip external files
                    
                item = QTreeWidgetItem(self.shp_tree)
                display_name = os.path.basename(filename) # Display only filename, not full path
                item.setText(0, display_name)
                item.setText(1, str(data.get('feature_count', 0)))
                item.setText(2, data.get('geometry_type', 'Unknown'))
                item.setText(3, data.get('crs', 'Unknown'))
                item.setData(0, _ItemDataRole.UserRole, {'source_file': filename, 'table_name': None})
                
                # Style as QGIS layer without configuration (palette-aware)
                palette = QApplication.palette()
                gray_color = palette_color(palette, None, 'PlaceholderText')
                italic_font = QFont("Arial", 9)
                italic_font.setItalic(True)
                for col in range(4):
                    item.setForeground(col, gray_color)
                    item.setFont(col, italic_font)
                
                # Icon based on geometry
                geom_type = data.get('geometry_type', '').lower()
                if 'point' in geom_type:
                    item.setIcon(0, ui_icon("point_layer"))
                elif 'line' in geom_type or 'string' in geom_type:
                    item.setIcon(0, ui_icon("line_layer"))
                elif 'polygon' in geom_type:
                    item.setIcon(0, ui_icon("polygon_layer"))
                else:
                    item.setIcon(0, ui_icon("table_layer"))
                
                # Tooltip for unconfigured QGIS layers
                source_type = "QGIS Layer"
                tooltip = f"""Source: {source_type}
Format: {data.get('format', 'Unknown')}
Source File: {filename}
Status: No configuration
Features: {data.get('feature_count', 0):,}
Geometry: {data.get('geometry_type', 'Unknown')}
CRS: {data.get('crs', 'Unknown')}
Path: {data.get('path', 'N/A')}"""
                item.setToolTip(0, tooltip)
        
        # Redimensionner les colonnes
        for i in range(self.shp_tree.columnCount()):
            self.shp_tree.resizeColumnToContents(i)
        
        # Mettre à jour les statistiques
        self.update_statistics()
    
    def _group_configurations_by_source_file(self):
        """Group configurations by source_file from gestionnaire"""
        try:
            configurations = self.config_manager.get_all_tables()
            source_file_configs = {}
            
            for table_name, config in configurations.items():
                source_file = config.get('source_file', '')
                if source_file:
                    if source_file not in source_file_configs:
                        source_file_configs[source_file] = []
                    source_file_configs[source_file].append({
                        'table_name': table_name,
                        'config': config
                    })
            
            return source_file_configs
            
        except Exception as e:
            self.log_message(f"Error grouping configurations: {str(e)}", "Warning")
            return {}
    
    def _create_data_from_config(self, config_info):
        """Create basic data structure from configuration when source file not loaded"""
        config = config_info.get('config', {})
        return {
            'feature_count': 0,
            'geometry_type': 'Unknown',
            'crs': config.get('target_crs', 'Unknown'),
            'is_qgis_layer': False,
            'format': 'Unknown',
            'field_count': len(config.get('calculated_fields', {})),
            'encoding': 'Unknown',
            'storage_type': 'Configuration only',
            'path': f"Configuration: {config_info['table_name']}"
        }
    
    def remove_selected_shapefile(self):
        """Remove the selected shapefile(s) or configurations - supports multiple selection"""
        selected_items = self.shp_tree.selectedItems()
        if not selected_items:
            self.log_message("Please select one or more items to remove", "Warning")
            return
        
        # Confirmation message for multiple selection
        if len(selected_items) == 1:
            item_data = selected_items[0].data(0, _ItemDataRole.UserRole)
            if isinstance(item_data, dict) and 'table_name' in item_data:
                if item_data['table_name']:
                    confirm_msg = f"Remove configuration '{item_data['table_name']}' for '{item_data['source_file']}'?"
                else:
                    confirm_msg = f"Remove source file '{item_data['source_file']}' from the list?"
            else:
                # Legacy support
                confirm_msg = f"Remove '{item_data}' from the source files list?"
        else:
            confirm_msg = f"Remove {len(selected_items)} selected items from the list?"
        
        reply = QMessageBox.question(
            self, "Confirm Removal", 
            confirm_msg,
            _MsgBoxButton.Yes | _MsgBoxButton.No,
            _MsgBoxButton.No
        )
        
        if reply != _MsgBoxButton.Yes:
            return
        
        # Remove all selected items
        removed_count = 0
        config_removed_count = 0
        
        for item in selected_items:
            item_data = item.data(0, _ItemDataRole.UserRole)
            
            if isinstance(item_data, dict):
                source_file = item_data.get('source_file')
                table_name = item_data.get('table_name')
                
                if table_name:
                    # Ask if user wants to delete configuration permanently from JSON
                    delete_msg = QMessageBox()
                    delete_msg.setIcon(_MsgBoxIcon.Question)
                    delete_msg.setWindowTitle("Delete Configuration")
                    delete_msg.setText(f"Configuration '{table_name}' removed from list.")
                    delete_msg.setInformativeText("Do you also want to delete this configuration permanently from the JSON file?\n\n"
                                                 "• Yes: Delete permanently (won't reappear)\n"
                                                 "• No: Keep in JSON (will reappear on next load)")
                    delete_msg.setStandardButtons(_MsgBoxButton.Yes | _MsgBoxButton.No | _MsgBoxButton.Cancel)
                    delete_msg.setDefaultButton(_MsgBoxButton.Yes)
                    
                    delete_reply = delete_msg.exec()
                    
                    if delete_reply == _MsgBoxButton.Yes:
                        # Remove configuration permanently from JSON
                        self.config_manager.remove_table_config(table_name)
                        config_removed_count += 1
                        self.log_message(f"Deleted configuration '{table_name}' permanently from JSON", "Success")
                    elif delete_reply == _MsgBoxButton.No:
                        # Just remove from current display, keep in JSON
                        self.log_message(f"Removed configuration '{table_name}' from display (kept in JSON)", "Info")
                    # If Cancel, do nothing
                else:
                    # Remove source file
                    if source_file in self.loaded_shapefiles:
                        data = self.loaded_shapefiles[source_file]
                        is_qgis_layer = data.get('is_qgis_layer', False)
                        
                        del self.loaded_shapefiles[source_file]
                        removed_count += 1
                        
                        if is_qgis_layer:
                            self.log_message(f"Removed QGIS layer from list: {source_file}", "Info")
                        else:
                            self.log_message(f"Removed external file from list: {source_file}", "Info")
            else:
                # Legacy support - assume it's a filename
                if item_data in self.loaded_shapefiles:
                    data = self.loaded_shapefiles[item_data]
                    is_qgis_layer = data.get('is_qgis_layer', False)
                    
                    del self.loaded_shapefiles[item_data]
                    removed_count += 1
                    
                    if is_qgis_layer:
                        self.log_message(f"Removed QGIS layer from list: {item_data}", "Info")
                    else:
                        self.log_message(f"Removed external file from list: {item_data}", "Info")
        
        self.refresh_shapefile_list()
        
        if removed_count > 0 or config_removed_count > 0:
            total_removed = removed_count + config_removed_count
            if config_removed_count > 0 and removed_count > 0:
                self.log_message(f"Removed {removed_count} source file(s) and {config_removed_count} configuration(s)", "Success")
            elif config_removed_count > 0:
                self.log_message(f"Removed {config_removed_count} configuration(s)", "Success")
            else:
                self.log_message(f"Removed {removed_count} source file(s)", "Success")
    
    def save_selected_configurations(self):
        """Save configurations for all selected vector files"""
        try:
            selected_items = self.shp_tree.selectedItems()
            if not selected_items:
                self.log_message("Please select one or more vector files to save configurations", "Warning")
                return
            
            # Get current configuration settings
            table_name = self.table_name_edit.text().strip()
            if not table_name:
                QMessageBox.warning(self, "Configuration Error", "Table name is required for saving configurations")
                return
            
            # Get calculated fields and geometry expression
            calculated_fields, geometry_expression = self.smart_fields.get_calculated_fields_with_geometry_info()
            
            # Get filter configuration
            filter_config = {"enabled": False, "expression": ""}
            if hasattr(self, 'smart_filter') and self.smart_filter:
                filter_config = self.smart_filter.get_filter_config()
            
            # Get target CRS
            target_crs_config = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs_config = self.target_crs.authid()
            
            saved_count = 0
            failed_count = 0
            
            # Save configuration for each selected file
            for item in selected_items:
                filename = item.data(0, _ItemDataRole.UserRole)
                if filename in self.loaded_shapefiles:
                    try:
                        # Use the configured table name directly - no concatenation
                        # If user wants different names per file, they should configure them individually
                        file_table_name = table_name
                        
                        # Get source file path
                        shapefile_info = self.loaded_shapefiles[filename]
                        source_file = shapefile_info.get('path', filename)
                        
                        # Save configuration using the configuration manager
                        result = self.config_manager.add_table_config(
                            file_table_name,
                            source_file,
                            calculated_fields,
                            filter_config,
                            target_crs_config,
                            geometry_expression
                        )
                        
                        # Log if a previous configuration was replaced
                        if result.get('replaced_table'):
                            self.log_message(f"Replaced previous configuration for '{result['replaced_table']}' (same source_file)", "Info")
                        
                        saved_count += 1
                        self.log_message(f"Configuration saved for '{filename}' as table '{file_table_name}'", "Success")
                        
                    except Exception as e:
                        failed_count += 1
                        self.log_message(f"Failed to save configuration for '{filename}': {str(e)}", "Error")
            
            # Persist changes to calculated_fields_config.json
            if saved_count > 0:
                self.config_manager.save_config()
                
            # Summary message
            if saved_count > 0:
                summary_msg = f"Batch save completed: {saved_count} configuration(s) saved to calculated_fields_config.json"
                if failed_count > 0:
                    summary_msg += f" ({failed_count} failed)"
                
                self.log_message(summary_msg, "Success")
                self.update_configuration_preview()
            else:
                self.log_message(f"All {len(selected_items)} configuration saves failed", "Error")
                
        except Exception as e:
            error_msg = f"Batch configuration save failed: {str(e)}"
            QMessageBox.critical(self, "Save Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def _set_table_name_edit(self, text: str) -> None:
        """Set table name without updating the layer tree display."""
        self._suppress_table_name_side_effects = True
        try:
            self.table_name_edit.setText(text)
        finally:
            self._suppress_table_name_side_effects = False

    def _clear_table_name_edit(self) -> None:
        """Clear table name without updating the layer tree display."""
        self._suppress_table_name_side_effects = True
        try:
            self.table_name_edit.clear()
        finally:
            self._suppress_table_name_side_effects = False

    def _reset_draft_config_tracking(self) -> None:
        self._draft_config_source = None
        self._config_modified_by_user = False

    def _revert_unchanged_draft_tree_item(self, source_file: str) -> None:
        """Restore a tree row to the plain source name after a browse-only visit."""
        if not source_file:
            return
        for i in range(self.shp_tree.topLevelItemCount()):
            item = self.shp_tree.topLevelItem(i)
            item_data = item.data(0, _ItemDataRole.UserRole)
            if not isinstance(item_data, dict):
                continue
            if item_data.get('source_file') != source_file:
                continue
            if item_data.get('table_name') is None:
                return
            display_name = os.path.basename(source_file) or source_file
            item.setText(0, display_name)
            item_data['table_name'] = None
            item.setData(0, _ItemDataRole.UserRole, item_data)
            return

    def _mark_config_modified_by_user(self) -> None:
        """Promote a browse-only preview into an active in-progress configuration."""
        was_unchanged_draft = bool(
            self._draft_config_source and not self._config_modified_by_user
        )
        self._config_modified_by_user = True
        self._draft_config_source = None
        if was_unchanged_draft:
            self._update_tree_item_display()

    def _update_tree_item_display(self) -> None:
        """Update the selected tree row to show source → target table."""
        try:
            current_item = self.shp_tree.currentItem()
            if not current_item:
                return

            item_data = current_item.data(0, _ItemDataRole.UserRole)
            if not isinstance(item_data, dict):
                return

            new_table_name = self.table_name_edit.text().strip()
            if not new_table_name:
                return

            source_file = item_data.get('source_file', '')
            current_item.setText(0, f"{source_file} → {new_table_name}")
            item_data['table_name'] = new_table_name
            current_item.setData(0, _ItemDataRole.UserRole, item_data)
        except Exception as e:
            self.log_message(f"Error updating table name display: {str(e)}", "Warning")

    def on_shapefile_selection_changed(self):
        """Handle shapefile/configuration selection change"""
        if self._draft_config_source and not self._config_modified_by_user:
            self._revert_unchanged_draft_tree_item(self._draft_config_source)
            self._reset_draft_config_tracking()

        current = self.shp_tree.currentItem()
        if current:
            item_data = current.data(0, _ItemDataRole.UserRole)
            
            # Handle new format with {source_file, table_name}
            if isinstance(item_data, dict):
                source_file = item_data.get('source_file')
                table_name = item_data.get('table_name')
                
                # Get source file data
                data = self.loaded_shapefiles.get(source_file, {})
                
                # Update selection information
                if table_name:
                    display_text = f"{source_file} → {table_name}"
                else:
                    display_text = source_file
                    
                self.selection_info_label.setText(display_text)
                self.features_count_label.setText(f"{data.get('feature_count', 0):,}")
                self.geometry_type_label.setText(data.get('geometry_type', 'Unknown'))
                self.crs_info_label.setText(data.get('crs', 'Unknown'))
                
                # Update the current CRS automatically
                self.update_current_crs(current)
                
                # Configure widgets with the new layer
                layer = data.get('layer')
                if layer and layer.isValid():
                    # Configure smart filter with the new layer
                    self.smart_filter.set_layer(layer)
                    
                    # Configure smart fields with the new layer
                    self.smart_fields.set_layer(layer)
                    
                    # Configure the expression builder with the new layer
                    if hasattr(self, 'advanced_expression') and self.advanced_expression:
                        self.advanced_expression.set_layer(layer)
                
                # Enable duplicate button for valid configurations
                has_valid_config = bool(table_name and self.config_manager.get_table_config(table_name))
                self.duplicate_action.setEnabled(has_valid_config)
                
                # Load the configuration if a table_name is provided
                if table_name:
                    config = self.config_manager.get_table_config(table_name)
                    if config:
                        self._apply_table_config(table_name, config)
                        self.log_message(f"Loaded configuration '{table_name}' for '{source_file}'", "Info")
                else:
                    # No configuration, just load the source file
                    self.auto_load_table_config_for_shapefile(source_file)
            else:
                # Legacy support - assume it's a filename
                filename = item_data
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
                
                # Always try to auto load configuration for individual selection
                self.auto_load_table_config_for_shapefile(filename)
            
        else:
            self.selection_info_label.setText("No selection")
            self.features_count_label.setText("0")
            self.geometry_type_label.setText("Unknown")
            self.crs_info_label.setText("Unknown")
            # Reset the current CRS
            self.current_crs_label.setText("Unknown")
    
    def auto_load_table_config_for_shapefile(self, filename: str):
        """Auto load configuration ONLY from calculated_fields_config.json - NO external fallback"""
        try:
            # First, check if a corresponding layer actually exists in QGIS project
            if not self._is_layer_present_in_qgis(filename):
                self.log_message(f"Layer for '{filename}' not found in QGIS project - mapping not loaded", "Info")
                # Clear any existing configuration
                self.smart_fields.clear_all_fields()
                self.table_name_edit.setText("")
                self.smart_filter.set_filter_config({})
                self.update_configuration_preview()
                return
            
            # ONLY try to load existing saved configuration from calculated_fields_config.json
            table_names = self.config_manager.get_tables_for_source(filename)
            if table_names:
                # Multiple configurations found - show selector
                if len(table_names) > 1:
                    self._show_config_selector(table_names, filename)
                    return
                
                # Single configuration - load directly
                first_table = table_names[0]
                config = self.config_manager.get_table_config(first_table)
                if config:
                    self._apply_table_config(first_table, config)
                    self.log_message(
                        f"Loaded configuration '{first_table}' from calculated_fields_config.json",
                        "Success",
                    )
                else:
                    self.log_message(
                        f"Configuration '{first_table}' not found in calculated_fields_config.json",
                        "Warning",
                    )
                    return
            else:
                # NO existing configuration: auto-populate all attribute fields in-memory
                # so the user can start editing immediately (replaces the old "Copy All" button).
                self._auto_populate_default_config(filename)
        
        except Exception as e:
            self.log_message(
                f"Error loading configuration for {filename}: {str(e)}", "Warning"
            )
            self.reset_configuration()
    
    def _auto_populate_default_config(self, filename: str) -> None:
        """Build a default in-memory config (one expression per attribute + geometry)
        from the layer attached to ``filename`` and apply it to the UI.
        
        Replaces the manual "Copy All" button: as soon as the user clicks a table,
        the bottom panel shows every attribute as an editable expression. The config
        is NOT persisted automatically; the user explicitly saves later.
        """
        try:
            data = self.loaded_shapefiles.get(filename, {}) if hasattr(self, 'loaded_shapefiles') else {}
            layer = data.get('layer')
            if layer is None or not layer.isValid():
                # Fallback: clear UI silently
                self.smart_fields.clear_all_fields()
                self.table_name_edit.setText("")
                self.smart_filter.set_filter_config({})
                self.update_configuration_preview()
                return
            
            # Build calculated_fields = {field_name: '"field_name"'} for every attribute
            calculated_fields = {}
            for fld in layer.fields():
                fname = fld.name()
                calculated_fields[fname] = f'"{fname}"'
            
            # Default geometry expression
            geometry_expression = "$geometry"
            try:
                from qgis.core import QgsWkbTypes
                if layer.geometryType() != QgsWkbTypes.NullGeometry:
                    calculated_fields["geometry"] = geometry_expression
            except Exception:
                calculated_fields["geometry"] = geometry_expression
            
            # Default table name: <basename>_transformed
            base_name = os.path.splitext(filename)[0]
            default_table_name = f"{base_name}_transformed"
            
            in_memory_config = {
                "calculated_fields": calculated_fields,
                "filter": {"enabled": False, "expression": ""},
                "geometry_expression": geometry_expression,
            }
            self._draft_config_source = filename
            self._config_modified_by_user = False
            self._apply_table_config(default_table_name, in_memory_config, as_draft=True)
            self.log_message(
                f"Auto-populated {len(calculated_fields)} fields from '{filename}' (unsaved)",
                "Info",
            )
        except Exception as exc:
            self.log_message(f"Auto-populate failed for '{filename}': {exc}", "Warning")
            try:
                self.smart_fields.clear_all_fields()
                self.table_name_edit.setText("")
                self.smart_filter.set_filter_config({})
                self.update_configuration_preview()
            except Exception as reset_exc:
                log_warning(f"reset_configuration failed: {reset_exc}")
    
    def _is_layer_present_in_qgis(self, filename: str) -> bool:
        """Check if a valid, accessible layer corresponding to filename is present in QGIS project"""
        try:
            from qgis.core import QgsProject, QgsVectorLayer
            import os
            project = QgsProject.instance()

            def _strip_ext(name: str) -> str:
                lower = name.lower()
                for ext in VECTOR_EXTENSIONS:
                    if lower.endswith(ext):
                        return name[: -len(ext)]
                return name

            filename_no_ext = _strip_ext(filename)

            for layer in project.mapLayers().values():
                if not isinstance(layer, QgsVectorLayer):
                    continue
                if not layer.isValid():
                    continue

                layer_name = layer.name()
                layer_source = layer.source()

                # 1. Exact name match
                if layer_name == filename:
                    return True

                # 2. Name without vector extension
                layer_name_no_ext = _strip_ext(layer_name)
                if layer_name == filename_no_ext or layer_name_no_ext == filename_no_ext:
                    return True

                # 3. Check if filename matches the basename of the source path
                if layer_source:
                    source_basename = os.path.basename(layer_source)
                    source_no_ext = _strip_ext(source_basename)
                    if (source_basename == filename
                            or source_no_ext == filename_no_ext
                            or source_no_ext == filename):
                        return True

                    # 4. GPKG/GeoPackage layer name in source (format: path|layername)
                    if '|' in layer_source:
                        gpkg_layer_name = layer_source.split('|')[-1]
                        if gpkg_layer_name == filename or gpkg_layer_name == filename_no_ext:
                            return True

            return False

        except Exception as e:
            self.log_message(f"Error checking layer presence for {filename}: {str(e)}", "Warning")
            return False
    
    def _show_config_selector(self, table_names, filename):
        """Show selector dialog when multiple configurations exist for one source file"""
        try:
            from qgis.PyQt.QtWidgets import QInputDialog
            
            # Create better display names showing source → table mapping
            display_names = [f"{filename} → {table}" for table in table_names]
            
            display_name, ok = QInputDialog.getItem(
                self, 
                "Multiple Configurations Found", 
                f"Multiple configurations found for source file '{filename}'.\nSelect which configuration to load:", 
                display_names, 
                0, 
                False
            )
            
            if ok and display_name:
                # Extract table name from display name
                table_name = display_name.split(' → ')[-1]
                config = self.config_manager.get_table_config(table_name)
                if config:
                    self._apply_table_config(table_name, config)
                    self.log_message(f"Loaded configuration '{table_name}' for '{filename}'", "Success")
                    
        except Exception as e:
            self.log_message(f"Error showing config selector: {str(e)}", "Warning")
    
    def _apply_table_config(self, table_name: str, config: dict, as_draft: bool = False):
        """Apply a table configuration to the UI"""
        try:
            if as_draft:
                self._draft_config_source = self._draft_config_source or config.get('source_file')
                self._config_modified_by_user = False
            else:
                self._reset_draft_config_tracking()

            # Update table name without changing the layer tree for browse-only previews
            self._set_table_name_edit(table_name)
            
            # Set calculated fields
            calculated_fields = config.get('calculated_fields', {})
            if hasattr(self, 'smart_fields') and self.smart_fields:
                self.smart_fields.set_calculated_fields(calculated_fields)
            elif hasattr(self, 'field_widget') and self.field_widget:
                self.field_widget.set_calculated_fields(calculated_fields)
            
            # Set filter
            filter_config = config.get('filter', {})
            if is_filter_enabled(filter_config):
                self.smart_filter.set_filter_expression(get_filter_expression(filter_config))
            else:
                self.smart_filter.clear_filter()
            
            # Set CRS
            target_crs = config.get('target_crs')
            if target_crs:
                try:
                    from qgis.core import QgsCoordinateReferenceSystem
                    crs_obj = QgsCoordinateReferenceSystem(target_crs)
                    if crs_obj.isValid():
                        crs_description = crs_obj.description()
                        self.set_target_crs(target_crs, crs_description)
                    else:
                        self.log_message(f"Invalid saved CRS: {target_crs}", "Warning")
                        self.target_crs = None
                except Exception as e:
                    self.log_message(f"Error loading saved CRS: {str(e)}", "Warning")
                    self.target_crs = None
            else:
                # No saved CRS - preserve current target_crs if user has set one
                if not hasattr(self, 'target_crs') or self.target_crs is None:
                    self.target_crs = None
            
            # Set geometry expression
            geometry_expression = config.get('geometry_expression')
            if geometry_expression and geometry_expression != '$geometry':
                self.advanced_expression.set_expression(geometry_expression)
                
            # Update configuration preview
            self.update_configuration_preview()
            
        except Exception as e:
            self.log_message(f"Error applying configuration: {str(e)}", "Warning")
    
    def load_table_config_by_name(self, table_name: str):
        """Load a specific configuration by table name and apply it to the interface"""
        try:
            # Get the configuration from config manager
            config = self.config_manager.get_table_config(table_name)
            if not config:
                self.log_message(f"Configuration '{table_name}' not found", "Warning")
                return False
            
            # Apply the configuration to the interface
            self._apply_table_config(table_name, config)
            self.log_message(f"Loaded configuration '{table_name}'", "Success")
            return True
            
        except Exception as e:
            self.log_message(f"Error loading configuration '{table_name}': {str(e)}", "Error")
            return False
    
    def update_configuration_dropdown(self):
        """Update any configuration dropdown/selector UI - placeholder for future implementation"""
        try:
            # For now, we trigger a config preview update to refresh the interface
            self.update_configuration_preview()
            
            # Log available configurations for user reference
            available_configs = self.config_manager.get_all_tables()
            if available_configs:
                config_names = list(available_configs.keys())
                self.log_message(f"Available configurations: {', '.join(config_names)}", "Info")
            
        except Exception as e:
            self.log_message(f"Error updating configuration dropdown: {str(e)}", "Warning")
    
    def _on_config_selected(self, table_name, filename):
        """Handle configuration selection from selector"""
        try:
            config = self.config_manager.get_table_config(table_name)
            if config:
                self._apply_table_config(table_name, config)
            else:
                self.log_message(f"Configuration '{table_name}' not found", "Warning")
                
        except Exception as e:
            self.log_message(f"Error loading selected configuration: {str(e)}", "Warning")
    
    def _on_config_deleted(self, table_name):
        """Handle configuration deletion from selector"""
        try:
            # Remove configuration
            success = self.config_manager.remove_table_config(table_name)
            if success:
                self.log_message(f"Configuration '{table_name}' deleted successfully", "Success")
                
                # Refresh selector if needed - get updated list
                current_filename = self.get_current_filename()
                if current_filename:
                    remaining_configs = self.config_manager.get_tables_for_source(current_filename)
                    if remaining_configs:
                        # Still have configs - reload
                        self.auto_load_table_config_for_shapefile(current_filename)
                    else:
                        # No configs left - load native fields
                        self.auto_load_table_config_for_shapefile(current_filename)
            else:
                self.log_message(f"Failed to delete configuration '{table_name}'", "Warning")
                
        except Exception as e:
            self.log_message(f"Error deleting configuration: {str(e)}", "Warning")
    
    def get_current_filename(self):
        """Get current selected filename"""
        try:
            current_item = self.shapefile_list.currentItem()
            if current_item:
                return current_item.text()
            return None
        except Exception:
            return None
    
    def reset_configuration(self):
        """Reset the configuration"""
        self.smart_fields.clear_all_fields()
        self.smart_filter.set_filter_config({"enabled": False, "expression": ""})
        # Reset the CRS target
        self.target_crs = None
        self.update_configuration_preview()
    
    def ensure_project_layer_signals(self):
        """Connect QGIS project layer signals (safe to call multiple times)."""
        project = QgsProject.instance()
        for signal_name, slot in (
            ('layersAdded', self.on_layers_added),
            ('layersRemoved', self.on_layers_removed),
            ('layerWillBeRemoved', self.on_layer_will_be_removed),
            ('readProject', self.on_project_read),
            ('cleared', self.on_project_cleared),
        ):
            signal = getattr(project, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            signal.connect(slot)

    def sync_layers_from_project(self):
        """Refresh the layer list from the current QGIS project."""
        try:
            self.auto_load_qgis_layers()
            self.refresh_shapefile_list()
            if hasattr(self, 'export_widget') and self.export_widget:
                if hasattr(self.export_widget, 'refresh_layers'):
                    self.export_widget.refresh_layers()
        except Exception as e:
            self.log_message(f"Error syncing layers from project: {str(e)}", "Warning")

    def on_project_read(self, *_args):
        """Handle QGIS project reload (e.g. opening a .qgz file)."""
        QTimer.singleShot(500, self.sync_layers_from_project)

    def on_project_cleared(self):
        """Handle QGIS project cleared."""
        layers_to_remove = list(self.loaded_shapefiles.keys())
        for layer_name in layers_to_remove:
            del self.loaded_shapefiles[layer_name]
        self.refresh_shapefile_list()

    def auto_load_qgis_layers(self):
        """Load vector layers from QGIS project to the source files list (supports all formats)"""
        try:
            project = QgsProject.instance()
            loaded_qgis_count = 0
            
            for layer_id, layer in project.mapLayers().items():
                # Only add VALID vector layers with accessible data (skip invalid/broken layers)
                if not isinstance(layer, QgsVectorLayer):
                    continue
                if not layer.isValid():
                    continue
                
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
                                'is_qgis_layer': True # Special flag to identify QGIS layers
                            }
                            
                            loaded_qgis_count += 1
            
            # Summary message
            if loaded_qgis_count > 0:
                self.log_message(
                    f"Loaded {loaded_qgis_count} layer(s) from project", 
                    "Info"
                )
            # No compatible layers (silent)
                            
        except Exception as e:
            self.log_message(f"Error loading QGIS layers: {str(e)}", "Warning")
    
    def on_layers_added(self, layers):
        """Handle when new layers are added to QGIS project"""
        vector_layers = [layer for layer in layers if isinstance(layer, QgsVectorLayer) and layer.isValid()]
        if vector_layers:
            QTimer.singleShot(100, self.sync_layers_from_project)
            
    def on_layers_removed(self, layer_ids):
        """Handle when layers are removed from QGIS project"""
        if layer_ids:
            self.log_message(f"Layers removed: {len(layer_ids)} layer(s)", "Info")
            # Remove layers from our loaded list
            layers_to_remove = []
            for layer_name, layer_data in self.loaded_shapefiles.items():
                layer = layer_data.get('layer')
                if self.is_layer_valid(layer):
                    if layer.id() in layer_ids:
                        layers_to_remove.append(layer_name)
                else:
                    # L'objet Qt a été supprimé, le retirer de notre liste
                    layers_to_remove.append(layer_name)
                    self.log_message(f"Removed deleted layer reference: {layer_name}", "Debug")
            
            for layer_name in layers_to_remove:
                del self.loaded_shapefiles[layer_name]
                
            self.refresh_shapefile_list()
            # Vector sources updated (silent)
            
    def on_layer_will_be_removed(self, layer_id):
        """Handle when a layer is about to be removed"""
        # Check if the layer being removed is currently selected
        current_item = self.shp_tree.currentItem()
        if current_item:
            item_data = current_item.data(0, _ItemDataRole.UserRole)
            
            # Extract filename from dict or use directly if string (legacy support)
            if isinstance(item_data, dict):
                filename = item_data.get('source_file', '')
            else:
                filename = item_data if item_data else ""
            
            if filename and filename in self.loaded_shapefiles:
                layer_data = self.loaded_shapefiles[filename]
                layer = layer_data.get('layer')
                if self.is_layer_valid(layer) and layer.id() == layer_id:
                    self.log_message(f"Currently selected layer '{filename}' is being removed - configuration will be reset", "Warning")
                elif not self.is_layer_valid(layer):
                    self.log_message(f"Layer reference for '{filename}' was already deleted", "Debug")
    
    # Removed remove_qgis_layers_from_list - not needed anymore since we only work with QGIS layers
    
    def is_layer_valid(self, layer):
        """Vérifie de manière sécurisée si un objet QgsVectorLayer est encore valide"""
        try:
            return layer is not None and hasattr(layer, 'id') and layer.id() is not None
        except RuntimeError:
            # L'objet Qt a été supprimé
            return False
    
    # === CONFIGURATION MANAGEMENT METHODS ===
    
    def update_configuration_preview(self):
        """Update the configuration preview"""
        try:
            table_name = self.table_name_edit.text().strip()
            
            current_item = self.shp_tree.currentItem()
            source_file = ""
            if current_item:
                item_data = current_item.data(0, _ItemDataRole.UserRole)
                if isinstance(item_data, dict):
                    source_file = item_data.get('source_file', '')
                else:
                    # Legacy support
                    source_file = item_data if item_data else ""
            
            # Get calculated fields separated from geometry
            if hasattr(self, 'smart_fields') and self.smart_fields:
                calculated_fields, geometry_expression = self.smart_fields.get_calculated_fields_with_geometry_info()
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
            
            filter_status = "Enabled" if is_filter_enabled(filter_config) else "Disabled"
            if is_filter_enabled(filter_config):
                filter_status += f" ({len(get_filter_expression(filter_config))} chars)"
            self.filter_status_label.setText(filter_status)
            
        except Exception as e:
            self.config_preview.setPlainText(f"Configuration preview error: {str(e)}")
            self.log_message(f"Error updating configuration preview: {str(e)}", "Warning")
    
    def on_filter_changed(self, expression, enabled):
        """Handle filter change"""
        self._mark_config_modified_by_user()
        self.update_configuration_preview()
        if enabled and expression:
            self.log_message(f"Filter updated: {expression[:50]}{'...' if len(expression) > 50 else ''}", "Info")
    
    def on_field_added(self, name, expression):
        """Handle field addition"""
        self._mark_config_modified_by_user()
        self.update_configuration_preview()
        self.log_message(f"Field added: {name} = {expression[:30]}{'...' if len(expression) > 30 else ''}", "Info")
    
    def on_field_removed(self, name):
        """Handle field removal"""
        self._mark_config_modified_by_user()
        self.update_configuration_preview()
        self.log_message(f"Field removed: {name}", "Info")
    
    def on_field_modified(self, old_name, new_name, expression):
        """Handle field modification"""
        self._mark_config_modified_by_user()
        self.update_configuration_preview()
        self.log_message(f"Field modified: {old_name} -> {new_name}", "Info")
    
    def on_table_name_changed(self):
        """Handle table name change - update display in shapefile list when edited."""
        if self._suppress_table_name_side_effects:
            return

        if self._draft_config_source and not self._config_modified_by_user:
            self._mark_config_modified_by_user()
            return

        if self._config_modified_by_user or not self._draft_config_source:
            self._update_tree_item_display()
    
    def duplicate_current_configuration(self):
        """Duplicate the current configuration with a new table name"""
        try:
            current_item = self.shp_tree.currentItem()
            if not current_item:
                QMessageBox.warning(self, "Warning", "Please select a configuration to duplicate.")
                return
            
            item_data = current_item.data(0, _ItemDataRole.UserRole)
            if not isinstance(item_data, dict):
                QMessageBox.warning(self, "Warning", "Cannot duplicate this item.")
                return
            
            source_file = item_data.get('source_file')
            current_table_name = item_data.get('table_name')
            
            if not source_file or not current_table_name:
                QMessageBox.warning(self, "Warning", "Invalid configuration selected.")
                return
            
            # Get current configuration
            current_config = self.config_manager.get_table_config(current_table_name)
            if not current_config:
                QMessageBox.warning(self, "Warning", "Configuration not found.")
                return
            
            # Prompt for new table name
            from qgis.PyQt.QtWidgets import QInputDialog
            new_table_name, ok = QInputDialog.getText(
                self, 
                "Duplicate Configuration", 
                f"Enter new table name for source '{source_file}':",
                text=f"{current_table_name}_copy"
            )
            
            if not ok or not new_table_name.strip():
                return
            
            new_table_name = new_table_name.strip()
            
            # Check if table name already exists
            if self.config_manager.get_table_config(new_table_name):
                QMessageBox.warning(self, "Warning", f"Table name '{new_table_name}' already exists.")
                return
            
            # Create new configuration by copying current one
            new_config = current_config.copy()
            new_config['table_name'] = new_table_name
            new_config['source_file'] = source_file
            new_config['created'] = datetime.now().isoformat()
            
            # Save the new configuration - extract parameters for add_table_config
            calculated_fields = new_config.get('calculated_fields', {})
            filter_config = new_config.get('filter', {})
            target_crs = new_config.get('target_crs')
            geometry_expression = new_config.get('geometry_expression')
            
            result = self.config_manager.add_table_config(
                new_table_name, 
                source_file, 
                calculated_fields,
                filter_config=filter_config,
                target_crs=target_crs,
                geometry_expression=geometry_expression,
                force_replace=False
            )
            success = result.get('success', False) if isinstance(result, dict) else result
            if success:
                self.refresh_shapefile_list()
                self.log_message(f"Configuration duplicated: '{current_table_name}' → '{new_table_name}'", "Success")
                
                # Select the new configuration
                for i in range(self.shp_tree.topLevelItemCount()):
                    item = self.shp_tree.topLevelItem(i)
                    item_data = item.data(0, _ItemDataRole.UserRole)
                    if isinstance(item_data, dict) and item_data.get('table_name') == new_table_name:
                        self.shp_tree.setCurrentItem(item)
                        break
            else:
                QMessageBox.critical(self, "Error", "Failed to save duplicated configuration.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error duplicating configuration: {str(e)}")
            self.log_message(f"Error duplicating configuration: {str(e)}", "Error")
    
    def validate_configuration(self):
        """Validate the current configuration"""
        try:
            # Sync JSON Preview → Field Management before validating
            self._sync_preview_to_fields()
            
            table_name = self.table_name_edit.text().strip()
            if not table_name:
                QMessageBox.warning(self, "Validation Error", "Table name is required")
                return False
            
            current_item = self.shp_tree.currentItem()
            if not current_item:
                QMessageBox.warning(self, "Validation Error", "Please select a shapefile")
                return False
            
            item_data = current_item.data(0, _ItemDataRole.UserRole)
            if isinstance(item_data, dict):
                filename = item_data.get('source_file', '')
            else:
                filename = item_data if item_data else ""
            
            if filename not in self.loaded_shapefiles:
                QMessageBox.warning(self, "Validation Error", "Source file not found")
                return False
                
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
            filter_expr = get_filter_expression(filter_config)
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
                    result_text += f" {error}\n"
                
                # Add available fields hint for "Field not found" errors
                if any("not found" in e.lower() for e in errors):
                    available_fields = [f.name() for f in layer.fields()]
                    result_text += f"\nAVAILABLE SOURCE FIELDS ({len(available_fields)}):\n"
                    result_text += " " + ", ".join(available_fields[:20])
                    if len(available_fields) > 20:
                        result_text += f"... (+{len(available_fields)-20} more)"
                
                result_text += "\n\nPlease fix the errors before proceeding."
                
                QMessageBox.warning(self, "Validation Errors", result_text)
                self.log_message(f"Configuration validation failed: {len(errors)} errors", "Warning")
                self._flash_validate_icons(False)
                return False
            else:
                # No errors - validation passed silently
                self.log_message(f"Configuration validated successfully: {table_name} ({len(successes)} fields validated)", "Info")
                self._flash_validate_icons(True)
                return True
                
        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            QMessageBox.critical(self, "Validation Error", error_msg)
            self.log_message(error_msg, "Error")
            self._flash_validate_icons(False)
            return False
    
    def _validate_icon_actions(self):
        actions = []
        for attr in ("_toolbar_validate_action", "_preview_validate_action"):
            action = getattr(self, attr, None)
            if action is not None:
                actions.append(action)
        return actions

    def _flash_validate_icons(self, success: bool) -> None:
        set_actions_outcome(self._validate_icon_actions(), "validate", success)

    def _refresh_toolbar_icons(self) -> None:
        """Re-apply default semantic icons after theme/cache reset."""
        icon_specs = (
            ("transform_action", "transform"),
            ("batch_action", "batch"),
            ("_toolbar_validate_action", "validate"),
            ("_preview_validate_action", "validate"),
        )
        for attr, name in icon_specs:
            action = getattr(self, attr, None)
            if action is not None:
                action.setIcon(ui_icon(name))
        for action, name in (
            (getattr(self, "table_config_action", None), "table_config"),
            (getattr(self, "filter_action", None), "filter"),
            (getattr(self, "expression_action", None), "expression"),
            (getattr(self, "fields_action", None), "fields"),
        ):
            if action is not None:
                action.setIcon(ui_icon(name))
    
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
                _MsgBoxButton.Yes | _MsgBoxButton.No,
                _MsgBoxButton.No
            )
            
            if reply == _MsgBoxButton.Yes:
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
    
    def _sync_preview_to_fields(self):
        """Sync Configuration Preview JSON to Field Management widget (bidirectional sync)"""
        try:
            json_text = self.config_preview.toPlainText().strip()
            if not json_text:
                return
            
            # Parse JSON from preview
            try:
                preview_config = json.loads(json_text)
            except json.JSONDecodeError:
                return
            
            # Get preview data
            preview_fields = preview_config.get('calculated_fields', {})
            preview_geom = preview_config.get('geometry_expression', '$geometry')
            preview_table = preview_config.get('table_name', '')
            
            # Block signals to prevent update_configuration_preview from being called
            self.smart_fields.blockSignals(True)
            self.smart_filter.blockSignals(True)
            
            try:
                # Sync table name
                if preview_table and preview_table != self.table_name_edit.text().strip():
                    self.table_name_edit.blockSignals(True)
                    self.table_name_edit.setText(preview_table)
                    self.table_name_edit.blockSignals(False)
                
                # Sync fields to Field Management (force update)
                self.smart_fields.set_calculated_fields(preview_fields, preview_geom)
                
                # Sync filter if present
                preview_filter = preview_config.get('filter', {})
                if preview_filter:
                    self.smart_filter.set_filter_config(preview_filter)
            finally:
                # Restore signals
                self.smart_fields.blockSignals(False)
                self.smart_filter.blockSignals(False)
                
        except Exception as e:
            self.log_message(f"Preview sync error: {str(e)}", "Warning")
    
    def _configurations_are_identical(self, config1, config2):
        """Compare two configurations to check if they are identical"""
        try:
            # Keys to compare (excluding metadata like save_date)
            keys_to_compare = ['calculated_fields', 'filter', 'target_crs', 'geometry_expression', 'source_file']
            
            for key in keys_to_compare:
                val1 = config1.get(key)
                val2 = config2.get(key)
                
                # Handle None values
                if val1 is None and val2 is None:
                    continue
                if val1 is None or val2 is None:
                    return False
                    
                # Special handling for different types
                if isinstance(val1, dict) and isinstance(val2, dict):
                    if val1 != val2:
                        return False
                elif str(val1) != str(val2):
                    return False
            
            return True
        except Exception:
            # If comparison fails for any reason, assume they're different
            return False
    
    def save_current_table_config(self, skip_validation=False):
        """Save the current table configuration with duplicate check"""
        try:
            # Sync JSON Preview → Field Management before saving
            self._sync_preview_to_fields()
            
            if not skip_validation and not self.validate_configuration():
                return
            
            table_name = self.table_name_edit.text().strip()
            current_item = self.shp_tree.currentItem()
            
            # Extract source file from item data
            item_data = current_item.data(0, _ItemDataRole.UserRole)
            if isinstance(item_data, dict):
                filename = item_data.get('source_file', '')
            else:
                filename = item_data if item_data else ""
            
            # Get calculated fields separated from geometry expression
            calculated_fields, geometry_expression = self.smart_fields.get_calculated_fields_with_geometry_info()
            filter_config = self.smart_filter.get_filter_config()
            
            # Get target CRS if defined
            target_crs = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs = self.target_crs.authid()
            
            # Check if a configuration already exists for this table
            if self.config_manager.has_table_config(table_name):
                existing_config = self.config_manager.get_table_config(table_name)
                existing_source = existing_config.get("source_file", "")
                
                # Create current configuration object for comparison
                current_config = {
                    'calculated_fields': calculated_fields,
                    'filter': filter_config,
                    'target_crs': target_crs,
                    'geometry_expression': geometry_expression,
                    'source_file': filename
                }
                
                # Compare configurations - only log if they're different
                if self._configurations_are_identical(existing_config, current_config):
                    # Configurations are identical, no need to save
                    self.log_message(f"Configuration for '{table_name}' is already up to date", "Info")
                    return
                else:
                    # Configurations are different, replace automatically without popup
                    self.log_message(f"Updating configuration for '{table_name}' with new settings", "Info")
                
                # Replace existing configuration automatically
                result = self.config_manager.add_table_config(table_name, filename, calculated_fields, filter_config, target_crs, geometry_expression, force_replace=True)
            else:
                # Add new configuration
                result = self.config_manager.add_table_config(table_name, filename, calculated_fields, filter_config, target_crs, geometry_expression)
            
            if result.get("success", False) and self.config_manager.save_config():
                action = result.get("action", "saved")
                replaced_info = f" (replaced '{result.get('replaced_table')}')" if result.get('replaced_table') else ""
                self.log_message(f"Configuration {action} for table '{table_name}'{replaced_info}", "Success")
                self._reset_draft_config_tracking()
                self.refresh_shapefile_list()
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
            self.progress_bar.setRange(0, 0) # Mode indéterminé
            
            if self.validate_configuration():
                # Test with a sample of data
                current_item = self.shp_tree.currentItem()
                filename = current_item.data(0, _ItemDataRole.UserRole)
                layer = self.loaded_shapefiles[filename]['layer']
                
                calculated_fields = self.smart_fields.get_calculated_fields()
                filter_config = self.smart_filter.get_filter_config()
                
                # Créer une couche de test temporaire avec un échantillon
                test_result = self.create_test_layer(layer, calculated_fields, filter_config)
                
                if test_result['success']:
                    result_msg = f"""Test Configuration Results

                                Table: {self.table_name_edit.text()}
                                Source: {filename}

                                 Test completed successfully!

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
            filter_expr = get_filter_expression(filter_config)
            if filter_expr:
                request = QgsFeatureRequest()
                request.setFilterExpression(filter_expr)
                filtered_features = list(layer.getFeatures(request))
                filtered_count = len(filtered_features)
            else:
                filtered_features = list(layer.getFeatures())
                filtered_count = len(filtered_features)
            
            # Limiter à un échantillon
            test_features = filtered_features[:max_features]
            processed_count = len(test_features)
            
            # Tester les expressions sur l'échantillon
            context = create_layer_expression_context(layer)
            
            for feature in test_features:
                context.setFeature(feature)
                
                for field_name, expression_text in calculated_fields.items():
                    is_valid, error_msg, expression = validate_expression_syntax(expression_text)
                    if not is_valid:
                        raise Exception(f"Syntax error in field '{field_name}': {error_msg}")
                    
                    success, result, eval_error = evaluate_expression(expression, context)
                    
                    if not success:
                        raise Exception(f"Expression error in field '{field_name}': {eval_error}")
            
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
        """Transform the selected shapefile(s) using background QgsTask"""
        try:
            selected_items = self.shp_tree.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "Warning", "Please select one or more shapefiles to transform")
                return
            
            if not self.validate_configuration():
                return
            
            self.save_current_table_config(skip_validation=True)
            
            target_crs = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs = self.target_crs
                self.log_message(f"Reprojection to {target_crs.authid()} will be applied", "Info")
            
            # Build task items
            items = []
            for item in selected_items:
                item_data = item.data(0, _ItemDataRole.UserRole)
                if isinstance(item_data, dict):
                    filename = item_data.get('source_file', '')
                else:
                    filename = item_data if item_data else ""
                
                if filename not in self.loaded_shapefiles:
                    self.log_message(f"Source file '{filename}' not found in loaded files", "Warning")
                    continue
                
                items.append({
                    "filename": filename,
                    "shapefile_info": self.loaded_shapefiles[filename],
                })
            
            if not items:
                QMessageBox.warning(self, "Warning", "No valid files to transform")
                return
            
            self._launch_transform_task(items, target_crs)
                
        except Exception as e:
            error_msg = f"Transformation setup failed: {str(e)}"
            QMessageBox.critical(self, "Transformation Error", error_msg)
            self.log_message(error_msg, "Error")

    def _launch_transform_task(self, items, target_crs, table_filter=None):
        """Launch a TransformTask on the QGIS task manager.

        ``table_filter`` (optional list of table_config names) is forwarded to
        the transformer to restrict which configs are applied per-source.
        """
        # C3: Guard against concurrent tasks — _current_task on the transformer
        # is a single slot, two concurrent tasks would overwrite each other.
        if self._active_transform_task is not None:
            self.log_message(
                "A transformation is already running, refusing to launch a second one",
                "Warning",
            )
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.status_label.setText(f"Transforming {len(items)} file(s)...")
        if hasattr(self, 'set_active_task'):
            self.set_active_task(f"Transform: {len(items)} layer(s)")
        self._set_transform_enabled(False)
        self.log_message(f"Starting background transformation of {len(items)} file(s)", "Info")

        task = TransformTask(
            self.transformer, items, target_crs,
            description=f"Transform {len(items)} layer(s)",
            table_filter=table_filter,
        )
        
        task.progressChanged.connect(
            lambda progress: self.progress_bar.setValue(int(progress))
        )
        task.taskCompleted.connect(lambda: self._on_transform_finished(task))
        task.taskTerminated.connect(lambda: self._on_transform_finished(task))
        
        self._active_transform_task = task
        QgsApplication.taskManager().addTask(task)

    def _set_transform_enabled(self, enabled):
        """Defensively enable/disable transform actions and legacy buttons."""
        for attr in ("transform_action", "batch_action",
                     "transform_selected_btn", "transform_all_btn"):
            obj = getattr(self, attr, None)
            if obj is not None and hasattr(obj, "setEnabled"):
                try:
                    obj.setEnabled(enabled)
                except Exception as exc:
                    log_warning(f"set_enabled failed on {attr}: {exc}")

    def _on_transform_finished(self, task):
        """Callback on main thread when TransformTask completes."""
        self.progress_bar.setVisible(False)
        self._set_transform_enabled(True)
        if hasattr(self, 'set_active_task'):
            self.set_active_task("")
        self._active_transform_task = None
        transform_ok = False

        if task.success_count > 0:
            transform_ok = True
            summary = f"Transformation completed: {len(task.created_layers)} layers from {task.success_count} files"
            if task.fail_count > 0:
                summary += f" ({task.fail_count} failed)"
            self.log_message(summary, "Success")
            self.status_label.setText(summary)
            set_action_outcome(self.transform_action, "transform", True)
            set_action_outcome(self.batch_action, "batch", True)

            # Trigger PostgreSQL auto-mapping
            if task.created_layers:
                self._trigger_postgresql_auto_mapping(
                    [layer.name() for layer in task.created_layers]
                )

            # Emit signals for each created layer
            for layer in task.created_layers:
                self.transformation_requested.emit(layer.name())
        else:
            self.log_message(f"Transformation failed: {task.fail_count} errors", "Warning")
            self.status_label.setText("Transformation failed")
            set_action_outcome(self.transform_action, "transform", False)
            set_action_outcome(self.batch_action, "batch", False)
            if task.errors:
                for err in task.errors[:5]:
                    self.log_message(err, "Error")

    def transform_all_shapefiles(self):
        """Transform all loaded shapefiles using background QgsTask"""
        try:
            if not self.loaded_shapefiles:
                QMessageBox.warning(self, "Warning", "No shapefiles loaded")
                return
            
            if not self.validate_configuration():
                return
            
            self.save_current_table_config(skip_validation=True)
            
            target_crs = None
            if hasattr(self, 'target_crs') and self.target_crs is not None and self.target_crs.isValid():
                target_crs = self.target_crs
                self.log_message(f"Reprojection to {target_crs.authid()} will be applied to all files", "Info")
            
            items = []
            for filename, data in self.loaded_shapefiles.items():
                items.append({
                    "filename": filename,
                    "shapefile_info": data,
                })
            
            self._launch_transform_task(items, target_crs)
                
        except Exception as e:
            error_msg = f"Batch transformation setup error: {str(e)}"
            QMessageBox.critical(self, "Batch Transformation Error", error_msg)
            self.log_message(error_msg, "Error")

    # === INTERFACE METHODS ===
    
    def on_tab_changed(self, index):
        """Handle tab change"""
        if index == 0:
            self.mode_label.setText("Configuration Mode")
            self.mode_label.setEnabled(True)
        elif index == 1:
            self.mode_label.setText("Export Mode")
            self.mode_label.setEnabled(True)
            # Refresh layers in the export tab if available - Import local to avoid circular import
            try:
                from ..main_plugin import EXPORT_MODULE_AVAILABLE
                if EXPORT_MODULE_AVAILABLE and hasattr(self, 'export_widget') and self.export_widget:
                    QTimer.singleShot(100, self.export_widget.refresh_layers)
            except (ImportError, AttributeError):
                pass # Module d'export non disponible, ignorer
    
    def on_transformation_completed(self, shapefile_path):
        """Handle transformation completion"""
        # Refresh layers in the export tab if available - Import local to avoid circular import
        try:
            from ..main_plugin import EXPORT_MODULE_AVAILABLE
            if EXPORT_MODULE_AVAILABLE and hasattr(self, 'export_widget') and self.export_widget:
                QTimer.singleShot(500, self.export_widget.refresh_layers)
        except (ImportError, AttributeError):
            pass # Module d'export non disponible, ignorer
    
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
            except (AttributeError, Exception) as exc:
                log_warning(f"update_statistics PG count failed: {exc}")
            
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
                filename = current_item.data(0, _ItemDataRole.UserRole)
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
                    if is_filter_enabled(filter_config):
                        self.filter_status_label.setText("Enabled")
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
    
    def _log_level_color(self, level: str) -> QColor:
        """Return a palette-aware color for the given log level."""
        palette = QApplication.palette()
        if level == "Info":
            return palette_color(palette, None, 'Text')
        elif level == "Panel":
            return palette_color(palette, None, 'PlaceholderText')
        elif level == "Success":
            return palette_color(palette, None, 'Link')
        elif level == "Warning":
            return palette_color(palette, None, 'ToolTipText')
        elif level == "Error":
            return palette_color(palette, None, 'LinkVisited')
        return palette_color(palette, None, 'Text')

    def log_message(self, message, level="Info"):
        """Add a message to the log with professional formatting and filtering"""
        try:
            # Initialize cache if not exists
            if not hasattr(self, '_log_cache'):
                self._log_cache = []
            
            # Auto-detect panel messages and set level to "Panel"
            if self._is_panel_message(message):
                level = "Panel"
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}"
            
            # Cache the log entry with its level
            self._log_cache.append((log_entry, level))
            
            # Check if this message type is filtered out
            if hasattr(self, 'log_filters') and level in self.log_filters:
                if not self.log_filters[level]:
                    # Still log to QGIS but not to UI
                    qgis_level = {
                        "Info": Qgis.Info,
                        "Warning": Qgis.Warning,
                        "Error": Qgis.Critical,
                        "Success": Qgis.Info,
                        "Panel": Qgis.Info
                    }.get(level, Qgis.Info)
                    QgsMessageLog.logMessage(message, "Transformer", qgis_level)
                    return
            
            # Add to the logs widget
            self.logs_text.appendPlainText(log_entry)
            
            # Apply color formatting
            cursor = self.logs_text.textCursor()
            cursor.movePosition(cursor.End)
            cursor.movePosition(cursor.StartOfLine, cursor.KeepAnchor)
            
            # Professional color coding using QPalette for theme compliance
            color = self._log_level_color(level)
            
            # Apply color to current line
            format = cursor.charFormat()
            format.setForeground(color)
            cursor.setCharFormat(format)
            
            # Move cursor to end for next message
            cursor.movePosition(cursor.End)
            self.logs_text.setTextCursor(cursor)
            
            # Ensure latest message is visible
            self.logs_text.ensureCursorVisible()
            
            # Log also to QGIS
            qgis_level = {
                "Info": Qgis.Info,
                "Warning": Qgis.Warning,
                "Error": Qgis.Critical,
                "Success": Qgis.Info,
                "Panel": Qgis.Info
            }.get(level, Qgis.Info)
            
            QgsMessageLog.logMessage(message, "Transformer", qgis_level)
            
        except Exception:
            pass # Avoid cascading errors
    
    def _is_panel_message(self, message):
        """Detect if a message is related to panel movements"""
        panel_keywords = [
            "Panel ",
            "moved to", 
            "shown", 
            "hidden", 
            "docked", 
            "floating", 
            "Layout reset",
            "drag to reposition",
            "Unknown area",
            "successfully"
        ]
        
        return any(keyword in message for keyword in panel_keywords)
    
    def _on_filter_combo_clicked(self, index):
        """Handle combo box clicks to toggle filter states"""
        try:
            # Get the filter key from the combo box items
            filter_keys = ["Success", "Info", "Warning", "Error", "Panel"]
            if 0 <= index < len(filter_keys):
                filter_key = filter_keys[index]
                
                # Toggle the filter state
                self.log_filters[filter_key] = not self.log_filters[filter_key]
                
                # Update the combo box display
                self._update_filter_combo_display()
                
                # Refresh the log display
                self.filter_logs()
                
                # Close the combo box popup (auto-collapse)
                self.filter_combo.hidePopup()
                
        except Exception as exc:
            log_warning(f"_on_filter_combo_clicked failed: {exc}")
    
    def _update_filter_combo_display(self):
        """Update combo box items to show current filter states with QGIS native style"""
        try:
            filter_items = [
                ("Success", self.log_filters.get("Success", True)),
                ("Info", self.log_filters.get("Info", True)),
                ("Warning", self.log_filters.get("Warning", True)),
                ("Error", self.log_filters.get("Error", True)),
                ("Panel", self.log_filters.get("Panel", False))
            ]
            
            # Update items with QGIS native green/white styling
            for i, (name, is_checked) in enumerate(filter_items):
                if is_checked:
                    # Green background for active filters with filled square
                    display_text = f" {name}"
                    self.filter_combo.setItemText(i, display_text)
                    # Use Qt roles for styling (palette-aware)
                    palette = QApplication.palette()
                    self.filter_combo.setItemData(i, palette_color(palette, None, 'Mid'), BackgroundRole)
                    self.filter_combo.setItemData(i, palette_color(palette, None, 'Text'), ForegroundRole)
                else:
                    # Inactive filter styling
                    display_text = f"⬜ {name}"
                    self.filter_combo.setItemText(i, display_text)
                    palette = QApplication.palette()
                    self.filter_combo.setItemData(i, palette_color(palette, None, 'Mid'), BackgroundRole)
                    self.filter_combo.setItemData(i, palette_color(palette, None, 'Text'), ForegroundRole)
        except Exception as exc:
            log_warning(f"_update_filter_combo_display failed: {exc}")
    
    def filter_logs(self):
        """Filter log display based on filter states"""
        try:
            if not hasattr(self, 'logs_text') or not hasattr(self, 'log_filters'):
                return
            
            # Get all text content and store with levels
            if not hasattr(self, '_log_cache'):
                self._log_cache = []
                return # No cached logs yet
            
            # Clear display
            self.logs_text.clear()
            
            # Re-add cached logs that match active filters
            for log_entry, level in self._log_cache:
                if level in self.log_filters and self.log_filters[level]:
                    self.logs_text.appendPlainText(log_entry)
                    
                    # Apply color formatting
                    cursor = self.logs_text.textCursor()
                    cursor.movePosition(cursor.End)
                    cursor.movePosition(cursor.StartOfLine, cursor.KeepAnchor)
                    
                    color = self._log_level_color(level)
                    format = cursor.charFormat()
                    format.setForeground(color)
                    cursor.setCharFormat(format)
            
            # Restore scroll position
            self.logs_text.ensureCursorVisible()
            
        except Exception as exc:
            log_warning(f"filter_logs failed: {exc}")
    
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
                            f" {mappings_loaded} mapping(s) PostgreSQL prêt(s) pour export (onglet PostgreSQL)", 
                            "Success"
                        )
                        break
            else:
                pass # Auto-mapping check completed (silent)
                
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
                
                self.log_message(f"Logs exported to {filename}", "Success")
                
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
            _MsgBoxButton.Yes | _MsgBoxButton.No,
            _MsgBoxButton.No
        )
        
        if reply == _MsgBoxButton.Yes:
            self.table_name_edit.clear()
            self.reset_configuration()
            self.log_message("New configuration created", "Info")
    
    def open_configuration(self):
        """Import external configuration and merge into calculated_fields_config.json"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Configuration", "",
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if filename:
            if self.config_manager.import_config(filename):
                # After successful import, configurations are merged into calculated_fields_config.json
                self.auto_load_configs()
                self.log_message(f"Configuration merged from {filename} into calculated_fields_config.json", "Success")
            else:
                self.log_message("Failed to import and merge configuration", "Error")
    
    def save_configuration(self):
        """Save the global configuration"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", 
            f"shape_transformer_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if filename:
            if self.config_manager.export_config(filename):
                self.log_message(f"Configuration exported to {filename}", "Success")
            else:
                QMessageBox.critical(self, "Error", "Failed to export configuration")
    
    def import_configuration(self):
        """Import external configuration and merge into calculated_fields_config.json"""
        self.open_configuration()
    
    def export_configuration(self):
        """Export the configuration"""
        self.save_configuration()
    
    def show_preferences(self):
        """Show preferences"""
        # Import local pour éviter l'import circulaire
        from ..widgets.preferences_dialog import PreferencesDialog
        dialog = PreferencesDialog(self.interface_settings, self)
        if dialog.exec() == _DialogCode.Accepted:
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
                self.log_message("All configurations are valid!", "Success")
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
            filename = current_item.data(0, _ItemDataRole.UserRole)
            layer = self.loaded_shapefiles[filename]['layer']
        else:
            layer = None
        
        dialog = ExpressionTesterDialog(layer, self)
        dialog.exec()
    
    def show_help(self):
        """Show help"""
        # Créer un dialog personnalisé
        dialog = QDialog(self)
        dialog.setWindowTitle("Help - Transformer")
        dialog.setModal(True)
        dialog.resize(1000, 700)
        dialog.setMinimumSize(800, 600)

        
        # Layout principal
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Créer le header avec logo
        header_widget = QWidget()

        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(25, 25, 25, 25)
        header_layout.setSpacing(20)
        
        # Logo cliquable
        logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'logo.png')
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(64, 64, KeepAspectRatio, SmoothTransformation)
            logo_label.setPixmap(pixmap)
        else:
            logo_label.setText("T")

        
        logo_label.setFixedSize(64, 64)
        logo_label.setAlignment(AlignCenter)

        logo_label.setCursor(PointingHandCursor)
        
        # Simuler le clic pour ouvrir GitHub
        def open_github():
            import webbrowser
            webbrowser.open('https://github.com/yadda07/Transformer')
        
        logo_label.mousePressEvent = lambda event: open_github()
        
        # Texte du header
        text_widget = QWidget()

        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addStretch() # Push content to center
        
        title_label = QLabel("Transformer")
        tl2_font = title_label.font()
        tl2_font.setBold(True)
        title_label.setFont(tl2_font)
        
        subtitle_label = QLabel("")

        
        # Animation typewriter
        self.typewriter_phrases = [
            "Arrange your data once, and never rearrange.",
            "Transform shapefiles with QGIS expressions.",
            "Export to PostgreSQL and multiple formats.",
            "Built for the QGIS community."
        ]
        self.current_phrase_index = 0
        self.current_char_index = 0
        self.is_typing = True
        self.cursor_visible = True
        
        # Timers pour l'animation
        self.help_typing_timer = QTimer(dialog) # Attacher au dialog
        self.help_typing_timer.timeout.connect(lambda: self.animate_typewriter(subtitle_label))
        self.help_typing_timer.start(80) # Plus rapide: 80ms entre chaque caractère
        
        self.help_cursor_timer = QTimer(dialog) # Attacher au dialog
        self.help_cursor_timer.timeout.connect(lambda: self.animate_cursor(subtitle_label))
        self.help_cursor_timer.start(200) # Curseur plus rapide: 300ms
        
        # Arrêter les timers à la fermeture du dialog
        dialog.finished.connect(lambda: self.stop_help_animation())
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(subtitle_label)
        text_layout.addStretch() # Push content to center
        
        header_layout.addWidget(logo_label, 0, AlignVCenter)
        header_layout.addWidget(text_widget, 1, AlignVCenter)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        # Contenu HTML simplifié (sans le problématique header)
        heart_icon = svg_html("heart", IconTone.ACTION)
        help_html = f"""
                <div style="font-family: 'Segoe UI', Arial, sans-serif; background: #0d1117; padding: 20px; border-radius: 10px; width: 100%; min-width: 850px; color: #e6edf3;">

                <!-- Core ETL Highlight -->
                <div style="background: linear-gradient(90deg, #0d2818 0%, #0c1c2b 100%); padding: 20px; border-bottom: 3px solid #238636;">
                <div style="text-align: center;">
                <h3 style="margin: 0 0 10px 0; color: #7ee787; font-size: 18px; font-weight: 600;">ETL Processing</h3>
                <p style="margin: 0; color: #adbac7; font-size: 14px; font-weight: 500;">
                Provides the equivalent of <strong style="color: #238636;">Reader + AttributeManager + Reprojector + Writer</strong><br/>
                components found in commercial ETL solutions, with intuitive tabbed interface.
                </p>
                </div>
                </div>

                <!-- Main Content Cards -->
                <div style="display: flex; gap: 20px; width: 100%; flex-wrap: wrap;">

                <!-- Left Column Card -->
                <div style="flex: 1; min-width: 350px; background: #161b22; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); overflow: hidden; border: 1px solid #30363d;">
                <div style="background: #238636; color: #e6edf3; padding: 15px; text-align: center;">
                <h2 style="margin: 0; font-size: 18px; font-weight: 600;">Features & Getting Started</h2>
                </div>
                <div style="padding: 25px;">

                <div style="margin-bottom: 30px;">
                <h3 style="color: #7ee787; margin: 0 0 15px 0; font-size: 16px; font-weight: 600; border-left: 4px solid #238636; padding-left: 12px;">Key Features</h3>
                <ul style="margin: 0; padding-left: 20px; color: #adbac7; font-size: 13px; line-height: 1.7;">
                <li><strong style="color: #7ee787;">Multi-format support:</strong> Shapefile, GeoJSON, GeoPackage, KML, and more</li>
                <li><strong style="color: #7ee787;">Expression builder:</strong> QGIS expressions with syntax validation and suggestions</li>
                <li><strong style="color: #7ee787;">Field management:</strong> Create, edit, and manage calculated fields</li>
                <li><strong style="color: #7ee787;">Filter system:</strong> Robust filtering with templates and suggestions</li>
                <li><strong style="color: #7ee787;">PostgreSQL integration:</strong> Direct export to PostgreSQL databases</li>
                <li><strong style="color: #7ee787;">Export capabilities:</strong> Multiple output formats and batch processing</li>
                <li><strong style="color: #7ee787;">Configuration templates:</strong> Save and reuse transformation settings</li>
                </ul>
                </div>

                <div>
                <h3 style="color: #7ee787; margin: 0 0 15px 0; font-size: 16px; font-weight: 600; border-left: 4px solid #238636; padding-left: 12px;">Getting Started</h3>
                <ol style="margin: 0; padding-left: 20px; color: #adbac7; font-size: 13px; line-height: 1.7;">
                <li><strong style="color: #7ee787;">Load vector files</strong> using the toolbar or from QGIS project layers</li>
                <li><strong style="color: #7ee787;">Select a source</strong> from the list (external files or QGIS layers)</li>
                <li><strong style="color: #7ee787;">Configure fields</strong> and expressions in the Configuration tab</li>
                <li><strong style="color: #7ee787;">Set up filters</strong> to process specific features only</li>
                <li><strong style="color: #7ee787;">Transform data</strong> to create new memory layers</li>
                <li><strong style="color: #7ee787;">Export results</strong> in various formats or to PostgreSQL</li>
                </ol>
                </div>

                </div>
                </div>

                <!-- Right Column Card -->
                <div style="flex: 1; min-width: 350px; background: #161b22; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); overflow: hidden; border: 1px solid #30363d;">
                <div style="background: #1f6feb; color: #e6edf3; padding: 15px; text-align: center;">
                <h2 style="margin: 0; font-size: 18px; font-weight: 600;">Technical Components</h2>
                </div>
                <div style="padding: 25px;">

                <div style="margin-bottom: 30px;">
                <h3 style="color: #79c0ff; margin: 0 0 15px 0; font-size: 16px; font-weight: 600; border-left: 4px solid #1f6feb; padding-left: 12px;">ETL Components</h3>
                <ul style="margin: 0; padding-left: 20px; color: #adbac7; font-size: 13px; line-height: 1.7;">
                <li><strong style="color: #79c0ff;">Reader:</strong> Multi-format input support (15+ vector formats)</li>
                <li><strong style="color: #79c0ff;">Expressions:</strong> Robust calculation and filtering using QGIS expressions</li>
                <li><strong style="color: #79c0ff;">Coordinate Transformations:</strong> Reprojection and geometric operations</li>
                <li><strong style="color: #79c0ff;">Writer:</strong> Multiple output formats and database integration</li>
                <li><strong style="color: #79c0ff;">Configuration Persistence:</strong> Save complete processing settings for automation</li>
                <li><strong style="color: #79c0ff;">Batch Processing:</strong> Handle multiple datasets with same transformation logic</li>
                </ul>
                </div>

                <div>
                <h3 style="color: #79c0ff; margin: 0 0 15px 0; font-size: 16px; font-weight: 600; border-left: 4px solid #1f6feb; padding-left: 12px;">Advanced Capabilities</h3>
                <ul style="margin: 0; padding-left: 20px; color: #adbac7; font-size: 13px; line-height: 1.7;">
                <li><strong style="color: #79c0ff;">Geometric transformations:</strong> Buffer, centroid, simplify operations</li>
                <li><strong style="color: #79c0ff;">Coordinate reprojection:</strong> Transform between different CRS</li>
                <li><strong style="color: #79c0ff;">Configuration templates:</strong> Save and reuse transformation settings</li>
                <li><strong style="color: #79c0ff;">Auto-mapping:</strong> PostgreSQL field correspondence</li>
                </ul>
                </div>

                </div>
                </div>

                </div>

                <!-- Developer Info Card -->
                <div style="background: #161b22; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); margin-top: 20px; overflow: hidden; border: 1px solid #30363d;">
                <div style="background: linear-gradient(90deg, #6e7681 0%, #484f58 100%); color: #e6edf3; padding: 15px; text-align: center;">
                <h3 style="margin: 0; font-size: 16px; font-weight: 600;">Developer Information</h3>
                </div>
                <div style="padding: 20px; text-align: center; background: #161b22;">
                <p style="margin: 0; font-size: 13px; color: #adbac7; line-height: 1.6;">
                <strong style="color: #7ee787;">Developed by:</strong> Yadda<br/>
                <strong style="color: #7ee787;">Contact:</strong> <span style="color: #79c0ff;">youcef.geodesien@gmail.com</span><br/>
                <strong style="color: #7ee787;">Portfolio:</strong> <a href="https://geodeci.xyz/" style="color: #79c0ff; text-decoration: none; font-weight: 500;">geodeci.xyz</a><br/>
                <strong style="color: #7ee787;">Documentation:</strong> <a href="https://github.com/yadda07/Transformer" style="color: #79c0ff; text-decoration: none; font-weight: 500;">github.com/yadda07/Transformer</a>
                </p>
                <p style="margin: 15px 0 0 0; font-size: 12px; color: #768390; font-style: italic;">
                Built with {heart_icon} for the QGIS community
                </p>
                </div>
                </div>

                </div>
        """
        
        # Zone de scroll pour le contenu HTML
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(_ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(_ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Widget de contenu HTML
        content_widget = QLabel()
        content_widget.setText(help_html)
        content_widget.setTextFormat(_TextFormat.RichText)
        content_widget.setWordWrap(True)
        content_widget.setAlignment(AlignTop)
        content_widget.setMargin(10)
        content_widget.setOpenExternalLinks(True)
        
        # Appliquer le CSS responsive
        responsive_css = """
        QLabel {
            background-color: #0d1117;
            color: #e6edf3;
        }
        QScrollArea {
            border: none;
            background-color: #0d1117;
        }
        """

        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        
        # Bouton OK
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("OK")
        ok_button.setDefault(True)
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        dialog.exec()
    
    def stop_help_animation(self):
        """Arrête les timers d'animation du Help"""
        try:
            if hasattr(self, 'help_typing_timer') and self.help_typing_timer is not None:
                self.help_typing_timer.stop()
        except RuntimeError:
            pass # Timer already deleted
        try:
            if hasattr(self, 'help_cursor_timer') and self.help_cursor_timer is not None:
                self.help_cursor_timer.stop()
        except RuntimeError:
            pass # Timer already deleted

    def animate_typewriter(self, label):
        """Anime l'effet typewriter"""
        if not hasattr(self, 'typewriter_phrases') or not label:
            return
            
        try:
            current_phrase = self.typewriter_phrases[self.current_phrase_index]
            
            if self.is_typing:
                # Écriture caractère par caractère
                if self.current_char_index <= len(current_phrase):
                    text = current_phrase[:self.current_char_index]
                    cursor = "|" if self.cursor_visible else " "
                    label.setText(text + cursor)
                    self.current_char_index += 1
                else:
                    # Pause à la fin de la phrase
                    if hasattr(self, 'help_typing_timer'):
                        self.help_typing_timer.stop()
                    QTimer.singleShot(1500, lambda: self.start_erasing(label)) # Pause 1.5s
        except RuntimeError:
            # Widget supprimé, arrêter l'animation
            self.stop_help_animation()
        
    def start_erasing(self, label):
        """Démarre l'effacement"""
        if not label:
            return
            
        try:
            if not hasattr(self, 'help_typing_timer') or self.help_typing_timer is None:
                return
                
            self.is_typing = False
            self.help_typing_timer.timeout.disconnect()
            self.help_typing_timer.timeout.connect(lambda: self.animate_erasing(label))
            self.help_typing_timer.start(30) # Plus rapide pour effacer: 30ms
        except RuntimeError:
            # Timer has been deleted, stop animation gracefully
            self.stop_help_animation()
        
    def animate_erasing(self, label):
        """Anime l'effacement"""
        if not hasattr(self, 'typewriter_phrases') or not label:
            return
            
        try:
            current_phrase = self.typewriter_phrases[self.current_phrase_index]
            
            if self.current_char_index > 0:
                self.current_char_index -= 1
                text = current_phrase[:self.current_char_index]
                cursor = "|" if self.cursor_visible else " "
                label.setText(text + cursor)
            else:
                # Passer à la phrase suivante
                self.current_phrase_index = (self.current_phrase_index + 1) % len(self.typewriter_phrases)
                self.is_typing = True
                if hasattr(self, 'help_typing_timer'):
                    self.help_typing_timer.timeout.disconnect()
                    self.help_typing_timer.timeout.connect(lambda: self.animate_typewriter(label))
                    self.help_typing_timer.start(40)
        except RuntimeError:
            self.stop_help_animation()
            
    def animate_cursor(self, label):
        """Anime le curseur clignotant"""
        if not label or not hasattr(self, 'typewriter_phrases'):
            return
            
        try:
            self.cursor_visible = not self.cursor_visible
            current_phrase = self.typewriter_phrases[self.current_phrase_index]
            text = current_phrase[:self.current_char_index]
            cursor = "|" if self.cursor_visible else " "
            label.setText(text + cursor)
        except RuntimeError:
            self.stop_help_animation()
    
    def show_about(self):
        """Show about information"""
        heart_icon = svg_html("heart", IconTone.ACTION)
        about_html = f"""
        <h2 style="color: #2E8B57; text-align: center; margin-bottom: 10px;">Transformer</h2>
        <h3 style="color: #4682B4; text-align: center; margin-bottom: 20px;">Shape Edition v2.1.0</h3>

        <p style="text-align: center; margin-bottom: 15px; color: #444;">
        <b style="color: #2E8B57;">Developed by Yadda</b>
        </p>

        <p style="text-align: center; margin-bottom: 15px; color: #555; font-style: italic;">
        QGIS plugin for vector data transformation<br/>with calculated fields, geometric operations and filtering capabilities
        </p>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;"/>

        <table style="margin: 0 auto; border-collapse: collapse;">
        <tr><td style="padding: 5px 15px; color: #666;"><b>Built with:</b></td><td style="padding: 5px 15px; color: #444;">QGIS API 3.10+ • PyQt5/6 • Python 3.6+</td></tr>
        <tr><td style="padding: 5px 15px; color: #666;"><b>Engine:</b></td><td style="padding: 5px 15px; color: #444;">Native QGIS Expression Engine</td></tr>
        <tr><td style="padding: 5px 15px; color: #666;"><b>Formats:</b></td><td style="padding: 5px 15px; color: #444;">Shapefile • GeoJSON • GeoPackage • KML • and more</td></tr>
        <tr><td style="padding: 5px 15px; color: #666;"><b>Contact:</b></td><td style="padding: 5px 15px;"><span style="color: #2E8B57;">youcef.geodesien@gmail.com</span></td></tr>
        <tr><td style="padding: 5px 15px; color: #666;"><b>License:</b></td><td style="padding: 5px 15px; color: #444;">GPL v2+</td></tr>
        </table>

        <p style="text-align: center; margin-top: 20px; font-size: 11px; color: #888;">
        Built with {heart_icon} for the QGIS community
        </p>
        """
        
        # Créer une QMessageBox personnalisée avec formatage HTML
        msg = QMessageBox(self)
        msg.setWindowTitle("About Transformer")
        msg.setTextFormat(_TextFormat.RichText)
        msg.setText(about_html)
        msg.setIcon(_MsgBoxIcon.Information)
        msg.setStandardButtons(_MsgBoxButton.Ok)
        msg.resize(450, 350)
        msg.exec()
    
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
                    _MsgBoxButton.Save | _MsgBoxButton.Discard | _MsgBoxButton.Cancel,
                    _MsgBoxButton.Save
                )
                
                if reply == _MsgBoxButton.Save:
                    self.save_current_table_config()
                elif reply == _MsgBoxButton.Cancel:
                    event.ignore()
                    return

            # Disconnect QgsProject signals only when the window is actually closing
            project = QgsProject.instance()
            for signal_name, slot in (
                ('layersAdded', self.on_layers_added),
                ('layersRemoved', self.on_layers_removed),
                ('layerWillBeRemoved', self.on_layer_will_be_removed),
                ('readProject', self.on_project_read),
                ('cleared', self.on_project_cleared),
            ):
                signal = getattr(project, signal_name, None)
                if signal is None:
                    continue
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError) as exc:
                    log_warning(f"Signal disconnect skipped during close: {exc}")
            
            self.log_message("Application closing", "Info")
            self.window_closed.emit()
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
                tooltip = "Suggestions:\n" + "\n".join(matches[:5]) # Limite à 5 suggestions
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
            
            if dialog.exec() == _DialogCode.Accepted:
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
                
                # Enable reprojection button if it exists
                if hasattr(self, 'apply_reprojection_button'):
                    self.apply_reprojection_button.setEnabled(True)
                
                self.log_message(f"Target CRS set to: {crs_code}", "Info")
                
                # Update configuration preview immediately to show the CRS
                self.update_configuration_preview()
            else:
                self.log_message(f"Invalid CRS: {crs_code}", "Error")
                self.target_crs = None
        except Exception as e:
            self.log_message(f"Error setting target CRS: {str(e)}", "Error")
            self.target_crs = None
    
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
                try:
                    btn.clicked.disconnect()
                except TypeError:
                    pass # No connections to disconnect
                btn.clicked.connect(lambda checked, c=crs_code, n=crs_name: self.set_target_crs(c, n))
            else:
                btn.setText("---")
                btn.setEnabled(False)
                btn.setVisible(False)
                btn.setToolTip("")
    
    def apply_reprojection(self):
        """Apply reprojection to all selected shapefiles"""
        try:
            if not hasattr(self, 'target_crs') or not self.target_crs.isValid():
                QMessageBox.warning(self, "Warning", "Please select a valid target CRS first.")
                return
            
            # Get all selected items
            selected_items = self.shp_tree.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "Warning", "Please select at least one shapefile.")
                return
            
            # Process each selected shapefile
            successful_count = 0
            failed_count = 0
            
            for item in selected_items:
                filename = item.data(0, _ItemDataRole.UserRole)
                if not filename or filename not in self.loaded_shapefiles:
                    self.log_message(f"Skipping invalid file: {filename}", "Warning")
                    failed_count += 1
                    continue
                
                try:
                    shapefile_info = self.loaded_shapefiles[filename]
                    
                    # Handle both external files and QGIS layers
                    if shapefile_info.get('is_qgis_layer', False):
                        # For QGIS layers, use the layer directly
                        layer = shapefile_info['layer']
                        if not layer.isValid():
                            self.log_message(f"Invalid QGIS layer: {filename}", "Error")
                            failed_count += 1
                            continue
                        
                        # Create output path based on layer name
                        output_path = Path.home() / f"{filename}_reprojected.shp"
                    else:
                        # For external files, use the file path
                        shapefile_path = shapefile_info.get('path', filename)
                        layer = QgsVectorLayer(shapefile_path, "temp", "ogr")
                        if not layer.isValid():
                            self.log_message(f"Failed to load shapefile: {filename}", "Error")
                            failed_count += 1
                            continue
                        
                        # Create output path next to original file
                        input_path = Path(shapefile_path)
                        output_path = input_path.parent / f"{input_path.stem}_reprojected.shp"
                    
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
                        self.log_message(f"Reprojection completed: {filename} -> {output_path.name}", "Success")
                        successful_count += 1
                        
                        # Save target CRS in configuration for this specific file
                        try:
                            # Get existing configuration or create basic one
                            table_names = self.config_manager.get_tables_for_source(filename)
                            if table_names:
                                table_name = table_names[0]
                                config = self.config_manager.get_table_config(table_name)
                                calculated_fields = config.get('calculated_fields', {})
                                filter_config = config.get('filter', {})
                                geometry_expression = config.get('geometry_expression', '$geometry')
                            else:
                                # Create basic config if none exists
                                table_name = f"{os.path.splitext(filename)[0]}_transformed"
                                calculated_fields = {}
                                filter_config = {"enabled": False, "expression": ""}
                                geometry_expression = "$geometry"
                                
                                # Add basic fields from layer
                                if layer and layer.isValid():
                                    for field in layer.fields():
                                        field_name = field.name()
                                        calculated_fields[field_name] = f'"{field_name}"'
                            
                            # Save config with the target CRS
                            target_crs_str = self.target_crs.authid() if self.target_crs and self.target_crs.isValid() else None
                            result = self.config_manager.add_table_config(
                                table_name,
                                filename,
                                calculated_fields,
                                filter_config,
                                target_crs_str,
                                geometry_expression
                            )
                            
                            # Log if a previous configuration was replaced
                            if result.get('replaced_table'):
                                self.log_message(f"Replaced previous configuration for '{result['replaced_table']}' (same source_file)", "Info")
                            self.log_message(f"Target CRS {target_crs_str} saved for '{filename}'", "Info")
                            
                        except Exception as e:
                            self.log_message(f"Warning: Could not save CRS config for {filename}: {str(e)}", "Warning")
                        
                    else:
                        self.log_message(f"Reprojection failed for {filename}: {error[1]}", "Error")
                        failed_count += 1
                        
                except Exception as e:
                    self.log_message(f"Error reprojecting {filename}: {str(e)}", "Error")
                    failed_count += 1
            
            # Summary message
            total_files = len(selected_items)
            if successful_count > 0:
                summary_msg = f"Batch reprojection completed: {successful_count}/{total_files} files successful"
                if failed_count > 0:
                    summary_msg += f", {failed_count} failed"
                self.log_message(summary_msg, "Success")
                
                # Save the configuration manager changes to disk
                if self.config_manager.save_config():
                    self.log_message("All target CRS configurations saved to disk", "Info")
                else:
                    self.log_message("Warning: Could not save configurations to disk", "Warning")
                
                # Reload the shapefiles list if any files were processed
                self.refresh_shapefile_list()
            else:
                self.log_message(f"All {total_files} reprojection operations failed", "Error")
                
        except Exception as e:
            error_msg = f"Error during batch reprojection: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.log_message(error_msg, "Error")
    
    def apply_json_changes(self):
        """Apply manual JSON changes to the configuration"""
        try:
            import json
            
            # Get the manually edited JSON text
            json_text = self.config_preview.toPlainText().strip()
            
            if not json_text:
                self.log_message("No JSON configuration to apply", "Warning")
                return
            
            # Parse the JSON
            try:
                config = json.loads(json_text)
            except json.JSONDecodeError as e:
                self.log_message(f"Invalid JSON syntax: {str(e)}", "Error")
                return
            
            # Validate required fields
            required_fields = ['table_name', 'calculated_fields']
            for field in required_fields:
                if field not in config:
                    self.log_message(f"Missing required field in JSON: '{field}'", "Error")
                    return
            
            # Apply table name
            if 'table_name' in config:
                self.table_name_edit.setText(config['table_name'])
            
            # Apply calculated fields and geometry expression
            calculated_fields = config.get('calculated_fields', {})
            geometry_expression = config.get('geometry_expression', '$geometry')
            
            # Update the field widget
            self.smart_fields.set_calculated_fields(calculated_fields, geometry_expression)
            
            # Apply filter configuration
            filter_config = config.get('filter', {})
            if filter_config:
                self.smart_filter.set_filter_config(filter_config)
            
            # Apply target CRS if specified
            target_crs_str = config.get('target_crs')
            if target_crs_str:
                try:
                    from qgis.core import QgsCoordinateReferenceSystem
                    target_crs = QgsCoordinateReferenceSystem(target_crs_str)
                    if target_crs.isValid():
                        crs_description = target_crs.description()
                        self.set_target_crs(target_crs_str, crs_description)
                        self.log_message(f"Target CRS applied: {target_crs_str}", "Success")
                    else:
                        self.log_message(f"Invalid CRS in JSON: {target_crs_str}", "Warning")
                except Exception as e:
                    self.log_message(f"Error applying CRS: {str(e)}", "Warning")
            
            # Count applied changes
            fields_count = len(calculated_fields)
            filter_enabled = is_filter_enabled(filter_config)
            
            # Success message
            changes_applied = []
            changes_applied.append(f"{fields_count} fields")
            if filter_enabled:
                changes_applied.append("filter enabled")
            if target_crs_str:
                changes_applied.append("target CRS")
                
            changes_summary = ", ".join(changes_applied)
            self.log_message(f"JSON changes applied: {changes_summary}", "Success")
            
            # Update the configuration preview to show properly formatted JSON
            self.update_configuration_preview()
            
        except Exception as e:
            error_msg = f"Error applying JSON changes: {str(e)}"
            self.log_message(error_msg, "Error")
    
    def update_current_crs(self, item):
        """Update the current CRS display"""
        if item:
            item_data = item.data(0, _ItemDataRole.UserRole)
            filename = None
            
            # Handle new format with source_file and table_name
            if isinstance(item_data, dict):
                filename = item_data.get('source_file', '')
            else:
                # Legacy format - direct filename string
                filename = item_data
            
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
                    except Exception:
                        self.current_crs_label.setText(crs_authid)
                    return
        
        self.current_crs_label.setText("Unknown")
    
    # Core transformation functionality
    
    # === NOUVEAUX WIDGETS MODULAIRES (transformation blocs centraux → docks) ===
 
