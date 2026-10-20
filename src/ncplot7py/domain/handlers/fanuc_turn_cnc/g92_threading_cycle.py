"""FANUC lathe straight and taper threading cycle G92."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.fanuc_turn_cnc.threading_primitives import ThreadingPrimitiveEmitter, target_axis
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class FanucG92ThreadingCycleHandler(Handler):
    """Expand modal G92 into rapid infeed, thread cut, retract, and return."""

    ALLOWED_WORDS = {"X", "U", "Z", "W", "R", "F", "Q"}

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        if self._cancels_cycle(codes):
            state.fanuc_state.g92_words = None
            state.set_modal("turning_cycle", None)

        if "G92" in codes:
            self._cancel_drilling_cycle(state)
            self._validate_words(node)
            words = dict(node.command_parameter)
            self._require(words, node, {"X", "U"}, "G92 requires X or U")
            self._require(words, node, {"Z", "W"}, "G92 requires Z or W")
            self._require(words, node, {"F"}, "G92 requires thread lead F")
            state.fanuc_state.g92_words = words
            state.set_modal("turning_cycle", "G92")
        elif state.get_modal("turning_cycle") == "G92" and self._is_repeat(node):
            words = dict(state.fanuc_state.g92_words or {})
            words.update(node.command_parameter)
            state.fanuc_state.g92_words = words
        else:
            return super().handle(node, state)

        return self._execute(node, state, words)

    def _execute(
        self, node: NCCommandNode, state: CNCState, words: Dict[str, str]
    ) -> Tuple[List[Point], float]:
        self._validate_thread_state(node, state, words)
        start_x = state.get_axis("X")
        start_z = state.get_axis("Z")
        end_x = target_axis(state, words, "X", "U")
        end_z = target_axis(state, words, "Z", "W")
        assert end_x is not None and end_z is not None
        taper = float(words.get("R", 0.0))
        lead = float(words["F"])

        emitter = ThreadingPrimitiveEmitter()
        points: List[Point] = []
        duration = 0.0
        operations = [
            ({"X": end_x + taper}, True, None),
            ({"X": end_x, "Z": end_z}, False, lead),
            ({"X": start_x}, True, None),
            ({"Z": start_z}, True, None),
        ]
        for target, rapid, operation_lead in operations:
            moved, elapsed = emitter.linear(
                target, state, rapid=rapid, source_code="G92", lead=operation_lead
            )
            points.extend(moved)
            duration += elapsed

        node.set_generated_motion_segments(emitter.segments)
        state.fanuc_state.threading_active = "G92"
        state.fanuc_state.threading_start_angle = float(words.get("Q", 0.0)) * 0.001
        return points, duration

    def _validate_thread_state(self, node: NCCommandNode, state: CNCState, words: Dict[str, str]) -> None:
        lead = self._number(words.get("F"), node, "F")
        if lead <= 0.0:
            self._error(node, 920, "G92 thread lead F must be greater than zero", str(lead))
        if float(state.spindle_speed or 0.0) <= 0.0:
            self._error(node, 921, "G92 requires a positive spindle speed", str(state.spindle_speed))
        q_value = self._number(words.get("Q", 0.0), node, "Q")
        if "Q" in words and "." in str(words["Q"]):
            self._error(node, 922, "G92 Q does not allow a decimal point", str(words["Q"]))
        if q_value < 0.0 or q_value > 360000.0:
            self._error(node, 922, "G92 Q must be between 0 and 360000", str(q_value))
        for word in {"X", "U", "Z", "W", "R"}.intersection(words):
            self._number(words[word], node, word)

    def _validate_words(self, node: NCCommandNode) -> None:
        invalid = {str(word).upper() for word in node.command_parameter} - self.ALLOWED_WORDS
        if invalid:
            self._error(node, 923, "Unsupported G92 words", ",".join(sorted(invalid)))

    @staticmethod
    def _is_repeat(node: NCCommandNode) -> bool:
        return bool({"X", "U"}.intersection(node.command_parameter))

    @staticmethod
    def _cancels_cycle(codes: set[str]) -> bool:
        return bool(codes.intersection({"G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03", "G32", "G34", "G35", "G36", "G76", "G90", "G94"}))

    @staticmethod
    def _cancel_drilling_cycle(state: CNCState) -> None:
        state.fanuc_state.turn_drilling_cycle = None
        state.set_modal("drilling_cycle", None)

    @staticmethod
    def _require(words: Dict[str, str], node: NCCommandNode, alternatives: set[str], message: str) -> None:
        if not alternatives.intersection(words):
            FanucG92ThreadingCycleHandler._error(node, 924, message, "")

    @staticmethod
    def _number(raw: object, node: NCCommandNode, word: str) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            FanucG92ThreadingCycleHandler._error(node, 925, f"{word} must be numeric", str(raw))
        return 0.0

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(ExceptionTyps.NCCodeErrors, code, message=message, value=value, line=node.nc_code_line_nr or 0)


__all__ = ["FanucG92ThreadingCycleHandler"]