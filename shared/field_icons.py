# -*- coding: utf-8 -*-
"""Field-type icons for attribute lists (int, float, string, date…)."""

from typing import Optional

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtGui import QIcon

from .field_classification import (
    _normalize_type_name,
    _source_field_type_name,
    is_passthrough,
)
from .icons import IconTone, icon

_TYPE_TO_ICON = {
    "bool": "field_bool",
    "int": "field_int",
    "double": "field_float",
    "datetime": "field_date",
    "string": "field_string",
    "geometry": "field_geometry",
}

_TYPE_LABELS = {
    "bool": "Boolean",
    "int": "Integer",
    "double": "Float",
    "datetime": "Date/Time",
    "string": "String",
    "geometry": "Geometry",
}


def field_type_label(type_name: str) -> str:
    """Human-readable label for a QGIS / PostgreSQL field type name."""
    return _TYPE_LABELS.get(_normalize_type_name(type_name), "String")


def field_type_icon_key(type_name: str) -> str:
    """Map a type name to a logical icon key in shared.icons."""
    normalized = _normalize_type_name(type_name)
    if normalized == "geometry":
        return "field_geometry"
    return _TYPE_TO_ICON.get(normalized, "field_string")


def resolve_field_output_type(
    field_name: str,
    expression: str,
    source_layer: Optional[QgsVectorLayer] = None,
    is_geometry_field: bool = False,
) -> str:
    """Resolve the output type name for a calculated or passthrough field."""
    if is_geometry_field or field_name == "geometry":
        return "geometry"

    expr = (expression or "").strip()
    if not expr:
        return "string"

    if source_layer:
        if is_passthrough(field_name, expr) or expr == field_name.strip():
            source_type = _source_field_type_name(source_layer, field_name)
            if source_type:
                return source_type

        try:
            from ..core.field_types import detect_field_type_from_expression

            detected = detect_field_type_from_expression(expr, source_layer)
            return detected.typeName()
        except Exception:
            pass

        source_type = _source_field_type_name(source_layer, field_name)
        if source_type and (expr == f'"{field_name}"' or expr.replace('"', "") == field_name):
            return source_type

    return "string"


def field_type_icon(
    type_name: str,
    tone: IconTone = IconTone.NEUTRAL,
) -> QIcon:
    """Return the icon for a field type name (QGIS, PostgreSQL, etc.)."""
    return icon(field_type_icon_key(type_name), tone)


def field_icon_for_definition(
    field_name: str,
    expression: str,
    source_layer: Optional[QgsVectorLayer] = None,
    is_geometry_field: bool = False,
) -> QIcon:
    """Return the icon matching a field's resolved output type."""
    output_type = resolve_field_output_type(
        field_name, expression, source_layer, is_geometry_field
    )
    return field_type_icon(output_type)
