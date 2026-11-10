"""Siemens-specific motion middleware.

This handler sits before the generic MotionHandler. It records Siemens motion
modal commands, adapts state for Siemens diameter programming, and consumes
PTP/PTPG0 linear moves that cannot be represented by straight path motion.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.domain.handlers.siemens_mill_cnc.common import ensure_siemens_scope
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


def _to_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


class SiemensMotionHandler(Handler):
    """Apply Siemens motion semantics before the generic motion handler."""

    _GEOMETRY_AXES = {"X", "Y", "Z", "A", "B", "C"}
    _INCREMENTAL_AXES = {"U": "X", "V": "Y", "W": "Z", "H": "C"}
    _DIAM_AXIS_RE = re.compile(r"^(DIAMONA|DIAMOFA|DIAM90A|DIAMCHANA)\s*\[\s*([A-Za-z][A-Za-z0-9_]*)\s*\]")

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._motion_helper = MotionHandler()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        scope = ensure_siemens_scope(state)
        if node.variable_command:
            self._apply_modal_command(node, state, scope)

        interp_mode = self._get_interp_mode(node, state)
        if interp_mode is None:
            return super().handle(node, state)

        previous_axis_units = self._apply_block_diameter_units(state, scope)
        try:
            axes_sync = str(scope.get("axes_sync") or "CP").upper()
            ptp_active = axes_sync == "PTP" or (axes_sync in {"PTPG0", "PTPG"} and interp_mode == "G00")
            if not ptp_active or interp_mode not in {"G00", "G01"}:
                return super().handle(node, state)

            start = state.axes.copy()
            resolved = self._resolve_target(node, state)
            if self._has_no_axis_change(start, resolved):
                return super().handle(node, state)

            points, duration = self._ptp_interpolate(start, resolved, state, rapid=interp_mode == "G00")
            state.update_axes(resolved)
            traversal = "RAPID" if interp_mode == "G00" else "FEED"
            node.set_motion_metadata("LINEAR", traversal, interp_mode)
            return self._motion_helper._transform_points_for_plot(points, state), duration
        finally:
            if previous_axis_units:
                for axis, unit in previous_axis_units.items():
                    state.set_axis_unit(axis, unit)

    def _apply_modal_command(self, node: NCCommandNode, state: CNCState, scope: Dict[str, object]) -> None:
        command = (node.variable_command or "").strip()
        if not command:
            return

        upper = command.upper()
        if upper in {"CP", "PTP", "PTPG0", "PTPG"}:
            scope["axes_sync"] = upper
        elif upper in {"FFWON", "FFWOF"}:
            scope["feed_forward"] = upper == "FFWON"
        elif upper in {"DIAMON", "DIAMOF", "DIAM90"}:
            scope["diameter_mode"] = upper
            self._apply_channel_diameter_mode(state, upper)
        elif upper == "DIAMCHAN":
            self._apply_channel_diameter_mode(state, str(scope.get("diameter_mode") or "DIAMOF"))
        elif upper.startswith("DIAM") and (match := self._DIAM_AXIS_RE.match(upper)):
            command_name, axis = match.groups()
            axis = axis.upper()
            mode = {
                "DIAMONA": "DIAMON",
                "DIAMOFA": "DIAMOF",
                "DIAM90A": "DIAM90",
                "DIAMCHANA": str(scope.get("diameter_mode") or "DIAMOF"),
            }[command_name]
            diameter_axes = scope.setdefault("diameter_axes", {})
            if isinstance(diameter_axes, dict):
                diameter_axes[axis] = mode
            self._apply_axis_diameter_mode(state, axis, mode)

    def _apply_channel_diameter_mode(self, state: CNCState, mode: str) -> None:
        for axis in self._get_channel_diameter_axes(state):
            self._apply_axis_diameter_mode(state, axis, mode)

    def _apply_axis_diameter_mode(self, state: CNCState, axis: str, mode: str) -> None:
        state.set_axis_unit(axis.upper(), "diameter" if mode.upper() in {"DIAMON", "DIAM90"} else "radius")

    def _apply_block_diameter_units(self, state: CNCState, scope: Dict[str, object]) -> Dict[str, str]:
        mode = str(scope.get("diameter_mode") or "DIAMOF").upper()
        if mode != "DIAM90":
            return {}

        absolute_mode = str(state.get_modal("distance") or "G90").upper() != "G91"
        desired_unit = "diameter" if absolute_mode else "radius"
        previous_units: Dict[str, str] = {}
        for axis in self._get_channel_diameter_axes(state):
            previous_units[axis] = state.get_axis_unit(axis)
            state.set_axis_unit(axis, desired_unit)
        return previous_units

    def _get_channel_diameter_axes(self, state: CNCState) -> List[str]:
        configured = list(getattr(getattr(state, "machine_config", None), "diameter_axes", ()) or [])
        if configured:
            return [str(axis).upper() for axis in configured]
        return ["X"]

    def _get_interp_mode(self, node: NCCommandNode, state: CNCState) -> Optional[str]:
        interp_mode = None
        for g_code in node.g_code:
            interp_mode = self._motion_helper._normalize_interp_mode(g_code) or interp_mode
        if interp_mode is None and self._has_motion_words(node, state):
            interp_mode = self._motion_helper._normalize_interp_mode(state.get_modal("G_GROUP_1"))
        return interp_mode

    def _has_motion_words(self, node: NCCommandNode, state: CNCState) -> bool:
        if not node.command_parameter:
            return False
        seventh_axis_name = self._motion_helper._get_seventh_axis_name(state)
        for key in node.command_parameter:
            upper_key = str(key).upper()
            if upper_key in self._GEOMETRY_AXES or upper_key in self._INCREMENTAL_AXES or (seventh_axis_name and upper_key == seventh_axis_name):
                return True
        return False

    def _resolve_target(self, node: NCCommandNode, state: CNCState) -> Dict[str, float]:
        absolute_target_spec: Dict[str, float] = {}
        incremental_target_spec: Dict[str, float] = {}
        absolute_mode = str(state.get_modal("distance") or "G90").upper() != "G91"
        seventh_axis_name = self._motion_helper._get_seventh_axis_name(state)
        seventh_axis_maps_to = self._motion_helper._get_seventh_axis_maps_to(state)

        for key, value in node.command_parameter.items():
            axis = key.upper()
            if axis in self._GEOMETRY_AXES:
                absolute_target_spec[axis] = _to_float(value)
            elif seventh_axis_name and axis == seventh_axis_name:
                numeric_value = _to_float(value)
                absolute_target_spec[axis] = numeric_value
                if seventh_axis_maps_to and seventh_axis_maps_to not in absolute_target_spec:
                    absolute_target_spec[seventh_axis_maps_to] = numeric_value
            elif axis in self._INCREMENTAL_AXES:
                mapped_axis = self._INCREMENTAL_AXES[axis]
                incremental_target_spec[mapped_axis] = incremental_target_spec.get(mapped_axis, 0.0) + _to_float(value)

        normalized_absolute = state.normalize_target_spec(absolute_target_spec)
        normalized_incremental = state.normalize_target_spec(incremental_target_spec)
        resolved = state.resolve_target(normalized_absolute, absolute=absolute_mode)
        for axis, delta in normalized_incremental.items():
            resolved[axis] = resolved.get(axis, state.get_axis(axis)) + delta
        return resolved

    def _ptp_interpolate(
        self,
        start: Dict[str, float],
        end: Dict[str, float],
        state: CNCState,
        rapid: bool,
    ) -> Tuple[List[Point], float]:
        moving_axes = [axis for axis in ["X", "Y", "Z", "A", "B", "C"] if not math.isclose(start.get(axis, 0.0), end.get(axis, start.get(axis, 0.0)), abs_tol=1e-9)]
        if not moving_axes:
            return [self._point_from_axes(start), self._point_from_axes(end)], 0.0

        axes_by_distance = sorted(moving_axes, key=lambda axis: abs(end.get(axis, 0.0) - start.get(axis, 0.0)), reverse=True)
        current = dict(start)
        points = [self._point_from_axes(current)]
        total_duration = 0.0
        for axis in axes_by_distance:
            next_position = dict(current)
            next_position[axis] = end.get(axis, current.get(axis, 0.0))
            distance = self._axis_travel(axis, current, next_position, state)
            feed_mm_s = self._motion_helper._get_rapid_mm_s(state) if rapid else self._motion_helper._get_feed_mm_s(state, current, next_position)
            if feed_mm_s > 0.0:
                total_duration += distance / feed_mm_s
            points.append(self._point_from_axes(next_position))
            current = next_position
        return points, total_duration

    def _axis_travel(self, axis: str, start: Dict[str, float], end: Dict[str, float], state: CNCState) -> float:
        if axis in {"A", "B", "C"}:
            return self._motion_helper._estimate_rotary_axes_travel(start, end, state)
        return abs(end.get(axis, start.get(axis, 0.0)) - start.get(axis, 0.0))

    def _point_from_axes(self, axes: Dict[str, float]) -> Point:
        return Point(
            x=axes.get("X", 0.0),
            y=axes.get("Y", 0.0),
            z=axes.get("Z", 0.0),
            a=axes.get("A", 0.0),
            b=axes.get("B", 0.0),
            c=axes.get("C", 0.0),
        )

    def _has_no_axis_change(self, start: Dict[str, float], end: Dict[str, float]) -> bool:
        return all(math.isclose(start.get(axis, 0.0), end.get(axis, start.get(axis, 0.0)), abs_tol=1e-9) for axis in self._GEOMETRY_AXES)


__all__ = ["SiemensMotionHandler"]