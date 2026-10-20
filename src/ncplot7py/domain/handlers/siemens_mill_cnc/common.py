"""Shared Siemens runtime helpers."""
from __future__ import annotations

from typing import Any, Dict

from ncplot7py.domain.cnc_state import CNCState


def ensure_siemens_scope(state: CNCState) -> Dict[str, Any]:
    """Return the Siemens runtime scope, creating default containers as needed."""
    scope = state.siemens_state.scope
    defaults = {
        "symbols": {},
        "types": {},
        "arrays": {},
        "labels": {},
        "flow": {},
        "system_variables": {},
        "frames": {},
        "transformations": {},
        "preprocess_stops": [],
        "path_mode": None,
        "axes_sync": "CP",
        "feed_forward": False,
        "diameter_mode": "DIAMOF",
        "diameter_axes": {},
        "workpiece": None,
    }
    for key, value in defaults.items():
        scope.setdefault(key, value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value)
    return scope


def format_number(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


__all__ = ["ensure_siemens_scope", "format_number"]