# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Headless Python API facade for calling Transformer from PyQGIS scripts."""

import os
from typing import Any, Dict, List, Optional, Tuple, Union

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFields,
    QgsProcessing,
    QgsProcessingContext,
    QgsProcessingUtils,
    QgsProject,
    QgsVectorLayer,
)

from .core.config_manager import ConfigManager
from .core.transformer import SimpleTransformer
from .pg.export_task import publish_source_to_postgresql
from .processing_provider.common import (
    check_sink_schema_preflight,
    cleanup_partial_output_file,
    extract_output_destination_path,
    field_mapping_to_recipe,
    resolve_postgres_connection_params,
)


_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_source(source) -> Tuple[Any, bool]:
    """Return (resolved_source, owned_by_api) for a layer, Processing source, or file path."""
    if isinstance(source, (str, os.PathLike)):
        path = os.fspath(source)
        name = os.path.splitext(os.path.basename(path))[0] or "source"
        layer = QgsVectorLayer(path, name, "ogr")
        if not layer.isValid():
            del layer
            raise ValueError(
                f"Transfomer.api: impossible d'ouvrir la source vectorielle '{path}'."
            )
        return layer, True
    if source is None:
        raise ValueError("Transfomer.api: source vectorielle manquante.")
    if hasattr(source, "isValid") and not source.isValid():
        raise ValueError("Transfomer.api: couche source invalide.")
    return source, False


def _resolve_crs(target_crs) -> Optional[QgsCoordinateReferenceSystem]:
    if target_crs is None or target_crs == "":
        return None
    if isinstance(target_crs, QgsCoordinateReferenceSystem):
        crs = target_crs
    elif isinstance(target_crs, str):
        crs = QgsCoordinateReferenceSystem(target_crs.strip())
    else:
        raise ValueError(f"Transfomer.api: SCR cible non pris en charge ({target_crs!r}).")
    if not crs.isValid():
        raise ValueError(f"Transfomer.api: SCR cible invalide ({target_crs!r}).")
    return crs


def _is_memory_output(output) -> bool:
    if output is None:
        return True
    if not isinstance(output, (str, os.PathLike)):
        return False
    text = os.fspath(output).strip()
    if not text:
        return True
    lowered = text.lower()
    return (
        text == QgsProcessing.TEMPORARY_OUTPUT
        or lowered == "temporary_output"
        or lowered.startswith("memory:")
    )


def _execute_streaming(
    source,
    layer_name: str,
    calculated_fields: Dict[str, str],
    field_definitions: Optional[Dict[str, Any]],
    filter_config: Dict[str, Any],
    geometry_expression: str,
    target_crs: Optional[QgsCoordinateReferenceSystem],
    output,
    strict_schema: bool,
    feedback,
    context: Optional[QgsProcessingContext],
) -> Dict[str, Any]:
    resolved_source, owned_source = _resolve_source(source)
    memory_mode = _is_memory_output(output)
    output_path = "" if memory_mode else os.fspath(output).strip()
    dest_file = "" if memory_mode else extract_output_destination_path(output_path)
    existed_before = bool(dest_file and os.path.exists(dest_file))

    proc_context = context if context is not None else QgsProcessingContext()
    if context is None:
        project = QgsProject.instance()
        if project is not None:
            proc_context.setProject(project)
            proc_context.setTransformContext(project.transformContext())

    def _validate_schema(fields: QgsFields, _wkb_type, _dest_crs):
        if memory_mode or not strict_schema:
            return
        issues = check_sink_schema_preflight(fields, output_path)
        if issues:
            raise ValueError(
                "Transfomer.api: precontrole schema echoue : " + " ; ".join(issues[:5])
            )

    if memory_mode:
        sink_factory = SimpleTransformer.create_memory_sink_factory(layer_name)
    else:
        def sink_factory(fields: QgsFields, wkb_type, dest_crs: QgsCoordinateReferenceSystem):
            parent_dir = os.path.dirname(os.path.abspath(dest_file or output_path))
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            sink, dest_id = QgsProcessingUtils.createFeatureSink(
                output_path, proc_context, fields, wkb_type, dest_crs,
            )
            if sink is None:
                raise ValueError(
                    f"Transfomer.api: impossible de creer la sortie '{output_path}'."
                )
            return sink, dest_id

    def _cleanup():
        cleanup_partial_output_file(dest_file, existed_before)

    engine = SimpleTransformer(None)
    try:
        result_handle, summary = engine.execute_to_sink(
            source=resolved_source,
            table_name=layer_name,
            calculated_fields=calculated_fields,
            sink_factory=sink_factory,
            filter_config=filter_config,
            target_crs=target_crs,
            geometry_expression=geometry_expression,
            field_definitions=field_definitions or {},
            expression_context=proc_context.expressionContext() if context is not None else None,
            transform_context=proc_context.transformContext(),
            feedback=feedback,
            schema_validator=_validate_schema,
            cleanup_on_failure=None if memory_mode else _cleanup,
            raise_on_error=True,
        )
    finally:
        if owned_source:
            resolved_source = None

    if memory_mode:
        result_handle.updateExtents()
        return {"layer": result_handle, "output_path": "", "summary": summary}
    return {"layer": None, "output_path": str(result_handle), "summary": summary}


