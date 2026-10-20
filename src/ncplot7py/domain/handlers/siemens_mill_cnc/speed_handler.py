"""Handler for Siemens ISO constant cutting speed modes (G96/G97)."""
from __future__ import annotations

from enum import Enum
import re
from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class SiemensSpeedMode(Enum):
    CONSTANT_CUTSPEED = "CONSTANT_CUTSPEED"
    CONSTANT_REV = "CONSTANT_REV"


class SiemensISOSpeedHandler(Handler):
    """Handle Siemens G96-family cutting speed modes and SCC reference axes."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        speed_codes = set()
        for g_code in node.g_code:
            if not isinstance(g_code, str):
                continue
            match = g_code.strip().upper()
            normalized = f"G{int(match[1:])}" if match[1:].isdigit() else match
            if normalized in {"G96", "G961", "G962", "G97", "G971", "G972", "G973"}:
                speed_codes.add(normalized)

        if len(speed_codes) > 1:
            raise_nc_error(
                ExceptionTyps.NCCodeErrors,
                100,
                message="Conflicting Siemens constant cutting speed modes",
                value=str(node.g_code),
            )

        speed_code = next(iter(speed_codes), None)
        if speed_code in {"G96", "G961", "G962"}:
            state.spindle_limits.surface_speed_mode = SiemensSpeedMode.CONSTANT_CUTSPEED
        elif speed_code in {"G97", "G971", "G972", "G973"}:
            state.spindle_limits.surface_speed_mode = SiemensSpeedMode.CONSTANT_REV

        if speed_code in {"G96", "G97", "G973"}:
            state.channel_state.feed_mode = "FEED_PER_REV"
        elif speed_code in {"G961", "G971"}:
            state.channel_state.feed_mode = "FEED_PER_MIN"

        if speed_code in {"G96", "G961", "G97"}:
            state.spindle_limits.spindle_speed_limit_active = True
        elif speed_code is not None:
            state.spindle_limits.spindle_speed_limit_active = False

        command = str(node.variable_command or "")
        limit_code = next(
            (code for code in node.g_code if str(code).strip().upper() in {"G25", "G025", "G26", "G026"}),
            None,
        )
        if limit_code is not None:
            is_maximum = int(str(limit_code).strip().upper()[1:]) == 26
            if "S" in node.command_parameter:
                s_limit = float(node.command_parameter.pop("S"))
                if is_maximum:
                    state.spindle_limits.spindle_speed_maximum = s_limit
                else:
                    state.spindle_limits.spindle_speed_minimum = s_limit
            indexed_limits = state.spindle_limits.spindle_speed_limits
            for key, value in node.command_parameter.items():
                if re.fullmatch(r"S\d+", str(key), re.IGNORECASE):
                    spindle = int(str(key)[1:])
                    indexed_limits.setdefault(spindle, {})["maximum" if is_maximum else "minimum"] = float(
                        str(value).lstrip("=")
                    )
            for spindle, value in re.findall(r"\bS(\d+)\s*=\s*([+-]?\d+(?:\.\d+)?)", command, re.IGNORECASE):
                indexed_limits.setdefault(int(spindle), {})["maximum" if is_maximum else "minimum"] = float(value)

        if match := re.search(r"\bSCC\s*\[\s*([A-Za-z][A-Za-z0-9_]*)\s*\]", command, re.IGNORECASE):
            state.spindle_limits.g96_reference_axis = match.group(1).upper()
        limit_match = re.search(r"\bLIMS(?:\s*\[\s*1\s*\])?\s*=\s*([+-]?\d+(?:\.\d+)?)", command, re.IGNORECASE)
        if limit_match:
            state.spindle_limits.spindle_speed_limit = float(limit_match.group(1))
        else:
            for key, value in node.command_parameter.items():
                if str(key).upper() in {"LIMS", "LIMS[1]"}:
                    state.spindle_limits.spindle_speed_limit = float(str(value).lstrip("="))
                    break

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None


__all__ = ["SiemensISOSpeedHandler", "SiemensSpeedMode"]