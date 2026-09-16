"""Motion handler for G1/G2/G3 moves located in domain.handlers.

This is the domain-located copy of the motion handler implementation.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.point import Point


def _to_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


class MotionHandler(Handler):
    """Handle G0/G1/G2/G3 interpolation.

    Produces (list[Point], duration_seconds) when motion occurs, otherwise
    delegates to next handler.
    """

    def __init__(self, next_handler: Optional[Handler] = None, max_segment: float = 0.5):
        super().__init__(next_handler=next_handler)
        self.max_segment = float(max_segment)

    def _normalize_interp_mode(self, code: Optional[str]) -> Optional[str]:
        if not code:
            return None

        normalized = str(code).strip().upper()
        if normalized in ("G00", "G0"):
            return "G00"
        if normalized in ("G01", "G1"):
            return "G01"
        if normalized in ("G02", "G2"):
            return "G02"
        if normalized in ("G03", "G3"):
            return "G03"
        return None

    @staticmethod
    def _physical_axis(state: CNCState, axis: str) -> str:
        bindings = getattr(state.machine_config, "axis_bindings", {})
        binding = bindings.get(axis) if isinstance(bindings, dict) else None
        if isinstance(binding, dict):
            return str(state.extra.get("star.targetAxis") or axis)
        return axis

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        # detect motion codes
        interp_mode = None  # 'G00','G01','G02','G03'
        for g in node.g_code:
            interp_mode = self._normalize_interp_mode(g) or interp_mode

        configured_axes = {str(axis).upper() for axis in getattr(state.machine_config, "axes", ())}
        motion_axes = {"X", "Y", "Z", "A", "B", "C", "U", "V", "W", "H"} | configured_axes
        seventh_axis_name = self._get_seventh_axis_name(state)
        seventh_axis_maps_to = self._get_seventh_axis_maps_to(state)
        if seventh_axis_name:
            motion_axes.add(seventh_axis_name)
        has_motion_words = any(str(key).upper() in motion_axes for key in node.command_parameter)

        if interp_mode is None and has_motion_words:
            interp_mode = self._normalize_interp_mode(state.get_modal("G_GROUP_1"))

        if interp_mode is None:
            return super().handle(node, state)

        # Resolve start and end positions using state.resolve_target
        start = state.axes.copy()
        # Build absolute-axis targets separately from always-incremental axes.
        absolute_target_spec: Dict[str, float] = {}
        incremental_target_spec: Dict[str, float] = {}
        absolute_mode = True
        # check distance mode modal (G90/G91)
        dm = state.get_modal("distance")
        if dm and dm.upper() == "G91":
            absolute_mode = False

        for k, v in node.command_parameter.items():
            key = k.upper()
            if key in ("X", "Y", "Z", "A", "B", "C"):
                absolute_target_spec[self._physical_axis(state, key)] = _to_float(v)
            elif key in configured_axes:
                absolute_target_spec[key] = _to_float(v)
            elif seventh_axis_name and key == seventh_axis_name:
                value = _to_float(v)
                absolute_target_spec[key] = value
                if seventh_axis_maps_to and seventh_axis_maps_to not in absolute_target_spec:
                    absolute_target_spec[seventh_axis_maps_to] = value
            elif key in ("U", "V", "W", "H"):
                # UVW are incremental XYZ moves and H is an incremental C move.
                mapped = {"U": "X", "V": "Y", "W": "Z", "H": "C"}[key]
                mapped = self._physical_axis(state, mapped)
                incremental_target_spec[mapped] = incremental_target_spec.get(mapped, 0.0) + _to_float(v)
            # I,J,K,R,F handled later
            # I,J,K,R,F handled later

        # Normalize incoming axis values according to cnc_state axis_units
        # (e.g. when X is interpreted as diameter the provided value should be
        # divided by 2 to obtain internal radius coordinates).
        normalized_absolute_target_spec = state.normalize_target_spec(absolute_target_spec)
        normalized_incremental_target_spec = state.normalize_target_spec(incremental_target_spec)

        # get resolved absolute targets, then apply always-incremental axes
        resolved = state.resolve_target(normalized_absolute_target_spec, absolute=absolute_mode)
        for axis, delta in normalized_incremental_target_spec.items():
            resolved[axis] = resolved.get(axis, state.get_axis(axis)) + delta

        # interpolation parameters
        params = {k.upper(): _to_float(v) for k, v in node.command_parameter.items()}
        # Normalize arc parameters (I/J/K offsets and R radius) to internal units
        params = state.normalize_arc_params(params)

        if interp_mode == "G01" or interp_mode == "G00":
            points, duration = self._linear_interpolate(start, resolved, state, rapid=interp_mode == "G00")
        elif interp_mode in ("G02", "G03"):
            cw = interp_mode == "G02"
            points, duration = self._circular_interpolate(start, resolved, params, state, cw)
        else:
            return super().handle(node, state)

        geometry = {
            "G00": "LINEAR",
            "G01": "LINEAR",
            "G02": "ARC_CW",
            "G03": "ARC_CCW",
        }[interp_mode]
        traversal = "RAPID" if interp_mode == "G00" else "FEED"
        node.set_motion_metadata(geometry, traversal, interp_mode)

        # update state axes to endpoint
        state.update_axes(resolved)

        # Modal parameter handling has been moved to a dedicated handler
        # (`ModalHandler`) earlier in the chain. MotionHandler should not
        # mutate modal state; it only consumes values from `state` to
        # compute durations.
        return self._transform_points_for_plot(points, state), duration

    def _linear_interpolate(
        self,
        start: Dict[str, float],
        end: Dict[str, float],
        state: CNCState,
        rapid: bool = False,
    ) -> Tuple[List[Point], float]:
        # compute distance in XYZ space and configured linear add-on axes, then
        # include rotary sweeps as physical travel when the tool is off-center.
        axes = ["X", "Y", "Z"]
        seventh_axis_name = self._get_seventh_axis_name(state)
        if seventh_axis_name and not self._get_seventh_axis_maps_to(state):
            axes.append(seventh_axis_name)
        linear_dist = state.compute_distance(start, end, axes=list(axes))
        rotary_dist = self._estimate_rotary_axes_travel(start, end, state)
        dist = math.hypot(linear_dist, rotary_dist)
        if dist <= 0.0:
            # no motion
            p = Point(x=end.get("X", 0.0), y=end.get("Y", 0.0), z=end.get("Z", 0.0),
                      a=end.get("A", 0.0), b=end.get("B", 0.0), c=end.get("C", 0.0))
            return [p], 0.0

        # determine number of segments. Allow an optional per-state override
        # so callers/tests can request higher resolution by setting
        # `state.extra['max_segment']` to a smaller value (e.g. 0.05).
        try:
            eff_max_segment = float(getattr(state, "extra", {}).get("max_segment", self.max_segment) or self.max_segment)
        except Exception:
            eff_max_segment = float(self.max_segment)
        # ensure sane lower bound
        if eff_max_segment <= 0.0:
            eff_max_segment = float(self.max_segment)
        n = max(1, int(math.ceil(dist / eff_max_segment)))
        if rapid:
            rapid_mm_s = self._get_rapid_mm_s(state)
            duration = dist / rapid_mm_s if rapid_mm_s > 0 else 0.0
        else:
            duration = self._get_feed_duration(dist, state, start, end)

        points: List[Point] = []
        # include explicit start point so joins between segments preserve
        # exact continuity when plotting consecutive motions
        points.append(Point(x=start.get("X", 0.0), y=start.get("Y", 0.0), z=start.get("Z", 0.0),
                             a=start.get("A", 0.0), b=start.get("B", 0.0), c=start.get("C", 0.0)))
        for i in range(1, n + 1):
            t = i / n
            x = start.get("X", 0.0) + (end.get("X", start.get("X", 0.0)) - start.get("X", 0.0)) * t
            y = start.get("Y", 0.0) + (end.get("Y", start.get("Y", 0.0)) - start.get("Y", 0.0)) * t
            z = start.get("Z", 0.0) + (end.get("Z", start.get("Z", 0.0)) - start.get("Z", 0.0)) * t
            a = start.get("A", 0.0) + (end.get("A", start.get("A", 0.0)) - start.get("A", 0.0)) * t
            b = start.get("B", 0.0) + (end.get("B", start.get("B", 0.0)) - start.get("B", 0.0)) * t
            c = start.get("C", 0.0) + (end.get("C", start.get("C", 0.0)) - start.get("C", 0.0)) * t
            points.append(Point(x=x, y=y, z=z, a=a, b=b, c=c))
        return points, duration

    def _get_active_plane(self, state: CNCState) -> str:
        plane = getattr(state, "extra", {}).get("g_group_16_plane", "X_Z")
        if hasattr(plane, "value"):
            plane = plane.value
        plane_name = str(plane)
        if plane_name.endswith("X_Z"):
            return "X_Z"
        if plane_name.endswith("Y_Z"):
            return "Y_Z"
        return "X_Y"

    def _get_plane_spec(self, state: CNCState) -> Tuple[Tuple[str, str], Tuple[str, str], Dict[str, str]]:
        plane = self._get_active_plane(state)
        if plane == "X_Z":
            # Use ordered axes (Z, X) so CW/CCW follows the positive-Y view
            # convention used by G18/ZX plane arcs.
            return ("X", "Z"), ("Z", "X"), {"X": "I", "Z": "K"}
        if plane == "Y_Z":
            return ("Y", "Z"), ("Y", "Z"), {"Y": "J", "Z": "K"}
        return ("X", "Y"), ("X", "Y"), {"X": "I", "Y": "J"}

    def _circular_interpolate(self, start: Dict[str, float], end: Dict[str, float], params: Dict[str, float], state: CNCState, cw: bool) -> Tuple[List[Point], float]:
        plane_axes, ordered_axes, center_letters = self._get_plane_spec(state)

        start_plane = {axis: start.get(axis, 0.0) for axis in plane_axes}
        end_plane = {axis: end.get(axis, start_plane[axis]) for axis in plane_axes}

        start_u = start_plane[ordered_axes[0]]
        start_v = start_plane[ordered_axes[1]]
        end_u = end_plane[ordered_axes[0]]
        end_v = end_plane[ordered_axes[1]]

        # center
        if any(letter in params for letter in center_letters.values()):
            center_by_axis = {}
            for axis in plane_axes:
                center_by_axis[axis] = start_plane[axis] + params.get(center_letters[axis], 0.0)
            center_u = center_by_axis[ordered_axes[0]]
            center_v = center_by_axis[ordered_axes[1]]
        elif "R" in params and params.get("R", 0.0) != 0.0:
            # derive center from radius
            r_val = params.get("R", 0.0)
            r = abs(r_val)
            is_major = r_val < 0
            # compute midpoint
            mx = (start_u + end_u) / 2.0
            my = (start_v + end_v) / 2.0
            dx = end_u - start_u
            dy = end_v - start_v
            d2 = dx * dx + dy * dy
            if d2 == 0.0:
                raise ValueError("Invalid arc with zero chord length")
            h = math.sqrt(max(0.0, r * r - d2 / 4.0)) / math.sqrt(d2)
            # two possible centers
            cx1 = mx - h * dy
            cy1 = my + h * dx
            cx2 = mx + h * dy
            cy2 = my - h * dx

            def directional_sweep(cx_c, cy_c, cw_flag):
                a0_c = math.atan2(start_v - cy_c, start_u - cx_c)
                a1_c = math.atan2(end_v - cy_c, end_u - cx_c)
                da_c = a1_c - a0_c
                if cw_flag:
                    while da_c >= 0:
                        da_c -= 2 * math.pi
                    while da_c < -2 * math.pi:
                        da_c += 2 * math.pi
                else:
                    while da_c <= 0:
                        da_c += 2 * math.pi
                    while da_c > 2 * math.pi:
                        da_c -= 2 * math.pi
                return da_c
            
            da1 = directional_sweep(cx1, cy1, cw)
            da2 = directional_sweep(cx2, cy2, cw)

            if is_major:
                if abs(da1) >= math.pi:
                    center_u, center_v = cx1, cy1
                else:
                    center_u, center_v = cx2, cy2
            else:
                if abs(da1) <= math.pi:
                    center_u, center_v = cx1, cy1
                else:
                    center_u, center_v = cx2, cy2

        else:
            # cannot compute arc center
            raise ValueError("Arc requires I/J or R parameter")

        # compute start and end angles
        a0 = math.atan2(start_v - center_v, start_u - center_u)
        a1 = math.atan2(end_v - center_v, end_u - center_u)

        # Robust sweep normalization:
        # - normalize difference into (-pi, pi]
        # - consider candidates da, da +/- 2pi and pick the candidate that
        #   matches the requested direction (CW -> negative, CCW -> positive)
        #   and has the smallest absolute magnitude. If no candidate matches
        #   the requested sign (rare), pick the candidate with the smallest
        #   absolute value (minor arc).
        def _normalize_sweep(a_start: float, a_end: float, cw_flag: bool) -> float:
            raw = a_end - a_start
            # map to (-pi, pi]
            da = (raw + math.pi) % (2 * math.pi) - math.pi
            # consider equivalent representations
            two_pi = 2 * math.pi
            candidates = [da, da - two_pi, da + two_pi]

            # desired sign: negative for cw (G02), positive for ccw (G03)
            if cw_flag:
                matching = [d for d in candidates if d < 0]
            else:
                matching = [d for d in candidates if d > 0]

            if matching:
                # pick the matching candidate with minimal absolute sweep
                return min(matching, key=abs)
            # fallback: choose the minor arc (smallest absolute value)
            return min(candidates, key=abs)

        da = _normalize_sweep(a0, a1, cw)

        radius = math.hypot(start_u - center_u, start_v - center_v)
        arc_length = abs(da) * radius
        rotary_dist = self._estimate_rotary_axes_travel(start, end, state)
        motion_length = math.hypot(arc_length, rotary_dist)
        # n segments — allow per-state override like in linear interpolation
        try:
            eff_max_segment = float(getattr(state, "extra", {}).get("max_segment", self.max_segment) or self.max_segment)
        except Exception:
            eff_max_segment = float(self.max_segment)
        if eff_max_segment <= 0.0:
            eff_max_segment = float(self.max_segment)
        n = max(2, int(math.ceil(max(motion_length, arc_length) / eff_max_segment)))
        # Ensure a minimum angular resolution so small-radius arcs don't
        # look like corners. Allow callers to override desired degrees per
        # segment via state.extra['angle_per_segment_deg'] (smaller -> more
        # segments). Default to 10 degrees per segment.
        try:
            desired_deg = float(getattr(state, "extra", {}).get("angle_per_segment_deg", 10.0) or 10.0)
        except Exception:
            desired_deg = 2.0
        if desired_deg <= 0.0:
            desired_deg = 2.0
        min_n_by_angle = max(2, int(math.ceil(abs(da) / math.radians(desired_deg))))
        if min_n_by_angle > n:
            n = min_n_by_angle

        # duration using feed rate (see linear routine for comments)
        duration = self._get_feed_duration(motion_length, state, start, end)

        points: List[Point] = []
        points.append(Point(x=start.get("X", 0.0), y=start.get("Y", 0.0), z=start.get("Z", 0.0),
                             a=start.get("A", 0.0), b=start.get("B", 0.0), c=start.get("C", 0.0)))
        for i in range(1, n + 1):
            t = i / n
            theta = a0 + da * t
            point_by_axis = {
                ordered_axes[0]: center_u + math.cos(theta) * radius,
                ordered_axes[1]: center_v + math.sin(theta) * radius,
            }
            x = point_by_axis.get("X", start.get("X", 0.0) + (end.get("X", start.get("X", 0.0)) - start.get("X", 0.0)) * t)
            y = point_by_axis.get("Y", start.get("Y", 0.0) + (end.get("Y", start.get("Y", 0.0)) - start.get("Y", 0.0)) * t)
            z = point_by_axis.get("Z", start.get("Z", 0.0) + (end.get("Z", start.get("Z", 0.0)) - start.get("Z", 0.0)) * t)
            a = start.get("A", 0.0) + (end.get("A", start.get("A", 0.0)) - start.get("A", 0.0)) * t
            b = start.get("B", 0.0) + (end.get("B", start.get("B", 0.0)) - start.get("B", 0.0)) * t
            c = start.get("C", 0.0) + (end.get("C", start.get("C", 0.0)) - start.get("C", 0.0)) * t
            points.append(Point(x=x, y=y, z=z, a=a, b=b, c=c))

        return points, duration

    def _estimate_rotary_axes_travel(self, start: Dict[str, float], end: Dict[str, float], state: CNCState) -> float:
        travel_squared = 0.0
        for axis, plane in self._get_rotary_axis_planes(state).items():
            start_angle = start.get(axis, 0.0)
            end_angle = end.get(axis, start_angle)
            if math.isclose(start_angle, end_angle, abs_tol=1e-9):
                continue

            radius = self._get_rotary_effective_radius(axis, plane, start, end, state)
            if radius <= 1e-9:
                continue
            travel = abs(math.radians(end_angle - start_angle)) * radius
            travel_squared += travel * travel
        return math.sqrt(travel_squared)

    def _transform_points_for_plot(self, points: List[Point], state: CNCState) -> List[Point]:
        center_x, center_y, center_z = self._get_rotary_center(state)
        transformed: List[Point] = []
        for point in points:
            plot_x, plot_y, plot_z = point.x, point.y, point.z
            for axis, plane in self._get_rotary_axis_planes(state).items():
                angle = getattr(point, axis.lower(), 0.0)
                plot_x, plot_y, plot_z = self._rotate_point_in_plane(
                    plot_x,
                    plot_y,
                    plot_z,
                    center_x,
                    center_y,
                    center_z,
                    plane,
                    angle,
                )
            transformed.append(Point(x=plot_x, y=plot_y, z=plot_z, a=point.a, b=point.b, c=point.c))
        return transformed

    def _get_c_axis_center(self, state: CNCState) -> Tuple[float, float]:
        center = getattr(state, "extra", {}).get("c_axis_center", getattr(state, "extra", {}).get("rotary_center", (0.0, 0.0)))
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            return float(center[0]), float(center[1])
        return 0.0, 0.0

    def _get_rotary_center(self, state: CNCState) -> Tuple[float, float, float]:
        center = getattr(state, "extra", {}).get("rotary_center", None)
        if isinstance(center, (list, tuple)) and len(center) >= 3:
            return float(center[0]), float(center[1]), float(center[2])
        center_x, center_y = self._get_c_axis_center(state)
        return center_x, center_y, 0.0

    def _get_rotary_axis_planes(self, state: CNCState) -> Dict[str, str]:
        planes = getattr(getattr(state, "machine_config", None), "rotary_axis_planes", None)
        if not isinstance(planes, dict):
            planes = {"A": "YZ", "B": "XZ", "C": "XY"}
        return {str(axis).upper(): str(plane).upper().replace("_", "") for axis, plane in planes.items() if axis and plane}

    def _get_seventh_axis_name(self, state: CNCState) -> Optional[str]:
        name = getattr(getattr(state, "machine_config", None), "seventh_axis_name", None)
        if name is None:
            name = getattr(state, "extra", {}).get("seventh_axis_name")
        if name is None:
            return None
        text = str(name).strip().upper()
        return text or None

    def _get_seventh_axis_maps_to(self, state: CNCState) -> Optional[str]:
        mapped = getattr(getattr(state, "machine_config", None), "seventh_axis_maps_to", None)
        if mapped is None:
            mapped = getattr(state, "extra", {}).get("seventh_axis_maps_to")
        if mapped is None:
            return None
        text = str(mapped).strip().upper()
        return text if text in {"X", "Y", "Z", "A", "B", "C"} else None

    def _get_rotary_effective_radius(
        self,
        axis: str,
        plane: str,
        start: Dict[str, float],
        end: Dict[str, float],
        state: CNCState,
    ) -> float:
        center_x, center_y, center_z = self._get_rotary_center(state)

        def radius(position: Dict[str, float]) -> float:
            if plane == "YZ":
                return math.hypot(position.get("Y", 0.0) - center_y, position.get("Z", 0.0) - center_z)
            if plane == "XZ":
                return math.hypot(position.get("X", 0.0) - center_x, position.get("Z", 0.0) - center_z)
            return math.hypot(position.get("X", 0.0) - center_x, position.get("Y", 0.0) - center_y)

        return max(radius(start), radius(end))

    def _rotate_point_in_plane(
        self,
        x: float,
        y: float,
        z: float,
        center_x: float,
        center_y: float,
        center_z: float,
        plane: str,
        angle_deg: float,
    ) -> Tuple[float, float, float]:
        if math.isclose(angle_deg, 0.0, abs_tol=1e-12):
            return x, y, z

        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        rel_x = x - center_x
        rel_y = y - center_y
        rel_z = z - center_z

        if plane == "YZ":
            return x, center_y + rel_y * cos_a - rel_z * sin_a, center_z + rel_y * sin_a + rel_z * cos_a
        if plane == "XZ":
            return center_x + rel_x * cos_a - rel_z * sin_a, y, center_z + rel_x * sin_a + rel_z * cos_a
        return center_x + rel_x * cos_a - rel_y * sin_a, center_y + rel_x * sin_a + rel_y * cos_a, z

    def _get_feed_mm_s(
        self,
        state: CNCState,
        start: Optional[Dict[str, float]] = None,
        end: Optional[Dict[str, float]] = None,
    ) -> float:
        feed = state.feed_rate or 1.0
        extra = getattr(state, "extra", {})
        feed_mode = extra.get("feed_mode") if isinstance(extra, dict) else None
        feed_mode_value = getattr(feed_mode, "value", feed_mode)

        effective_feed_mm_per_min = float(feed)
        if feed_mode_value == "FEED_PER_REV":
            rpm = float(state.spindle_speed or 1.0)
            speed_mode = extra.get("surface_speed_mode") if isinstance(extra, dict) else None
            if getattr(speed_mode, "value", speed_mode) == "CONSTANT_CUTSPEED":
                diameter = self._get_average_cutting_diameter(state, start, end)
                if diameter > 0.0:
                    rpm = (1000.0 * rpm) / (math.pi * diameter)
            spindle_limit = extra.get("spindle_speed_limit") if isinstance(extra, dict) else None
            limit_active = extra.get("spindle_speed_limit_active", False) if isinstance(extra, dict) else False
            if spindle_limit is not None and limit_active:
                rpm = min(rpm, float(spindle_limit))
            spindle_maximum = extra.get("spindle_speed_maximum") if isinstance(extra, dict) else None
            if spindle_maximum is not None:
                rpm = min(rpm, float(spindle_maximum))
            spindle_minimum = extra.get("spindle_speed_minimum") if isinstance(extra, dict) else None
            if spindle_minimum is not None:
                rpm = max(rpm, float(spindle_minimum))
            effective_feed_mm_per_min = float(feed) * rpm

        return effective_feed_mm_per_min / 60.0

    def _get_feed_duration(
        self,
        distance: float,
        state: CNCState,
        start: Optional[Dict[str, float]] = None,
        end: Optional[Dict[str, float]] = None,
    ) -> float:
        extra = getattr(state, "extra", {})
        feed_mode = extra.get("feed_mode") if isinstance(extra, dict) else None
        if getattr(feed_mode, "value", feed_mode) == "INVERSE_TIME":
            feed = float(state.feed_rate or 0.0)
            return 60.0 / feed if feed > 0.0 else 0.0
        feed_mm_s = self._get_feed_mm_s(state, start, end)
        return distance / feed_mm_s if feed_mm_s > 0.0 else 0.0

    def _get_average_cutting_diameter(
        self,
        state: CNCState,
        start: Optional[Dict[str, float]],
        end: Optional[Dict[str, float]],
    ) -> float:
        extra = getattr(state, "extra", {})
        runtime_axis = extra.get("g96_reference_axis") if isinstance(extra, dict) else None
        configured_axis = getattr(getattr(state, "machine_config", None), "g96_reference_axis", None)
        reference_axis = str(runtime_axis or configured_axis or "").strip().upper()
        if not reference_axis:
            configured_axes = list(getattr(getattr(state, "machine_config", None), "diameter_axes", ()) or ())
            diameter_axes = [str(axis).upper() for axis in configured_axes]
            if not diameter_axes:
                diameter_axes = [axis for axis in state.axes if state.is_axis_diameter(axis)]
            reference_axis = diameter_axes[0] if diameter_axes else ""
        if not reference_axis:
            return 0.0

        axis = reference_axis
        start_radius = float((start or state.axes).get(axis, state.get_axis(axis)))
        end_radius = float((end or state.axes).get(axis, start_radius))
        if start_radius * end_radius < 0.0:
            travel = abs(end_radius - start_radius)
            average_radius = (start_radius * start_radius + end_radius * end_radius) / (2.0 * travel)
        else:
            average_radius = (abs(start_radius) + abs(end_radius)) / 2.0
        return 2.0 * average_radius

    def _get_rapid_mm_s(self, state: CNCState) -> float:
        try:
            rapid_feed_rate = getattr(getattr(state, "machine_config", None), "rapid_feed_rate", None)
            if rapid_feed_rate is None:
                return 0.0
            rapid_mm_per_min = float(rapid_feed_rate)
        except Exception:
            return 0.0

        return rapid_mm_per_min / 60.0 if rapid_mm_per_min > 0 else 0.0


__all__ = ["MotionHandler", "Point"]

