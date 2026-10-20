"""FANUC optional counterclockwise circular threading G36."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.domain.handlers.fanuc_turn_cnc.threading_primitives import ThreadingPrimitiveEmitter
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class FanucG36CircularThreadingHandler(Handler):
    """Generate a CCW threaded arc when the circular-threading option is enabled."""

    ALLOWED_WORDS = {"X", "U", "Y", "V", "Z", "W", "I", "J", "K", "R", "F"}

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        if "G36" not in codes:
            return super().handle(node, state)
        state.fanuc_state.turn_drilling_cycle = None
        state.set_modal("drilling_cycle", None)
        state.fanuc_state.g92_words = None
        state.set_modal("turning_cycle", None)
        if not getattr(state.machine_config, "circular_threading_enabled", False):
            self._error(node, 360, "G36 circular threading option is not enabled", "G36")
        invalid = {str(word).upper() for word in node.command_parameter} - self.ALLOWED_WORDS
        if invalid:
            self._error(node, 361, "Unsupported G36 words", ",".join(sorted(invalid)))
        if "F" not in node.command_parameter:
            self._error(node, 362, "G36 requires thread lead F", "")
        try:
            lead = float(node.command_parameter["F"])
        except (TypeError, ValueError):
            self._error(node, 363, "G36 F must be numeric", str(node.command_parameter.get("F")))
        if lead <= 0.0 or float(state.spindle_speed or 0.0) <= 0.0:
            self._error(node, 364, "G36 requires positive lead and spindle speed", str(lead))

        emitter = ThreadingPrimitiveEmitter()
        points, duration = emitter.circular_ccw(
            node.command_parameter, state, source_code="G36", lead=lead
        )
        node.set_generated_motion_segments(emitter.segments)
        state.fanuc_state.threading_active = "G36"
        return points, duration

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(ExceptionTyps.NCCodeErrors, code, message=message, value=value, line=node.nc_code_line_nr or 0)


__all__ = ["FanucG36CircularThreadingHandler"]