# -*- coding: utf-8 -*-
"""
Vector file transformer using QGIS calculated fields with filter support
Fixed filter problem
"""

import os
from typing import Dict, List, Any, Optional, Tuple, Set

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsField, QgsGeometry,
    QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
    QgsProject, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsCoordinateTransform, QgsTask
)
from .field_types import (
    create_compatible_field,
    create_field_from_template,
    detect_field_type_from_expression,
)
from ..shared.constants import VECTOR_EXTENSIONS
from ..shared.geom_types import get_geom_name, get_wkb_type
from ..shared.expression_utils import validate_expression_syntax, evaluate_expression
from ..shared.helpers import is_filter_enabled, get_filter_expression
from ..shared.logger import logger


class SimpleTransformer:
    """Transforms vector files using QGIS calculated fields with filter support"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._current_task: Optional[QgsTask] = None  # Set by TransformTask for mid-item cancellation
        self._prebuilt_scopes: Optional[list] = None  # Set by TransformTask for thread-safe context
        self._logged_field_errors: Set[str] = set()  # Dedup error logs per field per transformation
    
    def get_field_type_from_expression_result(self, expression_text: str, source_layer: QgsVectorLayer) -> QgsField:
        """Determine field type by evaluating expression on sample data"""
        return detect_field_type_from_expression(expression_text, source_layer)
    
    def test_filter_expression(self, filter_expression: str, source_layer: QgsVectorLayer) -> Tuple[bool, str, int]:
        """Test filter expression and return validity, message, and filtered count"""
        try:
            is_valid, error_msg, expression = validate_expression_syntax(filter_expression)
            if not is_valid:
                return False, f"Syntax error: {error_msg}", 0
            
            if source_layer and source_layer.featureCount() > 0:
                context = self._build_expression_context(source_layer)
                
                matching_features = 0
                total_tested = 0
                test_errors = 0
                max_tests = min(50, source_layer.featureCount())  
                
                # Count the actual number of features that match the filter
                request = QgsFeatureRequest()
                request.setFilterExpression(filter_expression)
                
                try:
                    # Try to use QGIS filter directly
                    filtered_features = list(source_layer.getFeatures(request))
                    total_features = source_layer.featureCount()
                    actual_filtered_count = len(filtered_features)
                    
                    logger.info(f"Filter tested: {actual_filtered_count}/{total_features} features match", "transformer", "INFO")
                    
                    return True, f"Valid filter", actual_filtered_count
                    
                except Exception as filter_error:
                    # If QGIS filter doesn't work, do manual test
                    logger.warning(f"Filtre QGIS failed, testing manually: {str(filter_error)}", "transformer", "WARNING")
                    
                    for feature in source_layer.getFeatures():
                        if total_tested >= max_tests:
                            break
                        
                        context.setFeature(feature)
                        result = expression.evaluate(context)
                        
                        if expression.hasEvalError():
                            test_errors += 1
                            if test_errors > 5:  # Stop after 5 errors
                                return False, f"Multiple evaluation errors. Last error: {expression.evalErrorString()}", 0
                        else:
                            # Result must be True for feature to be included
                            if result and result != 0:  # True or non-zero
                                matching_features += 1
                        
                        total_tested += 1
                    
                    if test_errors > 0:
                        return False, f"Expression with evaluation errors on some features", 0
                    
                    # Extrapolate result for all features
                    total_features = source_layer.featureCount()
                    if total_tested > 0:
                        estimated_filtered = int((matching_features / total_tested) * total_features)
                    else:
                        estimated_filtered = 0
                    
                    return True, f"Valid filter (manual test)", estimated_filtered
            
            return True, "Syntactically valid filter expression (no test data)", 0
            
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
                    return request  # Return request without filter
                
                # Apply the filter
                request.setFilterExpression(cleaned_expression)
                
                logger.info(f"Filter applied: {cleaned_expression[:50]}{'...' if len(cleaned_expression) > 50 else ''}", "transformer", "INFO")
            
            return request
            
        except Exception as e:
            logger.warning(f"Filter application error: {str(e)}", "transformer", "WARNING")
            return QgsFeatureRequest()  # Return request without filter
    
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
        
        try:
            request = self.apply_filter_to_layer(source_layer, filter_expression)
            
            filtered_count = 0
            for _ in source_layer.getFeatures(request):
                filtered_count += 1
            
            logger.info(f"Count: {filtered_count}/{total_count} features match the filter", "transformer", "INFO")
            
            return total_count, filtered_count
            
        except Exception as e:
            logger.warning(f"Error counting filtered features: {str(e)}", "transformer", "WARNING")
            return total_count, total_count

    def _detect_expression_geometry_type(self, source_layer: QgsVectorLayer, geometry_expression: str) -> Optional[str]:
        """Detect the geometry type that an expression will produce by testing it on a sample feature"""
        try:
            # Setup expression evaluation context
            context = self._build_expression_context(source_layer)
            
            # Parse expression
            is_valid, error_msg, expression = validate_expression_syntax(geometry_expression)
            if not is_valid:
                logger.warning(f"Syntax error in geometry expression: {error_msg}", "transformer", "WARNING")
                return None
            
            # Get first feature to test expression
            features = source_layer.getFeatures()
            try:
                test_feature = next(features)
                if not test_feature.hasGeometry():
                    logger.warning("Source layer has no geometry for type detection", "transformer", "WARNING")
                    return None
            except StopIteration:
                logger.warning("No features available for geometry type detection", "transformer", "WARNING")
                return None
            
            # Evaluate expression on test feature
            context.setFeature(test_feature)
            expression.prepare(context)
            result = expression.evaluate(context)
            
            if expression.hasEvalError():
                logger.warning(f"Evaluation error in geometry expression: {expression.evalErrorString()}", "transformer", "WARNING")
                return None
            
            # Check if result is a geometry and determine type
            if isinstance(result, QgsGeometry) and not result.isNull():
                result_geom_type = result.type()
                detected_type = get_geom_name(result_geom_type)
                if detected_type:
                    logger.info(f"Detected geometry type: {detected_type} from expression test", "transformer", "INFO")
                    return detected_type
            
            logger.warning(f"Expression result is not a valid geometry: {type(result)}", "transformer", "WARNING")
            return None
        
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
    
    def _build_expression_context(self, source_layer: QgsVectorLayer) -> QgsExpressionContext:
        """Build an expression context for the given layer.

        Uses pre-built global+project scopes when available (thread-safe path
        for worker threads), falling back to globalProjectLayerScopes for
        non-threaded usage.
        """
        context = QgsExpressionContext()
        if self._prebuilt_scopes:
            from qgis.core import QgsExpressionContextScope
            for scope in self._prebuilt_scopes:
                context.appendScope(QgsExpressionContextScope(scope))
            context.appendScope(QgsExpressionContextUtils.layerScope(source_layer))
        else:
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
        context.setFields(source_layer.fields())
        return context

    def _prepare_field_expressions(
        self,
        calculated_fields: Dict[str, str],
        source_layer: QgsVectorLayer,
    ) -> Dict[str, QgsExpression]:
        """Build and prepare QgsExpression objects once for all features.

        Returns a dict {field_name: QgsExpression}. Expressions with parser
        errors are included but flagged via hasParserError().
        """
        prepared = {}
        context = self._build_expression_context(source_layer)

        for field_name, expression_text in calculated_fields.items():
            is_valid, error_msg, expr = validate_expression_syntax(expression_text)
            if is_valid:
                expr.prepare(context)
            else:
                logger.warning(f"Syntax error in expression '{field_name}': {error_msg}", "transformer", "WARNING")
            prepared[field_name] = expr

        logger.info(f"Prepared {len(prepared)} field expressions for layer '{source_layer.name()}'", "transformer", "INFO")
        return prepared

    def _prepare_geometry_expression(
        self,
        geometry_expression: str,
        source_layer: QgsVectorLayer,
    ) -> Optional[QgsExpression]:
        """Build and prepare a geometry QgsExpression once."""
        if not geometry_expression or geometry_expression == "$geometry":
            return None
        is_valid, error_msg, expr = validate_expression_syntax(geometry_expression)
        if not is_valid:
            logger.warning(f"Syntax error in geometry expression: {error_msg}", "transformer", "WARNING")
            return None
        context = self._build_expression_context(source_layer)
        expr.prepare(context)
        return expr

    def calculate_fields(
        self,
        source_feature: QgsFeature,
        source_layer: QgsVectorLayer,
        calculated_fields: Dict[str, str],
        prepared_expressions: Optional[Dict[str, QgsExpression]] = None,
    ) -> Dict[str, Any]:
        """Calculate field values using QGIS expressions.

        If prepared_expressions is provided, reuses pre-built QgsExpression
        objects (performance path). Otherwise builds them per-call (legacy).
        """
        calculated_values = {}

        context = self._build_expression_context(source_layer)
        context.setFeature(source_feature)

        for field_name, expression_text in calculated_fields.items():
            try:
                if prepared_expressions and field_name in prepared_expressions:
                    expression = prepared_expressions[field_name]
                else:
                    expression = QgsExpression(expression_text)
                    if expression.hasParserError():
                        logger.warning(f"Erreur de syntaxe d'expression '{field_name}': {expression.parserErrorString()}", "transformer", "WARNING")
                        calculated_values[field_name] = None
                        continue

                if expression.hasParserError():
                    calculated_values[field_name] = None
                    continue

                result = expression.evaluate(context)

                if expression.hasEvalError():
                    if field_name not in self._logged_field_errors:
                        logger.warning(f"Erreur d'évaluation d'expression '{field_name}': {expression.evalErrorString()}", "transformer", "WARNING")
                        self._logged_field_errors.add(field_name)
                    calculated_values[field_name] = None
                else:
                    calculated_values[field_name] = result

            except Exception as e:
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

        try:
            table_names = self.config_manager.get_tables_for_source(source_name)

            if not table_names:
                logger.warning(f"No configuration found for {source_name}", "transformer", "WARNING")
                return layers_created

            if table_filter is not None:
                allowed = set(table_filter)
                table_names = [n for n in table_names if n in allowed]
                if not table_names:
                    logger.info(f"No table_config in filter matched source {source_name}", "transformer", "INFO")
                    return layers_created

            for table_name in table_names:
                config = self.config_manager.get_table_config(table_name)
                if not config:
                    continue

                calculated_fields = config.get("calculated_fields", {})
                if not calculated_fields:
                    logger.warning(f"No calculated fields found for {table_name}", "transformer", "WARNING")
                    continue

                filter_config = config.get("filter", {"enabled": False, "expression": ""})
                geometry_expression = config.get("geometry_expression")

                layer = self.create_memory_layer_from_qgis_layer(
                    source_layer, table_name, calculated_fields,
                    filter_config, target_crs, geometry_expression,
                )

                # R9: Clean up error flags after transformation
                for field_name in calculated_fields.keys():
                    self._logged_field_errors.discard(field_name)

                if layer:
                    layers_created.append(layer)
                    logger.info(f"Layer created: {table_name}", "transformer", "INFO")
                else:
                    logger.warning(f"Layer creation failed: {table_name}", "transformer", "WARNING")

            return layers_created

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
    
    def create_memory_layer_from_qgis_layer(self, source_layer: QgsVectorLayer, table_name: str, 
                                           calculated_fields: Dict[str, str],
                                           filter_config: Optional[Dict[str, Any]] = None,
                                           target_crs: Optional[QgsCoordinateReferenceSystem] = None,
                                           geometry_expression: Optional[str] = None) -> Optional[QgsVectorLayer]:
        """Create memory layer from QGIS layer object with calculated fields and optional filter"""
        
        try:
            if not source_layer or not source_layer.isValid():
                logger.warning(f"Invalid QGIS source layer for {table_name}", "transformer", "WARNING")
                return None
                
            # Determine geometry type from source layer or expression
            source_geom_type = source_layer.geometryType()
            output_geom_type = source_geom_type

            # If geometry expression is specified, detect its output type
            if geometry_expression and geometry_expression != "$geometry":
                detected = self._detect_expression_geometry_type(source_layer, geometry_expression)
                if detected is not None:
                    mapped = get_wkb_type(detected)
                    output_geom_type = mapped if mapped is not None else source_geom_type
            
            # Determine CRS
            dest_crs = target_crs if target_crs and target_crs.isValid() else source_layer.crs()
            
            # Create memory layer URI
            geom_type_name = get_geom_name(output_geom_type)
            uri = f"{geom_type_name}?crs={dest_crs.authid()}&index=yes"
            
            dest_layer = QgsVectorLayer(uri, table_name, "memory")
            if not dest_layer.isValid():
                logger.warning(f"Failed to create memory layer: {table_name}", "transformer", "WARNING")
                return None
            
            # Add fields to destination layer with type detection (R6: same as shapefile path)
            field_configs = []
            
            for field_name, expression in calculated_fields.items():
                if field_name.lower() == 'geometry':
                    continue
                
                template_field = self.get_field_type_from_expression_result(expression, source_layer)
                field = create_field_from_template(field_name, template_field)
                field_configs.append((field, expression))
            
            # Add fields to destination layer
            dest_layer.startEditing()
            
            existing_fields = [field.name().lower() for field in dest_layer.fields()]
            
            for field, _ in field_configs:
                field_name_lower = field.name().lower()
                
                if field_name_lower in existing_fields:
                    continue
                
                if not dest_layer.addAttribute(field):
                    logger.warning(f"Failed to add field: {field.name()}", "transformer", "WARNING")
                    alternative_field = create_compatible_field(field.name(), "string", 255)
                    
                    if not dest_layer.addAttribute(alternative_field):
                        logger.warning(f"Alternative field creation also failed for: {field.name()}", "transformer", "WARNING")
                        dest_layer.rollBack()
                        return None
            
            if not dest_layer.commitChanges():
                logger.warning(f"Failed to commit field changes", "transformer", "WARNING")
                return None
            
            # Set up coordinate transformation if needed
            transform = None
            if target_crs and target_crs.isValid() and source_layer.crs() != target_crs:
                transform = QgsCoordinateTransform(source_layer.crs(), target_crs, QgsProject.instance())
            
            # Create feature request with filter if specified
            feature_request = self.create_feature_request_with_filter(
                source_layer, 
                get_filter_expression(filter_config) if is_filter_enabled(filter_config) else None,
            )
            
            # Get total feature count for progress tracking
            total_source_features = source_layer.featureCount()

            if is_filter_enabled(filter_config):
                features_to_process = None  # Unknown until iteration completes
                logger.info(f"Filtre appliqué: comptage en cours sur {total_source_features} features source", "transformer", "INFO")
            else:
                features_to_process = total_source_features
                logger.info(f"Aucun filtre: {features_to_process} features seront traitées", "transformer", "INFO")
            
            # R2: Prepare expressions once for all features
            fields_for_prep = {f.name(): expr for f, expr in field_configs}
            prepared_field_exprs = self._prepare_field_expressions(fields_for_prep, source_layer)
            prepared_geom_expr = self._prepare_geometry_expression(geometry_expression or "", source_layer)
            
            geom_context = self._build_expression_context(source_layer)
            
            # Process features
            processed = 0
            errors = 0
            
            features_batch = []
            for source_feature in source_layer.getFeatures(feature_request):
                # R8: Check cancellation every 1000 features
                if processed > 0 and processed % 1000 == 0:
                    task = getattr(self, '_current_task', None)
                    if task is not None and task.isCanceled():
                        logger.warning(f"Transformation cancelled at {processed}/{features_to_process} features", "transformer", "WARNING")
                        break

                dest_feature = QgsFeature(dest_layer.fields())
                dest_feature.setId(source_feature.id())
                
                # Calculate field values using prepared expressions
                calculated_values = self.calculate_fields(
                    source_feature, source_layer, fields_for_prep,
                    prepared_expressions=prepared_field_exprs,
                )
                
                for field_name, value in calculated_values.items():
                    if field_name in dest_layer.fields().names():
                        dest_feature.setAttribute(field_name, value)
                
                # Handle geometry
                source_geometry = source_feature.geometry()
                if source_geometry and not source_geometry.isNull():
                    try:
                        if transform:
                            source_geometry.transform(transform)
                        
                        final_geometry = source_geometry
                        if prepared_geom_expr is not None:
                            geom_context.setFeature(source_feature)
                            result = prepared_geom_expr.evaluate(geom_context)
                            if prepared_geom_expr.hasEvalError():
                                logger.warning(f"Geometry expression eval error: {prepared_geom_expr.evalErrorString()}", "transformer", "WARNING")
                            elif isinstance(result, QgsGeometry):
                                final_geometry = result
                            elif result is not None:
                                logger.warning(f"Geometry expression returned non-geometry result: {type(result)}", "transformer", "WARNING")
                        
                        dest_feature.setGeometry(final_geometry)
                        
                        if final_geometry and not final_geometry.isNull():
                            actual_geom_type = final_geometry.type()
                            expected_geom_type = dest_layer.geometryType()
                            if actual_geom_type != expected_geom_type:
                                logger.warning(f"Geometry type mismatch - Expected: {expected_geom_type}, Got: {actual_geom_type}", "transformer", "WARNING")
                        
                    except Exception as e:
                        logger.warning(f"Geometry processing error: {str(e)}", "transformer", "WARNING")
                        errors += 1
                        continue
                
                features_batch.append(dest_feature)
                processed += 1
                
                if processed % 1000 == 0 and processed > 0:
                    total_display = features_to_process if features_to_process else "?"
                    logger.info(f"Traité {processed}/{total_display} features", "transformer", "INFO")
            
            # Batch insert all features at once via data provider
            if features_batch:
                success, added = dest_layer.dataProvider().addFeatures(features_batch)
                if not success:
                    logger.warning(f"Batch insert failed for {table_name}", "transformer", "WARNING")
                    errors += len(features_batch)
                dest_layer.updateExtents()
            
            # Final count for filtered case
            if features_to_process is None:
                features_to_process = processed

            logger.info(f"QGIS Layer {table_name}: {processed} features processed, {errors} errors", "transformer", "INFO")
            return dest_layer
            
        except Exception as e:
            logger.warning(f"Error creating layer from QGIS layer {table_name}: {str(e)}", "transformer", "WARNING")
            return None
    
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
            
        except Exception as e:
            logger.warning(f"Error adding layers to project: {str(e)}", "transformer", "WARNING")
    
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