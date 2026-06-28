# -*- coding: utf-8 -*-
"""
Main Plugin - Transformer
Compatible QGIS 3.42+
Interface adapted for the new QMainWindow architecture with advanced features
Developed by the team of 4 Senior Developers
"""

import os
from typing import Optional

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QApplication

from qgis.core import QgsMessageLog, Qgis, QgsProject

# Import plugin modules
from .core.config_manager import ConfigManager as SimpleConfigManager
from .core.transformer import SimpleTransformer


# Direct import of the enhanced interface
INTERFACE_IMPORT_ERROR = ""
try:
    from .ui.main_window import EnhancedTransformerDialog
    ENHANCED_INTERFACE_AVAILABLE = True
except ImportError as e:
    INTERFACE_IMPORT_ERROR = str(e)
    QgsMessageLog.logMessage(f"Critical: Interface import failed: {INTERFACE_IMPORT_ERROR}", "Transformer", Qgis.Critical)
    EnhancedTransformerDialog = None
    ENHANCED_INTERFACE_AVAILABLE = False

# Import export module with detailed error handling
ExportManager = None
ExportWidget = None
EXPORT_MODULE_AVAILABLE = False

try:
    from .export.export_module import ExportManager as _ExportManager, ExportWidget as _ExportWidget, EXPORT_AVAILABLE
    
    if not EXPORT_AVAILABLE:
        raise ImportError("QGIS not available in export module")
    
    ExportManager = _ExportManager
    ExportWidget = _ExportWidget
    EXPORT_MODULE_AVAILABLE = True
    
except ImportError as e:
    QgsMessageLog.logMessage(f"Import Error: {str(e)}", "Transformer", Qgis.Warning)
    EXPORT_MODULE_AVAILABLE = False
except Exception as e:
    QgsMessageLog.logMessage(f"Unexpected Error: {str(e)}", "Transformer", Qgis.Critical)
    EXPORT_MODULE_AVAILABLE = False
    import traceback
    QgsMessageLog.logMessage(f"Traceback: {traceback.format_exc()}", "Transformer", Qgis.Critical)


