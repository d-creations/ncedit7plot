"""Modal M-code handling for Star turning machines."""

from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler


class StarModalMCodeHandler(BaseModalMCodeHandler):
    c_axis_reset_codes = {"M3", "M4", "M9"}

    def _apply_machine_specific_state(self, m_code, state):
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