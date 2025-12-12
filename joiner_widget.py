# -*- coding: utf-8 -*-
"""
Professional Joiner Widget - Modular Architecture
QGIS Plugin Transformer - Professional Join Operations
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QCheckBox, QPushButton, 
    QProgressBar, QFrame, QSplitter, QScrollArea, 
    QTableWidget, QTableWidgetItem, QMenu, QAction,
    QSpinBox, QDoubleSpinBox,
    QLineEdit, QAbstractItemView
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QFont

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsField, QgsFields,
    QgsWkbTypes, QgsSpatialIndex, Qgis, QgsMessageLog, QgsMapLayerProxyModel,
    QgsCoordinateTransform
)

from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox

# Import logger
try:
    from .logger import log_info, log_success, log_warning, log_error, log_debug
except ImportError:
    # Fallback logging functions
    def log_info(msg): QgsMessageLog.logMessage(msg, "Transformer", Qgis.Info)
    def log_success(msg): QgsMessageLog.logMessage(msg, "Transformer", Qgis.Success) 
    def log_warning(msg): QgsMessageLog.logMessage(msg, "Transformer", Qgis.Warning)
    def log_error(msg): QgsMessageLog.logMessage(msg, "Transformer", Qgis.Critical)
    def log_debug(msg): QgsMessageLog.logMessage(msg, "Transformer", Qgis.Info)

class JoinType(Enum):
    """Enumération des types de jointures supportés"""
    ATTRIBUTE_JOIN = "Attribute Join"
    SPATIAL_INTERSECTS = "Spatial Intersects"
    SPATIAL_CONTAINS = "Spatial Contains"
    SPATIAL_WITHIN = "Spatial Within"
    SPATIAL_NEAREST = "Spatial Nearest (Distance-based)"
    SPATIAL_BUFFER = "Spatial Buffer"
    SPATIAL_OVERLAY = "Spatial Overlay"


class SpatialRelation(Enum):
    """Relations spatiales disponibles"""
    INTERSECTS = "intersects"
    CONTAINS = "contains"
    WITHIN = "within"
    TOUCHES = "touches"
    CROSSES = "crosses"
    OVERLAPS = "overlaps"
    DISJOINT = "disjoint"
    EQUALS = "equals"


@dataclass
class JoinConfiguration:
    """Configuration complète d'une jointure"""
    join_type: JoinType
    source_layer_id: str
    target_layer_id: str
    
    # Paramètres attributaires
    source_field: Optional[str] = None
    target_field: Optional[str] = None
    
    # Paramètres spatiaux
    spatial_relation: Optional[SpatialRelation] = None
    max_distance: float = 0.0
    distance_unit: str = "meters"
    buffer_distance: float = 0.0
    max_matches: int = 1
    
    # Options communes
    keep_unmatched: bool = True
    add_prefix: bool = False
    field_prefix: str = "target_"
    add_suffix: bool = False
    field_suffix: str = "_target"
    
    # Options avancées
    include_distance_field: bool = False
    include_match_index: bool = False
    match_strategy: str = "closest"
    
    # Options de géométrie pour jointures attributaires
    geometry_option: str = "source"  # "source", "target", "none"
    
    def is_valid(self) -> bool:
        """Vérifie si la configuration est valide avec messages détaillés"""
        if not self.source_layer_id:
            log_warning("ETL JOIN CONFIG: Source layer not selected - please select a source layer")
            return False
            
        if not self.target_layer_id:
            log_warning("ETL JOIN CONFIG: Target layer not selected - please select a target layer")
            return False
            
        # Vérifier que les couches existent encore dans le projet
        source_layer = QgsProject.instance().mapLayer(self.source_layer_id)
        target_layer = QgsProject.instance().mapLayer(self.target_layer_id)
        
        if not source_layer:
            log_warning(f"ETL JOIN CONFIG: Source layer with ID {self.source_layer_id} no longer exists in project")
            return False
            
        if not target_layer:
            log_warning(f"ETL JOIN CONFIG: Target layer with ID {self.target_layer_id} no longer exists in project")
            return False
            
        if self.join_type == JoinType.ATTRIBUTE_JOIN:
            if not self.source_field:
                log_warning("ETL JOIN CONFIG: Source field not selected for attribute join")
                return False
            if not self.target_field:
                log_warning("ETL JOIN CONFIG: Target field not selected for attribute join")
                return False
            log_info(f"ETL JOIN CONFIG: Valid attribute join - {source_layer.name()}[{self.source_field}] = {target_layer.name()}[{self.target_field}]")
            return True
        else:
            if not self.spatial_relation:
                log_warning("ETL JOIN CONFIG: Spatial relation not selected for spatial join")
                return False
            log_info(f"ETL JOIN CONFIG: Valid spatial join - {source_layer.name()} {self.spatial_relation.value} {target_layer.name()}")
            return True


class ParameterManager:
    """Gestionnaire centralisé des paramètres de jointure selon les standards QGIS"""
    
    def __init__(self, parent_widget: QWidget):
        self.parent = parent_widget
        self.widgets: Dict[str, QWidget] = {}
        # Layout vertical compact conforme au Designers Guide QGIS
        self.layout = QFormLayout()
        self.layout.setVerticalSpacing(6)  # Espacement minimal conforme QGIS
        self.layout.setHorizontalSpacing(10)
        self.layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.layout.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
    def clear_all(self):
        """Nettoie tous les widgets de manière propre"""
        # Méthode Qt standard pour nettoyer un layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()
        
        self.widgets.clear()
        # M07 fix: Removed QApplication.processEvents() - can cause recursion issues
        
    def add_parameter(self, key: str, widget: QWidget, label_text: str = None):
        """Ajoute un paramètre avec layout vertical compact conforme QGIS"""
        self.widgets[key] = widget
        
        if label_text:
            # Utiliser QFormLayout pour un espacement optimal
            self.layout.addRow(label_text, widget)
        else:
            # Widget sans label - utiliser toute la largeur
            self.layout.addRow(widget)
            
    def add_visual_separator(self):
        """Ajoute une ligne de séparation visuelle"""
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #ccc; margin: 8px 0px;")
        self.layout.addRow(separator)
            
    def get_widget(self, key: str) -> Optional[QWidget]:
        """Récupère un widget par sa clé"""
        return self.widgets.get(key)
        
    def set_visible(self, key: str, visible: bool):
        """Contrôle la visibilité d'un paramètre avec QFormLayout"""
        widget = self.widgets.get(key)
        if widget:
            # Cacher/afficher le widget lui-même
            widget.setVisible(visible)
            
            # Méthode correcte pour obtenir le label associé dans QFormLayout
            # labelForField() retourne le QLabel créé par addRow(str, widget)
            label = self.layout.labelForField(widget)
            if label:
                label.setVisible(visible)


