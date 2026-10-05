"""Modal M-code handling for Fanuc turning machines."""

from typing import Optional

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler


class FanucTurnModalMCodeHandler(BaseModalMCodeHandler):
    c_axis_reset_codes = {"M3", "M4", "M6"}

    def _apply_machine_specific_state(self, m_code: Optional[str], state: CNCState) -> None:
        if m_code in {"M3", "M4"}:
            state.set_machining_mode("turning")
            state.extra["fanuc_turn_spindle_stopped"] = False
            state.spindle_state["main"] = {
                "direction": m_code,
                "active": True,
                "speed": state.spindle_speed,
            }
        elif m_code == "M5":
            state.spindle_state["main"] = {
                "direction": "M5",
                "active": False,
                "speed": 0.0,
            }
            state.extra["fanuc_turn_spindle_stopped"] = True
            state.set_machining_mode("milling")
        elif m_code in {"M36", "M37", "M46", "M47", "M56", "M57"}:
            state.set_machining_mode("milling")
            tool_name = "PowerDrivenTool1" if m_code in {"M36", "M37"} else ("PowerDrivenTool2" if m_code in {"M46", "M47"} else "PowerDrivenTool3")
            state.spindle_state["PowerDrivenTools"] = {
                "tool": tool_name,
                "direction": m_code,
                "active": True,
                "speed": state.spindle_speed,
            }
        elif m_code in {"M38", "M48", "M58"}:
            tool_name = "PowerDrivenTool1" if m_code == "M38" else ("PowerDrivenTool2" if m_code == "M48" else "PowerDrivenTool3")
            state.spindle_state["PowerDrivenTools"] = {
                "tool": tool_name,
                "direction": m_code,
                "active": False,
                "speed": 0.0,
            }


__all__ = ["FanucTurnModalMCodeHandler"]