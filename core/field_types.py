# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
QgsField creation and type detection utilities.
QGIS 3.40 - 4.x (Qt 5 / Qt 6) field contracts and bounded type inference.
"""

from datetime import date, datetime
import math
import re
from qgis.core import QgsField, QgsVectorLayer, QgsFeatureRequest, QgsVariantUtils
from qgis.PyQt.QtCore import QDate, QDateTime

from ..shared.compat import meta_type_enum, meta_type_name
from ..shared.helpers import create_layer_expression_context
from ..shared.expression_utils import validate_expression_syntax


_TYPE_NAME_MAP = {
    'bool': 'bool',
    'int': 'integer',
    'int64': 'int8',
    'double': 'double',
    'datetime': 'datetime',
    'date': 'date',
    'string': 'text',
}

_METATYPE_MAP = None


def _get_metatype_map():
    """Lazy-build MetaType mapping across Qt 5 / Qt 6 and QGIS 3.40 - 4.x."""
    global _METATYPE_MAP
    if _METATYPE_MAP is not None:
        return _METATYPE_MAP

    pairs = (
        ('bool', 'Bool'),
        ('int', 'Int'),
        ('int64', 'LongLong'),
        ('double', 'Double'),
        ('datetime', 'QDateTime'),
        ('date', 'QDate'),
        ('string', 'QString'),
    )
    resolved = {}
    for key, qt_name in pairs:
        val = meta_type_enum(qt_name)
        if val is not None:
            resolved[key] = val
    _METATYPE_MAP = resolved
    return _METATYPE_MAP


def create_compatible_field(
    field_name: str,
    field_type: str,
    length: int = 0,
    precision: int = 0,
) -> QgsField:
    """Create a typed QgsField across QGIS 3.40 - 4.x (Qt 5 / Qt 6).

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
    field = QgsField(template_field)
    field.setName(field_name)
    return field


def create_field_from_definition(field_name: str, definition: dict) -> QgsField:
    """Apply the explicit recipe schema without replacing dates or int64 by text."""
    names = {"Text": "string", "Integer": "int", "Integer64": "int64", "Real": "double",
             "Date": "date", "DateTime": "datetime", "Boolean": "bool"}
    field_type = definition.get("type", "Text")
    if field_type not in names:
        raise ValueError(f"Type de sortie inconnu pour {field_name} : {field_type}")
    field = create_compatible_field(field_name, names[field_type], int(definition.get("length", 0)), int(definition.get("precision", 0)))
    field.setComment(definition.get("description", ""))
    return field


