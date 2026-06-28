# -*- coding: utf-8 -*-
"""
QgsField creation and type detection utilities.
Compatible QGIS 3.44+ and 4.x (Qt5/Qt6).
"""

from qgis.core import QgsField, QgsVectorLayer, QgsExpression
from qgis.PyQt.QtCore import QMetaType

from ..shared.helpers import create_layer_expression_context
from ..shared.expression_utils import validate_expression_syntax


_TYPE_NAME_MAP = {
    'bool': 'bool',
    'int': 'integer',
    'double': 'double',
    'datetime': 'datetime',
    'string': 'text',
}

_METATYPE_MAP = None


def _get_metatype_map():
    """Lazy-build QMetaType.Type mapping (only available on newer QGIS)."""
    global _METATYPE_MAP
    if _METATYPE_MAP is not None:
        return _METATYPE_MAP

    if hasattr(QMetaType, 'Type'):
        _METATYPE_MAP = {
            'bool': QMetaType.Type.Bool,
            'int': QMetaType.Type.Int,
            'double': QMetaType.Type.Double,
            'datetime': QMetaType.Type.QDateTime,
            'string': QMetaType.Type.QString,
        }
    else:
        _METATYPE_MAP = {}
    return _METATYPE_MAP


def create_compatible_field(
    field_name: str,
    field_type: str,
    length: int = 0,
    precision: int = 0,
) -> QgsField:
    """Create a QgsField compatible with QGIS 3.44+ and 4.x.

    Args:
        field_name: Name of the field.
        field_type: One of 'bool', 'int', 'double', 'datetime', 'string'.
        length: Field length (0 = default).
        precision: Decimal precision (0 = default).

    Returns:
        A configured QgsField instance.
    """
    field = QgsField(field_name)

    type_name = _TYPE_NAME_MAP.get(field_type, 'text')
    field.setTypeName(type_name)

    metatype_map = _get_metatype_map()
    if field_type in metatype_map:
        try:
            field.setType(metatype_map[field_type])
        except (AttributeError, TypeError):
            pass

    if length > 0:
        field.setLength(length)
    if precision > 0:
        field.setPrecision(precision)

    return field


_PYTHON_TYPE_TO_FIELD = {
    bool: ('bool', 0, 0),
    int: ('int', 10, 0),
    float: ('double', 20, 6),
}


def create_field_from_template(field_name: str, template_field: QgsField) -> QgsField:
    """Create a QgsField from a template field's detected type.

    Maps the template field's typeName to the appropriate
    create_compatible_field call, preserving length and precision.

    Args:
        field_name: Name for the new field.
        template_field: A QgsField whose typeName indicates the target type.

    Returns:
        A configured QgsField instance.
    """
    type_name = template_field.typeName().lower()
    length = template_field.length()
    precision = template_field.precision()

    if type_name in ('bool', 'boolean'):
        return create_compatible_field(field_name, "bool")
    if type_name in ('int', 'integer'):
        return create_compatible_field(field_name, "int", length)
    if type_name in ('double', 'real', 'float'):
        return create_compatible_field(field_name, "double", length, precision)
    if type_name in ('datetime', 'timestamp'):
        return create_compatible_field(field_name, "datetime")
    return create_compatible_field(field_name, "string", length)


def detect_field_type_from_expression(
    expression_text: str,
    source_layer: QgsVectorLayer,
) -> QgsField:
    """Evaluate an expression on a sample of features to detect its return type.

    Samples up to 50 features to find the first non-None result. This avoids
    mis-detecting the type as string when the first feature has a NULL value
    but subsequent features return integers or doubles.

    Falls back to a text(255) field if detection fails on all samples.
    """
    if not source_layer or source_layer.featureCount() == 0:
        return create_compatible_field("temp", "string", 255)

    try:
        context = create_layer_expression_context(source_layer)

        is_valid, error_msg, expression = validate_expression_syntax(expression_text)
        if not is_valid:
            return create_compatible_field("temp", "string", 255)

        expression.prepare(context)

        max_samples = 50
        sampled = 0

        for feature in source_layer.getFeatures():
            if sampled >= max_samples:
                break
            sampled += 1

            context.setFeature(feature)
            result = expression.evaluate(context)

            if expression.hasEvalError() or result is None:
                continue

            for py_type, (ftype, length, prec) in _PYTHON_TYPE_TO_FIELD.items():
                if isinstance(result, py_type):
                    return create_compatible_field("temp", ftype, length, prec)

            if hasattr(result, 'date'):
                return create_compatible_field("temp", "datetime")

            # Non-None, non-matched type: treat as string
            return create_compatible_field("temp", "string", 255)

    except Exception as exc:
        from ..shared.logger import log_warning
        log_warning(f"detect_field_type_from_expression: detection failed: {exc}")

    return create_compatible_field("temp", "string", 255)
