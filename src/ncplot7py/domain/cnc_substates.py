"""Typed sub-state dataclasses for CNCState and synchronized legacy mapping view."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ChannelRuntimeState:
    """Channel-level runtime and kinematic configuration state."""

    path_number: Optional[int] = None
    axis_map: Dict[str, str] = field(default_factory=dict)
    target_carriers: Dict[str, str] = field(default_factory=dict)
    plane: Optional[str] = None
    prev_plane: Optional[str] = None
    polar_star_mode: Optional[str] = None
    polar_interpolate_axis: Optional[str] = None
    polar_mode: Optional[bool] = None
    x_axis_multiplication: Optional[float] = None
    y_axis_multiplication: Optional[float] = None
    feed_mode: Optional[Any] = None
    units: Optional[str] = None
    control_mode: Optional[str] = None
    work_offset: Optional[str] = None
    work_offset_index: Optional[int] = None
    active_work_offset_index: Optional[int] = None
    local_offsets: Dict[str, float] = field(default_factory=dict)
    rotation: Optional[Dict[str, float]] = None
    rotation_origin: Optional[Dict[str, float]] = None
    cycle_start_count: Optional[int] = None
    last_wait_code: Optional[Dict[str, Any]] = None
    wait_code: Optional[Dict[str, Any]] = None
    program_returned: Optional[bool] = None
    alarms: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    max_segment: Optional[float] = None
    angle_per_segment_deg: Optional[float] = None
    c_axis_center: Optional[Tuple[float, float]] = None
    rotary_center: Optional[Tuple[float, ...]] = None
    seventh_axis_name: Optional[str] = None
    seventh_axis_maps_to: Optional[str] = None
    pose_tools: Dict[Any, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ToolSelectionState:
    """Active tool selection, offset registers, and compensation tables."""

    active_tool_number: Optional[int] = None
    active_tool_name: Optional[str] = None
    active_tool_code: Optional[int] = None
    current_tool_number: Optional[int] = None
    current_tool_name: Optional[str] = None
    current_tool_code: Optional[int] = None
    active_offset_number: Optional[int] = None
    pending_tool_radius: Optional[float] = None
    pending_tool_quadrant: Optional[int] = None
    wear_offset_active: Optional[bool] = None
    tool_compensation_data: Dict[Any, Dict[str, Any]] = field(default_factory=dict)
    tool_offset_data: Dict[Any, Dict[str, Any]] = field(default_factory=dict)
    tools: Dict[Any, Any] = field(default_factory=dict)


@dataclass
class SpindleSpeedState:
    """Spindle speed mode, G96 reference axis, and RPM limits."""

    surface_speed_mode: Optional[Any] = None
    g96_reference_axis: Optional[str] = None
    spindle_speed_limit: Optional[float] = None
    spindle_speed_limit_active: Optional[bool] = None
    spindle_speed_limits: Dict[Any, float] = field(default_factory=dict)
    spindle_speed_maximum: Optional[float] = None
    spindle_speed_minimum: Optional[float] = None


@dataclass
class FanucChannelState:
    """Fanuc turning/milling cycle and coordinate rotation state."""

    coordinate_rotation: Optional[Dict[str, Any]] = None
    coordinate_rotation_logical_axes: Optional[Dict[str, float]] = None
    coordinate_rotation_requires_absolute: Optional[bool] = None
    g76_setup: Optional[Dict[str, Any]] = None
    g76_pass_depths: Optional[List[float]] = None
    g92_words: Optional[Dict[str, Any]] = None
    threading_active: Optional[str] = None
    threading_start_angle: Optional[float] = None
    last_tapping_reversal: Optional[bool] = None
    turn_drilling_cycle: Optional[Dict[str, Any]] = None
    turn_spindle_stopped: Optional[bool] = None


@dataclass
class SiemensChannelState:
    """Siemens 840D / ISO dialect runtime state."""

    scope: Dict[str, Any] = field(default_factory=dict)
    siemens_mode: Optional[bool] = None
    c_axis_mode: Optional[str] = None
    c_axis_position: Optional[float] = None
    c_axis_command: Optional[str] = None
    active_cycle: Optional[int] = None
    active_named_cycle: Optional[Dict[str, Any]] = None
    cycle_initial_z: Optional[float] = None
    cycle_r: Optional[float] = None
    cycle_z: Optional[float] = None
    cycle_return_mode: Optional[int] = None


@dataclass
class StarChannelState:
    """Star Swiss-type lathe channel state."""

    target_carrier_id: Optional[str] = None
    target_axis: Optional[str] = None
    c_axis_mode: Optional[str] = None
    path_mode: Optional[str] = None
    machining_mode: Optional[str] = None
    b1_tilting: Optional[Dict[str, Any]] = None
    g161: Optional[Dict[str, Any]] = None
    g266_parameters: Optional[Dict[str, Any]] = None
    spindle_fluctuation_monitoring: Optional[bool] = None
    axis_z1_moving: Optional[bool] = None
    coordinate_path2_machining: Optional[bool] = None
    coordinate_pickup_b: Optional[float] = None
    coordinate_pickup_set: Optional[bool] = None
    coordinate_projection_stored: Optional[bool] = None
    coordinate_z1_command: Optional[Dict[str, Any]] = None
    coordinate_z1_set: Optional[bool] = None
    coordinate_z2_set: Optional[bool] = None


_KEY_ROUTES: Dict[str, Tuple[str, str, bool]] = {
    # ChannelRuntimeState
    "path_number": ("channel_state", "path_number", False),
    "axis_map": ("channel_state", "axis_map", True),
    "target_carriers": ("channel_state", "target_carriers", True),
    "g_group_16_plane": ("channel_state", "plane", False),
    "g_group_21_prev_plane": ("channel_state", "prev_plane", False),
    "g_group_21_star": ("channel_state", "polar_star_mode", False),
    "polar_interpolate_axis": ("channel_state", "polar_interpolate_axis", False),
    "polar_mode": ("channel_state", "polar_mode", False),
    "x_axis_multiplication": ("channel_state", "x_axis_multiplication", False),
    "y_axis_multiplication": ("channel_state", "y_axis_multiplication", False),
    "feed_mode": ("channel_state", "feed_mode", False),
    "units": ("channel_state", "units", False),
    "control_mode": ("channel_state", "control_mode", False),
    "work_offset": ("channel_state", "work_offset", False),
    "work_offset_index": ("channel_state", "work_offset_index", False),
    "active_work_offset_index": ("channel_state", "active_work_offset_index", False),
    "local_offsets": ("channel_state", "local_offsets", True),
    "rotation": ("channel_state", "rotation", False),
    "rotation_origin": ("channel_state", "rotation_origin", False),
    "cycle_start_count": ("channel_state", "cycle_start_count", False),
    "last_wait_code": ("channel_state", "last_wait_code", False),
    "wait_code": ("channel_state", "wait_code", False),
    "program_returned": ("channel_state", "program_returned", False),
    "alarms": ("channel_state", "alarms", True),
    "messages": ("channel_state", "messages", True),
    "max_segment": ("channel_state", "max_segment", False),
    "angle_per_segment_deg": ("channel_state", "angle_per_segment_deg", False),
    "c_axis_center": ("channel_state", "c_axis_center", False),
    "rotary_center": ("channel_state", "rotary_center", False),
    "seventh_axis_name": ("channel_state", "seventh_axis_name", False),
    "seventh_axis_maps_to": ("channel_state", "seventh_axis_maps_to", False),
    "pose_tools": ("channel_state", "pose_tools", True),
    # ToolSelectionState
    "active_tool_number": ("tool_state", "active_tool_number", False),
    "active_tool_name": ("tool_state", "active_tool_name", False),
    "active_tool_code": ("tool_state", "active_tool_code", False),
    "current_tool_number": ("tool_state", "current_tool_number", False),
    "current_tool_name": ("tool_state", "current_tool_name", False),
    "current_tool_code": ("tool_state", "current_tool_code", False),
    "active_offset_number": ("tool_state", "active_offset_number", False),
    "pending_tool_radius": ("tool_state", "pending_tool_radius", False),
    "pending_tool_quadrant": ("tool_state", "pending_tool_quadrant", False),
    "wear_offset_active": ("tool_state", "wear_offset_active", False),
    "tool_compensation_data": ("tool_state", "tool_compensation_data", True),
    "tool_offset_data": ("tool_state", "tool_offset_data", True),
    "tools": ("tool_state", "tools", True),
    # SpindleSpeedState
    "surface_speed_mode": ("spindle_limits", "surface_speed_mode", False),
    "g96_reference_axis": ("spindle_limits", "g96_reference_axis", False),
    "spindle_speed_limit": ("spindle_limits", "spindle_speed_limit", False),
    "spindle_speed_limit_active": ("spindle_limits", "spindle_speed_limit_active", False),
    "spindle_speed_limits": ("spindle_limits", "spindle_speed_limits", True),
    "spindle_speed_maximum": ("spindle_limits", "spindle_speed_maximum", False),
    "spindle_speed_minimum": ("spindle_limits", "spindle_speed_minimum", False),
    # FanucChannelState
    "fanuc.coordinate_rotation": ("fanuc_state", "coordinate_rotation", False),
    "fanuc.coordinate_rotation.logical_axes": ("fanuc_state", "coordinate_rotation_logical_axes", False),
    "fanuc.coordinate_rotation.requires_absolute": ("fanuc_state", "coordinate_rotation_requires_absolute", False),
    "fanuc.g76.setup": ("fanuc_state", "g76_setup", False),
    "fanuc.g76.pass_depths": ("fanuc_state", "g76_pass_depths", False),
    "fanuc.g92.words": ("fanuc_state", "g92_words", False),
    "fanuc.threading.active": ("fanuc_state", "threading_active", False),
    "fanuc.threading.start_angle": ("fanuc_state", "threading_start_angle", False),
    "fanuc_turn.last_tapping_reversal": ("fanuc_state", "last_tapping_reversal", False),
    "fanuc_turn_drilling_cycle": ("fanuc_state", "turn_drilling_cycle", False),
    "fanuc_turn_spindle_stopped": ("fanuc_state", "turn_spindle_stopped", False),
    # SiemensChannelState
    "siemens": ("siemens_state", "scope", True),
    "siemens_mode": ("siemens_state", "siemens_mode", False),
    "siemens.c_axis_mode": ("siemens_state", "c_axis_mode", False),
    "siemens.c_axis_position": ("siemens_state", "c_axis_position", False),
    "siemens.c_axis_command": ("siemens_state", "c_axis_command", False),
    "active_cycle": ("siemens_state", "active_cycle", False),
    "active_named_cycle": ("siemens_state", "active_named_cycle", False),
    "cycle_initial_z": ("siemens_state", "cycle_initial_z", False),
    "cycle_r": ("siemens_state", "cycle_r", False),
    "cycle_z": ("siemens_state", "cycle_z", False),
    "cycle_return_mode": ("siemens_state", "cycle_return_mode", False),
    # StarChannelState
    "star.targetCarrierId": ("star_state", "target_carrier_id", False),
    "star.targetAxis": ("star_state", "target_axis", False),
    "star.c_axis_mode": ("star_state", "c_axis_mode", False),
    "star.path_mode": ("star_state", "path_mode", False),
    "star.machining_mode": ("star_state", "machining_mode", False),
    "star.b1_tilting": ("star_state", "b1_tilting", False),
    "star.g161": ("star_state", "g161", False),
    "star.g266.parameters": ("star_state", "g266_parameters", False),
    "star.spindle.fluctuation_monitoring": ("star_state", "spindle_fluctuation_monitoring", False),
    "star.axis.z1_moving": ("star_state", "axis_z1_moving", False),
    "star.coordinate.path2_machining": ("star_state", "coordinate_path2_machining", False),
    "star.coordinate.pickup_b": ("star_state", "coordinate_pickup_b", False),
    "star.coordinate.pickup_set": ("star_state", "coordinate_pickup_set", False),
    "star.coordinate.projection_stored": ("star_state", "coordinate_projection_stored", False),
    "star.coordinate.z1_command": ("star_state", "coordinate_z1_command", False),
    "star.coordinate.z1_set": ("star_state", "coordinate_z1_set", False),
    "star.coordinate.z2_set": ("star_state", "coordinate_z2_set", False),
}


class ExtraStateMapping(dict):
    """Dictionary view synchronized with typed sub-dataclasses on CNCState."""

    def __init__(self, owner: Any = None, initial: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self._owner = owner
        if initial:
            self.update(initial)

    def bind(self, owner: Any) -> None:
        object.__setattr__(self, "_owner", owner)
        self.sync_from_substates()

    def sync_from_substates(self) -> None:
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        for key, (sub_name, attr_name, is_container) in _KEY_ROUTES.items():
            sub = getattr(owner, sub_name, None)
            if sub is None:
                continue
            val = getattr(sub, attr_name, None)
            if is_container:
                if val:
                    dict.__setitem__(self, key, val)
                elif dict.__contains__(self, key) and not dict.__getitem__(self, key):
                    dict.pop(self, key, None)
            else:
                if val is not None:
                    dict.__setitem__(self, key, val)

    def _sync_key_from_substate(self, key: str) -> None:
        owner = getattr(self, "_owner", None)
        if owner is None or key not in _KEY_ROUTES:
            return
        sub_name, attr_name, is_container = _KEY_ROUTES[key]
        sub = getattr(owner, sub_name, None)
        if sub is None:
            return
        val = getattr(sub, attr_name, None)
        if is_container:
            if val:
                dict.__setitem__(self, key, val)
            elif dict.__contains__(self, key) and not dict.__getitem__(self, key):
                dict.pop(self, key, None)
        else:
            if val is not None:
                dict.__setitem__(self, key, val)
            else:
                dict.pop(self, key, None)

    def _write_to_substate(self, key: str, value: Any) -> None:
        owner = getattr(self, "_owner", None)
        if owner is None or key not in _KEY_ROUTES:
            return
        sub_name, attr_name, _ = _KEY_ROUTES[key]
        sub = getattr(owner, sub_name, None)
        if sub is not None:
            setattr(sub, attr_name, value)

    def _clear_in_substate(self, key: str) -> None:
        owner = getattr(self, "_owner", None)
        if owner is None or key not in _KEY_ROUTES:
            return
        sub_name, attr_name, is_container = _KEY_ROUTES[key]
        sub = getattr(owner, sub_name, None)
        if sub is None:
            return
        if is_container:
            current = getattr(sub, attr_name, None)
            if isinstance(current, list):
                setattr(sub, attr_name, [])
            elif isinstance(current, dict):
                setattr(sub, attr_name, {})
            else:
                setattr(sub, attr_name, None)
        else:
            setattr(sub, attr_name, None)

    def __getitem__(self, key: str) -> Any:
        self._sync_key_from_substate(key)
        return dict.__getitem__(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        self._write_to_substate(key, value)
        dict.__setitem__(self, key, value)

    def __delitem__(self, key: str) -> None:
        self._clear_in_substate(key)
        dict.__delitem__(self, key)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            self._sync_key_from_substate(key)
        return dict.__contains__(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        self._sync_key_from_substate(key)
        return dict.get(self, key, default)

    def pop(self, key: str, *args: Any) -> Any:
        self._sync_key_from_substate(key)
        self._clear_in_substate(key)
        return dict.pop(self, key, *args)

    def setdefault(self, key: str, default: Any = None) -> Any:
        self._sync_key_from_substate(key)
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        self[key] = default
        return default

    def update(self, *args: Any, **kwargs: Any) -> None:
        for k, v in dict(*args, **kwargs).items():
            self[k] = v

    def clear(self) -> None:
        for key in list(dict.keys(self)):
            self._clear_in_substate(key)
        dict.clear(self)


__all__ = [
    "ChannelRuntimeState",
    "ToolSelectionState",
    "SpindleSpeedState",
    "FanucChannelState",
    "SiemensChannelState",
    "StarChannelState",
    "ExtraStateMapping",
]
