"""Spindle and live tooling handler for Fanuc turning machines."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class FanucTurnSpindleHandler(Handler):
    """Handles turning spindle (M3/M4/M5) and live tooling mode switches on Fanuc lathes."""

    TURNING_SPINDLE_START = {"M3", "M4"}
    MILLING_TOOL_START = {"M36", "M37", "M46", "M47", "M56", "M57"}
    MILLING_TOOL_STOP = {"M38", "M48", "M58"}

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        # Check S parameter in block
        s_param = node.command_parameter.get("S")
        if s_param is not None:
            try:
                state.spindle_speed = float(s_param)
            except (ValueError, TypeError):
                pass

        m_codes = []
        m_val = node.command_parameter.get("M")
        if m_val is not None:
            norm = self._normalize_m_code(m_val)
            if norm:
                m_codes.append(norm)
        for extra_m in getattr(node, "m_code", ()) or ():
            norm = self._normalize_m_code(extra_m)
            if norm and norm not in m_codes:
                m_codes.append(norm)

        for m_code in m_codes:
            if m_code in self.TURNING_SPINDLE_START:
                state.set_modal("spindle_direction", m_code)
                state.set_machining_mode("turning")
                state.extra["fanuc_turn_spindle_stopped"] = False
                state.spindle_state["main"] = {
                    "direction": m_code,
                    "active": True,
                    "speed": state.spindle_speed,
                }
            elif m_code == "M5":
                state.set_modal("spindle_direction", "M5")
                state.spindle_state["main"] = {
                    "direction": "M5",
                    "active": False,
                    "speed": 0.0,
                }
                state.extra["fanuc_turn_spindle_stopped"] = True
                state.set_machining_mode("milling")
            elif m_code in self.MILLING_TOOL_START:
                state.set_machining_mode("milling")
                tool_name = "PowerDrivenTool1" if m_code in {"M36", "M37"} else ("PowerDrivenTool2" if m_code in {"M46", "M47"} else "PowerDrivenTool3")
                state.spindle_state["PowerDrivenTools"] = {
                    "tool": tool_name,
                    "direction": m_code,
                    "active": True,
                    "speed": state.spindle_speed,
                }
            elif m_code in self.MILLING_TOOL_STOP:
                tool_name = "PowerDrivenTool1" if m_code == "M38" else ("PowerDrivenTool2" if m_code == "M48" else "PowerDrivenTool3")
                state.spindle_state["PowerDrivenTools"] = {
                    "tool": tool_name,
                    "direction": m_code,
                    "active": False,
                    "speed": 0.0,
                }

        return super().handle(node, state)

    @staticmethod
    def _normalize_m_code(value: object) -> Optional[str]:
        text = str(value or "").strip().upper()
        if text.startswith("M"):
            text = text[1:]
        try:
            return f"M{int(text)}"
        except (TypeError, ValueError):
            return None


__all__ = ["FanucTurnSpindleHandler"]