class AttributeParameterBuilder:
    """Constructeur spécialisé pour les paramètres de jointure attributaire"""
    
    @staticmethod
    def build_parameters(manager: ParameterManager, layers_callback=None) -> Dict[str, QWidget]:
        """Construit tous les paramètres pour jointure attributaire"""
        
        # Sélection des champs
        source_field_combo = QgsFieldComboBox()
        source_field_combo.setToolTip("Field in source layer for matching")
        manager.add_parameter("source_field", source_field_combo, "Source Field:")
        
        target_field_combo = QgsFieldComboBox()
        target_field_combo.setToolTip("Field in target layer for matching")
        manager.add_parameter("target_field", target_field_combo, "Target Field:")
        
        # Options de jointure
        keep_unmatched_cb = QCheckBox("Keep unmatched features")
        keep_unmatched_cb.setChecked(True)
        keep_unmatched_cb.setToolTip("Include features without matches (LEFT JOIN)")
        manager.add_parameter("keep_unmatched", keep_unmatched_cb)
        
        # Préfixe
        prefix_cb = QCheckBox("Add prefix to joined fields")
        prefix_cb.setChecked(True)
        manager.add_parameter("add_prefix", prefix_cb)
        
        prefix_edit = QComboBox()
        prefix_edit.setEditable(True)
        prefix_edit.addItems(["target_", "joined_", "right_", "src_"])
        prefix_edit.setCurrentText("target_")
        manager.add_parameter("field_prefix", prefix_edit, "Prefix:")
        
        # Suffixe
        suffix_cb = QCheckBox("Add suffix to joined fields")
        suffix_cb.setChecked(False)
        manager.add_parameter("add_suffix", suffix_cb)
        
        suffix_edit = QComboBox()
        suffix_edit.setEditable(True)
        suffix_edit.addItems(["_target", "_joined", "_right", "_src"])
        suffix_edit.setCurrentText("_target")
        manager.add_parameter("field_suffix", suffix_edit, "Suffix:")
        
        # Choix de géométrie
        manager.add_visual_separator()
        
        geometry_combo = QComboBox()
        geometry_combo.addItems([
            "Keep source geometry", 
            "Keep target geometry", 
            "No geometry (table only)"
        ])
        geometry_combo.setCurrentIndex(0)  # Source par défaut
        geometry_combo.setToolTip("Choose which geometry to keep in the result")
        manager.add_parameter("geometry_option", geometry_combo, "Result Geometry:")
        
        return manager.widgets


class SpatialParameterBuilder:
    """Constructeur spécialisé pour les paramètres de jointure spatiale"""
    
    @staticmethod
    def build_parameters(manager: ParameterManager) -> Dict[str, QWidget]:
        """Construit tous les paramètres pour jointure spatiale"""
        
        # Relation spatiale
        relation_combo = QComboBox()
        relation_combo.addItems([rel.value for rel in SpatialRelation])
        relation_combo.setCurrentText(SpatialRelation.INTERSECTS.value)
        manager.add_parameter("spatial_relation", relation_combo, "Spatial Relation:")
        
        # Distance maximale
        distance_spin = QDoubleSpinBox()
        distance_spin.setRange(0, 999999)
        distance_spin.setValue(1000)
        distance_spin.setSuffix(" m")
        distance_spin.setToolTip("Maximum distance for spatial operations")
        manager.add_parameter("max_distance", distance_spin, "Max Distance:")
        
        # Unité de distance
        unit_combo = QComboBox()
        unit_combo.addItems(["meters", "kilometers", "feet", "miles", "degrees"])
        unit_combo.setCurrentText("meters")
        manager.add_parameter("distance_unit", unit_combo, "Distance Unit:")
        
        # Distance de buffer
        buffer_spin = QDoubleSpinBox()
        buffer_spin.setRange(0, 999999)
        buffer_spin.setValue(0)
        buffer_spin.setSuffix(" m")
        buffer_spin.setToolTip("Buffer distance around geometries")
        manager.add_parameter("buffer_distance", buffer_spin, "Buffer Distance:")
        
        # Nombre maximum de correspondances
        max_matches_spin = QSpinBox()
        max_matches_spin.setRange(1, 100)
        max_matches_spin.setValue(1)
        max_matches_spin.setToolTip("Maximum number of matches per feature")
        manager.add_parameter("max_matches", max_matches_spin, "Max Matches:")
        
        # Stratégie de correspondance
        strategy_combo = QComboBox()
        strategy_combo.addItems(["closest", "farthest", "largest_area", "smallest_area"])
        strategy_combo.setCurrentText("closest")
        manager.add_parameter("match_strategy", strategy_combo, "Match Strategy:")
        
        # Options avancées
        include_distance_cb = QCheckBox("Include distance field")
        include_distance_cb.setChecked(False)
        manager.add_parameter("include_distance", include_distance_cb)
        
        include_index_cb = QCheckBox("Include match index field")
        include_index_cb.setChecked(False)
        manager.add_parameter("include_index", include_index_cb)
        
        # Options communes aux jointures spatiales
        keep_unmatched_cb = QCheckBox("Keep unmatched features")
        keep_unmatched_cb.setChecked(True)
        manager.add_parameter("spatial_keep_unmatched", keep_unmatched_cb)
        
        # Préfixe pour jointures spatiales
        spatial_prefix_cb = QCheckBox("Add prefix to joined fields")
        spatial_prefix_cb.setChecked(True)
        manager.add_parameter("spatial_add_prefix", spatial_prefix_cb)
        
        spatial_prefix_edit = QLineEdit("spatial_")
        manager.add_parameter("spatial_field_prefix", spatial_prefix_edit, "Spatial Prefix:")
        
        return manager.widgets

# =============================================================================
# UTILITY FUNCTIONS - Centralized logic (M03/M04 fix - eliminate duplication)
# =============================================================================

def _build_join_index(layer, field_name: str) -> dict:
    """Build index for attribute join - centralized logic (M03 fix)
    
    Args:
        layer: QgsVectorLayer to index
        field_name: Field name to use as key
        
    Returns:
        dict mapping field values to list of features
    """
    join_index = {}
    for feature in layer.getFeatures():
        value = feature.attribute(field_name)
        if value is not None:
            if value not in join_index:
                join_index[value] = []
            join_index[value].append(feature)
    return join_index


def _copy_base_attributes(result_feature, source_feature, source_fields):
    """Copy attributes from source feature to result - centralized (M04 fix)"""
    for field in source_fields:
        result_feature.setAttribute(field.name(), source_feature.attribute(field.name()))


def _copy_joined_attributes(result_feature, join_feature, join_fields, prefix: str, exclude_field: str = None):
    """Copy attributes from joined feature with prefix - centralized (M04 fix)"""
    for field in join_fields:
        if exclude_field and field.name() == exclude_field:
            continue
        field_name = f"{prefix}{field.name()}"
        result_feature.setAttribute(field_name, join_feature.attribute(field.name()))


def _validate_crs(layer, layer_type: str = "Layer") -> bool:
    """Validate CRS is present and valid (C03 fix)"""
    if not layer.crs().isValid():
        log_error(f"ETL JOIN: Invalid CRS on {layer_type} '{layer.name()}'")
        return False
    return True


def _get_crs_string(layer) -> str:
    """Get CRS string safely - returns authid or WKT (C03 fix)"""
    crs = layer.crs()
    if crs.authid():
        return crs.authid()
    return crs.toWkt()


def _validate_spatial_relation_compatibility(source_layer, target_layer, relation) -> list:
    """Validate spatial relation is compatible with geometry types (C04 fix)
    
    Returns list of warning messages (empty if OK)
    """
    warnings = []
    
    src_type = source_layer.wkbType()
    tgt_type = target_layer.wkbType()
    
    # Get dimensions: 0=Point, 1=Line, 2=Polygon
    src_dim = QgsWkbTypes.geometryDimension(src_type)
    tgt_dim = QgsWkbTypes.geometryDimension(tgt_type)
    
    src_name = QgsWkbTypes.displayString(src_type)
    tgt_name = QgsWkbTypes.displayString(tgt_type)
    
    if relation == SpatialRelation.CONTAINS:
        if src_dim < tgt_dim:
            warnings.append(f"CONTAINS: {src_name} cannot contain {tgt_name} (lower dimension)")
        if src_dim == 0:  # Points cannot contain anything
            warnings.append(f"CONTAINS: Points cannot contain other geometries")
            
    elif relation == SpatialRelation.WITHIN:
        if src_dim > tgt_dim:
            warnings.append(f"WITHIN: {src_name} rarely fits within {tgt_name}")
            
    elif relation == SpatialRelation.CROSSES:
        if src_dim == tgt_dim:
            warnings.append(f"CROSSES: Same dimension geometries ({src_name}) cannot cross each other")
            
    elif relation == SpatialRelation.OVERLAPS:
        if src_dim != tgt_dim:
            warnings.append(f"OVERLAPS: Different dimensions ({src_name} vs {tgt_name}) - use INTERSECTS instead")
    
    return warnings


