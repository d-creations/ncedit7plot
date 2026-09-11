"""State-only command handling for G40/G41/G42 compensation."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.tool_compensation import ToolDataResolver
from ncplot7py.shared.nc_nodes import NCCommandNode


class RadiusCompensationCommandHandler(Handler):
    """Update compensation state while leaving point generation downstream."""

    def handle(
        self,
        node: NCCommandNode,
        state: CNCState,
    ) -> Tuple[Optional[List], Optional[float]]:
        command = self._get_command(node)
        if command == "G40":
            state.tool_compensation.radius_mode = "OFF"
            state.tool_compensation.radius = None
            state.tool_compensation.startup_pending = False
            state.tool_radius = None
        elif command in {"G41", "G42"} or state.tool_compensation.radius_mode != "OFF":
            tool = ToolDataResolver().resolve(state)
            line_number = getattr(node, "nc_code_line_nr", 0) or 0
            if tool.tool_id is None:
                raise_nc_error(
                    ExceptionTyps.NCCodeErrors,
                    -103,
                    message="Tool compensation cannot be activated without an active tool",
                    line=line_number,
                )
            if tool.radius is None or tool.radius <= 0.0:
                raise_nc_error(
                    ExceptionTyps.NCCodeErrors,
                    -100,
                    message=f"Tool radius compensation requires radius R for tool {tool.tool_id}",
                    value=str(tool.tool_id),
                    line=line_number,
                )

            if command in {"G41", "G42"}:
                if state.tool_compensation.radius_mode == "OFF":
                    state.tool_compensation.startup_pending = (
                        state.machine_config is not None
                        and state.machine_config.control_type == "FANUC"
                    )
                state.tool_compensation.radius_mode = "LEFT" if command == "G41" else "RIGHT"
            state.tool_compensation.radius = tool.radius
            state.tool_compensation.tip_orientation = tool.tip_orientation
            state.tool_compensation.edge_number = tool.edge_number
            state.tool_compensation.activation_line = line_number
            state.tool_radius = tool.radius
            state.tool_quadrant = tool.tip_orientation

        return super().handle(node, state)

    @staticmethod
    def _get_command(node: NCCommandNode) -> Optional[str]:
        for code in node.g_code:
            normalized = str(code).strip().upper()
            if normalized in {"G40", "G040"}:
                return "G40"
            if normalized in {"G41", "G041"}:
                return "G41"
            if normalized in {"G42", "G042"}:
                return "G42"
        return None


__all__ = ["RadiusCompensationCommandHandler"]