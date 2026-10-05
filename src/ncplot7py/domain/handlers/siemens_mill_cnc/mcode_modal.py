"""Modal M-code handling for Siemens milling machines."""
from __future__ import annotations

from typing import Optional

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler
from ncplot7py.domain.handlers.siemens_mill_cnc.common import ensure_siemens_scope


class SiemensMillModalMCodeHandler(BaseModalMCodeHandler):
    def _apply_machine_specific_state(self, m_code: Optional[str], state: CNCState) -> None:
        if m_code in {"M3", "M4", "M5"}:
            state.machining_mode = "milling"
            state.spindle_state["main"] = {
                "direction": m_code,
                "active": m_code != "M5",
                "speed": state.spindle_speed if m_code != "M5" else 0.0,
            }
        elif m_code == "M82":
            ensure_siemens_scope(state)["probe_enabled"] = True
        elif m_code == "M83":
            ensure_siemens_scope(state)["probe_enabled"] = False


__all__ = ["SiemensMillModalMCodeHandler"]