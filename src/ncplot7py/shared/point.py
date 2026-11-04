from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Point:
    """Simple point / toolpath vertex used across the codebase.

    Placing this in `shared` ensures the small data shape is available to
    infrastructure and application layers without importing domain handlers.
    """
    x: float
    y: float
    z: float
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0

    def copy(self) -> "Point":
        return Point(self.x, self.y, self.z, self.a, self.b, self.c)


__all__ = ["Point"]
