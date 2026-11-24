# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Parcours natif de préparation, état de recette et contrôle avant/après."""
import copy
import hashlib
import json
import re
import weakref
from datetime import datetime, timezone
from pathlib import Path

try:
    from qgis.PyQt import sip as _sip
except ImportError:
    _sip = None

from qgis.PyQt.QtCore import QSignalBlocker, QSize, QTimer, QPointF, QRectF
from qgis.PyQt.QtGui import QKeySequence, QPainter, QPen, QPolygonF, QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QToolButton, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem,
    QSplitter, QDockWidget, QPlainTextEdit, QMenu, QMessageBox,
    QFileDialog, QInputDialog, QComboBox, QCheckBox, QStackedWidget,
    QDoubleSpinBox, QFrame, QScrollArea,
)
from qgis.core import (
    Qgis, QgsApplication, QgsProject, QgsVectorLayer, QgsFeatureRequest, QgsExpression,
    QgsExpressionContext, QgsExpressionContextUtils, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsGeometry,
)
from ..shared.compat import (
    AccessibleDescriptionRole,
    AlignHCenter,
    AlignLeft,
    AllDockAreas,
    Antialias,
    BottomDockArea,
    CustomContextMenu,
    DialogAccepted,
    DockAllowNestedDocks,
    DockAllowTabbedDocks,
    DockClosable,
    DockFloatable,
    DockMovable,
    EventToolTip,
    ExtendedSelection,
    FormAllNonFixedFieldsGrow,
    FrameNoFrame,
    HeaderInteractive,
    HeaderResizeToContents,
    HeaderStretch,
    Horizontal,
    InstantPopup,
    LayerTypeVector,
    LeftDockArea,
    MsgBoxCancel,
    MsgBoxDiscard,
    MsgBoxNo,
    MsgBoxSave,
    MsgBoxYes,
    MsgWarning,
    NoEditTriggers,
    PaletteHighlight,
    PaletteText,
    QAction,
    RightDockArea,
    ToolButtonTextBesideIcon,
    ToolTipRole,
    UserRole,
    Vertical,
    fixed_system_font,
    wkb_type_name,
)
from ..shared.icons import icon as ui_icon
from ..shared.interface_config import InterfaceTheme
from ..widgets.field_widget import FieldWidget
from ..widgets.smart_filter_widget import SmartFilterWidget
from ..widgets.advanced_expression_widget import AdvancedExpressionWidget
from ..widgets.fluent import (
    FluentButton as QPushButton, FluentTabWidget as QTabWidget,
    StableStatus, apply_fluent_style,
)
from ..widgets.quick_rules import QuickRules
from .intentions_panel import IntentionsPanel


