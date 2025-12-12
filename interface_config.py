# -*- coding: utf-8 -*-
"""
Interface Configuration Classes
Separated to avoid circular imports
"""

from dataclasses import dataclass
from enum import Enum

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
