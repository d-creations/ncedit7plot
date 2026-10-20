"""Shared classified motion primitives for FANUC threading handlers."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class ThreadingPrimitiveEmitter:
    def __init__(self) -> None:
        self._motion = MotionHandler()
        self.segments: List[Dict[str, object]] = []

    def linear(
        self,
        target: Dict[str, float],
        state: CNCState,
        *,
        rapid: bool,
        source_code: str,
        lead: Optional[float] = None,
    ) -> Tuple[List[Point], float]:
        program_target = {
            axis: value * 2.0 if state.is_axis_diameter(axis) else value
            for axis, value in target.items()
        }
        command = {axis: str(value) for axis, value in program_target.items()}
        if lead is not None:
            command["F"] = str(lead)
        return self._emit(
            NCCommandNode(g_code_command={"G0" if rapid else "G1"}, command_parameter=command),
            state,
            geometry="LINEAR",
            traversal="RAPID" if rapid else "FEED",
            source_code="G00" if rapid else source_code,
            lead=lead,
        )

    def circular_ccw(
        self,
        command_parameter: Dict[str, str],
        state: CNCState,
        *,
        source_code: str,
        lead: float,
    ) -> Tuple[List[Point], float]:
        command = dict(command_parameter)
        command["F"] = str(lead)
        return self._emit(
            NCCommandNode(g_code_command={"G3"}, command_parameter=command),
            state,
            geometry="ARC_CCW",
            traversal="FEED",
            source_code=source_code,
            lead=lead,
        )

    def _emit(
        self,
        node: NCCommandNode,
        state: CNCState,
        *,
        geometry: str,
        traversal: str,
        source_code: str,
        lead: Optional[float],
    ) -> Tuple[List[Point], float]:
        old_mode = state.channel_state.feed_mode
        old_feed = state.feed_rate
        if lead is not None:
            state.channel_state.feed_mode = "FEED_PER_REV"
            state.feed_rate = lead
        try:
            points, duration = self._motion.handle(node, state)
        finally:
            state.channel_state.feed_mode = old_mode
            state.feed_rate = old_feed

        result_points = points or []
        result_duration = duration or 0.0
        if result_points:
            self.segments.append({
                "points": result_points,
                "duration": result_duration,
                "geometry": geometry,
                "traversal": traversal,
                "source_code": source_code,
            })
        return result_points, result_duration


def target_axis(
    state: CNCState,
    words: Dict[str, str],
    absolute_word: str,
    incremental_word: str,
) -> Optional[float]:
    if absolute_word in words:
        return state.normalize_axis_value(absolute_word, float(words[absolute_word]))
    if incremental_word in words:
        return state.get_axis(absolute_word) + state.normalize_axis_value(
            absolute_word, float(words[incremental_word])
        )
    return None


__all__ = ["ThreadingPrimitiveEmitter", "target_axis"]