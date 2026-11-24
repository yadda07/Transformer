# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Main Plugin - Transformer
Compatible QGIS 3.40 - 4.x (Qt 5 / Qt 6)
Interface adapted for the QMainWindow architecture with advanced features
"""

import os

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QTimer
from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject

_MSG_LEVEL = getattr(Qgis, "MessageLevel", Qgis)
MsgInfo = getattr(_MSG_LEVEL, "Info", 0)
MsgWarning = getattr(_MSG_LEVEL, "Warning", 1)
MsgCritical = getattr(_MSG_LEVEL, "Critical", 2)


# Lazy-loaded GUI/export modules so qgis_process stays headless-safe.
# PEP 562 __getattr__ preserves backward-compatible imports such as:
#   from ..main_plugin import EXPORT_MODULE_AVAILABLE
_LAZY_STATE = {
    "interface_loaded": False,
    "INTERFACE_IMPORT_ERROR": "",
    "EnhancedTransformerDialog": None,
    "ENHANCED_INTERFACE_AVAILABLE": False,
    "export_loaded": False,
    "ExportManager": None,
    "ExportWidget": None,
    "EXPORT_MODULE_AVAILABLE": False,
}


def _ensure_enhanced_interface() -> bool:
    if _LAZY_STATE["interface_loaded"]:
        return _LAZY_STATE["ENHANCED_INTERFACE_AVAILABLE"]
    _LAZY_STATE["interface_loaded"] = True
    try:
        from .ui.main_window import EnhancedTransformerDialog as _Dialog
        _LAZY_STATE["EnhancedTransformerDialog"] = _Dialog
        _LAZY_STATE["ENHANCED_INTERFACE_AVAILABLE"] = True
        _LAZY_STATE["INTERFACE_IMPORT_ERROR"] = ""
    except Exception as exc:
        _LAZY_STATE["INTERFACE_IMPORT_ERROR"] = str(exc)
        QgsMessageLog.logMessage(
            f"Critical: Interface import failed: {exc}",
            "Transformer", MsgCritical,
        )
        _LAZY_STATE["EnhancedTransformerDialog"] = None
        _LAZY_STATE["ENHANCED_INTERFACE_AVAILABLE"] = False
    return _LAZY_STATE["ENHANCED_INTERFACE_AVAILABLE"]


def _ensure_export_module() -> bool:
    if _LAZY_STATE["export_loaded"]:
        return _LAZY_STATE["EXPORT_MODULE_AVAILABLE"]
    _LAZY_STATE["export_loaded"] = True
    try:
        from .export.export_module import (
            ExportManager as _ExportManager,
            ExportWidget as _ExportWidget,
            EXPORT_AVAILABLE,
        )
        if not EXPORT_AVAILABLE:
            raise ImportError("QGIS not available in export module")
        _LAZY_STATE["ExportManager"] = _ExportManager
        _LAZY_STATE["ExportWidget"] = _ExportWidget
        _LAZY_STATE["EXPORT_MODULE_AVAILABLE"] = True
    except ImportError as exc:
        QgsMessageLog.logMessage(f"Import Error: {exc}", "Transformer", MsgWarning)
        _LAZY_STATE["EXPORT_MODULE_AVAILABLE"] = False
    except Exception as exc:
        QgsMessageLog.logMessage(f"Unexpected Error: {exc}", "Transformer", MsgCritical)
        _LAZY_STATE["EXPORT_MODULE_AVAILABLE"] = False
        import traceback
        QgsMessageLog.logMessage(f"Traceback: {traceback.format_exc()}", "Transformer", MsgCritical)
    return _LAZY_STATE["EXPORT_MODULE_AVAILABLE"]


def __getattr__(name: str):
    if name in ("ENHANCED_INTERFACE_AVAILABLE", "EnhancedTransformerDialog", "INTERFACE_IMPORT_ERROR"):
        _ensure_enhanced_interface()
        return _LAZY_STATE[name]
    if name in ("EXPORT_MODULE_AVAILABLE", "ExportManager", "ExportWidget"):
        _ensure_export_module()
        return _LAZY_STATE[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class TransformerPlugin:
    """Atelier de recettes vectorielles pour QGIS 3.40 - 4.x (Qt 5 / Qt 6)."""

    def __init__(self, iface=None):
        """Plugin constructor (accepts iface=None for headless qgis_process)."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.plugin_name = "Transformer"
        self.provider = None

        # Log runtime environment only in interactive QGIS Desktop sessions
        if self.iface is not None:
            try:
                from .shared.compat import log_environment
                log_environment()
            except Exception as exc:
                QgsMessageLog.logMessage(f"Environment log failed: {exc}", "Transformer", MsgWarning)

        # Main components
        self.config_manager = None
        self.transformer = None
        self.export_manager = None
        self.main_window = None

        # Interface
        self.action = None
        self.doc_action = None
        self.doc_dock = None
        self.menu_text = "Transformer"

        # Interface state
        self.interface_visible = False
        self._project_signals_connected = False
        self._layer_sync_timer = None

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
                    QgsMessageLog.logMessage(f"Loaded translation: {locale}", "Transformer", MsgInfo)
                else:
                    QgsMessageLog.logMessage(f"Failed to load translation: {locale}", "Transformer", MsgWarning)
        except Exception as e:
            QgsMessageLog.logMessage(f"Translation setup failed: {str(e)}", "Transformer", MsgWarning)

    def tr(self, message):
        """Translate messages"""
        return QCoreApplication.translate(self.plugin_name, message)

    def initProcessing(self):
        """Register the native Transformer Processing provider (Desktop and qgis_process)."""
        registry = QgsApplication.processingRegistry()
        if registry is None:
            return
        if self.provider is not None and registry.providerById(self.provider.id()) is self.provider:
            return
        from .processing_provider import TransformerProvider
        existing = registry.providerById("transformer")
        if existing is not None:
            registry.removeProvider(existing)
        self.provider = TransformerProvider(self.plugin_dir)
        registry.addProvider(self.provider)

    def initGui(self):
        """Initialize the plugin user interface and Processing provider."""
        self.initProcessing()
        if self.iface is None:
            return

        from qgis.PyQt.QtGui import QIcon
        from qgis.PyQt.QtWidgets import QMessageBox
        from .shared.compat import QAction

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
            self.action.setWhatsThis(self.tr("Préparer une livraison vectorielle, enregistrer sa recette et la rejouer"))
            self.action.setStatusTip(self.tr("Ouvrir l'atelier de recettes Transformer"))

            # Connecter l'action
            self.action.triggered.connect(self.run)

            # Ajouter l'action au menu et à la barre d'outils
            self.iface.addToolBarIcon(self.action)
            self.iface.addPluginToVectorMenu(self.menu_text, self.action)

            from .shared.icons import icon as ui_icon
            self.doc_action = QAction(
                ui_icon("documentation"),
                self.tr("Tutoriel && Guide Transformer"),
                self.iface.mainWindow()
            )
            self.doc_action.setObjectName("transformer_doc_action")
            self.doc_action.setStatusTip(self.tr("Ouvrir le guide et tutoriel pas à pas dans un dock QGIS"))
            self.doc_action.triggered.connect(self.open_documentation_dock)
            self.iface.addPluginToVectorMenu(self.menu_text, self.doc_action)

            # Initialize components
            self.initialize_components()

            # Listen to project layer changes even before the UI is opened
            self.setup_project_signals()

            # Keep GUI/export modules lazy until the user opens the plugin UI
            QgsMessageLog.logMessage(
                f"Plugin {self.plugin_name} initialized (Processing Provider ready; UI lazy-loaded)",
                "Transformer", MsgInfo
            )

        except Exception as e:
            QgsMessageLog.logMessage(f"Plugin initialization error: {str(e)}", "Transformer", MsgCritical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Erreur d'initialisation",
                f"Impossible d'initialiser le plugin {self.plugin_name} :\n{str(e)}"
            )

    def initialize_components(self):
        """Initialize plugin components"""
        try:
            from .core.config_manager import ConfigManager as SimpleConfigManager
            from .core.transformer import SimpleTransformer

            # Configuration manager
            self.config_manager = SimpleConfigManager(self.plugin_dir)

            # Transformer
            self.transformer = SimpleTransformer(self.config_manager)

        except Exception as e:
            QgsMessageLog.logMessage(f"Component initialization error: {str(e)}", "Transformer", MsgCritical)
            raise

    def unload(self):
        """Unload the plugin"""
        try:
            if self.provider is not None:
                try:
                    registry = QgsApplication.processingRegistry()
                    if registry is not None:
                        registry.removeProvider(self.provider)
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        f"Error removing Processing provider: {exc}",
                        "Transformer", MsgWarning,
                    )
                self.provider = None

            self.teardown_project_signals()

            if self.main_window:
                try:
                    if hasattr(self.main_window, "shutdown_resources"):
                        self.main_window.shutdown_resources()
                    self.main_window.close()
                    self.main_window.deleteLater()
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error closing main window: {exc}", "Transformer", MsgWarning)
                self.main_window = None

            try:
                from .pg.connection_task import PgConnectionPoolManager
                PgConnectionPoolManager.close_all()
            except Exception as exc:
                QgsMessageLog.logMessage(f"Error closing PostgreSQL pools: {exc}", "Transformer", MsgWarning)

            if hasattr(self, "translator") and self.translator is not None:
                try:
                    QCoreApplication.removeTranslator(self.translator)
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error removing translator: {exc}", "Transformer", MsgWarning)
                self.translator = None

            # Remove action
            if self.doc_action:
                try:
                    self.iface.removePluginVectorMenu(self.menu_text, self.doc_action)
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error removing doc menu action: {exc}", "Transformer", MsgWarning)
                self.doc_action = None

            if self.doc_dock:
                try:
                    self.iface.mainWindow().removeDockWidget(self.doc_dock)
                    self.doc_dock.close()
                    self.doc_dock.deleteLater()
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error closing doc dock: {exc}", "Transformer", MsgWarning)
                self.doc_dock = None

            if self.action:
                try:
                    self.iface.removePluginVectorMenu(self.menu_text, self.action)
                    self.iface.removeToolBarIcon(self.action)
                except Exception as exc:
                    QgsMessageLog.logMessage(f"Error removing plugin UI elements: {exc}", "Transformer", MsgWarning)
                self.action = None

            # Clean references
            self.config_manager = None
            self.transformer = None
            self.export_manager = None
            self.interface_visible = False

            QgsMessageLog.logMessage(f"Plugin {self.plugin_name} unloaded", "Transformer", MsgInfo)

        except Exception as e:
            QgsMessageLog.logMessage(f"Plugin unload error: {str(e)}", "Transformer", MsgWarning)

    def open_documentation_dock(self):
        """Ouvre la page HTML du guide utilisateur dans un QDockWidget QGIS."""
        from pathlib import Path
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        from qgis.PyQt.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget
        from .shared.compat import AllDockAreas, RightDockArea

        doc_path = Path(self.plugin_dir) / "docs" / "guide_utilisateur.html"
        if not doc_path.is_file():
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Documentation introuvable",
                f"Le fichier guide_utilisateur.html est introuvable :\n{doc_path}",
            )
            return False
        main_win = self.iface.mainWindow()
        if self.doc_dock is None:
            existing = main_win.findChild(QDockWidget, "transformer_qgis_doc_dock") if main_win else None
            if existing is not None:
                self.doc_dock = existing
            else:
                dock = QDockWidget("Transformer · Guide & Tutoriel", main_win)
                dock.setObjectName("transformer_qgis_doc_dock")
                dock.setAllowedAreas(AllDockAreas)
                container = QWidget(dock)
                layout = QVBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                bar = QFrame(container)
                bar_layout = QHBoxLayout(bar)
                bar_layout.setContentsMargins(8, 6, 8, 6)
                bar_layout.setSpacing(6)
                bar_layout.addWidget(QLabel("Guide & Tutoriel Transformer", bar), 1)
                browser_btn = QPushButton("Ouvrir dans le navigateur", bar)
                browser_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc_path))))
                bar_layout.addWidget(browser_btn)
                layout.addWidget(bar)
                try:
                    from qgis.PyQt.QtWebEngineWidgets import QWebEngineView
                    viewer = QWebEngineView(container)
                    viewer.load(QUrl.fromLocalFile(str(doc_path)))
                except Exception:
                    from qgis.PyQt.QtWidgets import QTextBrowser
                    viewer = QTextBrowser(container)
                    viewer.setOpenExternalLinks(True)
                    viewer.setSearchPaths([str(doc_path.parent)])
                    viewer.setHtml(doc_path.read_text(encoding="utf-8"))
                viewer.setMinimumWidth(420)
                layout.addWidget(viewer, 1)
                dock.setWidget(container)
                dock._html_loaded = True
                if main_win is not None:
                    main_win.addDockWidget(RightDockArea, dock)
                self.doc_dock = dock
        self.doc_dock.show()
        self.doc_dock.raise_()
        return True

    def run(self):
        """Execute the plugin"""
        from qgis.PyQt.QtWidgets import QMessageBox
        try:
            if not self.config_manager or not self.transformer:
                self.initialize_components()

            if not _ensure_enhanced_interface():
                detail = _LAZY_STATE["INTERFACE_IMPORT_ERROR"] or "Erreur d'import inconnue."
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Erreur",
                    f"L'interface du plugin n'a pas pu être chargée.\n\n{detail}"
                )
                return

            self.run_enhanced_interface()

        except Exception as e:
            QgsMessageLog.logMessage(f"Interface opening error: {str(e)}", "Transformer", MsgCritical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Erreur",
                f"Impossible d'ouvrir l'interface du plugin :\n{str(e)}"
            )

    def run_enhanced_interface(self):
        """Launch enhanced professional interface"""
        from qgis.PyQt.QtWidgets import QMessageBox
        try:
            if self.main_window is None:
                dialog_cls = _LAZY_STATE["EnhancedTransformerDialog"]
                self.main_window = dialog_cls(
                    self.config_manager,
                    self.transformer,
                    self.iface.mainWindow()
                )
                self.main_window.setVisible(False)
                self.setup_enhanced_interface_connections()
                self.center_window()

            # Show or hide interface
            if self.interface_visible and self.main_window.isVisible():
                self.main_window.hide()
                self.interface_visible = False
            else:
                self.main_window.setVisible(True)
                self.interface_visible = True

        except Exception as e:
            QgsMessageLog.logMessage(f"Enhanced interface error: {str(e)}", "Transformer", MsgCritical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Erreur",
                f"Erreur de l'interface Transformer :\n{str(e)}"
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

        if self._layer_sync_timer is not None:
            try:
                self._layer_sync_timer.stop()
            except RuntimeError:
                pass
            self._layer_sync_timer = None

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
            QgsMessageLog.logMessage(f"Enhanced interface connections error: {str(e)}", "Transformer", MsgWarning)

    def center_window(self):
        """Center the main window on the screen (before show)."""
        if not self.main_window:
            return

        from qgis.PyQt.QtWidgets import QApplication
        try:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geometry = screen.availableGeometry()
                win_size = self.main_window.size()
                x = screen_geometry.x() + (screen_geometry.width() - win_size.width()) // 2
                y = screen_geometry.y() + (screen_geometry.height() - win_size.height()) // 2
                self.main_window.move(x, y)

        except Exception as e:
            QgsMessageLog.logMessage(f"Window centering error: {str(e)}", "Transformer", MsgWarning)

    def on_enhanced_interface_closed(self):
        """Handle the closing of the enhanced interface"""
        self.interface_visible = False
        QgsMessageLog.logMessage("Enhanced interface closed", "Transformer", MsgInfo)

    def _schedule_interface_refresh(self, delay_ms=250):
        """Coalesce project refreshes and defer work when the main window is hidden."""
        win = self.main_window
        if win is None:
            return
        if hasattr(win, '_schedule_project_sync'):
            win._schedule_project_sync(delay_ms)
            return
        if not win.isVisible():
            win._layers_dirty = True
            return
        if self._layer_sync_timer is None:
            self._layer_sync_timer = QTimer()
            self._layer_sync_timer.setSingleShot(True)
            self._layer_sync_timer.timeout.connect(self.refresh_interface_layers)
        self._layer_sync_timer.start(max(0, int(delay_ms)))

    def on_layers_added(self, layers):
        """Handle the addition of layers to the project"""
        if self.main_window and layers:
            self._schedule_interface_refresh(250)

    def on_layers_removed(self, layer_ids):
        """Handle the removal of layers from the project"""
        if self.main_window and layer_ids:
            self._schedule_interface_refresh(250)

    def on_project_read(self, *_args):
        """Handle QGIS project reload."""
        if self.main_window:
            self._schedule_interface_refresh(500)

    def on_project_cleared(self):
        """Handle QGIS project cleared."""
        if self.main_window:
            self._schedule_interface_refresh(100)

    def refresh_interface_layers(self):
        """Refresh layers in the interface"""
        try:
            if self.main_window and hasattr(self.main_window, 'sync_layers_from_project'):
                self.main_window.sync_layers_from_project()
                QgsMessageLog.logMessage("Interface layers refreshed", "Transformer", MsgInfo)
        except Exception as e:
            QgsMessageLog.logMessage(f"Layer refresh error: {str(e)}", "Transformer", MsgWarning)

    def handle_transformation_request(self, shapefile_path: str):
        """Handle transformation requests"""
        try:
            QgsMessageLog.logMessage(f"Transformation request handled: {shapefile_path}", "Transformer", MsgInfo)

            # Refresh layers after transformation
            QTimer.singleShot(1000, self.refresh_interface_layers)

        except Exception as e:
            QgsMessageLog.logMessage(f"Transformation request error: {str(e)}", "Transformer", MsgWarning)
