"""Siemens 840D variable and expression handling."""
from __future__ import annotations

import ast
from functools import lru_cache
import math
import re
from typing import Any, Dict, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.handlers.siemens_mill_cnc.common import ensure_siemens_scope, format_number


def _atan2_deg(y_value: float, x_value: float) -> float:
    return math.degrees(math.atan2(y_value, x_value))


def _sin_deg(value: float) -> float:
    return math.sin(math.radians(value))


def _cos_deg(value: float) -> float:
    return math.cos(math.radians(value))


def _tan_deg(value: float) -> float:
    return math.tan(math.radians(value))


def _asin_deg(value: float) -> float:
    return math.degrees(math.asin(value))


def _acos_deg(value: float) -> float:
    return math.degrees(math.acos(value))


def _atan_deg(value: float) -> float:
    return math.degrees(math.atan(value))


_ALLOWED_FUNCS = {
    "SQRT": math.sqrt,
    "SIN": _sin_deg,
    "COS": _cos_deg,
    "TAN": _tan_deg,
    "ASIN": _asin_deg,
    "ACOS": _acos_deg,
    "ATAN": _atan_deg,
    "ATAN2": _atan2_deg,
    "ABS": abs,
    "POT": math.pow,
    "TRUNC": math.trunc,
    "LN": math.log,
    "EXP": math.exp,
    "ROUND": round,
    "FIX": math.trunc,
    "FUP": math.ceil,
    "TRUE": True,
    "FALSE": False,
    "PI": math.pi,
}


_ALLOWED_SIEMENS_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Load,
    ast.Name,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

_PLAIN_FLOAT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


@lru_cache(maxsize=2048)
def _compile_siemens_expr(expr: str):
    node = ast.parse(expr, mode="eval")
    for item in ast.walk(node):
        if not isinstance(item, _ALLOWED_SIEMENS_AST_NODES):
            raise ValueError(f"Unsafe Siemens expression element: {type(item).__name__}")
    return compile(node, "<siemens_expr>", "eval")


class _LazySiemensEvalContext(dict):
    """Lazy evaluation mapping backed directly by CNCState and Siemens scope."""

    def __init__(self, state: CNCState) -> None:
        super().__init__()
        self._state = state
        self._scope = ensure_siemens_scope(state)

    def __missing__(self, key: str) -> Any:
        if key in _ALLOWED_FUNCS:
            return _ALLOWED_FUNCS[key]
        if key.startswith("__r_"):
            r_key = key[4:]
            params = self._state.parameters
            if params and r_key in params:
                try:
                    return float(params[r_key])
                except Exception:
                    return 0.0
            return 0.0
        symbols = self._scope.get("symbols")
        if isinstance(symbols, dict) and key in symbols:
            val = symbols[key]
            try:
                return float(val)
            except Exception:
                return val
        return 0.0


