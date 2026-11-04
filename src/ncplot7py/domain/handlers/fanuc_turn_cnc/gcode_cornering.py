from __future__ import annotations

import math
from typing import Optional, Tuple, List, Dict

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState


def _to_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


class FanucCorneringHandler(Handler):
    """Handler for Fanuc-style Chamfering (C, ,C, I, K), Corner R (R, ,R), and DDDP Angle (A, ,A).

    Implements look-ahead buffer logic to process cornering and direct drawing
    dimension programming (DDDP) blocks in G01 linear interpolation.
    """

    _INCREMENTAL_TO_LOGICAL = {"U": "X", "V": "Y", "W": "Z", "H": "C"}
    _LOGICAL_TO_INCREMENTAL = {"X": "U", "Y": "V", "Z": "W", "C": "H"}
    _NON_MOTION_G_CODES = {
        "G04", "G4", "G10", "G28", "G30", "G50", "G52", "G53",
        "G65", "G66", "G67", "G68", "G68.1", "G69", "G69.1",
        "G70", "G71", "G72", "G73", "G74", "G75", "G76",
        "G80", "G83", "G84", "G85", "G87", "G89", "G92",
        "G125", "G130", "G131", "G132", "G133", "G161", "G162", "G163", "G266", "G300",
    }

    def _get_active_plane_axes(self, state: CNCState) -> Tuple[str, str]:
        # Determine the active plane (G17: X-Y, G18: Z-X, G19: Y-Z)
        channel_state = getattr(state, "channel_state", None)
        plane = (
            channel_state.plane
            if channel_state is not None and channel_state.plane is not None
            else getattr(state, "extra", {}).get("g_group_16_plane")
        ) or "X_Z"
        if hasattr(plane, "value"):
            plane = plane.value
        plane_name = str(plane)
        if plane_name.endswith("X_Y"):
            return ("X", "Y")
        if plane_name.endswith("Y_Z"):
            return ("Y", "Z")
        return ("Z", "X")  # Default to G18 Z-X for lathe

    @staticmethod
    def _normalize_interp_mode(code: Optional[str]) -> Optional[str]:
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

    def _effective_interp_mode(self, node: NCCommandNode, state: CNCState, default_mode: Optional[str] = None) -> Optional[str]:
        codes = {str(g).strip().upper() for g in node.g_code}
        if codes & self._NON_MOTION_G_CODES:
            return None
        interp_mode = None
        for g in node.g_code:
            interp_mode = self._normalize_interp_mode(g) or interp_mode
        if interp_mode is not None:
            return interp_mode
        fallback = default_mode if default_mode is not None else self._normalize_interp_mode(state.get_modal("G_GROUP_1"))
        return fallback

    @staticmethod
    def _is_c_axis_rotary_active(state: CNCState) -> bool:
        if getattr(state, "machining_mode", None) == "milling":
            return True
        if getattr(state.star_state, "c_axis_mode", None) == "positionControlled":
            return True
        if getattr(state.siemens_state, "c_axis_mode", None) == "positionControlled":
            return True
        if getattr(state.channel_state, "polar_star_mode", None) == "POLAR_COORDINATE_ON":
            return True
        return False

    def _extract_corner_and_angle(
        self,
        node: NCCommandNode,
        state: CNCState,
        ax1: str,
        ax2: str,
        consume: bool = True,
    ) -> Tuple[Optional[str], float, Optional[float]]:
        corner_type: Optional[str] = None
        corner_val = 0.0
        angle_val: Optional[float] = None

        # 1. Check DDDP comma parameters (e.g. ',C0.2', ',R0.5', ',A10.0')
        for dddp in list(node.dddp_command):
            up_dddp = dddp.strip().upper()
            if up_dddp.startswith(",C"):
                corner_type = "CHAMFER"
                corner_val = _to_float(up_dddp[2:])
                if consume:
                    node.dddp_command.remove(dddp)
            elif up_dddp.startswith(",R"):
                corner_type = "CORNER_R"
                corner_val = _to_float(up_dddp[2:])
                if consume:
                    node.dddp_command.remove(dddp)
            elif up_dddp.startswith(",A"):
                angle_val = _to_float(up_dddp[2:])
                if consume:
                    node.dddp_command.remove(dddp)

        # 2. Check non-comma Fanuc cornering / angle parameters ('C', 'I', 'K', 'R', 'A')
        has_plane_motion = any(
            k.upper() in {ax1, ax2, self._LOGICAL_TO_INCREMENTAL.get(ax1, ""), self._LOGICAL_TO_INCREMENTAL.get(ax2, "")}
            for k in node.command_parameter
        )
        c_rotary = self._is_c_axis_rotary_active(state)

        for key in list(node.command_parameter.keys()):
            upper_key = key.upper()
            if upper_key in ("I", "K") and corner_type is None:
                corner_type = "CHAMFER"
                corner_val = _to_float(node.command_parameter.pop(key) if consume else node.command_parameter[key])
            elif upper_key == "C" and corner_type is None:
                # Treat 'C' without comma as chamfer only when not in C-axis rotary/milling mode
                # and when accompanied by planar X/Z motion or DDDP angle.
                if not c_rotary and (has_plane_motion or angle_val is not None or "A" in {k.upper() for k in node.command_parameter}):
                    corner_type = "CHAMFER"
                    corner_val = _to_float(node.command_parameter.pop(key) if consume else node.command_parameter[key])
            elif upper_key == "R" and corner_type is None:
                corner_type = "CORNER_R"
                corner_val = _to_float(node.command_parameter.pop(key) if consume else node.command_parameter[key])
            elif upper_key == "A" and angle_val is None:
                angle_val = _to_float(node.command_parameter.pop(key) if consume else node.command_parameter[key])

        return corner_type, corner_val, angle_val

    @staticmethod
    def _physical_axis(state: CNCState, axis: str) -> str:
        axis_map = getattr(getattr(state, "channel_state", None), "axis_map", None)
        if isinstance(axis_map, dict) and axis in axis_map:
            return str(axis_map[axis])
        return axis

    def _is_axis_diameter(self, state: CNCState, axis: str) -> bool:
        phys = self._physical_axis(state, axis)
        return state.is_axis_diameter(axis) or state.is_axis_diameter(phys)

    def _normalize_axis_value(self, state: CNCState, axis: str, value: float) -> float:
        return value / 2.0 if self._is_axis_diameter(state, axis) else value

    def _extract_plane_specs(
        self,
        node: NCCommandNode,
        state: CNCState,
        ax1: str,
        ax2: str,
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Extract normalized (radius) absolute and incremental specifications for ax1 and ax2."""
        abs_spec: Dict[str, float] = {}
        inc_spec: Dict[str, float] = {}
        inc1 = self._LOGICAL_TO_INCREMENTAL.get(ax1)
        inc2 = self._LOGICAL_TO_INCREMENTAL.get(ax2)

        for k, v in node.command_parameter.items():
            uk = k.upper()
            if uk in (ax1, ax2):
                abs_spec[uk] = self._normalize_axis_value(state, uk, _to_float(v))
            elif uk == inc1:
                inc_spec[ax1] = inc_spec.get(ax1, 0.0) + self._normalize_axis_value(state, ax1, _to_float(v))
            elif uk == inc2:
                inc_spec[ax2] = inc_spec.get(ax2, 0.0) + self._normalize_axis_value(state, ax2, _to_float(v))

        return abs_spec, inc_spec

    @staticmethod
    def _resolve_from_origin(
        origin_1: float,
        origin_2: float,
        ax1: str,
        ax2: str,
        abs_spec: Dict[str, float],
        inc_spec: Dict[str, float],
        absolute_mode: bool,
    ) -> Tuple[float, float, bool, bool]:
        has_1 = (ax1 in abs_spec) or (ax1 in inc_spec)
        has_2 = (ax2 in abs_spec) or (ax2 in inc_spec)

        if absolute_mode:
            val_1 = abs_spec[ax1] if ax1 in abs_spec else origin_1
            val_2 = abs_spec[ax2] if ax2 in abs_spec else origin_2
        else:
            val_1 = origin_1 + abs_spec.get(ax1, 0.0)
            val_2 = origin_2 + abs_spec.get(ax2, 0.0)

        if ax1 in inc_spec:
            val_1 += inc_spec[ax1]
        if ax2 in inc_spec:
            val_2 += inc_spec[ax2]

        return val_1, val_2, has_1, has_2

    def _format_program_coord(self, state: CNCState, axis: str, internal_val: float) -> str:
        mult = 2.0 if self._is_axis_diameter(state, axis) else 1.0
        return str(round(internal_val * mult, 6))

    def _set_node_plane_target(
        self,
        node: NCCommandNode,
        state: CNCState,
        ax1: str,
        ax2: str,
        val_1: float,
        val_2: float,
    ) -> None:
        node._command_parameter[ax1] = self._format_program_coord(state, ax1, val_1)
        node._command_parameter[ax2] = self._format_program_coord(state, ax2, val_2)
        inc1 = self._LOGICAL_TO_INCREMENTAL.get(ax1)
        inc2 = self._LOGICAL_TO_INCREMENTAL.get(ax2)
        if inc1:
            node._command_parameter.pop(inc1, None)
        if inc2:
            node._command_parameter.pop(inc2, None)

    def _find_next_motion(self, node: NCCommandNode, state: CNCState) -> Optional[NCCommandNode]:
        curr = node._next_ncCode
        modal_g1 = "G01"
        while curr is not None:
            mode = self._effective_interp_mode(curr, state, default_mode=modal_g1)
            if mode is not None:
                ax1, ax2 = self._get_active_plane_axes(state)
                plane_words = {
                    ax1, ax2,
                    self._LOGICAL_TO_INCREMENTAL.get(ax1, ""),
                    self._LOGICAL_TO_INCREMENTAL.get(ax2, ""),
                    "A",
                }
                has_motion_or_dddp = (
                    any(k.upper() in plane_words for k in curr.command_parameter)
                    or any(d.strip().upper().startswith((",A", ",C", ",R")) for d in curr.dddp_command)
                )
                if has_motion_or_dddp:
                    return curr
            curr = curr._next_ncCode
        return None

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        # Only process G01 moves (explicit or modal)
        interp_mode = self._effective_interp_mode(node, state)
        if interp_mode != "G01":
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        ax1, ax2 = self._get_active_plane_axes(state)
        corner_type, corner_val, angle_val = self._extract_corner_and_angle(node, state, ax1, ax2, consume=True)
        has_corner = corner_type is not None and abs(corner_val) > 1e-9

        if not has_corner and angle_val is None:
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        # Current start position in internal (radius) coordinates
        start_1 = state.get_axis(ax1)
        start_2 = state.get_axis(ax2)

        dm = state.get_modal("distance")
        absolute_mode = not (dm and dm.upper() == "G91")

        abs_spec_1, inc_spec_1 = self._extract_plane_specs(node, state, ax1, ax2)
        corner_1, corner_2, has_1, has_2 = self._resolve_from_origin(
            start_1, start_2, ax1, ax2, abs_spec_1, inc_spec_1, absolute_mode
        )

        # Case A: Single-block DDDP angle move with one endpoint coordinate and NO cornering (,C / ,R)
        # e.g., G1 X50.0 ,A150.0  or  G1 Z-20.0 ,A-30.0
        if angle_val is not None and not has_corner and (has_1 or has_2):
            rad = math.radians(angle_val)
            v_dir_1 = math.cos(rad)
            v_dir_2 = math.sin(rad)
            if has_1 and not has_2 and abs(v_dir_1) > 1e-6:
                t = (corner_1 - start_1) / v_dir_1
                corner_2 = start_2 + t * v_dir_2
            elif has_2 and not has_1 and abs(v_dir_2) > 1e-6:
                t = (corner_2 - start_2) / v_dir_2
                corner_1 = start_1 + t * v_dir_1
            self._set_node_plane_target(node, state, ax1, ax2, corner_1, corner_2)
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        # Look ahead to next motion block
        next_motion = self._find_next_motion(node, state)
        if next_motion is None:
            if angle_val is not None:
                rad = math.radians(angle_val)
                v_dir_1 = math.cos(rad)
                v_dir_2 = math.sin(rad)
                if has_1 and not has_2 and abs(v_dir_1) > 1e-6:
                    t = (corner_1 - start_1) / v_dir_1
                    corner_2 = start_2 + t * v_dir_2
                    self._set_node_plane_target(node, state, ax1, ax2, corner_1, corner_2)
                elif has_2 and not has_1 and abs(v_dir_2) > 1e-6:
                    t = (corner_2 - start_2) / v_dir_2
                    corner_1 = start_1 + t * v_dir_1
                    self._set_node_plane_target(node, state, ax1, ax2, corner_1, corner_2)
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        # Inspect next_motion without consuming its own cornering parameters yet
        _, _, next_angle_val = self._extract_corner_and_angle(next_motion, state, ax1, ax2, consume=False)
        abs_spec_2, inc_spec_2 = self._extract_plane_specs(next_motion, state, ax1, ax2)

        # Resolve corner_1, corner_2 when angle_val is specified on current node
        if angle_val is not None:
            rad = math.radians(angle_val)
            v_dir_1 = math.cos(rad)
            v_dir_2 = math.sin(rad)

            if has_1 and not has_2:
                if abs(v_dir_1) > 1e-6:
                    t = (corner_1 - start_1) / v_dir_1
                    corner_2 = start_2 + t * v_dir_2
            elif has_2 and not has_1:
                if abs(v_dir_2) > 1e-6:
                    t = (corner_2 - start_2) / v_dir_2
                    corner_1 = start_1 + t * v_dir_1
            elif not has_1 and not has_2:
                # 2-block DDDP intersection: current block only has angle (and optional ,R/,C),
                # next block has endpoint (and optional second angle).
                end_1_prelim, end_2_prelim, has_next_1, has_next_2 = self._resolve_from_origin(
                    start_1, start_2, ax1, ax2, abs_spec_2, inc_spec_2, absolute_mode
                )
                if next_angle_val is not None and has_next_1 and has_next_2:
                    # Intersect ray from (start_1, start_2) along angle_val
                    # with line through (end_1_prelim, end_2_prelim) along next_angle_val
                    rad2 = math.radians(next_angle_val)
                    v2_dir_1 = math.cos(rad2)
                    v2_dir_2 = math.sin(rad2)
                    det = v_dir_1 * (-v2_dir_2) - v_dir_2 * (-v2_dir_1)
                    if abs(det) > 1e-6:
                        rhs_1 = end_1_prelim - start_1
                        rhs_2 = end_2_prelim - start_2
                        t1 = (rhs_1 * (-v2_dir_2) - rhs_2 * (-v2_dir_1)) / det
                        corner_1 = start_1 + t1 * v_dir_1
                        corner_2 = start_2 + t1 * v_dir_2
                    # Consume next_angle_val since next_motion's line is now fully determined from corner -> end
                    for dddp in list(next_motion.dddp_command):
                        if dddp.strip().upper().startswith(",A"):
                            next_motion.dddp_command.remove(dddp)
                    next_motion.command_parameter.pop("A", None)
                elif has_next_1 and not has_next_2:
                    if abs(v_dir_1) > 1e-6:
                        t = (end_1_prelim - start_1) / v_dir_1
                        corner_1 = end_1_prelim
                        corner_2 = start_2 + t * v_dir_2
                elif has_next_2 and not has_next_1:
                    if abs(v_dir_2) > 1e-6:
                        t = (end_2_prelim - start_2) / v_dir_2
                        corner_2 = end_2_prelim
                        corner_1 = start_1 + t * v_dir_1

        # If there is no cornering (,C / ,R), we only needed to resolve the intersection point for `node`
        if not has_corner:
            self._set_node_plane_target(node, state, ax1, ax2, corner_1, corner_2)
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        # Resolve P_end of next_motion starting from the true P_corner (corner_1, corner_2)
        end_1, end_2, has_next_1, has_next_2 = self._resolve_from_origin(
            corner_1, corner_2, ax1, ax2, abs_spec_2, inc_spec_2, absolute_mode
        )
        if next_angle_val is not None and (has_next_1 ^ has_next_2):
            rad2 = math.radians(next_angle_val)
            v2_dir_1 = math.cos(rad2)
            v2_dir_2 = math.sin(rad2)
            if has_next_1 and not has_next_2 and abs(v2_dir_1) > 1e-6:
                t2 = (end_1 - corner_1) / v2_dir_1
                end_2 = corner_2 + t2 * v2_dir_2
            elif has_next_2 and not has_next_1 and abs(v2_dir_2) > 1e-6:
                t2 = (end_2 - corner_2) / v2_dir_2
                end_1 = corner_1 + t2 * v2_dir_1

        # -------------------------------------------------------------
        # 2. Vector Math for Intersection Offset calculation
        # -------------------------------------------------------------
        # Vector V1: Corner -> Start
        dx1, dy1 = start_1 - corner_1, start_2 - corner_2
        len1 = math.hypot(dx1, dy1)

        # Vector V2: Corner -> End
        dx2, dy2 = end_1 - corner_1, end_2 - corner_2
        len2 = math.hypot(dx2, dy2)

        # If zero length lines, geometry fails, fallback to normal linear move to corner
        if len1 < 1e-6 or len2 < 1e-6:
            self._set_node_plane_target(node, state, ax1, ax2, corner_1, corner_2)
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        v1x, v1y = dx1 / len1, dy1 / len1
        v2x, v2y = dx2 / len2, dy2 / len2

        # Interior angle theta between V1 (Corner->Start) and V2 (Corner->End)
        dot = max(-1.0, min(1.0, v1x * v2x + v1y * v2y))
        theta = math.acos(dot)

        # Cross product to determine CW vs CCW in (ax1, ax2) plane:
        # Incoming tangent is -V1 = (-v1x, -v1y), outgoing tangent is V2 = (v2x, v2y).
        # Turn Z-component = (-v1x)*v2y - (-v1y)*v2x = v1y*v2x - v1x*v2y.
        # Negative turn in right-handed (ax1, ax2) coordinates means clockwise (G02).
        cross = v1y * v2x - v1x * v2y
        cw = cross < 0

        if theta < 1e-6 or abs(theta - math.pi) < 1e-6:
            # Parallel or collinear lines
            self._set_node_plane_target(node, state, ax1, ax2, corner_1, corner_2)
            if self.next_handler is not None:
                return self.next_handler.handle(node, state)
            return None, None

        # -------------------------------------------------------------
        # 3. Calculate Corner Trim Points & Execute Combined Segments
        # -------------------------------------------------------------
        if corner_type == "CORNER_R":
            R = abs(corner_val)
            tan_half = math.tan(theta / 2.0)
            D = R / tan_half
            blend_g_code = "G02" if cw else "G03"
            blend_geometry = "ARC_CW" if cw else "ARC_CCW"
        else:  # "CHAMFER"
            # In Fanuc turning / DDDP, chamfer size C (,C, C, I, K) is the distance
            # from the hypothetical corner point along each leg.
            D = abs(corner_val)
            blend_g_code = "G01"
            blend_geometry = "LINEAR"

        # Clamp D slightly within segment lengths if needed to avoid inverted segments
        p_start_new_1 = corner_1 + D * v1x
        p_start_new_2 = corner_2 + D * v1y

        p_end_new_1 = corner_1 + D * v2x
        p_end_new_2 = corner_2 + D * v2y

        # Update current node to move to p_start_new
        self._set_node_plane_target(node, state, ax1, ax2, p_start_new_1, p_start_new_2)

        # Update next_motion to ensure its starting assumptions remain valid if it used incremental U/W
        # without an angle override
        if any(k.upper() in ("U", "V", "W") for k in next_motion.command_parameter):
            self._set_node_plane_target(next_motion, state, ax1, ax2, end_1, end_2)
        if not any(self._normalize_interp_mode(g) for g in next_motion.g_code):
            next_motion._g_code.add("G01")

        if self.next_handler is None:
            return None, None

        # Execute the trimmed linear segment first
        pts1, dur1 = self.next_handler.handle(node, state)

        # Now execute the corner blend (arc or chamfer) as a second segment on the same line
        synthetic_node = NCCommandNode(
            g_code_command={blend_g_code},
            command_parameter={
                ax1: self._format_program_coord(state, ax1, p_end_new_1),
                ax2: self._format_program_coord(state, ax2, p_end_new_2),
            },
            nc_code_line_nr=node.nc_code_line_nr,
        )
        if corner_type == "CORNER_R":
            synthetic_node._command_parameter["R"] = str(abs(corner_val))

        pts2, dur2 = self.next_handler.handle(synthetic_node, state)

        segments: List[Dict[str, object]] = []
        combined_points: List = []
        total_duration = 0.0

        if pts1:
            segments.append({
                "points": pts1,
                "duration": float(dur1 or 0.0),
                "geometry": "LINEAR",
                "traversal": "FEED",
                "source_code": "G01",
            })
            combined_points.extend(pts1)
            total_duration += float(dur1 or 0.0)

        if pts2:
            segments.append({
                "points": pts2,
                "duration": float(dur2 or 0.0),
                "geometry": blend_geometry,
                "traversal": "FEED",
                "source_code": blend_g_code,
            })
            if combined_points:
                combined_points.extend(pts2[1:] if len(pts2) > 1 else pts2)
            else:
                combined_points.extend(pts2)
            total_duration += float(dur2 or 0.0)

        if segments:
            node.set_generated_motion_segments(segments)

        return combined_points if combined_points else pts1, total_duration

