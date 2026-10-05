"""Modal M-code handling for Fanuc milling machines."""

from typing import Optional

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler


class FanucMillModalMCodeHandler(BaseModalMCodeHandler):
    c_axis_reset_codes = {"M6"}

    def _apply_machine_specific_state(self, m_code: Optional[str], state: CNCState) -> None:
        if m_code in {"M3", "M4", "M5"}:
            state.machining_mode = "milling"
            state.spindle_state["main"] = {
                "direction": m_code,
                "active": m_code != "M5",
                "speed": state.spindle_speed if m_code != "M5" else 0.0,
            }


__all__ = ["FanucMillModalMCodeHandler"]