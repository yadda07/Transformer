
# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QGroupBox, QTableWidget, QTableWidgetItem, QDialogButtonBox, QMessageBox
)
from qgis.gui import QgsMapLayerComboBox

from ..shared.helpers import get_plugin_icon, create_layer_expression_context
from ..shared.expression_utils import validate_expression_syntax, evaluate_expression
from .advanced_expression_widget import AdvancedExpressionWidget

class ExpressionTesterDialog(QDialog):
    """Expression tester dialog"""
    
    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        
        self.setWindowTitle("Transformer - Expression Tester")
        self.setModal(True)
        self.resize(800, 600)
        
        self.setWindowIcon(get_plugin_icon())
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Layer selection
        if not self.layer:
            layer_layout = QHBoxLayout()
            layer_layout.addWidget(QLabel("Layer:"))
            
            self.layer_combo = QgsMapLayerComboBox()
            # Configuration pour couches vectorielles uniquement - approche moderne QGIS
            self.layer_combo.setShowCrs(True)
            self.layer_combo.setAllowEmptyLayer(False)
            layer_layout.addWidget(self.layer_combo)
            
            layout.addLayout(layer_layout)
        
        # Expression builder
        self.expression_widget = AdvancedExpressionWidget(self.layer)
        layout.addWidget(self.expression_widget)
        
        # Résultats
        results_group = QGroupBox("Test Results")
        results_layout = QVBoxLayout()
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Feature ID", "Result", "Type"])
        self.results_table.setMaximumHeight(200)
        
        results_layout.addWidget(self.results_table)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        # Actions
        actions_layout = QHBoxLayout()
        
        self.test_btn = QPushButton("Test Expression")
        self.test_btn.clicked.connect(self.test_expression)
        
        self.test_sample_btn = QPushButton("Test Sample (10 features)")
        self.test_sample_btn.clicked.connect(lambda: self.test_expression(sample_size=10))
        
        actions_layout.addWidget(self.test_btn)
        actions_layout.addWidget(self.test_sample_btn)
        actions_layout.addStretch()
        
        layout.addLayout(actions_layout)
        
        # Close buttons
        from ..shared.compat import DlgBtnClose
        buttons = QDialogButtonBox(DlgBtnClose)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure connections"""
        if hasattr(self, 'layer_combo'):
            self.layer_combo.layerChanged.connect(self.on_layer_changed)
    
    def on_layer_changed(self, layer):
        """Handle layer change"""
        self.layer = layer
        self.expression_widget.set_layer(layer)
        self.results_table.setRowCount(0)
    
    def test_expression(self, sample_size=None):
        """Test expression on features"""
        try:
            if not self.layer:
                QMessageBox.warning(self, "Warning", "No layer selected")
                return
            
            expression_text = self.expression_widget.get_expression().strip()
            if not expression_text:
                QMessageBox.warning(self, "Warning", "No expression to test")
                return
            
            is_valid, error_msg, expression = validate_expression_syntax(expression_text)
            if not is_valid:
                QMessageBox.warning(self, "Expression Error", f"Syntax error: {error_msg}")
                return
            
            # Prepare the context
            context = create_layer_expression_context(self.layer)
            
            # Get features
            if sample_size:
                features = list(self.layer.getFeatures())[:sample_size]
            else:
                features = list(self.layer.getFeatures())
            
            # Configure the table
            self.results_table.setRowCount(len(features))
            
            # Test on each feature
            for i, feature in enumerate(features):
                context.setFeature(feature)
                
                try:
                    success, result, eval_error = evaluate_expression(expression, context)
                    
                    if not success:
                        result_text = f"ERROR: {eval_error}"
                        result_type = "Error"
                    else:
                        result_text = str(result) if result is not None else "NULL"
                        result_type = type(result).__name__
                    
                except Exception as e:
                    result_text = f"EXCEPTION: {str(e)}"
                    result_type = "Exception"
                
                # Fill the table
                self.results_table.setItem(i, 0, QTableWidgetItem(str(feature.id())))
                self.results_table.setItem(i, 1, QTableWidgetItem(result_text))
                self.results_table.setItem(i, 2, QTableWidgetItem(result_type))
            
            # Adjust columns
            self.results_table.resizeColumnsToContents()
            
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"Error testing expression: {str(e)}")

