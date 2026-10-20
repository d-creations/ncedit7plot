"""Handler for Siemens ISO Coordinate Systems (G92, G53, G54-G59)."""
from __future__ import annotations

from typing import Optional, Tuple, List

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.siemens_mill_cnc.common import ensure_siemens_scope


class SiemensISOCoordinateHandler(Handler):
    """Handle G92 (Set Work Coordinate), G53 (Machine Coords), G54-G59 (Work Offsets)."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        scope = ensure_siemens_scope(state)
        has_g92 = False
        has_g53 = False
        work_offset_index = None  # 1=G54, 2=G55, ...

        for g in node.g_code:
            if not isinstance(g, str):
                continue
            try:
                if g.upper().startswith("G"):
                    gnum = int(g[1:])
                else:
                    continue
            except Exception:
                continue

            if gnum == 92:
                has_g92 = True
            elif gnum == 53:
                has_g53 = True
            elif 54 <= gnum <= 59:
                work_offset_index = gnum - 53

        if has_g92:
            # G92: Set current position to specified coordinates.
            # We update the current axes values to the G92 parameters.
            for axis, val in list(node.command_parameter.items()):
                if axis.upper() in ["X", "Y", "Z", "A", "B", "C"]:
                    try:
                        state.axes[axis.upper()] = float(val)
                    except Exception:
                        pass
            
            # Consume parameters so MotionHandler doesn't try to move there
            to_remove = [k for k in node.command_parameter if k.upper() in ["X", "Y", "Z", "A", "B", "C"]]
            for k in to_remove:
                node.command_parameter.pop(k, None)

        if has_g53:
            scope["bypass_work_offset_once"] = True

        if work_offset_index is not None:
            state.channel_state.active_work_offset_index = work_offset_index
            state.channel_state.work_offset_index = work_offset_index
            frame = scope.get("frames", {}).get(work_offset_index)
            if frame:
                for axis, value in frame.get("translation", {}).items():
                    state.offsets[axis] = float(value)

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None
