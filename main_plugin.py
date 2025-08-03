# -*- coding: utf-8 -*-
"""
Main Plugin - Transformer
Compatible QGIS 3.42+
Interface adapted for the new QMainWindow architecture with advanced features
Developed by the team of 4 Senior Developers
"""

import os
from typing import Optional

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QApplication

from qgis.core import QgsApplication, QgsMessageLog, Qgis, QgsProject

# Import plugin modules
from .gestionnaire import SimpleConfigManager
from .trans_calc import SimpleTransformer


# Robust import of the interface with error handling
try:
    from .Transformer_dialog import EnhancedTransformerDialog, MinimalTransformerDialog
    ENHANCED_INTERFACE_AVAILABLE = True
    QgsMessageLog.logMessage("Enhanced interface loaded successfully", "Transformer", Qgis.Info)
except ImportError as e:
    QgsMessageLog.logMessage(f"Enhanced interface import failed: {str(e)}", "Transformer", Qgis.Warning)
    try:
        # Fallback to minimal interface
        from .Transformer_dialog import MinimalTransformerDialog
        EnhancedTransformerDialog = None
        ENHANCED_INTERFACE_AVAILABLE = False
        QgsMessageLog.logMessage("Using fallback interface", "Transformer", Qgis.Info)
    except ImportError as e2:
        QgsMessageLog.logMessage(f"Critical: No interface available: {str(e2)}", "Transformer", Qgis.Critical)
        # Emergency interface
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel
        
        class MinimalTransformerDialog(QDialog):
            def __init__(self, config_manager, transformer, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Transformer - Error")
                layout = QVBoxLayout()
                layout.addWidget(QLabel("Interface loading failed"))
                layout.addWidget(QLabel("Please check plugin installation"))
                self.setLayout(layout)
        
        EnhancedTransformerDialog = None
        ENHANCED_INTERFACE_AVAILABLE = False

# Import export module with detailed error handling
ExportManager = None
ExportWidget = None
EXPORT_MODULE_AVAILABLE = False

try:
    # Explicit import with detailed logs
    QgsMessageLog.logMessage(" Tentative d'import du module d'export...", "Transformer", Qgis.Info)
    
    # First check that the file exists
    import os
    module_path = os.path.join(os.path.dirname(__file__), 'export_module.py')
    if not os.path.exists(module_path):
        raise ImportError(f"File export_module.py not found: {module_path}")
    
    QgsMessageLog.logMessage(f" Module found: {module_path}", "Transformer", Qgis.Info)
    
    # Import complete module
    from . import export_module
    QgsMessageLog.logMessage(" Module export_module imported", "Transformer", Qgis.Info)
    
    # Check QGIS availability in module
    if not hasattr(export_module, 'EXPORT_AVAILABLE') or not export_module.EXPORT_AVAILABLE:
        raise ImportError("QGIS not available in export module")
    
    QgsMessageLog.logMessage(" QGIS available in export module", "Transformer", Qgis.Info)
    
    # Import classes
    ExportManager = export_module.ExportManager
    ExportWidget = export_module.ExportWidget
    
    EXPORT_MODULE_AVAILABLE = True
    QgsMessageLog.logMessage("Export module loaded successfully!", "Transformer", Qgis.Success)
    
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
        self.use_enhanced_interface = ENHANCED_INTERFACE_AVAILABLE
        
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
            # Create menu action with error handling
            icon_path = os.path.join(self.plugin_dir, 'icon.png')
            if not os.path.exists(icon_path):
                # Use default QGIS icon compatible with 3.42
                try:
                    icon = self.iface.actionAddOgrLayer().icon()  # Existing icon
                except:
                    icon = QIcon()  # Empty icon as a last resort
            else:
                icon = QIcon(icon_path)
            
            action_text = "Transformer" if self.use_enhanced_interface else "Transformer"
            
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
                    QgsMessageLog.logMessage("Export manager initialized", "Transformer", Qgis.Info)
                except Exception as e:
                    QgsMessageLog.logMessage(f"Export manager initialization failed: {str(e)}", "Transformer", Qgis.Warning)
                    self.export_manager = None
            
            QgsMessageLog.logMessage("Plugin components initialized successfully", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Component initialization error: {str(e)}", "Transformer", Qgis.Critical)
            raise

    def unload(self):
        """Unload the plugin"""
        try:
            # Close main interface
            if self.main_window:
                try:
                    self.main_window.close()
                except:
                    pass
                self.main_window = None
            
            # Remove action
            if self.action:
                try:
                    self.iface.removePluginVectorMenu(self.menu_text, self.action)
                    self.iface.removeToolBarIcon(self.action)
                except:
                    pass
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
            # Check components
            if not self.config_manager or not self.transformer:
                self.initialize_components()
            
            # Use appropriate interface
            if self.use_enhanced_interface and ENHANCED_INTERFACE_AVAILABLE and EnhancedTransformerDialog:
                self.run_enhanced_interface()
            else:
                self.run_classic_interface()
                
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
                
                QgsMessageLog.logMessage("Enhanced interface created", "Transformer", Qgis.Info)
            
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
                QgsMessageLog.logMessage("Enhanced interface shown", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Enhanced interface error: {str(e)}", "Transformer", Qgis.Critical)
            # Fallback vers l'interface classique
            self.use_enhanced_interface = False
            self.run_classic_interface()

    def run_classic_interface(self):
        """Launch classic interface (Dialog)"""
        try:
            # Create classic interface each time (Modal dialog)
            dialog = MinimalTransformerDialog(
                self.config_manager,
                self.transformer,
                self.iface.mainWindow()
            )
            
            # Configure connections
            self.setup_classic_interface_connections(dialog)
            
            # Show modal dialog
            dialog.show()
            
            QgsMessageLog.logMessage("Classic interface opened", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Classic interface error: {str(e)}", "Transformer", Qgis.Critical)
            raise

    def setup_enhanced_interface_connections(self):
        """Configure the connections for the enhanced interface"""
        if not self.main_window:
            return
        
        try:
            # Connection for transformation
            if hasattr(self.main_window, 'transformation_requested'):
                self.main_window.transformation_requested.connect(self.handle_transformation_request)
            
            # Connexion pour la fermeture
            if hasattr(self.main_window, 'finished'):
                self.main_window.finished.connect(self.on_enhanced_interface_closed)
            
            # Connexions avec le projet QGIS
            QgsProject.instance().layersAdded.connect(self.on_layers_added)
            QgsProject.instance().layersRemoved.connect(self.on_layers_removed)
            
            QgsMessageLog.logMessage("Enhanced interface connections established", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Enhanced interface connections error: {str(e)}", "Transformer", Qgis.Warning)

    def setup_classic_interface_connections(self, dialog):
        """Configure the connections for the classic interface"""
        try:
            # Connection for transformation
            if hasattr(dialog, 'transformation_requested'):
                dialog.transformation_requested.connect(self.handle_transformation_request)
            
            QgsMessageLog.logMessage("Classic interface connections established", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Classic interface connections error: {str(e)}", "Transformer", Qgis.Warning)

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
        if self.main_window and self.interface_visible:
            # Refresh the interface if it is visible
            QTimer.singleShot(500, self.refresh_interface_layers)

    def on_layers_removed(self, layer_ids):
        """Handle the removal of layers from the project"""
        if self.main_window and self.interface_visible:
            # Refresh the interface if it is visible
            QTimer.singleShot(500, self.refresh_interface_layers)

    def refresh_interface_layers(self):
        """Refresh layers in the interface"""
        try:
            if self.main_window and hasattr(self.main_window, 'export_widget') and self.main_window.export_widget:
                if hasattr(self.main_window.export_widget, 'refresh_layers'):
                    self.main_window.export_widget.refresh_layers()
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

    def get_plugin_info(self) -> dict:
        """Return plugin information"""
        return {
            "name": self.plugin_name,
            "version": "1.0.0 Professional (QGIS 3.42+)",
            "description": "Transform shapefiles using QGIS calculated fields with advanced filtering and export",
            "author": "NGEDEV TEAM",
            "email": "yadda@ext.nge.fr",
            "qgis_version": "3.42+",
            "enhanced_interface": ENHANCED_INTERFACE_AVAILABLE,
            "export_module": EXPORT_MODULE_AVAILABLE,
            "config_manager": bool(self.config_manager),
            "transformer": bool(self.transformer),
            "export_manager": bool(self.export_manager),
            "interface_visible": self.interface_visible,
            "interface_type": "Enhanced" if self.use_enhanced_interface else "Classic"
        }

    def show_about(self):
        """Show plugin information"""
        info = self.get_plugin_info()
        
        about_text = f"""
<h2>{info['name']}</h2>
<h3>Version {info['version']}</h3>

<p><b>Developed by:</b> {info['author']}</p>
<p><b>Email:</b> {info['email']}</p>
<p><b>QGIS Version:</b> {info['qgis_version']}</p>

<h4>Features:</h4>
<ul>
<li>Enhanced Interface: {'✓ Available' if info['enhanced_interface'] else '✗ Not Available'}</li>
<li>Export Module: {'✓ Available' if info['export_module'] else '✗ Not Available'}</li>
<li>Current Mode: {info['interface_type']}</li>
</ul>

<h4>Features:</h4>
<ul>
<li>Native QGIS 3.42+ integration</li>
</ul>

<p>{info['description']}</p>
        """
        
        QMessageBox.about(self.iface.mainWindow(), "About Transformer", about_text)


def classFactory(iface):
    """Function called by QGIS to create the plugin instance"""
    return TransformerPlugin(iface)