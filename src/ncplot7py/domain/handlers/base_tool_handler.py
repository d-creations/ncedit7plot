"""Shared validation and compensation loading for tool changes."""
from __future__ import annotations

import logging

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.shared.nc_nodes import NCCommandNode

logger = logging.getLogger(__name__)


class BaseToolHandler:
    """Provide common tool validation and compensation loading."""

    def _handle_tool_change(self, node: NCCommandNode, state: CNCState) -> None:
        if "T" in node.command_parameter:
            self._activate_tool(node, state)

    def _activate_tool(self, node: NCCommandNode, state: CNCState) -> None:
        t_str = node.command_parameter["T"]

        try:
            t_val = int(float(t_str))
            tool_number = t_val

            if state.machine_config:
                min_t, max_t = state.machine_config.tool_range
                is_valid = min_t <= t_val <= max_t

                if not is_valid and "FANUC" in state.machine_config.control_type and t_val >= 100:
                    potential_tool = t_val // 100
                    if min_t <= potential_tool <= max_t:
                        is_valid = True
                        tool_number = potential_tool

                if not is_valid:
                    raise_nc_error(
                        ExceptionTyps.NCCodeErrors,
                        200,
                        message=(
                            f"Tool number T{t_val} out of range ({min_t}-{max_t}) "
                            f"for {state.machine_config.name}"
                        ),
                        value=t_str,
                        line=getattr(node, "nc_code_line_nr", 0) or 0,
                    )

            if tool_number == 0:
                self._clear_active_tool(state)
                return

            state.extra["active_tool_number"] = tool_number
            state.extra["current_tool_number"] = tool_number
            state.extra["active_tool_code"] = t_val
            state.extra["current_tool_code"] = t_val
            state.extra.pop("active_tool_name", None)
            state.extra.pop("current_tool_name", None)
            self._load_tool_compensation(tool_number, t_val, state)
        except ValueError:
            t_name = str(t_str).replace('"', "").replace("'", "")
            if t_name in {"", "0"}:
                self._clear_active_tool(state)
                return

            state.extra["active_tool_name"] = t_name
            state.extra["current_tool_name"] = t_name
            state.extra.pop("active_tool_number", None)
            state.extra.pop("active_tool_code", None)
            state.extra.pop("current_tool_number", None)
            state.extra.pop("current_tool_code", None)
            self._load_tool_compensation(t_name, t_name, state)

    @staticmethod
    def _clear_active_tool(state: CNCState) -> None:
        for key in (
            "active_tool_number",
            "active_tool_name",
            "active_tool_code",
            "current_tool_number",
            "current_tool_name",
            "current_tool_code",
        ):
            state.extra.pop(key, None)

    def _load_tool_compensation(
        self, tool_key: int | str, display_tool: int | str, state: CNCState
    ) -> None:
        tool_comp_data = state.extra.get("tool_compensation_data", {})
        if tool_key not in tool_comp_data:
            return

        tool_data = tool_comp_data[tool_key]
        r_value = tool_data.get("rValue")
        if r_value is not None:
            try:
                state.extra["pending_tool_radius"] = float(r_value)
            except (ValueError, TypeError) as error:
                logger.warning(
                    "Invalid tool radius value '%s' for tool T%s: %s",
                    r_value,
                    display_tool,
                    error,
                )

        q_value = tool_data.get("qValue")
        if q_value is not None:
            try:
                state.extra["pending_tool_quadrant"] = int(q_value)
            except (ValueError, TypeError) as error:
                logger.warning(
                    "Invalid tool quadrant value '%s' for tool T%s: %s",
                    q_value,
                    display_tool,
                    error,
                )