# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Native Qt tabs, retaining the existing help-widget public API."""

from qgis.PyQt.QtWidgets import QTabWidget

from ..shared.compat import FocusStrongFocus, TabSouth, TextElideNone


class SlidingTabWidget(QTabWidget):
    """QTabWidget supplies keyboard navigation and native accessible tab roles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transformer_help_tabs")
        self.setAccessibleName("Aide de la recette")
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)
        self.setTabPosition(TabSouth)
        self._bar = self.tabBar()
        self._bar.setAccessibleName("Rubriques de l'aide")
        self._bar.setAccessibleDescription("Parcourez les rubriques avec les touches fléchées.")
        self._bar.setFocusPolicy(FocusStrongFocus)
        self._bar.setElideMode(TextElideNone)
