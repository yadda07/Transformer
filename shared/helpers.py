# -*- coding: utf-8 -*-
"""
Shared utility helpers used across the Transformer plugin.

Centralizes cross-cutting logic that was previously duplicated:
- Plugin icon resolution (DUP-10)
- Expression context creation (DUP-01)
"""

import os

from qgis.core import (
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsVectorLayer,
    QgsFeature,
)
from qgis.PyQt.QtGui import QIcon


_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_plugin_icon() -> QIcon:
    """Return the plugin logo icon.

    The logo.png file lives at the plugin root, not in subdirectories.
    Returns an empty QIcon if the file is missing.
    """
    logo_path = os.path.join(_PLUGIN_ROOT, "logo.png")
    if os.path.exists(logo_path):
        return QIcon(logo_path)
    return QIcon()


def create_layer_expression_context(
    layer: QgsVectorLayer,
    feature: QgsFeature = None,
) -> QgsExpressionContext:
    """Build a QgsExpressionContext with global, project, and layer scopes.

    Optionally sets a feature on the context.

    Args:
        layer: The source vector layer for scope generation.
        feature: Optional feature to set on the context.

    Returns:
        A configured QgsExpressionContext ready for expression evaluation.
    """
    context = QgsExpressionContext()
    context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    context.setFields(layer.fields())
    if feature is not None:
        context.setFeature(feature)
    return context


def is_filter_enabled(filter_config) -> bool:
    """Return whether a filter config dict is enabled and non-empty.

    None-safe; treats missing or malformed config as disabled.
    """
    if not filter_config:
        return False
    return bool(filter_config.get("enabled", False)) and bool(filter_config.get("expression", "").strip())


def get_filter_expression(filter_config) -> str:
    """Return the trimmed filter expression from a filter config dict.

    Returns an empty string if the config is missing or disabled.
    """
    if not is_filter_enabled(filter_config):
        return ""
    return str(filter_config.get("expression", "")).strip()


def apply_compact_button(button, max_width=None, max_height=None):
    """Cap button height to match compact inline controls (e.g. Smart Filter)."""
    from .constants import COMPACT_BUTTON_MAX_HEIGHT

    height = max_height if max_height is not None else COMPACT_BUTTON_MAX_HEIGHT
    button.setMaximumHeight(height)
    if max_width is not None:
        button.setMaximumWidth(max_width)
