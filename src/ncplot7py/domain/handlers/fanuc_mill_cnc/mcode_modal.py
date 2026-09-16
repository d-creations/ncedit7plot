"""Modal M-code handling for Fanuc milling machines."""

from ncplot7py.domain.handlers.mcode_modal import BaseModalMCodeHandler


class FanucMillModalMCodeHandler(BaseModalMCodeHandler):
    c_axis_reset_codes = {"M6"}


__all__ = ["FanucMillModalMCodeHandler"]