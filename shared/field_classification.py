# -*- coding: utf-8 -*-
"""
Field transformation classification and color convention.

Universal color code for the calculated-fields list:
  - UNCHANGED   : default row color (passthrough, no user edit)
  - TYPE_CAST   : explicit type conversion in the expression (to_date, to_int…)
  - GEOMETRY    : geometry field or geometric construction (buffer, centroid…)
  - CALCULATED  : computed attribute (math, string, conditional…)
  - NEW_FIELD   : field not present in the source layer
"""

from enum import Enum
import re
from typing import Optional

from qgis.PyQt.QtGui import QColor
from qgis.core import QgsVectorLayer

from .compat import UserRole, palette_color


class FieldTransformCategory(Enum):
    UNCHANGED = "unchanged"
    TYPE_CAST = "type_cast"
    GEOMETRY = "geometry"
    CALCULATED = "calculated"
    NEW_FIELD = "new_field"


# Convention: muted fills that stay readable on light and dark tree backgrounds.
_CATEGORY_COLORS_LIGHT = {
    FieldTransformCategory.UNCHANGED: None,
    FieldTransformCategory.TYPE_CAST: QColor("#EDE7F6"),      # purple — type conversion
    FieldTransformCategory.GEOMETRY: QColor("#E0F2F1"),      # teal — geometric ops
    FieldTransformCategory.CALCULATED: QColor("#FFF3E0"),     # amber — computed values
    FieldTransformCategory.NEW_FIELD: QColor("#E3F2FD"),      # blue — new column
}

_CATEGORY_COLORS_DARK = {
    FieldTransformCategory.UNCHANGED: None,
    FieldTransformCategory.TYPE_CAST: QColor("#4A3560"),
    FieldTransformCategory.GEOMETRY: QColor("#1B4332"),
    FieldTransformCategory.CALCULATED: QColor("#5D4037"),
    FieldTransformCategory.NEW_FIELD: QColor("#1A3A5C"),
}

_CATEGORY_LABELS = {
    FieldTransformCategory.UNCHANGED: "Pass",
    FieldTransformCategory.TYPE_CAST: "Cast",
    FieldTransformCategory.GEOMETRY: "Geom",
    FieldTransformCategory.CALCULATED: "Calc",
    FieldTransformCategory.NEW_FIELD: "New",
}

_CATEGORY_LEGEND_ORDER = [
    FieldTransformCategory.UNCHANGED,
    FieldTransformCategory.TYPE_CAST,
    FieldTransformCategory.GEOMETRY,
    FieldTransformCategory.CALCULATED,
    FieldTransformCategory.NEW_FIELD,
]

_GEOMETRY_CONSTRUCTION_PATTERN = re.compile(
    r"\b("
    r"buffer|offset_curve|centroid|point_on_surface|simplify|densify_by_count|"
    r"densify_by_distance|combine|collect|merge_lines|node_to_point|points_to_path|"
    r"intersection|difference|sym_difference|union|clip|convex_hull|boundary|"
    r"envelope|oriented_bbox|make_point|make_line|make_polygon|make_triangle|"
    r"curve_to_line|line_interpolate_point|line_interpolate_angle|extend|reverse|"
    r"line_merge|force_rhr|force_polygon_cw|force_polygon_ccw|transform|translate|"
    r"rotate|scale|geom_from_wkt|geom_from_geojson|polygonize|single_sided_buffer|"
    r"shortest_line|line_locate_point|segmentize|smooth|snapped_to_grid|"
    r"remove_duplicate_points|subdivide|triangulate|voronoi|"
    r"collect_geometries|geometry_n|boundary|exterior_ring|interior_ring_n|"
    r"line_merge|multiline|multipolygon|geom_to_wkt|geom_to_geojson"
    r")\s*\(",
    re.IGNORECASE,
)

_TYPE_CAST_PATTERN = re.compile(
    r"\b("
    r"to_int|to_real|to_string|to_str|to_date|to_datetime|to_time|"
    r"to_decimal|to_bool|to_boolean|to_float|to_long"
    r")\s*\(",
    re.IGNORECASE,
)


