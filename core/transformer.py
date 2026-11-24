# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Vector file transformer using QGIS calculated fields with filter support
Fixed filter problem
"""

import os
import copy
from datetime import datetime
from typing import Callable, Dict, List, Any, Optional, Tuple, Set

from qgis.PyQt.QtCore import QThread
from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsFeature, QgsField, QgsFields,
    QgsFeatureSink, QgsGeometry, QgsExpression, QgsExpressionContext,
    QgsExpressionContextScope, QgsExpressionContextUtils,
    QgsProject, QgsCoordinateReferenceSystem, QgsFeatureRequest,
    QgsCoordinateTransform, QgsTask, QgsWkbTypes, QgsVariantUtils, Qgis,
)
from .field_types import (
    create_field_from_template,
    detect_field_type_from_expression,
    create_field_from_definition,
    make_field_converter,
)
from ..shared.constants import VECTOR_EXTENSIONS
from ..shared.expression_utils import validate_expression_syntax, evaluate_expression
from ..shared.logger import logger


class _MemoryProviderSink:
    """Adapt a memory QgsVectorLayer dataProvider to the QgsFeatureSink batch contract."""

    def __init__(self, layer: QgsVectorLayer):
        self._layer = layer
        self._provider = layer.dataProvider()
        self._last_error = ""

    def addFeatures(self, features: List[QgsFeature], _flags=None) -> bool:
        success, added = self._provider.addFeatures(features)
        if not success or len(added) != len(features):
            self._last_error = "Insertion incomplète : la sortie entière est rejetée."
            return False
        return True

    def lastError(self) -> str:
        return self._last_error


class SimpleTransformer:
    """Transforms vector sources using QGIS calculated fields with filter support."""

    _WORKER_BLOCKED_FUNCTIONS = frozenset({
        "aggregate", "relation_aggregate", "get_feature", "get_feature_by_id",
        "layer_property", "is_layer_visible", "is_selected", "num_selected",
        "raster_value", "raster_statistic", "represent_value", "project_color",
        "project_color_object", "eval", "current_value", "form_variable",
        "count", "count_distinct", "count_missing", "minimum", "maximum", "sum",
        "mean", "median", "stdev", "stdevsample", "range", "minority", "majority",
        "q1", "q3", "iqr", "min_length", "max_length", "concatenate",
        "concatenate_unique", "collect", "array_agg", "selected_features",
        "selected_feature_ids", "layers", "layers_by_name", "item_variables",
    })

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._current_task: Optional[QgsTask] = None  # Set by TransformTask for mid-item cancellation
        self._progress_feedback = None  # Set by TransformTask for intra-layer progress
        self._prebuilt_scopes: Optional[list] = None  # Set by TransformTask for thread-safe context
        self._logged_field_errors: Set[str] = set()  # Dedup error logs per field per transformation
        self.last_result_summary = {}
        self.result_summaries = []
        self._transform_context = None
        self.batch_size = 1000

    @staticmethod
    def _source_is_valid(source) -> bool:
        if source is None:
            return False
        if hasattr(source, "isValid"):
            return bool(source.isValid())
        return hasattr(source, "fields") and hasattr(source, "getFeatures")

    @staticmethod
    def _source_crs(source) -> QgsCoordinateReferenceSystem:
        if hasattr(source, "sourceCrs"):
            return source.sourceCrs()
        return source.crs()

    @staticmethod
    def _source_name(source) -> str:
        if hasattr(source, "sourceName"):
            return source.sourceName()
        return source.name() if hasattr(source, "name") else ""

    @staticmethod
    def _source_id(source) -> str:
        if hasattr(source, "id"):
            return source.id()
        return SimpleTransformer._source_name(source)

    @staticmethod
    def _is_off_main_thread() -> bool:
        app = QgsApplication.instance()
        if app is None:
            return False
        return QThread.currentThread() != app.thread()

    def _check_canceled(self, feedback=None):
        if self._current_task is not None and self._current_task.isCanceled():
            raise InterruptedError("Transformation annulée ; aucune sortie partielle publiée.")
        if feedback is not None and feedback.isCanceled():
            raise InterruptedError("Transformation annulée ; aucune sortie partielle publiée.")

    def _validated_expression(
        self,
        text,
        source_layer,
        context: Optional[QgsExpressionContext] = None,
        worker_thread: Optional[bool] = None,
    ):
        valid, error, expression = validate_expression_syntax(text)
        if not valid:
            raise ValueError(f"Expression invalide : {error}")
        in_worker = (
            bool(worker_thread)
            if worker_thread is not None
            else (self._current_task is not None or self._is_off_main_thread())
        )
        if in_worker:
            # These functions resolve live map-layer/project QObjects. A copied
            # expression scope does not make those lookups safe in a worker.
            functions = {name.lower() for name in expression.referencedFunctions()}
            unsafe = {
                name for name in functions
                if name in self._WORKER_BLOCKED_FUNCTIONS
                or name.startswith("overlay_")
                or name.startswith("get_feature")
            }
            builtin = {name.lower() for name in QgsExpression.BuiltinFunctions()}
            unsafe.update(functions - builtin)
            if "layer" in {name.lower() for name in expression.referencedVariables()}:
                unsafe.add("@layer")
            if unsafe:
                raise ValueError(
                    "Expression incompatible avec une tâche en arrière-plan ("
                    + ", ".join(sorted(unsafe))
                    + "). Préparez ces valeurs dans une couche QGIS avant de lancer la recette."
                )
        names = set(source_layer.fields().names())
        missing = set(expression.referencedColumns()) - names - {"#!allattributes!#"}
        if missing:
            raise ValueError("Champs source absents : " + ", ".join(sorted(missing)))
        prep_context = context if context is not None else self._build_expression_context(
            source_layer, worker_thread=in_worker,
        )
        if not expression.prepare(prep_context):
            raise ValueError(expression.evalErrorString() or "Expression impossible à préparer.")
        return expression

    def get_field_type_from_expression_result(
        self,
        expression_text: str,
        source_layer: QgsVectorLayer,
        sample_features=None,
        context=None,
        prepared_expression=None,
    ) -> QgsField:
        """Determine field type by evaluating expression on sample data"""
        return detect_field_type_from_expression(
            expression_text,
            source_layer,
            sample_features=sample_features,
            context=context,
            prepared_expression=prepared_expression,
        )

    def test_filter_expression(self, filter_expression: str, source_layer: QgsVectorLayer, max_features: Optional[int] = None) -> Tuple[bool, str, int]:
        """Test filter expression and return validity, message, and filtered count"""
        try:
            if not source_layer or not source_layer.isValid():
                return False, "Source indisponible.", 0
            expression = self._validated_expression(filter_expression, source_layer)
            context = self._build_expression_context(source_layer)
            request = QgsFeatureRequest()
            if max_features is not None:
                request.setLimit(max(0, int(max_features)))
            matching = tested = 0
            for feature in source_layer.getFeatures(request):
                self._check_canceled()
                context.setFeature(feature)
                result = expression.evaluate(context)
                if expression.hasEvalError():
                    return False, f"Erreur du filtre à l'entité {feature.id()} : {expression.evalErrorString()}", 0
                matching += int(not QgsVariantUtils.isNull(result) and bool(result))
                tested += 1
            scope = f"Échantillon de {tested} entités" if max_features is not None else f"{tested} entités contrôlées"
            return True, f"{scope} ; {matching} retenues.", matching

        except Exception as e:
            return False, f"Exception: {str(e)}", 0

    def apply_filter_to_layer(self, source_layer: QgsVectorLayer, filter_expression: str) -> QgsFeatureRequest:
        """Apply filter expression to create a feature request"""
        try:
            request = QgsFeatureRequest()

            if filter_expression and filter_expression.strip():
                # Clean the expression
                cleaned_expression = filter_expression.strip()

                # Test syntax first
                is_valid, error_msg, expression = validate_expression_syntax(cleaned_expression)

                if not is_valid:
                    logger.warning(f"Filter syntax error: {error_msg}", "transformer", "WARNING")
                    raise ValueError(f"Filtre invalide : {error_msg}")
                self._validated_expression(cleaned_expression, source_layer)

                # Apply the filter
                request.setFilterExpression(cleaned_expression)

                logger.info(f"Filter applied: {cleaned_expression[:50]}{'...' if len(cleaned_expression) > 50 else ''}", "transformer", "INFO")

            return request

        except Exception as e:
            logger.warning(f"Filter application error: {str(e)}", "transformer", "WARNING")
            raise ValueError(f"Le filtre n'a pas été appliqué : {e}") from e

    def create_feature_request_with_filter(self, source_layer: QgsVectorLayer, filter_expression: Optional[str] = None) -> QgsFeatureRequest:
        """Create a QgsFeatureRequest with optional filter expression"""
        if filter_expression and filter_expression.strip():
            return self.apply_filter_to_layer(source_layer, filter_expression)
        else:
            return QgsFeatureRequest()  # Return request without filter

    def count_filtered_features(self, source_layer: QgsVectorLayer, filter_expression: str) -> Tuple[int, int]:
        """Count total and filtered features incrementally (no full list in RAM)."""
        total_count = source_layer.featureCount()

        if not filter_expression or not filter_expression.strip():
            return total_count, total_count

        valid, message, count = self.test_filter_expression(filter_expression, source_layer)
        if not valid:
            raise ValueError(message)
        return total_count, count

    def _detect_expression_wkb_type(
        self,
        source_layer,
        geometry_expression: str,
        sample_features=None,
        context=None,
        prepared_expression=None,
        feedback=None,
        worker_thread: Optional[bool] = None,
    ):
        """Detect output WKB type across up to 50 sample features, promoting Multi/Z/M."""
        context = context or self._build_expression_context(source_layer, worker_thread=bool(worker_thread))
        expression = prepared_expression or self._validated_expression(
            geometry_expression, source_layer, context=context, worker_thread=worker_thread,
        )
        features_iter = (
            sample_features
            if sample_features is not None
            else source_layer.getFeatures(QgsFeatureRequest().setLimit(50))
        )
        detected_types = []
        for test_feature in features_iter:
            self._check_canceled(feedback)
            context.setFeature(test_feature)
            result = expression.evaluate(context)
            if expression.hasEvalError():
                raise ValueError(expression.evalErrorString())
            if isinstance(result, QgsGeometry) and not result.isNull():
                detected_types.append(result.wkbType())
        if not detected_types:
            return None
        first_family = QgsWkbTypes.geometryType(detected_types[0])
        for wkb in detected_types[1:]:
            if QgsWkbTypes.geometryType(wkb) != first_family:
                raise ValueError(
                    "L'expression geometrique produit des familles de geometries incompatibles dans l'echantillon."
                )
        resolved = detected_types[0]
        if any(QgsWkbTypes.isMultiType(wkb) for wkb in detected_types):
            resolved = QgsWkbTypes.multiType(resolved)
        if any(QgsWkbTypes.hasZ(wkb) for wkb in detected_types):
            resolved = QgsWkbTypes.addZ(resolved)
        if any(QgsWkbTypes.hasM(wkb) for wkb in detected_types):
            resolved = QgsWkbTypes.addM(resolved)
        return resolved

    def _detect_expression_geometry_type(
        self,
        source_layer: QgsVectorLayer,
        geometry_expression: str,
        sample_features=None,
        context=None,
        prepared_expression=None,
    ) -> Optional[str]:
        """Detect the geometry display name produced by an expression on a sample."""
        try:
            wkb = self._detect_expression_wkb_type(
                source_layer,
                geometry_expression,
                sample_features=sample_features,
                context=context,
                prepared_expression=prepared_expression,
            )
            return QgsWkbTypes.displayString(wkb) if wkb is not None else None
        except InterruptedError:
            raise
        except Exception as e:
            logger.warning(f"Error detecting geometry type: {str(e)}", "transformer", "WARNING")
            return None

    def create_memory_layer_from_shapefile(self, shp_path: str, table_name: str,
                                           calculated_fields: Dict[str, str],
                                           filter_config: Optional[Dict[str, Any]] = None,
                                           target_crs: Optional[QgsCoordinateReferenceSystem] = None,
                                           geometry_expression: Optional[str] = None) -> Optional[QgsVectorLayer]:
        """Create memory layer from vector file with calculated fields and optional filter.

        Delegates to create_memory_layer_from_qgis_layer after loading the file
        as a QgsVectorLayer, ensuring both paths share the same batch-insert
        and geometry-mismatch detection logic.
        """
        try:
            source_layer = QgsVectorLayer(shp_path, "temp_source", "ogr")
            if not source_layer.isValid():
                logger.warning(f"Invalid shapefile: {shp_path}", "transformer", "WARNING")
                return None

            return self.create_memory_layer_from_qgis_layer(
                source_layer, table_name, calculated_fields,
                filter_config, target_crs, geometry_expression,
            )
        except Exception as e:
            logger.critical(f"Erreur de transformation: {str(e)}", "transformer", "CRITICAL")
            return None

    def _build_expression_context(
        self,
        source_layer,
        base_context: Optional[QgsExpressionContext] = None,
        worker_thread: bool = False,
    ) -> QgsExpressionContext:
        """Build an expression context for a QgsVectorLayer, snapshot, or Processing source."""
        if base_context is not None:
            context = QgsExpressionContext(base_context)
            if hasattr(source_layer, "createExpressionContextScope"):
                src_scope = source_layer.createExpressionContextScope()
                if src_scope is not None:
                    if worker_thread:
                        src_scope.removeVariable("layer")
                    context.appendScope(src_scope)
            elif hasattr(source_layer, "expression_scope"):
                context.appendScope(QgsExpressionContextScope(source_layer.expression_scope))
            elif isinstance(source_layer, QgsVectorLayer):
                layer_scope = QgsExpressionContextUtils.layerScope(source_layer)
                if worker_thread:
                    layer_scope.removeVariable("layer")
                context.appendScope(layer_scope)
            context.setFields(source_layer.fields())
            return context

        if hasattr(source_layer, "expression_context"):
            return source_layer.expression_context()

        context = QgsExpressionContext()
        if self._prebuilt_scopes:
            for scope in self._prebuilt_scopes:
                context.appendScope(QgsExpressionContextScope(scope))
            if hasattr(source_layer, "createExpressionContextScope"):
                src_scope = source_layer.createExpressionContextScope()
                if src_scope is not None:
                    if worker_thread:
                        src_scope.removeVariable("layer")
                    context.appendScope(src_scope)
            elif isinstance(source_layer, QgsVectorLayer):
                layer_scope = QgsExpressionContextUtils.layerScope(source_layer)
                if worker_thread:
                    layer_scope.removeVariable("layer")
                context.appendScope(layer_scope)
        elif hasattr(source_layer, "createExpressionContextScope"):
            context.appendScope(QgsExpressionContextUtils.globalScope())
            if not worker_thread:
                project = QgsProject.instance()
                if project is not None:
                    context.appendScope(QgsExpressionContextUtils.projectScope(project))
            src_scope = source_layer.createExpressionContextScope()
            if src_scope is not None:
                if worker_thread:
                    src_scope.removeVariable("layer")
                context.appendScope(src_scope)
        else:
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
        context.setFields(source_layer.fields())
        return context

    def _prepare_field_expressions(
        self,
        calculated_fields: Dict[str, str],
        source_layer,
        context: Optional[QgsExpressionContext] = None,
        worker_thread: Optional[bool] = None,
    ) -> Dict[str, QgsExpression]:
        """Build and prepare QgsExpression objects once for all features."""
        prepared = {}
        for field_name, expression_text in calculated_fields.items():
            try:
                prepared[field_name] = self._validated_expression(
                    expression_text, source_layer, context=context, worker_thread=worker_thread,
                )
            except ValueError as exc:
                raise ValueError(f"Règle du champ {field_name} : {exc}") from exc

        logger.info(
            f"Prepared {len(prepared)} field expressions for layer '{self._source_name(source_layer)}'",
            "transformer", "INFO",
        )
        return prepared

    def _prepare_geometry_expression(
        self,
        geometry_expression: str,
        source_layer,
        context: Optional[QgsExpressionContext] = None,
        worker_thread: Optional[bool] = None,
    ) -> Optional[QgsExpression]:
        """Build and prepare a geometry QgsExpression once."""
        if not geometry_expression or geometry_expression == "$geometry":
            return None
        return self._validated_expression(
            geometry_expression, source_layer, context=context, worker_thread=worker_thread,
        )

    def calculate_fields(
        self,
        source_feature: QgsFeature,
        source_layer: QgsVectorLayer,
        calculated_fields: Dict[str, str],
        prepared_expressions: Optional[Dict[str, QgsExpression]] = None,
        expression_context: Optional[QgsExpressionContext] = None,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Calculate field values using QGIS expressions.

        If prepared_expressions is provided, reuses pre-built QgsExpression
        objects (performance path). Otherwise builds them per-call (legacy).
        """
        calculated_values = {}

        context = expression_context or self._build_expression_context(source_layer)
        context.setFeature(source_feature)

        for field_name, expression_text in calculated_fields.items():
            try:
                if prepared_expressions and field_name in prepared_expressions:
                    expression = prepared_expressions[field_name]
                else:
                    expression = QgsExpression(expression_text)
                    if expression.hasParserError():
                        if strict:
                            raise ValueError(expression.parserErrorString())
                        logger.warning(f"Erreur de syntaxe d'expression '{field_name}': {expression.parserErrorString()}", "transformer", "WARNING")
                        calculated_values[field_name] = None
                        continue

                if expression.hasParserError():
                    if strict:
                        raise ValueError(expression.parserErrorString())
                    calculated_values[field_name] = None
                    continue

                result = expression.evaluate(context)

                if expression.hasEvalError():
                    if strict:
                        raise ValueError(expression.evalErrorString())
                    if field_name not in self._logged_field_errors:
                        logger.warning(f"Erreur d'évaluation d'expression '{field_name}': {expression.evalErrorString()}", "transformer", "WARNING")
                        self._logged_field_errors.add(field_name)
                    calculated_values[field_name] = None
                else:
                    calculated_values[field_name] = result

            except Exception as e:
                if strict:
                    raise ValueError(f"Champ {field_name}, entité {source_feature.id()} : {e}") from e
                if field_name not in self._logged_field_errors:
                    logger.warning(f"Exception de calcul de champ '{field_name}': {str(e)}", "transformer", "WARNING")
                    self._logged_field_errors.add(field_name)
                calculated_values[field_name] = None

        return calculated_values

    def calculate_field_values(self, source_feature: QgsFeature, field_configs: List[Tuple[QgsField, str]], source_layer: QgsVectorLayer) -> Dict[str, Any]:
        """Calculate field values from field configs (compatibility wrapper)"""
        # Convert field_configs to calculated_fields format
        calculated_fields = {}
        for field, expression in field_configs:
            calculated_fields[field.name()] = expression

        # Use existing calculate_fields method
        return self.calculate_fields(source_feature, source_layer, calculated_fields)

    def _transform_to_memory_layers(
        self,
        source_layer: QgsVectorLayer,
        source_name: str,
        target_crs: Optional[QgsCoordinateReferenceSystem] = None,
        table_filter: Optional[List[str]] = None,
    ) -> List[QgsVectorLayer]:
        """Common orchestration for transform_shapefile and transform_qgis_layer.

        Looks up table configs for *source_name*, optionally filters by
        *table_filter*, then calls create_memory_layer_from_qgis_layer for
        each config. Cleans up per-field error dedup flags after each table.
        """
        layers_created = []
        self.result_summaries = []

        try:
            candidates = [source_name, source_layer.name(), source_layer.source(), os.path.basename(source_layer.source())]
            candidates.extend(os.path.splitext(name)[0] for name in list(candidates))
            table_names = []
            for candidate in candidates:
                for name in self.config_manager.get_tables_for_source(candidate, source_id=source_layer.id()):
                    if name not in table_names:
                        table_names.append(name)

            if not table_names:
                logger.warning(f"No configuration found for {source_name}", "transformer", "WARNING")
                self.result_summaries = [{"status": "failed", "source_id": source_layer.id(), "produced_count": 0, "rejected_count": 0, "errors": ["Aucune recette liée à cette source."]}]
                return layers_created

            if table_filter is not None:
                allowed = set(table_filter)
                table_names = [n for n in table_names if n in allowed]
                if not table_names:
                    logger.info(f"No table_config in filter matched source {source_name}", "transformer", "INFO")
                    return layers_created

            for table_name in table_names:
                self._check_canceled()
                config = self.config_manager.get_table_config(table_name)
                if not config:
                    continue

                calculated_fields = config.get("calculated_fields", {})
                if not calculated_fields:
                    logger.warning(f"No calculated fields found for {table_name}", "transformer", "WARNING")
                    continue

                filter_config = config.get("filter", {"enabled": False, "expression": ""})
                geometry_expression = config.get("geometry_expression")
                recipe_crs = target_crs
                if "target_crs" in config:
                    saved_crs = config.get("target_crs")
                    recipe_crs = QgsCoordinateReferenceSystem(saved_crs) if saved_crs else None
                    if recipe_crs is not None and not recipe_crs.isValid():
                        self.last_result_summary = {"recipe": table_name, "status": "failed", "produced_count": 0, "rejected_count": 0, "errors": ["SCR cible de la recette invalide."]}
                        self.result_summaries.append(copy.deepcopy(self.last_result_summary))
                        continue

                layer = self.create_memory_layer_from_qgis_layer(
                    source_layer, table_name, calculated_fields,
                    filter_config, recipe_crs, geometry_expression,
                    field_definitions=config.get("field_definitions", {}),
                )
                self.last_result_summary["recipe_version"] = config.get("recipe_version", 1)
                self.last_result_summary["recipe_id"] = config.get("recipe_id")
                self.result_summaries.append(copy.deepcopy(self.last_result_summary))

                # R9: Clean up error flags after transformation
                for field_name in calculated_fields.keys():
                    self._logged_field_errors.discard(field_name)

                if layer:
                    layers_created.append(layer)
                    logger.info(f"Layer created: {table_name}", "transformer", "INFO")
                else:
                    logger.warning(f"Layer creation failed: {table_name}", "transformer", "WARNING")

            self._check_canceled()
            return layers_created

        except InterruptedError:
            for summary in self.result_summaries:
                summary["published"] = False
            return []
        except Exception as e:
            import traceback
            error_msg = f"Transformation error for {source_name}: {str(e)}"
            stack_trace = traceback.format_exc()
            logger.critical(error_msg, "transformer", "CRITICAL")
            logger.critical(f"Stack trace: {stack_trace}", "transformer", "CRITICAL")
            return layers_created

    def transform_shapefile_to_memory_layers(self, shp_path: str, target_crs: QgsCoordinateReferenceSystem = None,
                                             table_filter: Optional[List[str]] = None) -> List[QgsVectorLayer]:
        """Transform vector file to memory layers based on configuration.

        Args:
            shp_path: source vector file path.
            target_crs: optional reprojection target.
            table_filter: optional list of table_config names; when provided, only those configs
                that both belong to the source AND appear in this list will be applied.
        """
        self.result_summaries = []
        source_layer = QgsVectorLayer(shp_path, "temp_source", "ogr")
        if not source_layer.isValid():
            logger.warning(f"Invalid source file: {shp_path}", "transformer", "WARNING")
            return []

        source_name = os.path.basename(shp_path)
        return self._transform_to_memory_layers(source_layer, source_name, target_crs, table_filter)

    def transform_qgis_layer_to_memory_layers(self, source_layer: QgsVectorLayer, layer_name: str,
                                              target_crs: QgsCoordinateReferenceSystem = None,
                                              table_filter: Optional[List[str]] = None) -> List[QgsVectorLayer]:
        """Transform QGIS layer object to memory layers based on configuration.

        Args:
            source_layer: QGIS layer to consume.
            layer_name: layer name used to look up table_configs in config_manager.
            target_crs: optional reprojection target.
            table_filter: optional list of table_config names; when provided, only those configs
                that both belong to the layer AND appear in this list will be applied.
        """
        self.result_summaries = []
        if not source_layer or not source_layer.isValid():
            logger.warning(f"Invalid QGIS source layer: {layer_name}", "transformer", "WARNING")
            return []

        # Normalize layer name by removing common vector file extension if present
        normalized_layer_name = layer_name
        lower_name = layer_name.lower()
        for ext in VECTOR_EXTENSIONS:
            if lower_name.endswith(ext):
                normalized_layer_name = layer_name[: -len(ext)]
                break

        return self._transform_to_memory_layers(
            source_layer, normalized_layer_name, target_crs, table_filter,
        )

    @staticmethod
    def _build_feature_request(
        source,
        filter_expr: Optional[QgsExpression],
        prepared_fields: Dict[str, QgsExpression],
        prepared_geom: Optional[QgsExpression],
        output_is_spatial: bool,
    ) -> QgsFeatureRequest:
        """Build a tight QgsFeatureRequest fetching only needed columns and geometry."""
        request = QgsFeatureRequest()
        all_exprs = list(prepared_fields.values())
        if filter_expr is not None:
            all_exprs.append(filter_expr)
        if prepared_geom is not None:
            all_exprs.append(prepared_geom)

        needed_cols: Set[str] = set()
        needs_all = False
        for expr in all_exprs:
            cols = set(expr.referencedColumns())
            if "#!allattributes!#" in cols:
                needs_all = True
                break
            needed_cols.update(cols)

        if not needs_all:
            src_fields = source.fields()
            indices = sorted({
                idx for idx in (src_fields.indexFromName(col) for col in needed_cols)
                if idx >= 0
            })
            request.setSubsetOfAttributes(indices)

        needs_geom = (
            (prepared_geom is None and output_is_spatial)
            or any(expr.needsGeometry() for expr in all_exprs)
        )
        if not needs_geom:
            no_geom_flag = getattr(
                getattr(Qgis, "FeatureRequestFlag", QgsFeatureRequest),
                "NoGeometry",
                None,
            )
            if no_geom_flag is not None:
                request.setFlags(no_geom_flag)
        return request

    @staticmethod
    def create_memory_sink_factory(table_name: str):
        """Return a sink_factory producing an in-memory QgsVectorLayer."""

        def _make_memory_sink(fields: QgsFields, wkb_type, dest_crs: QgsCoordinateReferenceSystem):
            geom_name = QgsWkbTypes.displayString(wkb_type)
            layer = QgsVectorLayer(f"{geom_name}?crs={dest_crs.authid()}", table_name, "memory")
            if not layer.isValid():
                raise ValueError("Impossible de créer la couche de sortie.")
            if dest_crs.isValid():
                layer.setCrs(dest_crs)
            provider = layer.dataProvider()
            field_list = [fields.at(i) for i in range(fields.count())]
            if field_list and not provider.addAttributes(field_list):
                raise ValueError("Le schéma de sortie n'a pas pu être créé.")
            layer.updateFields()
            return _MemoryProviderSink(layer), layer

        return _make_memory_sink

    def _collect_sample_features(
        self,
        source,
        filter_expr: Optional[QgsExpression],
        context: QgsExpressionContext,
        feedback=None,
        limit: int = 50,
    ) -> List[QgsFeature]:
        """Collect up to limit matching features (fallback to unfiltered if 0 match)."""
        if filter_expr is None:
            return list(source.getFeatures(QgsFeatureRequest().setLimit(limit)))

        matched: List[QgsFeature] = []
        fallback: List[QgsFeature] = []
        for feature in source.getFeatures():
            self._check_canceled(feedback)
            if len(fallback) < limit:
                fallback.append(feature)
            context.setFeature(feature)
            result = filter_expr.evaluate(context)
            if filter_expr.hasEvalError():
                raise ValueError(f"Filtre, entité {feature.id()} : {filter_expr.evalErrorString()}")
            if not QgsVariantUtils.isNull(result) and bool(result):
                matched.append(feature)
                if len(matched) >= limit:
                    break
        return matched if matched else fallback

    def execute_to_sink(
        self,
        source,
        table_name: str,
        calculated_fields: Dict[str, str],
        sink_factory: Callable[[QgsFields, Any, QgsCoordinateReferenceSystem], Tuple[Any, Any]],
        filter_config: Optional[Dict[str, Any]] = None,
        target_crs: Optional[QgsCoordinateReferenceSystem] = None,
        geometry_expression: Optional[str] = None,
        field_definitions: Optional[Dict[str, Any]] = None,
        expression_context: Optional[QgsExpressionContext] = None,
        transform_context=None,
        feedback=None,
        worker_thread: Optional[bool] = None,
        schema_validator: Optional[Callable[[QgsFields, Any, QgsCoordinateReferenceSystem], None]] = None,
        cleanup_on_failure: Optional[Callable[[], None]] = None,
        raise_on_error: bool = True,
    ) -> Tuple[Any, Dict[str, Any]]:
        """Stream a validated recipe from any QGIS feature source into any sink.

        Expressions evaluate on the untouched source feature in source CRS.
        Reprojection applies only to the resulting geometry. Batches stay
        bounded in memory, and schema/preflight checks run before sink creation.
        """
        summary = {
            "recipe": table_name, "status": "running", "started_at": datetime.now().isoformat(),
            "source_count": 0, "read_count": 0, "selected_count": 0,
            "filtered_out_count": 0, "produced_count": 0, "rejected_count": 0,
            "errors": [], "warnings": [], "published": False,
            "geometry_order": "expression_in_source_crs_then_reproject",
        }
        self.last_result_summary = summary
        in_worker = (
            bool(worker_thread)
            if worker_thread is not None
            else (self._current_task is not None or self._is_off_main_thread())
        )
        effective_feedback = feedback if feedback is not None else self._progress_feedback
        sink_created = False
        try:
            self._check_canceled(effective_feedback)
            if not self._source_is_valid(source):
                raise ValueError("core.transformer: couche source indisponible ou invalide.")

            source_crs = self._source_crs(source)
            source_wkb = source.wkbType()
            source_is_spatial = QgsWkbTypes.flatType(source_wkb) not in (
                QgsWkbTypes.Type.NoGeometry, QgsWkbTypes.Type.Unknown,
            )
            source_count = source.featureCount()
            summary["source_count"] = source_count
            summary["source_id"] = self._source_id(source)
            summary["source_name"] = self._source_name(source)
            summary["source_crs"] = source_crs.authid()

            from qgis.core import QgsUnitTypes
            summary["expression_units"] = QgsUnitTypes.toString(source_crs.mapUnits())

            if target_crs is not None and not target_crs.isValid():
                raise ValueError("core.transformer: SCR cible invalide.")
            dest_crs = target_crs if target_crs is not None else source_crs
            summary["target_crs"] = dest_crs.authid()

            if source_crs.isGeographic() and geometry_expression not in (None, "", "$geometry"):
                warning = "L'expression géométrique utilise les unités angulaires du SCR source, avant reprojection."
                summary["warnings"].append(warning)
                if effective_feedback is not None and hasattr(effective_feedback, "pushWarning"):
                    effective_feedback.pushWarning(warning)

            context = self._build_expression_context(
                source, base_context=expression_context, worker_thread=in_worker,
            )

            fc = filter_config or {"enabled": False, "expression": ""}
            filter_expr = None
            if fc.get("enabled", False):
                filter_text = fc.get("expression", "").strip()
                if not filter_text:
                    raise ValueError("Le filtre est actif mais son expression est vide.")
                try:
                    filter_expr = self._validated_expression(
                        filter_text, source, context=context, worker_thread=in_worker,
                    )
                except ValueError as exc:
                    raise ValueError(f"Règle du filtre : {exc}") from exc

            geometry_text = (geometry_expression or "").strip() or "$geometry"
            try:
                prepared_geom = self._prepare_geometry_expression(
                    geometry_text, source, context=context, worker_thread=in_worker,
                )
            except ValueError as exc:
                raise ValueError(f"Règle de géométrie : {exc}") from exc

            needs_sample = prepared_geom is not None or any(
                name.lower() != "geometry" and not (field_definitions or {}).get(name)
                for name in calculated_fields
            )
            sample_features = (
                self._collect_sample_features(source, filter_expr, context, feedback=effective_feedback, limit=50)
                if needs_sample
                else None
            )

            output_wkb_type = source_wkb
            if prepared_geom is not None:
                output_wkb_type = self._detect_expression_wkb_type(
                    source,
                    geometry_text,
                    sample_features=sample_features,
                    context=context,
                    prepared_expression=prepared_geom,
                    feedback=effective_feedback,
                    worker_thread=in_worker,
                )
                if output_wkb_type is None:
                    raise ValueError(
                        "Impossible d'attester le type de géométrie de sortie sur les 50 premières entités."
                    )

            dest_fields = QgsFields()
            expressions: Dict[str, str] = {}
            prepared: Dict[str, QgsExpression] = {}
            known_names: Set[str] = set()
            for name, text in calculated_fields.items():
                if name.lower() == "geometry":
                    continue
                if not name.strip() or name.lower() in known_names:
                    raise ValueError(f"Nom de champ vide ou homonyme : {name}")
                known_names.add(name.lower())
                prepared.update(
                    self._prepare_field_expressions(
                        {name: text}, source, context=context, worker_thread=in_worker,
                    )
                )
                definition = (field_definitions or {}).get(name)
                field = (
                    create_field_from_definition(name, definition)
                    if definition
                    else create_field_from_template(
                        name,
                        self.get_field_type_from_expression_result(
                            text,
                            source,
                            sample_features=sample_features,
                            context=context,
                            prepared_expression=prepared[name],
                        ),
                    )
                )
                dest_fields.append(field)
                expressions[name] = text

            transform = None
            output_is_spatial = QgsWkbTypes.flatType(output_wkb_type) not in (
                QgsWkbTypes.Type.NoGeometry, QgsWkbTypes.Type.Unknown,
            )
            if target_crs is not None and source_crs != target_crs:
                if source_is_spatial:
                    if not source_crs.isValid():
                        raise ValueError("Le SCR source doit être défini avant une reprojection.")
                    tctx = transform_context if transform_context is not None else self._transform_context
                    if tctx is None:
                        if in_worker:
                            raise RuntimeError("Le contexte de reprojection doit être préparé avant la tâche.")
                        tctx = QgsProject.instance().transformContext()
                    transform = QgsCoordinateTransform(source_crs, target_crs, tctx)
                elif output_is_spatial and source_crs.isValid():
                    tctx = transform_context if transform_context is not None else self._transform_context
                    if tctx is None:
                        if in_worker:
                            raise RuntimeError("Le contexte de reprojection doit être préparé avant la tâche.")
                        tctx = QgsProject.instance().transformContext()
                    transform = QgsCoordinateTransform(source_crs, target_crs, tctx)

            # Validate target schema before creating any file/sink
            if schema_validator is not None:
                schema_validator(dest_fields, output_wkb_type, dest_crs)

            sink, sink_result = sink_factory(dest_fields, output_wkb_type, dest_crs)
            if sink is None:
                raise ValueError("core.transformer: impossible de créer la sortie cible.")
            sink_created = True

            try:
                source_fields = source.fields()
                compiled_fields = []
                for field_idx in range(dest_fields.count()):
                    dest_field = dest_fields.at(field_idx)
                    fname = dest_field.name()
                    expr = prepared[fname]
                    raw_text = expressions[fname].strip()
                    direct_idx = -1
                    if len(raw_text) >= 2 and raw_text[0] == '"' and raw_text[-1] == '"':
                        inner = raw_text[1:-1].replace('""', '"')
                        escaped = inner.replace('"', '""')
                        if (
                            f'"{escaped}"' == raw_text
                            and not expr.needsGeometry()
                            and not expr.referencedFunctions()
                            and not expr.referencedVariables()
                            and set(expr.referencedColumns()) == {inner}
                        ):
                            direct_idx = source_fields.indexFromName(inner)
                    compiled_fields.append((fname, expr, direct_idx, make_field_converter(dest_field)))

                num_fields = len(compiled_fields)
                needs_context_feature = (
                    (filter_expr is not None)
                    or (prepared_geom is not None)
                    or any(direct_idx < 0 for _, _, direct_idx, _ in compiled_fields)
                )
                dest_geom_type = QgsWkbTypes.geometryType(output_wkb_type)
                dest_is_multi = QgsWkbTypes.isMultiType(output_wkb_type)
                fast_insert = getattr(getattr(QgsFeatureSink, "Flag", QgsFeatureSink), "FastInsert", 0)

                request = self._build_feature_request(
                    source, filter_expr, prepared, prepared_geom, output_is_spatial,
                )

                batch: List[QgsFeature] = []
                inserted = 0
                limit_batch = max(1, int(self.batch_size))
                last_progress = -1

                def flush_batch():
                    nonlocal inserted
                    if not batch:
                        return
                    self._check_canceled(effective_feedback)
                    ok = sink.addFeatures(batch, fast_insert)
                    if not ok:
                        err = sink.lastError() if hasattr(sink, "lastError") else ""
                        detail = f" ({err})" if err else ""
                        raise ValueError(f"Insertion incomplète : la sortie entière est rejetée.{detail}")
                    inserted += len(batch)
                    batch.clear()

                for feature in source.getFeatures(request):
                    self._check_canceled(effective_feedback)
                    summary["read_count"] += 1
                    if needs_context_feature:
                        context.setFeature(feature)

                    if filter_expr is not None:
                        match = filter_expr.evaluate(context)
                        if filter_expr.hasEvalError():
                            raise ValueError(f"Filtre, entité {feature.id()} : {filter_expr.evalErrorString()}")
                        if QgsVariantUtils.isNull(match) or not bool(match):
                            summary["filtered_out_count"] += 1
                            continue

                    summary["selected_count"] += 1
                    attrs = [None] * num_fields
                    fid = feature.id()
                    for pos, (name, expr, direct_idx, converter) in enumerate(compiled_fields):
                        if direct_idx >= 0:
                            val = feature.attribute(direct_idx)
                        else:
                            val = expr.evaluate(context)
                            if expr.hasEvalError():
                                raise ValueError(f"Champ {name}, entité {fid} : {expr.evalErrorString()}")
                        try:
                            attrs[pos] = converter(val)
                        except ValueError as exc:
                            raise ValueError(f"Champ {name}, entité {fid} : {exc}") from exc

                    output = QgsFeature(dest_fields)
                    output.setId(fid)
                    output.setAttributes(attrs)

                    # Evaluate geometry on untouched feature, clone only before mutation
                    if prepared_geom is not None:
                        geometry = prepared_geom.evaluate(context)
                        if prepared_geom.hasEvalError():
                            raise ValueError(f"Géométrie, entité {fid} : {prepared_geom.evalErrorString()}")
                        if not isinstance(geometry, QgsGeometry):
                            raise ValueError(f"Géométrie non produite pour l'entité {fid}.")
                    elif output_is_spatial:
                        geometry = feature.geometry()
                    else:
                        geometry = None

                    if geometry is not None and not geometry.isNull():
                        if geometry.type() != dest_geom_type:
                            raise ValueError(f"Type de géométrie incompatible à l'entité {fid}.")
                        needs_multi = dest_is_multi and not QgsWkbTypes.isMultiType(geometry.wkbType())
                        if needs_multi or transform is not None:
                            geometry = QgsGeometry(geometry)
                            if needs_multi:
                                geometry.convertToMultiType()
                            if transform is not None:
                                code = geometry.transform(transform)
                                if int(code) != 0:
                                    raise ValueError(f"Reprojection refusée à l'entité {fid}.")
                        output.setGeometry(geometry)

                    batch.append(output)
                    if len(batch) >= limit_batch:
                        flush_batch()
                        if effective_feedback is not None and source_count > 0:
                            pct = min(99, int(summary["read_count"] * 100 / source_count))
                            if pct != last_progress:
                                effective_feedback.setProgress(pct)
                                last_progress = pct

                flush_batch()
                self._check_canceled(effective_feedback)
            finally:
                # Always finalize and release GDAL/OGR handle before returning or cleanup
                try:
                    if sink is not None and hasattr(sink, "finalize"):
                        sink.finalize()
                finally:
                    sink = None
            summary["produced_count"] = inserted
            summary["status"] = "success"
            summary["finished_at"] = datetime.now().isoformat()
            if effective_feedback is not None:
                effective_feedback.setProgress(100)
            logger.info(
                f"Recette {table_name} : {inserted} entités produites, {summary['filtered_out_count']} exclues",
                "transformer", "INFO",
            )
            return sink_result, summary
        except InterruptedError as exc:
            if sink_created and cleanup_on_failure is not None:
                cleanup_on_failure()
            summary["status"] = "cancelled"
            summary["errors"] = [str(exc)]
            summary["produced_count"] = 0
            summary["finished_at"] = datetime.now().isoformat()
            if raise_on_error:
                raise
            return None, summary
        except Exception as exc:
            if sink_created and cleanup_on_failure is not None:
                cleanup_on_failure()
            summary["status"] = "failed"
            summary["rejected_count"] = 1 if summary["read_count"] else 0
            summary["errors"] = [str(exc)]
            summary["produced_count"] = 0
            summary["finished_at"] = datetime.now().isoformat()
            logger.warning(f"Recette {table_name} refusée : {exc}", "transformer", "WARNING")
            if raise_on_error:
                raise
            return None, summary

    def create_memory_layer_from_qgis_layer(self, source_layer: QgsVectorLayer, table_name: str,
                                            calculated_fields: Dict[str, str],
                                            filter_config: Optional[Dict[str, Any]] = None,
                                            target_crs: Optional[QgsCoordinateReferenceSystem] = None,
                                            geometry_expression: Optional[str] = None,
                                            field_definitions: Optional[Dict[str, Any]] = None) -> Optional[QgsVectorLayer]:
        """Build one complete memory layer recipe output; any error rejects it."""
        dest_layer, summary = self.execute_to_sink(
            source=source_layer,
            table_name=table_name,
            calculated_fields=calculated_fields,
            sink_factory=self.create_memory_sink_factory(table_name),
            filter_config=filter_config,
            target_crs=target_crs,
            geometry_expression=geometry_expression,
            field_definitions=field_definitions,
            raise_on_error=False,
        )
        if dest_layer is None:
            return None
        if dest_layer.featureCount() != summary["produced_count"]:
            summary["status"] = "failed"
            summary["produced_count"] = 0
            summary["errors"] = ["Le nombre de lignes écrites ne correspond pas au bilan."]
            return None
        dest_layer.updateExtents()
        return dest_layer

    def add_layers_to_project(self, layers: List[QgsVectorLayer], group_name: str = "Transformed Layers"):
        """Add layers to QGIS project in a group"""
        try:
            if not layers:
                return

            root = QgsProject.instance().layerTreeRoot()

            group = root.findGroup(group_name)
            if not group:
                group = root.addGroup(group_name)

            for layer in layers:
                QgsProject.instance().addMapLayer(layer, False)
                group.addLayer(layer)
                logger.info(f"Layer added to project: {layer.name()}", "transformer", "INFO")

            logger.info(f"{len(layers)} layers added to group '{group_name}'", "transformer", "INFO")
            return True

        except Exception as e:
            logger.warning(f"Error adding layers to project: {str(e)}", "transformer", "WARNING")
            return False

    def validate_expression(self, expression_text: str, sample_layer: QgsVectorLayer = None) -> tuple:
        """Validate QGIS expression"""
        try:
            is_valid, error_msg, expression = validate_expression_syntax(expression_text)
            if not is_valid:
                return False, f"Syntax error: {error_msg}"

            if sample_layer and sample_layer.featureCount() > 0:
                context = self._build_expression_context(sample_layer)

                feature = next(sample_layer.getFeatures())
                context.setFeature(feature)

                success, result, eval_error = evaluate_expression(expression, context)

                if not success:
                    return False, f"Evaluation error: {eval_error}"

                result_type = type(result).__name__
                return True, f"Expression valid - Result: {result} (type: {result_type})"

            return True, "Expression valid (syntax OK)"

        except Exception as e:
            return False, f"Exception: {str(e)}"
