# -*- coding: utf-8 -*-
"""
Vector file transformer using QGIS calculated fields with filter support
Fixed filter problem
"""

import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsField, QgsFields, QgsGeometry,
    QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
    QgsProject, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsMessageLog, Qgis, QgsMemoryProviderUtils, QgsFeatureRequest,
    QgsCoordinateTransform, edit
)
from qgis.PyQt.QtCore import QVariant


class SimpleTransformer:
    """Transforms vector files using QGIS calculated fields with filter support"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def get_field_type_from_expression_result(self, expression_text: str, source_layer: QgsVectorLayer) -> QgsField:
        """Determine field type by evaluating expression on sample data"""
        try:
            if source_layer and source_layer.featureCount() > 0:
                context = QgsExpressionContext()
                context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
                
                feature = next(source_layer.getFeatures())
                context.setFeature(feature)
                context.setFields(source_layer.fields())
                
                expression = QgsExpression(expression_text)
                if not expression.hasParserError():
                    result = expression.evaluate(context)
                    
                    if not expression.hasEvalError() and result is not None:
                        if isinstance(result, bool):
                            return QgsField("temp", QVariant.Bool, "boolean", 1)
                        elif isinstance(result, int):
                            field = QgsField("temp", QVariant.Int, "integer", 10)
                            return field
                        elif isinstance(result, float):
                            field = QgsField("temp", QVariant.Double, "double", 20, 6)
                            return field
                        elif hasattr(result, 'date'):
                            return QgsField("temp", QVariant.DateTime, "datetime", 20)
        
        except Exception:
            pass
        
        return QgsField("temp", QVariant.String, "string", 255)
    
    def test_filter_expression(self, filter_expression: str, source_layer: QgsVectorLayer) -> Tuple[bool, str, int]:
        """Test filter expression and return validity, message, and filtered count"""
        try:
            expression = QgsExpression(filter_expression)
            
            if expression.hasParserError():
                return False, f"Syntax error: {expression.parserErrorString()}", 0
            
            if source_layer and source_layer.featureCount() > 0:
                context = QgsExpressionContext()
                context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
                context.setFields(source_layer.fields())
                
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
                    
                    QgsMessageLog.logMessage(
                        f"Filter tested: {actual_filtered_count}/{total_features} features match", 
                        "Transformer", Qgis.Info
                    )
                    
                    return True, f"Valid filter", actual_filtered_count
                    
                except Exception as filter_error:
                    # If QGIS filter doesn't work, do manual test
                    QgsMessageLog.logMessage(f"Filtre QGIS failed, testing manually: {str(filter_error)}", "Transformer", Qgis.Warning)
                    
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
                expression = QgsExpression(cleaned_expression)
                
                if expression.hasParserError():
                    QgsMessageLog.logMessage(
                        f"Filter syntax error: {expression.parserErrorString()}", 
                        "Transformer", Qgis.Warning
                    )
                    return request  # Return request without filter
                
                # Apply the filter
                request.setFilterExpression(cleaned_expression)
                
                QgsMessageLog.logMessage(
                    f"Filter applied: {cleaned_expression[:50]}{'...' if len(cleaned_expression) > 50 else ''}", 
                    "Transformer", Qgis.Info
                )
            
            return request
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Filter application error: {str(e)}", "Transformer", Qgis.Warning)
            return QgsFeatureRequest()  # Return request without filter
    
    def create_feature_request_with_filter(self, source_layer: QgsVectorLayer, filter_expression: Optional[str] = None) -> QgsFeatureRequest:
        """Create a QgsFeatureRequest with optional filter expression"""
        if filter_expression and filter_expression.strip():
            return self.apply_filter_to_layer(source_layer, filter_expression)
        else:
            return QgsFeatureRequest()  # Return request without filter
    
    def count_filtered_features(self, source_layer: QgsVectorLayer, filter_expression: str) -> Tuple[int, int]:
        """Count total and filtered features"""
        total_count = source_layer.featureCount()
        
        if not filter_expression or not filter_expression.strip():
            return total_count, total_count
        
        try:
            request = self.apply_filter_to_layer(source_layer, filter_expression)
            
            # Count by listing all filtered features
            filtered_features = []
            for feature in source_layer.getFeatures(request):
                filtered_features.append(feature)
            
            filtered_count = len(filtered_features)
            
            QgsMessageLog.logMessage(
                f"Count: {filtered_count}/{total_count} features match the filter", 
                "Transformer", Qgis.Info
            )
            
            return total_count, filtered_count
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error counting filtered features: {str(e)}", "Transformer", Qgis.Warning)
            return total_count, total_count
    
    def debug_filter_expression(self, filter_expression: str, source_layer: QgsVectorLayer, limit: int = 10) -> str:
        """Debug filter expression on sample features"""
        debug_results = []
        debug_results.append(f"Debug filter: {filter_expression}")
        debug_results.append("=" * 50)
        
        try:
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
            context.setFields(source_layer.fields())
            
            expression = QgsExpression(filter_expression)
            
            if expression.hasParserError():
                debug_results.append(f"Syntax error: {expression.parserErrorString()}")
                return "\n".join(debug_results)
            
            feature_count = 0
            matching_count = 0
            
            for feature in source_layer.getFeatures():
                if feature_count >= limit:
                    break
                    
                context.setFeature(feature)
                result = expression.evaluate(context)
                
                if expression.hasEvalError():
                    debug_results.append(f"Feature {feature.id()}: ERROR - {expression.evalErrorString()}")
                else:
                    # Interpret boolean result
                    matches = bool(result) and result != 0
                    if matches:
                        matching_count += 1
                    
                    # Display some field values for debugging
                    commentair_value = feature.attribute("COMMENTAIR") if feature.fields().lookupField("COMMENTAIR") >= 0 else "N/A"
                    
                    debug_results.append(
                        f"Feature {feature.id()}: {'MATCHES' if matches else 'DOES NOT MATCH'} "
                        f"- COMMENTAIR='{commentair_value}' - Filter result: {result}"
                    )
                
                feature_count += 1
            
            debug_results.append("=" * 50)
            debug_results.append(f"Summary: {matching_count}/{feature_count} features match the filter")
            return "\n".join(debug_results)
            
        except Exception as e:
            debug_results.append(f"Exception: {str(e)}")
            return "\n".join(debug_results)

    def _detect_expression_geometry_type(self, source_layer: QgsVectorLayer, geometry_expression: str) -> Optional[str]:
        """Detect the geometry type that an expression will produce by testing it on a sample feature"""
        try:
            # Setup expression evaluation context
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
            context.setFields(source_layer.fields())
            
            # Parse expression
            expression = QgsExpression(geometry_expression)
            if expression.hasParserError():
                QgsMessageLog.logMessage(f"Syntax error in geometry expression: {expression.parserErrorString()}", "Transformer", Qgis.Warning)
                return None
            
            # Get first feature to test expression
            features = source_layer.getFeatures()
            try:
                test_feature = next(features)
                if not test_feature.hasGeometry():
                    QgsMessageLog.logMessage("Source layer has no geometry for type detection", "Transformer", Qgis.Warning)
                    return None
            except StopIteration:
                QgsMessageLog.logMessage("No features available for geometry type detection", "Transformer", Qgis.Warning)
                return None
            
            # Evaluate expression on test feature
            context.setFeature(test_feature)
            expression.prepare(context)
            result = expression.evaluate(context)
            
            if expression.hasEvalError():
                QgsMessageLog.logMessage(f"Evaluation error in geometry expression: {expression.evalErrorString()}", "Transformer", Qgis.Warning)
                return None
            
            # Check if result is a geometry and determine type
            if isinstance(result, QgsGeometry) and not result.isNull():
                result_geom_type = result.type()
                geom_type_names = {
                    QgsWkbTypes.PointGeometry: "Point",
                    QgsWkbTypes.LineGeometry: "LineString", 
                    QgsWkbTypes.PolygonGeometry: "Polygon"
                }
                detected_type = geom_type_names.get(result_geom_type)
                if detected_type:
                    QgsMessageLog.logMessage(f"Detected geometry type: {detected_type} from expression test", "Transformer", Qgis.Info)
                    return detected_type
            
            QgsMessageLog.logMessage(f"Expression result is not a valid geometry: {type(result)}", "Transformer", Qgis.Warning)
            return None
        
        except Exception as e:
            QgsMessageLog.logMessage(f"Error detecting geometry type: {str(e)}", "Transformer", Qgis.Warning)
            return None

    def create_memory_layer_from_shapefile(self, shp_path: str, table_name: str, 
                                         calculated_fields: Dict[str, str],
                                         filter_config: Optional[Dict[str, Any]] = None,
                                         target_crs: Optional[QgsCoordinateReferenceSystem] = None,
                                         geometry_expression: Optional[str] = None) -> Optional[QgsVectorLayer]:
        """Create memory layer from vector file with calculated fields and optional filter"""
        try:
            source_layer = QgsVectorLayer(shp_path, "temp_source", "ogr")
            if not source_layer.isValid():
                QgsMessageLog.logMessage(f"Invalid shapefile: {shp_path}", "Transformer", Qgis.Warning)
                return None
            
            # Determine geometry type - use polygon for geometry expressions
            if geometry_expression and geometry_expression != "$geometry":
                # Most geometry expressions produce polygons (buffer, convex_hull, etc.)
                geom_name = self._detect_expression_geometry_type(source_layer, geometry_expression)
                if geom_name is None:
                    geom_name = "Polygon"
                QgsMessageLog.logMessage(f"Using geometry type: {geom_name} from expression detection", "Transformer", Qgis.Info)
            else:
                # Use original geometry type
                geom_type = source_layer.geometryType()
                geom_type_names = {
                    QgsWkbTypes.PointGeometry: "Point",
                    QgsWkbTypes.LineGeometry: "LineString", 
                    QgsWkbTypes.PolygonGeometry: "Polygon"
                }
                geom_name = geom_type_names.get(geom_type, "Point")
            
            # Get CRS
            source_crs = source_layer.crs()
        
            # Determine target CRS (use target_crs if provided, otherwise use source CRS)
            if target_crs and target_crs.isValid():
                final_crs = target_crs
                coordinate_transform = QgsCoordinateTransform(source_crs, final_crs, QgsProject.instance())
                QgsMessageLog.logMessage(f"Reprojection from {source_crs.authid()} to {final_crs.authid()}", "Transformer", Qgis.Info)
            else:
                final_crs = source_crs
                coordinate_transform = None
        
            # Create destination memory layer
            layer_def = f"{geom_name}?crs={final_crs.authid()}"
            dest_layer = QgsVectorLayer(layer_def, table_name, "memory")
            
            if not dest_layer.isValid():
                QgsMessageLog.logMessage(f"Échec de création de la couche mémoire", "Transformer", Qgis.Warning)
                return None
            
            dest_layer.startEditing()
            
            # Add fields with correct types
            fields_to_add = []
            for field_name, expression_text in calculated_fields.items():
                template_field = self.get_field_type_from_expression_result(expression_text, source_layer)
                
                field = QgsField(field_name, template_field.type())
                field.setTypeName(template_field.typeName())
                field.setLength(template_field.length())
                field.setPrecision(template_field.precision())
                fields_to_add.append(field)
                
                QgsMessageLog.logMessage(f"Champ '{field_name}': {template_field.typeName()}", "Transformer", Qgis.Info)
            
            if fields_to_add:
                dest_layer.dataProvider().addAttributes(fields_to_add)
                dest_layer.updateFields()
            
            # Prepare filter request
            feature_request = QgsFeatureRequest()
            filter_applied = False
            filter_expression = ""
            
            if filter_config and filter_config.get("enabled", False):
                filter_expression = filter_config.get("expression", "").strip()
                if filter_expression:
                    feature_request = self.apply_filter_to_layer(source_layer, filter_expression)
                    filter_applied = True
                    QgsMessageLog.logMessage(f"Filtre activé: {filter_expression}", "Transformer", Qgis.Info)
            
            # Count features for progress tracking
            total_source_features = source_layer.featureCount()
            
            if filter_applied:
                # Compter réellement les features filtrées
                filtered_feature_list = list(source_layer.getFeatures(feature_request))
                features_to_process = len(filtered_feature_list)
                QgsMessageLog.logMessage(
                    f"Filtre appliqué: {features_to_process}/{total_source_features} features seront traitées", 
                    "Transformer", Qgis.Info
                )
            else:
                features_to_process = total_source_features
                QgsMessageLog.logMessage(f"Aucun filtre: {features_to_process} features seront traitées", "Transformer", Qgis.Info)
            
            # Process features
            processed = 0
            errors = 0
            
            for source_feature in source_layer.getFeatures(feature_request):
                dest_feature = QgsFeature(dest_layer.fields())
                
                # Handle geometry - either from expression or copy original
                final_geometry = None
                
                if geometry_expression and geometry_expression != "$geometry":
                    # Use custom geometry expression
                    QgsMessageLog.logMessage(f"Applying geometry expression: {geometry_expression}", "Transformer", Qgis.Info)
                    try:
                        expr = QgsExpression(geometry_expression)
                        if not expr.isValid():
                            QgsMessageLog.logMessage(f"Invalid geometry expression: {expr.parserErrorString()}", "Transformer", Qgis.Warning)
                            # Fallback to original geometry
                            if source_feature.hasGeometry():
                                final_geometry = source_feature.geometry()
                        else:
                            # Setup expression context
                            context = QgsExpressionContext()
                            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
                            context.setFeature(source_feature)
                            context.setFields(source_layer.fields())
                            
                            # Evaluate expression
                            expr.prepare(context)
                            result = expr.evaluate(context)
                            
                            if expr.hasEvalError():
                                QgsMessageLog.logMessage(f"Geometry expression evaluation error: {expr.evalErrorString()}", "Transformer", Qgis.Warning)
                                # Fallback to original geometry
                                if source_feature.hasGeometry():
                                    final_geometry = source_feature.geometry()
                            elif isinstance(result, QgsGeometry):
                                final_geometry = result
                                QgsMessageLog.logMessage(f"Geometry expression applied successfully: {geometry_expression}", "Transformer", Qgis.Info)
                            elif result is not None:
                                QgsMessageLog.logMessage(f"Geometry expression returned non-geometry: {type(result)}", "Transformer", Qgis.Warning)
                                # Fallback to original geometry
                                if source_feature.hasGeometry():
                                    final_geometry = source_feature.geometry()
                            else:
                                # Expression returned None - create null geometry or fallback
                                if source_feature.hasGeometry():
                                    final_geometry = source_feature.geometry()
                    except Exception as e:
                        QgsMessageLog.logMessage(f"Error evaluating geometry expression: {str(e)}", "Transformer", Qgis.Warning)
                        # Fallback to original geometry
                        if source_feature.hasGeometry():
                            final_geometry = source_feature.geometry()
                else:
                    # Use original geometry (default behavior)
                    if source_feature.hasGeometry():
                        final_geometry = source_feature.geometry()
                
                # Apply coordinate transformation if needed
                if final_geometry is not None and coordinate_transform:
                    try:
                        final_geometry.transform(coordinate_transform)
                    except Exception as e:
                        QgsMessageLog.logMessage(f"Error transforming geometry: {str(e)}", "Transformer", Qgis.Warning)
                        # Use original geometry if transformation fails
                        if source_feature.hasGeometry():
                            final_geometry = source_feature.geometry()
                        else:
                            final_geometry = None
                
                # Set final geometry
                if final_geometry is not None:
                    dest_feature.setGeometry(final_geometry)
                
                # Calculate and set attribute fields
                calculated_values = self.calculate_fields(
                    source_feature, source_layer, calculated_fields
                )
                
                if calculated_values and any(v is None for v in calculated_values.values()):
                    errors += 1
                
                for field_name, value in calculated_values.items():
                    dest_feature.setAttribute(field_name, value)
                
                dest_layer.dataProvider().addFeature(dest_feature)
                
                processed += 1
                if processed % 100 == 0:
                    QgsMessageLog.logMessage(f"Traité {processed}/{features_to_process} features", "Transformer", Qgis.Info)
            
            dest_layer.commitChanges()
            dest_layer.updateExtents()
            
            # Log results
            if filter_applied:
                filter_info = f" (filtrées de {total_source_features} avec: {filter_expression[:30]}{'...' if len(filter_expression) > 30 else ''})"
            else:
                filter_info = ""
            
            # Add reprojection info
            if coordinate_transform:
                reprojection_info = f" - Reprojection: {source_crs.authid()} → {final_crs.authid()}"
            else:
                reprojection_info = ""
            
            if errors > 0:
                QgsMessageLog.logMessage(
                    f"Couche créée: {table_name} avec {processed} features et {len(calculated_fields)} champs ({errors} erreurs){filter_info}{reprojection_info}", 
                    "Transformer", Qgis.Warning
                )
            else:
                QgsMessageLog.logMessage(
                    f"Couche créée: {table_name} avec {processed} features et {len(calculated_fields)} champs{filter_info}{reprojection_info}", 
                    "Transformer", Qgis.Info
                )
            
            return dest_layer
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur de transformation: {str(e)}", "Transformer", Qgis.Critical)
            return None
    
    def calculate_fields(self, source_feature: QgsFeature, source_layer: QgsVectorLayer, 
                         calculated_fields: Dict[str, str]) -> Dict[str, Any]:
        """Calculate field values using QGIS expressions"""
        calculated_values = {}
        
        context = QgsExpressionContext()
        context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
        context.setFeature(source_feature)
        context.setFields(source_layer.fields())
        
        for field_name, expression_text in calculated_fields.items():
            try:
                expression = QgsExpression(expression_text)
                
                if expression.hasParserError():
                    QgsMessageLog.logMessage(f"Erreur de syntaxe d'expression '{field_name}': {expression.parserErrorString()}", "Transformer", Qgis.Warning)
                    calculated_values[field_name] = None
                    continue
                
                result = expression.evaluate(context)
                
                if expression.hasEvalError():
                    if not hasattr(self, f'_logged_error_{field_name}'):
                        QgsMessageLog.logMessage(f"Erreur d'évaluation d'expression '{field_name}': {expression.evalErrorString()}", "Transformer", Qgis.Warning)
                        setattr(self, f'_logged_error_{field_name}', True)
                    calculated_values[field_name] = None
                else:
                    calculated_values[field_name] = result
                    
            except Exception as e:
                if not hasattr(self, f'_logged_exception_{field_name}'):
                    QgsMessageLog.logMessage(f"Exception de calcul de champ '{field_name}': {str(e)}", "Transformer", Qgis.Warning)
                    setattr(self, f'_logged_exception_{field_name}', True)
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
    
    def transform_shapefile_to_memory_layers(self, shp_path: str, target_crs: QgsCoordinateReferenceSystem = None) -> List[QgsVectorLayer]:
        """Transform vector file to memory layers based on configuration with filter support and optional reprojection"""
        layers_created = []
        
        try:
            shp_filename = os.path.basename(shp_path)
            table_names = self.config_manager.get_tables_for_source(shp_filename)
            
            if not table_names:
                QgsMessageLog.logMessage(f"No configuration found for {shp_filename}", "Transformer", Qgis.Warning)
                return layers_created
            
            for table_name in table_names:
                config = self.config_manager.get_table_config(table_name)
                if not config:
                    continue
                
                calculated_fields = config.get("calculated_fields", {})
                if not calculated_fields:
                    QgsMessageLog.logMessage(f"No calculated fields found for {table_name}", "Transformer", Qgis.Warning)
                    continue
                
                # Get filter configuration
                filter_config = config.get("filter", {"enabled": False, "expression": ""})
                
                # Get geometry expression configuration
                geometry_expression = config.get("geometry_expression")
                QgsMessageLog.logMessage(f"Table {table_name}: geometry_expression = {geometry_expression}", "Transformer", Qgis.Info)
                
                # Reset error flags
                for field_name in calculated_fields.keys():
                    if hasattr(self, f'_logged_error_{field_name}'):
                        delattr(self, f'_logged_error_{field_name}')
                    if hasattr(self, f'_logged_exception_{field_name}'):
                        delattr(self, f'_logged_exception_{field_name}')
                
                layer = self.create_memory_layer_from_shapefile(
                    shp_path, table_name, calculated_fields, filter_config, target_crs, geometry_expression
                )
                
                if layer:
                    layers_created.append(layer)
                    QgsMessageLog.logMessage(f"Layer created: {table_name}", "Transformer", Qgis.Info)
                else:
                    QgsMessageLog.logMessage(f"Layer creation failed: {table_name}", "Transformer", Qgis.Warning)
            
            return layers_created
            
        except Exception as e:
            import traceback
            error_msg = f"QGIS layer transformation error for {layer_name}: {str(e)}"
            stack_trace = traceback.format_exc()
            QgsMessageLog.logMessage(error_msg, "Transformer", Qgis.Critical)
            QgsMessageLog.logMessage(f"Stack trace: {stack_trace}", "Transformer", Qgis.Critical)
            print(f"PRINT: Exception in transform_qgis_layer_to_memory_layers: {error_msg}")
            print(f"PRINT: Stack trace: {stack_trace}")
            return layers_created
    
    def transform_qgis_layer_to_memory_layers(self, source_layer: QgsVectorLayer, layer_name: str, target_crs: QgsCoordinateReferenceSystem = None) -> List[QgsVectorLayer]:
        """Transform QGIS layer object to memory layers based on configuration with filter support and optional reprojection"""
        layers_created = []
        
        try:
            if not source_layer or not source_layer.isValid():
                QgsMessageLog.logMessage(f"Invalid QGIS source layer: {layer_name}", "Transformer", Qgis.Warning)
                return layers_created
                
            # Normalize layer name by removing file extension if present
            normalized_layer_name = layer_name
            if layer_name.lower().endswith('.shp'):
                normalized_layer_name = layer_name[:-4]
            
            # Use the normalized layer name to find table configurations
            table_names = self.config_manager.get_tables_for_source(normalized_layer_name)
            
            if not table_names:
                QgsMessageLog.logMessage(f"No configuration found for QGIS layer: '{layer_name}'", "Transformer", Qgis.Warning)
                return layers_created
                
            for table_name in table_names:
                config = self.config_manager.get_table_config(table_name)
                if not config:
                    continue
                
                calculated_fields = config.get("calculated_fields", {})
                if not calculated_fields:
                    QgsMessageLog.logMessage(f"No calculated fields found for {table_name}", "Transformer", Qgis.Warning)
                    continue
                
                # Get filter configuration
                filter_config = config.get("filter", {"enabled": False, "expression": ""})
                
                # Get geometry expression configuration
                geometry_expression = config.get("geometry_expression")
                
                # Reset error flags
                for field_name in calculated_fields.keys():
                    if hasattr(self, f'_logged_error_{field_name}'):
                        delattr(self, f'_logged_error_{field_name}')
                    if hasattr(self, f'_logged_exception_{field_name}'):
                        delattr(self, f'_logged_exception_{field_name}')
                
                layer = self.create_memory_layer_from_qgis_layer(
                    source_layer, table_name, calculated_fields, filter_config, target_crs, geometry_expression
                )
                
                if layer:
                    layers_created.append(layer)
                    QgsMessageLog.logMessage(f"Layer created from QGIS layer: {table_name}", "Transformer", Qgis.Info)
                else:
                    QgsMessageLog.logMessage(f"Layer creation from QGIS layer failed: {table_name}", "Transformer", Qgis.Warning)
            
            return layers_created
            
        except Exception as e:
            import traceback
            error_msg = f"QGIS layer transformation error for {layer_name}: {str(e)}"
            stack_trace = traceback.format_exc()
            QgsMessageLog.logMessage(error_msg, "Transformer", Qgis.Critical)
            QgsMessageLog.logMessage(f"Stack trace: {stack_trace}", "Transformer", Qgis.Critical)
            print(f"PRINT: Exception in transform_qgis_layer_to_memory_layers: {error_msg}")
            print(f"PRINT: Stack trace: {stack_trace}")
            return layers_created
    
    def create_memory_layer_from_qgis_layer(self, source_layer: QgsVectorLayer, table_name: str, 
                                           calculated_fields: Dict[str, str],
                                           filter_config: Optional[Dict[str, Any]] = None,
                                           target_crs: Optional[QgsCoordinateReferenceSystem] = None,
                                           geometry_expression: Optional[str] = None) -> Optional[QgsVectorLayer]:
        """Create memory layer from QGIS layer object with calculated fields and optional filter"""
        
        try:
            if not source_layer or not source_layer.isValid():
                QgsMessageLog.logMessage(f"Invalid QGIS source layer for {table_name}", "Transformer", Qgis.Warning)
                return None
                
            # Determine geometry type from source layer or expression
            source_geom_type = source_layer.geometryType()
            output_geom_type = source_geom_type
            
            QgsMessageLog.logMessage(f"Source geometry type: {source_geom_type} for {table_name}", "Transformer", Qgis.Info)
            
            # If there's a geometry expression, we might need to adjust the geometry type
            if geometry_expression and geometry_expression != "$geometry":
                # For complex expressions, we'll keep the original type and let QGIS handle it
                QgsMessageLog.logMessage(f"Using geometry expression: {geometry_expression}", "Transformer", Qgis.Info)
                pass
            
            # Determine CRS
            dest_crs = target_crs if target_crs and target_crs.isValid() else source_layer.crs()
            
            # Create memory layer URI
            geom_type_map = {
                QgsWkbTypes.PointGeometry: "Point",
                QgsWkbTypes.LineGeometry: "LineString", 
                QgsWkbTypes.PolygonGeometry: "Polygon",
                QgsWkbTypes.UnknownGeometry: "NoGeometry",
                QgsWkbTypes.NullGeometry: "NoGeometry"
            }
            
            geom_type_name = geom_type_map.get(output_geom_type, "Point")
            uri = f"{geom_type_name}?crs={dest_crs.authid()}&index=yes"
            
            dest_layer = QgsVectorLayer(uri, table_name, "memory")
            if not dest_layer.isValid():
                QgsMessageLog.logMessage(f"Failed to create memory layer: {table_name}", "Transformer", Qgis.Warning)
                return None
            
            # Add fields to destination layer
            field_configs = []
            
            for field_name, expression in calculated_fields.items():
                # Skip geometry field - it's handled by geometry_expression
                if field_name.lower() == 'geometry':
                    QgsMessageLog.logMessage(f"Skipping geometry field - handled by geometry_expression: {expression}", "Transformer", Qgis.Info)
                    continue
                    
                field = QgsField(field_name, QVariant.String, "string", 255)
                field_configs.append((field, expression))
            
            # Use edit context to add fields
            with edit(dest_layer):
                for field, _ in field_configs:
                    if not dest_layer.addAttribute(field):
                        QgsMessageLog.logMessage(f"Failed to add field: {field.name()}", "Transformer", Qgis.Warning)
                        return None
            
            # Set up coordinate transformation if needed
            transform = None
            if target_crs and target_crs.isValid() and source_layer.crs() != target_crs:
                transform = QgsCoordinateTransform(source_layer.crs(), target_crs, QgsProject.instance())
            
            # Create feature request with filter if specified
            feature_request = self.create_feature_request_with_filter(
                source_layer, 
                filter_config.get("expression", "") if filter_config and filter_config.get("enabled", False) else None
            )
            
            # Get total feature count for progress tracking
            total_source_features = source_layer.featureCount()
            
            # Count filtered features if filter is applied
            if filter_config and filter_config.get("enabled", False) and filter_config.get("expression", ""):
                filtered_count, _ = self.count_filtered_features(source_layer, filter_config.get("expression", ""))
                features_to_process = filtered_count
            else:
                features_to_process = total_source_features
            
            # Process features
            processed = 0
            errors = 0
            
            for source_feature in source_layer.getFeatures(feature_request):
                dest_feature = QgsFeature(dest_layer.fields())
                dest_feature.setId(source_feature.id())
                
                # Calculate field values
                calculated_values = self.calculate_field_values(source_feature, field_configs, source_layer)
                
                # Set calculated field values
                for field_name, value in calculated_values.items():
                    if field_name in dest_layer.fields().names():
                        dest_feature.setAttribute(field_name, value)
                
                # Handle geometry
                source_geometry = source_feature.geometry()
                if source_geometry and not source_geometry.isNull():
                    try:
                        # Apply coordinate transformation if needed
                        if transform:
                            source_geometry.transform(transform)
                        
                        # Apply geometry expression if specified
                        final_geometry = source_geometry
                        if geometry_expression and geometry_expression != "$geometry":
                            # Create expression context
                            context = QgsExpressionContext()
                            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(source_layer))
                            context.setFeature(source_feature)
                            
                            # Evaluate geometry expression
                            expr = QgsExpression(geometry_expression)
                            if expr.hasParserError():
                                QgsMessageLog.logMessage(f"Geometry expression parse error: {expr.parserErrorString()}", "Transformer", Qgis.Warning)
                            else:
                                result = expr.evaluate(context)
                                if expr.hasEvalError():
                                    QgsMessageLog.logMessage(f"Geometry expression eval error: {expr.evalErrorString()}", "Transformer", Qgis.Warning)
                                elif isinstance(result, QgsGeometry):
                                    final_geometry = result
                                    QgsMessageLog.logMessage(f"Geometry expression applied successfully", "Transformer", Qgis.Info)
                                elif result is not None:
                                    QgsMessageLog.logMessage(f"Geometry expression returned non-geometry result: {type(result)}", "Transformer", Qgis.Warning)
                        
                        dest_feature.setGeometry(final_geometry)
                        
                        # Log geometry type compatibility for debugging
                        if final_geometry and not final_geometry.isNull():
                            actual_geom_type = final_geometry.type()
                            expected_geom_type = dest_layer.geometryType()
                            if actual_geom_type != expected_geom_type:
                                QgsMessageLog.logMessage(f"Geometry type mismatch - Expected: {expected_geom_type}, Got: {actual_geom_type}", "Transformer", Qgis.Warning)
                        
                    except Exception as e:
                        QgsMessageLog.logMessage(f"Geometry processing error: {str(e)}", "Transformer", Qgis.Warning)
                        errors += 1
                        continue
                
                # Add feature to destination layer
                try:
                    with edit(dest_layer):
                        success = dest_layer.addFeature(dest_feature)
                        if not success:
                            QgsMessageLog.logMessage(f"Failed to add feature {processed + 1} to layer {table_name}", "Transformer", Qgis.Warning)
                            errors += 1
                except Exception as e:
                    QgsMessageLog.logMessage(f"Error adding feature to layer {table_name}: {str(e)}", "Transformer", Qgis.Warning)
                    errors += 1
                    continue
                
                processed += 1
            
            QgsMessageLog.logMessage(f"QGIS Layer {table_name}: {processed} features processed", "Transformer", Qgis.Info)
            return dest_layer
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error creating layer from QGIS layer {table_name}: {str(e)}", "Transformer", Qgis.Warning)
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
                QgsMessageLog.logMessage(f"Layer added to project: {layer.name()}", "Transformer", Qgis.Info)
            
            QgsMessageLog.logMessage(f"{len(layers)} layers added to group '{group_name}'", "Transformer", Qgis.Info)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error adding layers to project: {str(e)}", "Transformer", Qgis.Warning)
    
    def validate_expression(self, expression_text: str, sample_layer: QgsVectorLayer = None) -> tuple:
        """Validate QGIS expression"""
        try:
            expression = QgsExpression(expression_text)
            
            if expression.hasParserError():
                return False, f"Syntax error: {expression.parserErrorString()}"
            
            if sample_layer and sample_layer.featureCount() > 0:
                context = QgsExpressionContext()
                context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(sample_layer))
                
                feature = next(sample_layer.getFeatures())
                context.setFeature(feature)
                context.setFields(sample_layer.fields())
                
                result = expression.evaluate(context)
                
                if expression.hasEvalError():
                    return False, f"Evaluation error: {expression.evalErrorString()}"
                
                result_type = type(result).__name__
                return True, f"Expression valid - Result: {result} (type: {result_type})"
            
            return True, "Expression valid (syntax OK)"
            
        except Exception as e:
            return False, f"Exception: {str(e)}"


def transform_shapefile_to_memory_layers(shp_path, calculated_fields=None, geometry_expression=None, filter_config=None, feedback=None):
    """
    Processing-compatible function for shapefile transformation
    """
    if calculated_fields is None:
        calculated_fields = {}
    if geometry_expression is None:
        geometry_expression = "$geometry"
    if filter_config is None:
        filter_config = {"enabled": False, "expression": ""}
    
    from .gestionnaire import SimpleConfigManager
    
    # Create temporary components
    plugin_dir = os.path.dirname(__file__)
    config_manager = SimpleConfigManager(plugin_dir)
    transformer = SimpleTransformer(config_manager)
    
    # Create temporary table config
    temp_table_name = f"temp_{os.path.splitext(os.path.basename(shp_path))[0]}"
    config_manager.add_table_config(
        temp_table_name,
        os.path.basename(shp_path),
        calculated_fields,
        geometry_expression=geometry_expression,
        filter_expression=filter_config.get("expression", "") if filter_config.get("enabled", False) else ""
    )
    
    if feedback:
        feedback.setProgressText(f"Processing {os.path.basename(shp_path)}")
    
    # Transform
    layers = transformer.transform_shapefile_to_memory_layers(shp_path)
    
    # Clean up temporary config
    config_manager.remove_table_config(temp_table_name)
    
    return layers