class SiemensExpressionEvaluator:
    """Small Siemens-aware evaluator for numeric and BOOL-compatible expressions."""

    _SYSTEM_VAR_RE = re.compile(r"\$[A-Za-z0-9_]+(?:\[[^\]]+\])?")
    _SYSTEM_VAR_TOKEN_RE = re.compile(r"^(\$[A-Za-z0-9_]+)(?:\[([^\]]+)\])?$")
    _R_PARAM_RE = re.compile(r"\bR(\d+)\b", re.IGNORECASE)
    _NAME_INDEX_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\]]+)\s*\]")
    _AND_RE = re.compile(r"\bAND\b", re.IGNORECASE)
    _OR_RE = re.compile(r"\bOR\b", re.IGNORECASE)
    _NOT_RE = re.compile(r"\bNOT\b", re.IGNORECASE)
    _DIV_RE = re.compile(r"\bDIV\b", re.IGNORECASE)
    _MOD_RE = re.compile(r"\bMOD\b", re.IGNORECASE)
    _MNEMONIC_PATTERNS = tuple(
        (
            mnemonic,
            operator,
            re.compile(rf"(?<=[A-Za-z0-9_\]\)]){mnemonic}(?=[A-Za-z0-9$\[])", re.IGNORECASE),
            re.compile(rf"\b{mnemonic}\b", re.IGNORECASE),
        )
        for mnemonic, operator in (
            ("GE", ">="),
            ("LE", "<="),
            ("GT", ">"),
            ("LT", "<"),
            ("EQ", "=="),
            ("NE", "!="),
        )
    )

    def evaluate(self, expression: str, state: CNCState) -> float:
        expression = str(expression or "").strip()
        if expression.startswith("="):
            expression = expression[1:].strip()
        if not expression:
            return 0.0
        if _PLAIN_FLOAT_RE.match(expression):
            return float(expression)
        return float(self._eval_python(self._to_python(expression, state), state))

    def is_true(self, expression: str, state: CNCState) -> bool:
        return bool(self._eval_python(self._to_python(expression, state), state))

    def replace_in_parameter(self, value: str, state: CNCState) -> str:
        value = str(value)
        if _PLAIN_FLOAT_RE.match(value):
            return format_number(float(value))
        if "=" in value:
            # Safely handle both "=EXPR" and buggy "A=EXPR" from parser overlaps
            _, expr = value.split("=", 1)
            try:
                return format_number(self.evaluate(expr, state))
            except Exception:
                return expr
        try:
            return format_number(self.evaluate(value, state))
        except Exception:
            return value

    def _to_python(self, expression: str, state: CNCState) -> str:
        expr = expression.strip()
        if expr.startswith("[") and expr.endswith("]"):
            expr = expr[1:-1]
        if _PLAIN_FLOAT_RE.match(expr):
            return expr
        expr = self._AND_RE.sub(" and ", expr)
        expr = self._OR_RE.sub(" or ", expr)
        expr = self._NOT_RE.sub(" not ", expr)
        expr = self._DIV_RE.sub(" // ", expr)
        expr = self._MOD_RE.sub(" % ", expr)
        expr = self._replace_mnemonic_comparisons(expr)
        if "<>" in expr:
            expr = expr.replace("<>", "!=")
        if "$" in expr:
            expr = self._SYSTEM_VAR_RE.sub(lambda match: str(self._read_system_variable(match.group(0), state)), expr)
        if "R" in expr or "r" in expr:
            expr = self._R_PARAM_RE.sub(lambda match: f"__r_{match.group(1)}", expr)

        if "[" in expr:
            scope = ensure_siemens_scope(state)

            def replace_array(match: re.Match) -> str:
                name = match.group(1)
                if name.upper() in _ALLOWED_FUNCS:
                    return match.group(0)
                index_value = int(float(self.evaluate(match.group(2), state)))
                if name in scope["arrays"]:
                    values = scope["arrays"].get(name, [])
                    if 0 <= index_value < len(values):
                        return str(values[index_value])
                return "0.0"

            previous = None
            while previous != expr and "[" in expr:
                previous = expr
                expr = self._NAME_INDEX_RE.sub(replace_array, expr)
        return expr

    def _replace_mnemonic_comparisons(self, expression: str) -> str:
        expr = expression
        upper = expr.upper()
        for mnemonic, operator, tight_re, word_re in self._MNEMONIC_PATTERNS:
            if mnemonic in upper:
                expr = tight_re.sub(operator, expr)
                expr = word_re.sub(operator, expr)
        return expr

    def _read_system_variable(self, token: str, state: CNCState) -> float:
        scope = ensure_siemens_scope(state)
        match = self._SYSTEM_VAR_TOKEN_RE.match(token)
        if not match:
            return 0.0
        name = match.group(1).upper()
        index_text = match.group(2)
        if name in {"$VA_IW", "$AA_IW", "$AA_MW"} and index_text:
            axis = index_text.strip().strip('"').upper()
            if name == "$AA_MW":
                return float(scope["system_variables"].get(f"$AA_MW[{axis}]", state.axes.get(axis, 0.0)))
            return float(state.axes.get(axis, 0.0))
        if name.startswith("$TC_DP"):
            return 0.0
        if name == "$P_UIFR" and index_text:
            return float(self.evaluate(index_text, state))
        return float(scope["system_variables"].get(token, 0.0))

    def _eval_python(self, expr: str, state: CNCState) -> Any:
        code = _compile_siemens_expr(expr)
        context = _LazySiemensEvalContext(state)
        return eval(code, {"__builtins__": {}}, context)

    def build_context(self, state: CNCState) -> Dict[str, Any]:
        scope = ensure_siemens_scope(state)
        context: Dict[str, Any] = {}
        for key, value in state.parameters.items():
            context[f"__r_{key}"] = float(value)
        for key, value in scope["symbols"].items():
            try:
                context[key] = float(value)
            except Exception:
                context[key] = value
        return context


