#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centralized logging module for Transformer
Automatically sends messages to:
- QgsMessageLog (QGIS messages)
- Plugin Activity Log (user panel)
"""

from datetime import datetime
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsMessageLog, Qgis

class TransformerLogger(QObject):
    """Centralized logger for Transformer plugin"""
    
    # Signal emitted when a log message is created
    log_message_created = pyqtSignal(str, str)  # message, level
    
    def __init__(self):
        super().__init__()
        self._activity_log_widget = None
        self._logging_lock = False
        
    def set_activity_log_widget(self, widget):
        """Sets the Activity Log widget for display"""
        self._activity_log_widget = widget
        
    def log(self, message, level="Info", category="Transformer"):
        """
        Log a message to all systems
        
        Args:
            message (str): Message to log
            level (str): Level: Info, Warning, Error, Success
            category (str): Category for QgsMessageLog
        """
        try:
            # 1. Log to QgsMessageLog (QGIS messages)
            qgis_level = self._get_qgis_level(level)
            QgsMessageLog.logMessage(message, category, qgis_level)
            
            # 2. Log to plugin Activity Log if available
            if self._activity_log_widget:
                self._add_to_activity_log(message, level)
            
            # 3. Emit signal for other listeners
            self.log_message_created.emit(message, level)
            
        except Exception:
            # Avoid cascading errors in logging
            pass
    
    def _get_qgis_level(self, level):
        """Convert string level to Qgis level"""
        level_map = {
            "Info": Qgis.Info,
            "Warning": Qgis.Warning,
            "Error": Qgis.Critical,
            "Success": Qgis.Info,
            "Critical": Qgis.Critical
        }
        return level_map.get(level, Qgis.Info)
    
    def _add_to_activity_log(self, message, level):
        """Add message to Activity Log panel with color coding using QTextCursor"""
        # Prevent concurrent logging operations
        if self._logging_lock:
            return
            
        try:
            from qgis.PyQt.QtGui import QTextCursor, QTextCharFormat, QColor
            from qgis.PyQt.QtWidgets import QApplication
            
            self._logging_lock = True  # Lock during operation
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Define colors and prefixes for each level
            level_config = {
                "Info": {"prefix": "INFO", "color": QColor("#ffffff")},        # White
                "Warning": {"prefix": "WARN", "color": QColor("#ff8c00")},     # Orange
                "Error": {"prefix": "ERROR", "color": QColor("#ff4444")},      # Red
                "Success": {"prefix": "SUCCESS", "color": QColor("#28a745")},   # Green
                "Critical": {"prefix": "CRITICAL", "color": QColor("#dc3545")} # Dark Red
            }
            
            config = level_config.get(level, {"prefix": "LOG", "color": QColor("#cccccc")})
            
            # Single atomic insertion with QTextCursor for colors + guaranteed line separation
            if hasattr(self._activity_log_widget, 'textCursor'):
                # Ensure we start on a new line by adding one if needed
                cursor = self._activity_log_widget.textCursor()
                cursor.movePosition(QTextCursor.End)
                
                # Check if we need to add a newline first (if cursor not at start of line)
                if cursor.columnNumber() > 0:
                    cursor.insertText("\n")
                
                # Build complete message as one atomic operation
                full_message = f"[{timestamp}] {config['prefix']} {message}\n"
                
                # Insert with default formatting first
                start_position = cursor.position()
                cursor.insertText(full_message)
                
                # Now apply formatting to specific ranges
                # Format timestamp in gray
                cursor.setPosition(start_position)
                cursor.setPosition(start_position + len(f"[{timestamp}] "), QTextCursor.KeepAnchor)
                timestamp_format = QTextCharFormat()
                timestamp_format.setForeground(QColor("#888888"))
                cursor.setCharFormat(timestamp_format)
                
                # Format level prefix with color and bold
                cursor.setPosition(start_position + len(f"[{timestamp}] "))
                cursor.setPosition(start_position + len(f"[{timestamp}] {config['prefix']} "), QTextCursor.KeepAnchor)
                level_format = QTextCharFormat()
                level_format.setForeground(config["color"])
                level_format.setFontWeight(600)
                cursor.setCharFormat(level_format)
                
                # Format message with color
                cursor.setPosition(start_position + len(f"[{timestamp}] {config['prefix']} "))
                cursor.setPosition(start_position + len(f"[{timestamp}] {config['prefix']} {message}"), QTextCursor.KeepAnchor)
                message_format = QTextCharFormat()
                message_format.setForeground(config["color"])
                cursor.setCharFormat(message_format)
                
                # Position cursor at the very end
                cursor.movePosition(QTextCursor.End)
                self._activity_log_widget.setTextCursor(cursor)
                self._activity_log_widget.ensureCursorVisible()
                
            else:
                # Fallback to plain text methods
                plain_entry = f"[{timestamp}] {config['prefix']} {message}"
                if hasattr(self._activity_log_widget, 'appendPlainText'):
                    self._activity_log_widget.appendPlainText(plain_entry)
                elif hasattr(self._activity_log_widget, 'append'):
                    self._activity_log_widget.append(plain_entry)
            
            # Force event processing to prevent line merging
            if QApplication.instance():
                QApplication.processEvents()
            
        except Exception:
            # Avoid cascading errors - fallback to simple text
            try:
                plain_entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
                if hasattr(self._activity_log_widget, 'appendPlainText'):
                    self._activity_log_widget.appendPlainText(plain_entry)
            except:
                pass
        finally:
            # Always release the lock
            self._logging_lock = False
    
    # Convenience methods for different levels
    def info(self, message, category="Transformer"):
        """Log an information message"""
        self.log(message, "Info", category)
    
    def warning(self, message, category="Transformer"):
        """Log a warning"""
        self.log(message, "Warning", category)
    
    def error(self, message, category="Transformer"):
        """Log an error"""
        self.log(message, "Error", category)
    
    def success(self, message, category="Transformer"):
        """Log a success"""
        self.log(message, "Success", category)
    
    def critical(self, message, category="Transformer"):
        """Log a critical error"""
        self.log(message, "Critical", category)


# Global logger instance
logger = TransformerLogger()

# Convenience functions for simple import
def log(message, level="Info", category="Transformer"):
    """Global logging function"""
    logger.log(message, level, category)

def log_info(message, category="Transformer"):
    """Information log"""
    logger.info(message, category)

def log_warning(message, category="Transformer"):
    """Warning log"""
    logger.warning(message, category)

def log_error(message, category="Transformer"):
    """Error log"""
    logger.error(message, category)

def log_success(message, category="Transformer"):
    """Success log"""
    logger.success(message, category)

def log_critical(message, category="Transformer"):
    """Critical log"""
    logger.critical(message, category)
