"""Shared state and vector geometry for tool-radius compensation."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ncplot7py.shared.point import Point
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error


def load_tool_data(state, tool_values: list, tool_offsets: list) -> None:
    def identifier(value):
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str) and value:
            return value
        raise ValueError("toolNumber must be a nonnegative integer or a nonempty name")

    def values(record):
        result = {}
        for field in ("qValue", "rValue", "lengthValue", "edgeNumber"):
            value = record.get(field)
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{field} must be a finite number")
            if field == "edgeNumber" and (value < 0 or int(value) != value):
                raise ValueError("edgeNumber must be a nonnegative integer")
            result[field] = value
        return result

    if not isinstance(tool_values, list) or not isinstance(tool_offsets, list):
        raise ValueError("toolValues and toolOffsets must be arrays")
    tools = {}
    offsets = {}
    for record in tool_values:
        if not isinstance(record, dict):
            raise ValueError("Tool records must be objects")
        key = identifier(record.get("toolNumber"))
        if key in tools:
            raise ValueError("Duplicate toolNumber")
        tools[key] = values(record)
    policy = state.machine_config.tool_selection if state.machine_config else {}
    scope = policy.get("offset_scope", "global")
    for record in tool_offsets:
        if not isinstance(record, dict):
            raise ValueError("Offset records must be objects")
        register = record.get("offsetNumber")
        if type(register) is not int or register <= 0:
            raise ValueError("offsetNumber must be a positive integer; zero cancels offsets")
        tool = identifier(record.get("toolNumber")) if scope == "tool" else None
        if scope != "tool" and "toolNumber" in record:
            raise ValueError("Global offsets must not specify toolNumber")
        key = (tool, register)
        if key in offsets:
            raise ValueError("Duplicate offset record")
        offsets[key] = values(record)
    state.extra["tool_compensation_data"] = tools
    state.extra["tool_offset_data"] = offsets


@dataclass
class ToolCompensationState:
    radius_mode: str = "OFF"
    radius: Optional[float] = None
    tip_orientation: Optional[int] = None
    edge_number: Optional[int] = None
    activation_line: Optional[int] = None
    startup_pending: bool = False


@dataclass(frozen=True)
class ActiveToolGeometry:
    tool_id: object
    radius: Optional[float] = None
    tip_orientation: Optional[int] = None
    length: Optional[float] = None
    edge_number: Optional[int] = None


class ToolDataResolver:
    """Resolve geometry for the tool active in one channel state."""

    @staticmethod
    def active_tool_id(state) -> object:
        tool_id = state.extra.get("active_tool_number")
        if tool_id is None:
            tool_id = state.extra.get("active_tool_name")
        return tool_id

    def resolve(self, state, require_offset: bool = True) -> ActiveToolGeometry:
        tool_id = self.active_tool_id(state)
        tool_values = state.extra.get("tool_compensation_data", {})
        values = tool_values.get(tool_id, {}) if tool_id is not None else {}
        register = state.extra.get("active_offset_number")
        offsets = state.extra.get("tool_offset_data", {})
        if register == 0:
            values = {}
        elif offsets:
            policy = state.machine_config.tool_selection if state.machine_config else {}
            owner = tool_id if policy.get("offset_scope") == "tool" else None
            if register is None or (owner, register) not in offsets:
                values = {}
                if require_offset:
                    raise_nc_error(
                        ExceptionTyps.NCCodeErrors, -100,
                        message=f"No compensation data for selected offset {register} and tool {tool_id}",
                    )
            else:
                values = offsets[(owner, register)]
        return ActiveToolGeometry(
            tool_id=tool_id,
            radius=self._optional_float(values.get("rValue")),
            tip_orientation=self._optional_int(values.get("qValue")),
            length=self._optional_float(values.get("lengthValue")),
            edge_number=self._optional_int(values.get("edgeNumber")),
        )

    @staticmethod
    def _optional_float(value: object) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_int(value: object) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class ToolPathCompensator:
    """Offset generated polylines without changing interpolation code."""

    _PLANE_AXES = {
        "X_Y": ("x", "y"),
        "X_Z": ("x", "z"),
        "Y_Z": ("y", "z"),
    }
    _TURN_TIP_TO_CENTER = {
        1: (-1.0, -1.0),
        2: (1.0, -1.0),
        3: (1.0, 1.0),
        4: (-1.0, 1.0),
        5: (0.0, -1.0),
        6: (1.0, 0.0),
        7: (0.0, 1.0),
        8: (-1.0, 0.0),
        9: (0.0, 0.0),
    }

    def __init__(self) -> None:
        self._previous_points: Optional[List[Point]] = None
        self._previous_signature: Optional[Tuple[object, ...]] = None
        self._pending_entry: Optional[List[Point]] = None

    def reset(self) -> None:
        self._previous_points = None
        self._previous_signature = None
        self._pending_entry = None

    def project(self, points: List[Point], state) -> List[Point]:
        compensation = state.tool_compensation
        if state.tool_path_mode != "center" or compensation.radius_mode == "OFF":
            self.reset()
            return points

        radius = compensation.radius
        if radius is None or radius <= 0.0 or len(points) < 2:
            self.reset()
            return points

        plane = str(state.extra.get("g_group_16_plane", "X_Y"))
        axes = self._PLANE_AXES.get(plane)
        if axes is None:
            self.reset()
            return points

        side = 1.0 if compensation.radius_mode == "LEFT" else -1.0
        projected = self._offset_polyline(points, axes, radius * side)
        tip_shift = self._turn_tip_to_center_shift(state, plane, radius)
        if tip_shift is not None:
            self._translate_points(projected, axes, tip_shift)
        signature = (
            compensation.radius_mode,
            radius,
            plane,
            compensation.tip_orientation if tip_shift is not None else None,
            ToolDataResolver.active_tool_id(state),
        )
        has_planar_motion = any(
            math.hypot(
                getattr(end, axes[0]) - getattr(start, axes[0]),
                getattr(end, axes[1]) - getattr(start, axes[1]),
            ) > 1e-12
            for start, end in zip(points, points[1:])
        )
        if not has_planar_motion:
            return projected

        if compensation.startup_pending:
            self.reset()
            compensation.startup_pending = False
            projected[0] = Point(**vars(points[0]))
            self._pending_entry = projected
        elif self._previous_signature == signature:
            if self._pending_entry is not None:
                entry = self._pending_entry
                for axis in axes:
                    start_value = getattr(entry[0], axis)
                    end_value = getattr(projected[0], axis)
                    for index, point in enumerate(entry):
                        fraction = index / (len(entry) - 1)
                        setattr(point, axis, start_value + fraction * (end_value - start_value))
                self._pending_entry = None
            elif self._previous_points is not None:
                self._join_paths(self._previous_points, projected, axes, radius)
        else:
            self._pending_entry = None

        self._previous_points = projected
        self._previous_signature = signature
        return projected

    def _turn_tip_to_center_shift(
        self,
        state,
        plane: str,
        radius: float,
    ) -> Optional[Tuple[float, float]]:
        config = getattr(state, "machine_config", None)
        if config is None or not str(getattr(config, "name", "")).startswith("FANUC_STAR"):
            return None
        if plane != "X_Z":
            return None
        orientation = getattr(state.tool_compensation, "tip_orientation", None)
        if orientation not in self._TURN_TIP_TO_CENTER:
            return None
        vector = self._TURN_TIP_TO_CENTER[orientation]
        return vector[0] * radius, vector[1] * radius

    @staticmethod
    def _translate_points(
        points: List[Point],
        axes: Tuple[str, str],
        shift: Tuple[float, float],
    ) -> None:
        for point in points:
            setattr(point, axes[0], getattr(point, axes[0]) + shift[0])
            setattr(point, axes[1], getattr(point, axes[1]) + shift[1])

    def _offset_polyline(
        self,
        points: List[Point],
        axes: Tuple[str, str],
        signed_radius: float,
    ) -> List[Point]:
        projected = [Point(**vars(point)) for point in points]
        tangents: List[Optional[Tuple[float, float]]] = []
        for start, end in zip(points, points[1:]):
            du = getattr(end, axes[0]) - getattr(start, axes[0])
            dv = getattr(end, axes[1]) - getattr(start, axes[1])
            length = math.hypot(du, dv)
            tangents.append(None if length <= 1e-12 else (du / length, dv / length))

        for index, point in enumerate(projected):
            before = self._nearest_tangent(tangents, index - 1, -1)
            after = self._nearest_tangent(tangents, index, 1)
            tangent = after or before
            if tangent is None:
                continue

            if before is not None and after is not None:
                normal = self._miter_normal(before, after, signed_radius)
            else:
                normal = (-tangent[1] * signed_radius, tangent[0] * signed_radius)
            setattr(point, axes[0], getattr(point, axes[0]) + normal[0])
            setattr(point, axes[1], getattr(point, axes[1]) + normal[1])
        return projected

    @staticmethod
    def _nearest_tangent(
        tangents: List[Optional[Tuple[float, float]]],
        index: int,
        direction: int,
    ) -> Optional[Tuple[float, float]]:
        while 0 <= index < len(tangents):
            if tangents[index] is not None:
                return tangents[index]
            index += direction
        return None

    @staticmethod
    def _miter_normal(
        before: Tuple[float, float],
        after: Tuple[float, float],
        signed_radius: float,
    ) -> Tuple[float, float]:
        first = (-before[1], before[0])
        second = (-after[1], after[0])
        sum_u = first[0] + second[0]
        sum_v = first[1] + second[1]
        length = math.hypot(sum_u, sum_v)
        if length <= 1e-12:
            return first[0] * signed_radius, first[1] * signed_radius
        miter = (sum_u / length, sum_v / length)
        denominator = miter[0] * second[0] + miter[1] * second[1]
        if abs(denominator) <= 1e-9:
            return first[0] * signed_radius, first[1] * signed_radius
        scale = signed_radius / denominator
        limit = abs(signed_radius) * 10.0
        scale = max(-limit, min(limit, scale))
        return miter[0] * scale, miter[1] * scale

    def _join_paths(
        self,
        previous: List[Point],
        current: List[Point],
        axes: Tuple[str, str],
        radius: float,
    ) -> None:
        if len(previous) < 2 or len(current) < 2:
            return
        intersection = self._line_intersection(previous[-2], previous[-1], current[0], current[1], axes)
        if intersection is None:
            return
        corner_distance = math.hypot(
            intersection[0] - getattr(previous[-1], axes[0]),
            intersection[1] - getattr(previous[-1], axes[1]),
        )
        if corner_distance > radius * 10.0:
            return
        setattr(previous[-1], axes[0], intersection[0])
        setattr(previous[-1], axes[1], intersection[1])
        setattr(current[0], axes[0], intersection[0])
        setattr(current[0], axes[1], intersection[1])

    @staticmethod
    def _line_intersection(
        first_start: Point,
        first_end: Point,
        second_start: Point,
        second_end: Point,
        axes: Tuple[str, str],
    ) -> Optional[Tuple[float, float]]:
        x1, y1 = getattr(first_start, axes[0]), getattr(first_start, axes[1])
        x2, y2 = getattr(first_end, axes[0]), getattr(first_end, axes[1])
        x3, y3 = getattr(second_start, axes[0]), getattr(second_start, axes[1])
        x4, y4 = getattr(second_end, axes[0]), getattr(second_end, axes[1])
        denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denominator) <= 1e-12:
            return None
        determinant_1 = x1 * y2 - y1 * x2
        determinant_2 = x3 * y4 - y3 * x4
        return (
            (determinant_1 * (x3 - x4) - (x1 - x2) * determinant_2) / denominator,
            (determinant_1 * (y3 - y4) - (y1 - y2) * determinant_2) / denominator,
        )


__all__ = [
    "ActiveToolGeometry",
    "ToolCompensationState",
    "ToolDataResolver",
    "ToolPathCompensator",
]