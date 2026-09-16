"""Modal M-code handling for Star turning machines."""

from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarModalMCodeHandler(BaseModalMCodeHandler):
    c_axis_reset_codes = {"M3", "M4", "M6", "M9"}

    def _return_c_axis_to_zero(self, node: NCCommandNode, state: CNCState):
        axis = state.extra.get("star.targetAxis")
        if axis not in {"C1", "C2"}:
            return super()._return_c_axis_to_zero(node, state)

        reset_node = NCCommandNode(
            g_code_command={"G0"},
            command_parameter={axis: "0"},
            nc_code_line_nr=node.nc_code_line_nr,
        )
        if self.next_handler is None:
            state.set_axis(axis, 0.0)
            return None, None
        return self.next_handler.handle(reset_node, state)

    def _apply_machine_specific_state(self, m_code, state):
        if m_code == "M8":
            state.extra["star.c_axis_mode"] = "positionControlled"
        elif m_code == "M9":
            state.extra["star.c_axis_mode"] = "spindleInvariant"
        if m_code in {"M171", "M172"}:
            state.extra["star.path_mode"] = m_code
            if m_code == "M171":
                state.extra["star.targetCarrierId"] = "mainSpindle"
                state.extra["star.targetAxis"] = "C1"
            else:
                state.extra["star.targetCarrierId"] = "subSpindle"
                state.extra["star.targetAxis"] = "C2"
        elif m_code in {"M40", "M41"}:
            state.extra["star.machining_mode"] = m_code


__all__ = ["StarModalMCodeHandler"]