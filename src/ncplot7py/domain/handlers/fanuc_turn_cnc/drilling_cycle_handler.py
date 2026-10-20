"""FANUC lathe canned drilling cycles G80, G83-G85, G87, and G89."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class FanucTurnDrillingCycleHandler(Handler):
    """Expand FANUC lathe drilling cycles into visible motion primitives."""

    CYCLE_CODES = {"G83", "G84", "G85", "G87", "G89"}
    ALLOWED_WORDS = {"X", "U", "Z", "W", "C", "H", "R", "P", "Q", "F", "K", "M"}
    INTEGER_DISTANCE_SCALE = 0.001

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._motion = MotionHandler()
        self._active_segments: Optional[List[Dict[str, object]]] = None

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        if "G80" in codes:
            self._cancel(state)
            return super().handle(node, state)

        selected = self.CYCLE_CODES.intersection(codes)
        if len(selected) > 1:
            self._error(node, 830, "Conflicting canned drilling cycles", str(sorted(selected)))

        explicit_code = next(iter(selected), None)
        if explicit_code is not None:
            self._validate_words(node)
            cycle = self._create_cycle(explicit_code, node, state)
            state.fanuc_state.turn_drilling_cycle = cycle
            state.set_modal("drilling_cycle", explicit_code)
        else:
            cycle = state.fanuc_state.turn_drilling_cycle
            if not isinstance(cycle, dict) or not self._is_repeat_block(node, cycle):
                return super().handle(node, state)
            cycle = self._merge_repeat_words(cycle, node)
            state.fanuc_state.turn_drilling_cycle = cycle

        return self._execute_cycle(cycle, state, node)

    def _create_cycle(self, code: str, node: NCCommandNode, state: CNCState) -> Dict[str, object]:
        drill_axis = "Z" if code in {"G83", "G84", "G85"} else "X"
        depth_words = {"Z", "W"} if drill_axis == "Z" else {"X", "U"}
        if not depth_words.intersection(node.command_parameter):
            self._error(node, 831, f"{code} requires a drilling depth", drill_axis)

        initial_level = state.get_axis(drill_axis)
        cycle: Dict[str, object] = {
            "code": code,
            "drill_axis": drill_axis,
            "initial_level": initial_level,
            "words": dict(node.command_parameter),
        }
        return cycle

    def _merge_repeat_words(self, cycle: Dict[str, object], node: NCCommandNode) -> Dict[str, object]:
        merged = dict(cycle)
        words = dict(cycle.get("words", {}))
        words.update(node.command_parameter)
        merged["words"] = words
        return merged

    def _execute_cycle(
        self,
        cycle: Dict[str, object],
        state: CNCState,
        node: NCCommandNode,
    ) -> Tuple[List[Point], float]:
        code = str(cycle["code"])
        drill_axis = str(cycle["drill_axis"])
        words = dict(cycle["words"])
        initial_level = float(cycle["initial_level"])
        points: List[Point] = []
        duration = 0.0
        self._active_segments = []

        position_target = self._position_target(code, words, state)
        moved_points, moved_duration = self._move(position_target, state, rapid=True)
        points.extend(moved_points)
        duration += moved_duration

        r_offset = self._axis_distance(drill_axis, words.get("R", 0.0), state, radius_word=True)
        depth_word = "Z" if drill_axis == "Z" else "X"
        incremental_depth_word = "W" if drill_axis == "Z" else "U"
        raw_depth = words.get(depth_word, words.get(incremental_depth_word))
        depth = self._axis_distance(drill_axis, raw_depth, state)
        r_level = initial_level + r_offset
        bottom = r_level + depth

        moved_points, moved_duration = self._move({drill_axis: r_level}, state, rapid=True)
        points.extend(moved_points)
        duration += moved_duration

        repeats = self._positive_int(words.get("K", 1), node, "K")
        dwell_seconds = max(0.0, self._float(words.get("P", 0.0), node, "P") / 1000.0)
        for _ in range(repeats):
            if code in {"G83", "G87"}:
                cycle_points, cycle_duration = self._peck(drill_axis, r_level, bottom, words, state)
            elif code == "G84":
                cycle_points, cycle_duration = self._tap(drill_axis, r_level, bottom, state)
                state.fanuc_state.last_tapping_reversal = True
            else:
                cycle_points, cycle_duration = self._bore(drill_axis, r_level, bottom, state)
            points.extend(cycle_points)
            duration += cycle_duration + dwell_seconds

        return_level = initial_level if self._feed_mode(state) == "FEED_PER_MIN" else r_level
        if not math.isclose(state.get_axis(drill_axis), return_level, abs_tol=1e-9):
            moved_points, moved_duration = self._move({drill_axis: return_level}, state, rapid=True)
            points.extend(moved_points)
            duration += moved_duration

        node.set_generated_motion_segments(self._active_segments)
        self._active_segments = None
        return points, duration

    def _peck(
        self,
        axis: str,
        r_level: float,
        bottom: float,
        words: Dict[str, str],
        state: CNCState,
    ) -> Tuple[List[Point], float]:
        raw_q = words.get("Q")
        if raw_q is None:
            return self._feed_and_rapid_return(axis, bottom, r_level, state)

        peck = abs(float(raw_q)) * self.INTEGER_DISTANCE_SCALE
        if peck <= 0.0:
            raise_nc_error(ExceptionTyps.NCCodeErrors, 832, message="Q must be greater than zero")
        direction = 1.0 if bottom > r_level else -1.0
        current_depth = r_level
        points: List[Point] = []
        duration = 0.0
        while not math.isclose(current_depth, bottom, abs_tol=1e-9):
            next_depth = current_depth + direction * peck
            if (direction > 0 and next_depth > bottom) or (direction < 0 and next_depth < bottom):
                next_depth = bottom
            moved_points, moved_duration = self._move({axis: next_depth}, state, rapid=False)
            points.extend(moved_points)
            duration += moved_duration
            current_depth = next_depth
            if not math.isclose(current_depth, bottom, abs_tol=1e-9):
                moved_points, moved_duration = self._move({axis: r_level}, state, rapid=True)
                points.extend(moved_points)
                duration += moved_duration
        moved_points, moved_duration = self._move({axis: r_level}, state, rapid=True)
        points.extend(moved_points)
        duration += moved_duration
        return points, duration

    def _tap(self, axis: str, r_level: float, bottom: float, state: CNCState) -> Tuple[List[Point], float]:
        points: List[Point] = []
        duration = 0.0
        for target in (bottom, r_level):
            moved_points, moved_duration = self._move({axis: target}, state, rapid=False)
            points.extend(moved_points)
            duration += moved_duration
        return points, duration

    def _bore(self, axis: str, r_level: float, bottom: float, state: CNCState) -> Tuple[List[Point], float]:
        points, duration = self._move({axis: bottom}, state, rapid=False)
        return_points, return_duration = self._move({axis: r_level}, state, rapid=False, feed_multiplier=2.0)
        return points + return_points, duration + return_duration

    def _feed_and_rapid_return(
        self, axis: str, bottom: float, r_level: float, state: CNCState
    ) -> Tuple[List[Point], float]:
        points, duration = self._move({axis: bottom}, state, rapid=False)
        return_points, return_duration = self._move({axis: r_level}, state, rapid=True)
        return points + return_points, duration + return_duration

    def _position_target(self, code: str, words: Dict[str, str], state: CNCState) -> Dict[str, float]:
        target: Dict[str, float] = {}
        if code in {"G83", "G84", "G85"}:
            self._absolute_or_incremental(target, "X", "U", words, state)
        else:
            self._absolute_or_incremental(target, "Z", "W", words, state)
        self._absolute_or_incremental(target, "C", "H", words, state)
        return target

    def _absolute_or_incremental(
        self,
        target: Dict[str, float],
        absolute_word: str,
        incremental_word: str,
        words: Dict[str, str],
        state: CNCState,
    ) -> None:
        if absolute_word in words:
            target[absolute_word] = state.normalize_axis_value(absolute_word, float(words[absolute_word]))
        elif incremental_word in words:
            target[absolute_word] = state.get_axis(absolute_word) + state.normalize_axis_value(
                absolute_word, float(words[incremental_word])
            )

    def _move(
        self,
        target: Dict[str, float],
        state: CNCState,
        *,
        rapid: bool,
        feed_multiplier: float = 1.0,
    ) -> Tuple[List[Point], float]:
        if not target:
            return [], 0.0
        program_target = {
            axis: value * 2.0 if state.is_axis_diameter(axis) else value
            for axis, value in target.items()
        }
        original_feed = state.feed_rate
        if original_feed is not None and not rapid:
            state.feed_rate = float(original_feed) * feed_multiplier
        try:
            points, duration = self._motion.handle(
                NCCommandNode(g_code_command={"G0" if rapid else "G1"}, command_parameter={
                    axis: str(value) for axis, value in program_target.items()
                }),
                state,
            )
        finally:
            state.feed_rate = original_feed
        if points and self._active_segments is not None:
            self._active_segments.append({
                "points": points,
                "duration": duration or 0.0,
                "geometry": "LINEAR",
                "traversal": "RAPID" if rapid else "FEED",
                "source_code": "G00" if rapid else "G01",
            })
        return points or [], duration or 0.0

    def _axis_distance(self, axis: str, raw: object, state: CNCState, radius_word: bool = False) -> float:
        value = float(raw)
        if radius_word:
            return value
        return state.normalize_axis_value(axis, value)

    def _validate_words(self, node: NCCommandNode) -> None:
        invalid = {str(word).upper() for word in node.command_parameter} - self.ALLOWED_WORDS
        if invalid:
            self._error(node, 833, "Unsupported canned-cycle words", ",".join(sorted(invalid)))

    def _is_repeat_block(self, node: NCCommandNode, cycle: Dict[str, object]) -> bool:
        words = {str(word).upper() for word in node.command_parameter}
        code = str(cycle.get("code"))
        position_words = {"X", "U", "C", "H"} if code in {"G83", "G84", "G85"} else {"Z", "W", "C", "H"}
        return bool(words.intersection(position_words))

    @staticmethod
    def _feed_mode(state: CNCState) -> str:
        mode = state.channel_state.feed_mode or "FEED_PER_REV"
        return str(getattr(mode, "value", mode))

    @staticmethod
    def _float(raw: object, node: NCCommandNode, word: str) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            FanucTurnDrillingCycleHandler._error(node, 834, f"{word} must be numeric", str(raw))
        return 0.0

    @staticmethod
    def _positive_int(raw: object, node: NCCommandNode, word: str) -> int:
        value = int(FanucTurnDrillingCycleHandler._float(raw, node, word))
        if value < 1:
            FanucTurnDrillingCycleHandler._error(node, 835, f"{word} must be at least one", str(raw))
        return value

    @staticmethod
    def _cancel(state: CNCState) -> None:
        state.fanuc_state.turn_drilling_cycle = None
        state.set_modal("drilling_cycle", None)

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(
            ExceptionTyps.NCCodeErrors,
            code,
            message=message,
            value=value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["FanucTurnDrillingCycleHandler"]