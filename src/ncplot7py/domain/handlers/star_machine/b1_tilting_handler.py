"""Star B1-axis tilting and coordinate setup commands G910 and G920."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class StarB1TiltingHandler(Handler):
    """Index B1 and establish the documented Star tilting coordinate mode."""

    CODES = {"G910", "G920"}
    ALLOWED_WORDS = {"B", "X", "Z"}

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._motion = MotionHandler()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        codes = self.CODES.intersection(str(code).strip().upper() for code in node.g_code)
        if not codes:
            return super().handle(node, state)
        if len(codes) != 1:
            self._error(node, 3228, "G910 and G920 cannot be commanded together", "")
        code = next(iter(codes))
        words = {str(word).upper(): value for word, value in node.command_parameter.items()}
        invalid = set(words) - self.ALLOWED_WORDS
        if invalid or "B" not in words:
            self._error(node, 3228, f"{code} requires B and allows only B, X, and Z", ",".join(sorted(words)))
        self._validate_runtime(node, state, code)

        try:
            angle = float(words["B"])
            coordinate_reference = {
                axis: state.normalize_axis_value(axis, float(words[axis]))
                for axis in ("X", "Z")
                if axis in words
            }
        except (TypeError, ValueError):
            self._error(node, 3228, f"{code} arguments must be numeric", str(words))

        program_angle = str(angle)
        motion_node = NCCommandNode(
            g_code_command={"G0"},
            command_parameter={"B1": program_angle},
            nc_code_line_nr=node.nc_code_line_nr,
        )
        points, duration = self._motion.handle(motion_node, state)
        # Keep the legacy logical B state in sync while pose capture uses B1.
        state.axes["B"] = state.axes.get("B1", angle)
        result_points = points or []
        result_duration = duration or 0.0
        node.set_generated_motion_segments([{
            "points": result_points,
            "duration": result_duration,
            "geometry": "LINEAR",
            "traversal": "RAPID",
            "source_code": code,
        }])
        node.command_parameter.clear()
        state.extra["star.b1_tilting"] = {
            "mode": code,
            "angle": angle,
            "coordinate_reference": coordinate_reference,
            "automatic_offset_calculated": False,
        }
        state.set_modal("star_b1_tilting", code)
        return result_points, result_duration

    def _validate_runtime(self, node: NCCommandNode, state: CNCState, code: str) -> None:
        tool_code = state.extra.get("current_tool_code")
        if not isinstance(tool_code, int) or not 1600 <= tool_code <= 1900:
            self._error(node, 3233, f"{code} requires a selected T1600-T1900 tool", str(tool_code))
        if state.get_modal("tool_nose_compensation") in {"G41", "G42"}:
            self._error(node, 3229, f"{code} cannot execute during G41/G42 mode", "")
        if state.get_modal("drilling_cycle") or state.extra.get("fanuc_turn_drilling_cycle"):
            self._error(node, 3230, f"{code} cannot execute during a drilling cycle", "")
        if state.extra.get("wear_offset_active"):
            self._error(node, 3231, f"{code} cannot execute during wear offset", "")
        if state.extra.get("fanuc.coordinate_rotation"):
            self._error(node, 3232, f"{code} cannot execute during G68.1 mode", "")

        path_number = int(state.extra.get("path_number", 1))
        path_mode = state.extra.get("star.path_mode")
        if path_number == 1 and path_mode == "M172":
            self._error(node, 3235, f"{code} cannot execute on PATH1 during M172 mode", "")
        if path_number == 2 and path_mode == "M171":
            self._error(node, 3237, f"{code} cannot execute on PATH2 during M171 mode", "")

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(
            ExceptionTyps.NCCanalStarErrors,
            code,
            message=message,
            value=value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["StarB1TiltingHandler"]