class GeometryFlowPreview(QWidget):
    """Schéma sémantique de la règle ; aucune prétention de rendu des données."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_kind = 'Polygon'
        self.expression = '$geometry'
        self.setMinimumHeight(150)
        self.setMaximumHeight(180)

    def set_operation(self, source_kind, expression):
        self.source_kind = source_kind or 'Polygon'
        self.expression = expression or '$geometry'
        self.setAccessibleName('Schéma de géométrie : '+self.operation_label()+'. La forme réelle reste à vérifier dans le contrôle.')
        self.update()

    def operation_label(self):
        text = self.expression.lower()
        if 'centroid(' in text:
            return 'Calculer le centroïde'
        if 'buffer(' in text:
            return 'Créer une zone tampon'
        if 'simplify(' in text:
            return 'Simplifier la géométrie'
        return 'Conserver la géométrie' if text == '$geometry' else 'Évaluer la règle géométrique'

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(Antialias)
        palette = self.palette()
        ink = palette.color(PaletteText)
        accent = palette.color(PaletteHighlight)
        fill = QColor(accent)
        fill.setAlpha(35)
        left = QPointF(self.width() * .18, 70)
        right = QPointF(self.width() * .82, 70)
        def shape(center, kind):
            painter.setPen(QPen(accent, 2))
            painter.setBrush(fill)
            if 'point' in kind.lower():
                painter.setBrush(accent)
                painter.drawEllipse(center, 6, 6)
            elif any(token in kind.lower() for token in ('line', 'curve')):
                painter.drawPolyline(QPolygonF([center+QPointF(-28,16),center+QPointF(-9,-18),center+QPointF(9,8),center+QPointF(28,-10)]))
            else:
                painter.drawPolygon(QPolygonF([center+QPointF(-28,-17),center+QPointF(16,-26),center+QPointF(30,19),center+QPointF(-21,27)]))
        target = 'Point' if 'centroid(' in self.expression.lower() else ('Polygon' if 'buffer(' in self.expression.lower() else self.source_kind)
        shape(left, self.source_kind)
        shape(right, target)
        painter.setPen(QPen(ink, 1.5))
        start = QPointF(self.width()*.33,70)
        end = QPointF(self.width()*.67,70)
        painter.drawLine(start,end)
        painter.drawLine(end,end+QPointF(-8,-5))
        painter.drawLine(end,end+QPointF(-8,5))
        painter.setPen(ink)
        painter.drawText(QRectF(0,9,self.width(),24),AlignHCenter,self.operation_label())
        painter.drawText(QRectF(0,108,self.width()*.36,24),AlignHCenter,'Entrée')
        painter.drawText(QRectF(self.width()*.64,108,self.width()*.36,24),AlignHCenter,'Résultat prévu')


class RecipeWorkspaceMixin:
    """Isoler la représentation de recette des services et outils historiques."""

    def __init__(self, *args, **kwargs):
        self._loading_recipe = True
        self._editing_source_id = None
        self._loaded_recipe_name = None
        self._saved_state = None
        self._force_dirty = False
        self._raw_target_crs = None
        self._destination_error = False
        self._expected_source_schema = []
        self._selection_guard = False
        self._writing_json = False
        self._json_pending = False
        self._recipe_destination = {}
        self._last_control = None
        self._run_history = []
        self._pending_delivery = None
        self._current_execution_plan = []
        self._last_selection = None
        self._source_signal_connections = []
        self._workspace_context_key = None
        self._workspace_views = {}
        self._view_generation = 0
        self._chosen_intentions = []
        self._guided_prepared = set()
        self._result_layers = []
        self._banner_dismissed_sources = set()
        self._tooltip_filtered_widgets = weakref.WeakSet()
        self._compat_recipes_cache = None
        self._initializing_workspace = True
        super().__init__(*args, **kwargs)
        self._initializing_workspace = False
        self._loading_recipe = False
        self._layout_default()
        self.refresh_shapefile_list()
        self.main_tabs.setTabText(0, 'Préparer')
        self.main_tabs.setTabText(1, 'Livrer')
        self._install_delivery_page()
        self.status_label.setText('Prêt')
        self.mode_label.setText('Préparation')
        self._apply_workspace_preferences()
        if getattr(self, 'export_widget', None) is not None:
            self.export_widget.request_started.connect(self._on_file_export_requested)
            self.export_widget.export_finished.connect(self._on_file_export_finished)
        pg_mapping = getattr(getattr(self, 'postgresql_widget', None), 'mapping_widget', None)
        if pg_mapping is not None and hasattr(pg_mapping, 'publication_finished'):
            pg_mapping.publication_finished.connect(self._on_publication_finished)
        history_path = Path(self.config_manager.plugin_dir) / 'execution_history.json'
        if history_path.exists():
            try:
                saved = json.loads(history_path.read_text(encoding='utf-8'))
                self._run_history = saved[-100:] if isinstance(saved, list) else []
                self._render_history()
            except (OSError, ValueError, TypeError, KeyError):
                self._run_history = []
        self._show_workspace_editor()
        self._update_recipe_status()
        if self._editing_source_id is None and self.loaded_shapefiles:
            active_id = None
            try:
                from qgis.utils import iface
                active = iface.activeLayer() if iface is not None else None
                if active is not None and active.id() in self.loaded_shapefiles:
                    active_id = active.id()
            except Exception:
                active_id = None
            source_id = active_id or next(iter(self.loaded_shapefiles))
            for index in range(self.shp_tree.topLevelItemCount()):
                item = self.shp_tree.topLevelItem(index)
                if self._selected_data(item) == {'source_file': source_id, 'table_name': None}:
                    self.shp_tree.setCurrentItem(item)
                    break

    def setup_main_window(self):
        self.setWindowTitle('Transformer | Des données prêtes à utiliser')
        self.setMinimumSize(780, 560)
        self.resize(1360, 900)
        self.setDockOptions(DockAllowNestedDocks | DockAllowTabbedDocks)
        self.setDockNestingEnabled(True)
        logo = Path(__file__).resolve().parent.parent / 'logo.png'
        if logo.exists():
            from qgis.PyQt.QtGui import QIcon
            self.setWindowIcon(QIcon(str(logo)))

    def create_configuration_tab(self):
        return self.create_expression_panel()

    def setup_central_widget(self):
        super().setup_central_widget()
        original = self.main_tabs
        tabs = QTabWidget()
        tabs.setAccessibleName('Préparer et utiliser les données')
        tabs.setDocumentMode(True)
        while original.count():
            widget, icon, title = original.widget(0), original.tabIcon(0), original.tabText(0)
            original.removeTab(0)
            tabs.addTab(widget, icon, title)
        original.parentWidget().layout().replaceWidget(original, tabs)
        self.main_tabs = tabs
        original.deleteLater()

    def create_expression_panel(self):
        panel = QWidget()
        panel.setObjectName('transformer_work_surface')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        self.workspace_back = QPushButton('Assistant d’objectifs', icon_name='layers', compact=True)
        self.workspace_back.setToolTip('Ouvrir l’assistant de choix multiples d’objectifs')
        self.workspace_back.clicked.connect(self._show_intentions)
        heading.addWidget(self.workspace_back)
        self.workspace_doc_btn = QPushButton('Tutoriel && Guide', icon_name='documentation', compact=True)
        self.workspace_doc_btn.setObjectName('transformer_workspace_doc_btn')
        self.workspace_doc_btn.setToolTip('Ouvrir le guide et tutoriel illustré pas à pas dans un panneau latéral (F1)')
        self.workspace_doc_btn.clicked.connect(self.open_documentation_dock)
        heading.addWidget(self.workspace_doc_btn)
        title = QLabel('Préparer, puis voir la différence.')
        title.setProperty('fluentRole', 'section')
        self.workspace_title = title
        font = title.font()
        font.setPointSizeF(max(font.pointSizeF(), 10) * 1.35)
        font.setBold(True)
        title.setFont(font)
        heading.addWidget(title)
        heading.addStretch()
        self.recipe_status_label = QLabel('Choisir une source')
        self.recipe_status_label.setAccessibleName('État de la préparation')
        self.recipe_status_label.setProperty('fluentRole', 'detail')
        heading.addWidget(self.recipe_status_label)
        layout.addLayout(heading)

        recipe_form = QFrame()
        recipe_form.setObjectName('transformer_recipe_header_card')
        recipe_form.setProperty('fluentCard', True)
        form = QFormLayout(recipe_form)
        form.setContentsMargins(12, 8, 12, 8)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(FormAllNonFixedFieldsGrow)
        top_meta = QHBoxLayout()
        top_meta.setSpacing(12)
        self.table_name_edit = QLineEdit()
        self.table_name_edit.setPlaceholderText('Nom de la préparation et du résultat')
        self.table_name_edit.setAccessibleName('Nom de la préparation')
        self.table_name_edit.setToolTip('Nom donné au résultat et à la préparation réutilisable (recette) lorsque vous l\'enregistrez.')
        top_meta.addWidget(self.table_name_edit, 1)
        entree_title = QLabel('Entrée :')
        entree_title.setProperty('fluentRole', 'detail')
        top_meta.addWidget(entree_title)
        self.recipe_source_label = QLabel('Sélectionner une couche QGIS ou une recette à gauche.')
        self.recipe_source_label.setWordWrap(False)
        top_meta.addWidget(self.recipe_source_label, 1)
        self.rebind_button = QPushButton('Changer de données…', compact=True)
        self.rebind_button.setIcon(ui_icon('layers'))
        self.rebind_button.clicked.connect(self.rebind_recipe)
        top_meta.addWidget(self.rebind_button)
        form.addRow('Préparation', top_meta)
        destination_row = QHBoxLayout()
        self.recipe_destination_label = QLabel('Aucune destination enregistrée : le calcul produit une couche QGIS.')
        self.recipe_destination_label.setWordWrap(True)
        destination_row.addWidget(self.recipe_destination_label, 1)
        self.replay_destination_cb = QCheckBox('Livrer après le calcul')
        self.replay_destination_cb.setEnabled(False)
        self.replay_destination_cb.setToolTip('Réutiliser la destination fichier enregistrée. Un remplacement demande toujours confirmation.')
        self.replay_destination_cb.toggled.connect(self._on_destination_replay_changed)
        destination_row.addWidget(self.replay_destination_cb)
        self._destination_widget = QWidget()
        self._destination_widget.setLayout(destination_row)
        form.addRow('Livraison', self._destination_widget)
        self._destination_label = form.labelForField(self._destination_widget)
        self._destination_widget.hide()
        self._destination_label.hide()
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.setObjectName('transformer_workspace_stack')
        self.intentions_panel = IntentionsPanel()
        self.intentions_panel.continueRequested.connect(self._begin_intentions)
        self.intentions_panel.skipRequested.connect(self._show_workspace_editor)
        self.workspace_stack.addWidget(self.intentions_panel)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)

        self.context_banner = QFrame()
        self.context_banner.setObjectName('transformer_context_banner')
        self.context_banner.setProperty('fluentCard', 'banner')
        self.context_banner.setMaximumHeight(48)
        banner_layout = QHBoxLayout(self.context_banner)
        banner_layout.setContentsMargins(10, 5, 8, 5)
        banner_layout.setSpacing(6)
        self.banner_icon = QLabel()
        self.banner_icon.setFixedSize(18, 18)
        self.banner_icon.setPixmap(ui_icon('about').pixmap(QSize(18, 18)))
        banner_layout.addWidget(self.banner_icon)
        self.banner_label = QLabel('Sélectionnez une couche à gauche ou ouvrez un fichier :')
        self.banner_label.setObjectName('transformer_banner_label')
        self.banner_label.setWordWrap(False)
        banner_layout.addWidget(self.banner_label)
        self.banner_open_btn = QPushButton('Ajouter des données…', variant='primary', icon_name='open', compact=True)
        self.banner_open_btn.clicked.connect(self._open_source_data)
        banner_layout.addWidget(self.banner_open_btn)
        self.banner_clean_btn = QPushButton('Nettoyer texte', icon_name='text', compact=True)
        self.banner_clean_btn.setToolTip('Ouvrir l’outil de nettoyage guidé des colonnes texte')
        self.banner_clean_btn.clicked.connect(self._quick_action_clean)
        banner_layout.addWidget(self.banner_clean_btn)
        self.banner_filter_btn = QPushButton('Filtrer lignes', icon_name='filter', compact=True)
        self.banner_filter_btn.setToolTip('Définir une condition pour garder certaines lignes')
        self.banner_filter_btn.clicked.connect(self._quick_action_filter)
        banner_layout.addWidget(self.banner_filter_btn)
        self.banner_geom_btn = QPushButton('Géométrie / SCR', icon_name='geometry', compact=True)
        self.banner_geom_btn.setToolTip('Adapter la géométrie ou changer le système de coordonnées')
        self.banner_geom_btn.clicked.connect(self._quick_action_geometry)
        banner_layout.addWidget(self.banner_geom_btn)
        self.banner_compare_btn = QPushButton('Comparer', variant='primary', icon_name='compare', compact=True)
        self.banner_compare_btn.setToolTip('Calculer un aperçu avant/après sur 50 objets')
        self.banner_compare_btn.clicked.connect(self.test_configuration)
        banner_layout.addWidget(self.banner_compare_btn)
        banner_layout.addStretch(1)
        self.banner_close_btn = QToolButton()
        self.banner_close_btn.setIcon(ui_icon('clear'))
        self.banner_close_btn.setToolTip('Masquer cette barre de raccourcis')
        self.banner_close_btn.setAccessibleName('Masquer la barre de raccourcis')
        self.banner_close_btn.clicked.connect(self._dismiss_context_banner)
        banner_layout.addWidget(self.banner_close_btn)
        editor_layout.addWidget(self.context_banner)

        editor_layout.addWidget(recipe_form)

        self.stage_tabs = QTabWidget()
        self.stage_tabs.setAccessibleName('Étapes de préparation de la recette')
        self.stage_tabs.setDocumentMode(True)
        self.stage_tabs.currentChanged.connect(self._on_stage_changed)
        self.config_components = {'table_config': recipe_form}

        rules = QWidget()
        rules_layout = QVBoxLayout(rules)
        rules_layout.setContentsMargins(0, 12, 0, 0)
        self.advanced_expression = AdvancedExpressionWidget()
        self.smart_fields = FieldWidget(self.advanced_expression)
        self.quick_rules = QuickRules(self.smart_fields, button_factory=QPushButton)
        self.quick_rules.changed.connect(self._on_recipe_edited)
        self.quick_rules.changed.connect(self._mark_guided_columns)
        self.quick_rules.hide()
        rules_layout.addWidget(self.quick_rules)
        self.config_components['field_management'] = self.smart_fields
        self.config_components['expression_builder'] = self.advanced_expression
        self.config_splitter = QSplitter(Vertical)
        self.config_splitter.setChildrenCollapsible(False)
        self.config_splitter.setMinimumHeight(240)
        self.config_splitter.addWidget(self.smart_fields)
        self.config_splitter.addWidget(self.advanced_expression)
        self.advanced_expression.hide()
        self.config_splitter.setStretchFactor(0, 3)
        self.config_splitter.setStretchFactor(1, 1)
        rules_layout.addWidget(self.config_splitter, 1)
        rule_tools = QHBoxLayout()
        self.rule_summary = QLabel('Les champs de la couche seront proposés automatiquement.')
        self.rule_summary.setWordWrap(True)
        rule_tools.addWidget(self.rule_summary, 1)
        self.quick_tools_toggle = QPushButton('Nettoyer les valeurs', compact=True)
        self.quick_tools_toggle.setCheckable(True)
        self.quick_tools_toggle.toggled.connect(self.quick_rules.setVisible)
        rule_tools.addWidget(self.quick_tools_toggle)
        self.expression_toggle = QPushButton('Expression avancée')
        self.expression_toggle.setCheckable(True)
        self.expression_toggle.toggled.connect(self.advanced_expression.setVisible)
        rule_tools.addWidget(self.expression_toggle)
        rules_layout.addLayout(rule_tools)
        self.stage_tabs.addTab(self._scroll_stage(rules), ui_icon('fields'), 'Colonnes')

        filter_page = QWidget()
        filter_layout = QVBoxLayout(filter_page)
        filter_layout.setContentsMargins(0, 12, 0, 0)
        guided_filter = QFormLayout()
        self.filter_column = QComboBox()
        self.filter_column.setAccessibleName('Colonne de la condition')
        self.filter_operator = QComboBox()
        for label, code in [('est égal à', 'equal'), ('contient le texte', 'contains'),
                            ('n’est pas renseigné', 'null'), ('est supérieur à', 'greater')]:
            self.filter_operator.addItem(label, code)
        self.filter_value = QLineEdit()
        self.filter_value.setPlaceholderText('Valeur à rechercher')
        self.filter_value.setAccessibleName('Valeur de la condition')
        self.filter_operator.currentIndexChanged.connect(
            lambda: self.filter_value.setEnabled(self.filter_operator.currentData() != 'null'))
        guided_filter.addRow('Garder les lignes dont', self.filter_column)
        guided_filter.addRow('La valeur', self.filter_operator)
        guided_filter.addRow('Comparer avec', self.filter_value)
        filter_layout.addLayout(guided_filter)
        apply_filter = QPushButton('Appliquer cette condition', icon_name='filter')
        apply_filter.clicked.connect(self._apply_guided_filter)
        filter_layout.addWidget(apply_filter, 0, AlignLeft)
        self.smart_filter = SmartFilterWidget()
        self.config_components['smart_filter'] = self.smart_filter
        self.filter_active = QCheckBox('Garder uniquement les lignes de cette condition')
        self.filter_active.toggled.connect(self._guided_filter_enabled)
        filter_layout.addWidget(self.filter_active)
        filter_details = QPushButton('Condition détaillée', compact=True)
        filter_details.setCheckable(True)
        filter_details.toggled.connect(self.smart_filter.setVisible)
        filter_layout.addWidget(filter_details, 0, AlignLeft)
        filter_layout.addWidget(self.smart_filter)
        self.smart_filter.hide()
        filter_note = QLabel('Un filtre activé invalide bloque le traitement. Désactiver le filtre conserve sa règle.')
        filter_note.setWordWrap(True)
        filter_layout.addWidget(filter_note)
        filter_layout.addStretch()
        self.stage_tabs.addTab(self._scroll_stage(filter_page), ui_icon('filter'), 'Lignes')

        spatial = QWidget()
        spatial_layout = QVBoxLayout(spatial)
        spatial_layout.setContentsMargins(0, 16, 0, 0)
        spatial_form = QFormLayout()
        self.geometry_operation = QComboBox()
        self.geometry_operation.setAccessibleName('Transformation de la forme')
        for label, value in [('Conserver la forme', '$geometry'),
                             ('Représenter chaque objet par un point', 'centroid($geometry)'),
                             ('Créer une zone autour de chaque objet', 'buffer'),
                             ('Utiliser une expression détaillée', 'custom')]:
            self.geometry_operation.addItem(label, value)
        spatial_form.addRow('Ce que je veux obtenir', self.geometry_operation)
        self.geometry_distance = QDoubleSpinBox()
        self.geometry_distance.setRange(0.01, 10000000)
        self.geometry_distance.setValue(25)
        self.geometry_distance.setDecimals(2)
        self.geometry_distance.setAccessibleName('Distance dans les unités de la source')
        self.geometry_distance.setToolTip('La distance utilise les unités du système de coordonnées source, avant reprojection.')
        self.geometry_distance.hide()
        spatial_form.addRow('Distance (unités source)', self.geometry_distance)
        spatial_form.labelForField(self.geometry_distance).hide()
        self.geometry_form = spatial_form
        self.geometry_operation.currentIndexChanged.connect(self._guided_geometry_changed)
        self.geometry_distance.valueChanged.connect(self._guided_geometry_changed)
        self.geometry_expression_edit = QLineEdit('$geometry')
        self.geometry_expression_edit.setAccessibleName('Expression de géométrie')
        self.geometry_expression_edit.textChanged.connect(self._sync_geometry_controls)
        self.geometry_expression_edit.setPlaceholderText('$geometry, centroid($geometry), buffer($geometry, 25)…')
        spatial_form.addRow('Géométrie', self.geometry_expression_edit)
        self.current_crs_label = QLabel('Aucune source')
        self.current_crs_label.setWordWrap(True)
        spatial_form.addRow('SCR de calcul', self.current_crs_label)
        crs_row = QHBoxLayout()
        self.target_crs_label = QLabel('Conserver le SCR de la source')
        self.target_crs_label.setWordWrap(True)
        crs_row.addWidget(self.target_crs_label, 1)
        self.crs_selection_button = QPushButton('Choisir le SCR…')
        self.crs_selection_button.clicked.connect(self.open_crs_dialog)
        crs_row.addWidget(self.crs_selection_button)
        self.keep_crs_button = QPushButton('Conserver la source')
        self.keep_crs_button.clicked.connect(self._keep_source_crs)
        crs_row.addWidget(self.keep_crs_button)
        spatial_form.addRow('SCR de sortie', crs_row)
        spatial_layout.addLayout(spatial_form)
        self.geometry_details_toggle = QPushButton('Expression de géométrie détaillée', compact=True)
        self.geometry_details_toggle.setCheckable(True)
        self.geometry_details_toggle.toggled.connect(self._show_geometry_expression)
        spatial_layout.addWidget(self.geometry_details_toggle, 0, AlignLeft)
        self.geometry_expression_edit.hide()
        spatial_form.labelForField(self.geometry_expression_edit).hide()
        self.geometry_flow = GeometryFlowPreview()
        spatial_layout.addWidget(self.geometry_flow)
        self.spatial_note = QLabel('L’expression est calculée dans le SCR source, puis le résultat est reprojeté. Vérifier les unités avant une distance ou une surface.')
        self.spatial_note.setWordWrap(True)
        spatial_layout.addWidget(self.spatial_note)
        schema_note = QLabel('Schéma explicatif de la règle. Le contrôle calcule les valeurs et la géométrie sur l’échantillon.')
        schema_note.setWordWrap(True)
        spatial_layout.addWidget(schema_note)
        spatial_layout.addStretch()
        # Public references preserved for the native CRS chooser and history.
        self.crs_search_edit = QLineEdit()
        self.crs_search_edit.hide()
        self.quick_crs_buttons = []
        self.recent_crs_list = []
        self.target_crs = None
        self.current_crs = None
        self.stage_tabs.addTab(self._scroll_stage(spatial), ui_icon('geometry'), 'Géométrie')

        control = QWidget()
        control_layout = QVBoxLayout(control)
        control_layout.setContentsMargins(0, 12, 0, 0)
        control_bar = QHBoxLayout()
        self.control_status = QLabel('Aperçu à calculer : jusqu’à 50 objets lus, sans publication.')
        self.control_status.setWordWrap(True)
        control_bar.addWidget(self.control_status, 1)
        preview_button = QPushButton('Actualiser la comparaison')
        preview_button.setIcon(ui_icon('validate'))
        preview_button.clicked.connect(self.test_configuration)
        control_bar.addWidget(preview_button)
        control_layout.addLayout(control_bar)
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setMinimumHeight(140)
        self.preview_table.setAccessibleName('Aperçu des valeurs source et résultat calculé')
        self.preview_table.setEditTriggers(NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setSectionResizeMode(HeaderInteractive)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        control_layout.addWidget(self.preview_table, 1)
        self.control_details = QLabel('Un aperçu limité ne garantit pas l’absence d’erreur sur les autres objets.')
        self.control_details.setWordWrap(True)
        control_layout.addWidget(self.control_details)
        self.stage_tabs.addTab(control, ui_icon('validate'), 'Comparer')

        history = QWidget()
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(0, 12, 0, 0)
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(['Date', 'Recette / opération', 'État', 'Résultat'])
        self.history_tree.setRootIsDecorated(False)
        self.history_tree.setAlternatingRowColors(True)
        self.history_tree.header().setStretchLastSection(True)
        history_layout.addWidget(self.history_tree)
        export_receipt = QPushButton('Exporter le compte rendu…')
        export_receipt.clicked.connect(self.export_execution_receipt)
        receipt_actions = QHBoxLayout()
        receipt_actions.addWidget(export_receipt)
        diagnostic_button = QPushButton('Diagnostic anonymisé…')
        diagnostic_button.setToolTip('Exporter les versions, états et comptes sans noms, expressions, valeurs ou chemins métier.')
        diagnostic_button.clicked.connect(self.export_anonymized_diagnostic)
        receipt_actions.addWidget(diagnostic_button)
        receipt_actions.addStretch()
        history_layout.addLayout(receipt_actions)
        self.stage_tabs.addTab(history, ui_icon('history'), 'Résultats')
        editor_layout.addWidget(self.stage_tabs, 1)
        self.workspace_stack.addWidget(editor)
        layout.addWidget(self.workspace_stack, 1)

        self.workspace_footer = QWidget()
        footer = QHBoxLayout(self.workspace_footer)
        footer.setContentsMargins(0, 0, 0, 0)
        self.workspace_message = StableStatus('Choisissez vos objectifs. La source est conservée et les changements restent à vérifier.')
        self.workspace_message.setWordWrap(True)
        self.workspace_message.setFixedHeight(max(44, self.fontMetrics().height() * 2 + 10))
        layout.addWidget(self.workspace_message)
        self.flow_hint = QLabel('Votre source reste intacte.')
        self.flow_hint.setProperty('fluentRole', 'detail')
        footer.addWidget(self.flow_hint, 1)
        self.save_recipe_button = QPushButton('Enregistrer la préparation', compact=True)
        self.save_recipe_button.setIcon(ui_icon('save'))
        self.save_recipe_button.setToolTip('Enregistrer ces réglages comme préparation réutilisable (recette) pour les retrouver, les transmettre ou les rejouer.')
        self.save_recipe_button.clicked.connect(self.save_current_table_config)
        footer.addWidget(self.save_recipe_button)
        self.transform_selected_btn = QPushButton('Comparer les changements', variant='primary')
        self.transform_selected_btn.setIcon(ui_icon('transform'))
        self.transform_selected_btn.setAutoDefault(False)
        self.transform_selected_btn.setMinimumHeight(34)
        self.transform_selected_btn.clicked.connect(self._primary_workspace_action)
        footer.addWidget(self.transform_selected_btn)
        self.cancel_execution_button = QPushButton('Annuler', compact=True)
        self.cancel_execution_button.setAccessibleName('Annuler la création du résultat')
        self.cancel_execution_button.clicked.connect(self._cancel_execution)
        policy = self.cancel_execution_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.cancel_execution_button.setSizePolicy(policy)
        self.cancel_execution_button.hide()
        footer.addWidget(self.cancel_execution_button)
        self.transform_all_btn = QPushButton('Exécuter toutes les recettes…')
        self.transform_all_btn.clicked.connect(self.transform_all_shapefiles)
        self.transform_all_btn.hide()
        layout.addWidget(self.workspace_footer)
        self.workspace_stack.setCurrentIndex(1)
        return panel

    def create_shapefiles_widget(self):
        widget = QWidget()
        widget.setMinimumWidth(250)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        new_button = QPushButton('Nouvelle préparation', compact=True)
        new_button.setIcon(ui_icon('new'))
        new_button.clicked.connect(self.new_configuration)
        toolbar.addWidget(new_button)
        refresh_button = QToolButton()
        refresh_button.setIcon(ui_icon('refresh'))
        refresh_button.setToolTip('Actualiser les couches du projet')
        refresh_button.setAccessibleName('Actualiser les couches du projet')
        refresh_button.clicked.connect(self.sync_layers_from_project)
        toolbar.addWidget(refresh_button)
        layout.addLayout(toolbar)
        source_button = QPushButton('Ajouter des données…', icon_name='open', compact=True)
        source_button.clicked.connect(self._open_source_data)
        layout.addWidget(source_button)
        self.source_search = QLineEdit()
        self.source_search.setPlaceholderText('Trouver des données ou une préparation')
        self.source_search.setClearButtonEnabled(True)
        self.source_search.setAccessibleName('Rechercher une couche ou une recette')
        self.source_search.textChanged.connect(self._filter_source_rows)
        layout.addWidget(self.source_search)
        self.shp_tree = QTreeWidget()
        self.shp_tree.setHeaderLabels(['Données', 'Lignes'])
        self.shp_tree.setAlternatingRowColors(False)
        self.shp_tree.setRootIsDecorated(False)
        self.shp_tree.setSelectionMode(ExtendedSelection)
        self.shp_tree.header().setSectionResizeMode(0, HeaderStretch)
        self.shp_tree.header().setSectionResizeMode(1, HeaderResizeToContents)
        self.shp_tree.setAccessibleName('Couches QGIS et recettes enregistrées')
        self.shp_tree.setStyleSheet('QTreeView::item { min-height: 30px; }')
        layout.addWidget(self.shp_tree, 1)
        self.empty_sources_label = QLabel('Ajoutez vos données ou choisissez une couche déjà ouverte dans QGIS. Une préparation enregistrée peut aussi être reprise.')
        self.empty_sources_label.setWordWrap(True)
        layout.addWidget(self.empty_sources_label)
        self.selection_info_label = QLabel('Aucune sélection')
        self.selection_info_label.setWordWrap(True)
        layout.addWidget(self.selection_info_label)
        self.features_count_label = QLabel('0')
        self.geometry_type_label = QLabel('')
        self.crs_info_label = QLabel('')
        for label in (self.features_count_label, self.geometry_type_label, self.crs_info_label):
            label.hide()
        self.duplicate_action = QAction(ui_icon('duplicate'), 'Dupliquer la recette', self)
        self.duplicate_action.triggered.connect(self.duplicate_current_configuration)
        self.duplicate_action.setEnabled(False)
        menu = QMenu(self.shp_tree)
        menu.addAction(self.duplicate_action)
        menu.addAction('Relier une livraison…', self.rebind_recipe)
        menu.addAction('Supprimer la recette…', self.remove_selected_shapefile)
        self.shp_tree.setContextMenuPolicy(CustomContextMenu)
        self.shp_tree.customContextMenuRequested.connect(lambda point: menu.exec(self.shp_tree.viewport().mapToGlobal(point)))
        return widget

    def create_config_preview_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        note = QLabel('Vue experte de la recette. Une modification JSON doit être appliquée explicitement avant enregistrement ou exécution.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.config_preview = QPlainTextEdit()
        self.config_preview.setFont(fixed_system_font())
        self.config_preview.setAccessibleName('Recette au format JSON')
        self.config_preview.setMinimumWidth(180)
        self.config_preview.textChanged.connect(self._on_json_edited)
        layout.addWidget(self.config_preview, 1)
        apply_button = QPushButton('Appliquer le JSON au brouillon')
        apply_button.clicked.connect(self.apply_json_changes)
        layout.addWidget(apply_button)
        self.total_fields_label = QLabel('0')
        self.total_tables_label = QLabel('0')
        self.filter_status_label = QLabel('Sans filtre')
        counts = QHBoxLayout()
        counts.addWidget(QLabel('Champs'))
        counts.addWidget(self.total_fields_label)
        counts.addWidget(QLabel('Recettes'))
        counts.addWidget(self.total_tables_label)
        counts.addStretch()
        layout.addLayout(counts)
        return widget

    def create_help_widget(self):
        tabs = QTabWidget()
        tabs.setAccessibleName('Aide de l’atelier de recettes')
        self._help_tabs = tabs
        pages = [
            ('Recettes', 'Préparer, conserver et rejouer\n\nChoisir une couche dans la liste. Les champs de la source constituent le brouillon de départ. Définir les règles, le filtre, la géométrie et le SCR, puis calculer un aperçu.\n\nEnregistrer conserve la recette et ses types. Une recette dont l’entrée est absente reste visible : Relier une livraison permet de l’utiliser avec une nouvelle couche. Deux noms identiques ne désignent pas forcément la même couche.\n\nLe JSON est une vue avancée. Ses changements doivent être appliqués explicitement au brouillon. Un échec d’enregistrement conserve le travail et empêche la fermeture demandée avec Enregistrer.'),
            ('Règles', 'Champs de sortie\n\nLa matrice indique le nom de sortie, la règle, le type prévu et l’action. Sélectionner une ligne puis Définir, Entrée ou F2 permet de modifier sa règle et son type. Exclure retire le champ de la sortie ; la source reste intacte.\n\nExemples :\nupper("code")\nconcat("commune", \'_\', "numero")\nround("valeur", 2)\n\nUn type incompatible bloque la recette : une fraction n’est pas silencieusement tronquée dans un entier. Les valeurs NULL sont distinguées des erreurs. Les erreurs de calcul empêchent la publication de la recette concernée.'),
            ('Géométrie', 'Géométrie et unités\n\n$geometry conserve la forme ; centroid($geometry) produit un point. L’expression utilise le SCR source, puis la géométrie obtenue est reprojetée vers le SCR de sortie.\n\nUne distance ou surface doit être calculée dans un espace adapté. Un buffer dans un SCR en degrés est refusé : préparer une source dans un SCR métrique ou exprimer la transformation dans la règle.\n\nL’exécution de fond travaille sur une copie indépendante de la source. Les expressions lisant d’autres couches (aggregate, overlay, get_feature, @layer) et les fonctions personnalisées non sûres sont refusées avant évaluation. Préparer ces relations dans QGIS ou un modèle Processing puis utiliser leur résultat comme entrée.'),
            ('Livraison', 'Du calcul à la preuve d’écriture\n\nExécuter calcule les recettes sélectionnées vers de nouvelles couches QGIS. L’onglet Livraison fichier écrit les résultats avec format et encodage choisis. Après choix d’une destination, elle peut être enregistrée dans la recette. Livrer après le calcul permet son rejeu ; le remplacement d’un fichier existant reste confirmé. Une sélection ponctuelle d’objets n’est pas rejouée automatiquement.\n\nPostgreSQL analyse les tables sans les modifier. Le plan de colonnes et le mode d’écriture sont confirmés avant publication. Une erreur ou une annulation restaure la transaction de la table concernée. Les secrets sont gérés par l’authentification QGIS.\n\nExécutions distingue calcul, export fichier et publication. Un aperçu de 50 objets ne certifie pas le reste de la livraison. Le compte rendu décrit les réussites et les limites réellement observées.'),
        ]
        for title, text in pages:
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setPlainText(text)
            editor.setAccessibleName(title)
            tabs.addTab(editor, title)
        return tabs

    def _refresh_help_content(self):
        # The native plain-text help inherits font, palette and text scaling.
        return None

    def _create_modern_dock(self, title, object_name, widget):
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setFeatures(DockMovable | DockFloatable | DockClosable)
        dock.setAllowedAreas(AllDockAreas)
        return dock

    def setup_dockwidgets(self):
        self.source_dock = self._create_modern_dock('Mes données', 'source_dock', self.create_shapefiles_widget())
        self.config_dock = self._create_modern_dock('Recette JSON', 'config_dock', self.create_config_preview_widget())
        self.log_dock = self._create_modern_dock('Journal technique', 'log_dock', self.create_logs_widget())
        self.help_dock = self._create_modern_dock('Aide', 'help_dock', self.create_help_widget())
        self.doc_dock = self._create_modern_dock('Guide & Tutoriel', 'doc_dock', QWidget())
        self._doc_view_loaded = False
        self._arrange_fluid_layout()

    def _arrange_fluid_layout(self):
        self.addDockWidget(LeftDockArea, self.source_dock)
        for dock in (self.config_dock, self.help_dock, self.doc_dock):
            self.addDockWidget(RightDockArea, dock)
        self.addDockWidget(BottomDockArea, self.log_dock)
        self._layout_default()

    def _layout_default(self):
        self.source_dock.setVisible(True)
        for dock in (self.config_dock, self.log_dock, self.help_dock):
            dock.hide()
        if hasattr(self, 'doc_dock'):
            self.doc_dock.hide()
        self.resizeDocks([self.source_dock], [300], Horizontal)

    def _ensure_doc_dock_content(self, target_dock=None):
        dock = target_dock or getattr(self, 'doc_dock', None)
        if dock is None:
            return None
        doc_path = Path(__file__).resolve().parent.parent / 'docs' / 'guide_utilisateur.html'
        if getattr(dock, '_html_loaded', False):
            return doc_path
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        container = QWidget(dock)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QFrame(container)
        bar.setProperty('fluentCard', True)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.setSpacing(6)
        title_lbl = QLabel('Guide & Tutoriel pas à pas', bar)
        title_lbl.setProperty('fluentRole', 'section')
        bar_layout.addWidget(title_lbl, 1)
        float_btn = QPushButton('Agrandir / Détacher', compact=True)
        float_btn.clicked.connect(lambda: (dock.setFloating(not dock.isFloating()), dock.resize(1040, 740) if dock.isFloating() else None))
        bar_layout.addWidget(float_btn)
        browser_btn = QPushButton('Navigateur web', icon_name='open', compact=True)
        browser_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc_path))))
        bar_layout.addWidget(browser_btn)
        layout.addWidget(bar)
        try:
            from qgis.PyQt.QtWebEngineWidgets import QWebEngineView
            viewer = QWebEngineView(container)
            if doc_path.is_file():
                viewer.load(QUrl.fromLocalFile(str(doc_path)))
        except Exception:
            from qgis.PyQt.QtWidgets import QTextBrowser
            viewer = QTextBrowser(container)
            viewer.setOpenExternalLinks(True)
            if doc_path.is_file():
                viewer.setSearchPaths([str(doc_path.parent)])
                viewer.setHtml(doc_path.read_text(encoding='utf-8'))
        viewer.setMinimumWidth(420)
        layout.addWidget(viewer, 1)
        dock.setWidget(container)
        dock._html_loaded = True
        dock._doc_viewer = viewer
        return doc_path

    def open_documentation_dock(self):
        doc_path = self._ensure_doc_dock_content(self.doc_dock)
        if doc_path is None or not doc_path.is_file():
            self.workspace_message.setText('Le fichier docs/guide_utilisateur.html est introuvable.')
            return False
        self.doc_dock.show()
        self.doc_dock.raise_()
        self.resizeDocks([self.doc_dock], [520], Horizontal)
        self.workspace_message.setText('Guide et tutoriel ouvert dans le panneau latéral.')
        return True

    def _finalize_dock_setup(self):
        self.update()

    def restore_dock_state(self):
        # Old layout bytes came from a different dock hierarchy.
        return False

    def save_dock_state(self):
        return None

    def setup_toolbar(self):
        toolbar = self.addToolBar('Recettes')
        toolbar.setObjectName('transformer_main_toolbar')
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(ToolButtonTextBesideIcon)
        actions = [
            ('new', 'Nouvelle', self.new_configuration, 'Ctrl+N'),
            ('open', 'Importer…', self.open_configuration, 'Ctrl+O'),
            ('save', 'Enregistrer', self.save_current_table_config, 'Ctrl+S'),
        ]
        for icon, label, slot, shortcut in actions:
            action = QAction(ui_icon(icon), label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            toolbar.addAction(action)
        toolbar.addSeparator()
        self._toolbar_validate_action = QAction(ui_icon('validate'), 'Comparer', self)
        self._toolbar_validate_action.triggered.connect(self.test_configuration)
        toolbar.addAction(self._toolbar_validate_action)
        self.transform_action = QAction(ui_icon('transform'), 'Créer le résultat', self)
        self.transform_action.setShortcut(QKeySequence('F6'))
        self.transform_action.triggered.connect(self.transform_selected_shapefile)
        toolbar.addAction(self.transform_action)
        self.batch_action = QAction(ui_icon('batch'), 'Exécuter toutes les recettes…', self)
        self.batch_action.triggered.connect(self.transform_all_shapefiles)
        toolbar.addSeparator()
        details = QToolButton()
        details.setText('Outils')
        details.setPopupMode(InstantPopup)
        menu = QMenu(details)
        for dock in (self.config_dock, self.log_dock, self.help_dock):
            menu.addAction(dock.toggleViewAction())
        menu.addSeparator()
        menu.addAction(self.batch_action)
        menu.addAction('Exporter cette recette seule (.json)…', self.export_current_recipe)
        menu.addAction('Exporter les recettes…', self.save_configuration)
        menu.addAction('Dupliquer la recette', self.duplicate_current_configuration)
        menu.addAction('Préférences…', self.show_preferences)
        details.setMenu(menu)
        toolbar.addWidget(details)
        self.doc_action = QAction(ui_icon('documentation'), 'Tutoriel && Guide', self)
        self.doc_action.setShortcut(QKeySequence('F1'))
        self.doc_action.setToolTip('Ouvrir la documentation interactive et le tutoriel pas à pas dans un dock (F1)')
        self.doc_action.triggered.connect(self.open_documentation_dock)
        toolbar.addAction(self.doc_action)
        self.main_toolbar = toolbar

    def setup_menubar(self):
        recipes = self.menuBar().addMenu('Préparations')
        recipes.addAction('Nouvelle', self.new_configuration)
        recipes.addAction('Importer…', self.open_configuration)
        recipes.addAction('Enregistrer', self.save_current_table_config)
        recipes.addAction('Exporter cette recette seule (.json)…', self.export_current_recipe)
        recipes.addAction('Exporter la bibliothèque…', self.save_configuration)
        recipes.addSeparator()
        recipes.addAction('Fermer', self.close)
        view = self.menuBar().addMenu('Affichage')
        for dock in (self.source_dock, self.config_dock, self.log_dock, self.help_dock, self.doc_dock):
            view.addAction(dock.toggleViewAction())
        view.addAction('Disposition de travail', self._layout_default)
        edit = self.menuBar().addMenu('Édition')
        edit.addAction('Dupliquer la recette', self.duplicate_current_configuration)
        edit.addAction('Effacer les champs du brouillon', self._clear_all_fields)
        edit.addAction('Effacer le filtre', self._clear_active_filter)
        edit.addAction('Préférences…', self.show_preferences)
        help_menu = self.menuBar().addMenu('Aide')
        help_menu.addAction(ui_icon('documentation'), 'Tutoriel && Guide pas à pas (Dock)', self.open_documentation_dock)
        help_menu.addAction('Aide rapide (texte)', self.help_dock.show)
        help_menu.addAction('À propos', self.show_about)

    def setup_connections(self):
        self.shp_tree.itemSelectionChanged.connect(self.on_shapefile_selection_changed)
        self.table_name_edit.textChanged.connect(self._on_recipe_edited)
        self.smart_filter.filter_applied.connect(self._on_recipe_edited)
        self.smart_fields.field_added.connect(self.on_field_added)
        self.smart_fields.field_removed.connect(self.on_field_removed)
        self.smart_fields.field_modified.connect(self.on_field_modified)
        self.geometry_expression_edit.textChanged.connect(self._on_recipe_edited)
        self.main_tabs.currentChanged.connect(self.on_tab_changed)
        self.transformation_requested.connect(self.on_transformation_completed)
        self.ensure_project_layer_signals()

    def apply_theme(self):
        apply_fluent_style(self)
        if hasattr(self, '_refresh_toolbar_icons'):
            self._refresh_toolbar_icons()
        if hasattr(self, 'banner_close_btn'):
            self.banner_close_btn.setIcon(ui_icon('clear'))
        self._refresh_context_banner()

    def restore_window_state(self):
        if hasattr(self.interface_settings, 'load'):
            self.interface_settings.load()
        self.interface_settings.theme = InterfaceTheme.QGIS_NATIVE

    def save_window_state(self):
        if hasattr(self.interface_settings, 'save'):
            self.interface_settings.save()

    def _selected_data(self, item=None):
        item = item or self.shp_tree.currentItem()
        if item is None:
            return {}
        data = item.data(0, UserRole)
        return data if isinstance(data, dict) else {'source_file': data, 'table_name': None}

    def _source_info(self, key=None):
        return self.loaded_shapefiles.get(key if key is not None else self._editing_source_id, {})

    def _disconnect_active_source_signals(self, target_layer_id=None):
        remaining = []
        for source_id, signal, slot in getattr(self, '_source_signal_connections', ()):
            if target_layer_id is not None and source_id != target_layer_id:
                remaining.append((source_id, signal, slot))
                continue
            layer = self.loaded_shapefiles.get(source_id, {}).get('layer')
            if layer is None or _sip is None or not _sip.isdeleted(layer):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        if hasattr(self, '_source_signal_connections'):
            self._source_signal_connections = remaining

    def _sync_active_source_signals(self, source_id=None):
        target_id = source_id if source_id is not None else self._editing_source_id
        current_ids = {entry[0] for entry in getattr(self, '_source_signal_connections', ())}
        if target_id and current_ids == {target_id}:
            return
        self._disconnect_active_source_signals()
        if not target_id:
            return
        layer = (self.loaded_shapefiles.get(target_id) or {}).get('layer')
        if layer is None or not layer.isValid():
            return
        for name in ('dataChanged', 'updatedFields', 'attributeValueChanged', 'geometryChanged'):
            signal = getattr(layer, name, None)
            if signal is not None:
                def _slot(*_args, sid=target_id):
                    self._on_source_changed(sid)

                signal.connect(_slot)
                self._source_signal_connections.append((target_id, signal, _slot))

    def auto_load_qgis_layers(self):
        current = {}
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            current[layer.id()] = {
                'layer': layer, 'path': layer.source(), 'display_name': layer.name(),
                'name': layer.name(), 'source_id': layer.id(), 'format': layer.providerType(),
                'provider': layer.providerType(), 'feature_count': layer.featureCount(),
                'field_count': layer.fields().count(), 'geometry_type': wkb_type_name(layer.wkbType()),
                'crs': layer.crs().authid(), 'is_qgis_layer': True,
            }
        self.loaded_shapefiles = current
        self._sync_active_source_signals()

    def auto_load_configs(self):
        self.refresh_shapefile_list()

    def _find_source_for_config(self, config):
        source_id = config.get('source_id')
        if source_id in self.loaded_shapefiles:
            return source_id
        # A re-opened file layer can have a new project id. Match an exact URI
        # only; never silently select among identical visible names.
        source = config.get('source_file', '')
        matches = [key for key, info in self.loaded_shapefiles.items()
                   if source and source in (info.get('path'), info.get('display_name'))]
        if source_id:
            return None
        return matches[0] if len(matches) == 1 else None

    def refresh_shapefile_list(self):
        if getattr(self, '_initializing_workspace', False) or not hasattr(self, 'shp_tree'):
            return
        selected = [self._selected_data(item) for item in self.shp_tree.selectedItems()]
        current_key = (self._editing_source_id, self._loaded_recipe_name)
        blocker = QSignalBlocker(self.shp_tree)
        self.shp_tree.clear()
        bound = set()
        for name, config in self.config_manager.get_all_tables().items():
            source_id = self._find_source_for_config(config)
            info = self.loaded_shapefiles.get(source_id, {})
            if source_id:
                bound.add(source_id)
            source_name = info.get('display_name') or config.get('source_file') or 'Entrée à relier'
            item = QTreeWidgetItem(self.shp_tree, [name, str(info.get('feature_count', ''))])
            item.setIcon(0, ui_icon('config' if source_id else 'warning'))
            item.setData(0, UserRole, {'source_file': source_id, 'table_name': name})
            item.setToolTip(0, f'Recette : {name}\nEntrée : {source_name}\n'+('Entrée disponible' if source_id else 'Entrée à relier, recette conservée'))
            if (source_id, name) == current_key:
                self.shp_tree.setCurrentItem(item)
            if any(s.get('source_file') == source_id and s.get('table_name') == name for s in selected):
                item.setSelected(True)
        for source_id, info in self.loaded_shapefiles.items():
            item = QTreeWidgetItem(self.shp_tree, [info['display_name'], str(info['feature_count'])])
            geom_kind = str(info.get('geometry_type', '')).lower()
            icon_key = ('point_layer' if 'point' in geom_kind else
                        'line_layer' if any(t in geom_kind for t in ('line', 'curve')) else
                        'polygon_layer' if any(t in geom_kind for t in ('polygon', 'surface')) else
                        'table_layer' if 'no' in geom_kind or 'null' in geom_kind else 'layers')
            item.setIcon(0, ui_icon(icon_key))
            item.setData(0, UserRole, {'source_file': source_id, 'table_name': None})
            item.setToolTip(0, f"Couche QGIS : {info['display_name']}\n{info['provider']} · {info['crs']}\nIdentité : {source_id}")
            if current_key == (source_id, None):
                self.shp_tree.setCurrentItem(item)
            if any(s.get('source_file') == source_id and s.get('table_name') is None for s in selected):
                item.setSelected(True)
        del blocker
        self.empty_sources_label.setVisible(self.shp_tree.topLevelItemCount() == 0)
        if hasattr(self, 'source_search'):
            self._filter_source_rows(self.source_search.text())
        self.update_statistics()

    def _filter_source_rows(self, text):
        for index in range(self.shp_tree.topLevelItemCount()):
            item = self.shp_tree.topLevelItem(index)
            item.setHidden(text.casefold() not in (item.text(0)+' '+item.toolTip(0)).casefold())

    def _restore_selection(self, key=None, selected=None):
        key = key or (self._editing_source_id, self._loaded_recipe_name)
        selected = selected if selected is not None else [key]
        with QSignalBlocker(self.shp_tree):
            self.shp_tree.clearSelection()
            for index in range(self.shp_tree.topLevelItemCount()):
                item = self.shp_tree.topLevelItem(index)
                data = self._selected_data(item)
                item_key = (data.get('source_file'), data.get('table_name'))
                if item_key == key:
                    self.shp_tree.setCurrentItem(item)
                item.setSelected(item_key in selected)

    def _confirm_departure(self):
        if getattr(self, '_active_transform_task', None) is not None:
            self.workspace_message.setText('La création est en cours. Annulez-la et attendez son bilan avant de changer de préparation.')
            return False
        if not self.has_unsaved_changes():
            return True
        reply = QMessageBox.question(self, 'Préparation modifiée', 'Enregistrer la préparation avant de changer de contexte ?', MsgBoxSave | MsgBoxDiscard | MsgBoxCancel, MsgBoxSave)
        if reply == MsgBoxCancel:
            return False
        if reply == MsgBoxSave:
            return bool(self.save_current_table_config())
        return True

    def on_shapefile_selection_changed(self):
        if self._selection_guard or self._loading_recipe:
            return
        data = self._selected_data()
        if not data:
            return
        key = (data.get('source_file'), data.get('table_name'))
        requested_selection = [(row.get('source_file'),row.get('table_name')) for row in (self._selected_data(item) for item in self.shp_tree.selectedItems())]
        if key == (self._editing_source_id, self._loaded_recipe_name):
            self._last_selection = requested_selection
            return
        self._remember_workspace_view()
        self._selection_guard = True
        try:
            if not self._confirm_departure():
                self._restore_selection(selected=self._last_selection)
                return
            self._editing_source_id, self._loaded_recipe_name = key
            self._sync_active_source_signals(key[0])
            config = self.config_manager.get_table_config(key[1]) if key[1] else None
            if config:
                self._apply_table_config(key[1], config)
            else:
                self._auto_populate_default_config(key[0])
            self._json_pending = False
            self._saved_state = self._recipe_state()
            self._last_control = None
            self._restore_selection(key=key,selected=requested_selection)
            self._last_selection = requested_selection
            self._update_recipe_status()
            self._restore_workspace_view(key)
        finally:
            self._selection_guard = False

    def _auto_populate_default_config(self, filename):
        info = self._source_info(filename)
        layer = info.get('layer')
        if layer is None:
            return
        name = re.sub(r'[^\w]+', '_', info['display_name'], flags=re.UNICODE).strip('_')+'_preparee'
        fields = {}
        target_names = {}
        for field in layer.fields():
            target = field.name()
            if target.casefold() == 'geometry':
                target = 'geometry_attribut'
                suffix = 2
                while target in layer.fields().names() or target in fields:
                    target = f'geometry_attribut_{suffix}'
                    suffix += 1
            fields[target] = QgsExpression.quotedColumnRef(field.name())
            target_names[field.name()] = target
        definitions = {}
        for field in layer.fields():
            type_name = field.typeName().lower()
            canonical = 'Text'
            if 'bool' in type_name:
                canonical = 'Boolean'
            elif 'datetime' in type_name or 'timestamp' in type_name:
                canonical = 'DateTime'
            elif 'date' in type_name:
                canonical = 'Date'
            elif 'int8' in type_name or '64' in type_name or 'longlong' in type_name:
                canonical = 'Integer64'
            elif 'int' in type_name:
                canonical = 'Integer'
            elif any(s in type_name for s in ('real', 'double', 'numeric', 'float', 'decimal')):
                canonical = 'Real'
            definitions[target_names[field.name()]] = {'type': canonical, 'length': max(field.length(),0), 'precision': max(field.precision(),0), 'description': field.comment()}
        self._loaded_recipe_name = None
        self._apply_table_config(name, {'source_file':info['display_name'], 'source_id':filename, 'calculated_fields':fields, 'field_definitions':definitions, 'geometry_expression':'$geometry', 'filter':{'enabled':False,'expression':''}, 'target_crs':None}, as_draft=True)

    def _apply_table_config(self, table_name, config, as_draft=False):
        config = copy.deepcopy(config)
        legacy_renamed = False
        fields = config.get('calculated_fields', {})
        for field_name in list(fields):
            if field_name.casefold() != 'geometry':
                continue
            value = fields[field_name]
            if value == '$geometry' or value == config.get('geometry_expression'):
                config['geometry_expression'] = value
                del fields[field_name]
                config.get('field_definitions', {}).pop(field_name,None)
            else:
                target = 'geometry_attribut'
                suffix = 2
                while target in fields:
                    target = f'geometry_attribut_{suffix}'
                    suffix += 1
                config['calculated_fields'] = {target if key == field_name else key:expr for key,expr in fields.items()}
                if field_name in config.get('field_definitions', {}):
                    config['field_definitions'][target] = config['field_definitions'].pop(field_name)
            legacy_renamed = True
        self._loading_recipe = True
        try:
            if config.get('source_id') in self.loaded_shapefiles:
                self._editing_source_id = config['source_id']
            elif self._editing_source_id not in self.loaded_shapefiles:
                self._editing_source_id = self._find_source_for_config(config)
            self._loaded_recipe_name = None if as_draft else table_name
            self._destination_error = not isinstance(config.get('destination',{}),dict)
            self._recipe_destination = copy.deepcopy(config.get('destination') or {}) if not self._destination_error else {}
            self._refresh_destination_label()
            self._set_table_name_edit(table_name)
            self.smart_fields.set_calculated_fields(config.get('calculated_fields', {}), None, config.get('field_definitions') or {})
            self.smart_filter.set_filter_config(config.get('filter') or {'enabled':False,'expression':''})
            self.geometry_expression_edit.setText(config.get('geometry_expression') or '$geometry')
            target = config.get('target_crs')
            self._raw_target_crs = target
            self.target_crs = QgsCoordinateReferenceSystem(target) if target else None
            self.target_crs_label.setText(('SCR invalide : '+str(target)) if target and not self.target_crs.isValid() else (self.target_crs.authid() if self.target_crs else 'Conserver le SCR de la source'))
            info = self._source_info()
            layer = info.get('layer')
            saved_schema = config.get('source_schema')
            self._expected_source_schema = copy.deepcopy(saved_schema) if isinstance(saved_schema,list) else ([{'name':field.name(),'type':field.typeName()} for field in layer.fields()] if layer else [])
            self.smart_fields.set_layer(layer)
            self.smart_filter.set_layer(layer)
            if layer is not None:
                self.advanced_expression.set_layer(layer)
            self.recipe_source_label.setText((info.get('display_name')+' · '+info.get('crs','')) if layer else 'Entrée absente : relier une livraison pour rejouer cette recette.')
            self.selection_info_label.setText(self.recipe_source_label.text())
            self.current_crs_label.setText(layer.crs().description()+' ('+layer.crs().authid()+')' if layer else 'Entrée à relier')
            self.duplicate_action.setEnabled(not as_draft)
            self._json_pending = False
            self._last_control = None
            self._saved_state = self._recipe_state()
            self._force_dirty = legacy_renamed
            if legacy_renamed:
                self.workspace_message.setText('Le nom réservé geometry a été séparé de la géométrie ou proposé comme geometry_attribut. Vérifier puis enregistrer la recette.')
            self.update_configuration_preview()
        finally:
            self._loading_recipe = False

    def _recipe_state(self):
        if not hasattr(self, 'smart_fields'):
            return {}
        info = self._source_info()
        fields, _geometry = self.smart_fields.get_calculated_fields_with_geometry_info()
        return {
            'table_name':self.table_name_edit.text().strip(),
            'source_file':info.get('display_name') or (self.config_manager.get_table_config(self._loaded_recipe_name) or {}).get('source_file',''),
            'source_id':self._editing_source_id,
            'source_schema':copy.deepcopy(self._expected_source_schema),
            'calculated_fields':fields,
            'field_definitions':self.smart_fields.get_field_definitions() if hasattr(self.smart_fields,'get_field_definitions') else {},
            'filter':self.smart_filter.get_filter_config(),
            'geometry_expression':self.geometry_expression_edit.text().strip() or '$geometry',
            'target_crs':self.target_crs.authid() if self.target_crs is not None and self.target_crs.isValid() else self._raw_target_crs,
            'destination':copy.deepcopy(self._recipe_destination),
        }

    def has_unsaved_changes(self, state=None):
        current = self._recipe_state() if state is None else state
        return bool(self._force_dirty or self._json_pending or (self._saved_state is not None and current != self._saved_state))

    def _on_recipe_edited(self, *_args):
        if self._loading_recipe:
            return
        self._last_control = None
        self.update_configuration_preview()

    def on_field_added(self, name, expression):
        if name == 'geometry' and not self._loading_recipe:
            self.geometry_expression_edit.setText(expression)
        self._on_recipe_edited()

    def on_field_removed(self, name):
        if name == 'geometry' and not self._loading_recipe:
            self.geometry_expression_edit.setText('$geometry')
        self._on_recipe_edited()

    def on_field_modified(self, old_name, new_name, expression):
        if new_name == 'geometry' and not self._loading_recipe:
            self.geometry_expression_edit.setText(expression)
        self._on_recipe_edited()

    def on_table_name_changed(self):
        self._on_recipe_edited()

    def _on_json_edited(self):
        if self._writing_json or self._loading_recipe:
            return
        self._json_pending = True
        self._last_control = None
        self._update_recipe_status()

    def update_configuration_preview(self):
        if not hasattr(self, 'config_preview'):
            return
        state = self._recipe_state()
        if not self._json_pending:
            self._writing_json = True
            try:
                self.config_preview.setPlainText(json.dumps(state,ensure_ascii=False,indent=2))
            finally:
                self._writing_json = False
        self.total_fields_label.setText(str(len(state['calculated_fields'])))
        table_count = len(self.config_manager.config_data.get('tables', {}))
        self.total_tables_label.setText(str(table_count))
        self.filter_status_label.setText('Activé' if state['filter'].get('enabled') else 'Sans filtre')
        self.rule_summary.setText(f"{len(state['calculated_fields'])} champs de sortie · géométrie et SCR dans une étape dédiée")
        self._update_recipe_status(state=state)

    def _update_recipe_status(self, state=None):
        if not hasattr(self,'recipe_status_label'):
            return
        state = self._recipe_state() if state is None else state
        current_preview = bool(self._last_control and self._last_control.get('fingerprint') ==
                               self._state_fingerprint(state))
        preview_state = ('Aperçu à corriger' if self._last_control.get('errors') else 'Aperçu actuel') if current_preview else 'Contrôle à actualiser'
        if self._json_pending:
            text = 'JSON modifié : appliquer au brouillon'
        elif self.has_unsaved_changes(state=state):
            text = 'Modifiée · ' + preview_state
        elif self._loaded_recipe_name:
            text = 'Enregistrée' + (' · ' + preview_state if current_preview else ' · Contrôle à calculer')
        elif self._editing_source_id:
            text = 'Préparation à enregistrer' + (' · ' + preview_state if current_preview else '')
        else:
            text = 'Choisir une source ou relier une recette'
        self.recipe_status_label.setText(text)
        if hasattr(self,'control_status') and self._last_control is None:
            origin = getattr(self, '_last_preview_context', '')
            self.control_status.setText(('Résultat précédent : ' + origin + '. Cliquez sur « Comparer » pour actualiser la préparation actuelle.')
                if origin else 'Comparez les changements : jusqu’à 50 objets lus, sans modifier la source.')
        if hasattr(self, 'geometry_flow'):
            info = self._source_info()
            self.geometry_flow.set_operation(info.get('geometry_type','Polygon'),self.geometry_expression_edit.text())
        if hasattr(self,'transform_selected_btn'):
            self.transform_selected_btn.setEnabled(bool(self._source_info()) and self._active_transform_task is None)
        self._update_workspace_context()
        filter_config = state['filter']
        blocker = QSignalBlocker(self.filter_active)
        self.filter_active.setChecked(bool(filter_config.get('enabled')))
        self.filter_active.setEnabled(bool(filter_config.get('expression')))
        self.filter_active.setToolTip('Définissez une condition avant de l’activer.' if not filter_config.get('expression') else 'Désactiver conserve la condition sans exclure de lignes.')
        del blocker
        self._update_primary_action()

    def _update_workspace_context(self):
        if not hasattr(self, 'intentions_panel') or not hasattr(self, 'loaded_shapefiles'):
            return
        info = self._source_info()
        layer = info.get('layer')
        schema = {field.name(): field.typeName() for field in layer.fields()} if layer else {}
        compatible = []
        if layer:
            raw_tables = self.config_manager.config_data.get('tables', {})
            tables_sig = tuple(
                (name, cfg.get('recipe_version', 1), cfg.get('source_id'), cfg.get('source_file'), len(cfg.get('calculated_fields') or {}))
                for name, cfg in raw_tables.items()
            )
            cache_key = (self._editing_source_id, tuple(schema.items()), tables_sig)
            cached = getattr(self, '_compat_recipes_cache', None)
            if cached is not None and cached[0] == cache_key:
                compatible = list(cached[1])
            else:
                schema_cols = set(schema)
                for name, config in raw_tables.items():
                    if self._find_source_for_config(config) != self._editing_source_id:
                        continue
                    expected = {row['name']: row.get('type', '') for row in config.get('source_schema', [])
                                if isinstance(row, dict) and row.get('name')}
                    if expected and any(schema.get(column) != kind for column, kind in expected.items()):
                        continue
                    expressions = list((config.get('calculated_fields') or {}).values())
                    if (config.get('filter') or {}).get('enabled'):
                        expressions.append(config['filter'].get('expression', ''))
                    ok = True
                    for text in expressions:
                        expr = QgsExpression(text)
                        if expr.hasParserError() or not set(expr.referencedColumns()).issubset(schema_cols):
                            ok = False
                            break
                    if ok:
                        compatible.append(name)
                self._compat_recipes_cache = (cache_key, tuple(compatible))
        context = dict(source_id=self._editing_source_id, source_name=info.get('display_name', ''),
            field_names=list(schema), field_types=schema, geometry=bool(layer and layer.isSpatial()),
            read_only=bool(layer and layer.readOnly()),
            feature_count=info.get('feature_count'), compatible_recipes=compatible,
            source_crs=layer.crs().authid() if layer else '')
        key = json.dumps(context, sort_keys=True, ensure_ascii=False)
        if key == self._workspace_context_key:
            return
        self._workspace_context_key = key
        self._intentions_context = context
        self.intentions_panel.set_context(context)
        self.quick_rules.set_source(layer)
        old_field = self.filter_column.currentText()
        blocker = QSignalBlocker(self.filter_column)
        self.filter_column.clear()
        self.filter_column.addItems(list(schema))
        if old_field in schema:
            self.filter_column.setCurrentText(old_field)
        del blocker
        self.geometry_operation.setEnabled(bool(layer and layer.isSpatial()))
        self.geometry_operation.setToolTip('Cette entrée ne possède pas de géométrie.' if layer and not layer.isSpatial() else '')
        self.stage_tabs.setTabEnabled(2, bool(layer and layer.isSpatial()))
        self.stage_tabs.setTabToolTip(2, 'Cette entrée ne possède pas de géométrie.' if layer and not layer.isSpatial() else 'Préparer la forme et les coordonnées du résultat.')
        if layer:
            from qgis.core import QgsUnitTypes
            units = QgsUnitTypes.toString(layer.crs().mapUnits())
            self.geometry_distance.setSuffix(' ' + units)
            geographic = layer.crs().isGeographic()
            self.geometry_operation.model().item(2).setEnabled(not geographic)
            self.geometry_operation.setItemData(2,
                'Les coordonnées source sont en degrés. Utilisez une source projetée pour une distance en mètres.' if geographic
                else 'La distance est mesurée dans les unités de la source, avant reprojection.', ToolTipRole)
        self._refresh_context_banner(layer, info, schema)

    def _refresh_context_banner(self, layer=None, info=None, schema=None):
        if not hasattr(self, 'context_banner'):
            return
        if info is None:
            info = self._source_info()
        if layer is None:
            layer = info.get('layer')
        if schema is None:
            schema = {field.name(): field.typeName() for field in layer.fields()} if layer else {}
        has_source = layer is not None and layer.isValid()
        spatial = bool(has_source and layer.isSpatial())
        if not has_source:
            self.banner_icon.setPixmap(ui_icon('warning').pixmap(QSize(18, 18)))
            self.banner_label.setText('Aucune couche active : cliquez sur une couche à gauche ou ouvrez un fichier :')
            self.banner_open_btn.setVisible(True)
            for btn in (self.banner_clean_btn, self.banner_filter_btn, self.banner_geom_btn, self.banner_compare_btn):
                btn.setVisible(False)
            self.context_banner.setVisible(True)
        else:
            count = info.get('feature_count', 0)
            count_txt = f"{count} lignes" if isinstance(count, int) and count >= 0 else "lignes"
            self.banner_icon.setPixmap(ui_icon('about').pixmap(QSize(18, 18)))
            self.banner_label.setText(f"Accès rapide ({len(schema)} col. · {count_txt}) :")
            self.banner_open_btn.setVisible(False)
            self.banner_clean_btn.setVisible(bool(schema))
            self.banner_filter_btn.setVisible(bool(schema))
            self.banner_geom_btn.setVisible(spatial)
            self.banner_compare_btn.setVisible(True)
            on_prep_tab = hasattr(self, 'stage_tabs') and self.stage_tabs.currentIndex() in (0, 1, 2)
            self.context_banner.setVisible(
                on_prep_tab and self._editing_source_id not in getattr(self, '_banner_dismissed_sources', set())
            )

    def _dismiss_context_banner(self):
        if self._editing_source_id:
            self._banner_dismissed_sources.add(self._editing_source_id)
        if hasattr(self, 'context_banner'):
            self.context_banner.hide()

    def _quick_action_clean(self):
        self._show_workspace_editor()
        self.stage_tabs.setCurrentIndex(0)
        self.quick_tools_toggle.setChecked(True)
        self.quick_rules.setVisible(True)
        self.quick_rules.field_combo.setFocus()

    def _quick_action_filter(self):
        self._show_workspace_editor()
        self.stage_tabs.setCurrentIndex(1)
        self.filter_column.setFocus()

    def _quick_action_geometry(self):
        if self.stage_tabs.isTabEnabled(2):
            self._show_workspace_editor()
            self.stage_tabs.setCurrentIndex(2)
            self.geometry_operation.setFocus()

    def _show_intentions(self):
        self._view_generation += 1
        self.workspace_stack.setCurrentIndex(0)
        self.workspace_back.hide()
        if hasattr(self, 'workspace_footer'):
            self.workspace_footer.hide()
        self.workspace_title.setText('Assistant d’objectifs')
        if hasattr(self.intentions_panel, 'focus_first_choice'):
            self.intentions_panel.focus_first_choice()
        else:
            self.intentions_panel.setFocus()

    @staticmethod
    def _scroll_stage(widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(FrameNoFrame)
        scroll.setWidget(widget)
        scroll.setMinimumSize(0, 0)
        return scroll

    def _begin_intentions(self, intentions):
        if not self._source_info():
            self.workspace_message.setText('Choisissez ou ajoutez des données avant de préparer un résultat.')
            return
        choices = [value for value in intentions if value in ('clean', 'fields', 'filter', 'geometry', 'compare', 'deliver', 'replay')]
        if not choices:
            return
        self._chosen_intentions = choices
        self._guided_prepared.clear()
        if 'replay' in choices:
            names = self._intentions_context.get('compatible_recipes', [])
            if names:
                name, ok = (names[0], True) if len(names) == 1 else QInputDialog.getItem(
                    self, 'Reprendre une préparation', 'Préparation compatible', names, 0, False)
                if not ok or not self._confirm_departure():
                    return
                self._apply_table_config(name, self.config_manager.get_table_config(name))
                self._restore_selection((self._editing_source_id, name))
        self._show_workspace_editor()
        indexes = {'clean': 0, 'fields': 0, 'filter': 1, 'geometry': 2, 'compare': 3, 'deliver': 3, 'replay': 3}
        self.stage_tabs.setCurrentIndex(indexes[choices[0]])
        self.quick_tools_toggle.setChecked('clean' in choices)
        self.quick_rules.setVisible('clean' in choices)
        self.workspace_message.setText('Votre préparation combine les objectifs choisis. Comparez les changements avant de créer le résultat.')
        self._update_primary_action()

    def _show_workspace_editor(self):
        self._view_generation += 1
        self.workspace_stack.setCurrentIndex(1)
        self.workspace_back.show()
        self.workspace_footer.show()
        self.workspace_title.setText('Préparer, puis voir la différence.')

    def _on_stage_changed(self, index):
        if self._loading_recipe or not hasattr(self, 'workspace_message'):
            return
        self._view_generation += 1
        self._refresh_context_banner()
        self._update_primary_action()

    def _update_primary_action(self):
        if not hasattr(self, 'transform_selected_btn'):
            return
        running = getattr(self, '_active_transform_task', None) is not None
        checked = bool(self._last_control and not self._last_control.get('errors')
                       and self._last_control.get('fingerprint') == self._state_fingerprint(self._recipe_state()))
        if running:
            text = 'Création du résultat…'
        elif self._result_layers and self.stage_tabs.currentIndex() == 4:
            text = 'Choisir comment livrer'
        elif self.stage_tabs.currentIndex() != 3 and self._next_guided_stage() is not None:
            text = {0: 'Préparer les colonnes', 1: 'Choisir les lignes', 2: 'Transformer la forme'}[self._next_guided_stage()]
        elif checked:
            text = 'Créer le résultat'
        else:
            text = 'Comparer les changements'
        self.transform_selected_btn.setText(text)
        self.transform_selected_btn.setBusy(running)
        self.transform_selected_btn.setToolTip('La source est conservée. Le contrôle complet est exécuté pendant la création du résultat.')

    def _primary_workspace_action(self):
        if self._active_transform_task is not None:
            return
        self._show_workspace_editor()
        current = self.stage_tabs.currentIndex()
        next_stage = self._next_guided_stage()
        if current != 3 and next_stage is not None:
            self._guided_prepared.add(current)
            self.stage_tabs.setCurrentIndex(next_stage)
            return
        if self._result_layers and self.stage_tabs.currentIndex() == 4:
            self._open_result_delivery()
        elif self._last_control and not self._last_control.get('errors') and self._last_control.get('fingerprint') == self._state_fingerprint(self._recipe_state()):
            self.transform_selected_shapefile()
        else:
            self.test_configuration()

    def _next_guided_stage(self):
        stages = {'clean': 0, 'fields': 0, 'filter': 1, 'geometry': 2}
        current = self.stage_tabs.currentIndex()
        for intention in self._chosen_intentions:
            stage = stages.get(intention)
            if stage is not None and stage != current and stage not in self._guided_prepared:
                return stage
        return None

    def _mark_guided_columns(self):
        self._guided_prepared.add(0)
        self._update_primary_action()

    def _remember_workspace_view(self):
        if not hasattr(self, 'workspace_stack'):
            return
        key = (self._editing_source_id, self._loaded_recipe_name)
        self._workspace_views[key] = (self.workspace_stack.currentIndex(), self.stage_tabs.currentIndex(),
            self.preview_table.verticalScrollBar().value(), self.preview_table.horizontalScrollBar().value())

    def _restore_workspace_view(self, key):
        self._view_generation += 1
        generation = self._view_generation
        view = self._workspace_views.get(key, (1, 0, 0, 0))
        if view[0]:
            self._show_workspace_editor()
        else:
            self._show_intentions()
        self.stage_tabs.setCurrentIndex(view[1])
        self._pending_workspace_view = (generation, key, view)
        if not hasattr(self, '_workspace_view_timer'):
            self._workspace_view_timer = QTimer(self)
            self._workspace_view_timer.setSingleShot(True)
            self._workspace_view_timer.timeout.connect(self._restore_deferred_workspace_view)
        self._workspace_view_timer.start(0)

    def _restore_deferred_workspace_view(self):
        generation, key, view = self._pending_workspace_view
        if generation != self._view_generation or key != (self._editing_source_id, self._loaded_recipe_name):
            return
        self.preview_table.verticalScrollBar().setValue(view[2])
        self.preview_table.horizontalScrollBar().setValue(view[3])

    def _guided_geometry_changed(self, *_args):
        mode = self.geometry_operation.currentData()
        show_distance = mode == 'buffer'
        self.geometry_distance.setVisible(show_distance)
        self.geometry_form.labelForField(self.geometry_distance).setVisible(show_distance)
        if not hasattr(self, 'geometry_expression_edit') or self._loading_recipe or mode == 'custom':
            if mode == 'custom' and hasattr(self, 'geometry_details_toggle'):
                self.geometry_details_toggle.setChecked(True)
            return
        expression = 'buffer($geometry, %s)' % format(self.geometry_distance.value(), '.12g') if show_distance else mode
        self.geometry_expression_edit.setText(expression)

    def _sync_geometry_controls(self, *_args):
        expression = self.geometry_expression_edit.text().strip()
        index = self.geometry_operation.findData(expression)
        buffer = re.fullmatch(r'buffer\(\s*\$geometry\s*,\s*([\d.eE+\-]+)\s*\)', expression, re.I)
        if buffer:
            index = self.geometry_operation.findData('buffer')
        if index < 0:
            index = self.geometry_operation.findData('custom')
        blocker = QSignalBlocker(self.geometry_operation)
        distance_blocker = QSignalBlocker(self.geometry_distance)
        self.geometry_operation.setCurrentIndex(index)
        if buffer:
            try:
                self.geometry_distance.setValue(float(buffer.group(1)))
            except ValueError:
                pass
        del blocker, distance_blocker
        self.geometry_distance.setVisible(bool(buffer))
        self.geometry_form.labelForField(self.geometry_distance).setVisible(bool(buffer))
        if self.geometry_operation.currentData() == 'custom' and hasattr(self, 'geometry_details_toggle'):
            self.geometry_details_toggle.setChecked(True)

    def _show_geometry_expression(self, visible):
        self.geometry_expression_edit.setVisible(visible)
        self.geometry_form.labelForField(self.geometry_expression_edit).setVisible(visible)

    def _guided_filter_enabled(self, enabled):
        config = self.smart_filter.get_filter_config()
        config['enabled'] = bool(enabled)
        self.smart_filter.set_filter_config(config)
        self._on_recipe_edited()

    def _apply_guided_filter(self):
        layer = self._source_info().get('layer')
        name, operator = self.filter_column.currentText(), self.filter_operator.currentData()
        if not layer or name not in layer.fields().names():
            self.workspace_message.setText('Choisissez une colonne de la source pour définir la condition.')
            return
        column, value = QgsExpression.quotedColumnRef(name), self.filter_value.text()
        if operator == 'null':
            expression = column + ' IS NULL'
        elif operator == 'contains':
            expression = 'strpos(lower(to_string(%s)), lower(%s)) > 0' % (column, QgsExpression.quotedValue(value))
        else:
            field = layer.fields().field(name)
            if field.isNumeric():
                try:
                    from decimal import Decimal, InvalidOperation
                    number = Decimal(value.replace(',', '.'))
                    if not number.is_finite():
                        raise InvalidOperation
                    literal = str(number)
                except (InvalidOperation, ValueError):
                    self.workspace_message.setText('Cette colonne contient des nombres. Saisissez un nombre valide pour la condition.')
                    self.filter_value.setFocus()
                    return
            elif operator == 'greater':
                self.workspace_message.setText('Choisissez une colonne numérique pour comparer des nombres.')
                return
            else:
                literal = QgsExpression.quotedValue(value)
            expression = '%s %s %s' % (column, '>' if operator == 'greater' else '=', literal)
        self.smart_filter.set_filter_config({'enabled': True, 'expression': expression})
        self._guided_prepared.add(1)
        self._on_recipe_edited()
        self.workspace_message.setText('Condition préparée. Comparez les lignes retenues avant de créer le résultat.')

    def _open_source_data(self):
        if not self._confirm_departure():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choisir des données', '',
            'Données (*.gpkg *.geojson *.json *.shp *.tab *.csv);;Tous les fichiers (*)')
        if not path:
            return
        from qgis.core import QgsProviderRegistry
        details = [item for item in QgsProviderRegistry.instance().querySublayers(path)
                   if item.type() == LayerTypeVector]
        uri = path
        if len(details) > 1:
            names = [item.name() for item in details]
            name, ok = QInputDialog.getItem(self, 'Choisir les données du fichier', 'Couche', names, 0, False)
            if not ok:
                return
            uri = details[names.index(name)].uri()
        layer = QgsVectorLayer(uri, Path(path).stem, 'ogr')
        if not layer.isValid():
            self.workspace_message.setText('Ce fichier ne fournit pas une couche lisible. Vérifiez son format ou ouvrez-le depuis QGIS.')
            return
        QgsProject.instance().addMapLayer(layer)
        self.auto_load_qgis_layers()
        self.refresh_shapefile_list()
        for index in range(self.shp_tree.topLevelItemCount()):
            item = self.shp_tree.topLevelItem(index)
            if self._selected_data(item) == {'source_file': layer.id(), 'table_name': None}:
                self.shp_tree.setCurrentItem(item)
                break

    def _install_delivery_page(self):
        from .delivery_panel import DeliveryPanel
        exporter = getattr(self, 'export_widget', None)
        if exporter is None:
            return
        self.main_tabs.removeTab(1)
        exporter.setParent(self)
        exporter.hide()
        self.delivery_panel = DeliveryPanel(exporter, self)
        self.main_tabs.insertTab(1, self._scroll_stage(self.delivery_panel), ui_icon('export'), 'Livrer')

    def _open_result_delivery(self):
        if not hasattr(self, 'delivery_panel'):
            self.workspace_message.setText('Le module de livraison est indisponible. Votre résultat reste accessible dans QGIS.')
            return
        existing = []
        for result in self._result_layers:
            try:
                current = QgsProject.instance().mapLayer(result.id())
                if current is not None and current.isValid():
                    existing.append(current)
            except RuntimeError:
                continue
        self._result_layers = existing
        self.delivery_panel.set_results(existing)
        if len(self._result_layers) == 1:
            result_id = self._result_layers[0].id()
            self.delivery_panel.layer_combo.setCurrentIndex(self.delivery_panel.layer_combo.findData(result_id))
        self.main_tabs.setCurrentIndex(1)
        if not existing:
            self.delivery_panel.delivery_status.setText('Le résultat n’est plus disponible dans QGIS. Recréez-le avant de préparer sa livraison.')

    def _sync_preview_to_fields(self):
        if self._json_pending:
            self.workspace_message.setText('Appliquer ou abandonner les modifications de la vue JSON avant de poursuivre.')
            self.config_dock.show()
            self.config_dock.raise_()
            return False
        return True

    def apply_json_changes(self):
        try:
            state = json.loads(self.config_preview.toPlainText())
            self._validate_recipe_candidate(state)
            source_id = self._editing_source_id
            name = self._loaded_recipe_name
            baseline = self._saved_state
            state['source_id'] = source_id
            self._apply_table_config(state['table_name'],state,as_draft=name is None)
            self._loaded_recipe_name = name
            self._saved_state = baseline
            self._json_pending = False
            self._on_recipe_edited()
            self.workspace_message.setText('JSON appliqué au brouillon. Vérifier puis enregistrer la recette.')
            return True
        except (ValueError,TypeError,KeyError) as exc:
            QMessageBox.warning(self,'Recette JSON invalide',str(exc))
            return False

    def _validate_recipe_candidate(self, state, imported=False):
        if not isinstance(state,dict) or not isinstance(state.get('calculated_fields'),dict) or not isinstance(state.get('table_name'),str) or not state['table_name'].strip():
            raise ValueError('La recette doit contenir un nom et un dictionnaire de champs.')
        errors = self.config_manager._validate_document({'version':self.config_manager._CONFIG_VERSION,'tables':{state['table_name']:state}})
        if errors:
            raise ValueError('\n'.join(errors))
        if not imported and state.get('source_id') not in (None,self._editing_source_id):
            raise ValueError('Pour changer d’entrée, utiliser Relier une livraison.')
        target = state.get('target_crs')
        if target and not QgsCoordinateReferenceSystem(target).isValid():
            raise ValueError('SCR de sortie inconnu. Choisir un code EPSG disponible avant d’appliquer la recette.')
        expressions = list(state['calculated_fields'].items())+[('Géométrie',state.get('geometry_expression') or '$geometry')]
        filter_config = state.get('filter') or {}
        if filter_config.get('enabled'):
            expressions.append(('Filtre',filter_config.get('expression','')))
        for name,text in expressions:
            expression = QgsExpression(text)
            if not text or expression.hasParserError():
                raise ValueError(f'{name} : '+(expression.parserErrorString() or 'expression vide'))

    def validate_configuration(self):
        if not self._sync_preview_to_fields():
            return False
        state = self._recipe_state()
        layer = self._source_info().get('layer')
        errors=[]
        if not state['table_name']:
            errors.append('Donner un nom à la recette.')
        if layer is None or not layer.isValid():
            errors.append('Relier une couche QGIS disponible à la recette.')
        if not state['calculated_fields']:
            errors.append('Conserver ou créer au moins un champ de sortie.')
        if state.get('target_crs') and not QgsCoordinateReferenceSystem(state['target_crs']).isValid():
            errors.append('Le SCR enregistré est invalide. Choisir un SCR disponible ou conserver le SCR source.')
        if self._destination_error:
            errors.append('La destination enregistrée est invalide. Choisir une nouvelle destination dans Livraison fichier.')
        if layer is not None:
            known=set(layer.fields().names())
            expressions=list(state['calculated_fields'].items())+[('Géométrie',state['geometry_expression'])]
            if state['filter'].get('enabled'):
                expressions.append(('Filtre',state['filter'].get('expression','')))
            for name,text in expressions:
                expr=QgsExpression(text)
                if not text or expr.hasParserError():
                    errors.append(f'{name} : '+(expr.parserErrorString() or 'expression vide'))
                elif not set(expr.referencedColumns()).issubset(known | {'#!allattributes!#'}):
                    missing=set(expr.referencedColumns())-known-{'#!allattributes!#'}
                    errors.append(f'{name} : champs absents '+', '.join(sorted(missing)))
            spatial=state['geometry_expression'].lower()
            if (any(word in spatial for word in ('buffer(', 'distance(', 'area(', 'length(')) and layer.crs().isGeographic()):
                errors.append('Cette opération de distance ou de surface utilise un SCR géographique. Reprojeter la couche dans un SCR métrique avant le calcul, ou écrire une transformation explicite dans l’expression.')
        if errors:
            self.workspace_message.setText(errors[0])
            QMessageBox.warning(self,'Recette à corriger','\n'.join(errors[:10]))
            return False
        self.workspace_message.setText('Règles vérifiées. L’aperçu contrôle un échantillon ; l’exécution contrôle tous les objets retenus.')
        return True

    def save_selected_configurations(self):
        return self.save_current_table_config()

    def save_current_table_config(self, skip_validation=False):
        if not self._sync_preview_to_fields():
            return False
        if not skip_validation and not self.validate_configuration():
            return False
        state=self._recipe_state()
        name=state['table_name']
        if not name:
            return False
        if self.config_manager.has_table_config(name) and name != self._loaded_recipe_name:
            answer=QMessageBox.question(self,'Nom déjà utilisé',f'Une autre recette porte le nom « {name} ». La remplacer ?',MsgBoxYes | MsgBoxNo,MsgBoxNo)
            if answer!=MsgBoxYes:
                return False
        before=copy.deepcopy(self.config_manager.config_data)
        result=self.config_manager.add_table_config(name,state['source_file'],state['calculated_fields'],state['filter'],state['target_crs'],state['geometry_expression'],force_replace=True,field_definitions=state['field_definitions'],source_id=state['source_id'],source_schema=state['source_schema'],destination=state['destination'])
        if not result.get('success') or not self.config_manager.save_config():
            self.config_manager.config_data=before
            detail = result.get('message','') if not result.get('success') else 'Vérifier les droits du dossier puis réessayer.'
            self.workspace_message.setText('Recette non enregistrée. Le brouillon est conservé. '+detail)
            QMessageBox.critical(self,'Recette non enregistrée',self.workspace_message.text())
            return False
        self._loaded_recipe_name=name
        self._force_dirty=False
        self._saved_state=self._recipe_state()
        self._json_pending=False
        self.refresh_shapefile_list()
        self.workspace_message.setText(f'Recette « {name} » enregistrée.')
        self._update_recipe_status()
        return True

    def _context(self,layer):
        context=QgsExpressionContext()
        context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        return context

    def test_configuration(self):
        if not self.validate_configuration():
            return False
        self._show_workspace_editor()
        state=self._recipe_state()
        layer=self._source_info()['layer']
        context=self._context(layer)
        expressions={name:QgsExpression(text) for name,text in state['calculated_fields'].items()}
        geom_expr=QgsExpression(state['geometry_expression'])
        filter_expr=QgsExpression(state['filter'].get('expression','')) if state['filter'].get('enabled') else None
        for expr in list(expressions.values())+[geom_expr]+([filter_expr] if filter_expr else []):
            expr.prepare(context)
        request=QgsFeatureRequest().setLimit(50)
        rows=[]
        errors=[]
        examined=0
        excluded=0
        layer_field_names = set(layer.fields().names())
        expr_ref_cols = {
            name: sorted(set(expr.referencedColumns()) & layer_field_names)
            for name, expr in expressions.items()
        }
        coord_transform = None
        if layer.isSpatial() and state['target_crs']:
            coord_transform = QgsCoordinateTransform(
                layer.crs(),
                QgsCoordinateReferenceSystem(state['target_crs']),
                QgsProject.instance().transformContext(),
            )
        for feature in layer.getFeatures(request):
            examined+=1
            context.setFeature(feature)
            if filter_expr is not None:
                included=filter_expr.evaluate(context)
                if filter_expr.hasEvalError():
                    errors.append(f'Objet {feature.id()} : filtre, {filter_expr.evalErrorString()}')
                    continue
                if not included:
                    excluded+=1
                    continue
            row=[str(feature.id())]
            for name,expr in expressions.items():
                value=expr.evaluate(context)
                if expr.hasEvalError():
                    errors.append(f'Objet {feature.id()}, {name} : {expr.evalErrorString()}')
                    value='ERREUR'
                columns = expr_ref_cols[name]
                source = feature.attribute(name) if name in layer_field_names else '; '.join(f'{column}={feature.attribute(column)}' for column in columns) or 'Constante'
                row.extend([str(source),str(value)])
            geometry=geom_expr.evaluate(context) if layer.isSpatial() else None
            if not layer.isSpatial():
                row.append('Sans géométrie')
            elif geom_expr.hasEvalError() or not isinstance(geometry,QgsGeometry):
                errors.append(f'Objet {feature.id()} : géométrie invalide ou expression sans géométrie.')
                row.append('ERREUR')
            else:
                if coord_transform is not None:
                    geometry=QgsGeometry(geometry)
                    geometry.transform(coord_transform)
                row.append(geometry.asWkt(3)[:160])
            rows.append(row)
        headers=['Objet']
        for name in expressions:
            headers.extend([f'Avant · {name}',f'Après · {name}'])
        headers.append('Géométrie après')
        self.preview_table.setUpdatesEnabled(False)
        try:
            self.preview_table.clear()
            self.preview_table.setColumnCount(len(headers))
            self.preview_table.setHorizontalHeaderLabels(headers)
            self.preview_table.setRowCount(len(rows))
            changes = 0
            for i,row in enumerate(rows):
                for j,value in enumerate(row):
                    item=QTableWidgetItem(value)
                    item.setToolTip(value)
                    if j > 0 and j % 2 == 0 and j < len(row) - 1 and value != row[j - 1]:
                        changes += 1
                        color = QColor(self.palette().color(PaletteHighlight))
                        color.setAlpha(24)
                        item.setBackground(color)
                        item.setIcon(ui_icon('edit'))
                        item.setToolTip('Valeur modifiée : ' + value + '\nAvant : ' + row[j - 1])
                        item.setData(AccessibleDescriptionRole, 'Valeur modifiée : ' + value)
                    self.preview_table.setItem(i,j,item)
            self.preview_table.resizeColumnsToContents()
            for col in range(self.preview_table.columnCount()):
                self.preview_table.setColumnWidth(col,min(260,max(110,self.preview_table.columnWidth(col))))
        finally:
            self.preview_table.setUpdatesEnabled(True)
        self._last_control={'fingerprint':self._state_fingerprint(state),'read':examined,'excluded':excluded,'rows':len(rows),'errors':errors}
        self._last_preview_context = layer.name() + ' / ' + state['table_name']
        self.control_status.setText(f'{examined} lignes lues · {excluded} exclues · {len(rows)} retenues · {changes} valeurs modifiées · {len(errors)} erreurs')
        self.control_details.setText('\n'.join(errors[:5]) if errors else 'Aperçu limité aux 50 premiers objets lus. Les types et valeurs seront contrôlés sur toute la sortie pendant l’exécution.')
        self.stage_tabs.setCurrentIndex(3)
        self.workspace_message.setText('Comparaison prête. La création contrôlera les types et les valeurs sur la totalité du résultat.' if not errors else 'La comparaison contient des erreurs. Corrigez les règles indiquées avant de créer le résultat.')
        self._update_recipe_status()
        return not errors

    @staticmethod
    def _state_fingerprint(state):
        return hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False,default=str).encode('utf-8')).hexdigest()

    def create_test_layer(self,layer,calculated_fields,filter_config,max_features=100):
        count=sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setLimit(max_features)))
        return {'success':True,'source_count':layer.featureCount(),'filtered_count':None,'processed_count':count,'limited':True}

    def _snapshot_selected_transform_items(self,selected_items):
        grouped={}
        for item in selected_items:
            data=self._selected_data(item)
            source_id=data.get('source_file')
            recipe=data.get('table_name')
            if not source_id or source_id not in self.loaded_shapefiles:
                continue
            if not recipe:
                if source_id==self._editing_source_id and self._loaded_recipe_name:
                    recipe=self._loaded_recipe_name
                else:
                    continue
            grouped.setdefault(source_id,set()).add(recipe)
        return [{'filename':source_id,'shapefile_info':dict(self.loaded_shapefiles[source_id]),'table_names':sorted(names)} for source_id,names in grouped.items()]

    def _snapshot_all_transform_items(self):
        grouped={}
        for name,config in self.config_manager.get_all_tables().items():
            source_id=self._find_source_for_config(config)
            if source_id:
                grouped.setdefault(source_id,[]).append(name)
        return [{'filename':key,'shapefile_info':dict(self.loaded_shapefiles[key]),'table_names':names} for key,names in grouped.items()]

    def transform_selected_shapefile(self):
        if self._active_transform_task is not None:
            self.workspace_message.setText('Une exécution est déjà en cours. Attendre ou l’annuler avant de relancer.')
            return False
        selected=self.shp_tree.selectedItems()
        selected_keys=[(data.get('source_file'),data.get('table_name')) for data in (self._selected_data(item) for item in selected)]
        active_selected = (self._editing_source_id,self._loaded_recipe_name) in selected_keys or (self._editing_source_id,None) in selected_keys or not selected
        if active_selected:
            if not self.validate_configuration() or not self.save_current_table_config(skip_validation=True):
                return False
            selected=self.shp_tree.selectedItems()
        items=self._snapshot_selected_transform_items(selected)
        if not items and active_selected and self._editing_source_id:
            items=[{'filename':self._editing_source_id,'shapefile_info':dict(self._source_info()),'table_names':[self._loaded_recipe_name]}]
        if not items:
            return False
        names=[name for item in items for name in item['table_names']]
        self.workspace_message.setText('Exécution : '+', '.join(names))
        destination = (self.config_manager.get_table_config(names[0]) or {}).get('destination',{}) if len(names)==1 else {}
        self._pending_delivery = copy.deepcopy(destination) if isinstance(destination,dict) and destination.get('replay') else None
        self._launch_transform_task(items,None)
        return True

    def transform_all_shapefiles(self):
        if not self._confirm_departure():
            return False
        items=self._snapshot_all_transform_items()
        names=[name for item in items for name in item['table_names']]
        if not names:
            self.workspace_message.setText('Aucune recette reliée à une entrée disponible.')
            return False
        answer=QMessageBox.question(self,'Exécution de plusieurs recettes',f'Exécuter {len(names)} recettes ?\n\n'+'\n'.join(names[:20]),MsgBoxYes | MsgBoxNo,MsgBoxNo)
        if answer!=MsgBoxYes:
            return False
        self._launch_transform_task(items,None)
        return True

    def _on_transform_finished(self,task):
        if self._active_transform_task is not task or getattr(task,'_workspace_receipt_delivered',False):
            return
        task._workspace_receipt_delivered = True
        self.progress_bar.hide()
        self._active_transform_task=None
        self._set_transform_enabled(True)
        self.set_active_task('')
        result=copy.deepcopy(getattr(task,'result_summary',{}) or {})
        cancelled=task.isCanceled() or result.get('status') in ('cancelled','canceled')
        status='cancelled' if cancelled else result.get('status', 'success' if task.success_count and not task.fail_count else 'failed')
        labels={'success':'Calcul terminé','partial':'Calcul partiel','failed':'Calcul échoué','cancelled':'Calcul annulé'}
        message=labels.get(status,status)
        if status=='success':
            message+=f' · {len(task.created_layers)} couches produites'
        self.workspace_message.setText(message)
        self.status_label.setText(message)
        receipt={'at':datetime.now(timezone.utc).isoformat(),'operation':'Transformation','status':status,'recipes':[name for item in task.items for name in item.get('table_names',[])],'plan':copy.deepcopy(self._current_execution_plan),'result':result,'outputs':[layer.name() for layer in task.created_layers] if not cancelled else [],'errors':list(task.errors)}
        self._run_history.append(receipt)
        self._render_history()
        self._persist_receipts()
        self.log_message(message,'Success' if status=='success' else 'Warning')
        if status=='success':
            self._result_layers = list(task.created_layers)
            if hasattr(self, 'delivery_panel'):
                self.delivery_panel.set_results(self._result_layers)
            self._show_workspace_editor()
            self.stage_tabs.setCurrentIndex(4)
            self.workspace_message.setText(message + '. Votre source est conservée. Choisissez comment utiliser ou livrer le résultat.')
            for layer in task.created_layers:
                self.transformation_requested.emit(layer.name())
            if self._pending_delivery and len(task.created_layers) == 1:
                self._replay_file_delivery(task.created_layers[0], self._pending_delivery)
        self._pending_delivery = None
        self._update_recipe_status()

    def _launch_transform_task(self, items, target_crs, table_filter=None):
        self._result_layers = []
        if hasattr(self, 'delivery_panel'):
            self.delivery_panel.set_results([])
        self._current_execution_plan = []
        for item in items:
            for name in item.get('table_names', []):
                recipe = self.config_manager.get_table_config(name) or {}
                self._current_execution_plan.append({'name':name,'recipe_id':recipe.get('recipe_id'),'recipe_version':recipe.get('recipe_version',1),'source_id':item.get('filename'),'fingerprint':self._state_fingerprint(recipe)})
        result = super()._launch_transform_task(items, target_crs, table_filter)
        self._update_primary_action()
        return result

    def _refresh_destination_label(self):
        if hasattr(self, '_destination_widget'):
            self._destination_widget.setVisible(bool(self._recipe_destination))
            self._destination_label.setVisible(bool(self._recipe_destination))
        if not hasattr(self, 'recipe_destination_label'):
            return
        destination = self._recipe_destination
        enabled = destination.get('kind') == 'file' and bool(destination.get('path')) and not destination.get('selected_only')
        self.replay_destination_cb.blockSignals(True)
        self.replay_destination_cb.setEnabled(enabled)
        self.replay_destination_cb.setChecked(bool(enabled and destination.get('replay')))
        self.replay_destination_cb.blockSignals(False)
        if destination.get('kind') == 'file':
            self.recipe_destination_label.setText(str(destination.get('format','Fichier'))+' · '+Path(destination.get('path','')).name)
            self.recipe_destination_label.setToolTip(destination.get('path',''))
        elif destination.get('kind') == 'postgresql':
            self.recipe_destination_label.setText('PostgreSQL · plan enregistré ; confirmation avant chaque publication')
        else:
            self.recipe_destination_label.setText('Aucune destination enregistrée : le calcul produit une couche QGIS.')

    def _on_destination_replay_changed(self, checked):
        self._recipe_destination['replay'] = bool(checked)
        self._on_recipe_edited()

    def _on_file_export_requested(self, request):
        layers = request.get('layers', [])
        paths = request.get('destinations', [])
        if self._loaded_recipe_name in layers and len(layers) == len(paths) == 1:
            self._recipe_destination = {'kind':'file','path':paths[0],'format':request.get('format'),'encoding':self.export_widget.get_selected_encoding(),'selected_only':bool(request.get('selected_only')),'replay':self.replay_destination_cb.isChecked()}
            self._destination_error = False
            self._refresh_destination_label()
            self._on_recipe_edited()

    def _on_file_export_finished(self, result):
        receipt = {'at':datetime.now(timezone.utc).isoformat(),'operation':'Export fichier','status':result.get('status','failed'),'recipes':result.get('layers',[]),'result':copy.deepcopy(result),'outputs':result.get('outputs',[]),'errors':result.get('errors',[])}
        self._run_history.append(receipt)
        self._render_history()
        self._persist_receipts()
        self.workspace_message.setText('Livraison fichier : '+{'success':'écriture vérifiée','failed':'échec','cancelled':'annulée'}.get(result.get('status'),result.get('status','inconnue')))

    def _on_publication_finished(self, result):
        plan = result.get('plan', [])
        receipt = {'at':datetime.now(timezone.utc).isoformat(),'operation':'PostgreSQL','status':result.get('status','failed'),'recipes':[row.get('layer','') for row in plan],'result':copy.deepcopy(result),'outputs':[row.get('schema','')+'.'+row.get('table','') for row in plan] if result.get('status') == 'success' else [],'errors':result.get('errors',[])}
        self._run_history.append(receipt)
        self._render_history()
        self._persist_receipts()
        if self._loaded_recipe_name in receipt['recipes']:
            self._recipe_destination = {'kind':'postgresql','targets':[{'schema':row.get('schema'),'table':row.get('table')} for row in plan],'replay':False}
            self._refresh_destination_label()
            self._on_recipe_edited()

    def _replay_file_delivery(self, layer, destination):
        exporter = getattr(self, 'export_widget', None)
        if exporter is None or destination.get('kind') != 'file' or destination.get('selected_only'):
            self.workspace_message.setText('Calcul terminé. Vérifier la destination dans Livraison fichier avant de publier.')
            return False
        batch = getattr(exporter, '_export_batch', None)
        if batch is not None and not batch.closed:
            self.workspace_message.setText('Un export est déjà en cours. La couche calculée est disponible dans QGIS.')
            return False
        if hasattr(self, 'delivery_panel'):
            self.main_tabs.setCurrentIndex(1)
            return self.delivery_panel.replay(layer, destination)
        for index in range(exporter.format_combo.count()):
            format_value = exporter.format_combo.itemData(index)
            if getattr(format_value, 'value', None) == destination.get('format'):
                exporter.format_combo.setCurrentIndex(index)
                break
        else:
            self.workspace_message.setText('Format enregistré indisponible : choisir une destination dans Livraison fichier.')
            return False
        encoding_index = exporter.encoding_combo.findData(destination.get('encoding','utf-8'))
        if encoding_index >= 0:
            exporter.encoding_combo.setCurrentIndex(encoding_index)
        self.main_tabs.setCurrentIndex(1)
        exporter._start_export_jobs([exporter._export_job(layer,destination['path'])])
        return True

    def _trigger_postgresql_auto_mapping(self,layer_names=None):
        # Preparing data must never initiate publication or a network request.
        return None

    def _cancel_execution(self):
        if self._active_transform_task is not None:
            self._active_transform_task.cancel()
            self.cancel_execution_button.setEnabled(False)
            self.workspace_message.setText('Annulation demandée. Attendre le bilan avant de relancer.')

    def _set_transform_enabled(self, enabled):
        self.transform_selected_btn.setBusy(not enabled)
        for name in ('transform_action', 'batch_action', 'transform_selected_btn', 'transform_all_btn'):
            action = getattr(self, name, None)
            if action is not None:
                action.setEnabled(enabled)
        self.cancel_execution_button.setVisible(not enabled)
        self.cancel_execution_button.setEnabled(not enabled)
        self.save_recipe_button.setEnabled(enabled)
        self.workspace_stack.setEnabled(enabled)
        self.shp_tree.setEnabled(enabled)
        if enabled:
            self._update_primary_action()

    def _on_source_changed(self, source_id):
        if source_id == self._editing_source_id:
            self._last_control = None
            self._workspace_context_key = None
            self.auto_load_qgis_layers()
            self.workspace_message.setText('La source a changé. Recalculer l’aperçu avant de livrer.')
            self._update_recipe_status()

    def _remove_tooltip_filters(self):
        for widget in list(getattr(self, '_tooltip_filtered_widgets', ())):
            if widget is not None and (_sip is None or not _sip.isdeleted(widget)):
                try:
                    widget.removeEventFilter(self)
                except RuntimeError:
                    pass
        if hasattr(self, '_tooltip_filtered_widgets'):
            self._tooltip_filtered_widgets.clear()

    def _apply_workspace_preferences(self):
        if self.interface_settings.show_tooltips:
            self._remove_tooltip_filters()
            return
        self.installEventFilter(self)
        self._tooltip_filtered_widgets.add(self)
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
            self._tooltip_filtered_widgets.add(widget)

    def eventFilter(self, watched, event):
        if event.type() == EventToolTip and not self.interface_settings.show_tooltips:
            return True
        return super().eventFilter(watched, event)

    def show_preferences(self):
        from ..widgets.preferences_dialog import PreferencesDialog
        dialog = PreferencesDialog(self.interface_settings, self)
        if dialog.exec() == DialogAccepted:
            self.interface_settings = dialog.get_settings()
            self.apply_theme()
            self._apply_workspace_preferences()

    def _render_history(self):
        self.history_tree.clear()
        labels={'success':'Réussi','partial':'Partiel','failed':'Échec','cancelled':'Annulé'}
        for receipt in reversed(self._run_history):
            at = datetime.fromisoformat(receipt['at']).astimezone().strftime('%d/%m/%Y %H:%M')
            operation = receipt.get('operation','')+' · '+(', '.join(receipt.get('recipes',[])))
            QTreeWidgetItem(self.history_tree,[at,operation,labels.get(receipt.get('status'),receipt.get('status','')),', '.join(receipt.get('outputs',[])) or '; '.join(receipt.get('errors',[])[:2])])

    def _persist_receipts(self):
        path=Path(self.config_manager.plugin_dir)/'execution_history.json'
        try:
            import os
            import tempfile
            handle,name=tempfile.mkstemp(prefix='.history-',suffix='.json',dir=str(path.parent))
            with os.fdopen(handle,'w',encoding='utf-8') as stream:
                json.dump(self._run_history[-100:],stream,ensure_ascii=False,indent=2,default=str)
            os.replace(name,path)
        except OSError as exc:
            self.log_message('Historique non enregistré : '+str(exc),'Warning')

    def export_execution_receipt(self):
        if not self._run_history:
            self.workspace_message.setText('Aucune exécution à exporter dans cette session.')
            return
        path,_=QFileDialog.getSaveFileName(self,'Exporter le compte rendu','compte-rendu-transformer.json','JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(self._run_history,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            except OSError:
                QMessageBox.warning(self,'Compte rendu non exporté','Le compte rendu reste dans Exécutions. Vérifier le dossier de destination puis réessayer.')

    def build_anonymized_diagnostic(self):
        from qgis.PyQt.QtCore import QT_VERSION_STR
        operations = []
        for receipt in self._run_history:
            result = receipt.get('result') or {}
            if not isinstance(result,dict):
                result = {}
            status = receipt.get('status')
            status = status if status in {'success','failed','partial','cancelled','canceled'} else 'unknown'
            operation = receipt.get('operation')
            operation = operation if operation in {'Transformation','Export fichier','PostgreSQL'} else 'Opération'
            row = {'operation':operation,'status':status,'recipe_count':len(receipt.get('recipes',[])),'output_count':len(receipt.get('outputs',[])),'error_count':len(receipt.get('errors',[]))}
            for key in ('source_count','produced_count','rejected_count','total_inserted','features'):
                value = result.get(key)
                if isinstance(value,int) and not isinstance(value,bool):
                    row[key] = value
            operations.append(row)
        return {'schema_version':1,'product':'Transformer','version':'3.3.0','qgis':Qgis.QGIS_VERSION,'qt':QT_VERSION_STR,'operations':operations,'privacy':'Noms, valeurs, expressions, messages libres et chemins exclus.'}

    def export_anonymized_diagnostic(self):
        path,_ = QFileDialog.getSaveFileName(self,'Exporter le diagnostic anonymisé','diagnostic-transformer.json','JSON (*.json)')
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self.build_anonymized_diagnostic(),ensure_ascii=False,indent=2),encoding='utf-8')
            self.workspace_message.setText('Diagnostic exporté sans noms, valeurs, expressions ou chemins métier.')
        except OSError:
            QMessageBox.warning(self,'Diagnostic non exporté','Vérifier le dossier et ses droits puis réessayer.')

    def new_configuration(self):
        if not self._confirm_departure():
            return
        self.main_tabs.setCurrentIndex(0)
        self._show_workspace_editor()
        if self._editing_source_id in self.loaded_shapefiles:
            self._banner_dismissed_sources.discard(self._editing_source_id)
            self._auto_populate_default_config(self._editing_source_id)
            self._saved_state=self._recipe_state()
            self._update_recipe_status()
            self._refresh_context_banner()
        else:
            self.workspace_message.setText('Choisir une couche QGIS à gauche pour créer sa recette.')
            self.shp_tree.setFocus()

    def duplicate_current_configuration(self):
        if not self._confirm_departure():
            return
        current=self._recipe_state()
        name,ok=QInputDialog.getText(self,'Dupliquer la recette','Nom de la copie',text=current['table_name']+'_copie')
        if ok and name.strip():
            self._apply_table_config(name.strip(),current,as_draft=True)
            self._force_dirty=True
            self.save_current_table_config()

    def remove_selected_shapefile(self):
        data=self._selected_data()
        name=data.get('table_name')
        if not name:
            self.workspace_message.setText('Les couches restent gérées dans QGIS. Sélectionner une recette pour la supprimer.')
            return
        if not self._confirm_departure():
            return
        answer=QMessageBox.question(self,'Supprimer une recette',f'Supprimer « {name} » de la bibliothèque ? Les couches QGIS seront conservées.',MsgBoxYes | MsgBoxNo,MsgBoxNo)
        if answer==MsgBoxYes:
            before=copy.deepcopy(self.config_manager.config_data)
            self.config_manager.remove_table_config(name)
            if not self.config_manager.save_config():
                self.config_manager.config_data=before
                return
            self._loaded_recipe_name=None
            self.refresh_shapefile_list()

    def rebind_recipe(self):
        if not self._confirm_departure():
            return
        sources=list(self.loaded_shapefiles.items())
        if not sources:
            self.workspace_message.setText('Ajouter une couche vectorielle au projet QGIS puis actualiser.')
            return
        labels=[f"{info['display_name']} · {info['crs']} · {key[-8:]}" for key,info in sources]
        chosen,ok=QInputDialog.getItem(self,'Relier une livraison','Couche utilisée comme nouvelle entrée',labels,0,False)
        if not ok:
            return
        source_id,info=sources[labels.index(chosen)]
        state=self._recipe_state()
        referenced=set()
        expressions=list(state['calculated_fields'].values())+[state['geometry_expression']]
        if state['filter'].get('enabled'):
            expressions.append(state['filter'].get('expression',''))
        for text in expressions:
            referenced.update(QgsExpression(text).referencedColumns())
        missing=referenced-set(info['layer'].fields().names())-{'#!allattributes!#'}
        if missing:
            QMessageBox.warning(self,'Schéma de livraison différent','Champs requis absents : '+', '.join(sorted(missing))+'.\nAdapter les règles ou choisir une autre livraison.')
            return
        expected={row['name']:row.get('type','') for row in state.get('source_schema',[]) if isinstance(row,dict) and row.get('name')}
        actual={field.name():field.typeName() for field in info['layer'].fields()}
        changed=[f'{name} : {expected[name]} vers {actual[name]}' for name in expected.keys() & actual.keys() if expected[name].casefold()!=actual[name].casefold()]
        absent=sorted(expected.keys()-actual.keys())
        added=sorted(actual.keys()-expected.keys())
        differences=changed+(['Champs non utilisés absents : '+', '.join(absent)] if absent else [])+(['Nouveaux champs : '+', '.join(added)] if added else [])
        if differences:
            answer=QMessageBox.question(self,'Schéma de livraison différent','\n'.join(differences[:12])+'\n\nRelier cette livraison et conserver les règles ? Le contrôle sera à recalculer.',MsgBoxYes | MsgBoxNo,MsgBoxNo)
            if answer!=MsgBoxYes:
                return
        original=self._saved_state
        name=self._loaded_recipe_name
        state['source_id']=source_id
        state['source_file']=info['display_name']
        state['source_schema']=[{'name':field.name(),'type':field.typeName()} for field in info['layer'].fields()]
        self._editing_source_id=source_id
        self._apply_table_config(state['table_name'],state,as_draft=name is None)
        self._saved_state=original
        self._loaded_recipe_name=name
        self._on_recipe_edited()
        self.workspace_message.setText('Nouvelle entrée reliée au brouillon. Vérifier le schéma et enregistrer la recette.')

    def open_configuration(self):
        if not self._confirm_departure():
            return
        path,_=QFileDialog.getOpenFileName(self,'Importer des recettes','','JSON (*.json)')
        if not path:
            return
        try:
            document=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            for name,recipe in document.get('tables',{}).items():
                self._validate_recipe_candidate({**recipe,'table_name':name},imported=True)
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            QMessageBox.warning(self,'Bibliothèque invalide',str(exc))
            return
        preview=self.config_manager.preview_import_config(path)
        if not preview.get('valid'):
            QMessageBox.warning(self,'Bibliothèque invalide','\n'.join(preview.get('errors',[])))
            return
        policy='reject'
        conflicts=preview.get('conflicts',[])
        if conflicts:
            choice,ok=QInputDialog.getItem(self,'Recettes homonymes',f'{len(conflicts)} recettes existent déjà. Choisir le traitement des conflits.',['Conserver les recettes existantes','Remplacer les recettes homonymes'],0,False)
            if not ok:
                return
            policy='keep' if choice.startswith('Conserver') else 'replace'
        if self.config_manager.import_config(path,conflict_policy=policy):
            current=self.config_manager.get_table_config(self._loaded_recipe_name) if self._loaded_recipe_name else None
            if current:
                self._editing_source_id=self._find_source_for_config(current)
                self._apply_table_config(self._loaded_recipe_name,current)
            self.refresh_shapefile_list()
            self.workspace_message.setText('Recettes importées et enregistrées. Relier les entrées absentes pour les rejouer.')
        else:
            QMessageBox.warning(self,'Import non enregistré','La bibliothèque actuelle est conservée. Vérifier le fichier et les droits du dossier.')

    def save_configuration(self):
        if not self._confirm_departure():
            return
        path,_=QFileDialog.getSaveFileName(self,'Exporter les recettes','recettes-transformer.json','JSON (*.json)')
        if path and not self.config_manager.export_config(path):
            QMessageBox.warning(self,'Export impossible','Vérifier les droits du dossier de destination.')

    def export_current_recipe(self):
        """Export only the active saved recipe as a portable JSON for Model Builder."""
        if not self._confirm_departure():
            return
        name = (self._loaded_recipe_name or self.table_name_edit.text().strip())
        if not name or not self.config_manager.has_table_config(name):
            QMessageBox.information(
                self,
                'Recette non enregistree',
                "Enregistrez d'abord la recette courante avant de l'exporter pour le Modeleur.",
            )
            return
        safe_name = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in name).strip('_') or 'recette'
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Exporter cette recette pour Processing / Modeleur',
            f'{safe_name}.json',
            'JSON (*.json)',
        )
        if not path:
            return
        if self.config_manager.export_single_recipe(name, path):
            self.workspace_message.setText(
                f"Recette '{name}' exportee vers {path} (utilisable dans transformer:apply_recipe)."
            )
        else:
            detail = self.config_manager.last_export_error or "Verifiez les droits du dossier."
            QMessageBox.warning(
                self,
                'Export impossible',
                f"Impossible d'exporter la recette '{name}' :\n{detail}",
            )

    def load_table_config_by_name(self,table_name):
        config=self.config_manager.get_table_config(table_name)
        if config and self._confirm_departure():
            self._editing_source_id=self._find_source_for_config(config)
            self._apply_table_config(table_name,config)
            self.refresh_shapefile_list()

    def _clear_all_fields(self):
        self.smart_fields.clear_all_fields()

    def _clear_active_filter(self):
        self.smart_filter.clear_filter()
        self._on_recipe_edited()

    def _keep_source_crs(self):
        self.target_crs=None
        self._raw_target_crs=None
        self.target_crs_label.setText('Conserver le SCR de la source')
        self._on_recipe_edited()

    def set_target_crs(self,crs_code,crs_name):
        crs=QgsCoordinateReferenceSystem(crs_code)
        if not crs.isValid():
            self.workspace_message.setText('SCR invalide : choisir un code EPSG disponible.')
            return
        self.target_crs=crs
        self._raw_target_crs=crs.authid()
        self.target_crs_label.setText(f'{crs_name} ({crs.authid()})')
        self._on_recipe_edited()

    def update_current_crs(self,*_args):
        layer=self._source_info().get('layer')
        self.current_crs_label.setText(layer.crs().authid() if layer else 'Entrée à relier')

    def get_current_filename(self):
        return self._editing_source_id

    def _is_layer_present_in_qgis(self,filename):
        return filename in self.loaded_shapefiles

    def update_statistics(self):
        if hasattr(self,'stats_label'):
            table_count = len(self.config_manager.config_data.get('tables', {}))
            self.stats_label.setText(f'{len(self.loaded_shapefiles)} couches · {table_count} recettes')

    def on_tab_changed(self,index):
        if hasattr(self,'mode_label'):
            self.mode_label.setText(('Préparation','Livraison fichier','Publication PostgreSQL')[index] if index<3 else '')
        if index==1 and getattr(self,'export_widget',None):
            self.export_widget.refresh_layers()

    def on_layers_removed(self,layer_ids):
        removed_set = set(layer_ids or ())
        for layer_id in removed_set:
            self.loaded_shapefiles.pop(layer_id,None)
        if removed_set and hasattr(self, '_source_signal_connections'):
            # Do not call signal.disconnect() here: layersRemoved fires after
            # C++ QObject destruction, which already disconnected Qt signals
            # and left the bound signal wrapper pointing to freed C++ memory.
            self._source_signal_connections = [
                entry for entry in self._source_signal_connections
                if entry[0] not in removed_set
            ]
        self.refresh_shapefile_list()
        if self._editing_source_id in removed_set:
            self.recipe_source_label.setText('Entrée retirée du projet. La recette est conservée ; relier une autre livraison.')
        self._update_recipe_status()

    def _detach_layer_widgets(self, layer_id=None):
        """Release C++ QgsVectorLayer pointers from child widgets before layer destruction."""
        expr = getattr(self, 'advanced_expression', None)
        if expr is not None:
            current = getattr(expr, 'layer', None)
            if layer_id is None or (current is not None and current.id() == layer_id):
                try:
                    expr.set_layer(None)
                except (RuntimeError, AttributeError):
                    pass
        flt = getattr(self, 'smart_filter', None)
        if flt is not None:
            current = getattr(flt, 'layer', None)
            if layer_id is None or (current is not None and current.id() == layer_id):
                flt.layer = None
        flds = getattr(self, 'smart_fields', None)
        if flds is not None:
            current = getattr(flds, 'current_layer', None)
            if layer_id is None or (current is not None and current.id() == layer_id):
                flds.current_layer = None

    def on_layer_will_be_removed(self, layer_id):
        self._disconnect_active_source_signals(layer_id)
        self._detach_layer_widgets(layer_id)
        return None

    def on_project_cleared(self):
        self._detach_layer_widgets(None)
        self.loaded_shapefiles.clear()
        self.refresh_shapefile_list()
        self.recipe_source_label.setText('Projet vidé. Les recettes restent dans la bibliothèque.')
        self._update_recipe_status()

    def shutdown_resources(self):
        """Force-cancel active tasks, release PostgreSQL pools and detach signals/loggers on plugin unload."""
        self._force_shutdown = True
        exporter = getattr(self, 'export_widget', None)
        batch = getattr(exporter, '_export_batch', None)
        if batch is not None and not batch.closed:
            try:
                exporter.cancel_export()
            except Exception as exc:
                QgsApplication.messageLog().logMessage(f"Export cancel on shutdown warning: {exc}", "Transformer", MsgWarning)
        pg_widget = getattr(self, 'postgresql_widget', None)
        mapping = getattr(pg_widget, 'mapping_widget', None)
        config_w = getattr(pg_widget, 'config_widget', None)
        for owner, attr in (
            (mapping, '_active_export_task'),
            (mapping, '_active_compat_task'),
            (mapping, '_active_schema_task'),
            (mapping, '_active_table_task'),
            (config_w, '_active_conn_task'),
            (self, '_active_transform_task'),
        ):
            task = getattr(owner, attr, None) if owner is not None else None
            if task is not None and hasattr(task, 'cancel'):
                try:
                    task.cancel()
                except Exception as exc:
                    QgsApplication.messageLog().logMessage(f"Task cancel on shutdown warning: {exc}", "Transformer", MsgWarning)
        self._teardown_workspace_resources()

    def _teardown_workspace_resources(self):
        self._disconnect_active_source_signals()
        self._remove_tooltip_filters()
        self._detach_layer_widgets(None)
        for timer_attr in ('_project_sync_timer', '_workspace_view_timer', '_show_sync_timer', '_show_dock_timer'):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
        if getattr(self, 'loaded_shapefiles', None) is not None:
            self.loaded_shapefiles.clear()
        if getattr(self, '_result_layers', None) is not None:
            self._result_layers.clear()
        log_mon = getattr(self, 'log_monitor', None)
        if log_mon is not None and hasattr(log_mon, 'teardown'):
            log_mon.teardown()
        exporter = getattr(self, 'export_widget', None)
        if exporter is not None:
            if hasattr(exporter, 'teardown_resources'):
                exporter.teardown_resources()
            elif hasattr(exporter, 'teardown_qgis_signals'):
                exporter.teardown_qgis_signals()
        pg_widget = getattr(self, 'postgresql_widget', None)
        if pg_widget is not None:
            if hasattr(pg_widget, 'teardown_resources'):
                pg_widget.teardown_resources()
            else:
                pg_mapping = getattr(pg_widget, 'mapping_widget', None)
                if pg_mapping is not None and hasattr(pg_mapping, 'teardown_qgis_signals'):
                    pg_mapping.teardown_qgis_signals()
        doc_dock = getattr(self, 'doc_dock', None)
        if doc_dock is not None:
            viewer = getattr(doc_dock, '_doc_viewer', None)
            if viewer is not None and (_sip is None or not _sip.isdeleted(viewer)):
                try:
                    if hasattr(viewer, 'setUrl'):
                        from qgis.PyQt.QtCore import QUrl
                        viewer.setUrl(QUrl('about:blank'))
                    viewer.deleteLater()
                except RuntimeError:
                    pass
                doc_dock._doc_viewer = None
                doc_dock._html_loaded = False
        fluent_ctx = getattr(self, '_fluent_context', None)
        if fluent_ctx is not None and hasattr(fluent_ctx, '_detach'):
            fluent_ctx._detach()
        project = QgsProject.instance()
        for name, slot in [('layersAdded', self.on_layers_added), ('layersRemoved', self.on_layers_removed), ('layerWillBeRemoved', self.on_layer_will_be_removed), ('readProject', self.on_project_read), ('cleared', self.on_project_cleared)]:
            try:
                getattr(project, name).disconnect(slot)
            except (TypeError, RuntimeError, AttributeError):
                pass
        try:
            from ..pg.connection_task import PgConnectionPoolManager
            PgConnectionPoolManager.close_all()
        except Exception as exc:
            QgsApplication.messageLog().logMessage(f"Pool close on teardown warning: {exc}", "Transformer", MsgWarning)
        try:
            from ..shared.logger import logger as _plugin_logger
            _plugin_logger.set_activity_log_widget(None)
        except Exception as exc:
            QgsApplication.messageLog().logMessage(f"Logger detach on teardown warning: {exc}", "Transformer", MsgWarning)

    def closeEvent(self,event):
        if not getattr(self, '_force_shutdown', False):
            exporter = getattr(self, 'export_widget', None)
            batch = getattr(exporter, '_export_batch', None)
            if batch is not None and not batch.closed:
                answer = QMessageBox.question(self,'Livraison en cours','Annuler la livraison ? La fenêtre restera ouverte jusqu\'au bilan de l\'annulation.',MsgBoxYes | MsgBoxNo,MsgBoxNo)
                if answer == MsgBoxYes:
                    exporter.cancel_export()
                event.ignore()
                return
            mapping = getattr(getattr(self,'postgresql_widget',None),'mapping_widget',None)
            pg_task = getattr(mapping,'_active_export_task',None)
            if pg_task is not None:
                answer = QMessageBox.question(self,'Publication en cours','Demander l\'annulation de la publication ? La fenêtre restera ouverte jusqu\'au bilan.',MsgBoxYes | MsgBoxNo,MsgBoxNo)
                if answer == MsgBoxYes:
                    pg_task.cancel()
                event.ignore()
                return
            if self._active_transform_task is not None:
                answer=QMessageBox.question(self,'Exécution en cours','Annuler l\'exécution ? La fenêtre restera ouverte jusqu\'à la fin de son annulation.',MsgBoxYes | MsgBoxNo,MsgBoxNo)
                if answer==MsgBoxYes:
                    self._active_transform_task.cancel()
                event.ignore()
                return
            if not self._confirm_departure():
                event.ignore()
                return
        self.save_window_state()
        self._teardown_workspace_resources()
        self.window_closed.emit()
        event.accept()
