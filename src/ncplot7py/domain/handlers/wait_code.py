from __future__ import annotations

import re
from typing import Optional, Tuple, List, Dict, Any

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState


class WaitCodeHandler(Handler):
    """Handler for multi-canal synchronization wait codes (e.g. Star M-codes, Siemens WAITM).
    
    Identifies wait codes, extracts synchronization parameters (e.g. M code, P channel pair),
    attaches wait metadata to the node, and records wait markers in CNCState/MachineState.
    """

    @classmethod
    def extract_wait_code(cls, node: NCCommandNode, state: CNCState) -> Optional[Dict[str, Any]]:
        """Inspects an NCCommandNode to determine if it contains a wait/synchronization command.
        
        Returns a dict with {"code": int|str, "p": Optional[int], "strategy": str} or None.
        """
        config = getattr(state, "machine_config", None)
        strategy = getattr(config, "synchronization_strategy", "NONE") if config else "NONE"

        # Check Star / Fanuc style wait codes (M200-M888, M40, M41, M82, M83, M131, M133)
        # Note: even if strategy is not STAR_WAIT, Star programs use these M codes.
        params = getattr(node, "command_parameter", {}) or {}
        if "M" in params:
            try:
                m_val = int(params["M"])
            except (ValueError, TypeError):
                m_val = None

            if m_val is not None:
                is_star_wait = False
                p_val = None

                if 200 <= m_val <= 888:
                    is_star_wait = True
                    if "P" in params:
                        try:
                            p_val = int(params["P"])
                        except (ValueError, TypeError):
                            p_val = None
                elif m_val in (40, 41, 82, 83):
                    is_star_wait = True
                    p_val = 12
                elif m_val in (131, 133):
                    is_star_wait = True
                    p_val = 13
                elif m_val in (171, 172):
                    is_star_wait = True
                    # Check channel: if Channel 3 (or P specifies 23/32), pair 23; else pair 12
                    ch_num = state.extra.get("path_number", 1)
                    if "P" in params:
                        try:
                            p_val = int(params["P"])
                        except (ValueError, TypeError):
                            p_val = 23 if ch_num == 3 else 12
                    else:
                        p_val = 23 if ch_num == 3 else 12

                if is_star_wait:
                    return {
                        "type": "STAR_WAIT",
                        "code": m_val,
                        "p": p_val,
                    }

        # Check Siemens style WAITM / WAITMC / WAITE
        # Could be in node.variable_command or node.full_line_text or command_parameter
        var_cmd = str(getattr(node, "variable_command", "") or "")
        line_text = str(getattr(node, "full_line_text", "") or "")
        siemens_text = var_cmd if ("WAITM" in var_cmd.upper() or "WAITE" in var_cmd.upper()) else line_text

        if "WAITM" in siemens_text.upper() or "WAITE" in siemens_text.upper():
            # Parse WAITM(<marker>[, <ch1>[, <ch2>...]])
            m = re.search(r"WAITM\s*\(\s*([^,\)]+)(?:,\s*([^,\)]+))?(?:,\s*([^,\)]+))?", siemens_text, re.IGNORECASE)
            marker = None
            channels = None
            if m:
                try:
                    marker = int(m.group(1).strip())
                except (ValueError, TypeError):
                    marker = m.group(1).strip()
                chs = [c.strip() for c in (m.group(2), m.group(3)) if c is not None]
                if chs:
                    channels = chs
            return {
                "type": "SIEMENS_WAIT",
                "code": marker if marker is not None else siemens_text.strip(),
                "marker": marker,
                "channels": channels,
                "statement": siemens_text.strip(),
            }

        return None

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        wait_info = self.extract_wait_code(node, state)
        if wait_info:
            if not hasattr(node, "extra") or node.extra is None:
                node.extra = {}
            node.extra["wait_code"] = wait_info

            # Also record current canal wait status in state
            state.extra["last_wait_code"] = wait_info

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None


__all__ = ["WaitCodeHandler"]
