"""FANUC planar coordinate-system rotation G68.1 and G69.1."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class FanucCoordinateRotationHandler(Handler):
    """Rotate programmed absolute coordinates in the selected plane."""

    REFERENCE_CODES = {"G27", "G28", "G29", "G30"}
    COORDINATE_CHANGE_CODES = {"G50", "G52", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}
    CANNED_CYCLE_CODES = {"G70", "G71", "G72", "G73", "G74", "G75", "G76", "G80", "G83", "G84", "G85", "G87", "G89", "G90", "G92", "G94"}

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        cancel_codes = {"G69.1"}
        if getattr(state.machine_config, "machine_type", "") == "TURN_MILL":
            cancel_codes.add("G69")

        if codes.intersection(cancel_codes):
            state.fanuc_state.coordinate_rotation = None
            state.fanuc_state.coordinate_rotation_logical_axes = None
            state.fanuc_state.coordinate_rotation_requires_absolute = None
            return super().handle(node, state)

        if "G68.1" in codes:
            self._activate(node, state)
            return super().handle(node, state)

        rotation = state.fanuc_state.coordinate_rotation
        if not isinstance(rotation, dict):
            return super().handle(node, state)
        if codes.intersection(self.REFERENCE_CODES | self.COORDINATE_CHANGE_CODES):
            self._error(node, 681, "Command is not allowed during G68.1 coordinate rotation", str(sorted(codes)))
        if codes.intersection(self.CANNED_CYCLE_CODES):
            self._error(node, 687, "Canned cycles are not allowed during G68.1 coordinate rotation", str(sorted(codes)))
        if not self._has_motion_words(node):
            return super().handle(node, state)
        if state.fanuc_state.coordinate_rotation_requires_absolute and {
            "U", "V", "W", "H"
        }.intersection(node.command_parameter):
            self._error(node, 682, "The first move after G68.1 must use absolute coordinates", "")

        logical_axes = dict(state.fanuc_state.coordinate_rotation_logical_axes or state.axes)
        logical_target = dict(logical_axes)
        self._apply_program_words(logical_target, node.command_parameter, state)
        transformed = self._rotate_target(logical_target, rotation)
        self._rewrite_plane_words(node, transformed, rotation, state)
        self._rotate_arc_offsets(node, rotation, state)

        result = super().handle(node, state)
        state.fanuc_state.coordinate_rotation_logical_axes = logical_target
        state.fanuc_state.coordinate_rotation_requires_absolute = False
        return result

    def _activate(self, node: NCCommandNode, state: CNCState) -> None:
        if state.get_modal("drilling_cycle") or state.get_modal("turning_cycle"):
            self._error(node, 683, "G68.1 cannot start during a canned cycle", "")
        plane, ordered_axes = self._plane(state)
        allowed = set(ordered_axes) | {"R"}
        invalid = {str(word).upper() for word in node.command_parameter} - allowed
        if invalid:
            self._error(node, 684, "G68.1 contains words outside the selected plane", ",".join(sorted(invalid)))

        logical_axes = dict(state.axes)
        center = {
            axis: state.normalize_axis_value(axis, float(node.command_parameter[axis]))
            if axis in node.command_parameter
            else logical_axes.get(axis, 0.0)
            for axis in ordered_axes
        }
        try:
            angle_text = str(node.command_parameter.get("R", 0.0)).strip()
            angle = float(angle_text)
            if abs(angle) > 360.0:
                angle *= 0.001
        except (TypeError, ValueError):
            self._error(node, 685, "G68.1 R must be numeric", str(node.command_parameter.get("R")))
        if angle < -360000.0 or angle > 360000.0:
            self._error(node, 686, "G68.1 angle is outside the supported range", str(angle))

        state.fanuc_state.coordinate_rotation = {
            "active": True,
            "plane": plane,
            "ordered_axes": ordered_axes,
            "center": center,
            "angle": angle,
        }
        state.fanuc_state.coordinate_rotation_logical_axes = logical_axes
        state.fanuc_state.coordinate_rotation_requires_absolute = True
        for word in list(node.command_parameter):
            node.command_parameter.pop(word, None)

    def _apply_program_words(
        self, target: Dict[str, float], words: Dict[str, str], state: CNCState
    ) -> None:
        for axis in ("X", "Y", "Z"):
            if axis in words:
                target[axis] = state.normalize_axis_value(axis, float(words[axis]))
        for word, axis in {"U": "X", "V": "Y", "W": "Z"}.items():
            if word in words:
                target[axis] = target.get(axis, 0.0) + state.normalize_axis_value(axis, float(words[word]))

    def _rotate_target(self, target: Dict[str, float], rotation: Dict[str, object]) -> Dict[str, float]:
        first, second = tuple(rotation["ordered_axes"])
        center = dict(rotation["center"])
        angle = math.radians(float(rotation["angle"]))
        first_delta = target.get(first, 0.0) - float(center[first])
        second_delta = target.get(second, 0.0) - float(center[second])
        transformed = dict(target)
        transformed[first] = float(center[first]) + first_delta * math.cos(angle) - second_delta * math.sin(angle)
        transformed[second] = float(center[second]) + first_delta * math.sin(angle) + second_delta * math.cos(angle)
        return transformed

    def _rewrite_plane_words(
        self,
        node: NCCommandNode,
        transformed: Dict[str, float],
        rotation: Dict[str, object],
        state: CNCState,
    ) -> None:
        for word in ("X", "Y", "Z", "U", "V", "W"):
            node.command_parameter.pop(word, None)
        for axis in tuple(rotation["ordered_axes"]):
            value = transformed[axis] * 2.0 if state.is_axis_diameter(axis) else transformed[axis]
            node.command_parameter[axis] = str(value)

    def _rotate_arc_offsets(
        self, node: NCCommandNode, rotation: Dict[str, object], state: CNCState
    ) -> None:
        first, second = tuple(rotation["ordered_axes"])
        letters = {"X": "I", "Y": "J", "Z": "K"}
        first_letter = letters[first]
        second_letter = letters[second]
        if first_letter not in node.command_parameter and second_letter not in node.command_parameter:
            return
        first_value = float(node.command_parameter.get(first_letter, 0.0))
        second_value = float(node.command_parameter.get(second_letter, 0.0))
        angle = math.radians(float(rotation["angle"]))
        rotated_first = first_value * math.cos(angle) - second_value * math.sin(angle)
        rotated_second = first_value * math.sin(angle) + second_value * math.cos(angle)
        node.command_parameter[first_letter] = str(rotated_first)
        node.command_parameter[second_letter] = str(rotated_second)

    @staticmethod
    def _plane(state: CNCState) -> Tuple[str, Tuple[str, str]]:
        raw_plane = state.channel_state.plane or "X_Z"
        value = str(getattr(raw_plane, "value", raw_plane))
        if value.endswith("X_Y"):
            return "G17", ("X", "Y")
        if value.endswith("Y_Z"):
            return "G19", ("Y", "Z")
        return "G18", ("Z", "X")

    @staticmethod
    def _has_motion_words(node: NCCommandNode) -> bool:
        return bool({"X", "Y", "Z", "U", "V", "W"}.intersection(node.command_parameter))

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(ExceptionTyps.NCCodeErrors, code, message=message, value=value, line=node.nc_code_line_nr or 0)


__all__ = ["FanucCoordinateRotationHandler"]