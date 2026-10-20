"""Handler for Siemens ISO Mill plane selection (G17/G18/G19) -- Group 6.

Updates the current working plane in the `CNCState`.
It detects conflicting codes and raises an NC error when multiple plane
codes are present in the same block.
"""
from __future__ import annotations

from typing import Optional, Tuple, List

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import raise_nc_error, ExceptionTyps

class SiemensGroup6PlaneHandler(Handler):
    """Handle Siemens G17/G18/G19 plane selection (Group 6)."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        has17 = False
        has18 = False
        has19 = False

        for g in node.g_code:
            if not isinstance(g, str):
                continue
            try:
                g_upper = g.upper()
                if g_upper.startswith("G"):
                    num = float(g_upper[1:])
                    if num == 17:
                        has17 = True
                    elif num == 18:
                        has18 = True
                    elif num == 19:
                        has19 = True
            except Exception:
                pass

        if (has17 and has18) or (has17 and has19) or (has18 and has19):
            raise_nc_error(ExceptionTyps.NCCodeErrors, 120, message="Conflicting plane selection codes (G17/G18/G19)", value=str(node.g_code))

        if has17:
            state.channel_state.plane = "X_Y"
        if has18:
            state.channel_state.plane = "X_Z"
        if has19:
            state.channel_state.plane = "Y_Z"

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None

__all__ = ["SiemensGroup6PlaneHandler"]
