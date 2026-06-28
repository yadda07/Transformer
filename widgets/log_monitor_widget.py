#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LogMonitorWidget - Enterprise-grade log viewer.

Features:
- Tabular display: timestamp / severity icon / module icon / code icon / message
- Per-severity color coding via QPalette (theme-compatible)
- SVG icons for severity, module, and operation codes
- Live filtering: severity, module, full-text search
- Auto-scroll toggle
- Pause/Resume live feed
- Clear / Export to file
- Bounded memory: ring buffer (10k rows max in UI)
- Listens to TransformerLogger.log_entry_created signal
"""

from datetime import datetime
from typing import List

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor, QFont, QPalette
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QCheckBox, QLabel,
    QFileDialog, QToolButton, QMessageBox, QSizePolicy,
)

from ..shared.compat import (
    AlignCenter, AlignVCenter, AlignLeft, _HeaderResizeMode,
    _SelectionBehavior, _SelectionMode, _SizePolicy, StyleHintMonospace,
    ToolButtonTextBesideIcon, palette_color,
)
from ..shared.log_icons import (
    code_icon, log_toolbar_icon, module_icon, severity_icon,
)

# QAbstractItemView.EditTrigger.NoEditTriggers (Qt6) / QAbstractItemView.NoEditTriggers (Qt5)
_EditTrigger = getattr(__import__('qgis.PyQt.QtWidgets', fromlist=['QAbstractItemView']).QAbstractItemView,
                       'EditTrigger', None)
NoEditTriggers = (
    getattr(_EditTrigger, 'NoEditTriggers', None)
    if _EditTrigger is not None
    else __import__('qgis.PyQt.QtWidgets', fromlist=['QAbstractItemView']).QAbstractItemView.NoEditTriggers
)


# Severity ordering for filter logic
SEVERITY_ORDER = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

# Severity palette roles (theme-aware: derived from QPalette where possible)
def _severity_color(palette: QPalette, severity: str) -> QColor:
    """Return a color for a severity, derived from palette to respect theme."""
    base = palette_color(palette, None, 'Text')
    if severity == "debug":
        return QColor(base.red(), base.green(), base.blue(), 140)  # dim
    if severity == "info":
        return base
    if severity == "warning":
        return QColor("#d68910")  # amber, readable both themes
    if severity == "error":
        return QColor("#c0392b")  # red
    if severity == "critical":
        return QColor("#922b21")  # dark red
    return base


SEVERITY_BADGE = {
    "debug": "DBG",
    "info": "INF",
    "warning": "WRN",
    "error": "ERR",
    "critical": "CRT",
}

_SEVERITY_FILTER_ICONS = {
    "debug": "log_info",
    "info": "log_info",
    "warning": "log_warning",
    "error": "log_error",
    "critical": "log_critical",
}

_MODULE_FILTER_ICONS = {
    "system": "log_module_system",
    "transformer": "log_module_transformer",
    "exporter": "log_module_exporter",
    "db": "log_module_db",
    "ui": "log_module_ui",
}


class LogMonitorWidget(QWidget):
    """Enterprise log viewer with filters, search, and export."""

    MAX_ROWS = 10000  # ring buffer cap

    COL_TIME = 0
    COL_SEV = 1
    COL_MOD = 2
    COL_CODE = 3
    COL_MSG = 4
    COLUMNS = ["Time", "Lvl", "Module", "Code", "Message"]

    def __init__(self, transformer_logger=None, parent=None):
        super().__init__(parent)
        self._logger = transformer_logger
        self._all_entries: List[dict] = []  # full buffer (filtered out + visible)
        self._auto_scroll = True
        self._paused = False
        self._severity_filter = "debug"  # show all by default (>= debug)
        self._module_filter = "all"
        self._search_text = ""

        self._build_ui()
        self._wire_logger()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Toolbar row
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # Severity filter
        toolbar.addWidget(QLabel("Level:"))
        self.severity_combo = QComboBox()
        for label, value in (
            ("All", "debug"),
            ("Info+", "info"),
            ("Warn+", "warning"),
            ("Error+", "error"),
            ("Critical", "critical"),
        ):
            idx = self.severity_combo.count()
            self.severity_combo.addItem(label, value)
            icon_key = _SEVERITY_FILTER_ICONS.get(value, "log_info")
            self.severity_combo.setItemIcon(idx, log_toolbar_icon(icon_key))
        self.severity_combo.currentIndexChanged.connect(self._on_severity_changed)
        toolbar.addWidget(self.severity_combo)

        # Module filter
        toolbar.addWidget(QLabel("Module:"))
        self.module_combo = QComboBox()
        self.module_combo.addItem("All", "all")
        self.module_combo.setItemIcon(0, log_toolbar_icon("log_module_system"))
        for mod in ("system", "transformer", "exporter", "db", "ui"):
            idx = self.module_combo.count()
            self.module_combo.addItem(mod, mod)
            icon_key = _MODULE_FILTER_ICONS.get(mod, "log_module_system")
            self.module_combo.setItemIcon(idx, log_toolbar_icon(icon_key))
        self.module_combo.currentIndexChanged.connect(self._on_module_changed)
        toolbar.addWidget(self.module_combo)

        # Search
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search messages...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.setSizePolicy(_SizePolicy.Expanding, _SizePolicy.Fixed)
        toolbar.addWidget(self.search_edit, 1)

        # Pause/Resume
        self.pause_btn = QToolButton()
        self.pause_btn.setToolButtonStyle(ToolButtonTextBesideIcon)
        self.pause_btn.setIcon(log_toolbar_icon("log_pause"))
        self.pause_btn.setIconSize(QSize(16, 16))
        self.pause_btn.setText("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        toolbar.addWidget(self.pause_btn)

        # Auto-scroll
        self.autoscroll_check = QCheckBox("Auto-scroll")
        self.autoscroll_check.setChecked(True)
        self.autoscroll_check.toggled.connect(self._on_autoscroll_toggled)
        toolbar.addWidget(self.autoscroll_check)

        # Clear
        self.clear_btn = QToolButton()
        self.clear_btn.setToolButtonStyle(ToolButtonTextBesideIcon)
        self.clear_btn.setIcon(log_toolbar_icon("log_clear"))
        self.clear_btn.setIconSize(QSize(16, 16))
        self.clear_btn.setText("Clear")
        self.clear_btn.clicked.connect(self.clear_logs)
        toolbar.addWidget(self.clear_btn)

        # Export
        self.export_btn = QToolButton()
        self.export_btn.setToolButtonStyle(ToolButtonTextBesideIcon)
        self.export_btn.setIcon(log_toolbar_icon("log_export"))
        self.export_btn.setIconSize(QSize(16, 16))
        self.export_btn.setText("Export")
        self.export_btn.clicked.connect(self.export_logs)
        toolbar.addWidget(self.export_btn)

        root.addLayout(toolbar)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        self.count_label = QLabel("0 entries")
        font = self.count_label.font()
        font.setPointSize(max(font.pointSize() - 1, 8))
        self.count_label.setFont(font)
        stats_row.addWidget(self.count_label)
        stats_row.addStretch(1)
        root.addLayout(stats_row)

        # Table
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(_SelectionBehavior.SelectRows)
        self.table.setSelectionMode(_SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setIconSize(QSize(16, 16))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_TIME, _HeaderResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_SEV, _HeaderResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_MOD, _HeaderResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_CODE, _HeaderResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_MSG, _HeaderResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_SEV, 28)
        self.table.setColumnWidth(self.COL_MOD, 28)
        self.table.setColumnWidth(self.COL_CODE, 28)

        # Mono font for time / code columns
        mono = QFont("Consolas, Menlo, monospace")
        mono.setStyleHint(StyleHintMonospace)
        self.table.setFont(mono)

        root.addWidget(self.table, 1)

    def _wire_logger(self):
        """Connect to global logger if provided."""
        if self._logger is not None:
            try:
                self._logger.log_entry_created.connect(self._on_log_entry)
                buffer = getattr(self._logger, "_log_buffer", None)
                if buffer:
                    self.replay_buffer(list(buffer))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_log_entry(self, entry):
        """Receive a LogEntry from the logger signal."""
        if self._paused:
            # Still buffer, just don't refresh table
            self._all_entries.append(self._entry_to_dict(entry))
            self._enforce_buffer_cap()
            return

        d = self._entry_to_dict(entry)
        self._all_entries.append(d)
        self._enforce_buffer_cap()

        if self._row_visible(d):
            self._append_table_row(d)
            self._update_count()

    def _on_severity_changed(self, _idx: int):
        self._severity_filter = self.severity_combo.currentData()
        self._refresh_table()

    def _on_module_changed(self, _idx: int):
        self._module_filter = self.module_combo.currentData()
        self._refresh_table()

    def _on_search_changed(self, text: str):
        self._search_text = text.strip().lower()
        self._refresh_table()

    def _on_pause_toggled(self, paused: bool):
        self._paused = paused
        self.pause_btn.setText("Resume" if paused else "Pause")
        self.pause_btn.setIcon(
            log_toolbar_icon("log_resume" if paused else "log_pause")
        )
        if not paused:
            self._refresh_table()

    def _on_autoscroll_toggled(self, on: bool):
        self._auto_scroll = on

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _entry_to_dict(entry) -> dict:
        """Convert LogEntry to dict, robust to backend variations."""
        if hasattr(entry, "to_dict"):
            d = entry.to_dict()
        else:
            d = {
                "timestamp": getattr(entry, "timestamp", datetime.now().isoformat()),
                "severity": getattr(entry, "severity", "info"),
                "module": getattr(entry, "module", "system"),
                "code": getattr(entry, "code", ""),
                "message": getattr(entry, "message", str(entry)),
            }
        return d

    def _enforce_buffer_cap(self):
        if len(self._all_entries) > self.MAX_ROWS:
            del self._all_entries[: len(self._all_entries) - self.MAX_ROWS]

    def _row_visible(self, d: dict) -> bool:
        """Return True if entry passes current filters."""
        sev = d.get("severity", "info")
        if SEVERITY_ORDER.get(sev, 1) < SEVERITY_ORDER.get(self._severity_filter, 0):
            return False
        if self._module_filter != "all" and d.get("module") != self._module_filter:
            return False
        if self._search_text:
            hay = (
                d.get("message", "") + " " + d.get("code", "") + " " + d.get("module", "")
            ).lower()
            if self._search_text not in hay:
                return False
        return True

    def _make_item(self, text: str, color: QColor, bold: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setForeground(color)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        return item

    def _make_icon_item(
        self,
        icon,
        tooltip: str,
        color: QColor,
        bold: bool = False,
    ) -> QTableWidgetItem:
        """Icon-only table cell with tooltip for semiology / accessibility."""
        item = QTableWidgetItem()
        item.setIcon(icon)
        item.setToolTip(tooltip)
        item.setForeground(color)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        item.setTextAlignment(AlignCenter)
        return item

    def _append_table_row(self, d: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)

        ts = d.get("timestamp", "")
        try:
            short_ts = ts.split("T", 1)[1] if "T" in ts else ts
        except Exception:
            short_ts = ts

        sev = d.get("severity", "info")
        code = d.get("code", "")
        module = d.get("module", "system")
        badge = SEVERITY_BADGE.get(sev, sev[:3].upper())
        color = _severity_color(self.palette(), sev)
        bold = sev in ("error", "critical")

        time_item = self._make_item(short_ts, color)
        time_item.setTextAlignment(AlignVCenter | AlignLeft)
        self.table.setItem(row, self.COL_TIME, time_item)

        sev_item = self._make_icon_item(
            severity_icon(sev, code),
            f"{sev.upper()} ({badge})",
            color,
            bold=bold,
        )
        self.table.setItem(row, self.COL_SEV, sev_item)

        mod_item = self._make_icon_item(
            module_icon(module),
            module,
            color,
        )
        self.table.setItem(row, self.COL_MOD, mod_item)

        code_icon_ref = code_icon(code)
        if not code_icon_ref.isNull():
            code_item = self._make_icon_item(code_icon_ref, code, color)
        else:
            code_item = self._make_item("", color)
            if code:
                code_item.setToolTip(code)
        self.table.setItem(row, self.COL_CODE, code_item)

        msg_item = self._make_item(d.get("message", ""), color, bold=bold)
        msg_item.setTextAlignment(AlignVCenter | AlignLeft)
        self.table.setItem(row, self.COL_MSG, msg_item)

        while self.table.rowCount() > self.MAX_ROWS:
            self.table.removeRow(0)

        if self._auto_scroll:
            self.table.scrollToBottom()

    def _refresh_table(self):
        """Rebuild table from full buffer applying filters."""
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for d in self._all_entries:
                if self._row_visible(d):
                    self._append_table_row(d)
        finally:
            self.table.setUpdatesEnabled(True)
        self._update_count()

    def _update_count(self):
        total = len(self._all_entries)
        shown = self.table.rowCount()
        if shown == total:
            self.count_label.setText(f"{total} entries")
        else:
            self.count_label.setText(f"{shown} / {total} entries")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear_logs(self):
        self._all_entries.clear()
        self.table.setRowCount(0)
        self._update_count()

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Logs", "transformer_logs.txt",
            "Text files (*.txt);;CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            sep = "," if path.lower().endswith(".csv") else "\t"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(sep.join(self.COLUMNS) + "\n")
                for d in self._all_entries:
                    if not self._row_visible(d):
                        continue
                    row = [
                        d.get("timestamp", ""),
                        d.get("severity", ""),
                        d.get("module", ""),
                        d.get("code", ""),
                        d.get("message", "").replace("\n", " "),
                    ]
                    fh.write(sep.join(row) + "\n")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def replay_buffer(self, buffer):
        """Replay a list of LogEntry objects (e.g., on dock attach)."""
        for entry in buffer:
            d = self._entry_to_dict(entry)
            self._all_entries.append(d)
        self._enforce_buffer_cap()
        self._refresh_table()
