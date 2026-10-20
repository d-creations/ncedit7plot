"""Handler for Fanuc Mill plane selection (G17/G18/G19) -- Group 2.

Updates the current working plane in the `CNCState`. Conflicting codes
are handled by the FanucMillGCodeGroupValidator.
"""
from __future__ import annotations

from typing import Optional, Tuple, List
from enum import Enum

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState

class FanucMillPlaneMode(Enum):
    X_Y = "X_Y"  # G17
    X_Z = "X_Z"  # G18
    Y_Z = "Y_Z"  # G19

class FanucMillGroup2PlaneHandler(Handler):
    """Handle Fanuc Mill G17/G18/G19 plane selection (Group 2)."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        for g in node.g_code:
            if not isinstance(g, str):
                continue
            try:
                g_upper = g.upper()
                if g_upper.startswith("G"):
                    num = float(g_upper[1:])
                    if num == 17:
                        state.channel_state.plane = FanucMillPlaneMode.X_Y.value
                    elif num == 18:
                        state.channel_state.plane = FanucMillPlaneMode.X_Z.value
                    elif num == 19:
                        state.channel_state.plane = FanucMillPlaneMode.Y_Z.value
            except Exception:
                pass

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None

__all__ = ["FanucMillGroup2PlaneHandler", "FanucMillPlaneMode"]
