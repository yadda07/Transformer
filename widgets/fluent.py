# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Native widget contracts with fixed geometry and interruptible painted motion."""

from functools import lru_cache
import weakref

try:
    from qgis.PyQt import sip as _sip
except ImportError:
    _sip = None

from qgis.PyQt.QtCore import (
    QObject, QPointF, QRectF, QSize, QTimer, QVariantAnimation,
)
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QIcon
from qgis.PyQt.QtWidgets import (
    QApplication, QLabel, QPushButton, QStyleOptionButton,
    QTabBar, QTabWidget, QWidget,
)

from ..shared import interface_config
from ..shared.compat import (
    Antialias,
    BrushNoBrush,
    CompositionSourceIn,
    EaseOutCubic,
    EventApplicationFontChange,
    EventApplicationPaletteChange,
    EventDynamicPropertyChange,
    EventEnabledChange,
    EventFontChange,
    EventHide,
    EventKeyPress,
    EventMouseButtonPress,
    EventPaletteChange,
    EventResize,
    EventShow,
    EventWindowActivate,
    EventWindowDeactivate,
    FocusNoFocus,
    FocusStrongFocus,
    FontDemiBold,
    ImageFormatARGB32Premultiplied,
    KeyEnter,
    KeyReturn,
    KeySpace,
    NoPen,
    PaletteButton,
    PaletteButtonText,
    PaletteGroupActive,
    PaletteGroupDisabled,
    PaletteGroupInactive,
    PaletteHighlight,
    PaletteWindow,
    PenCapRound,
    PenSolidLine,
    PlainText,
    PointingHandCursor,
    SizePolicyExpanding,
    SizePolicyPreferred,
    StyleCEPushButtonLabel,
    StyleStateEnabled,
    TextElideNone,
    TextWordWrap,
    WidgetAttrNoSystemBackground,
    WidgetAttrTransparentForMouse,
    font_database_families,
    icon_pixmap,
)
from ..shared.icons import icon as ui_icon

MICRO_MS = 140
FEEDBACK_MS = 180
NAVIGATION_MS = 240


def _mix(first, second, weight):
    a, b = QColor(first), QColor(second)
    return QColor.fromRgbF(*(a.getRgbF()[i] * (1 - weight) + b.getRgbF()[i] * weight for i in range(4)))


def _settings(widget):
    current = widget
    while current is not None:
        settings = getattr(current, "interface_settings", None)
        if settings is not None:
            return settings
        current = current.parentWidget()
    return None


def _context(widget):
    current = widget
    while current is not None:
        found = getattr(current, "_fluent_context", None)
        if found is not None:
            return found
        current = current.parentWidget()
    return None


def _motion(widget):
    context = _context(widget)
    return (widget.isVisible() and not getattr(widget, "_keyboard", False)
            and not (context and (context.keyboard or context.reduced))
            and interface_config.animations_enabled(_settings(widget)))


def _animation(owner, callback):
    animation = QVariantAnimation(owner)
    animation.setEasingCurve(EaseOutCubic)
    animation.valueChanged.connect(callback)
    return animation


@lru_cache(maxsize=8)
def _grain(dpr):
    """A tiny deterministic tile, shared by surfaces and never regenerated per frame."""
    size = max(16, round(16 * dpr))
    image = QImage(size, size, ImageFormatARGB32Premultiplied)
    for y in range(size):
        for x in range(size):
            level = ((x * 1973 + y * 9277 + x * y * 26699) ^ (x << 4)) & 255
            image.setPixelColor(x, y, QColor(level, level, level, 255))
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


_FONT_FAMILY_SET_CACHE = None


def _font_family_set():
    global _FONT_FAMILY_SET_CACHE
    if _FONT_FAMILY_SET_CACHE is not None:
        return _FONT_FAMILY_SET_CACHE
    families = frozenset(font_database_families())
    if families and QApplication.instance() is not None:
        _FONT_FAMILY_SET_CACHE = families
    return families


def role_font(widget, role="body"):
    """Resolve installed display faces while keeping the QGIS body font and scale."""
    font = QFont(QApplication.font() if QApplication.instance() else widget.font())
    point = font.pointSizeF() if font.pointSizeF() > 0 else 10.0
    if role in ("title", "section", "number"):
        families = _font_family_set()
        for family in ("Bahnschrift", "Segoe UI Variable Display", "Segoe UI Semibold"):
            if family in families:
                font.setFamily(family)
                break
        font.setWeight(FontDemiBold)
    factor = {"title": 1.8, "section": 1.15, "number": 1.5, "meta": .93}.get(role, 1.0)
    font.setPointSizeF(max(9.0, point * factor))
    return font


