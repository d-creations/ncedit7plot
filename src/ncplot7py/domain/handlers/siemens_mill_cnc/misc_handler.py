"""Handler for Siemens ISO Misc Codes (G4, G28, etc.)."""
from __future__ import annotations

from typing import Optional, Tuple, List

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState


class SiemensISOMiscHandler(Handler):
    """Handle G4 (Dwell), G28 (Reference Return)."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        has_g4 = False
        has_g28 = False

        for g in node.g_code:
            if not isinstance(g, str):
                continue
            try:
                if g.upper().startswith("G"):
                    gnum = int(g[1:])
                    if gnum == 4:
                        has_g4 = True
                    elif gnum == 28:
                        has_g28 = True
            except Exception:
                continue

        if has_g4:
            # Dwell. Calculate duration.
            # P or X or U usually.
            duration = 0.0
            if "P" in node.command_parameter:
                try:
                    duration = float(node.command_parameter["P"]) / 1000.0  # P is often ms
                except Exception:
                    pass
            elif "X" in node.command_parameter:
                try:
                    duration = float(node.command_parameter["X"])
                except Exception:
                    pass

            # Return no points, but duration
            return [], duration

        if has_g28:
            node.g_code.add("G00")
            home_positions = getattr(getattr(state, "machine_config", None), "home_position", {}) or {}
            axis_map = state.channel_state.axis_map or {}
            inc_map = {"U": "X", "V": "Y", "W": "Z", "H": "C"}
            for key in list(node.command_parameter.keys()):
                upper_key = key.upper()
                mapped = inc_map.get(upper_key, upper_key)
                if mapped not in ("X", "Y", "Z", "A", "B", "C") and mapped not in home_positions:
                    continue
                try:
                    raw = float(node.command_parameter.get(key))
                except Exception:
                    continue
                physical = axis_map.get(mapped, mapped)
                home_val = float(home_positions.get(physical, home_positions.get(mapped, 0.0)))
                target = home_val + raw if upper_key in inc_map else (home_val if raw == 0.0 else raw)
                node.command_parameter[mapped] = str(target)
                if mapped != upper_key:
                    node.command_parameter.pop(key, None)

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None
