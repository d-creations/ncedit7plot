"""Handler for Siemens ISO Feed Modes (G94/G95)."""
from __future__ import annotations

from typing import Optional, Tuple, List
from enum import Enum

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState


class FeedMode(Enum):
    INVERSE_TIME = "INVERSE_TIME"  # G93
    FEED_PER_MIN = "FEED_PER_MIN"  # G94
    FEED_PER_REV = "FEED_PER_REV"  # G95


class SiemensISOFeedHandler(Handler):
    """Handle Siemens G93 inverse time, G94 per minute, and G95 per revolution."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        selected_mode = None

        for g in node.g_code:
            if not isinstance(g, str):
                continue
            try:
                if g.upper().startswith("G"):
                    gnum = int(g[1:])
                else:
                    continue
            except Exception:
                continue

            if gnum == 93:
                selected_mode = FeedMode.INVERSE_TIME
            elif gnum == 94:
                selected_mode = FeedMode.FEED_PER_MIN
            elif gnum == 95:
                selected_mode = FeedMode.FEED_PER_REV

        if selected_mode is not None:
            state.channel_state.feed_mode = selected_mode
            state.spindle_limits.surface_speed_mode = "CONSTANT_REV"

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None