class _Surface(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("transformerFluentMaterial")
        self.setAttribute(WidgetAttrTransparentForMouse)
        self.setAttribute(WidgetAttrNoSystemBackground)
        self.setFocusPolicy(FocusNoFocus)
        self.setGeometry(parent.rect())
        self.lower()

    def paintEvent(self, event):
        painter = QPainter(self)
        base = self.parentWidget().palette().color(PaletteWindow)
        dark = base.lightnessF() < .5
        canvas = _mix(base, QColor("#11161d" if dark else "#e8eef5"), .35)
        painter.fillRect(self.rect(), canvas)
        accent = self.parentWidget().palette().color(PaletteHighlight)
        if dark and accent.lightnessF() < .38:
            accent = QColor("#38bdf8")
        painter.fillRect(QRectF(0, 0, self.width(), 2), accent)


class _InputModeFilter(QObject):
    """Lightweight global filter attached only while the root window is active and visible."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self._ctx = ctx

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind != EventKeyPress and kind != EventMouseButtonPress:
            return False
        ctx = self._ctx
        root = ctx.root
        if root is None:
            ctx._detach_app_filter()
            return False
        if _sip is not None and (_sip.isdeleted(root) or _sip.isdeleted(watched)):
            if _sip.isdeleted(root):
                ctx._detach()
            return False
        if not isinstance(watched, QWidget):
            return False
        try:
            belongs = watched is root or root.isAncestorOf(watched)
        except RuntimeError:
            ctx._detach()
            return False
        if not belongs:
            return False
        if kind == EventKeyPress:
            ctx.keyboard = True
            ctx.settle()
        else:
            ctx.keyboard = False
        return False


class _FluentContext(QObject):
    def __init__(self, root):
        super().__init__(root)
        self.root = root
        self.keyboard = False
        self.reduced = bool(root.property("fluentReducedMotion"))
        self.animated = weakref.WeakSet()
        self.surface = _Surface(root)
        self.surface.show()
        self._app_filter = _InputModeFilter(self)
        self._app_filter_installed = False
        root.installEventFilter(self)
        if root.isVisible():
            self._attach_app_filter()
        root.destroyed.connect(self._detach)

    def _attach_app_filter(self):
        if self._app_filter_installed or self.root is None:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._app_filter)
            self._app_filter_installed = True

    def _detach_app_filter(self):
        if not self._app_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._app_filter)
        self._app_filter_installed = False

    def _detach(self, *args):
        self._detach_app_filter()
        root = self.root
        self.root = None
        if root is not None and (_sip is None or not _sip.isdeleted(root)):
            try:
                root.removeEventFilter(self)
            except RuntimeError:
                pass

    def settle(self):
        for widget in list(self.animated):
            try:
                widget._settle()
            except RuntimeError:
                pass

    def _resume_animated(self):
        if self.root is None or not self.root.isVisible() or self.reduced:
            return
        for child in list(self.animated):
            try:
                if hasattr(child, "_resume_motion"):
                    child._resume_motion()
            except RuntimeError:
                pass

    def eventFilter(self, watched, event):
        if self.root is None or watched is not self.root:
            return False
        if _sip is not None and _sip.isdeleted(self.root):
            self._detach()
            return False
        kind = event.type()
        if kind == EventResize:
            self.surface.setGeometry(self.root.rect())
            self.settle()
            self._resume_animated()
        elif kind in (EventPaletteChange, EventApplicationPaletteChange,
                      EventFontChange, EventApplicationFontChange):
            self.surface.update()
            for child in self.root.findChildren(QWidget):
                child.update()
        elif kind == EventDynamicPropertyChange:
            self.reduced = bool(self.root.property("fluentReducedMotion"))
            if self.reduced:
                self.settle()
        elif kind == EventShow:
            self._attach_app_filter()
        elif kind in (EventHide, EventWindowDeactivate):
            self._detach_app_filter()
            self.settle()
        elif kind == EventWindowActivate:
            if self.root.isVisible():
                self._attach_app_filter()
            self._resume_animated()
        return False


def _is_dark_widget(widget):
    pal = widget.window().palette() if widget is not None and widget.window() is not None else widget.palette()
    win = pal.color(PaletteWindow).lightness()
    if win == 0 and QApplication.instance() is not None:
        win = QApplication.instance().palette().color(PaletteWindow).lightness()
    return win < 128


def _style(widget):
    dark = _is_dark_widget(widget)
    pal = widget.palette()
    raw_accent = pal.color(PaletteHighlight)
    if dark and raw_accent.lightness() < 110:
        accent = "#38bdf8"
        accent_bg = "#172a3a"
    elif not dark and raw_accent.lightness() > 200:
        accent = "#0284c7"
        accent_bg = "#e0f2fe"
    else:
        accent = raw_accent.name()
        accent_bg = _mix(QColor("#1e2530" if dark else "#ffffff"), raw_accent, .22 if dark else .12).name()
    if dark:
        fg, fg_meta, fg_disabled = "#f1f5f9", "#cbd5e1", "#8b949e"
        card_bg, input_bg, alt_bg = "#22272e", "#161b22", "#1c2128"
        border, border_strong, header_bg = "#3b4452", "#525f73", "#28303b"
        banner_bg, banner_border = "#1d283a", accent
    else:
        fg, fg_meta, fg_disabled = "#0f172a", "#334155", "#64748b"
        card_bg, input_bg, alt_bg = "#ffffff", "#ffffff", "#f8fafc"
        border, border_strong, header_bg = "#cbd5e1", "#94a3b8", "#f1f5f9"
        banner_bg, banner_border = "#eff6ff", accent
    sheet = f"""
        QWidget {{ color: {fg}; }}
        QLabel {{ color: {fg}; background: transparent; }}
        QLabel[fluentRole="meta"], QLabel[fluentRole="detail"], QLabel[role="detail"] {{ color: {fg_meta}; }}
        QLabel[fluentRole="title"], QLabel[fluentRole="section"], QLabel[role="heading"] {{ color: {fg}; font-weight: 600; }}
        QLabel:disabled {{ color: {fg_disabled}; }}
        QCheckBox, QRadioButton {{ color: {fg}; spacing: 8px; background: transparent; font-weight: 500; }}
        QCheckBox:disabled, QRadioButton:disabled {{ color: {fg_disabled}; }}
        QCheckBox::indicator:unchecked {{ width: 16px; height: 16px; border-radius: 4px;
            border: 1.5px solid {border_strong}; background: {input_bg}; }}
        QCheckBox::indicator:unchecked:hover {{ border-color: {accent}; }}
        QCheckBox::indicator:unchecked:disabled {{ border: 1.5px solid {border}; background: {alt_bg}; }}
        QFrame[fluentCard="true"] {{ background: {card_bg}; border: 1px solid {border}; border-radius: 8px; }}
        QFrame[fluentCard="banner"] {{ background: {banner_bg}; border: 1.5px solid {banner_border}; border-radius: 8px; }}
        QFrame[fluentCard="row"] {{ background: {card_bg}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
        QGroupBox {{ background: {card_bg}; border: 1px solid {border}; border-radius: 8px;
            margin-top: 12px; padding: 16px 12px 12px 12px; color: {fg}; font-weight: 600; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {fg}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 30px;
            border: 1px solid {border_strong}; border-radius: 6px; padding: 4px 10px;
            background: {input_bg}; color: {fg}; selection-background-color: {accent}; }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            background: {alt_bg}; color: {fg_disabled}; border-color: {border}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1.5px solid {accent}; }}
        QTreeView, QTableView, QPlainTextEdit {{ border: 1px solid {border};
            border-radius: 6px; background: {card_bg}; color: {fg};
            alternate-background-color: {alt_bg}; gridline-color: {border};
            selection-background-color: {accent_bg}; selection-color: {fg}; }}
        QHeaderView::section {{ background: {header_bg}; color: {fg}; font-weight: 600;
            padding: 6px 8px; border: none; border-bottom: 1px solid {border}; border-right: 1px solid {border}; }}
        QTabWidget::pane {{ background: {card_bg}; border: 1px solid {border}; border-radius: 8px; top: -1px; }}
        QTabBar::tab {{ padding: 9px 14px; margin-right: 4px; border: 1px solid transparent;
            border-top-left-radius: 6px; border-top-right-radius: 6px;
            background: transparent; color: {fg_meta}; font-weight: 500; }}
        QTabBar::tab:hover {{ color: {fg}; background: {alt_bg}; }}
        QTabBar::tab:selected {{ background: {card_bg}; color: {fg}; font-weight: 600; border-color: {border}; border-bottom-color: {card_bg}; }}
        QTabBar::tab:disabled {{ color: {fg_disabled}; }}
        QTabBar::tab:focus {{ border: 1px solid {accent}; }}
        QDockWidget {{ color: {fg}; font-weight: 600; }}
        QDockWidget::title {{ background: {header_bg}; padding: 6px 10px; border: 1px solid {border}; border-radius: 4px; }}
        QToolBar {{ background: {card_bg}; border-bottom: 1px solid {border}; spacing: 6px; padding: 4px 8px; }}
        QToolButton {{ color: {fg}; background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px 8px; }}
        QToolButton:hover {{ background: {alt_bg}; border-color: {border}; }}
    """
    if getattr(widget, "_fluent_last_qss", None) != sheet:
        widget._fluent_last_qss = sheet
        widget.setStyleSheet(sheet)


def apply_fluent_style(widget):
    """Install one palette-aware material and motion context on a native widget tree."""
    if getattr(widget, "_fluent_context", None) is None:
        widget._fluent_context = _FluentContext(widget)
    _style(widget)
    for label in widget.findChildren(QLabel):
        role = label.property("fluentRole")
        if role:
            label.setFont(role_font(label, str(role)))
    for child in widget.findChildren(QWidget):
        if hasattr(child, "_settle"):
            widget._fluent_context.animated.add(child)
    if not interface_config.animations_enabled(_settings(widget)) or widget._fluent_context.reduced:
        widget._fluent_context.settle()
    return widget


class FluentButton(QPushButton):
    """The native button keeps its rectangle; only its painted label compresses."""
    def __init__(self, text="", parent=None, *, variant="secondary", icon_name=None, compact=False):
        super().__init__(text, parent)
        self.variant, self.compact = variant, bool(compact)
        self._icon_name = icon_name
        self._hover = self._press = 0.0
        self._keyboard = False
        self._busy = False
        self._enabled_before_busy = True
        self._busy_angle = 0
        self._hover_animation = _animation(self, self._set_hover)
        self._press_animation = _animation(self, self._set_press)
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(33)
        self._busy_timer.timeout.connect(self._busy_tick)
        self.setCursor(PointingHandCursor)
        self.setFocusPolicy(FocusStrongFocus)
        self.setAutoRepeat(False)
        self.setIconSize(QSize(20, 20))
        if icon_name:
            self.setIcon(ui_icon(icon_name))
        self.pressed.connect(lambda: self._transition(self._press_animation, self._press, 1., MICRO_MS))
        self.released.connect(lambda: self._transition(self._press_animation, self._press, 0., FEEDBACK_MS))

    @property
    def contentScale(self):
        return 1.0 - .02 * self._press

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(max(72, hint.width() + (22 if self.icon().isNull() else 8)),
                     max(34 if self.compact else 42, hint.height()))

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _set_press(self, value):
        self._press = float(value)
        self.update()

    def _transition(self, animation, start, end, duration):
        animation.stop()
        context = _context(self)
        if context:
            context.animated.add(self)
        if not _motion(self):
            (self._set_hover if animation is self._hover_animation else self._set_press)(end)
            return
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setDuration(duration)
        animation.start()

    def _settle(self):
        self._hover_animation.stop()
        self._press_animation.stop()
        self._hover = float(self.underMouse() and self.isEnabled())
        self._press = float(self.isDown() and self.isEnabled()) if self._keyboard else 0.
        self._busy_timer.stop()
        self.update()

    def enterEvent(self, event):
        self._keyboard = False
        self._transition(self._hover_animation, self._hover, 1., MICRO_MS)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._transition(self._hover_animation, self._hover, 0., MICRO_MS)
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        self._keyboard = True
        self._settle()
        if event.isAutoRepeat() and event.key() in (KeySpace, KeyReturn, KeyEnter):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        self._keyboard = False
        super().mousePressEvent(event)

    def hideEvent(self, event):
        self.setDown(False)
        self._settle()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._resume_motion()

    def _resume_motion(self):
        if self._busy and _motion(self):
            self._busy_timer.start()

    def resizeEvent(self, event):
        self._settle()
        super().resizeEvent(event)
        self._resume_motion()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (EventEnabledChange, EventPaletteChange):
            self._settle()
            if self._icon_name and event.type() == EventPaletteChange:
                self.setIcon(ui_icon(self._icon_name))

    def setBusy(self, busy):
        busy = bool(busy)
        if busy == self._busy:
            return
        self._busy = busy
        if busy:
            self._enabled_before_busy = self.isEnabled()
            self.setEnabled(False)
            if _motion(self):
                self._busy_timer.start()
        else:
            self._busy_timer.stop()
            self.setEnabled(self._enabled_before_busy)
        self.setProperty("busy", busy)
        self.update()

    def isBusy(self):
        return self._busy

    def _busy_tick(self):
        if not self._busy or not _motion(self):
            self._busy_timer.stop()
            return
        self._busy_angle = (self._busy_angle + 12) % 360
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(Antialias)
        palette = self.palette()
        dark = _is_dark_widget(self)
        enabled = self.isEnabled() or self._busy
        group = PaletteGroupActive if enabled else PaletteGroupDisabled
        accent = palette.color(PaletteGroupActive, PaletteHighlight)
        if dark and accent.lightness() < 105:
            accent = QColor("#2563eb")
        surface = palette.color(group, PaletteButton)
        if dark and surface.lightness() < 34:
            surface = QColor("#28303d")
        elif not dark and surface.lightness() > 250:
            surface = QColor("#ffffff")
        primary = self.variant in ("primary", "accent")
        checked = self.isCheckable() and self.isChecked()
        if enabled:
            ink = QColor("#ffffff") if (primary and accent.lightnessF() < .65) else (
                QColor("#0f172a") if primary else QColor("#f1f5f9" if dark else "#0f172a")
            )
            fill = accent if primary else surface
            if checked and not primary:
                fill = _mix(surface, accent, .22 if dark else .14)
            fill = _mix(fill, QColor("#ffffff" if dark else "#0f172a"), .09 * self._hover + .08 * self._press)
            border = _mix(surface, accent, .65 if primary else .36 + .22 * self._hover)
            if checked:
                border = ink if primary else accent
        else:
            fill = QColor("#21262d" if dark else "#e2e8f0")
            ink = QColor("#94a3b8" if dark else "#64748b")
            border = QColor("#3b4452" if dark else "#cbd5e1")
            if checked:
                fill = _mix(fill, accent, .18)
                border = ink
        bounds = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.setBrush(fill)
        painter.setPen(QPen(border, 1.8 if checked else 1.2))
        painter.drawRoundedRect(bounds, 6, 6)
        # The highlight stays inside the fixed border, never following the content scale.
        painter.setPen(QPen(QColor(255, 255, 255, 24 if fill.lightnessF() < .5 else 110), 1))
        painter.drawLine(QPointF(8, 1.5), QPointF(max(8, self.width() - 8), 1.5))
        painter.save()
        center = bounds.center()
        painter.translate(center)
        painter.scale(self.contentScale, self.contentScale)
        painter.translate(-center)
        option.rect = self.rect().adjusted(10, 3, -10, -3)
        option.state |= StyleStateEnabled
        for cg in (PaletteGroupActive, PaletteGroupInactive, PaletteGroupDisabled):
            option.palette.setColor(cg, PaletteButtonText, ink)
        if (primary or not enabled) and not option.icon.isNull():
            # The command glyph takes the foreground of its actual button surface.
            key = (option.icon.cacheKey(), self.iconSize(), ink.rgba(), self.devicePixelRatioF())
            if getattr(self, "_tinted_icon_key", None) != key:
                pixmap = icon_pixmap(option.icon, self.iconSize(), self.devicePixelRatioF())
                tint = QPainter(pixmap)
                tint.setCompositionMode(CompositionSourceIn)
                tint.fillRect(pixmap.rect(), ink)
                tint.end()
                self._tinted_icon = QIcon(pixmap)
                self._tinted_icon_key = key
            option.icon = self._tinted_icon
        if self._busy:
            option.icon = QIcon()
            option.rect.adjust(22, 0, 0, 0)
            painter.setPen(QPen(ink, 1.7, PenSolidLine, PenCapRound))
            painter.setBrush(BrushNoBrush)
            painter.drawArc(QRectF(12, (self.height() - 16) / 2, 16, 16), -self._busy_angle * 16, 270 * 16)
        self.style().drawControl(StyleCEPushButtonLabel, option, painter, self)
        painter.restore()
        if self.hasFocus():
            painter.setBrush(BrushNoBrush)
            painter.setPen(QPen(ink if primary else accent, 2))
            painter.drawRoundedRect(bounds.adjusted(2, 2, -2, -2), 4, 4)


class _FluentTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyboard = False
        self._indicator = QRectF()
        self._slide = _animation(self, self._set_indicator)
        self.setFocusPolicy(FocusStrongFocus)
        self.setElideMode(TextElideNone)
        self.setUsesScrollButtons(True)
        self.currentChanged.connect(self._move_indicator)

    def _target(self):
        if self.currentIndex() < 0:
            return QRectF()
        rect = QRectF(self.tabRect(self.currentIndex()))
        return QRectF(rect.x() + 10, rect.bottom() - 2, max(0, rect.width() - 20), 2)

    def _set_indicator(self, value):
        self._indicator = QRectF(value)
        self.update()

    def _move_indicator(self, index):
        self._slide.stop()
        context = _context(self)
        if context:
            context.animated.add(self)
        target = self._target()
        if not _motion(self) or self._indicator.isEmpty():
            self._set_indicator(target)
            return
        self._slide.setStartValue(self._indicator)
        self._slide.setEndValue(target)
        self._slide.setDuration(NAVIGATION_MS)
        self._slide.start()

    def _settle(self):
        self._slide.stop()
        self._set_indicator(self._target())

    def keyPressEvent(self, event):
        self._keyboard = True
        self._settle()
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self._keyboard = False
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._settle()

    def hideEvent(self, event):
        self._settle()
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(Antialias)
        painter.setPen(NoPen)
        painter.setBrush(self.palette().color(PaletteHighlight))
        painter.drawRoundedRect(self._indicator, 1, 1)


class FluentTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(_FluentTabBar(self))
        self.setDocumentMode(True)

    def keyPressEvent(self, event):
        self.tabBar()._keyboard = True
        self.tabBar()._settle()
        super().keyPressEvent(event)


class StableStatus(QLabel):
    """A reserved three-line plain-text slot whose message never moves its neighbours."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._keyboard = False
        self._opacity = 1.
        self._fade = _animation(self, self._set_opacity)
        self.setTextFormat(PlainText)
        self.setWordWrap(True)
        self.setSizePolicy(SizePolicyExpanding, SizePolicyPreferred)
        self.setMinimumHeight(self.sizeHint().height())

    def sizeHint(self):
        return QSize(260, max(42, self.fontMetrics().lineSpacing() * 3 + 8))

    def minimumSizeHint(self):
        return QSize(80, self.sizeHint().height())

    def heightForWidth(self, width):
        return self.sizeHint().height()

    def _set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    def _settle(self):
        self._fade.stop()
        self._set_opacity(1.)

    def setText(self, text):
        changed = str(text) != self.text()
        super().setText(str(text))
        self.setToolTip(str(text))
        if not hasattr(self, "_fade") or not changed:
            return
        self._fade.stop()
        context = _context(self)
        if context:
            context.animated.add(self)
        if not _motion(self):
            self._set_opacity(1.)
            return
        self._fade.setStartValue(max(.65, self._opacity if self._opacity < 1 else .65))
        self._fade.setEndValue(1.)
        self._fade.setDuration(FEEDBACK_MS)
        self._fade.start()

    def hideEvent(self, event):
        self._settle()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self._settle()
        super().resizeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (EventFontChange, EventApplicationFontChange):
            self.setMinimumHeight(self.sizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(Antialias)
        dark = _is_dark_widget(self)
        bg = QColor("#1c222b" if dark else "#f8fafc")
        border = QColor("#384250" if dark else "#cbd5e1")
        ink = QColor("#f1f5f9" if dark else "#0f172a")
        bounds = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(bounds, 6, 6)
        painter.setOpacity(self._opacity)
        painter.setPen(ink)
        flags = int(self.alignment())
        if self.wordWrap():
            flags |= int(TextWordWrap)
        painter.drawText(self.contentsRect().adjusted(10, 4, -10, -4), flags, self.text())
