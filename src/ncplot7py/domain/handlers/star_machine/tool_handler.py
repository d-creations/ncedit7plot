"""Tool-change handler for Star Fanuc controls."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.fanuc_machine.tool_handler import FanucToolHandler
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarFanucToolHandler(FanucToolHandler):
    """Handle Star Fanuc tool changes and move to the configured or tool-specific position."""

    TOOL_CHANGE_POSITIONS = {
        1100: {"B": 0.0, "Y": 0.0},
    }

    def _resolve_tool_change_position(self, state: CNCState) -> dict[str, float]:
        target = super()._resolve_tool_change_position(state)
        if not target:
            return {"B": 0.0, "Y": 0.0}
        return target

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        previous_tool = state.tool_state.active_tool_code
        self._handle_tool_change(node, state)
        if "T" not in node.command_parameter or state.tool_state.active_tool_code == previous_tool or state.tool_state.active_tool_code is None:
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        return self._execute_tool_change_move(node, state)