def is_passthrough(field_name: str, expression: str) -> bool:
    """True when the expression only references the source field unchanged."""
    expr = (expression or "").strip()
    if not expr:
        return False

    name = field_name.strip()
    if expr in (f'"{name}"', f"'{name}'"):
        return True

    lower = expr.lower()
    name_lower = name.lower()
    if lower in (
        f"attribute('{name_lower}')",
        f"attributes('{name_lower}')",
        f"attribute($currentfeature, '{name_lower}')",
    ):
        return True

    if expr == f"${name}":
        return True

    if expr == name:
        return True

    return False


def is_geometry_passthrough(expression: str) -> bool:
    return (expression or "").strip() == "$geometry"


def is_geometry_construction(expression: str, is_geometry_field: bool = False) -> bool:
    """True when the expression builds or transforms geometry."""
    expr = (expression or "").strip()
    if not expr:
        return False

    if is_geometry_field:
        return not is_geometry_passthrough(expr)

    lower = expr.lower()
    if "$geometry" in lower or "geometry(" in lower:
        if _GEOMETRY_CONSTRUCTION_PATTERN.search(expr):
            return True
        if lower.startswith("$geometry") and lower != "$geometry":
            return True

    return bool(_GEOMETRY_CONSTRUCTION_PATTERN.search(expr))


def _source_field_type_name(layer: QgsVectorLayer, field_name: str) -> Optional[str]:
    idx = layer.fields().indexFromName(field_name)
    if idx < 0:
        return None
    return layer.fields().field(idx).typeName().lower()


def _normalize_type_name(type_name: str) -> str:
    name = (type_name or "").lower()
    if name in ("bool", "boolean"):
        return "bool"
    if name in ("int", "integer", "int4", "int8", "long"):
        return "int"
    if name in ("double", "real", "float", "numeric", "decimal"):
        return "double"
    if name in ("datetime", "date", "time", "timestamp"):
        return "datetime"
    return "string"


def is_explicit_type_cast(expression: str) -> bool:
    """True when the user explicitly converts type in the expression."""
    return bool(_TYPE_CAST_PATTERN.search((expression or "").strip()))


def classify_field(
    field_name: str,
    expression: str,
    source_layer: Optional[QgsVectorLayer] = None,
    is_geometry_field: bool = False,
) -> FieldTransformCategory:
    """Classify a field transformation for color coding."""
    expr = (expression or "").strip()

    if is_geometry_field or field_name == "geometry":
        if is_geometry_passthrough(expr):
            return FieldTransformCategory.UNCHANGED
        return FieldTransformCategory.GEOMETRY

    source_has_field = False
    if source_layer:
        source_has_field = source_layer.fields().indexFromName(field_name) >= 0

    if not source_has_field:
        if is_geometry_construction(expr):
            return FieldTransformCategory.GEOMETRY
        return FieldTransformCategory.NEW_FIELD

    if is_passthrough(field_name, expr):
        return FieldTransformCategory.UNCHANGED

    if is_geometry_construction(expr):
        return FieldTransformCategory.GEOMETRY

    if is_explicit_type_cast(expr):
        return FieldTransformCategory.TYPE_CAST

    return FieldTransformCategory.CALCULATED


def is_dark_palette(palette) -> bool:
    return palette_color(palette, None, 'Window').lightness() < 128


def category_background(category: FieldTransformCategory, palette=None) -> Optional[QColor]:
    if category == FieldTransformCategory.UNCHANGED:
        return None
    colors = _CATEGORY_COLORS_DARK if palette and is_dark_palette(palette) else _CATEGORY_COLORS_LIGHT
    return colors.get(category)


def category_label(category: FieldTransformCategory) -> str:
    return _CATEGORY_LABELS[category]


def legend_categories():
    return _CATEGORY_LEGEND_ORDER


FIELD_CATEGORY_ROLE = UserRole + 100
