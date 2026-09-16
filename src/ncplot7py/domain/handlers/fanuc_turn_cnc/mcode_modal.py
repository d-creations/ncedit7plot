"""Modal M-code handling for Fanuc turning machines."""

from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler


class FanucTurnModalMCodeHandler(BaseModalMCodeHandler):
    c_axis_reset_codes = {"M3", "M4", "M6"}


__all__ = ["FanucTurnModalMCodeHandler"]