"""Fanuc Turn maximum spindle speed clamp (G50 S)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class FanucTurnSpindleLimitHandler(Handler):
    """Handle the Fanuc turning maximum spindle-speed clamp."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        has_g50 = any(str(code).strip().upper() in {"G50", "G050"} for code in node.g_code)
        if has_g50 and "S" in node.command_parameter:
            state.spindle_limits.spindle_speed_maximum = float(node.command_parameter.pop("S"))

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None


__all__ = ["FanucTurnSpindleLimitHandler"]