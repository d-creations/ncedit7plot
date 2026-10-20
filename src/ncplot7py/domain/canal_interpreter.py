"""Step-by-step NC program interpreter and motion context projector for a single canal."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionNode, ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.tool_compensation import ToolPathCompensator
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


def _format_node_debug(node: Optional[NCCommandNode]) -> Dict[str, Any]:
    if node is None:
        return {}
    return {
        "line": getattr(node, "nc_code_line_nr", None),
        "g_code": sorted(getattr(node, "g_code", set()) or []),
        "command_parameter": dict(getattr(node, "command_parameter", {}) or {}),
        "loop_command": repr(getattr(node, "loop_command", None)),
        "variable_command": repr(getattr(node, "variable_command", None)),
        "dddp_command": sorted(getattr(node, "dddp_command", set()) or []),
    }


class CanalProgramInterpreter:
    """Executes linked NCCommandNodes against a CNCState and Handler chain."""

    def __init__(self, tool_path_compensator: Optional[ToolPathCompensator] = None) -> None:
        self._tool_path_compensator = tool_path_compensator or ToolPathCompensator()

    @property
    def tool_path_compensator(self) -> ToolPathCompensator:
        return self._tool_path_compensator

    @staticmethod
    def axis_for_workpiece(simulation: Dict[str, object], carrier_id: str) -> str:
        for carrier in simulation.get("carriers", []):
            if carrier.get("id") != carrier_id:
                continue
            for joint in carrier.get("rotationChain", []):
                return str(joint["axisId"])
        return ""

    @classmethod
    def initialize_configured_target(cls, channel_name: str, state: CNCState) -> None:
        from ncplot7py.domain.handlers.axis_binding import AxisBindingHandler

        AxisBindingHandler.apply_bindings(state)

        config = getattr(state, "machine_config", None)
        simulation = getattr(config, "simulation", None)
        if not isinstance(simulation, dict):
            return
        channel_id = str(state.channel_state.path_number or 1)
        for mount in simulation.get("toolMounts", []):
            target = mount.get("target", {})
            if str(mount.get("channelId")) not in (channel_id, str(channel_name)) or target.get("mode") != "execution":
                continue
            carrier = target.get("defaultWorkpieceCarrierId")
            if carrier:
                if state.star_state.target_carrier_id is None:
                    state.star_state.target_carrier_id = carrier
                if state.star_state.target_axis is None:
                    state.star_state.target_axis = cls.axis_for_workpiece(simulation, carrier)
            break

    @classmethod
    def resolve_motion_target(cls, channel_name: str, state: CNCState) -> Optional[Dict[str, str]]:
        """Resolve the executed tool carrier and workpiece target for this motion."""
        config = getattr(state, "machine_config", None)
        simulation = getattr(config, "simulation", None)
        if not isinstance(simulation, dict):
            return None

        active_tool = state.tool_state.active_tool_number
        if active_tool is None:
            active_tool = state.tool_state.active_tool_name
        channel_id = str(channel_name)
        for mount in simulation.get("toolMounts", []):
            if str(mount.get("channelId")) != channel_id:
                continue
            selector = mount.get("tools", {})
            selected = False
            if selector.get("kind") == "numericRange" and type(active_tool) is int:
                selected = selector.get("from", 1) <= active_tool <= selector.get("to", 0)
            elif selector.get("kind") == "identifiers":
                selected = active_tool in selector.get("values", [])
            if not selected:
                continue
            target = mount.get("target", {})
            if target.get("mode") == "fixed":
                workpiece = target.get("workpieceCarrierId")
                return {
                    "toolCarrierId": str(mount["carrierId"]),
                    "targetCarrierId": str(workpiece),
                    "targetAxis": cls.axis_for_workpiece(simulation, str(workpiece)),
                }
            selected_target = state.star_state.target_carrier_id
            allowed = target.get("allowedWorkpieceCarrierIds", [])
            if selected_target in allowed:
                return {
                    "toolCarrierId": str(mount["carrierId"]),
                    "targetCarrierId": str(selected_target),
                    "targetAxis": str(state.star_state.target_axis or cls.axis_for_workpiece(simulation, selected_target)),
                }
            return None
        return None

    @classmethod
    def capture_motion_context(
        cls,
        channel_name: str,
        state: CNCState,
        start_axes: Optional[Dict[str, float]] = None,
    ) -> Dict[str, object]:
        """Detach state required by later kinematics from this exact motion."""
        configured_axes = getattr(state.machine_config, "axes", ())
        axes = {
            axis: float(state.axes[axis])
            for axis in configured_axes
            if axis in state.axes
        }
        compensation = state.tool_compensation
        tool_offset = {
            "number": state.tool_state.active_offset_number,
            "radiusMode": compensation.radius_mode,
            "radius": compensation.radius,
            "tipOrientation": compensation.tip_orientation,
            "edgeNumber": compensation.edge_number,
        }
        machining_mode = getattr(state, "machining_mode", "unknown") or "unknown"
        context: Dict[str, object] = {
            "channelId": str(channel_name),
            "startAxes": dict(start_axes) if start_axes is not None else dict(axes),
            "endAxes": axes,
            "toolOffset": {key: value for key, value in tool_offset.items() if value is not None},
            "machiningMode": machining_mode,
        }
        c_axis_mode = state.star_state.c_axis_mode or state.siemens_state.c_axis_mode
        if c_axis_mode:
            context["workpieceRotationMode"] = c_axis_mode
        target = cls.resolve_motion_target(channel_name, state)
        if target is not None:
            context.update(target)
        if "workpieceRotationMode" not in context:
            config = getattr(state, "machine_config", None)
            simulation = getattr(config, "simulation", None)
            if isinstance(simulation, dict) and getattr(config, "machine_type", "") in {"TURN", "TURN_MILL"}:
                context["workpieceRotationMode"] = "spindleInvariant"
        return context

    def execute(
        self,
        channel_name: str,
        nodes: List[NCCommandNode],
        state: CNCState,
        chain: Optional[Handler],
        tool_path: Optional[List[Tuple[List[Point], float]]] = None,
        tool_nodes: Optional[List[NCCommandNode]] = None,
        exec_sequence: Optional[List[NCCommandNode]] = None,
    ) -> Tuple[List[Tuple[List[Point], float]], List[NCCommandNode], List[NCCommandNode]]:
        """Run the linked command node list through the handler chain."""
        if exec_sequence is None:
            exec_sequence = []
        else:
            exec_sequence.clear()
        if tool_path is None:
            tool_path = []
        else:
            tool_path.clear()
        if tool_nodes is None:
            tool_nodes = []
        else:
            tool_nodes.clear()
        self._tool_path_compensator.reset()

        for i in range(len(nodes) - 1):
            nodes[i]._next_ncCode = nodes[i + 1]
            nodes[i + 1]._before_ncCode = nodes[i]

        current_handler = chain
        while current_handler is not None:
            if hasattr(current_handler, "setup_maps"):
                try:
                    current_handler.setup_maps(nodes)
                except Exception:
                    pass
            current_handler = getattr(current_handler, "next_handler", None)

        node = nodes[0] if len(nodes) > 0 else None
        config_max = getattr(state.machine_config, "max_execution_nodes", 0) if getattr(state, "machine_config", None) else 0
        max_steps = config_max if config_max > 0 else max(100000, len(nodes) * 100)

        steps = 0
        logger = logging.getLogger(__name__)

        while node is not None and steps < max_steps:
            try:
                exec_sequence.append(node)
            except Exception:
                pass

            pts, dur = None, 0.0
            start_axes = {
                axis: float(state.axes[axis])
                for axis in getattr(state.machine_config, "axes", ())
                if axis in state.axes
            }
            if chain is not None:
                try:
                    pts, dur = chain.handle(node, state)
                except ExceptionNode:
                    raise
                except Exception as exc:
                    logger.error(
                        "NC execution failure at line=%s node=%s prev=%s next=%s state_parameters=%s siemens=%s",
                        getattr(node, "nc_code_line_nr", 0) or 0,
                        _format_node_debug(node),
                        _format_node_debug(getattr(node, "_before_ncCode", None)),
                        _format_node_debug(getattr(node, "_next_ncCode", None)),
                        dict(getattr(state, "parameters", {}) or {}),
                        dict(state.siemens_state.scope or {}),
                        exc_info=True,
                    )
                    raise_nc_error(
                        ExceptionTyps.NCCodeErrors,
                        1999,
                        message=str(exc),
                        value=str(exc),
                        line=getattr(node, "nc_code_line_nr", 0) or 0,
                    )

            if logger.isEnabledFor(logging.DEBUG):
                try:
                    ln = getattr(node, "nc_code_line_nr", None)
                    g = getattr(node, "g_code", None)
                    logger.debug("node idx=%s line=%s g_code=%s -> pts=%s dur=%s", steps, ln, g, "Y" if pts is not None else "N", dur)
                except Exception:
                    logger.debug("node idx=%s -> pts=%s dur=%s", steps, "Y" if pts is not None else "N", dur)

            if state.tool_compensation.radius_mode == "OFF":
                self._tool_path_compensator.reset()

            if pts is not None:
                motion_node = node.copy()
                active_tool = state.tool_state.active_tool_number
                if active_tool is None:
                    active_tool = state.tool_state.active_tool_name
                motion_node.set_execution_metadata(
                    execution_step=steps,
                    tool_number=active_tool if active_tool is not None else "unknown",
                    motion_context=self.capture_motion_context(channel_name, state, start_axes),
                )
                generated_segments = getattr(node, "generated_motion_segments", [])
                if generated_segments:
                    for segment in generated_segments:
                        segment_points = segment.get("points")
                        if not isinstance(segment_points, list) or not segment_points:
                            continue
                        segment_node = motion_node.copy()
                        segment_node.set_motion_metadata(
                            str(segment.get("geometry", "LINEAR")),
                            str(segment.get("traversal", "FEED")),
                            str(segment.get("source_code", "G01")),
                        )
                        segment_node.set_generated_motion_segments([])
                        projected_points = self._tool_path_compensator.project(segment_points, state)
                        tool_path.append((projected_points, float(segment.get("duration", 0.0))))
                        tool_nodes.append(segment_node)
                else:
                    projected_points = self._tool_path_compensator.project(pts, state)
                    tool_path.append((projected_points, dur or 0.0))
                    tool_nodes.append(motion_node)
            else:
                wait_info = getattr(node, "extra", {}).get("wait_code") if hasattr(node, "extra") and node.extra else None
                if wait_info:
                    non_motion_node = node.copy()
                    tool_path.append(([], 0.0))
                    tool_nodes.append(non_motion_node)

            next_node = getattr(node, "_next_ncCode", None)
            if next_node is node:
                break
            node = next_node
            steps += 1

        return tool_path, tool_nodes, exec_sequence


__all__ = ["CanalProgramInterpreter"]
