"""Star automatic coordinate-setting commands G125 and G130-G133."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarAutomaticCoordinateHandler(Handler):
    """Validate and track the Star automatic-coordinate command sequence."""

    CODES = {"G125", "G130", "G131", "G132", "G133"}

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        owned_codes = self.CODES.intersection(str(code).strip().upper() for code in node.g_code)
        if not owned_codes:
            return super().handle(node, state)
        if len(owned_codes) != 1:
            self._error(node, 3620, "Only one Star automatic-coordinate command is allowed per block")

        code = next(iter(owned_codes))
        self._require_compensation_off(node, state, code)

        if code == "G125":
            self._handle_g125(node, state)
        elif code == "G130":
            self._require_words(node, code, set(), 3620)
            state.extra["star.coordinate.z2_set"] = False
            state.extra["star.coordinate.path2_machining"] = False
        elif code == "G131":
            self._handle_g131(node, state)
        elif code == "G132":
            self._require_words(node, code, set(), 3623)
            state.extra["star.coordinate.z2_set"] = True
            state.extra["star.coordinate.path2_machining"] = True
        elif code == "G133":
            self._require_words(node, code, set(), 3624)
            state.extra["star.coordinate.projection_stored"] = True

        return super().handle(node, state)

    def _handle_g125(self, node: NCCommandNode, state: CNCState) -> None:
        self._require_words(node, "G125", {"Z", "W"}, 3622)
        values = self._numeric_words(node, {"Z", "W"})
        values.setdefault("Z", 0.0)
        state.extra["star.coordinate.z1_command"] = values
        state.extra["star.coordinate.z1_set"] = True
        for word in values:
            node.command_parameter.pop(word, None)

    def _handle_g131(self, node: NCCommandNode, state: CNCState) -> None:
        self._require_words(node, "G131", {"B"}, 3621)
        if state.extra.get("star.axis.z1_moving"):
            self._error(node, 3628, "G131 cannot execute while the Z1 axis is moving")

        values = self._numeric_words(node, {"B"})
        state.extra["star.coordinate.pickup_b"] = values.get("B")
        state.extra["star.coordinate.pickup_set"] = True
        node.command_parameter.pop("B", None)

    def _require_compensation_off(self, node: NCCommandNode, state: CNCState, code: str) -> None:
        mode = state.get_modal("tool_nose_compensation")
        if mode in {"G41", "G42"}:
            self._error(node, 3635, f"{code} cannot execute during G41/G42 mode")

    def _require_words(
        self,
        node: NCCommandNode,
        code: str,
        allowed: set[str],
        alarm: int,
        require_any: bool = False,
    ) -> None:
        words = {str(word).upper() for word in node.command_parameter}
        if words - allowed or (require_any and not words.intersection(allowed)):
            self._error(node, alarm, f"Invalid word format for {code}", value=",".join(sorted(words)))

    def _numeric_words(self, node: NCCommandNode, words: set[str]) -> dict[str, float]:
        values: dict[str, float] = {}
        for word in words.intersection(node.command_parameter):
            try:
                values[word] = float(node.command_parameter[word])
            except (TypeError, ValueError):
                self._error(node, 3622, f"{word} value must be numeric", value=node.command_parameter[word])
        return values

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str = "") -> None:
        raise_nc_error(
            ExceptionTyps.NCCanalStarErrors,
            code,
            message=message,
            value=value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["StarAutomaticCoordinateHandler"]