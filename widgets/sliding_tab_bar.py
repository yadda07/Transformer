"""Sliding segmented tab bar with animated hover and selection highlight.

Replaces QTabWidget for Quick Help: a QStackedWidget for content plus a
custom-painted bar whose highlight glides between segments on hover and
click, using QVariantAnimation for smooth 180 ms easing.
"""
from qgis.PyQt.QtCore import QRectF, QVariantAnimation, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFontMetrics, QPainter
from qgis.PyQt.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from ..shared.compat import (
    AlignCenter, Antialias, EaseInOutQuad, NoPen, PointingHandCursor,
)


class _SlidingBar(QWidget):
    """Custom-painted segmented bar with sliding hover and primary highlight."""

    segmentClicked = pyqtSignal(int)

    _HEIGHT = 26
    _MARGIN_HOVER = 4
    _ALPHA_PRIMARY = 210
    _ALPHA_HOVER = 130
    _ANIM_DURATION = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = []
        self._primary = -1
        self._hover = -1
        self._press = -1
        self._slider_pos = -1.0
        self._hover_pos = -1.0
        self._anim = self._build_anim(self._on_slider_anim)
        self._hover_anim = self._build_anim(self._on_hover_anim)
        self.setMouseTracking(True)
        self.setCursor(PointingHandCursor)
        self.setFixedHeight(self._HEIGHT)

    def _build_anim(self, callback):
        anim = QVariantAnimation(self)
        anim.setDuration(self._ANIM_DURATION)
        anim.setEasingCurve(EaseInOutQuad)
        anim.valueChanged.connect(callback)
        return anim

    def _on_slider_anim(self, val):
        self._slider_pos = float(val)
        self.update()

    def _on_hover_anim(self, val):
        self._hover_pos = float(val)
        self.update()

    def labels(self):
        return list(self._labels)

    def setLabels(self, labels):
        self._labels = list(labels)
        self._primary = min(self._primary, len(self._labels) - 1) if self._labels else -1
        self._slider_pos = float(self._primary) if self._primary >= 0 else -1.0
        self.update()

    def setPrimaryIndex(self, index):
        if index < 0 or index >= len(self._labels):
            return
        self._primary = index
        self._move_slider(float(index), self._anim, self._slider_pos)
        self.update()

    def primaryIndex(self):
        return self._primary

    def _segment_w(self):
        if not self._labels:
            return 0
        return self.width() / len(self._labels)

    def _index_at(self, x):
        if not self._labels:
            return -1
        sw = self._segment_w()
        if sw <= 0:
            return -1
        return min(int(x / sw), len(self._labels) - 1)

    def _move_slider(self, target, anim, current):
        anim.stop()
        anim.setStartValue(float(current))
        anim.setEndValue(float(target))
        anim.start()

    def _event_x(self, event):
        if hasattr(event, "position"):
            return float(event.position().x())
        return float(event.x())

    def mouseMoveEvent(self, event):
        idx = self._index_at(self._event_x(event))
        if idx != self._hover:
            self._hover = idx
        target = float(idx) if idx >= 0 else -1.0
        self._move_slider(target, self._hover_anim, self._hover_pos)

    def leaveEvent(self, event):
        self._hover = -1
        self._move_slider(-1.0, self._hover_anim, self._hover_pos)

    def mousePressEvent(self, event):
        idx = self._index_at(self._event_x(event))
        if idx >= 0:
            self._press = idx
            self.update()

    def mouseReleaseEvent(self, event):
        idx = self._index_at(self._event_x(event))
        prev = self._press
        self._press = -1
        self.update()
        if idx == prev and idx >= 0:
            self.segmentClicked.emit(idx)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(Antialias)
        self._draw_bg(p)
        self._draw_slider(p, self._slider_pos, self._ALPHA_PRIMARY, 0)
        self._draw_slider(p, self._hover_pos, self._ALPHA_HOVER, self._MARGIN_HOVER)
        self._draw_labels(p)

    def _draw_bg(self, p):
        pal = self.palette()
        mid = pal.mid().color()
        base = pal.base().color()
        p.setPen(QColor(mid.red(), mid.green(), mid.blue(), 200))
        p.setBrush(QColor(base.red(), base.green(), base.blue(), 230))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 6, 6)

    def _draw_slider(self, p, pos, alpha, margin):
        if pos < 0 or not self._labels:
            return
        sw = self._segment_w()
        x = margin + sw * pos
        rect = QRectF(x, margin, sw - margin * 2, self.height() - margin * 2)
        hl = self.palette().highlight().color()
        p.setPen(NoPen)
        p.setBrush(QColor(hl.red(), hl.green(), hl.blue(), alpha))
        p.drawRoundedRect(rect, 5, 5)

    def _draw_labels(self, p):
        sw = self._segment_w()
        for i, label in enumerate(self._labels):
            rect = QRectF(i * sw, 0, sw, self._HEIGHT)
            self._draw_label(p, label, rect, i == self._primary, i == self._press)

    def _draw_label(self, p, label, rect, is_primary, is_pressed):
        pal = self.palette()
        color = pal.highlightedText().color() if is_primary else pal.text().color()
        alpha = 180 if is_pressed else 255
        color = QColor(color.red(), color.green(), color.blue(), alpha)
        font = p.font()
        font.setBold(is_primary)
        p.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(label)
        x = rect.x() + (rect.width() - text_w) / 2
        p.setPen(color)
        text_rect = QRectF(x, 0, text_w, self._HEIGHT)
        p.drawText(text_rect, AlignCenter, label)


class SlidingTabWidget(QWidget):
    """Tab widget with sliding segmented bar, mimicking QTabWidget API."""

    currentChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedWidget()
        self._bar = _SlidingBar()
        self._bar.segmentClicked.connect(self._on_segment_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack)
        layout.addWidget(self._bar)

    def _on_segment_clicked(self, index):
        self._stack.setCurrentIndex(index)
        self._bar.setPrimaryIndex(index)
        self.currentChanged.emit(index)

    def count(self):
        return self._stack.count()

    def addTab(self, widget, label):
        self._stack.addWidget(widget)
        labels = self._bar.labels()
        labels.append(label)
        self._bar.setLabels(labels)
        if self._bar.primaryIndex() < 0:
            self._bar.setPrimaryIndex(0)
            self._stack.setCurrentIndex(0)

    def removeTab(self, index):
        if index < 0 or index >= self._stack.count():
            return
        widget = self._stack.widget(index)
        self._stack.removeWidget(widget)
        labels = self._bar.labels()
        labels.pop(index)
        self._bar.setLabels(labels)
        if self._stack.count() > 0:
            new_idx = min(index, self._stack.count() - 1)
            self.setCurrentIndex(new_idx)
        else:
            self._bar.setPrimaryIndex(-1)

    def currentIndex(self):
        return self._stack.currentIndex()

    def setCurrentIndex(self, index):
        if index < 0 or index >= self._stack.count():
            return
        self._stack.setCurrentIndex(index)
        self._bar.setPrimaryIndex(index)

    def widget(self, index):
        return self._stack.widget(index)

    def setTabText(self, index, text):
        labels = self._bar.labels()
        if 0 <= index < len(labels):
            labels[index] = text
            self._bar.setLabels(labels)

    def setTabPosition(self, _position):
        pass

    def setStyleSheet(self, _sheet):
        pass