def list_recipes(recipe_file: str = "", plugin_dir: Optional[str] = None) -> List[str]:
    """Return sorted recipe names from a JSON file or the local Transformer catalogue."""
    return ConfigManager.list_recipe_names(plugin_dir or _PLUGIN_DIR, recipe_file=recipe_file)


def load_recipe(
    recipe_file: str = "",
    recipe_name: str = "",
    plugin_dir: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Resolve and validate one recipe from a JSON file or local catalogue."""
    return ConfigManager.resolve_recipe(
        plugin_dir or _PLUGIN_DIR,
        recipe_file=recipe_file,
        recipe_name=recipe_name,
    )


def export_recipe(
    recipe_name: str,
    output_path: str,
    plugin_dir: Optional[str] = None,
) -> str:
    """Export one recipe from the local catalogue to a portable JSON file."""
    manager = ConfigManager(plugin_dir or _PLUGIN_DIR)
    if not manager.export_single_recipe(recipe_name, output_path):
        reason = manager.last_export_error or "cause inconnue"
        raise ValueError(
            f"Transfomer.api: echec d'export de la recette '{recipe_name}' vers '{output_path}' ({reason})."
        )
    return output_path


def apply_recipe(
    source,
    recipe_file: str = "",
    recipe_name: str = "",
    output: Optional[Union[str, os.PathLike]] = None,
    target_crs=None,
    filter_expression: Optional[str] = None,
    geometry_expression: Optional[str] = None,
    strict_schema: bool = True,
    feedback=None,
    context: Optional[QgsProcessingContext] = None,
    plugin_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a saved Transformer recipe to a layer or file path."""
    resolved_name, recipe = load_recipe(
        recipe_file=recipe_file,
        recipe_name=recipe_name,
        plugin_dir=plugin_dir,
    )
    calculated_fields = recipe.get("calculated_fields", {})
    if not calculated_fields:
        raise ValueError(
            f"Transfomer.api: la recette '{resolved_name}' ne definit aucun champ calcule."
        )

    filter_config = dict(recipe.get("filter") or {"enabled": False, "expression": ""})
    if filter_expression is not None:
        cleaned_filter = filter_expression.strip()
        filter_config = {"enabled": bool(cleaned_filter), "expression": cleaned_filter}

    geom_expr = (
        geometry_expression.strip()
        if geometry_expression is not None and geometry_expression.strip()
        else (recipe.get("geometry_expression") or "$geometry")
    )
    crs = _resolve_crs(target_crs) if target_crs is not None else _resolve_crs(recipe.get("target_crs"))

    result = _execute_streaming(
        source=source,
        layer_name=resolved_name,
        calculated_fields=calculated_fields,
        field_definitions=recipe.get("field_definitions") or {},
        filter_config=filter_config,
        geometry_expression=geom_expr,
        target_crs=crs,
        output=output,
        strict_schema=strict_schema,
        feedback=feedback,
        context=context,
    )
    result["summary"]["recipe_version"] = int(recipe.get("recipe_version", 1))
    result["summary"]["recipe_id"] = recipe.get("recipe_id")
    return result


def transform_vector(
    source,
    calculated_fields: Optional[Dict[str, str]] = None,
    field_definitions: Optional[Dict[str, Dict[str, Any]]] = None,
    filter_expression: str = "",
    geometry_expression: str = "$geometry",
    target_crs=None,
    output: Optional[Union[str, os.PathLike]] = None,
    strict_schema: bool = True,
    feedback=None,
    context: Optional[QgsProcessingContext] = None,
    layer_name: str = "transformed",
) -> Dict[str, Any]:
    """Transform a vector layer or file path directly without a JSON recipe."""
    resolved_source, owned_source = _resolve_source(source)
    try:
        if calculated_fields is None:
            fields_map, defs_map = field_mapping_to_recipe([], resolved_source.fields())
        else:
            fields_map = dict(calculated_fields)
            defs_map = dict(field_definitions or {})

        cleaned_filter = (filter_expression or "").strip()
        filter_config = {"enabled": bool(cleaned_filter), "expression": cleaned_filter}
        geom_expr = (geometry_expression or "").strip() or "$geometry"
        crs = _resolve_crs(target_crs)

        return _execute_streaming(
            source=resolved_source,
            layer_name=layer_name,
            calculated_fields=fields_map,
            field_definitions=defs_map,
            filter_config=filter_config,
            geometry_expression=geom_expr,
            target_crs=crs,
            output=output,
            strict_schema=strict_schema,
            feedback=feedback,
            context=context,
        )
    finally:
        if owned_source:
            resolved_source = None


def publish_postgresql(
    source,
    connection: Union[str, Dict[str, Any]],
    schema: str,
    table: str,
    mode: str = "append",
    allow_create: bool = False,
    geometry_column: str = "",
    field_mapping=None,
    source_key_field: str = "",
    target_key_field: str = "",
    feedback=None,
    plugin_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a vector layer, source, or file path to PostgreSQL in one transaction."""
    resolved_source, owned_source = _resolve_source(source)
    try:
        if isinstance(connection, dict):
            conn_params = dict(connection)
        elif isinstance(connection, str):
            conn_params = resolve_postgres_connection_params(
                connection, plugin_dir=plugin_dir or _PLUGIN_DIR,
            )
        else:
            raise ValueError(
                "Transfomer.api: 'connection' doit etre un nom de connexion QGIS ou un dict psycopg2."
            )

        update_config = None
        if mode == "update":
            if not source_key_field:
                raise ValueError(
                    "Transfomer.api: 'source_key_field' est requis en mode update."
                )
            update_config = {
                "join_type": "attribute",
                "source_key_field": source_key_field,
                "target_key_field": target_key_field or source_key_field,
            }

        summary = publish_source_to_postgresql(
            conn_params=conn_params,
            schema=schema,
            table=table,
            source=resolved_source,
            export_mode=mode,
            allow_create=allow_create,
            geometry_column=geometry_column or None,
            field_mapping=field_mapping,
            update_config=update_config,
            feedback=feedback,
        )
        if summary.get("status") != "success":
            detail = " ; ".join(summary.get("errors", [])) or "echec de publication PostgreSQL."
            raise RuntimeError(f"Transfomer.api ({schema}.{table}): {detail}")
        return summary
    finally:
        if owned_source:
            resolved_source = None