def definition_from_processing_mapping(entry: dict) -> dict:
    """Convert one QgsProcessingParameterFieldMapping dict to a recipe field definition."""
    if not isinstance(entry, dict):
        raise ValueError("core.field_types: entree de mapping de champ invalide (dictionnaire attendu).")

    raw_type = entry.get("type")
    type_name_hint = str(entry.get("type_name") or "").strip().lower()
    canonical = None

    # Resolve QMetaType.Type enum or integer code
    if raw_type is not None and not isinstance(raw_type, bool):
        int_code = None
        if isinstance(raw_type, int):
            int_code = raw_type
        elif hasattr(raw_type, "value") and isinstance(raw_type.value, int):
            int_code = raw_type.value
        elif isinstance(raw_type, str) and raw_type.strip().lstrip("-").isdigit():
            int_code = int(raw_type.strip())

        if int_code is not None:
            metatype_map = _get_metatype_map()
            code_to_canonical = {
                int(metatype_map["bool"]): "Boolean",
                int(metatype_map["int"]): "Integer",
                int(metatype_map["int64"]): "Integer64",
                int(metatype_map["double"]): "Real",
                int(metatype_map["string"]): "Text",
                int(metatype_map["date"]): "Date",
                int(metatype_map["datetime"]): "DateTime",
            }
            # Accept unsigned integer variants safely as Integer64
            for attr, target in (
                ("UInt", "Integer64"),
                ("Short", "Integer"),
                ("UShort", "Integer"),
                ("Float", "Real"),
            ):
                enum_val = meta_type_enum(attr)
                if enum_val is not None:
                    code_to_canonical.setdefault(int(enum_val), target)
            canonical = code_to_canonical.get(int_code)

        if canonical is None and isinstance(raw_type, str):
            type_name_hint = raw_type.strip().lower()

    if canonical is None and type_name_hint:
        hint_map = {
            "text": "Text",
            "string": "Text",
            "qstring": "Text",
            "varchar": "Text",
            "char": "Text",
            "integer": "Integer",
            "int": "Integer",
            "int4": "Integer",
            "integer64": "Integer64",
            "int8": "Integer64",
            "int64": "Integer64",
            "longlong": "Integer64",
            "bigint": "Integer64",
            "real": "Real",
            "double": "Real",
            "float": "Real",
            "float8": "Real",
            "numeric": "Real",
            "decimal": "Real",
            "bool": "Boolean",
            "boolean": "Boolean",
            "date": "Date",
            "qdate": "Date",
            "datetime": "DateTime",
            "qdatetime": "DateTime",
            "timestamp": "DateTime",
        }
        canonical = hint_map.get(type_name_hint)

    if canonical is None:
        raise ValueError(
            f"core.field_types: type de champ non pris en charge pour "
            f"'{entry.get('name', '')}' (type={raw_type!r}, type_name={type_name_hint!r})."
        )

    def _parse_bound(raw_val, label: str, maximum: int) -> int:
        if raw_val is None or raw_val == "":
            return 0
        if isinstance(raw_val, bool):
            raise ValueError(
                f"core.field_types: {label} booleen invalide ({raw_val!r}) pour '{entry.get('name', '')}'."
            )
        try:
            parsed = int(raw_val)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"core.field_types: {label} invalide ({raw_val!r}) pour '{entry.get('name', '')}'."
            ) from exc
        # QGIS providers / FieldMapping use -1 as sentinel for default length/precision
        if parsed < 0:
            return 0
        if parsed > maximum:
            raise ValueError(
                f"core.field_types: {label} invalide ({parsed}) pour '{entry.get('name', '')}'."
            )
        return parsed

    length = _parse_bound(entry.get("length", 0), "longueur", 65535)
    precision = _parse_bound(entry.get("precision", 0), "precision", 30)
    return {
        "type": canonical,
        "length": length,
        "precision": precision,
        "description": str(entry.get("comment") or entry.get("description") or ""),
    }


_INT_REGEX = re.compile(r"[+-]?\d+")


def convert_value_for_field(field: QgsField, value):
    """Refuse lossy numeric and text conversions, including late sample outliers."""
    if QgsVariantUtils.isNull(value):
        return value
    kind_name = meta_type_name(field.type())
    if kind_name in ("Int", "LongLong"):
        if isinstance(value, str):
            if not _INT_REGEX.fullmatch(value.strip()):
                raise ValueError("L'entier attendu ne peut pas être obtenu sans perte.")
            value = int(value.strip())
        if not isinstance(value, (bool, int, float)) or (isinstance(value, float) and (not math.isfinite(value) or not value.is_integer())):
            raise ValueError("Une valeur décimale ne peut pas être tronquée en entier.")
        lower, upper = (-(2 ** 31), 2 ** 31 - 1) if kind_name == "Int" else (-(2 ** 63), 2 ** 63 - 1)
        if not lower <= value <= upper:
            raise ValueError("L'entier dépasse la capacité du type de sortie.")
        value = int(value)
    elif kind_name == "Double":
        if isinstance(value, int) and int(float(value)) != value:
            raise ValueError("Cet entier ne peut pas être représenté exactement en nombre réel.")
        if isinstance(value, (int, float)) and not math.isfinite(float(value)):
            raise ValueError("La valeur réelle doit être finie.")
    elif kind_name == "QString" and field.length() > 0:
        if len(str(value)) > field.length():
            raise ValueError("Le texte dépasse la longueur de sortie ; aucune troncature n'est appliquée.")
    compatible = field.convertCompatible(value)
    if isinstance(compatible, tuple):
        ok, converted = compatible[0], compatible[1]
        if not ok:
            raise ValueError("La valeur est incompatible avec le type de sortie.")
        return converted
    if compatible is False:
        raise ValueError("La valeur est incompatible avec le type de sortie.")
    return value


