"""Shared validation and compensation loading for tool changes."""
from __future__ import annotations

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.tool_compensation import ToolDataResolver
from ncplot7py.shared.nc_nodes import NCCommandNode


class BaseToolHandler:
    """Provide common tool validation and compensation loading."""

    def _handle_tool_change(self, node: NCCommandNode, state: CNCState) -> None:
        if "T" in node.command_parameter:
            self._activate_tool(node, state)
        policy = state.machine_config.tool_selection if state.machine_config else {}
        address = policy.get("offset_address")
        if address and address in node.command_parameter:
            raw_value = node.command_parameter[address]
            try:
                register = int(float(raw_value))
                if register < 0 or float(raw_value) != register:
                    raise ValueError("Invalid offset")
            except (ValueError, TypeError, OverflowError):
                raise_nc_error(
                    ExceptionTyps.NCCodeErrors, 200,
                    message="Offset selector must be a nonnegative integer", value=raw_value,
                )
            state.extra["active_offset_number"] = register
        if "T" in node.command_parameter or (address and address in node.command_parameter):
            self._load_tool_compensation(state)

    def _activate_tool(self, node: NCCommandNode, state: CNCState) -> None:
        t_str = node.command_parameter["T"]
        policy = state.machine_config.tool_selection if state.machine_config else {}
        mode = policy.get("mode", "direct")
        quoted = isinstance(t_str, str) and t_str.startswith('"') and t_str.endswith('"')

        try:
            if quoted:
                raise ValueError("Named tool")
            t_val = int(float(t_str))
            if float(t_str) != t_val or t_val < 0:
                raise_nc_error(ExceptionTyps.NCCodeErrors, 200, value=t_str)
            tool_number = t_val
            offset_number = None

            if mode == "star":
                digits = str(t_str).strip()
                tool_min, tool_max = policy.get("tool_digits", [3, 4])
                offset_min, offset_max = policy.get("offset_digits", [1, 2])
                if offset_min <= len(digits) <= offset_max:
                    state.extra["active_offset_number"] = t_val
                    return
                if not tool_min <= len(digits) <= tool_max or not digits.isdigit():
                    raise_nc_error(
                        ExceptionTyps.NCCodeErrors, 200,
                        message="STAR tool codes must use three or four digits; offsets use one or two digits",
                        value=t_str,
                    )

            if mode in {"packed", "station"}:
                divisor = 10 ** int(policy["offset_digits"])
                station, offset_number = divmod(t_val, divisor)
                if station == 0:
                    state.extra["active_offset_number"] = offset_number
                    return
                if mode == "station":
                    if t_val in policy.get("subtool_codes", []):
                        tool_number = t_val
                    elif offset_number == 0:
                        tool_number = station
                    else:
                        raise_nc_error(
                            ExceptionTyps.NCCodeErrors, 200,
                            message="Tool selection code is not configured for this machine",
                            value=t_str,
                        )
                else:
                    tool_number = station

            if state.machine_config:
                min_t, max_t = state.machine_config.tool_range
                range_number = station if mode in {"packed", "station"} else tool_number
                is_valid = min_t <= range_number <= max_t

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

            if mode == "packed":
                state.extra["active_offset_number"] = offset_number
            state.extra["active_tool_number"] = tool_number
            state.extra["current_tool_number"] = tool_number
            state.extra["active_tool_code"] = t_val
            state.extra["current_tool_code"] = t_val
            state.extra.pop("active_tool_name", None)
            state.extra.pop("current_tool_name", None)
        except ValueError:
            t_name = str(t_str)[1:-1] if quoted else str(t_str)
            if not policy.get("named_tools", True) or not t_name:
                raise_nc_error(ExceptionTyps.NCCodeErrors, 200, value=t_str)

            state.extra["active_tool_name"] = t_name
            state.extra["current_tool_name"] = t_name
            state.extra.pop("active_tool_number", None)
            state.extra.pop("active_tool_code", None)
            state.extra.pop("current_tool_number", None)
            state.extra.pop("current_tool_code", None)

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

    def _load_tool_compensation(self, state: CNCState) -> None:
        tool = ToolDataResolver().resolve(state, require_offset=False)
        state.extra.pop("pending_tool_radius", None)
        state.extra.pop("pending_tool_quadrant", None)
        if tool.radius is not None:
            state.extra["pending_tool_radius"] = tool.radius
        if tool.tip_orientation is not None:
            state.extra["pending_tool_quadrant"] = tool.tip_orientation