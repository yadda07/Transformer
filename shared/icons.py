# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Tabler outline SVG icons with enterprise semantic coloring."""

import base64
import os
import re
from enum import Enum
from functools import lru_cache
from typing import Optional, Union

from qgis.PyQt.QtCore import QByteArray, QSize, QTimer
from qgis.PyQt.QtGui import QIcon, QPainter, QPixmap, QColor
from qgis.PyQt.QtWidgets import QApplication

from .compat import (
    Antialias,
    CompositionSourceIn,
    GlobalTransparent,
    IconModeDisabled,
    IconModeNormal,
    IconStateOff,
    PaletteButtonText,
    PaletteGroupDisabled,
    palette_color,
)

try:
    from qgis.PyQt.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SVG_DIR = os.path.join(_PLUGIN_ROOT, "svg", "outline")

_SVG_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_VIEWBOX_24_RE = re.compile(r'viewBox\s*=\s*"0 0 24 24"')
_STROKE_WIDTH_RE = re.compile(r'stroke-width="[\d.]+"')


class IconTone(Enum):
    """Semantic icon colors : enterprise visual language."""

    ACTION = "action"
    SUCCESS = "success"
    DANGER = "danger"
    WARNING = "warning"
    ACCENT = "accent"
    NEUTRAL = "neutral"
    MUTED = "muted"
    INFO = "info"
    DATA_POINT = "data_point"
    DATA_LINE = "data_line"
    DATA_POLYGON = "data_polygon"
    DATA_TABLE = "data_table"
    DATA_LAYER = "data_layer"
    DATA_GEOMETRY = "data_geometry"
    DATA_DATE = "data_date"
    DATA_NUMBER = "data_number"
    DATA_TEXT = "data_text"


# Dark / light palettes tuned for contrast on QGIS backgrounds.
_PALETTE = {
    True: {
        IconTone.ACTION: "#E11D48",
        IconTone.SUCCESS: "#4ADE80",
        IconTone.DANGER: "#FB7185",
        IconTone.WARNING: "#FBBF24",
        IconTone.ACCENT: "#F97316",
        IconTone.NEUTRAL: "#F1F5F9",
        IconTone.MUTED: "#CBD5E1",
        IconTone.INFO: "#67E8F9",
        IconTone.DATA_POINT: "#F472B6",
        IconTone.DATA_LINE: "#93C5FD",
        IconTone.DATA_POLYGON: "#6EE7B7",
        IconTone.DATA_TABLE: "#C4B5FD",
        IconTone.DATA_LAYER: "#94A3B8",
        IconTone.DATA_GEOMETRY: "#C4B5FD",
        IconTone.DATA_DATE: "#FCD34D",
        IconTone.DATA_NUMBER: "#34D399",
        IconTone.DATA_TEXT: "#E2E8F0",
    },
    False: {
        IconTone.ACTION: "#BE123C",
        IconTone.SUCCESS: "#15803D",
        IconTone.DANGER: "#DC2626",
        IconTone.WARNING: "#B45309",
        IconTone.ACCENT: "#C2410C",
        IconTone.NEUTRAL: "#334155",
        IconTone.MUTED: "#64748B",
        IconTone.INFO: "#0369A1",
        IconTone.DATA_POINT: "#DB2777",
        IconTone.DATA_LINE: "#2563EB",
        IconTone.DATA_POLYGON: "#059669",
        IconTone.DATA_TABLE: "#7C3AED",
        IconTone.DATA_LAYER: "#475569",
        IconTone.DATA_GEOMETRY: "#7C3AED",
        IconTone.DATA_DATE: "#CA8A04",
        IconTone.DATA_NUMBER: "#047857",
        IconTone.DATA_TEXT: "#475569",
    },
}

