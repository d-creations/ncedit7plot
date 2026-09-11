"""Tool-change handler for Star Fanuc controls."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.fanuc_machine.tool_handler import FanucToolHandler
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarFanucToolHandler(FanucToolHandler):
    """Handle Star Fanuc tool changes and return the B axis to zero."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        previous_tool = state.extra.get("active_tool_code")
        self._handle_tool_change(node, state)
        if "T" not in node.command_parameter or state.extra.get("active_tool_code") == previous_tool:
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        reset_node = NCCommandNode(
            g_code_command={"G0"},
            command_parameter={"B": "0"},
            nc_code_line_nr=node.nc_code_line_nr,
        )
        if self.next_handler is None:
            state.set_axis("B", 0.0)
            return None, None

        reset_points, reset_duration = self.next_handler.handle(reset_node, state)
        points, duration = self.next_handler.handle(node, state)
        combined_points = (reset_points or []) + (points or [])
        combined_duration = (reset_duration or 0.0) + (duration or 0.0)
        return combined_points or None, combined_duration