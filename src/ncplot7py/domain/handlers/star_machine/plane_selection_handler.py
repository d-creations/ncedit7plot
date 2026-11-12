"""Star Group 16 plane selection handler for G17, G18, G19, G117, G118, and G119."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group16_plane import (
    GCodeGroup16PlaneExecChainLink,
    PlaneMode,
)
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarPlaneSelectionHandler(GCodeGroup16PlaneExecChainLink):
    """Handle Star plane selection (G17/G18/G19/G117/G118/G119) and PS0499 plane restrictions."""

    PLANE_BY_NUMBER: Dict[int, Tuple[str, str]] = {
        17: ("G17", PlaneMode.X_Y.value),
        18: ("G18", PlaneMode.X_Z.value),
        19: ("G19", PlaneMode.Y_Z.value),
        117: ("G117", PlaneMode.Y_X.value),
        118: ("G118", PlaneMode.Z_X.value),
        119: ("G119", PlaneMode.Z_Y.value),
    }
    REVERSED_PLANES: Set[str] = {
        PlaneMode.Y_X.value,
        PlaneMode.Z_X.value,
        PlaneMode.Z_Y.value,
    }
    FORBIDDEN_ON_REVERSED_PLANE: Set[str] = {
        "G31",
        "G70",
        "G71",
        "G72",
        "G73",
        "G74",
        "G75",
        "G76",
        "G80",
        "G83",
        "G84",
        "G85",
        "G87",
        "G89",
        "G90",
        "G94",
        "G107",
        "G112",
    }
    OUT_OF_PLANE_WORDS: Dict[str, Set[str]] = {
        PlaneMode.Y_X.value: {"Z", "W"},
        PlaneMode.Z_X.value: {"Y", "V"},
        PlaneMode.Z_Y.value: {"X", "U"},
    }

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        selected_codes: List[Tuple[str, str]] = []
        normalized_codes = self._normalized_g_codes(node)

        for g in node.g_code:
            if not isinstance(g, str):
                continue
            g_upper = g.strip().upper()
            if not g_upper.startswith("G"):
                continue
            try:
                num = float(g_upper[1:])
            except ValueError:
                continue
            if num.is_integer() and int(num) in self.PLANE_BY_NUMBER:
                spec = self.PLANE_BY_NUMBER[int(num)]
                if spec not in selected_codes:
                    selected_codes.append(spec)

        if len(selected_codes) > 1:
            raise_nc_error(
                ExceptionTyps.NCCodeErrors,
                120,
                message="Conflicting plane selection codes (G17/G18/G19/G117/G118/G119)",
                value=str(node.g_code),
                line=node.nc_code_line_nr or 0,
            )

        if selected_codes:
            plane_code, target_plane = selected_codes[0]
            if state.fanuc_state.coordinate_rotation:
                raise_nc_error(
                    ExceptionTyps.NCCodeErrors,
                    121,
                    message="Plane selection is not allowed during G68.1 mode",
                    value=str(node.g_code),
                    line=node.nc_code_line_nr or 0,
                )
            if self._is_compensation_active(node, state):
                self._ps0499(
                    node,
                    "Cancel tool nose radius compensation (G41/G42) by G40 before selecting a plane",
                    plane_code,
                )
            state.channel_state.plane = target_plane
            state.set_modal("g_group_16_plane_code", plane_code)

        active_plane = str(state.channel_state.plane or PlaneMode.X_Z.value)
        if "G112" in normalized_codes and str(state.channel_state.prev_plane or "") in self.REVERSED_PLANES:
            self._ps0499(
                node,
                f"G112 cannot be commanded on the reversed plane ({state.channel_state.prev_plane})",
                "G112",
            )
        if active_plane in self.REVERSED_PLANES:
            self._validate_reversed_plane_restrictions(node, state, active_plane, normalized_codes)

        if self.next_handler is not None:
            return self.next_handler.handle(node, state)
        return None, None

    @staticmethod
    def _normalized_g_codes(node: NCCommandNode) -> Set[str]:
        normalized: Set[str] = set()
        for raw in node.g_code:
            if not isinstance(raw, str):
                continue
            text = raw.strip().upper()
            if not text.startswith("G"):
                continue
            try:
                num = float(text[1:])
            except ValueError:
                normalized.add(text)
                continue
            if num.is_integer():
                normalized.add(f"G{int(num)}")
            else:
                normalized.add(f"G{num:g}")
        return normalized

    @staticmethod
    def _is_compensation_active(node: NCCommandNode, state: CNCState) -> bool:
        for raw in node.g_code:
            if str(raw).strip().upper() in {"G40", "G040"}:
                return False
        if state.get_modal("tool_nose_compensation") in {"G41", "G42"}:
            return True
        if (
            state.tool_compensation.radius_mode in {"LEFT", "RIGHT"}
            and state.tool_state.active_offset_number != 0
        ):
            return True
        return False

    def _validate_reversed_plane_restrictions(
        self,
        node: NCCommandNode,
        state: CNCState,
        active_plane: str,
        codes: Set[str],
    ) -> None:
        forbidden = sorted(codes.intersection(self.FORBIDDEN_ON_REVERSED_PLANE))
        if forbidden:
            self._ps0499(
                node,
                f"{forbidden[0]} cannot be commanded on the reversed plane ({active_plane})",
                forbidden[0],
            )

        if active_plane in {PlaneMode.Y_X.value, PlaneMode.Z_X.value}:
            if "G92" in codes or (
                state.get_modal("turning_cycle") == "G92"
                and bool({"X", "U", "Y", "V"}.intersection(node.command_parameter))
                and not codes.intersection({"G0", "G1", "G2", "G3"})
            ):
                self._ps0499(
                    node,
                    f"G92 threading cycle cannot be commanded on the {active_plane} plane",
                    "G92",
                )

        if (
            state.get_modal("drilling_cycle") or state.fanuc_state.turn_drilling_cycle
        ) and bool({"X", "U", "Y", "V", "Z", "W", "C", "H"}.intersection(node.command_parameter)):
            self._ps0499(
                node,
                f"Drilling canned cycle cannot execute on the reversed plane ({active_plane})",
                str(state.get_modal("drilling_cycle") or "G83"),
            )

        if (
            state.channel_state.polar_star_mode == "POLAR_COORDINATE_ON"
            and "G113" not in codes
        ):
            self._ps0499(
                node,
                f"Polar coordinate interpolation is not allowed on the reversed plane ({active_plane})",
                "G112",
            )

        if node.dddp_command:
            token = sorted(str(item).strip() for item in node.dddp_command)[0]
            self._ps0499(
                node,
                f"Chamfering, corner R, and direct drawing dimension programming are not allowed on {active_plane}",
                token,
            )

        words = {str(key).upper() for key in node.command_parameter}
        if self._is_circular_block(codes, state):
            out_of_plane = sorted(words.intersection(self.OUT_OF_PLANE_WORDS.get(active_plane, set())))
            if out_of_plane:
                self._ps0499(
                    node,
                    f"Helical interpolation is not allowed on the reversed plane ({active_plane})",
                    ",".join(out_of_plane),
                )
        elif self._is_linear_feed_block(codes, state):
            if "A" in words or "R" in words or "I" in words or "K" in words:
                offending = sorted(words.intersection({"A", "R", "I", "K"}))[0]
                self._ps0499(
                    node,
                    f"Chamfering, corner R, and direct drawing dimension programming are not allowed on {active_plane}",
                    offending,
                )

    @staticmethod
    def _is_circular_block(codes: Set[str], state: CNCState) -> bool:
        if codes.intersection({"G2", "G3"}):
            return True
        if codes.intersection({"G0", "G1"}):
            return False
        modal_group_1 = str(state.get_modal("G_GROUP_1") or "").strip().upper()
        return modal_group_1 in {"G2", "G02", "G3", "G03"}

    @staticmethod
    def _is_linear_feed_block(codes: Set[str], state: CNCState) -> bool:
        if "G1" in codes:
            return True
        if codes.intersection({"G0", "G2", "G3"}):
            return False
        modal_group_1 = str(state.get_modal("G_GROUP_1") or "").strip().upper()
        return modal_group_1 in {"G1", "G01"}

    @staticmethod
    def _ps0499(node: NCCommandNode, message: str, value: str) -> None:
        raise_nc_error(
            ExceptionTyps.NCCanalStarErrors,
            499,
            message=f"PS0499: {message}",
            value=value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["StarPlaneSelectionHandler"]
