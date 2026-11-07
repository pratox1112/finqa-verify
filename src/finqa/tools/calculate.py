"""Calculator tool (ROADMAP P3.4, guide §3.1): arithmetic over named numbers, nothing else.

`calculate(expression, variables)` evaluates e.g. "(rev_2020 - rev_2019) / rev_2019 * 100"
with {"rev_2019": 4.71e9, "rev_2020": 9.50e9} and returns the result together with the
expression and variables, so the expression can become a claim's `expression` and be
recomputed later (Phase 4).

Allowed: numbers, the given variable names, + - * / ** and parentheses, unary + and -.
Everything else (function calls, attributes, comparisons, subscripts, unknown names, strings,
assignments, several statements) is rejected before evaluation, by an allow-list over the
parsed expression. The checked expression is then evaluated with asteval, given only the
variables as symbols. Division by zero and non-finite results are errors too.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field

from asteval import Interpreter

MAX_EXPRESSION_CHARS = 500
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load)
_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.UAdd, ast.USub)


class CalculationError(ValueError):
    """The expression is not plain arithmetic over the variables, or it can't be computed."""


@dataclass(frozen=True)
class Calculation:
    result: float
    expression: str
    variables: dict[str, float] = field(default_factory=dict)


def check_arithmetic(expression: str, names: set[str]) -> None:
    """Raise CalculationError unless `expression` is arithmetic over numbers and `names`."""
    if not expression.strip():
        raise CalculationError("the expression is empty")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalculationError(f"the expression is longer than {MAX_EXPRESSION_CHARS} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise CalculationError(f"not a valid expression: {e.msg}") from e
    for node in ast.walk(tree):
        if isinstance(node, _ALLOWED + _OPERATORS):
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, int | float):
                raise CalculationError(f"only numbers are allowed, not {node.value!r}")
            continue
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise CalculationError(f"unknown variable {node.id!r}")
            continue
        raise CalculationError(f"not arithmetic: {type(node).__name__} is not allowed")


def calculate(expression: str, variables: dict[str, float] | None = None) -> Calculation:
    variables = dict(variables or {})
    for name, value in variables.items():
        if not _NAME.match(name):
            raise CalculationError(f"invalid variable name {name!r}")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CalculationError(f"variable {name!r} is not a number: {value!r}")
        if not math.isfinite(value):
            raise CalculationError(f"variable {name!r} is not finite: {value!r}")
    check_arithmetic(expression, set(variables))

    interpreter = Interpreter(
        symtable={k: float(v) for k, v in variables.items()},
        minimal=True,
        use_numpy=False,
        builtins_readonly=True,
    )
    result = interpreter.eval(expression.strip(), show_errors=False, raise_errors=False)
    if interpreter.error:
        exc = interpreter.error[0].get_error()[0]
        if exc == "ZeroDivisionError":
            raise CalculationError("division by zero")
        if exc == "OverflowError":
            raise CalculationError("the result is not finite (overflow)")
        raise CalculationError(f"could not evaluate: {exc}")
    if isinstance(result, bool) or not isinstance(result, int | float):
        raise CalculationError(f"the result is not a number: {result!r}")
    if not math.isfinite(result):
        raise CalculationError(f"the result is not finite: {result!r}")
    return Calculation(float(result), expression.strip(), variables)