class SiemensVariableHandler(Handler):
    """Handle Siemens DEF declarations, named assignments, and parameter resolution."""

    _DEF_RE = re.compile(r"^DEF\s+(INT|REAL|BOOL|CHAR|STRING(?:\[\d+\])?|AXIS|FRAME)\s+(.+)$", re.IGNORECASE)
    _ASSIGN_RE = re.compile(r"^(.+?)\s*=\s*(.+)$")
    _ARRAY_DEF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(\d+)\s*\]$")
    _R_VAR_RE = re.compile(r"^R(\d+)$", re.IGNORECASE)
    _SYS_VAR_LHS_RE = re.compile(r"^(\$[A-Za-z0-9_]+(?:\[[^\]]+\])?)$")
    _ARRAY_LHS_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\]]+)\s*\]$")
    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._evaluator = SiemensExpressionEvaluator()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[list], Optional[float]]:
        command = (node.variable_command or "").strip()
        cmd_params = node.command_parameter

        if command:
            scope = ensure_siemens_scope(state)
            if self._handle_definition(command, state, scope) or self._handle_assignment(command, state, scope):
                pass

        original_parameters = None
        if cmd_params and any(not _PLAIN_FLOAT_RE.match(str(v)) for v in cmd_params.values()):
            new_parameters = {
                key: (value if _PLAIN_FLOAT_RE.match(str(value)) else self._evaluator.replace_in_parameter(value, state))
                for key, value in cmd_params.items()
            }
            original_parameters = node._command_parameter
            node._command_parameter = new_parameters

        result = super().handle(node, state)

        if original_parameters is not None:
            node._command_parameter = original_parameters
        return result

    def _handle_definition(self, command: str, state: CNCState, scope: Dict[str, Any]) -> bool:
        if not command.upper().startswith("DEF"):
            return False
        match = self._DEF_RE.match(command)
        if not match:
            return False
        type_name = match.group(1).upper()
        declaration = match.group(2).strip()
        name_part, init_expr = (declaration.split("=", 1) + [None])[:2] if "=" in declaration else (declaration, None)
        name_part = name_part.strip()
        array_match = self._ARRAY_DEF_RE.match(name_part)
        if array_match:
            name = array_match.group(1)
            length = int(array_match.group(2))
            scope["types"][name] = type_name
            scope["arrays"][name] = [0.0] * length
            return True

        name = name_part.split()[0]
        scope["types"][name] = type_name
        if init_expr is not None:
            scope["symbols"][name] = self._cast_value(type_name, self._evaluator.evaluate(init_expr, state))
        else:
            scope["symbols"].setdefault(name, False if type_name == "BOOL" else 0.0)
        return True

    def _handle_assignment(self, command: str, state: CNCState, scope: Dict[str, Any]) -> bool:
        if "=" not in command:
            return False
        match = self._ASSIGN_RE.match(command)
        if not match:
            return False
        left = match.group(1).strip()
        right = match.group(2).strip()

        r_match = self._R_VAR_RE.match(left)
        if r_match:
            state.parameters[r_match.group(1)] = float(self._evaluator.evaluate(right, state))
            return True

        if left.startswith("$"):
            system_match = self._SYS_VAR_LHS_RE.match(left)
            if system_match:
                if left.upper().startswith("$P_UIFR"):
                    return False
                scope["system_variables"][left] = float(self._evaluator.evaluate(right, state))
                return True

        if "[" in left:
            array_match = self._ARRAY_LHS_RE.match(left)
            if array_match:
                name = array_match.group(1)
                index = int(float(self._evaluator.evaluate(array_match.group(2), state)))
                values = scope["arrays"].setdefault(name, [])
                while len(values) <= index:
                    values.append(0.0)
                values[index] = self._evaluator.evaluate(right, state)
                return True

        if self._IDENT_RE.match(left):
            type_name = scope["types"].get(left, "REAL")
            scope["symbols"][left] = self._cast_value(type_name, self._evaluator.evaluate(right, state))
            return True
        return False

    def _cast_value(self, type_name: str, value: float) -> Any:
        if type_name == "INT":
            return int(value)
        if type_name == "BOOL":
            return bool(value)
        return float(value)


__all__ = ["SiemensExpressionEvaluator", "SiemensVariableHandler"]