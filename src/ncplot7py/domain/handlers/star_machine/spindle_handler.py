"""Spindle and power-driven tool handler for Star turning machines."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarSpindleHandler(Handler):
    """Handles main spindle (M3/M4/M5) and power-driven milling tools (M36-M38, M46-M48, M56-M58)."""

    TURNING_SPINDLE_START = {"M3", "M4"}
    MILLING_TOOL_1_START = {"M36", "M37"}
    MILLING_TOOL_1_STOP = {"M38"}
    MILLING_TOOL_2_START = {"M46", "M47"}
    MILLING_TOOL_2_STOP = {"M48"}
    MILLING_TOOL_3_START = {"M56", "M57"}
    MILLING_TOOL_3_STOP = {"M58"}

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
                info = {
                    "direction": m_code,
                    "active": True,
                    "speed": state.spindle_speed,
                }
                state.spindle_state["main"] = info
            elif m_code == "M5":
                state.set_modal("spindle_direction", "M5")
                info = {
                    "direction": "M5",
                    "active": False,
                    "speed": 0.0,
                }
                state.spindle_state["main"] = info
            elif m_code in self.MILLING_TOOL_1_START:
                state.set_machining_mode("milling")
                info = {
                    "tool": "PowerDrivenTool1",
                    "direction": m_code,
                    "active": True,
                    "speed": state.spindle_speed,
                }
                state.spindle_state["PowerDrivenTools"] = info
            elif m_code in self.MILLING_TOOL_1_STOP:
                info = {
                    "tool": "PowerDrivenTool1",
                    "direction": m_code,
                    "active": False,
                    "speed": 0.0,
                }
                state.spindle_state["PowerDrivenTools"] = info
            elif m_code in self.MILLING_TOOL_2_START:
                state.set_machining_mode("milling")
                info = {
                    "tool": "PowerDrivenTool2",
                    "direction": m_code,
                    "active": True,
                    "speed": state.spindle_speed,
                }
                state.spindle_state["PowerDrivenTools"] = info
            elif m_code in self.MILLING_TOOL_2_STOP:
                info = {
                    "tool": "PowerDrivenTool2",
                    "direction": m_code,
                    "active": False,
                    "speed": 0.0,
                }
                state.spindle_state["PowerDrivenTools"] = info
            elif m_code in self.MILLING_TOOL_3_START:
                state.set_machining_mode("milling")
                info = {
                    "tool": "PowerDrivenTool3",
                    "direction": m_code,
                    "active": True,
                    "speed": state.spindle_speed,
                }
                state.spindle_state["PowerDrivenTools"] = info
            elif m_code in self.MILLING_TOOL_3_STOP:
                info = {
                    "tool": "PowerDrivenTool3",
                    "direction": m_code,
                    "active": False,
                    "speed": 0.0,
                }
                state.spindle_state["PowerDrivenTools"] = info

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


__all__ = ["StarSpindleHandler"]
