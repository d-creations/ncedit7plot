"""Siemens SETAL user alarm handler."""
from __future__ import annotations

import re
from typing import Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.siemens_mill_cnc.variable_handler import SiemensExpressionEvaluator
from ncplot7py.shared.nc_nodes import NCCommandNode


class SiemensAlarmHandler(Handler):
    """Validate, record, and stop execution for Siemens SETAL commands."""

    _SETAL_RE = re.compile(
        r'^SETAL\s*\(\s*([^,()]+?)\s*(?:,\s*"([^"]*)"\s*)?\)'
        r'(?:\s*;\s*(.*))?$',
        re.IGNORECASE,
    )

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._evaluator = SiemensExpressionEvaluator()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[list], Optional[float]]:
        command = (node.variable_command or "").strip()
        if not command.upper().startswith("SETAL"):
            return super().handle(node, state)

        match = self._SETAL_RE.fullmatch(command)
        if match is None:
            raise_nc_error(
                ExceptionTyps.NCCodeErrors,
                0,
                message='Invalid SETAL syntax; expected SETAL(<alarm_no>[,"Alarm text"])',
                value=command,
                line=node.nc_code_line_nr or 0,
            )

        code = int(float(self._evaluator.evaluate(match.group(1), state)))
        if code < 0:
            raise_nc_error(
                ExceptionTyps.NCCodeErrors,
                code,
                message="SETAL alarm number must not be negative",
                value=code,
                line=node.nc_code_line_nr or 0,
            )

        message = (match.group(2) or match.group(3) or "").strip()
        state.channel_state.alarms.append(
            {"code": code, "message": message, "line": node.nc_code_line_nr}
        )
        raise_nc_error(
            ExceptionTyps.CNCError,
            code,
            message=message or "Siemens user alarm",
            value=code,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["SiemensAlarmHandler"]