_ICONS = {
    "add_layer": "map-plus",
    "refresh": "refresh",
    "validate": "circle-check",
    "save": "device-floppy",
    "play": "player-play",
    "transform": "player-play",
    "batch": "player-skip-forward",
    "config": "settings",
    "export": "file-export",
    "postgresql": "database",
    "expression": "math-function",
    "fields": "columns",
    "remove": "trash",
    "duplicate": "copy",
    "clear": "x",
    "history": "history",
    "help": "help-circle",
    "documentation": "book-open",
    "about": "info-circle",
    "new": "file-plus",
    "open": "folder-open",
    "preferences": "settings",
    "window": "transform",
    "layout": "layout-grid",
    "options": "settings-2",
    "move": "arrows-move",
    "resize": "resize",
    "float": "window-maximize",
    "show_all_layers": "layers-linked",
    "layers": "layers-linked",
    "point_layer": "point",
    "line_layer": "line",
    "polygon_layer": "polygon",
    "table_layer": "table",
    "layer": "map",
    "geometry": "geometry",
    "datetime": "calendar",
    "number": "numbers",
    "text": "letter-t",
    "table_config": "table",
    "filter": "filter",
    "show_all": "eye",
    "compare": "eye",
    "edit": "transform",
    "warning": "alert-triangle",
    "field_string": "letter-t",
    "field_int": "binary",
    "field_float": "decimal",
    "field_bool": "checkbox",
    "field_date": "calendar",
    "field_geometry": "geometry",
    "log_debug": "terminal-2",
    "log_info": "info-circle",
    "log_warning": "alert-triangle",
    "log_error": "circle-x",
    "log_critical": "alert-octagon",
    "log_success": "circle-check",
    "log_pause": "player-pause",
    "log_resume": "player-play",
    "log_clear": "trash",
    "log_export": "download",
    "log_search": "search",
    "log_module_system": "cpu",
    "log_module_transformer": "transform",
    "log_module_exporter": "file-export",
    "log_module_db": "database",
    "log_module_ui": "layout-grid",
    "log_code_transform": "transform",
    "log_code_export": "file-export",
    "log_code_db": "database",
}

_ICON_TONES = {
    "add_layer": IconTone.ACTION,
    "refresh": IconTone.ACTION,
    "validate": IconTone.ACTION,
    "save": IconTone.ACTION,
    "play": IconTone.ACTION,
    "transform": IconTone.ACTION,
    "batch": IconTone.ACTION,
    "new": IconTone.ACTION,
    "open": IconTone.ACTION,
    "window": IconTone.ACTION,
    "remove": IconTone.DANGER,
    "clear": IconTone.DANGER,
    "config": IconTone.NEUTRAL,
    "export": IconTone.NEUTRAL,
    "postgresql": IconTone.NEUTRAL,
    "expression": IconTone.ACTION,
    "fields": IconTone.NEUTRAL,
    "filter": IconTone.NEUTRAL,
    "table_config": IconTone.NEUTRAL,
    "duplicate": IconTone.MUTED,
    "history": IconTone.MUTED,
    "help": IconTone.INFO,
    "documentation": IconTone.INFO,
    "about": IconTone.INFO,
    "preferences": IconTone.MUTED,
    "layout": IconTone.MUTED,
    "options": IconTone.MUTED,
    "move": IconTone.MUTED,
    "resize": IconTone.MUTED,
    "float": IconTone.MUTED,
    "show_all_layers": IconTone.MUTED,
    "layers": IconTone.DATA_LAYER,
    "show_all": IconTone.MUTED,
    "compare": IconTone.ACTION,
    "edit": IconTone.ACCENT,
    "warning": IconTone.WARNING,
    "point_layer": IconTone.DATA_POINT,
    "line_layer": IconTone.DATA_LINE,
    "polygon_layer": IconTone.DATA_POLYGON,
    "table_layer": IconTone.DATA_TABLE,
    "layer": IconTone.DATA_LAYER,
    "geometry": IconTone.DATA_GEOMETRY,
    "datetime": IconTone.DATA_DATE,
    "number": IconTone.DATA_NUMBER,
    "text": IconTone.DATA_TEXT,
    "field_string": IconTone.NEUTRAL,
    "field_int": IconTone.NEUTRAL,
    "field_float": IconTone.NEUTRAL,
    "field_bool": IconTone.NEUTRAL,
    "field_date": IconTone.NEUTRAL,
    "field_geometry": IconTone.NEUTRAL,
    "log_debug": IconTone.MUTED,
    "log_info": IconTone.INFO,
    "log_warning": IconTone.WARNING,
    "log_error": IconTone.DANGER,
    "log_critical": IconTone.DANGER,
    "log_success": IconTone.SUCCESS,
    "log_pause": IconTone.NEUTRAL,
    "log_resume": IconTone.ACTION,
    "log_clear": IconTone.DANGER,
    "log_export": IconTone.NEUTRAL,
    "log_search": IconTone.MUTED,
    "log_module_system": IconTone.MUTED,
    "log_module_transformer": IconTone.ACTION,
    "log_module_exporter": IconTone.ACCENT,
    "log_module_db": IconTone.INFO,
    "log_module_ui": IconTone.NEUTRAL,
    "log_code_transform": IconTone.ACTION,
    "log_code_export": IconTone.ACCENT,
    "log_code_db": IconTone.INFO,
}


