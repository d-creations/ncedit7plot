"""Shared validation and compensation loading for tool changes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.tool_compensation import ToolDataResolver
from ncplot7py.shared.nc_nodes import NCCommandNode


class BaseToolHandler:
    """Provide common tool validation, compensation loading, and tool-change positioning."""

    TOOL_CHANGE_POSITIONS: Dict[Any, Dict[str, float]] = {}

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
            state.tool_state.active_offset_number = register
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
                    state.tool_state.active_offset_number = t_val
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
                    state.tool_state.active_offset_number = offset_number
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
                state.tool_state.active_offset_number = offset_number
            state.tool_state.active_tool_number = tool_number
            state.tool_state.current_tool_number = tool_number
            state.tool_state.active_tool_code = t_val
            state.tool_state.current_tool_code = t_val
            state.tool_state.active_tool_name = None
            state.tool_state.current_tool_name = None
        except ValueError:
            t_name = str(t_str)[1:-1] if quoted else str(t_str)
            if not policy.get("named_tools", True) or not t_name:
                raise_nc_error(ExceptionTyps.NCCodeErrors, 200, value=t_str)

            state.tool_state.active_tool_name = t_name
            state.tool_state.current_tool_name = t_name
            state.tool_state.active_tool_number = None
            state.tool_state.active_tool_code = None
            state.tool_state.current_tool_number = None
            state.tool_state.current_tool_code = None

    @staticmethod
    def _clear_active_tool(state: CNCState) -> None:
        state.tool_state.active_tool_number = None
        state.tool_state.active_tool_name = None
        state.tool_state.active_tool_code = None
        state.tool_state.current_tool_number = None
        state.tool_state.current_tool_name = None
        state.tool_state.current_tool_code = None

    def _load_tool_compensation(self, state: CNCState) -> None:
        tool = ToolDataResolver().resolve(state, require_offset=False)
        state.tool_state.pending_tool_radius = tool.radius
        state.tool_state.pending_tool_quadrant = tool.tip_orientation

    def _resolve_tool_change_position(self, state: CNCState) -> Dict[str, float]:
        """Resolve the target axis coordinates for the newly activated tool."""
        config = getattr(state, "machine_config", None)
        tc_config = getattr(config, "tool_change_position", {}) if config is not None else {}
        if not isinstance(tc_config, dict):
            tc_config = {}

        target: Dict[str, float] = {}
        default_pos = tc_config.get("default", {})
        if isinstance(default_pos, dict):
            for ax, val in default_pos.items():
                try:
                    target[str(ax).upper()] = float(val)
                except (TypeError, ValueError):
                    pass

        by_channel = tc_config.get("by_channel", {})
        if isinstance(by_channel, dict):
            ch_id = str(state.channel_state.path_number or 1)
            ch_pos = by_channel.get(ch_id) or by_channel.get(f"C{ch_id}")
            if isinstance(ch_pos, dict):
                for ax, val in ch_pos.items():
                    try:
                        target[str(ax).upper()] = float(val)
                    except (TypeError, ValueError):
                        pass

        tool_keys: List[str] = []
        if state.tool_state.active_tool_code is not None:
            tool_keys.append(str(state.tool_state.active_tool_code))
        if state.tool_state.active_tool_number is not None:
            tool_keys.append(str(state.tool_state.active_tool_number))
        if state.tool_state.active_tool_name is not None:
            tool_keys.append(str(state.tool_state.active_tool_name))

        by_tool = tc_config.get("by_tool", {})
        if isinstance(by_tool, dict):
            for key in tool_keys:
                if key in by_tool and isinstance(by_tool[key], dict):
                    for ax, val in by_tool[key].items():
                        try:
                            target[str(ax).upper()] = float(val)
                        except (TypeError, ValueError):
                            pass
                    break

        for key in (
            state.tool_state.active_tool_code,
            state.tool_state.active_tool_number,
            state.tool_state.active_tool_name,
            *tool_keys,
        ):
            if key is not None and key in self.TOOL_CHANGE_POSITIONS:
                for ax, val in self.TOOL_CHANGE_POSITIONS[key].items():
                    try:
                        target[str(ax).upper()] = float(val)
                    except (TypeError, ValueError):
                        pass
                break

        return target

    def _execute_tool_change_move(
        self,
        node: NCCommandNode,
        state: CNCState,
        target_axes: Optional[Dict[str, float]] = None,
    ) -> Tuple[Optional[List], Optional[float]]:
        """Move to the resolved tool-change position and then delegate `node`."""
        resolved_targets = target_axes if target_axes is not None else self._resolve_tool_change_position(state)
        next_handler = getattr(self, "next_handler", None)
        if not resolved_targets:
            if next_handler is not None:
                return next_handler.handle(node, state)
            return None, None

        command_params = {str(axis).upper(): str(val) for axis, val in resolved_targets.items()}
        reset_node = NCCommandNode(
            g_code_command={"G0"},
            command_parameter=command_params,
            nc_code_line_nr=node.nc_code_line_nr,
        )
        if next_handler is None:
            for axis, val in resolved_targets.items():
                state.set_axis(str(axis).upper(), float(val))
            return None, None

        reset_start = state.axes.copy()
        reset_points, reset_duration = next_handler.handle(reset_node, state)
        reset_moved = any(
            reset_start.get(axis, 0.0) != state.axes.get(axis, 0.0)
            for axis in reset_start.keys() | state.axes.keys()
        )
        points, duration = next_handler.handle(node, state)
        if reset_moved and reset_points and not points:
            node.set_motion_metadata(
                reset_node.motion_geometry,
                reset_node.motion_traversal,
                reset_node.motion_source_code,
            )
        combined_points = (reset_points or []) + (points or [])
        combined_duration = (reset_duration or 0.0) + (duration or 0.0)
        return combined_points or None, combined_duration