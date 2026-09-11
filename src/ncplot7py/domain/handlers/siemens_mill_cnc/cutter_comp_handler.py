"""Siemens ISO G40/G41/G42 command handling."""

from ncplot7py.domain.handlers.radius_compensation import RadiusCompensationCommandHandler


class SiemensISOCutterCompHandler(RadiusCompensationCommandHandler):
    """Apply Siemens command semantics through shared compensation state."""


__all__ = ["SiemensISOCutterCompHandler"]
