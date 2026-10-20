from __future__ import annotations

from typing import Optional, Tuple, List

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState


class CycleEnd(Handler):
    """Handler to update modal feed/spindle parameters from block parameters.

    This centralizes updating `state.feed_rate` and `state.spindle_speed` so
    motion handlers can rely on modal state being set earlier in the chain.
    """

    def _apply_modal_g_codes(self, node: NCCommandNode, state: CNCState) -> None:
        config = getattr(state, "machine_config", None)
        if config is None:
            return

        control_type = str(getattr(config, "control_type", "")).upper()
        m_code = str(node.command_parameter.get("M", "")).strip()
        if (control_type == "FANUC" and m_code == "99") or (control_type == "SIEMENS" and m_code == "30"):
            node._next_ncCode = None
            return

        cycle_start_code = getattr(config, "cycle_start_code", "").strip().upper()
        if not cycle_start_code:
            return

        is_cycle_start = False
        
        # Check command parameters (e.g. M20 -> M="20", START: -> S="TART:")
        for k, v in node.command_parameter.items():
            if f"{k}{v}".strip().upper() == cycle_start_code:
                is_cycle_start = True
                break

        # Also fallback to check loop_command or variable_command if it wasn't parsed into dict
        if not is_cycle_start:
            is_cycle_start = bool(
                (node.variable_command and cycle_start_code in str(node.variable_command).upper()) or
                (node.loop_command and cycle_start_code in str(node.loop_command).upper())
            )

        if is_cycle_start:
            count = state.channel_state.cycle_start_count or 0
            if count >= 1:
                # Sever the linked list to stop execution
                node._next_ncCode = None
            else:
                state.channel_state.cycle_start_count = count + 1

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        try:
            self._apply_modal_g_codes(node, state)
        except Exception:
            pass

        # Extract block parameters (keys are letters) and update modal state
        try:
            for k, v in node.command_parameter.items():
                key = str(k).upper()
                if key == "F":
                    try:
                        state.feed_rate = float(v)
                    except Exception:
                        # ignore invalid feed values
                        pass
                elif key == "S":
                    try:
                        state.spindle_speed = float(v)
                    except Exception:
                        pass
        except Exception:
            # be defensive: if node.command_parameter is unexpected, ignore
            pass

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None


__all__ = ["CycleEnd"]
