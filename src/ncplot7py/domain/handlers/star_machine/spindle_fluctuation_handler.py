"""Star spindle-speed fluctuation detection for G25 and G26."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarSpindleFluctuationHandler(Handler):
    """Toggle Star spindle-speed fluctuation monitoring."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        has_g25 = "G25" in codes
        has_g26 = "G26" in codes

        if has_g25 and has_g26:
            raise_nc_error(
                ExceptionTyps.NCCanalStarErrors,
                25,
                message="Conflicting spindle fluctuation commands G25 and G26",
                value=str(node.g_code),
                line=node.nc_code_line_nr or 0,
            )

        if has_g25:
            state.set_modal("star_spindle_fluctuation", "G25")
            state.star_state.spindle_fluctuation_monitoring = False
        elif has_g26:
            state.set_modal("star_spindle_fluctuation", "G26")
            state.star_state.spindle_fluctuation_monitoring = True

        return super().handle(node, state)


__all__ = ["StarSpindleFluctuationHandler"]