class TransformerPlugin:
    """Main plugin for shapefile transformation - QGIS 3.42+ Version"""

    def __init__(self, iface):
        """Plugin constructor"""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.plugin_name = "Transformer"
        
        # Enterprise diagnostics: log runtime environment so we always know
        # which QGIS/Qt/PyQt the plugin is running against.
        try:
            from .shared.compat import log_environment
            log_environment()
        except Exception as exc:
            QgsMessageLog.logMessage(f"Environment log failed: {exc}", "Transformer", Qgis.Warning)
        
        # Main components
        self.config_manager: Optional[SimpleConfigManager] = None
        self.transformer: Optional[SimpleTransformer] = None
        self.export_manager: Optional[ExportManager] = None
        self.main_window: Optional[EnhancedTransformerDialog] = None
        
        # Interface
        self.action = None
        self.menu_text = "Transformer"
        
        # Interface state
        self.interface_visible = False
        self._project_signals_connected = False
        
        # Internationalization with error handling
        try:
            locale = QSettings().value('locale/userLocale', 'en')
            if isinstance(locale, str) and len(locale) >= 2:
                locale = locale[:2]
            else:
                locale = 'en'
                
            locale_path = os.path.join(
                self.plugin_dir,
                'i18n',
                f'{self.plugin_name}_{locale}.qm'
            )
            
            if os.path.exists(locale_path):
                self.translator = QTranslator()
                if self.translator.load(locale_path):
                    QCoreApplication.installTranslator(self.translator)
                    QgsMessageLog.logMessage(f"Loaded translation: {locale}", "Transformer", Qgis.Info)
                else:
                    QgsMessageLog.logMessage(f"Failed to load translation: {locale}", "Transformer", Qgis.Warning)
        except Exception as e:
            QgsMessageLog.logMessage(f"Translation setup failed: {str(e)}", "Transformer", Qgis.Warning)

    def tr(self, message):
        """Translate messages"""
        return QCoreApplication.translate(self.plugin_name, message)

    def initGui(self):
        """Initialize the plugin user interface"""
        try:
            # Create menu action with error handling - use logo.png
            icon_path = os.path.join(self.plugin_dir, 'logo.png')
            if not os.path.exists(icon_path):
                # Use default QGIS icon compatible with 3.42
                try:
                    icon = self.iface.actionAddOgrLayer().icon()  # Existing icon
                except Exception:
                    icon = QIcon()  # Empty icon as a last resort
            else:
                icon = QIcon(icon_path)
            
            action_text = "Transformer"
            
            self.action = QAction(
                icon,
                self.tr(action_text),
                self.iface.mainWindow()
            )
            
            self.action.setObjectName("transformer_action")
            self.action.setWhatsThis(self.tr("Transform shapefiles with calculated fields and advanced filtering"))
            self.action.setStatusTip(self.tr("Open shapefile transformation interface"))
            
            # Connecter l'action
            self.action.triggered.connect(self.run)
            
            # Ajouter l'action au menu et à la barre d'outils
            self.iface.addToolBarIcon(self.action)
            self.iface.addPluginToVectorMenu(self.menu_text, self.action)
            
            # Initialize components
            self.initialize_components()

            # Listen to project layer changes even before the UI is opened
            self.setup_project_signals()
            
            # Log available features
            features = []
            if ENHANCED_INTERFACE_AVAILABLE:
                features.append("Enhanced Interface")
            if EXPORT_MODULE_AVAILABLE:
                features.append("Export Module")
            
            features_text = ", ".join(features) if features else "Basic Interface"
            QgsMessageLog.logMessage(
                f"Plugin {self.plugin_name} initialized with features: {features_text}", 
                "Transformer", Qgis.Info
            )
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Plugin initialization error: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Initialization Error",
                f"Failed to initialize plugin {self.plugin_name}:\n{str(e)}"
            )

    def initialize_components(self):
        """Initialize plugin components"""
        try:
            # Configuration manager
            self.config_manager = SimpleConfigManager(self.plugin_dir)
            
            # Transformer
            self.transformer = SimpleTransformer(self.config_manager)
            
            # Export manager if available
            if EXPORT_MODULE_AVAILABLE and ExportManager:
                try:
                    self.export_manager = ExportManager()
                    # Export manager initialized (no QGIS log)
                except Exception as e:
                    QgsMessageLog.logMessage(f"Export manager initialization failed: {str(e)}", "Transformer", Qgis.Warning)
                    self.export_manager = None
            
            # Plugin components initialized (no QGIS log)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Component initialization error: {str(e)}", "Transformer", Qgis.Critical)
            raise

    def unload(self):
        """Unload the plugin"""
        try:
            self.teardown_project_signals()

            if self.main_window:
                try:
                    self.main_window.close()
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error closing main window: {exc}", "Transformer", Qgis.Warning)
                self.main_window = None
            
            # Remove action
            if self.action:
                try:
                    self.iface.removePluginVectorMenu(self.menu_text, self.action)
                    self.iface.removeToolBarIcon(self.action)
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error removing plugin UI elements: {exc}", "Transformer", Qgis.Warning)
                self.action = None
            
            # Clean references
            self.config_manager = None
            self.transformer = None
            self.export_manager = None
            self.interface_visible = False
            
            QgsMessageLog.logMessage(f"Plugin {self.plugin_name} unloaded", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Plugin unload error: {str(e)}", "Transformer", Qgis.Warning)

    def run(self):
        """Execute the plugin"""
        try:
            if not self.config_manager or not self.transformer:
                self.initialize_components()
            
            if not ENHANCED_INTERFACE_AVAILABLE:
                detail = INTERFACE_IMPORT_ERROR or "Unknown import error."
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Plugin interface failed to load.\n\n{detail}"
                )
                return
            
            self.run_enhanced_interface()
                
        except Exception as e:
            QgsMessageLog.logMessage(f"Interface opening error: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to open plugin interface:\n{str(e)}"
            )

    def run_enhanced_interface(self):
        """Launch enhanced professional interface"""
        try:
            if self.main_window is None:
                # Create new professional interface
                self.main_window = EnhancedTransformerDialog(
                    self.config_manager,
                    self.transformer,
                    self.iface.mainWindow()
                )
                
                # Configure interface
                self.setup_enhanced_interface_connections()
                
                # Center on screen
                self.center_window()
                # Enhanced interface created (no QGIS log)
            
            # Show or hide interface
            if self.interface_visible and self.main_window.isVisible():
                self.main_window.hide()
                self.interface_visible = False
                QgsMessageLog.logMessage("Enhanced interface hidden", "Transformer", Qgis.Info)
            else:
                self.main_window.show()
                self.main_window.raise_()
                self.main_window.activateWindow()
                self.interface_visible = True
                # Enhanced interface shown (no QGIS log)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Enhanced interface error: {str(e)}", "Transformer", Qgis.Critical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Enhanced interface error:\n{str(e)}"
            )

    def setup_project_signals(self):
        """Connect persistent QGIS project signals for automatic layer sync."""
        if self._project_signals_connected:
            return

        project = QgsProject.instance()
        for signal_name, slot in (
            ('layersAdded', self.on_layers_added),
            ('layersRemoved', self.on_layers_removed),
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

        self._project_signals_connected = True

    def teardown_project_signals(self):
        """Disconnect persistent QGIS project signals."""
        if not self._project_signals_connected:
            return

        project = QgsProject.instance()
        for signal_name, slot in (
            ('layersAdded', self.on_layers_added),
            ('layersRemoved', self.on_layers_removed),
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

        self._project_signals_connected = False

    def setup_enhanced_interface_connections(self):
        """Configure the connections for the enhanced interface"""
        if not self.main_window:
            return
        
        try:
            # Connection for transformation
            if hasattr(self.main_window, 'transformation_requested'):
                self.main_window.transformation_requested.connect(self.handle_transformation_request)
            
            if hasattr(self.main_window, 'window_closed'):
                self.main_window.window_closed.connect(self.on_enhanced_interface_closed)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Enhanced interface connections error: {str(e)}", "Transformer", Qgis.Warning)

    def center_window(self):
        """Center the main window on the screen"""
        if not self.main_window:
            return
        
        try:
            # Get the geometry of the main screen (compatible 3.42)
            screen = QApplication.primaryScreen()
            if screen:
                screen_geometry = screen.availableGeometry()
                
                # Calculer la position centrée
                window_geometry = self.main_window.geometry()
                x = (screen_geometry.width() - window_geometry.width()) // 2
                y = (screen_geometry.height() - window_geometry.height()) // 2
                
                # Déplacer la fenêtre
                self.main_window.move(x, y)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Window centering error: {str(e)}", "Transformer", Qgis.Warning)

    def on_enhanced_interface_closed(self):
        """Handle the closing of the enhanced interface"""
        self.interface_visible = False
        QgsMessageLog.logMessage("Enhanced interface closed", "Transformer", Qgis.Info)

    def on_layers_added(self, layers):
        """Handle the addition of layers to the project"""
        if self.main_window:
            QTimer.singleShot(300, self.refresh_interface_layers)

    def on_layers_removed(self, layer_ids):
        """Handle the removal of layers from the project"""
        if self.main_window:
            QTimer.singleShot(300, self.refresh_interface_layers)

    def on_project_read(self, *_args):
        """Handle QGIS project reload."""
        if self.main_window:
            QTimer.singleShot(500, self.refresh_interface_layers)

    def on_project_cleared(self):
        """Handle QGIS project cleared."""
        if self.main_window:
            QTimer.singleShot(100, self.refresh_interface_layers)

    def refresh_interface_layers(self):
        """Refresh layers in the interface"""
        try:
            if self.main_window and hasattr(self.main_window, 'sync_layers_from_project'):
                self.main_window.sync_layers_from_project()
                QgsMessageLog.logMessage("Interface layers refreshed", "Transformer", Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(f"Layer refresh error: {str(e)}", "Transformer", Qgis.Warning)

    def handle_transformation_request(self, shapefile_path: str):
        """Handle transformation requests"""
        try:
            QgsMessageLog.logMessage(f"Transformation request handled: {shapefile_path}", "Transformer", Qgis.Info)
            
            # Refresh layers after transformation
            QTimer.singleShot(1000, self.refresh_interface_layers)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Transformation request error: {str(e)}", "Transformer", Qgis.Warning)


