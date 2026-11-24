# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Interface Configuration Classes
Separated to avoid circular imports
"""

from dataclasses import dataclass, fields
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
    compact_toolbar: bool = False
    expression_syntax_highlighting: bool = True
    auto_complete_expressions: bool = True
    max_undo_steps: int = 30
    show_performance_stats: bool = False
    enable_debugging: bool = False
    auto_backup_interval: int = 300

    def load(self, qsettings=None):
        """Load this instance; injected QSettings keeps tests/profile use isolated."""
        if qsettings is None:
            from qgis.PyQt.QtCore import QSettings
            qsettings = QSettings()
        for field in fields(self):
            default = getattr(self, field.name)
            value = qsettings.value(f"Transformer/interface/{field.name}", default)
            if isinstance(default, bool):
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "oui")
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError, OverflowError):
                    value = default
            elif isinstance(default, Enum):
                try:
                    value = type(default)(value)
                except (ValueError, TypeError):
                    value = default
            setattr(self, field.name, value)
        self.theme = InterfaceTheme.QGIS_NATIVE
        self.max_undo_steps = min(100, max(10, self.max_undo_steps))
        self.auto_backup_interval = min(3600, max(60, self.auto_backup_interval))
        return self

    def save(self, qsettings=None):
        """Persist explicit settings and return whether QSettings reports success."""
        if qsettings is None:
            from qgis.PyQt.QtCore import QSettings
            qsettings = QSettings()
        self.theme = InterfaceTheme.QGIS_NATIVE
        for field in fields(self):
            value = getattr(self, field.name)
            qsettings.setValue(f"Transformer/interface/{field.name}", value.value if isinstance(value, Enum) else value)
        qsettings.setValue("Transformer/theme", self.theme.value)
        if hasattr(qsettings, "sync"):
            qsettings.sync()
        if not hasattr(qsettings, "status"):
            return True
        status = qsettings.status()
        return int(status.value if hasattr(status, "value") else status) == 0


def windows_reduced_motion() -> bool:
    """Read the Windows animation preference without changing system settings."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        enabled = wintypes.BOOL()
        query = ctypes.windll.user32.SystemParametersInfoW
        query.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT)
        query.restype = wintypes.BOOL
        # SPI_GETCLIENTAREAANIMATION, available since Windows Vista.
        return bool(query(0x1042, 0, ctypes.byref(enabled), 0)) and not bool(enabled.value)
    except (AttributeError, OSError, ValueError):
        return False


def animations_enabled(settings=None) -> bool:
    """Explicit application preference and system accessibility both take effect."""
    return bool(getattr(settings, "enable_animations", True)) and not windows_reduced_motion()
