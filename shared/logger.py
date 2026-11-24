#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com

"""
Centralized logging module for Transformer
Automatically sends messages to:
- QgsMessageLog (QGIS messages)
- Plugin Activity Log (user panel)
"""

from collections import deque
from datetime import datetime
import json
import os
import re
import threading
try:
    from qgis.PyQt import sip as _sip
except ImportError:
    _sip = None
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QPlainTextEdit
from qgis.core import QgsMessageLog, QgsProject

from .compat import (
    CursorEnd,
    CursorLineUnder,
    CursorUp,
    FontBold,
    MsgCritical,
    MsgInfo,
    MsgWarning,
    palette_color,
)

_SECRET_REDACT_RE = re.compile(
    r"((?:postgres(?:ql)?://[^:\s/]+:)[^@\s]+(@)|(?:password|passwd|pwd|secret|token|api_key)\s*[=:]\s*['\"]?[^\s'\",;)]+)",
    re.IGNORECASE,
)
_MAX_LOG_FILE_BYTES = 5 * 1024 * 1024


class LogEntry:
    """Structured log entry conforming to @[/logger] specifications"""

    def __init__(self, timestamp, severity, module, code, message, context=None):
        self.timestamp = timestamp  # ISO format with ms
        self.severity = severity  # debug/info/warning/error/critical
        self.module = module  # exporter/transformer/ui/db
        self.code = code  # Short standardized tag
        self.message = message  # Human-readable description
        self.context = context or {}  # Optional JSON context data

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'timestamp': self.timestamp,
            'severity': self.severity,
            'module': self.module,
            'code': self.code,
            'message': self.message,
            'context': self.context
        }

    def to_display_string(self):
        """Format for UI display"""
        return f"[{self.timestamp}] {self.severity.upper()} {self.module}.{self.code} {self.message}"


