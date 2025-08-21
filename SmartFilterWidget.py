
# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import pyqtSignal

# Import QTimer with fallback
try:
    from qgis.PyQt.QtCore import QTimer
except ImportError:
    try:
        from PyQt5.QtCore import QTimer
    except ImportError:
        class QTimer:
            @staticmethod
            def singleShot(msec, func):
                try:
                    func()
                except:
                    pass
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton, 
    QCheckBox, QComboBox
)
from qgis.core import QgsExpression

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

class SmartFilterWidget(QWidget):
    """Smart filter widget with suggestions"""
    
    filter_changed = pyqtSignal(str)
    filter_applied = pyqtSignal(str, bool)  # expression, enabled
    
    def __init__(self, layer=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.filter_templates = self.load_filter_templates()
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """Configure the filter widget interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header with activation
        header_layout = QHBoxLayout()
        
        self.enable_filter_cb = QCheckBox("Enable Filter")
        self.enable_filter_cb.setFont(QFont("Segoe UI", 9, QFont.Bold))
        header_layout.addWidget(self.enable_filter_cb)
        
        header_layout.addStretch()
        
        # Info filtre intégrée - apparaît seulement quand nécessaire
        self.filter_status_label = QLabel()
        self.filter_status_label.setFont(QFont("Segoe UI", 8))
        self.filter_status_label.setVisible(False)
        header_layout.addWidget(self.filter_status_label)
        
        self.filter_count_label = QLabel()
        self.filter_count_label.setFont(QFont("Segoe UI", 8))
        self.filter_count_label.setVisible(False)
        self.filter_count_label.setStyleSheet("margin-left: 8px;")
        header_layout.addWidget(self.filter_count_label)
        
        # Espacement avant les boutons
        header_layout.addSpacing(10)
        
        # Action buttons - version compacte
        self.test_filter_btn = QPushButton("Test")
        self.test_filter_btn.setMaximumWidth(50)  # Réduit de 60 à 50
        self.test_filter_btn.setMaximumHeight(22)  # Réduit de 28 à 22
        self.test_filter_btn.setFont(QFont("Segoe UI", 8))  # Police plus petite
        self.test_filter_btn.setEnabled(False)
        self.test_filter_btn.setStyleSheet("""
            QPushButton {
                font-size: 8px;
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 2px 4px;
                background-color: palette(button);
                color: palette(button-text);
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
            QPushButton:disabled {
                background-color: palette(button);
                color: palette(disabled-text);
                border-color: palette(disabled-text);
            }
        """)
        
        self.builder_btn = QPushButton("Builder")
        self.builder_btn.setMaximumWidth(60)  # Réduit de 70 à 60
        self.builder_btn.setMaximumHeight(22)  # Réduit de 28 à 22
        self.builder_btn.setFont(QFont("Segoe UI", 8))  # Police plus petite
        self.builder_btn.setEnabled(False)
        self.builder_btn.setStyleSheet("""
            QPushButton {
                font-size: 8px;
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 2px 4px;
                background-color: palette(button);
                color: palette(button-text);
            }
            QPushButton:hover {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
            QPushButton:disabled {
                background-color: palette(button);
                color: palette(disabled-text);
                border-color: palette(disabled-text);
            }
        """)
        
        header_layout.addWidget(self.test_filter_btn)
        header_layout.addWidget(self.builder_btn)
        
        layout.addLayout(header_layout)
        
        # Filter expression with auto-completion
        filter_layout = QHBoxLayout()
        
        self.filter_expression = QLineEdit()
        self.filter_expression.setPlaceholderText('e.g., "TYPE" = \'Building\' AND area($geometry) > 1000')
        self.filter_expression.setEnabled(False)
        
        filter_layout.addWidget(QLabel("Filter:"))
        filter_layout.addWidget(self.filter_expression)
        
        layout.addLayout(filter_layout)
        
        # Templates and suggestions
        templates_layout = QHBoxLayout()
        templates_layout.addWidget(QLabel("Quick:"))
        
        # Quick templates buttons
        self.template_buttons = []
        templates = [
            ("Area > 100", "area($geometry) > 100"),
            ("Valid Geom", "is_valid($geometry)"),
            ("Not NULL", '"FIELD" IS NOT NULL'),
            ("By Type", '"TYPE" = \'VALUE\''),
            ("Date Range", '"DATE" >= \'2023-01-01\'')
        ]

        for name, template in templates:
            btn = QPushButton(name)
            btn.setMaximumWidth(65)
            btn.setMaximumHeight(24)
            btn.setEnabled(False)
            btn.setStyleSheet("""
                QPushButton { 
                    font-size: 9px;
                    border: 1px solid palette(mid);
                    border-radius: 3px;
                    padding: 2px 4px;
                    background-color: palette(button);
                    color: palette(button-text);
                }
                QPushButton:hover {
                    background-color: palette(highlight);
                    color: palette(highlighted-text);
                }
                QPushButton:disabled {
                    background-color: palette(button);
                    color: palette(disabled-text);
                    border-color: palette(disabled-text);
                }
            """)
            btn.clicked.connect(lambda checked, t=template: self.apply_template(t))
            self.template_buttons.append(btn)
            templates_layout.addWidget(btn)
        
        templates_layout.addStretch()
        layout.addLayout(templates_layout)
        
        # Les labels de statut/compteur sont maintenant dans le header
        # Plus besoin du panel séparé - économise de l'espace !
        
        self.setLayout(layout)
    
    def setup_connections(self):
        """Configure the signal connections"""
        self.enable_filter_cb.toggled.connect(self.on_filter_enabled_changed)
        self.filter_expression.textChanged.connect(self.on_filter_expression_changed)
        self.test_filter_btn.clicked.connect(self.test_filter)
        self.builder_btn.clicked.connect(self.open_filter_builder)
    
    def set_layer(self, layer):
        """Set the context layer"""
        self.layer = layer
        self.update_template_buttons()
    
    def update_template_buttons(self):
        """Update template buttons based on the layer"""
        if not self.layer:
            return
        
        # Adapt templates based on available fields
        fields = self.layer.fields()
        field_names = [field.name() for field in fields]
        
        # Search for common fields
        type_fields = [name for name in field_names if 'type' in name.lower() or 'class' in name.lower()]
        status_fields = [name for name in field_names if 'status' in name.lower() or 'state' in name.lower()]
        date_fields = [name for name in field_names if 'date' in name.lower() or 'time' in name.lower()]
        
        # Update templates
        if len(self.template_buttons) >= 4:
            if type_fields:
                self.template_buttons[3].setText(f'By {type_fields[0][:6]}')
                try:
                    self.template_buttons[3].clicked.disconnect()
                except TypeError:
                    pass  # No connections to disconnect
                self.template_buttons[3].clicked.connect(
                    lambda: self.apply_template(f'"{type_fields[0]}" = \'VALUE\'')
                )
            
            if date_fields:
                self.template_buttons[4].setText(f'{date_fields[0][:6]} >')
                try:
                    self.template_buttons[4].clicked.disconnect()
                except TypeError:
                    pass  # No connections to disconnect
                self.template_buttons[4].clicked.connect(
                    lambda: self.apply_template(f'"{date_fields[0]}" >= \'2023-01-01\'')
                )
    
    def on_filter_enabled_changed(self, enabled):
        """Filter activation/deactivation management"""
        self.filter_expression.setEnabled(enabled)
        self.builder_btn.setEnabled(enabled)
        self.test_filter_btn.setEnabled(enabled)
        
        for btn in self.template_buttons:
            btn.setEnabled(enabled)
        
        # Filter info panel visibility handled in update_filter_info()
        if hasattr(self, 'filter_info_panel'):
            self.filter_info_panel.setVisible(enabled)
        
        if not enabled:
            self.filter_expression.clear()
        
        self.emit_filter_changed()
    
    def on_filter_expression_changed(self):
        """Filter expression change management"""
        self.filter_changed.emit(self.get_filter_expression())
        self.update_filter_info()
    
    def apply_template(self, template):
        """Apply a filter template"""
        if self.enable_filter_cb.isChecked():
            current_text = self.filter_expression.text().strip()
            
            if current_text:
                # Combiner avec l'expression existante
                combined = f"({current_text}) AND ({template})"
                self.filter_expression.setText(combined)
            else:
                self.filter_expression.setText(template)
    
    def test_filter(self):
        """Test the filter expression"""
        if not self.layer:
            QMessageBox.warning(self, "Warning", "No layer context available")
            return
        
        filter_expr = self.get_filter_expression()
        if not filter_expr:
            QMessageBox.warning(self, "Warning", "No filter expression to test")
            return
        
        try:
            # Test expression
            expression = QgsExpression(filter_expr)
            
            if expression.hasParserError():
                QMessageBox.warning(self, "Filter Error", f"Syntax error: {expression.parserErrorString()}")
                return
            
            # Count matching features
            request = QgsFeatureRequest()
            request.setFilterExpression(filter_expr)
            
            filtered_features = list(self.layer.getFeatures(request))
            total_features = self.layer.featureCount()
            filtered_count = len(filtered_features)
            
            # Display results
            reduction_percent = ((total_features - filtered_count) / total_features * 100) if total_features > 0 else 0
            
            result_message = f"""Filter Test Results

Expression: {filter_expr}

Results:
• Total features: {total_features:,}
• Filtered features: {filtered_count:,}
• Reduction: {reduction_percent:.1f}%

Filter is valid and ready to use!"""
            
            QMessageBox.information(self, "Filter Test", result_message)
            
            # Update display
            self.update_filter_status(True, filtered_count, total_features)
            
        except Exception as e:
            QMessageBox.critical(self, "Filter Error", f"Error testing filter: {str(e)}")
    
    def open_filter_builder(self):
        """Open the expression builder for the filter"""
        if not self.layer:
            QMessageBox.warning(self, "Warning", "No layer context available")
            return
        
        current_expr = self.filter_expression.text().strip()
        
        dialog = QgsExpressionBuilderDialog(self.layer, current_expr, self)
        dialog.setWindowTitle("Filter Expression Builder")
        
        if dialog.exec_() == QDialog.Accepted:
            new_expr = dialog.expressionText()
            self.filter_expression.setText(new_expr)
            
            # Automatic test after construction
            QTimer.singleShot(100, self.test_filter)
    
    def get_filter_expression(self):
        """Get the current filter expression"""
        if self.enable_filter_cb.isChecked():
            return self.filter_expression.text().strip()
        return ""
    
    def get_filter_config(self):
        """Get the filter configuration"""
        return {
            "enabled": self.enable_filter_cb.isChecked(),
            "expression": self.get_filter_expression()
        }
    
    def set_filter_config(self, config):
        """Set the filter configuration"""
        if config and isinstance(config, dict):
            enabled = config.get("enabled", False)
            expression = config.get("expression", "")
            
            self.enable_filter_cb.setChecked(enabled)
            self.filter_expression.setText(expression)
    
    def emit_filter_changed(self):
        """Emit the filter change signal"""
        config = self.get_filter_config()
        self.filter_applied.emit(config.get("expression", ""), config.get("enabled", False))
    
    def update_filter_info(self):
        """Update filter information - affichage intégré dans le header"""
        if not self.enable_filter_cb.isChecked():
            # Masquer les informations si le filtre est désactivé
            self.filter_status_label.setVisible(False)
            self.filter_count_label.setVisible(False)
            return
        
        filter_expr = self.get_filter_expression()
        if filter_expr:
            self.filter_status_label.setText("Active")
            self.filter_status_label.setStyleSheet("font-weight: bold;")
            self.filter_status_label.setVisible(True)
        else:
            self.filter_status_label.setText("No expression")
            self.filter_status_label.setStyleSheet("font-weight: bold;")
            self.filter_status_label.setVisible(True)
            self.filter_count_label.setVisible(False)
    
    def update_filter_status(self, valid, filtered_count, total_count):
        """Update filter status - affichage intégré dans le header"""
        if valid:
            self.filter_status_label.setText("Valid")
            self.filter_status_label.setStyleSheet("font-weight: bold;")
            self.filter_count_label.setText(f"({filtered_count:,}/{total_count:,})")
            # Rendre visible les informations
            self.filter_status_label.setVisible(True)
            self.filter_count_label.setVisible(True)
        else:
            self.filter_status_label.setText("Invalid")
            self.filter_status_label.setStyleSheet("font-weight: bold;")
            self.filter_count_label.clear()
            # Rendre visible l'erreur, masquer le compteur
            self.filter_status_label.setVisible(True)
            self.filter_count_label.setVisible(False)
    
    def load_filter_templates(self):
        """Load filter templates"""
        return {
            "geometry": [
                ("Valid geometries", "is_valid($geometry)"),
                ("Area greater than", "area($geometry) > 1000"),
                ("Perimeter less than", "perimeter($geometry) < 500"),
                ("Contains point", "contains($geometry, make_point(x, y))"),
                ("Intersects extent", "intersects($geometry, geom_from_wkt('POLYGON((...))'))")
            ],
            "attributes": [
                ("Not null", '"FIELD" IS NOT NULL'),
                ("Equals value", '"FIELD" = \'VALUE\''),
                ("Contains text", '"FIELD" LIKE \'%TEXT%\''),
                ("Numeric range", '"FIELD" BETWEEN 10 AND 100'),
                ("In list", '"FIELD" IN (\'A\', \'B\', \'C\')')
            ],
            "temporal": [
                ("After date", '"DATE_FIELD" >= \'2023-01-01\''),
                ("Between dates", '"DATE_FIELD" BETWEEN \'2023-01-01\' AND \'2023-12-31\''),
                ("Recent features", '"DATE_FIELD" >= (now() - interval \'30 days\')'),
                ("This year", 'year("DATE_FIELD") = year(now())'),
                ("This month", 'month("DATE_FIELD") = month(now()) AND year("DATE_FIELD") = year(now())')
            ]
        }

