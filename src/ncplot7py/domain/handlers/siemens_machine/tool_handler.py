"""Tool-change handler for Siemens controls."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.base_tool_handler import BaseToolHandler
from ncplot7py.shared.nc_nodes import NCCommandNode


class SiemensToolHandler(BaseToolHandler, Handler):
    """Handle tool changes for Siemens controls."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        previous_tool = (
            state.tool_state.active_tool_code,
            state.tool_state.active_tool_number,
            state.tool_state.active_tool_name,
        )
        self._handle_tool_change(node, state)
        current_tool = (
            state.tool_state.active_tool_code,
            state.tool_state.active_tool_number,
            state.tool_state.active_tool_name,
        )
        tool_changed = "T" in node.command_parameter and current_tool != previous_tool and any(v is not None for v in current_tool)
        if tool_changed:
            return self._execute_tool_change_move(node, state)
        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None