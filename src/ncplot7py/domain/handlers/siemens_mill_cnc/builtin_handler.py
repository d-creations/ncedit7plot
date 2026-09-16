"""Siemens built-in command markers used by plotting."""
from __future__ import annotations

import re
from typing import Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.handlers.siemens_mill_cnc.common import ensure_siemens_scope
from ncplot7py.domain.handlers.siemens_mill_cnc.variable_handler import SiemensExpressionEvaluator


class SiemensBuiltinHandler(Handler):
    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._evaluator = SiemensExpressionEvaluator()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[list], Optional[float]]:
        scope = ensure_siemens_scope(state)
        command = (node.variable_command or "").strip()
        upper = command.upper()

        if re.match(r"^SPOSA?\s*=", command, re.IGNORECASE):
            command_name, value = command.split("=", 1)
            position = self._evaluator.evaluate(value, state)
            scope["spindle_position"] = position
            state.extra["siemens.c_axis_mode"] = "positionControlled"
            state.extra["siemens.c_axis_position"] = position
            state.extra["siemens.c_axis_command"] = command_name.strip().upper()
        elif upper == "RET" or upper == "M17":
            state.extra["program_returned"] = True
        elif upper == "STOPRE":
            scope["preprocess_stops"].append(node.nc_code_line_nr)
        elif upper.startswith("MSG"):
            state.extra.setdefault("messages", []).append({"message": command, "line": node.nc_code_line_nr})
        elif upper.startswith("WORKPIECE"):
            scope["workpiece"] = True
        elif upper.startswith("NEWCONF"):
            scope["newconf"] = True
        elif upper.startswith("NULLPUNKT"):
            scope["nullpunkt"] = True
        elif upper.startswith("GETEXET"):
            scope["getexet"] = True
        elif upper.startswith("MCALL"):
            scope["mcall"] = upper.replace("MCALL", "").strip() or None
        elif upper in {"CP", "PTP", "PTPG0"}:
            scope["axes_sync"] = upper
        elif upper in {"FFWON", "FFWOF"}:
            scope["feed_forward"] = upper
        elif upper in {"DIAMON", "DIAMOF", "DIAM90"}:
            scope["diameter_mode"] = upper

        return super().handle(node, state)


__all__ = ["SiemensBuiltinHandler"]