def make_field_converter(field: QgsField):
    """Build a specialized value validator/converter avoiding per-cell metadata lookups."""
    kind_name = meta_type_name(field.type())
    max_len = field.length()

    if kind_name == "QString":
        def _convert_text(value):
            if value is None:
                return None
            if type(value) is str:
                if max_len > 0 and len(value) > max_len:
                    raise ValueError("Le texte dépasse la longueur de sortie ; aucune troncature n'est appliquée.")
                return value
            return convert_value_for_field(field, value)
        return _convert_text

    if kind_name in ("Int", "LongLong"):
        lower, upper = (-(2 ** 31), 2 ** 31 - 1) if kind_name == "Int" else (-(2 ** 63), 2 ** 63 - 1)

        def _convert_int(value):
            if value is None:
                return None
            if type(value) is int:
                if not lower <= value <= upper:
                    raise ValueError("L'entier dépasse la capacité du type de sortie.")
                return value
            return convert_value_for_field(field, value)
        return _convert_int

    if kind_name == "Double":
        def _convert_double(value):
            if value is None:
                return None
            t = type(value)
            if t is float:
                if not math.isfinite(value):
                    raise ValueError("La valeur réelle doit être finie.")
                return value
            if t is int:
                if int(float(value)) != value:
                    raise ValueError("Cet entier ne peut pas être représenté exactement en nombre réel.")
                return float(value)
            return convert_value_for_field(field, value)
        return _convert_double

    if kind_name == "Bool":
        def _convert_bool(value):
            if value is None or type(value) is bool:
                return value
            return convert_value_for_field(field, value)
        return _convert_bool

    return lambda value: convert_value_for_field(field, value)


def detect_field_type_from_expression(
    expression_text: str,
    source_layer: QgsVectorLayer,
    sample_features=None,
    context=None,
    prepared_expression=None,
) -> QgsField:
    """Evaluate an expression on a sample of features to detect its return type.

    Reads at most 50 features. Mixed numeric values are promoted to Real,
    dates and int64 are retained, and direct field copies preserve the schema.

    Falls back to a text(255) field if detection fails on all samples.
    """
    if not source_layer:
        return create_compatible_field("temp", "string", 255)

    try:
        # A direct reference already has a reliable schema, even on an empty layer.
        quoted = expression_text.strip()
        if len(quoted) >= 2 and quoted[0] == quoted[-1] == '"':
            name = quoted[1:-1].replace('""', '"')
            index = source_layer.fields().indexFromName(name)
            if index >= 0:
                return create_field_from_template("temp", source_layer.fields()[index])
        if context is None:
            context = source_layer.expression_context() if hasattr(source_layer, "expression_context") else create_layer_expression_context(source_layer)

        if prepared_expression is not None:
            expression = prepared_expression
        else:
            is_valid, error_msg, expression = validate_expression_syntax(expression_text)
            if not is_valid:
                return create_compatible_field("temp", "string", 255)
            expression.prepare(context)

        detected = set()
        features_iter = (
            sample_features
            if sample_features is not None
            else source_layer.getFeatures(QgsFeatureRequest().setLimit(50))
        )
        for feature in features_iter:
            context.setFeature(feature)
            result = expression.evaluate(context)

            if expression.hasEvalError() or QgsVariantUtils.isNull(result):
                continue
            if isinstance(result, bool):
                detected.add("bool")
            elif isinstance(result, int):
                detected.add("int64" if result < -(2 ** 31) or result > 2 ** 31 - 1 else "int")
            elif isinstance(result, float):
                detected.add("double")
            elif isinstance(result, (QDateTime, datetime)):
                detected.add("datetime")
            elif isinstance(result, (QDate, date)):
                detected.add("date")
            else:
                detected.add("string")
        if detected and detected <= {"bool", "int", "int64", "double"}:
            kind = "double" if "double" in detected else ("int64" if "int64" in detected else ("int" if "int" in detected else "bool"))
        elif detected and detected <= {"date", "datetime"}:
            kind = "datetime" if "datetime" in detected else "date"
        else:
            kind = next(iter(detected)) if len(detected) == 1 else "string"
        return create_compatible_field("temp", kind, 254 if kind == "string" else 0, 6 if kind == "double" else 0)

    except Exception as exc:
        from ..shared.logger import log_warning
        log_warning(f"detect_field_type_from_expression: detection failed: {exc}")

    return create_compatible_field("temp", "string", 255)
