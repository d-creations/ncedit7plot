import ast
from functools import lru_cache
import math
import re
from typing import Any, Dict, Optional

from ncplot7py.domain.cnc_state import CNCState

def _sin_deg(x: float) -> float:
    return math.sin(math.radians(x))

def _cos_deg(x: float) -> float:
    return math.cos(math.radians(x))

def _tan_deg(x: float) -> float:
    return math.tan(math.radians(x))

def _asin_deg(x: float) -> float:
    return math.degrees(math.asin(x))

def _acos_deg(x: float) -> float:
    return math.degrees(math.acos(x))

def _atan_deg(x: float) -> float:
    return math.degrees(math.atan(x))

def _abs(x: float) -> float:
    return abs(x)

def _bin(x: float) -> float:
    return float(x)

def _bcd(x: float) -> float:
    return float(x)

def _round(x: float) -> float:
    if x >= 0:
        return math.floor(x + 0.5)
    return math.ceil(x - 0.5)

def _fix(x: float) -> float:
    return float(math.trunc(x))

def _fup(x: float) -> float:
    if x >= 0:
        return math.ceil(x)
    return math.floor(x)

_ALLOWED_FUNCS = {
    "sin": _sin_deg,    "cos": _cos_deg,    "tan": _tan_deg,
    "asin": _asin_deg,  "acos": _acos_deg,  "atan": _atan_deg,
    "sqrt": math.sqrt,  "abs": _abs,        "bin": _bin,
    "bcd": _bcd,        "round": _round,    "fix": _fix,
    "fup": _fup,        "pi": math.pi,
    "SIN": _sin_deg,    "COS": _cos_deg,    "TAN": _tan_deg,
    "ASIN": _asin_deg,  "ACOS": _acos_deg,  "ATAN": _atan_deg,
    "SQRT": math.sqrt,  "ABS": _abs,        "BIN": _bin,
    "BCD": _bcd,        "ROUND": _round,    "FIX": _fix,
    "FUP": _fup,        "PI": math.pi,
}

_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Load,
    ast.Name,
    ast.Constant,
    ast.Pow,
    ast.Sub,
    ast.Add,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.UAdd,
    ast.USub,
)

_PLAIN_FLOAT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


@lru_cache(maxsize=2048)
def _compile_safe_expr(expr: str):
    node = ast.parse(expr, mode="eval")
    for n in ast.walk(node):
        if not isinstance(n, _ALLOWED_AST_NODES):
            raise ValueError(f"Unsafe expression element: {type(n).__name__}")
    return compile(node, "<expr>", "eval")


@lru_cache(maxsize=32)
def _compile_var_regex(pattern: str) -> re.Pattern:
    return re.compile(pattern)


class _LazySafeEvalCtx(dict):
    """Lazy evaluation mapping that resolves variables on demand from CNCState."""

    def __init__(self, state: Optional[CNCState] = None, variables: Optional[Dict[str, float]] = None) -> None:
        super().__init__()
        self._state = state
        self._variables = variables

    def __missing__(self, key: str) -> Any:
        if key in _ALLOWED_FUNCS:
            return _ALLOWED_FUNCS[key]
        if self._variables is not None and key in self._variables:
            return self._variables[key]
        state = self._state
        if state is not None and key.startswith("v"):
            raw_key = key[1:]
            params = state.parameters
            if params:
                if raw_key in params:
                    try:
                        return float(params[raw_key])
                    except Exception:
                        return 0.0
                hash_key = f"#{raw_key}"
                if hash_key in params:
                    try:
                        return float(params[hash_key])
                    except Exception:
                        return 0.0
            if state.machine_state is not None and state.machine_state.global_parameters:
                gparams = state.machine_state.global_parameters
                if raw_key in gparams:
                    try:
                        return float(gparams[raw_key])
                    except Exception:
                        return 0.0
                hash_key = f"#{raw_key}"
                if hash_key in gparams:
                    try:
                        return float(gparams[hash_key])
                    except Exception:
                        return 0.0
        return 0.0


def _safe_eval(expr: str, variables: Optional[Dict[str, float]] = None, state: Optional[CNCState] = None) -> float:
    """Evaluate a restricted arithmetic expression safely."""
    code = _compile_safe_expr(expr)
    ctx = _LazySafeEvalCtx(state=state, variables=variables)
    return float(eval(code, {"__builtins__": {}}, ctx))


class ExpressionEvaluator:
    """Evaluates mathematical expressions with variables based on CNC state."""

    # Match innermost bracket expressions (no nested '[' or ']' inside)
    BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")

    def __init__(self):
        pass

    def get_var_regex(self, state: CNCState) -> re.Pattern:
        if state.machine_config and state.machine_config.variable_pattern:
            return _compile_var_regex(state.machine_config.variable_pattern)
        return _compile_var_regex(r"#(\d+)")

    def _build_variable_map(self, state: CNCState) -> Dict[str, float]:
        class SafeVarMap(dict):
            def __missing__(self, key: str) -> float:
                return 0.0

        vm = SafeVarMap()
        # Merge global machine parameters if available
        if state.machine_state is not None:
            for k, v in (state.machine_state.global_parameters or {}).items():
                vm_key = f"v{k.lstrip('#')}"
                try:
                    vm[vm_key] = float(v)
                except Exception:
                    vm[vm_key] = 0.0
        for k, v in (state.parameters or {}).items():
            vm_key = f"v{k.lstrip('#') if isinstance(k, str) else k}"
            try:
                vm[vm_key] = float(v)
            except Exception:
                vm[vm_key] = 0.0
        return vm

    def _replace_vars_in_expr(self, expr: str, state: CNCState) -> str:
        var_re = self.get_var_regex(state)
        return var_re.sub(lambda m: f"v{m.group(1)}", expr)

    def evaluate(self, expr: str, state: CNCState) -> float:
        expr = expr.strip()
        if not expr:
            return 0.0
        if _PLAIN_FLOAT_RE.match(expr):
            return float(expr)
        expr_py = expr.replace('[', '(').replace(']', ')') if ('[' in expr or ']' in expr) else expr
        if _PLAIN_FLOAT_RE.match(expr_py):
            return float(expr_py)
        expr_py = self._replace_vars_in_expr(expr_py, state)
        return _safe_eval(expr_py, state=state)

    def eval_and_replace_in_string(self, s: str, state: CNCState) -> str:
        if "[" not in s:
            return s

        def repl(m: re.Match) -> str:
            inner = m.group(1)
            val = self.evaluate(inner, state)
            if float(val).is_integer():
                return str(int(val))
            return str(val)

        out = s
        max_iters = 50
        it = 0
        while "[" in out:
            new_out = self.BRACKET_RE.sub(repl, out)
            if new_out == out:
                break
            out = new_out
            it += 1
            if it >= max_iters:
                break
        return out
