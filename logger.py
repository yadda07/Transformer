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
        """Add message to Activity Log panel"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            level_prefix = {
                "Info": "ℹ",
                "Warning": "⚠",
                "Error": "✗",
                "Success": "✓",
                "Critical": "🔥"
            }.get(level, "•")
            
            log_entry = f"[{timestamp}] {level_prefix} {message}"
            
            # Add to log widget if it exists
            if hasattr(self._activity_log_widget, 'appendPlainText'):
                self._activity_log_widget.appendPlainText(log_entry)
            
        except Exception:
            # Avoid cascading errors
            pass
    
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
