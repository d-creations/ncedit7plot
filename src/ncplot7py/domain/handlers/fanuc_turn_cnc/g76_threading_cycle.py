"""FANUC lathe two-block multiple threading cycle G76."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.fanuc_turn_cnc.threading_primitives import ThreadingPrimitiveEmitter, target_axis
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class FanucG76ThreadingCycleHandler(Handler):
    """Store the first G76 block and expand the second into multiple passes."""

    SETUP_WORDS = {"P", "Q", "R"}
    CUT_WORDS = {"X", "U", "Z", "W", "R", "P", "Q", "F"}
    INTEGER_DISTANCE_SCALE = 0.001

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        if "G76" not in codes:
            return super().handle(node, state)

        words = {str(word).upper(): value for word, value in node.command_parameter.items()}
        state.fanuc_state.turn_drilling_cycle = None
        state.set_modal("drilling_cycle", None)
        state.fanuc_state.g92_words = None
        state.set_modal("turning_cycle", None)
        if not {"X", "U", "Z", "W"}.intersection(words):
            self._store_setup(node, state, words)
            return super().handle(node, state)
        return self._execute(node, state, words)

    def _store_setup(self, node: NCCommandNode, state: CNCState, words: Dict[str, str]) -> None:
        invalid = set(words) - self.SETUP_WORDS
        if invalid or not self.SETUP_WORDS.issubset(words):
            self._error(node, 760, "First G76 block requires only P, Q, and R", ",".join(sorted(words)))
        p_raw = str(words["P"]).strip()
        if "." in p_raw:
            self._error(node, 761, "G76 setup P does not allow a decimal point", p_raw)
        p_text = p_raw.zfill(6)
        if len(p_text) != 6 or not p_text.isdigit():
            self._error(node, 761, "G76 setup P must contain six digits", str(words["P"]))
        finishing_passes = int(p_text[:2])
        chamfer_tenths = int(p_text[2:4])
        tool_angle = int(p_text[4:])
        if not 1 <= finishing_passes <= 99 or tool_angle not in {0, 29, 30, 55, 60, 80}:
            self._error(node, 762, "G76 setup P contains an invalid pass count or tool angle", p_text)
        minimum_depth = self._scaled_positive(words["Q"], node, "Q")
        finishing_allowance = self._distance(words["R"], node, "R", allow_zero=True)
        state.fanuc_state.g76_setup = {
            "finishing_passes": finishing_passes,
            "chamfer_leads": chamfer_tenths / 10.0,
            "tool_angle": tool_angle,
            "minimum_depth": minimum_depth,
            "finishing_allowance": finishing_allowance,
        }

    def _execute(
        self, node: NCCommandNode, state: CNCState, words: Dict[str, str]
    ) -> Tuple[List[Point], float]:
        setup = state.fanuc_state.g76_setup
        if not isinstance(setup, dict):
            self._error(node, 763, "G76 cutting block requires a preceding setup block", "")
        invalid = set(words) - self.CUT_WORDS
        if invalid:
            self._error(node, 764, "Unsupported G76 cutting words", ",".join(sorted(invalid)))
        for required in ({"X", "U"}, {"Z", "W"}, {"P"}, {"Q"}, {"F"}):
            if not required.intersection(words):
                self._error(node, 765, "G76 cutting block is missing a required word", ",".join(sorted(required)))
        if float(state.spindle_speed or 0.0) <= 0.0:
            self._error(node, 766, "G76 requires a positive spindle speed", str(state.spindle_speed))

        start_x = state.get_axis("X")
        start_z = state.get_axis("Z")
        end_x = target_axis(state, words, "X", "U")
        end_z = target_axis(state, words, "Z", "W")
        assert end_x is not None and end_z is not None
        taper = self._distance(words.get("R", 0.0), node, "R", allow_zero=True)
        height = self._scaled_positive(words["P"], node, "P")
        first_depth = self._scaled_positive(words["Q"], node, "Q")
        lead = self._positive(words["F"], node, "F")
        finishing_allowance = float(setup["finishing_allowance"])
        if finishing_allowance >= height:
            self._error(node, 767, "G76 finishing allowance must be less than thread height", str(finishing_allowance))

        direction = -1.0 if end_x < start_x else 1.0
        rough_limit = height - finishing_allowance
        depths: List[float] = []
        pass_number = 1
        while True:
            depth = min(first_depth * math.sqrt(pass_number), rough_limit)
            if depths and math.isclose(depth, depths[-1], abs_tol=1e-9):
                break
            if depths and depth - depths[-1] < float(setup["minimum_depth"]):
                depth = min(depths[-1] + float(setup["minimum_depth"]), rough_limit)
            depths.append(depth)
            if math.isclose(depth, rough_limit, abs_tol=1e-9):
                break
            pass_number += 1
            if pass_number > 10000:
                self._error(node, 768, "G76 pass schedule did not converge", "")
        depths.extend([height] * int(setup["finishing_passes"]))

        emitter = ThreadingPrimitiveEmitter()
        points: List[Point] = []
        duration = 0.0
        for depth in depths:
            remaining = height - depth
            cut_end_x = end_x - direction * remaining
            cut_start_x = cut_end_x + taper
            for target, rapid, operation_lead in (
                ({"X": cut_start_x}, True, None),
                ({"X": cut_end_x, "Z": end_z}, False, lead),
                ({"X": start_x}, True, None),
                ({"Z": start_z}, True, None),
            ):
                moved, elapsed = emitter.linear(
                    target, state, rapid=rapid, source_code="G76", lead=operation_lead
                )
                points.extend(moved)
                duration += elapsed

        node.set_generated_motion_segments(emitter.segments)
        state.fanuc_state.threading_active = "G76"
        state.fanuc_state.g76_pass_depths = depths
        return points, duration

    def _scaled_positive(self, raw: object, node: NCCommandNode, word: str) -> float:
        text = str(raw).strip()
        if "." in text:
            self._error(node, 769, f"G76 {word} does not allow a decimal point", text)
        return self._positive(text, node, word) * self.INTEGER_DISTANCE_SCALE

    def _distance(
        self, raw: object, node: NCCommandNode, word: str, *, allow_zero: bool = False
    ) -> float:
        text = str(raw).strip()
        value = self._positive(text, node, word, allow_zero=allow_zero)
        return value if "." in text else value * self.INTEGER_DISTANCE_SCALE

    def _positive(
        self, raw: object, node: NCCommandNode, word: str, *, allow_zero: bool = False
    ) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            self._error(node, 769, f"{word} must be numeric", str(raw))
        if value < 0.0 or (not allow_zero and value <= 0.0):
            self._error(node, 770, f"{word} must be positive", str(raw))
        return value

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(ExceptionTyps.NCCodeErrors, code, message=message, value=value, line=node.nc_code_line_nr or 0)


__all__ = ["FanucG76ThreadingCycleHandler"]