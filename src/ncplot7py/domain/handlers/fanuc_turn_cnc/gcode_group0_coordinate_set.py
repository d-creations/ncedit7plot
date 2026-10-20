from __future__ import annotations

from typing import Optional, Tuple, List

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState


class GCodeGroup0CoordinateSetExecChainLink(Handler):
    """Handle G50 (set offsets) and G28 (go to reference) and small misc.

    Behavior is adapted from the user example but uses `CNCState` storage
    conventions (dicts for axes/offsets/multipliers).
    """

    AXIS_MAP = {"U": "X", "V": "Y", "W": "Z", "H": "C"}

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        # Defensive copy of g-codes to iterate safely
        for g_code in set(node.g_code):
            # normalize e.g. 'G50' -> 50
            try:
                if g_code.upper().startswith("G"):
                    g_num = int(g_code[1:])
                else:
                    # not a G code, skip
                    continue
            except Exception:
                continue

            # --- G50: set offsets (store current pos into offsets and set new pos)
            if g_num == 50:
                for key in list(node.command_parameter.keys()):
                    raw = node.command_parameter.pop(key, None)
                    if raw is None:
                        continue
                    # map input letter to axis name (allow A,B,C,X,Y,Z)
                    axis = key.upper()
                    if axis in ("A", "B", "C", "X", "Y", "Z"):
                        # add current axis pos to offset
                        current = state.axes.get(axis, 0.0)
                        state.offsets[axis] = state.offsets.get(axis, 0.0) + current
                        mult = state.axis_multipliers.get(axis, 1.0) or 1.0
                        # set new current axis pos from parameter (apply multiplier)
                        try:
                            val = float(raw)
                        except Exception:
                            val = 0.0
                        state.axes[axis] = val / mult

            # --- G28: move to reference/home position, convert U/V/W/H to X/Y/Z/C and
            # adjust for offsets (we mutate parameters so downstream motion
            # handlers see absolute coordinates after offset correction)
            elif g_num == 28:
                # ensure a rapid (G00) motion code is present
                node.g_code.add("G00")
                home_positions = getattr(getattr(state, "machine_config", None), "home_position", {}) or {}
                axis_map = state.channel_state.axis_map or {}
                for key in list(node.command_parameter.keys()):
                    upper_key = key.upper()
                    mapped = self.AXIS_MAP.get(upper_key, upper_key)
                    if mapped not in ("X", "Y", "Z", "A", "B", "C") and mapped not in home_positions:
                        continue
                    try:
                        raw = float(node.command_parameter.get(key))
                    except Exception:
                        # leave as-is when not numeric
                        continue
                    physical = axis_map.get(mapped, mapped)
                    home_val = float(home_positions.get(physical, home_positions.get(mapped, 0.0)))
                    off = state.offsets.get(mapped, 0.0)
                    mult = state.axis_multipliers.get(mapped, 1.0) or 1.0
                    target_base = home_val + raw if upper_key in self.AXIS_MAP else (home_val if raw == 0.0 else raw)
                    corrected = target_base - off * mult
                    # update parameter using mapped axis letter
                    node.command_parameter[mapped] = str(corrected)
                    # remove original key if different (U/V/W/H)
                    if mapped != upper_key:
                        node.command_parameter.pop(key, None)

            # --- G4: dwell — consume time parameters but no axis motion
            elif g_num == 4:
                # Example popped U/X in their code; we simply remove dwell params
                for key in list(node.command_parameter.keys()):
                    if key.upper() in ("U", "X"):
                        node.command_parameter.pop(key, None)

        # Delegate to next handler if present
        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None


__all__ = ["GCodeGroup0CoordinateSetExecChainLink"]