def _is_dark_theme() -> bool:
    app = QApplication.instance()
    if app is None:
        return True
    palette = app.palette()
    window = palette_color(palette, None, 'Window')
    base = palette_color(palette, None, 'Base')
    text = palette_color(palette, None, 'WindowText')
    # QGIS dark UI: dark surfaces but windowText can stay black ; use surfaces.
    bg_lightness = min(window.lightness(), base.lightness())
    if bg_lightness < 128:
        return True
    if text.lightness() > 180 and bg_lightness > 140:
        return False
    return bg_lightness < 140


def _tone_color(tone: IconTone, dark: bool) -> str:
    app = QApplication.instance()
    if app is not None and tone == IconTone.ACTION:
        candidate = palette_color(app.palette(), None, 'Highlight')
        if dark and candidate.lightness() < 115:
            return _PALETTE[True][IconTone.ACTION]
        if not dark and candidate.lightness() > 190:
            return _PALETTE[False][IconTone.ACTION]
        return candidate.name()
    if app is not None and tone == IconTone.NEUTRAL:
        candidate = palette_color(app.palette(), None, 'WindowText')
        if dark and candidate.lightness() < 175:
            return _PALETTE[True][IconTone.NEUTRAL]
        if not dark and candidate.lightness() > 100:
            return _PALETTE[False][IconTone.NEUTRAL]
        return candidate.name()
    return _PALETTE[dark].get(tone, _PALETTE[dark][IconTone.ACTION])


