# -*- coding: utf-8 -*-
"""
Smooth transparent configuration selector widget
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, 
    QMenu, QAction, QFrame
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QPoint

# Import QTimer with fallback
try:
    from qgis.PyQt.QtCore import QTimer
except ImportError:
    try:
        from PyQt5.QtCore import QTimer
    except ImportError:
        class QTimer:
            def __init__(self, parent=None):
                pass
            def timeout(self):
                class Signal:
                    def connect(self, func):
                        pass
                return Signal()
            def setSingleShot(self, single):
                pass
            def start(self, msec=None):
                pass
            def stop(self):
                pass
            @staticmethod
            def singleShot(msec, func):
                try:
                    func()
                except:
                    pass
from qgis.PyQt.QtGui import QCursor

# Import QFont with fallback
try:
    from qgis.PyQt.QtGui import QFont
except ImportError:
    try:
        from PyQt5.QtGui import QFont
    except ImportError:
        class QFont:
            def __init__(self, family="Arial", size=9, weight=None):
                pass
            class Bold:
                pass
            class Medium:
                pass


class SmoothConfigSelector(QWidget):
    """Smooth transparent selector for multiple configurations"""
    
    config_selected = pyqtSignal(str, str)  # table_name, filename
    config_deleted = pyqtSignal(str)        # table_name
    
    def __init__(self, parent, table_names, filename):
        super().__init__(parent)
        self.table_names = table_names
        self.filename = filename
        self.setup_ui()
        
    def setup_ui(self):
        """Setup smooth transparent UI"""
        # Window properties - transparent and floating
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Container frame with smooth styling
        self.frame = QFrame()
        self.frame.setStyleSheet("""
            QFrame {
                background-color: rgba(45, 45, 45, 240);
                border: 1px solid rgba(100, 100, 100, 150);
                border-radius: 8px;
                padding: 2px;
            }
        """)
        layout.addWidget(self.frame)
        
        # List widget for configurations
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        
        self.config_list = QListWidget()
        self.config_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
                font-size: 13px;
                font-weight: 500;
            }
            QListWidget::item {
                color: #FFFFFF;
                padding: 8px 12px;
                border-bottom: 1px solid rgba(100, 100, 100, 80);
                background: transparent;
            }
            QListWidget::item:hover {
                background-color: rgba(76, 175, 80, 120);
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: rgba(33, 150, 243, 150);
                border-radius: 4px;
            }
        """)
        
        # Configure list widget
        self.config_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.config_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.config_list.setSelectionMode(QListWidget.SingleSelection)
        
        # Add configurations to list
        for table_name in self.table_names:
            item = QListWidgetItem(f"📋 {table_name}")
            item.setData(Qt.UserRole, table_name)
            item.setToolTip(f"Configuration: {table_name}\nSource: {self.filename}")
            self.config_list.addItem(item)
        
        frame_layout.addWidget(self.config_list)
        
        # Connect signals
        self.config_list.itemClicked.connect(self.on_item_clicked)
        self.config_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.config_list.customContextMenuRequested.connect(self.show_context_menu)
        
        # Auto-hide timer
        self.hide_timer = QTimer()
        self.hide_timer.timeout.connect(self.fade_out)
        self.hide_timer.setSingleShot(True)
        
        # Calculate optimal size
        self.adjust_size()
    
    def adjust_size(self):
        """Adjust widget size to content"""
        item_height = 36  # padding + font + border
        list_height = len(self.table_names) * item_height
        max_width = 0
        
        # Calculate max width needed
        font = QFont()
        font.setPointSize(13)
        font.setWeight(QFont.Medium)
        
        from qgis.PyQt.QtGui import QFontMetrics
        metrics = QFontMetrics(font)
        
        for table_name in self.table_names:
            text_width = metrics.width(f"📋 {table_name}")
            max_width = max(max_width, text_width + 40)  # padding + icon space
        
        # Set fixed size - compact and minimal
        widget_width = max(200, min(400, max_width))
        widget_height = list_height + 4  # frame padding
        
        self.setFixedSize(widget_width, widget_height)
        
    def show_at_cursor(self):
        """Show selector at cursor position"""
        cursor_pos = QCursor.pos()
        
        # Offset slightly to avoid cursor overlap
        show_pos = QPoint(cursor_pos.x() + 10, cursor_pos.y() + 10)
        
        # Ensure within screen bounds
        screen = self.parent().screen()
        screen_geom = screen.availableGeometry()
        
        if show_pos.x() + self.width() > screen_geom.right():
            show_pos.setX(cursor_pos.x() - self.width() - 10)
        if show_pos.y() + self.height() > screen_geom.bottom():
            show_pos.setY(cursor_pos.y() - self.height() - 10)
            
        self.move(show_pos)
        self.show()
        self.raise_()
        self.activateWindow()
        
        # Auto-select first item
        if self.config_list.count() > 0:
            self.config_list.setCurrentRow(0)
            
        # Start auto-hide timer (longer for user to read)
        self.hide_timer.start(8000)  # 8 seconds
    
    def on_item_clicked(self, item):
        """Handle configuration selection"""
        table_name = item.data(Qt.UserRole)
        self.config_selected.emit(table_name, self.filename)
        self.fade_out()
    
    def show_context_menu(self, position):
        """Show context menu with delete option"""
        item = self.config_list.itemAt(position)
        if not item:
            return
            
        table_name = item.data(Qt.UserRole)
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(60, 60, 60, 240);
                border: 1px solid rgba(100, 100, 100, 150);
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #FFFFFF;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: rgba(244, 67, 54, 150);
            }
        """)
        
        # Delete action
        delete_action = QAction("🗑️ Delete Configuration", self)
        delete_action.triggered.connect(lambda: self.delete_config(table_name))
        menu.addAction(delete_action)
        
        # Show context menu
        global_pos = self.config_list.mapToGlobal(position)
        menu.exec_(global_pos)
    
    def delete_config(self, table_name):
        """Delete a configuration"""
        self.config_deleted.emit(table_name)
        self.fade_out()
    
    def fade_out(self):
        """Smooth fade out and close"""
        self.hide()
        self.close()
        
    def keyPressEvent(self, event):
        """Handle keyboard navigation"""
        if event.key() == Qt.Key_Escape:
            self.fade_out()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            current_item = self.config_list.currentItem()
            if current_item:
                self.on_item_clicked(current_item)
        elif event.key() == Qt.Key_Up:
            current_row = self.config_list.currentRow()
            if current_row > 0:
                self.config_list.setCurrentRow(current_row - 1)
        elif event.key() == Qt.Key_Down:
            current_row = self.config_list.currentRow()
            if current_row < self.config_list.count() - 1:
                self.config_list.setCurrentRow(current_row + 1)
        else:
            super().keyPressEvent(event)
            
    def focusOutEvent(self, event):
        """Auto-hide when losing focus"""
        # Delay hide to allow context menu interaction
        QTimer.singleShot(200, self.fade_out)
        super().focusOutEvent(event)