class TransformerLogger(QObject):
    """Centralized logger conforming to @[/logger] @[/transformerdev] @[/designers] specifications"""

    # Signal emitted when a log entry is created
    log_entry_created = pyqtSignal(object)  # LogEntry object

    def __init__(self):
        super().__init__()
        self._activity_log_widget = None
        self._buffer_lock = threading.Lock()
        self._file_lock = threading.Lock()
        self._logging_lock = self._file_lock
        self._file_write_count = 0

        # In-memory ring buffer (O(1) bounded at 10k entries as per @[/logger])
        self._max_buffer_size = 10000
        self._log_buffer = deque(maxlen=self._max_buffer_size)

        # Persistent storage
        self._log_file_path = None

        # Smart logging configuration - eliminate noise aggressively
        self._noise_filters = {
            # UI state changes - suppress ALL panel visibility messages
            'panel_noise': [
                'Panel .* hidden', 'Panel .* shown', 'Panel .* moved to',
                'Enhanced interface hidden', 'Enhanced interface shown'
            ],

            # Widget state spam - suppress ALL widget visibility logs
            'widget_noise': [
                'UI VISIBILITY:', 'Widget .* set to visible', 'Label for .* set to visible',
                'Attribute mode=', 'Spatial mode=', 'Parameter visibility updated'
            ],

            # Debug/Development spam - eliminate ALL debug messages
            'debug_noise': [
                'DEBUG:', 'Added source field:', 'Added target field:', 'Table row count set to:',
                'Table items set successfully', 'Columns resized', 'Calling populate_field_mapping_table',
                'populate_field_mapping_table called', 'Source fields count:', 'Target fields count:',
                'Total fields to display:', 'Status updated:', 'update_field_mapping_preview called'
            ],

            # Connection spam - reduce repetitive connection messages
            'connection_noise': [
                'Connected .* signal', 'Connecting signals', 'Logger connected to Activity',
                'Connecting delayed signals',
                'Connected source_layer_combo signals', 'Connected target_layer_combo signals'
            ],

            # Initialization noise - reduce startup verbosity
            'init_noise': [
                'Enhanced interface connections established', 'Component visibility states restored',
                'Activity Monitor ready', 'Dock widgets ready', 'Native Qt dock drop zones activated',
                'Theme applied from CSS file', 'Centralized logger configured successfully'
            ],

            # Repetitive emoji logs - eliminate format detection spam
            'format_noise': [
                'Added from QGIS:', 'Loaded .* vector layer\\(s\\) from QGIS project'
            ],

            # Field mapping verbosity - too much detail
            'field_spam': [
                'Source layer:', 'Target layer:', 'Source layer changed:', 'Target layer changed:',
            ]
        }
        self._noise_re = re.compile(
            "|".join(
                f"(?:{pattern})"
                for patterns in self._noise_filters.values()
                for pattern in patterns
            ),
            re.IGNORECASE,
        )

        # Initialize persistent logging
        self._setup_persistent_logging()

    def set_activity_log_widget(self, widget):
        """Sets the Activity Log widget for display and auto-clears on destruction."""
        self._activity_log_widget = widget
        if widget is not None and hasattr(widget, "destroyed"):
            try:
                widget.destroyed.connect(self._on_activity_widget_destroyed)
            except Exception as exc:
                QgsMessageLog.logMessage(f"Activity widget destroy hook skipped: {exc}", "Transformer", MsgWarning)

    def _on_activity_widget_destroyed(self, *_args):
        self._activity_log_widget = None

    @staticmethod
    def redact_secrets(text: str) -> str:
        if not text or not isinstance(text, str):
            return str(text or "")
        def _repl(match):
            full = match.group(0)
            if "://" in full and "@" in full:
                prefix = full.split(":", 2)[:2]
                suffix = full.split("@", 1)[1]
                return ":".join(prefix) + ":[secret masqué]@" + suffix
            key = full.split("=")[0].split(":")[0]
            sep = "=" if "=" in full else ":"
            return f"{key}{sep}[secret masqué]"
        return _SECRET_REDACT_RE.sub(_repl, text)

    def _setup_persistent_logging(self):
        """Setup persistent log file per project as per @[/logger]"""
        try:
            project = QgsProject.instance()
            if project.fileName():
                project_dir = os.path.dirname(project.fileName())
                self._log_file_path = os.path.join(project_dir, f"{os.path.basename(project.fileName())}_transformer.log")
            else:
                # Fallback to temp directory scoped by PID to avoid multi-QGIS collisions
                import tempfile
                self._log_file_path = os.path.join(
                    tempfile.gettempdir(), f"transformer_session_{os.getpid()}.log"
                )
        except Exception as exc:
            QgsMessageLog.logMessage(f"Failed to setup log file path: {exc}", "Transformer", MsgWarning)
            self._log_file_path = None

    def log(self, message, severity="info", module="system", code="GENERAL", context=None):
        """
        Main logging method conforming to @[/logger] specifications

        Args:
            message (str): Clear human-readable message
            severity (str): debug/info/warning/error/critical
            module (str): Module name (transformer/exporter/db/ui/system)
            code (str): Short standardized code
            context (dict): Optional context data
        """
        try:
            # Create timestamp with milliseconds (ISO format)
            timestamp = datetime.now().isoformat(timespec='milliseconds')

            # Normalize severity to standard levels
            severity = self._normalize_severity(severity)
            safe_message = self.redact_secrets(str(message))

            # Create structured log entry
            entry = LogEntry(timestamp, severity, module, code, safe_message, context)

            # Smart filtering - skip noise
            if self._should_filter_entry(entry):
                return

            # Add to in-memory buffer
            self._add_to_buffer(entry)

            # Log to QgsMessageLog for external visibility
            qgis_level = self._get_qgis_level(severity)
            QgsMessageLog.logMessage(entry.to_display_string(), "Transformer", qgis_level)

            # Display in Activity Log widget if available (main thread only, Qt widget constraint)
            if self._activity_log_widget and threading.current_thread() is threading.main_thread():
                self._add_to_activity_log(entry)

            # Write to persistent file
            self._write_to_file(entry)

            # Emit signal for other listeners
            self.log_entry_created.emit(entry)

        except Exception:
            # Fallback logging to prevent cascading errors
            try:
                QgsMessageLog.logMessage(f"LOGGING_ERROR: {message}", "Transformer", MsgCritical)
            except Exception as fallback_exc:
                # Last resort: QGIS message log itself is broken, nothing we can do
                import sys
                print(f"Transformer: both logger and QgsMessageLog failed: {fallback_exc}", file=sys.stderr)

    def _normalize_severity(self, severity):
        """Normalize severity to standard levels per @[/logger]"""
        severity_map = {
            # Legacy compatibility
            'Info': 'info',
            'Warning': 'warning',
            'Error': 'error',
            'Success': 'info',
            'Critical': 'critical',
            # Standard levels
            'debug': 'debug',
            'info': 'info',
            'warning': 'warning',
            'error': 'error',
            'critical': 'critical'
        }
        return severity_map.get(severity, 'info')

    def _get_qgis_level(self, severity):
        """Convert severity to Qgis level"""
        level_map = {
            'debug': MsgInfo,
            'info': MsgInfo,
            'warning': MsgWarning,
            'error': MsgCritical,
            'critical': MsgCritical
        }
        return level_map.get(severity, MsgInfo)

    def _should_filter_entry(self, entry):
        """Filter log entries based on intelligent noise reduction"""

        # Never filter critical errors
        if entry.severity in ['error', 'critical']:
            return False

        noise_re = getattr(self, "_noise_re", None)
        if noise_re is not None:
            return bool(noise_re.search(entry.message))

        for _cat, patterns in self._noise_filters.items():
            for pattern in patterns:
                if re.search(pattern, entry.message, re.IGNORECASE):
                    return True
        return False

    def _add_to_buffer(self, entry):
        """Add entry to in-memory ring buffer in O(1)."""
        with self._buffer_lock:
            if isinstance(self._log_buffer, deque) and self._log_buffer.maxlen == self._max_buffer_size:
                self._log_buffer.append(entry)
            else:
                self._log_buffer = deque(self._log_buffer, maxlen=self._max_buffer_size)
                self._log_buffer.append(entry)

    def _write_to_file(self, entry):
        """Write entry to persistent log file with 5 MB rotation cap."""
        if not self._log_file_path:
            return

        try:
            with self._file_lock:
                self._file_write_count += 1
                if self._file_write_count == 1 or (self._file_write_count % 50) == 0:
                    try:
                        if os.path.exists(self._log_file_path) and os.path.getsize(self._log_file_path) >= _MAX_LOG_FILE_BYTES:
                            rotated = self._log_file_path + ".old"
                            os.replace(self._log_file_path, rotated)
                    except OSError:
                        pass
                with open(self._log_file_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry.to_dict()) + '\n')
        except Exception as exc:
            # Log to QGIS message log instead of swallowing silently
            QgsMessageLog.logMessage(f"Failed to write log entry to file: {exc}", "Transformer", MsgWarning)

    def _add_to_activity_log(self, entry):
        """Add entry to Activity Log widget without acquiring the file I/O lock."""
        try:
            widget = self._activity_log_widget
            if widget is None or (_sip is not None and _sip.isdeleted(widget)):
                self._activity_log_widget = None
                return

            if isinstance(widget, QPlainTextEdit):
                if not widget.isVisible():
                    return
                widget.appendPlainText(entry.to_display_string())
                return

            from qgis.PyQt.QtGui import QTextCharFormat

            palette = QApplication.palette()
            colors = {
                'debug': palette_color(palette, None, 'PlaceholderText'),
                'info': palette_color(palette, None, 'Text'),
                'warning': palette_color(palette, None, 'ToolTipText'),
                'error': palette_color(palette, None, 'LinkVisited'),
                'critical': palette_color(palette, None, 'LinkVisited'),
            }

            color = colors.get(entry.severity, palette_color(palette, None, 'Text'))
            display_text = entry.to_display_string()

            if hasattr(widget, 'textCursor'):
                cursor = widget.textCursor()
                cursor.movePosition(CursorEnd)

                if cursor.columnNumber() > 0:
                    cursor.insertText("\n")

                cursor.insertText(display_text + "\n")

                cursor.movePosition(CursorUp)
                cursor.select(CursorLineUnder)
                fmt = QTextCharFormat()
                fmt.setForeground(color)
                if entry.severity in ['error', 'critical']:
                    fmt.setFontWeight(FontBold)
                cursor.setCharFormat(fmt)

                cursor.movePosition(CursorEnd)
                widget.setTextCursor(cursor)
                widget.ensureCursorVisible()
            elif hasattr(widget, 'appendPlainText'):
                widget.appendPlainText(display_text)

        except Exception as exc:
            QgsMessageLog.logMessage(f"Activity log write failed: {exc}", "Transformer", MsgWarning)

    # Convenience methods per @[/logger] standards
    def debug(self, message, module="system", code="DEBUG", context=None):
        """Log debug message"""
        self.log(message, "debug", module, code, context)

    def info(self, message, module="system", code="INFO", context=None):
        """Log info message"""
        self.log(message, "info", module, code, context)

    def warning(self, message, module="system", code="WARNING", context=None):
        """Log warning message"""
        self.log(message, "warning", module, code, context)

    def error(self, message, module="system", code="ERROR", context=None):
        """Log error message"""
        self.log(message, "error", module, code, context)

    def critical(self, message, module="system", code="CRITICAL", context=None):
        """Log critical message"""
        self.log(message, "critical", module, code, context)

    # Structured logging for ETL operations per @[/transformerdev]
    def log_transformation(self, operation, source=None, target=None, status="start", context=None):
        """Log transformation operations with standard codes"""
        codes = {
            'start': 'TRANSFORM_START',
            'success': 'TRANSFORM_SUCCESS',
            'fail': 'TRANSFORM_FAIL'
        }
        severity = 'info' if status == 'start' else ('info' if status == 'success' else 'error')

        if source and target:
            message = f"Transformation {operation}: {source} -> {target}"
        else:
            message = f"Transformation {operation}"

        self.log(message, severity, "transformer", codes.get(status, "TRANSFORM"), context)

    def log_export(self, format_type, target, status="start", context=None):
        """Log export operations"""
        codes = {
            'start': 'EXPORT_START',
            'success': 'EXPORT_SUCCESS',
            'fail': 'EXPORT_FAIL'
        }
        severity = 'info' if status == 'start' else ('info' if status == 'success' else 'error')
        message = f"Export to {format_type}: {target}"

        self.log(message, severity, "exporter", codes.get(status, "EXPORT"), context)

    def log_db_operation(self, operation, table=None, status="start", context=None):
        """Log database operations"""
        codes = {
            'connect': 'DB_CONNECT',
            'fail': 'DB_CONN_FAIL',
            'table': 'TABLE_CREATE',
            'transfer': 'DATA_TRANSFER'
        }
        severity = 'info' if status in ['connect', 'table', 'transfer'] else 'error'

        if table:
            message = f"Database {operation}: {table}"
        else:
            message = f"Database {operation}"

        self.log(message, severity, "db", codes.get(operation, "DB_OPERATION"), context)


# Global logger instance
logger = TransformerLogger()

# Legacy compatibility functions


def log_info(message, category="Transformer"):
    """Legacy compatibility function"""
    logger.info(message, "system", "INFO", {"category": category})


def log_warning(message, category="Transformer"):
    """Legacy compatibility function"""
    logger.warning(message, "system", "WARNING", {"category": category})


def log_error(message, category="Transformer"):
    """Legacy compatibility function"""
    logger.error(message, "system", "ERROR", {"category": category})


def log_success(message, category="Transformer"):
    """Legacy compatibility function"""
    logger.info(message, "system", "SUCCESS", {"category": category})


def log_critical(message, category="Transformer"):
    """Legacy compatibility function"""
    logger.critical(message, "system", "CRITICAL", {"category": category})
