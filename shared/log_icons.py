# -*- coding: utf-8 -*-
"""Semantic SVG icons for the Activity Log / Log Monitor."""

from qgis.PyQt.QtGui import QIcon

from .icons import IconTone, icon

_SEVERITY_KEYS = {
    "debug": "log_debug",
    "info": "log_info",
    "warning": "log_warning",
    "error": "log_error",
    "critical": "log_critical",
}

_MODULE_KEYS = {
    "system": "log_module_system",
    "transformer": "log_module_transformer",
    "exporter": "log_module_exporter",
    "db": "log_module_db",
    "ui": "log_module_ui",
}

_CODE_PREFIX_KEYS = (
    ("TRANSFORM", "log_code_transform"),
    ("EXPORT", "log_code_export"),
    ("DB_", "log_code_db"),
    ("TABLE_", "log_code_db"),
    ("DATA_", "log_code_db"),
)


def severity_icon(severity: str, code: str = "") -> QIcon:
    """Icon for a log severity level (with SUCCESS code override)."""
    code_upper = (code or "").upper()
    if code_upper in ("SUCCESS",) or code_upper.endswith("_SUCCESS"):
        return icon("log_success", IconTone.SUCCESS)
    key = _SEVERITY_KEYS.get((severity or "info").lower(), "log_info")
    return icon(key)


def module_icon(module: str) -> QIcon:
    """Icon for a log module (transformer, db, ui…)."""
    key = _MODULE_KEYS.get((module or "system").lower(), "log_module_system")
    return icon(key)


def code_icon(code: str) -> QIcon:
    """Icon for a standardized log code tag."""
    code_upper = (code or "").upper()
    if not code_upper:
        return QIcon()
    if code_upper in ("SUCCESS",) or code_upper.endswith("_SUCCESS"):
        return icon("log_success", IconTone.SUCCESS)
    for prefix, key in _CODE_PREFIX_KEYS:
        if code_upper.startswith(prefix):
            return icon(key)
    return icon("log_info", IconTone.MUTED)


def log_toolbar_icon(name: str) -> QIcon:
    """Icons for log monitor toolbar controls."""
    return icon(name)
