
# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QMessageBox, QDialogButtonBox
)

class FieldDefinitionDialog(QDialog):
    """Field definition dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Field Definition")
        self.setModal(True)
        self.resize(400, 200)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Formulaire
        form_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter field name...")
        form_layout.addRow("Field Name:", self.name_edit)
        
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional description...")
        form_layout.addRow("Description:", self.description_edit)
        
        layout.addLayout(form_layout)
        
        # Boutons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def set_field_info(self, name, description=""):
        """Set field information"""
        self.name_edit.setText(name)
        self.description_edit.setText(description)
    
    def get_field_info(self):
        """Get field information"""
        return (
            self.name_edit.text().strip(),
            self.description_edit.text().strip()
        )
    
    def accept(self):
        """Validation avant acceptation"""
        name = self.name_edit.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Warning", "Field name is required")
            return
        
        super().accept()

