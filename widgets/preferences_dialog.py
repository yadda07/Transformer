# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Preferences that expose only the implemented native appearance controls."""

import copy

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QCheckBox, QDialogButtonBox,
    QLabel, QMessageBox,
)
from ..shared.compat import (
    DlgBtnCancel,
    DlgBtnOk,
    DlgBtnRestoreDefaults,
    FormWrapLongRows,
)
from ..shared.interface_config import InterfaceTheme, InterfaceSettings
from ..shared.helpers import get_plugin_icon


class PreferencesDialog(QDialog):
    def __init__(self, settings: InterfaceSettings, parent=None, qsettings=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        self._qsettings = qsettings
        self.setWindowTitle("Transformer : préférences")
        self.setWindowIcon(get_plugin_icon())
        self.setModal(True)
        self.resize(440, 240)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setRowWrapPolicy(FormWrapLongRows)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("QGIS natif", InterfaceTheme.QGIS_NATIVE)
        self.theme_combo.setAccessibleName("Apparence")
        self.theme_combo.setAccessibleDescription("La palette et la police de QGIS sont utilisées.")
        form.addRow("&Apparence :", self.theme_combo)
        self.tooltips_cb = QCheckBox("Afficher les &bulles d'aide")
        form.addRow(self.tooltips_cb)
        layout.addLayout(form)
        note = QLabel("Couleurs, contraste et police suivent QGIS.\nLes commandes et onglets utilisent les interactions natives de Qt.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.buttons = QDialogButtonBox(
            DlgBtnOk | DlgBtnCancel | DlgBtnRestoreDefaults
        )
        self.buttons.button(DlgBtnOk).setText("Enregistrer")
        self.buttons.button(DlgBtnCancel).setText("Annuler")
        self.buttons.button(DlgBtnRestoreDefaults).setText("Valeurs initiales")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(DlgBtnRestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(self.buttons)
        self.setTabOrder(self.theme_combo, self.tooltips_cb)
        self.setTabOrder(self.tooltips_cb, self.buttons.button(DlgBtnOk))
        self.buttons.button(DlgBtnOk).setDefault(True)

    def load_settings(self):
        self.theme_combo.setCurrentIndex(0)
        self.tooltips_cb.setChecked(self.settings.show_tooltips)

    def save_settings(self):
        self.settings.theme = InterfaceTheme.QGIS_NATIVE
        self.settings.show_tooltips = self.tooltips_cb.isChecked()

    def restore_defaults(self):
        self.settings = InterfaceSettings()
        self.load_settings()

    def accept(self):
        self.save_settings()
        try:
            saved = self.settings.save(self._qsettings)
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Préférences non enregistrées", f"Le profil QGIS n'a pas accepté ces préférences :\n{error}\nVérifiez son accès puis réessayez.")
            return
        if not saved:
            QMessageBox.warning(self, "Préférences non enregistrées", "QGIS n'a pas pu enregistrer ces préférences. Vérifiez que le profil est accessible, puis réessayez.")
            return
        super().accept()

    def get_settings(self) -> InterfaceSettings:
        return copy.deepcopy(self.settings)