@lru_cache(maxsize=256)
def _load_raw_svg(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        markup = handle.read()
    markup = _SVG_COMMENT_RE.sub("", markup).strip()
    return markup, bool(_VIEWBOX_24_RE.search(markup))


def _read_svg_markup(path: str, color: str, size: int = 24) -> str:
    markup, has_viewbox_24 = _load_raw_svg(path)
    if has_viewbox_24:
        # Logical sizes 16/18/20/24 all retain a 1.5 px optical stroke.
        stroke = min(2.25, max(1.5, 1.5 * 24 / max(1, size)))
        markup = _STROKE_WIDTH_RE.sub('stroke-width="%s"' % format(stroke, '.3g'), markup, count=1)
    return markup.replace("currentColor", color)


def _render_svg_icon(path: str, color: str) -> QIcon:
    if QSvgRenderer is None:
        return QIcon(path)

    qicon = QIcon()
    app = QApplication.instance()
    scales = {1.0, 2.0}
    disabled_color = None
    if app:
        scales.update(round(screen.devicePixelRatio(), 2) for screen in app.screens())
        # Disabled glyphs remain legible on the real disabled surface.
        dark = _is_dark_theme()
        muted_col = app.palette().color(PaletteGroupDisabled, PaletteButtonText)
        if dark and muted_col.lightness() < 120:
            muted = "#94A3B8"
        elif not dark and muted_col.lightness() > 170:
            muted = "#64748B"
        else:
            muted = muted_col.name()
        if muted != color:
            disabled_color = QColor(muted)

    sorted_scales = sorted(scales)
    for size in (16, 18, 20, 24, 32):
        renderer = QSvgRenderer(QByteArray(_read_svg_markup(path, color, size).encode("utf-8")))
        if not renderer.isValid():
            return QIcon(path)
        for scale in sorted_scales:
            physical = max(1, round(size * scale))
            pixmap = QPixmap(QSize(physical, physical))
            pixmap.fill(GlobalTransparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(Antialias)
            renderer.render(painter)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            qicon.addPixmap(pixmap, IconModeNormal, IconStateOff)
            if disabled_color is not None:
                disabled_pm = pixmap.copy()
                disabled_pm.setDevicePixelRatio(1.0)
                tint = QPainter(disabled_pm)
                tint.setCompositionMode(CompositionSourceIn)
                tint.fillRect(disabled_pm.rect(), disabled_color)
                tint.end()
                disabled_pm.setDevicePixelRatio(scale)
                qicon.addPixmap(disabled_pm, IconModeDisabled, IconStateOff)
    return qicon


def _resolve_tone(name: str, tone: Optional[Union[IconTone, str]]) -> IconTone:
    if tone is None:
        return _ICON_TONES.get(name, IconTone.ACTION)
    if isinstance(tone, str):
        return IconTone(tone)
    return tone


def icon(name: str, tone: Optional[Union[IconTone, str]] = None) -> QIcon:
    """Return a cached QIcon with semantic coloring."""
    svg_name = _ICONS.get(name)
    if not svg_name:
        return QIcon()
    path = os.path.join(_SVG_DIR, f"{svg_name}.svg")
    if not os.path.exists(path):
        return QIcon()

    resolved = _resolve_tone(name, tone)
    dark = _is_dark_theme()
    color = _tone_color(resolved, dark)
    app = QApplication.instance()
    # The cache key follows palette and screen changes, even before a caller refreshes.
    palette_key = app.palette().cacheKey() if app else 0
    scales = tuple(round(screen.devicePixelRatio(), 2) for screen in app.screens()) if app else ()
    return _cached_icon(path, color, palette_key, scales)


@lru_cache(maxsize=256)
def _cached_icon(path, color, palette_key, scales):
    return _render_svg_icon(path, color)


# Preserve the cache helpers used by existing callers and diagnostics.
icon.cache_clear = _cached_icon.cache_clear
icon.cache_info = _cached_icon.cache_info


def svg_html(
    svg_name: str,
    tone: Union[IconTone, str] = IconTone.ACTION,
    size: int = 14,
) -> str:
    """Return an HTML img tag with a tone-colored SVG for RichText labels."""
    path = os.path.join(_SVG_DIR, f"{svg_name}.svg")
    if not os.path.exists(path):
        return ""

    if isinstance(tone, str):
        tone = IconTone(tone)
    dark = _is_dark_theme()
    color = _tone_color(tone, dark)
    markup = _read_svg_markup(path, color, size)
    encoded = base64.b64encode(markup.encode("utf-8")).decode("ascii")
    return (
        f'<img src="data:image/svg+xml;base64,{encoded}" '
        f'width="{size}" height="{size}" style="vertical-align: middle;" />'
    )


def clear_icon_cache() -> None:
    """Drop cached pixmaps (e.g. after theme change)."""
    icon.cache_clear()


def set_action_outcome(action, name: str, outcome: Optional[bool], duration_ms: int = 2500) -> None:
    """Flash success (green) or warning (amber), then restore default tone."""
    if outcome is True:
        action.setIcon(icon(name, IconTone.SUCCESS))
    elif outcome is False:
        action.setIcon(icon(name, IconTone.WARNING))
    else:
        action.setIcon(icon(name))
        return

    QTimer.singleShot(duration_ms, lambda: action.setIcon(icon(name)))


def set_actions_outcome(actions, name: str, outcome: Optional[bool], duration_ms: int = 2500) -> None:
    """Apply outcome coloring to several actions at once."""
    for action in actions:
        if action is not None:
            set_action_outcome(action, name, outcome, duration_ms)
