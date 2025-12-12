# -*- coding: utf-8 -*-
import os
import copy
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget, QComboBox, 
    QCheckBox, QSpinBox, QDialogButtonBox, QLabel
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

# Import des enums depuis le fichier de configuration
from .interface_config import InterfaceTheme, InterfaceSettings

class PreferencesDialog(QDialog):
    """Preferences dialog"""
    
    def __init__(self, settings: InterfaceSettings, parent=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        
        self.setWindowTitle("Transformer - Preferences")
        self.setModal(True)
        self.resize(500, 400)
        
        # Définir l'icône du dialog avec le logo
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
        
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

