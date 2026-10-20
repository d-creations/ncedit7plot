"""Star G161 Step Cycle Pro command validation and state."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.shared.nc_nodes import NCCommandNode


@dataclass(frozen=True)
class StepCycleParameters:
    a: Optional[float] = None
    f: Optional[float] = None
    d: Optional[float] = None
    q: Optional[float] = None


class StarG161StepCycleHandler(Handler):
    """Validate G161 and draw its net linear move to X/Y/Z."""

    ALLOWED_WORDS = {"X", "Y", "Z", "A", "F", "D", "Q"}

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._motion = MotionHandler()

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        if "G161" not in codes:
            return super().handle(node, state)

        words = {str(word).upper(): value for word, value in node.command_parameter.items()}
        invalid = set(words) - self.ALLOWED_WORDS
        if invalid:
            self._error(node, 3730, "G161 allows only X, Y, Z, A, F, D, and Q", ",".join(sorted(invalid)))
        endpoint_words = {axis: words[axis] for axis in ("X", "Y", "Z") if axis in words}
        missing = {"A", "D"} - set(words)
        if missing:
            self._error(node, 3730, "G161 is missing required Step Cycle parameters", ",".join(sorted(missing)))
        self._validate_runtime(node, state, has_endpoint=bool(endpoint_words))

        values = {}
        for word in ("A", "F", "D", "Q"):
            if word not in words:
                continue
            raw = words[word]
            try:
                values[word.lower()] = float(raw)
            except (TypeError, ValueError):
                self._error(node, 3730, f"G161 {word} must be numeric", str(raw))
        if not 1.0 <= values["a"] <= 5.0:
            self._error(node, 3730, "G161 amplitude A must be between 1 and 5", str(values["a"]))
        if not 1.0 <= values["d"] <= 5.0:
            self._error(node, 3730, "G161 rotations-per-amplitude D must be between 1 and 5", str(values["d"]))
        if "f" in values and values["f"] <= 0.0:
            self._error(node, 3730, "G161 F must be greater than zero", str(values["f"]))
        if "q" in values and values["q"] < 0.0:
            self._error(node, 3730, "G161 Q must be zero or greater", str(values["q"]))

        parameters = StepCycleParameters(**values)
        result_points = None
        result_duration = None
        if endpoint_words:
            feed = values.get("f", state.feed_rate)
            if feed is None or float(feed) <= 0.0:
                self._error(node, 3730, "G161 endpoint movement requires a positive feed rate", str(feed))
            state.feed_rate = float(feed)
            motion_node = NCCommandNode(
                g_code_command={"G1"},
                command_parameter=endpoint_words,
                nc_code_line_nr=node.nc_code_line_nr,
            )
            points, duration = self._motion.handle(motion_node, state)
            result_points = points or []
            result_duration = duration or 0.0
            node.set_generated_motion_segments([{
                "points": result_points,
                "duration": result_duration,
                "geometry": "LINEAR",
                "traversal": "FEED",
                "source_code": "G161",
            }])
        state.star_state.g161 = {
            "parameters": asdict(parameters),
            "endpoint": {axis: state.get_axis(axis) for axis in endpoint_words},
            "geometry_available": bool(endpoint_words),
            "geometry_source": "linear_endpoint_approximation" if endpoint_words else None,
            "physical_cycle_path_available": False,
            "option_enabled": bool(getattr(state.machine_config, "step_cycle_pro_enabled", False)),
        }
        state.set_modal("star_step_cycle", "G161")
        node.command_parameter.clear()
        return result_points, result_duration

    def _validate_runtime(self, node: NCCommandNode, state: CNCState, has_endpoint: bool) -> None:
        speed_mode = self._mode_value(state.spindle_limits.surface_speed_mode)
        if speed_mode == "CONSTANT_CUTSPEED":
            self._error(node, 3712, "G161 cannot execute during G96 mode", "G96")

        feed_mode = self._mode_value(state.channel_state.feed_mode)
        if feed_mode != "FEED_PER_REV":
            self._error(node, 3729, "G161 requires G99 feed-per-revolution mode", str(feed_mode))

        if has_endpoint and float(state.spindle_speed or 0.0) <= 0.0:
            self._error(node, 3730, "G161 requires a positive spindle speed", str(state.spindle_speed))

        control_mode = str(state.channel_state.control_mode or "MACHINING").upper()
        if control_mode == "MACHINING" and not getattr(state.machine_config, "step_cycle_pro_enabled", False):
            self._error(node, 3727, "Step Cycle Pro option is required for G161 in MACHINING mode", "G161")

    @staticmethod
    def _mode_value(value: object) -> str:
        return str(getattr(value, "value", value or ""))

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(
            ExceptionTyps.NCCanalStarErrors,
            code,
            message=message,
            value=value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["StarG161StepCycleHandler", "StepCycleParameters"]