"""FANUC custom macro alarm handler."""
from __future__ import annotations

import re
from typing import Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.expression_evaluator import ExpressionEvaluator
from ncplot7py.shared.nc_nodes import NCCommandNode


class FanucAlarmHandler(Handler):
    """Stop execution when a custom macro writes system variable #3000."""

    _ALARM_RE = re.compile(r"^\s*#\s*3000\s*=\s*([^()]+?)\s*((?:\([^)]*\)\s*)*)$", re.IGNORECASE)
    _MESSAGE_RE = re.compile(r"\(([^)]*)\)")

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._evaluator = ExpressionEvaluator()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[list], Optional[float]]:
        command = node.variable_command or ""
        match = self._ALARM_RE.match(command)
        if not match:
            return super().handle(node, state)

        alarm_value = int(float(self._evaluator.evaluate(match.group(1).strip(), state)))
        if not 0 <= alarm_value <= 200:
            raise_nc_error(
                ExceptionTyps.NCCodeErrors,
                3000,
                message="#3000 alarm value must be between 0 and 200",
                value=alarm_value,
                line=node.nc_code_line_nr or 0,
            )

        messages = self._MESSAGE_RE.findall(match.group(2))
        message = messages[0].strip() if messages else "Macro alarm"
        alarm_code = 3000 + alarm_value
        state.channel_state.alarms.append(
            {"code": alarm_code, "message": message, "line": node.nc_code_line_nr}
        )
        raise_nc_error(
            ExceptionTyps.CNCError,
            alarm_code,
            message=message,
            value=alarm_value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["FanucAlarmHandler"]