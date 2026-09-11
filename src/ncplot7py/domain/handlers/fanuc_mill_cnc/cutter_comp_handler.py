"""FANUC milling G40/G41/G42 command handler."""

from ncplot7py.domain.handlers.radius_compensation import RadiusCompensationCommandHandler


class FanucCutterCompCommandHandler(RadiusCompensationCommandHandler):
    """Apply FANUC command semantics through the shared compensation state."""


__all__ = ["FanucCutterCompCommandHandler"]