def _check_crs_match(source_layer, target_layer):
    """Check CRS match and return transform if needed (C02 fix)
    
    Returns:
        tuple: (needs_transform: bool, transform: QgsCoordinateTransform or None, warning: str or None)
    """
    if source_layer.crs() == target_layer.crs():
        return False, None, None
    
    warning = f"CRS mismatch - Source: {source_layer.crs().authid()}, Target: {target_layer.crs().authid()}"
    transform = QgsCoordinateTransform(
        target_layer.crs(), 
        source_layer.crs(), 
        QgsProject.instance()
    )
    return True, transform, warning


class JoinerWidget(QWidget):
    """Widget principal pour les opérations de jointure - Architecture professionnelle"""
    
    # Signaux
    configuration_changed = pyqtSignal(object)  # JoinConfiguration
    join_executed = pyqtSignal(str, str, dict)  # source_id, target_id, params
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # État
        self.current_config = JoinConfiguration(
            join_type=JoinType.ATTRIBUTE_JOIN,
            source_layer_id="",
            target_layer_id=""
        )
        
        # Gestionnaires
        self.param_manager = ParameterManager(self)
        
        # Composants UI
        self.join_type_combo: Optional[QComboBox] = None
        self.source_layer_combo: Optional[QgsMapLayerComboBox] = None
        self.target_layer_combo: Optional[QgsMapLayerComboBox] = None
        self.field_mapping_table: Optional[QTableWidget] = None
        self.preview_status: Optional[QLabel] = None
        
        # État des paramètres
        self._parameters_initialized = False
        
        # Initialisation
        self.setup_ui()
        self.connect_signals()
        self.setup_layer_monitoring()
        
    def setup_ui(self):
        """Configuration de l'interface utilisateur selon les standards QGIS"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Configuration principale (fixe en haut)
        config_frame = self.create_configuration_frame()
        main_layout.addWidget(config_frame)
        
        # Splitter vertical pour zones redimensionnables
        splitter = QSplitter(Qt.Vertical)
        
        # Section paramètres redimensionnable avec scroll
        params_scroll = QScrollArea()
        params_scroll.setFrameStyle(QFrame.StyledPanel)
        params_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        params_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        params_widget = QWidget()
        params_widget.setLayout(self.param_manager.layout)
        
        params_scroll.setWidget(params_widget)
        params_scroll.setWidgetResizable(True)
        params_scroll.setMinimumHeight(120)  # Minimum très petit
        
        # Container pour paramètres + toolbar
        params_container = QWidget()
        params_container_layout = QVBoxLayout(params_container)
        params_container_layout.setContentsMargins(0, 0, 0, 0)
        params_container_layout.addWidget(params_scroll)
        
        # Barre d'outils intégrée
        toolbar = self.create_toolbar()
        params_container_layout.addWidget(toolbar)
        
        splitter.addWidget(params_container)
        
        # Zone de prévisualisation
        preview_frame = self.create_preview_area()
        preview_frame.setMinimumHeight(150)
        splitter.addWidget(preview_frame)
        
        # Configuration du splitter
        splitter.setStretchFactor(0, 1)  # Paramètres moins prioritaires
        splitter.setStretchFactor(1, 2)  # Prévisualisation plus prioritaire
        splitter.setSizes([200, 300])    # Tailles initiales
        
        main_layout.addWidget(splitter)
        
        # Initialiser les paramètres
        self.initialize_parameters()
        
    def connect_signals(self):
        """Connexion des signaux et slots"""
        
        # Attendre que les widgets soient créés
        QTimer.singleShot(100, self._connect_delayed_signals)
        
    def _connect_delayed_signals(self):
        """Connexion retardée des signaux après création complète des widgets"""
        
        # Changements de configuration
        if self.join_type_combo:
            self.join_type_combo.currentTextChanged.connect(self.on_join_type_changed)
            
        # Changements de couches
        if self.source_layer_combo:
            self.source_layer_combo.layerChanged.connect(self.on_source_layer_changed)
            self.source_layer_combo.layerChanged.connect(self.update_field_mapping_preview)
            self.source_layer_combo.layerChanged.connect(self.update_result_name_suggestion)
            
        if self.target_layer_combo:
            self.target_layer_combo.layerChanged.connect(self.on_target_layer_changed)
            self.target_layer_combo.layerChanged.connect(self.update_field_mapping_preview)
            self.target_layer_combo.layerChanged.connect(self.update_result_name_suggestion)
            
        # Connecter aussi le changement de type de jointure à la preview et suggestion de nom
        if self.join_type_combo:
            self.join_type_combo.currentTextChanged.connect(self.update_field_mapping_preview)
            self.join_type_combo.currentTextChanged.connect(self.update_result_name_suggestion)
        
    def create_configuration_frame(self) -> QFrame:
        """Crée le frame de configuration principal"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel)
        layout = QFormLayout(frame)
        
        # Type de jointure
        self.join_type_combo = QComboBox()
        self.join_type_combo.addItems([jt.value for jt in JoinType])
        layout.addRow("Join Type:", self.join_type_combo)
        
        # Sélection des couches avec widgets QGIS natifs
        self.source_layer_combo = QgsMapLayerComboBox()
        self.source_layer_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        layout.addRow("Source Layer:", self.source_layer_combo)
        
        self.target_layer_combo = QgsMapLayerComboBox()
        self.target_layer_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        layout.addRow("Target Layer:", self.target_layer_combo)
        
        return frame
        
    def create_preview_area(self) -> QFrame:
        """Crée la zone de mapping des champs"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        
        # Titre de la section
        title_label = QLabel("Field Mapping & Join Preview")
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # Table de mapping des champs avec plus d'espace
        self.field_mapping_table = QTableWidget()
        self.field_mapping_table.setColumnCount(5)
        self.field_mapping_table.setHorizontalHeaderLabels([
            "Field Name", "Type", "From Layer", "Status", "Result Name"
        ])
        self.field_mapping_table.setAlternatingRowColors(True)
        self.field_mapping_table.verticalHeader().setVisible(False)
        self.field_mapping_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.field_mapping_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.field_mapping_table.customContextMenuRequested.connect(self.show_context_menu)
        
        # Redimensionnement automatique des colonnes
        header = self.field_mapping_table.horizontalHeader()
        header.setStretchLastSection(True)
        
        layout.addWidget(self.field_mapping_table)
        
        # Barre de statut pour la prévisualisation  
        self.preview_status = QLabel("Select source and target layers to see field mapping")
        self.preview_status.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.preview_status)
        
        return frame
        
    def create_toolbar(self) -> QFrame:
        """Crée la barre d'outils optimisée avec nom de couche"""
        toolbar = QFrame()
        toolbar.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(toolbar)
        
        # Barre de progression
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Stretcher pour pousser à droite
        layout.addStretch()
        
        # Label pour le nom de résultat
        result_label = QLabel("Result Layer:")
        result_label.setStyleSheet("font-weight: bold; margin-right: 5px;")
        layout.addWidget(result_label)
        
        # Champ de saisie pour le nom de la couche résultante
        self.result_name_edit = QLineEdit()
        self.result_name_edit.setPlaceholderText("Enter result layer name...")
        self.result_name_edit.setMinimumWidth(200)
        self.result_name_edit.setMaximumWidth(300)
        self.result_name_edit.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                border: 2px solid #ddd;
                border-radius: 4px;
                background-color: white;
                margin-right: 10px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
        """)
        layout.addWidget(self.result_name_edit)
        
        # Bouton d'exécution
        self.execute_btn = QPushButton("Execute Join")
        self.execute_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        layout.addWidget(self.execute_btn)
        
        return toolbar
        
    def initialize_parameters(self):
        """Initialise tous les paramètres une seule fois selon l'architecture QGIS"""
        if self._parameters_initialized:
            return
            
        
        # Construire les paramètres attributaires
        AttributeParameterBuilder.build_parameters(
            self.param_manager, 
            self.update_field_combos
        )
        
        # Construire les paramètres spatiaux
        SpatialParameterBuilder.build_parameters(self.param_manager)
        
        self._parameters_initialized = True
        
        # Forcer la mise à jour de la visibilité initiale
        self.update_parameter_visibility()
            
        if hasattr(self, 'execute_btn'):
            self.execute_btn.clicked.connect(self.execute_join)
            
    def setup_layer_monitoring(self):
        """Configure la surveillance des changements de couches"""
        project = QgsProject.instance()
        project.layersAdded.connect(self.on_layers_added)
        project.layersRemoved.connect(self.on_layers_removed)
        
    def on_join_type_changed(self):
        """Gestionnaire professionnel du changement de type de jointure"""
        join_type_text = self.join_type_combo.currentText()
        
        # Mettre à jour la configuration
        for jt in JoinType:
            if jt.value == join_type_text:
                self.current_config.join_type = jt
                break
                
        
        # Mettre à jour l'affichage des paramètres avec délai pour s'assurer que l'UI est prête
        QTimer.singleShot(50, self.update_parameter_visibility)
        
        # Émettre le signal de changement
        self.configuration_changed.emit(self.current_config)
        
    def update_parameter_visibility(self):
        """Met à jour la visibilité des paramètres selon le type de jointure"""
        join_type = self.current_config.join_type
        is_attribute = join_type == JoinType.ATTRIBUTE_JOIN
        is_spatial = not is_attribute
        
        # Types spécifiques
        is_nearest = join_type == JoinType.SPATIAL_NEAREST
        is_buffer = join_type == JoinType.SPATIAL_BUFFER
        
        # Paramètres attributaires
        for key in ["source_field", "target_field", "keep_unmatched", 
                   "add_prefix", "field_prefix", "add_suffix", "field_suffix", "geometry_option"]:
            self.param_manager.set_visible(key, is_attribute)
            
        # Paramètres spatiaux communs
        for key in ["spatial_relation", "max_matches", "match_strategy",
                   "spatial_keep_unmatched", "spatial_add_prefix", "spatial_field_prefix"]:
            self.param_manager.set_visible(key, is_spatial)
        
        # Paramètres spécifiques Nearest (distance-based)
        self.param_manager.set_visible("max_distance", is_nearest)
        self.param_manager.set_visible("distance_unit", is_nearest)
        self.param_manager.set_visible("include_distance", is_nearest)
        self.param_manager.set_visible("include_index", is_nearest)
        
        # Paramètre spécifique Buffer
        self.param_manager.set_visible("buffer_distance", is_buffer)
            

    def update_result_name_suggestion(self):
        """Met à jour la suggestion de nom pour la couche résultante"""
        if not hasattr(self, 'result_name_edit') or not self.result_name_edit:
            return
            
        # Ne pas écraser si l'utilisateur a déjà tapé quelque chose
        if self.result_name_edit.text().strip() and not self.result_name_edit.text().startswith(("joined_", "spatial_")):
            return
            
        source_layer = self.source_layer_combo.currentLayer() if self.source_layer_combo else None
        target_layer = self.target_layer_combo.currentLayer() if self.target_layer_combo else None
        join_type = self.join_type_combo.currentText() if self.join_type_combo else "Attribute Join"
        
        if not source_layer or not target_layer:
            self.result_name_edit.setText("")
            return
            
        # Générer un nom intelligent selon le type de jointure
        if join_type == "Attribute Join":
            suggested_name = f"{source_layer.name()}_joined_{target_layer.name()}"
        else:
            suggested_name = f"{source_layer.name()}_spatial_{target_layer.name()}"
            
        # Limiter la longueur et nettoyer
        suggested_name = suggested_name.replace(" ", "_")[:50]
        self.result_name_edit.setText(suggested_name)
        
    def get_result_layer_name(self, source_layer, target_layer, config):
        """Récupère le nom de la couche résultante (personnalisé ou par défaut)"""
        if hasattr(self, 'result_name_edit') and self.result_name_edit.text().strip():
            custom_name = self.result_name_edit.text().strip()
            return custom_name
        else:
            # Nom par défaut selon le type de jointure
            if config.join_type == JoinType.ATTRIBUTE_JOIN:
                if config.geometry_option == "target":
                    default_name = f"{target_layer.name()}_joined_with_{source_layer.name()}"
                else:
                    default_name = f"{source_layer.name()}_joined_with_{target_layer.name()}"
            else:
                default_name = f"{source_layer.name()}_spatial_join_{target_layer.name()}"
            
            return default_name
            
    def on_source_layer_changed(self, layer: QgsVectorLayer):
        """Gestionnaire du changement de couche source"""
        if layer:
            self.current_config.source_layer_id = layer.id()
            self.update_field_combos()
            
    def on_target_layer_changed(self, layer: QgsVectorLayer):
        """Gestionnaire de changement de couche cible"""
        if layer:
            self.current_config.target_layer_id = layer.id()
            self.update_field_combos()
            
    def update_field_combos(self):
        """Met à jour les combos de champs selon les standards QGIS"""
        # Mise à jour des combos de champs pour jointures attributaires
        source_combo = self.param_manager.get_widget("source_field")
        target_combo = self.param_manager.get_widget("target_field")
        
        if isinstance(source_combo, QgsFieldComboBox) and self.source_layer_combo.currentLayer():
            source_combo.setLayer(self.source_layer_combo.currentLayer())
            
        if isinstance(target_combo, QgsFieldComboBox) and self.target_layer_combo.currentLayer():
            target_combo.setLayer(self.target_layer_combo.currentLayer())
            
    def on_layers_added(self, layers: List[QgsVectorLayer]):
        """Gestionnaire d'ajout de couches - refresh combos si nécessaire"""
        if layers:
            log_debug(f"Layers added to project: {len(layers)}")
        
    def on_layers_removed(self, layer_ids: List[str]):
        """Gestionnaire de suppression de couches - reset config si nécessaire"""
        for layer_id in layer_ids:
            if layer_id == self.current_config.source_layer_id:
                log_warning("ETL JOIN: Source layer removed - resetting configuration")
                self.current_config.source_layer_id = ""
            elif layer_id == self.current_config.target_layer_id:
                log_warning("ETL JOIN: Target layer removed - resetting configuration")
                self.current_config.target_layer_id = ""
                
    def get_current_configuration(self) -> JoinConfiguration:
        """Retourne la configuration actuelle complète"""
        # Mettre à jour la configuration avec les valeurs des widgets
        config = self.current_config
        
        # Récupérer les couches sélectionnées depuis les widgets
        if self.source_layer_combo and self.source_layer_combo.currentLayer():
            config.source_layer_id = self.source_layer_combo.currentLayer().id()
            log_debug(f"ETL JOIN CONFIG: Source layer ID updated to {config.source_layer_id}")
        else:
            log_debug("ETL JOIN CONFIG: No source layer selected in combo")
            
        if self.target_layer_combo and self.target_layer_combo.currentLayer():
            config.target_layer_id = self.target_layer_combo.currentLayer().id()
            log_debug(f"ETL JOIN CONFIG: Target layer ID updated to {config.target_layer_id}")
        else:
            log_debug("ETL JOIN CONFIG: No target layer selected in combo")
        
        # Paramètres attributaires
        if self.current_config.join_type == JoinType.ATTRIBUTE_JOIN:
            source_field_combo = self.param_manager.get_widget("source_field")
            target_field_combo = self.param_manager.get_widget("target_field")
            geometry_combo = self.param_manager.get_widget("geometry_option")
            
            if isinstance(source_field_combo, QgsFieldComboBox):
                config.source_field = source_field_combo.currentField()
            if isinstance(target_field_combo, QgsFieldComboBox):
                config.target_field = target_field_combo.currentField()
                
            # Récupérer l'option de géométrie
            if isinstance(geometry_combo, QComboBox):
                geometry_text = geometry_combo.currentText()
                if "source" in geometry_text.lower():
                    config.geometry_option = "source"
                elif "target" in geometry_text.lower():
                    config.geometry_option = "target"
                else:
                    config.geometry_option = "none"
                
        # Paramètres spatiaux
        else:
            relation_combo = self.param_manager.get_widget("spatial_relation")
            if isinstance(relation_combo, QComboBox):
                for rel in SpatialRelation:
                    if rel.value == relation_combo.currentText():
                        config.spatial_relation = rel
                        break
                        
            distance_spin = self.param_manager.get_widget("max_distance")
            if isinstance(distance_spin, QDoubleSpinBox):
                config.max_distance = distance_spin.value()
                
        return config
        
    def execute_join(self):
        """Execute la jointure avec la configuration actuelle"""
        log_info("ETL JOIN: Starting join execution process...")
        
        config = self.get_current_configuration()
        
        if not config.is_valid():
            log_error("ETL JOIN: Cannot execute - invalid configuration")
            return
            
        log_info(f"ETL JOIN: Configuration validated - executing {config.join_type.value}")
        
        # Exécuter la jointure directement
        self._perform_join_operation(config)
        
        # Émettre le signal pour information
        self.join_executed.emit(
            config.source_layer_id,
            config.target_layer_id,
            self._config_to_dict(config)
        )
        
        log_info("ETL JOIN: Execution process completed")
        
    def _config_to_dict(self, config: JoinConfiguration) -> Dict[str, Any]:
        """Convertit la configuration en dictionnaire"""
        return {
            "join_type": config.join_type.value,
            "source_field": config.source_field,
            "target_field": config.target_field,
            "spatial_relation": config.spatial_relation.value if config.spatial_relation else None,
            "max_distance": config.max_distance,
            "distance_unit": config.distance_unit,
            "buffer_distance": config.buffer_distance,
            "max_matches": config.max_matches,
            "keep_unmatched": config.keep_unmatched,
            "add_prefix": config.add_prefix,
            "field_prefix": config.field_prefix,
            "add_suffix": config.add_suffix,
            "field_suffix": config.field_suffix,
            "include_distance_field": config.include_distance_field,
            "include_match_index": config.include_match_index,
            "match_strategy": config.match_strategy,
            "geometry_option": config.geometry_option,
        }
    
    def _perform_join_operation(self, config: JoinConfiguration):
        """Implémente la logique de jointure réelle"""
        try:
            # Afficher la barre de progression
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setVisible(True)
                self.progress_bar.setValue(0)
                
            # Désactiver le bouton d'exécution
            if hasattr(self, 'execute_btn'):
                self.execute_btn.setEnabled(False)
                self.execute_btn.setText("Executing...")
            
            # Récupérer les couches source et cible
            source_layer = QgsProject.instance().mapLayer(config.source_layer_id)
            target_layer = QgsProject.instance().mapLayer(config.target_layer_id)
            
            if not source_layer:
                log_error(f"ETL JOIN: Source layer not found in project (ID: {config.source_layer_id})")
                return
                
            if not target_layer:
                log_error(f"ETL JOIN: Target layer not found in project (ID: {config.target_layer_id})")
                return
                
            # Validation supplémentaire
            if not source_layer.isValid():
                log_error(f"ETL JOIN: Source layer is not valid - {source_layer.name()}")
                return
                
            if not target_layer.isValid():
                log_error(f"ETL JOIN: Target layer is not valid - {target_layer.name()}")
                return
            
            # Vérifier les champs pour jointures attributaires
            if config.join_type == JoinType.ATTRIBUTE_JOIN:
                source_fields = [field.name() for field in source_layer.fields()]
                target_fields = [field.name() for field in target_layer.fields()]
                
                if config.source_field not in source_fields:
                    log_error(f"ETL JOIN: Source field '{config.source_field}' not found in layer '{source_layer.name()}'. Available: {source_fields}")
                    return
                    
                if config.target_field not in target_fields:
                    log_error(f"ETL JOIN: Target field '{config.target_field}' not found in layer '{target_layer.name()}'. Available: {target_fields}")
                    return
                
            log_info(f"ETL JOIN: Starting operation - {source_layer.name()} ({source_layer.featureCount()} features) → {target_layer.name()} ({target_layer.featureCount()} features)")
            
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setValue(20)
            
            # Créer la couche résultat selon le type de jointure
            if config.join_type == JoinType.ATTRIBUTE_JOIN:
                result_layer = self._perform_attribute_join(source_layer, target_layer, config)
            else:
                result_layer = self._perform_spatial_join(source_layer, target_layer, config)
                
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setValue(90)
                
            if result_layer:
                # Ajouter la couche résultat au projet QGIS
                QgsProject.instance().addMapLayer(result_layer)
                log_success(f"ETL JOIN: SUCCESS! Result layer '{result_layer.name()}' created with {result_layer.featureCount()} features and added to project")
                
                if hasattr(self, 'progress_bar'):
                    self.progress_bar.setValue(100)
            else:
                log_error("ETL JOIN: FAILED - No result layer was created")
                
        except Exception as e:
            log_error(f"ETL JOIN: CRITICAL ERROR - {str(e)}")
            import traceback
            log_error(f"ETL JOIN: Stack trace - {traceback.format_exc()}")
        finally:
            # Restaurer l'interface
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setVisible(False)
            if hasattr(self, 'execute_btn'):
                self.execute_btn.setEnabled(True)
                self.execute_btn.setText("Execute Join")
            log_info("ETL JOIN: Interface restored - ready for next operation")
    
    def _perform_attribute_join(self, source_layer, target_layer, config):
        """Effectue une jointure attributaire avec validation robuste"""
        try:
            log_info(f"ETL JOIN: Performing attribute join on fields - {config.source_field} = {config.target_field}")
            log_info(f"ETL JOIN: Geometry option selected - {config.geometry_option}")
            
            # C03 fix: Validate CRS before processing
            if config.geometry_option != "none":
                if not _validate_crs(source_layer, "Source") or not _validate_crs(target_layer, "Target"):
                    return None
            
            # M08 fix: Check field type compatibility
            source_field_obj = source_layer.fields().field(config.source_field)
            target_field_obj = target_layer.fields().field(config.target_field)
            if source_field_obj.type() != target_field_obj.type():
                log_warning(f"ETL JOIN: Field type mismatch - {config.source_field}({source_field_obj.typeName()}) vs {config.target_field}({target_field_obj.typeName()}) - May cause reduced matches")
            
            # Determine base layer for geometry
            if config.geometry_option == "target":
                base_layer = target_layer
                join_layer = source_layer
                base_field = config.target_field
                join_field = config.source_field
            elif config.geometry_option == "source":
                base_layer = source_layer
                join_layer = target_layer
                base_field = config.source_field
                join_field = config.target_field
            else:  # "none" - no geometry
                return self._perform_table_join(source_layer, target_layer, config)
            
            result_name = self.get_result_layer_name(source_layer, target_layer, config)
            
            # Build result fields
            result_fields = QgsFields()
            for field in base_layer.fields():
                result_fields.append(QgsField(field.name(), field.type()))
            
            prefix = config.field_prefix if config.add_prefix and config.field_prefix else "joined_"
            for field in join_layer.fields():
                if field.name() != join_field:
                    field_name = f"{prefix}{field.name()}"
                    result_fields.append(QgsField(field_name, field.type()))
            
            # C03 fix: Safe CRS string
            geom_type = base_layer.wkbType()
            crs_str = _get_crs_string(base_layer)
            result_layer = QgsVectorLayer(f"{QgsWkbTypes.displayString(geom_type)}?crs={crs_str}", result_name, "memory")
            
            if not result_layer.isValid():
                log_error(f"ETL JOIN: Failed to create result layer with CRS {crs_str}")
                return None
            
            result_provider = result_layer.dataProvider()
            result_provider.addAttributes(result_fields)
            result_layer.updateFields()
            
            # M03 fix: Use centralized index builder
            join_index = _build_join_index(join_layer, join_field)
            
            # Perform join
            result_features = []
            matched_count = 0
            skipped_null_geom = 0
            
            for base_feature in base_layer.getFeatures():
                base_geom = base_feature.geometry()
                
                # C01 fix: Track NULL geometries
                if not base_geom or base_geom.isEmpty():
                    skipped_null_geom += 1
                    if config.keep_unmatched:
                        # Still keep feature with NULL geometry if requested
                        result_feature = QgsFeature(result_fields)
                        _copy_base_attributes(result_feature, base_feature, base_layer.fields())
                        result_features.append(result_feature)
                    continue
                
                base_value = base_feature.attribute(base_field)
                join_features = join_index.get(base_value, [])
                
                if join_features:
                    for join_feature in join_features:
                        result_feature = QgsFeature(result_fields)
                        result_feature.setGeometry(base_geom)
                        
                        # M04 fix: Use centralized attribute copy
                        _copy_base_attributes(result_feature, base_feature, base_layer.fields())
                        _copy_joined_attributes(result_feature, join_feature, join_layer.fields(), prefix, join_field)
                        
                        result_features.append(result_feature)
                        matched_count += 1
                        
                elif config.keep_unmatched:
                    result_feature = QgsFeature(result_fields)
                    result_feature.setGeometry(base_geom)
                    _copy_base_attributes(result_feature, base_feature, base_layer.fields())
                    result_features.append(result_feature)
            
            result_provider.addFeatures(result_features)
            
            # C01 fix: Report skipped features
            if skipped_null_geom > 0:
                log_warning(f"ETL JOIN: {skipped_null_geom} features skipped (NULL/empty geometry)")
            
            log_info(f"ETL JOIN: Attribute join completed - {matched_count} matches, {len(result_features)} total features")
            log_success(f"ETL JOIN: Attribute join successful - {result_layer.featureCount()} features with {config.geometry_option} geometry")
            return result_layer
                
        except Exception as e:
            log_error(f"ETL JOIN: Attribute join error - {str(e)}")
            import traceback
            log_error(f"ETL JOIN: Attribute join traceback - {traceback.format_exc()}")
            return None
    
    def _perform_table_join(self, source_layer, target_layer, config):
        """Effectue une jointure attributaire sans géométrie (résultat tabulaire)"""
        try:
            log_info("ETL JOIN: Performing table join (no geometry)")
            
            # Utiliser le nom personnalisé
            result_name = self.get_result_layer_name(source_layer, target_layer, config)
            
            # Créer les champs pour la table résultat
            result_fields = QgsFields()
            
            # Ajouter les champs de la couche source
            for field in source_layer.fields():
                field_name = f"src_{field.name()}"
                result_fields.append(QgsField(field_name, field.type()))
            
            # Ajouter les champs de la couche cible avec préfixe
            prefix = config.field_prefix if config.add_prefix else "target_"
            for field in target_layer.fields():
                if field.name() != config.target_field:  # Éviter la duplication du champ de jointure
                    field_name = f"{prefix}{field.name()}"
                    result_fields.append(QgsField(field_name, field.type()))
            
            # Créer la table mémoire résultat (sans géométrie)
            result_layer = QgsVectorLayer("None", result_name, "memory")
            
            result_provider = result_layer.dataProvider()
            result_provider.addAttributes(result_fields)
            result_layer.updateFields()
            
            # Créer un index des features cibles pour la jointure
            target_index = {}
            for feature in target_layer.getFeatures():
                join_value = feature.attribute(config.target_field)
                if join_value is not None:
                    if join_value not in target_index:
                        target_index[join_value] = []
                    target_index[join_value].append(feature)
            
            # Traiter chaque feature source
            matched_count = 0
            
            for source_feature in source_layer.getFeatures():
                source_join_value = source_feature.attribute(config.source_field)
                
                if source_join_value in target_index:
                    # Correspondance trouvée
                    for target_feature in target_index[source_join_value]:
                        result_feature = QgsFeature(result_fields)
                        
                        # Copier les attributs source
                        field_idx = 0
                        for field in source_layer.fields():
                            result_feature.setAttribute(field_idx, source_feature.attribute(field.name()))
                            field_idx += 1
                        
                        # Copier les attributs cible (sauf le champ de jointure)
                        for field in target_layer.fields():
                            if field.name() != config.target_field:
                                result_feature.setAttribute(field_idx, target_feature.attribute(field.name()))
                                field_idx += 1
                        
                        result_provider.addFeature(result_feature)
                        matched_count += 1
                        
                elif config.keep_unmatched:
                    # Garder les features source non appariées
                    result_feature = QgsFeature(result_fields)
                    
                    field_idx = 0
                    for field in source_layer.fields():
                        result_feature.setAttribute(field_idx, source_feature.attribute(field.name()))
                        field_idx += 1
                    
                    result_provider.addFeature(result_feature)
            
            log_success(f"Table join completed: {matched_count} matches found, {result_layer.featureCount()} total records")
            return result_layer
            
        except Exception as e:
            log_error(f"Table join error: {str(e)}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def _perform_spatial_join(self, source_layer, target_layer, config):
        """Effectue une jointure spatiale avec validation robuste et optimisation"""
        try:
            log_info(f"ETL JOIN: Performing spatial join with relation - {config.spatial_relation.value}")
            
            # C03 fix: Validate CRS
            if not _validate_crs(source_layer, "Source") or not _validate_crs(target_layer, "Target"):
                return None
            
            # C02 fix: Check and handle CRS mismatch
            needs_transform, crs_transform, crs_warning = _check_crs_match(source_layer, target_layer)
            if crs_warning:
                log_warning(f"ETL JOIN: {crs_warning} - Target geometries will be reprojected")
            
            # C04 fix: Validate spatial relation compatibility
            relation_warnings = _validate_spatial_relation_compatibility(source_layer, target_layer, config.spatial_relation)
            for warning in relation_warnings:
                log_warning(f"ETL JOIN: {warning}")
            
            log_info(f"ETL JOIN: Building spatial index for {target_layer.featureCount()} target features...")
            
            result_name = self.get_result_layer_name(source_layer, target_layer, config)
            
            # Build result fields
            result_fields = QgsFields()
            
            for field in source_layer.fields():
                field_name = field.name()
                if config.add_prefix and hasattr(config, 'field_prefix'):
                    field_name = f"src_{field_name}"
                result_fields.append(QgsField(field_name, field.type()))
            
            prefix = getattr(config, 'spatial_field_prefix', 'target_')
            for field in target_layer.fields():
                field_name = f"{prefix}{field.name()}"
                result_fields.append(QgsField(field_name, field.type()))
            
            # C03 fix: Safe CRS string
            geom_type = source_layer.wkbType()
            crs_str = _get_crs_string(source_layer)
            result_layer = QgsVectorLayer(f"{QgsWkbTypes.displayString(geom_type)}?crs={crs_str}", 
                                        result_name, "memory")
            
            if not result_layer.isValid():
                log_error(f"ETL JOIN: Failed to create result layer with CRS {crs_str}")
                return None
            
            result_provider = result_layer.dataProvider()
            result_provider.addAttributes(result_fields)
            result_layer.updateFields()
            
            # Build spatial index
            spatial_index = QgsSpatialIndex(target_layer.getFeatures())
            
            # Pre-cache target features for M02 optimization (batch retrieval)
            target_features_cache = {f.id(): f for f in target_layer.getFeatures()}
            
            # Process source features
            matched_count = 0
            skipped_null_source = 0
            skipped_null_target = 0
            total_features = source_layer.featureCount()
            result_features = []  # Batch add for performance
            
            for i, source_feature in enumerate(source_layer.getFeatures()):
                source_geom = source_feature.geometry()
                
                # C01 fix: Track NULL source geometries
                if not source_geom or source_geom.isEmpty():
                    skipped_null_source += 1
                    continue
                
                intersecting_ids = spatial_index.intersects(source_geom.boundingBox())
                
                matches_found = False
                match_count = 0
                
                for target_id in intersecting_ids:
                    if match_count >= config.max_matches:
                        break
                    
                    # M02 fix: Use cached features instead of getFeature()
                    target_feature = target_features_cache.get(target_id)
                    if not target_feature:
                        continue
                        
                    target_geom = target_feature.geometry()
                    
                    # C01 fix: Track NULL target geometries
                    if not target_geom or target_geom.isEmpty():
                        skipped_null_target += 1
                        continue
                    
                    # C02 fix: Apply CRS transformation if needed
                    if needs_transform and crs_transform:
                        target_geom = QgsGeometry(target_geom)
                        target_geom.transform(crs_transform)
                    
                    # Check spatial relation
                    relation_ok = self._check_spatial_relation(source_geom, target_geom, config.spatial_relation)
                    
                    if relation_ok:
                        result_feature = QgsFeature(result_fields)
                        result_feature.setGeometry(source_geom)
                        
                        # Copy source attributes
                        field_idx = 0
                        for field in source_layer.fields():
                            result_feature.setAttribute(field_idx, source_feature.attribute(field.name()))
                            field_idx += 1
                        
                        # Copy target attributes with prefix
                        for field in target_layer.fields():
                            result_feature.setAttribute(field_idx, target_feature.attribute(field.name()))
                            field_idx += 1
                        
                        result_features.append(result_feature)
                        matches_found = True
                        match_count += 1
                        matched_count += 1
                
                # Keep unmatched features if requested
                if not matches_found and getattr(config, 'spatial_keep_unmatched', True):
                    result_feature = QgsFeature(result_fields)
                    result_feature.setGeometry(source_geom)
                    
                    field_idx = 0
                    for field in source_layer.fields():
                        result_feature.setAttribute(field_idx, source_feature.attribute(field.name()))
                        field_idx += 1
                    
                    result_features.append(result_feature)
                
                # Progress update every 500 features
                if i % 500 == 0 and i > 0:
                    log_info(f"ETL JOIN: Progress {i}/{total_features} features processed...")
            
            # Batch add all features at once for performance
            result_provider.addFeatures(result_features)
            result_layer.updateExtents()
            
            # C01 fix: Report skipped features
            if skipped_null_source > 0:
                log_warning(f"ETL JOIN: {skipped_null_source} source features skipped (NULL/empty geometry)")
            if skipped_null_target > 0:
                log_warning(f"ETL JOIN: {skipped_null_target} target geometry checks skipped (NULL/empty)")
            
            log_success(f"ETL JOIN: Spatial join completed - {matched_count} matches, {result_layer.featureCount()} total features")
            
            return result_layer
            
        except Exception as e:
            log_error(f"ETL JOIN: Spatial join error - {str(e)}")
            import traceback
            log_error(f"ETL JOIN: Traceback - {traceback.format_exc()}")
            return None
    
    def _check_spatial_relation(self, source_geom, target_geom, relation) -> bool:
        """Check spatial relation between two geometries - centralized logic"""
        if relation == SpatialRelation.INTERSECTS:
            return source_geom.intersects(target_geom)
        elif relation == SpatialRelation.CONTAINS:
            return source_geom.contains(target_geom)
        elif relation == SpatialRelation.WITHIN:
            return source_geom.within(target_geom)
        elif relation == SpatialRelation.TOUCHES:
            return source_geom.touches(target_geom)
        elif relation == SpatialRelation.CROSSES:
            return source_geom.crosses(target_geom)
        elif relation == SpatialRelation.OVERLAPS:
            return source_geom.overlaps(target_geom)
        elif relation == SpatialRelation.DISJOINT:
            return source_geom.disjoint(target_geom)
        elif relation == SpatialRelation.EQUALS:
            return source_geom.equals(target_geom)
        else:
            # Default to intersects
            return source_geom.intersects(target_geom)

    # =====================================
    # LEGACY COMPATIBILITY LAYER
    # =====================================
    
    @property 
    def params_layout(self):
        """Compatibility: Access to parameter layout"""
        return self.param_manager.layout
        
    def get_selected_layer(self, combo):
        """Compatibility: Get layer from combo"""
        if hasattr(combo, 'currentLayer'):
            return combo.currentLayer()
        return None
        
    def clear_params_layout(self):
        """Legacy compatibility method for clearing parameters"""
        self.param_manager.clear_all()
        
    def update_layer_field_combos(self):
        """Legacy compatibility method"""
        self.update_field_combos()
        
    def update_configuration_preview(self):
        """Legacy compatibility - emit configuration changed signal"""
        self.configuration_changed.emit(self.current_config)
        
    # =====================================  
    # LEGACY METHOD STUBS FOR COMPATIBILITY
    # =====================================
    
    def validate_configuration(self):
        """Legacy compatibility - validate current configuration"""
        config = self.get_current_configuration()
        return config.is_valid()
        
    def preview_join(self):
        """Legacy compatibility - preview join operation"""
        if self.validate_configuration():
            log_info("Join preview would be generated here")
        
    def update_stats_label(self):
        """Legacy compatibility - update statistics"""
        # Intentionally empty - legacy compatibility stub
    
    # Note: on_layers_added and on_layers_removed are defined earlier in the class
        
    def on_layer_will_be_removed(self, layer_id):
        """Legacy compatibility - handle layer about to be removed"""
        if layer_id == self.current_config.source_layer_id:
            self.current_config.source_layer_id = ""
        elif layer_id == self.current_config.target_layer_id:
            self.current_config.target_layer_id = ""
    
    # Preview table management methods
    def show_column(self, column_index):
        """Show a previously hidden column"""
        if hasattr(self, 'preview_table') and self.preview_table:
            self.preview_table.showColumn(column_index)
            if hasattr(self, 'excluded_columns'):
                self.excluded_columns.discard(column_index)
        
    def hide_column(self, column_index):
        """Hide a column from the preview table"""
        if hasattr(self, 'preview_table') and self.preview_table:
            self.preview_table.hideColumn(column_index)
            if hasattr(self, 'excluded_columns'):
                self.excluded_columns.add(column_index)
                
    def show_all_columns(self):
        """Show all hidden columns"""
        if hasattr(self, 'preview_table') and self.preview_table:
            for column in range(self.preview_table.columnCount()):
                self.preview_table.showColumn(column)
            if hasattr(self, 'excluded_columns'):
                self.excluded_columns.clear()
        
    def reset_preview_table(self):
        """Reset the preview table to its original state"""
        self.show_all_columns()
        self.update_preview_table()
        log_info("Preview table reset to original state")
        
    def update_preview_status(self):
        """Update the preview status with column information"""
        if not hasattr(self, 'preview_table') or not self.preview_table:
            return
            
        total_columns = self.preview_table.columnCount()
        hidden_columns = len(getattr(self, 'excluded_columns', set()))
        visible_columns = total_columns - hidden_columns
        
        if hidden_columns > 0:
            status_text = f"Preview: {visible_columns}/{total_columns} columns visible ({hidden_columns} hidden)"
        else:
            rows = self.preview_table.rowCount()
            status_text = f"Preview: {rows} features, {total_columns} columns"
            
        if hasattr(self, 'preview_status') and self.preview_status:
            self.preview_status.setText(status_text)
            
    def update_field_mapping_preview(self):
        """Met à jour la table de mapping des champs"""
        log_debug("update_field_mapping_preview called")
        
        if not hasattr(self, 'field_mapping_table') or not self.field_mapping_table:
            log_debug("No field_mapping_table found")
            return
            
        source_layer = self.source_layer_combo.currentLayer() if self.source_layer_combo else None
        target_layer = self.target_layer_combo.currentLayer() if self.target_layer_combo else None
        
        log_debug(f"Source layer: {source_layer.name() if source_layer else 'None'}")
        log_debug(f"Target layer: {target_layer.name() if target_layer else 'None'}")
        
        if not source_layer or not target_layer:
            self.clear_field_mapping_table()
            if hasattr(self, 'preview_status'):
                self.preview_status.setText("Select both source and target layers to see field mapping")
            return
            
        # Mettre à jour le mapping des champs
        log_debug("Calling populate_field_mapping_table")
        self.populate_field_mapping_table(source_layer, target_layer)
        
    def clear_field_mapping_table(self):
        """Vide la table de mapping des champs"""
        if hasattr(self, 'field_mapping_table') and self.field_mapping_table:
            self.field_mapping_table.setRowCount(0)
            
    def populate_field_mapping_table(self, source_layer, target_layer):
        """Remplit la table de mapping des champs"""
        log_debug("populate_field_mapping_table called")
        
        if not hasattr(self, 'field_mapping_table') or not self.field_mapping_table:
            log_debug("field_mapping_table not available")
            return
            
        try:
            # Récupérer les champs des couches
            source_fields = source_layer.fields()
            target_fields = target_layer.fields()
            
            log_debug(f"Source fields count: {len(source_fields)}")
            log_debug(f"Target fields count: {len(target_fields)}")
            
            # Configuration du tableau - montrer clairement le résultat final
            all_fields = []
            
            # Récupérer la configuration actuelle
            config = self.get_current_configuration()
            join_type = self.join_type_combo.currentText() if self.join_type_combo else "Attribute Join"
            
            if join_type == "Attribute Join":
                # Logique pour jointure attributaire
                if config.geometry_option == "source":
                    base_layer = source_layer
                    join_layer = target_layer  
                    base_name = source_layer.name()
                    join_name = target_layer.name()
                elif config.geometry_option == "target":
                    base_layer = target_layer
                    join_layer = source_layer
                    base_name = target_layer.name() 
                    join_name = source_layer.name()
                else:  # no geometry
                    base_layer = source_layer
                    join_layer = target_layer
                    base_name = source_layer.name()
                    join_name = target_layer.name()
                
                # Ajouter les champs de base (gardés tels quels)
                for field in base_layer.fields():
                    field_type = self.get_field_type_display(field)
                    status = "✓ Kept" if field.name() != config.source_field and field.name() != config.target_field else "✓ Join Key"
                    all_fields.append((field.name(), field_type, f"{base_name} (Base)", status, field.name()))
                
                # Ajouter les champs joints (avec préfixe)
                prefix = config.field_prefix if config.add_prefix and config.field_prefix else "joined_"
                for field in join_layer.fields():
                    if field.name() != config.source_field and field.name() != config.target_field:
                        field_type = self.get_field_type_display(field)
                        result_name = f"{prefix}{field.name()}"
                        all_fields.append((field.name(), field_type, f"{join_name} (Joined)", "✓ Added", result_name))
            else:
                # Logique pour jointure spatiale  
                for field in source_fields:
                    field_type = self.get_field_type_display(field)
                    all_fields.append((field.name(), field_type, f"{source_layer.name()} (Source)", "✓ Kept", field.name()))
                
                prefix = "spatial_" if config.add_prefix else ""
                for field in target_fields:
                    field_type = self.get_field_type_display(field)
                    result_name = f"{prefix}{field.name()}"
                    all_fields.append((field.name(), field_type, f"{target_layer.name()} (Target)", "✓ Added", result_name))
            
            log_debug(f"Total fields to display: {len(all_fields)}")
            
            # Remplir le tableau avec 5 colonnes
            self.field_mapping_table.setRowCount(len(all_fields))
            log_debug(f"Table row count set to: {len(all_fields)}")
            
            for row, (field_name, field_type, from_layer, status, result_name) in enumerate(all_fields):
                self.field_mapping_table.setItem(row, 0, QTableWidgetItem(field_name))
                self.field_mapping_table.setItem(row, 1, QTableWidgetItem(field_type))
                self.field_mapping_table.setItem(row, 2, QTableWidgetItem(from_layer))
                self.field_mapping_table.setItem(row, 3, QTableWidgetItem(status))
                self.field_mapping_table.setItem(row, 4, QTableWidgetItem(result_name))
                
            log_debug("Table items set successfully")
            
            # Redimensionner les colonnes
            self.field_mapping_table.resizeColumnsToContents()
            log_debug("Columns resized")
            
            # Mettre à jour le statut avec plus de détails
            join_type = self.join_type_combo.currentText() if self.join_type_combo else ""
            total_fields = len(all_fields)
            source_count = len(source_fields)
            target_count = len(target_fields)
            
            # Compter les champs gardés vs ajoutés
            kept_count = len([f for f in all_fields if "Kept" in f[3] or "Join Key" in f[3]])
            added_count = len([f for f in all_fields if "Added" in f[3]])
            
            if hasattr(self, 'preview_status'):
                status = f"Preview: {kept_count} fields kept + {added_count} fields added = {total_fields} total | Join: {join_type} | Result Geometry: {config.geometry_option}"
                self.preview_status.setText(status)
                log_debug(f"Status updated: {status}")
                
        except Exception as e:
            log_error(f"Error in populate_field_mapping_table: {str(e)}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")
        
    def get_field_type_display(self, field):
        """Retourne un nom lisible pour le type de champ"""
        type_map = {
            'QString': 'Text',
            'QVariant::String': 'Text',
            'Integer': 'Integer',
            'QVariant::Int': 'Integer', 
            'Double': 'Double',
            'QVariant::Double': 'Double',
            'Date': 'Date',
            'QVariant::Date': 'Date',
            'DateTime': 'DateTime',
            'QVariant::DateTime': 'DateTime'
        }
        
        type_name = field.typeName()
        return type_map.get(type_name, type_name)
            
    def show_context_menu(self, position):
        """Affiche le menu contextuel pour la table de mapping"""
        if not hasattr(self, 'field_mapping_table') or not self.field_mapping_table:
            return
            
        # Vérifier si on a cliqué sur un en-tête de colonne
        item = self.field_mapping_table.itemAt(position)
        if item is None:
            return
            
        column = item.column()
        
        # Créer le menu contextuel
        context_menu = QMenu(self)
        
        # Actions pour gérer les colonnes
        hide_action = QAction(f"Hide column '{self.field_mapping_table.horizontalHeaderItem(column).text()}'", self)
        hide_action.triggered.connect(lambda: self.hide_column(column))
        context_menu.addAction(hide_action)
        
        context_menu.addSeparator()
        
        # Action pour afficher toutes les colonnes
        show_all_action = QAction("Show all columns", self)
        show_all_action.triggered.connect(self.show_all_columns)
        context_menu.addAction(show_all_action)
        
        # Action pour réinitialiser la table
        reset_action = QAction("Reset mapping table", self)
        reset_action.triggered.connect(self.reset_field_mapping_table)
        context_menu.addAction(reset_action)
        
        # Afficher le menu
        context_menu.exec_(self.field_mapping_table.mapToGlobal(position))
        
    def reset_field_mapping_table(self):
        """Reset la table de mapping des champs"""
        self.show_all_columns()
        self.update_field_mapping_preview()
        log_info("Field mapping table reset to original state")
