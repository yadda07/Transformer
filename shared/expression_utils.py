# -*- coding: utf-8 -*-
"""
Expression validation and evaluation utilities.

Centralizes the repeated pattern of:
  QgsExpression(text) → hasParserError → prepare → evaluate → hasEvalError

Used across transformer.py, field_types.py, advanced_expression_widget.py,
expression_tester_dialog.py, smart_filter_widget.py, and main_window.py.
"""

from typing import Any, Optional, Tuple

from qgis.core import QgsExpression, QgsExpressionContext


def validate_expression_syntax(
    expression_text: str,
) -> Tuple[bool, str, Optional[QgsExpression]]:
    """Parse an expression string and check for syntax errors.

    Args:
        expression_text: The QGIS expression string to validate.

    Returns:
        A tuple of (is_valid, error_message, expression_object).
        On success, error_message is empty and expression_object is the
        prepared QgsExpression. On failure, expression_object is None.
    """
    if not expression_text or not expression_text.strip():
        return False, "Empty expression", None

    expr = QgsExpression(expression_text)
    if expr.hasParserError():
        return False, expr.parserErrorString(), None

    return True, "", expr


def evaluate_expression(
    expression: QgsExpression,
    context: QgsExpressionContext,
) -> Tuple[bool, Any, str]:
    """Evaluate a QgsExpression against a context.

    Assumes the expression has already been parsed (no parser error check).
    The caller should call expression.prepare(context) before using this
    in a loop for performance.

    Args:
        expression: A QgsExpression to evaluate.
        context: A QgsExpressionContext with feature and fields set.

    Returns:
        A tuple of (success, result, error_message).
        On success, result is the evaluated value and error_message is empty.
        On failure, result is None and error_message describes the error.
    """
    result = expression.evaluate(context)

    if expression.hasEvalError():
        return False, None, expression.evalErrorString()

    return True, result, ""
