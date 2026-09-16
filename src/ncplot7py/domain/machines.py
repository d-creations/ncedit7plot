from typing import Dict, Any, List, Tuple, Optional
from dataclasses import asdict, dataclass, field
from copy import deepcopy
import json
import os
import hashlib
import math
from importlib.resources import files

POSE_CONTRACT = "workpiece-tool-reference-v1"


def _simulation_object(value: Any, required: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"Expected exactly these fields: {sorted(required)}")
    return value


def _simulation_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Expected a nonempty identifier of at most 256 characters")
    return value


def _simulation_integer(value: Any, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 9007199254740991:
        raise ValueError("Expected a safe integer in the supported range")
    return value


def _simulation_vector(value: Any) -> list:
    if not isinstance(value, list) or len(value) != 3 or any(
        type(component) not in (int, float) or not math.isfinite(component)
        for component in value
    ):
        raise ValueError("Expected three finite numbers")
    return value


def _simulation_identifier(value: Any) -> tuple[type, Any]:
    if type(value) is int:
        _simulation_integer(value)
    else:
        _simulation_text(value)
        if value == "unknown":
            raise ValueError("unknown is reserved for unavailable tools")
    return type(value), value


def validate_simulation_config(value: Any, channels: int, axes: tuple[str, ...]) -> dict:
    """Validate simulation settings that belong to a static machine profile."""
    required = {
        "schemaVersion", "revision", "modelId", "displayName", "fidelity",
        "poseContract", "carriers", "toolMounts",
    }
    if not isinstance(value, dict) or set(value) not in (required, required | {"initialAxes"}):
        raise ValueError(f"Expected these fields: {sorted(required)} with optional initialAxes")
    config = value
    if type(config["schemaVersion"]) is not int or config["schemaVersion"] != 1:
        raise ValueError("Unsupported simulation schemaVersion")
    _simulation_integer(config["revision"], 1)
    _simulation_text(config["modelId"])
    _simulation_text(config["displayName"])
    if config["fidelity"] not in ("demo", "configured"):
        raise ValueError("fidelity must be demo or configured")
    if config["poseContract"] != POSE_CONTRACT:
        raise ValueError("Unsupported simulation poseContract")
    initial_axes = config.get("initialAxes", {})
    if not isinstance(initial_axes, dict) or any(
        axis not in axes or type(position) not in (int, float) or not math.isfinite(position)
        for axis, position in initial_axes.items()
    ):
        raise ValueError("Invalid initialAxes")
    if not isinstance(config["carriers"], list) or not 1 <= len(config["carriers"]) <= 64:
        raise ValueError("Expected 1..64 carriers")
    roles = {}
    for carrier in config["carriers"]:
        _simulation_object(carrier, {"id", "role", "referenceOrientationDegrees", "rotationChain"})
        identity = _simulation_text(carrier["id"])
        if identity in roles or carrier["role"] not in ("tool", "workpiece"):
            raise ValueError("Duplicate carrier or invalid role")
        roles[identity] = carrier["role"]
        _simulation_vector(carrier["referenceOrientationDegrees"])
        chain = carrier["rotationChain"]
        if not isinstance(chain, list) or len(chain) > 16:
            raise ValueError("Invalid rotation chain")
        seen_axes = set()
        for joint in chain:
            _simulation_object(joint, {"axisId", "axis", "sign", "zeroDegrees"})
            axis = _simulation_text(joint["axisId"])
            if axis not in axes or axis in seen_axes:
                raise ValueError("Unknown or repeated chain axis")
            seen_axes.add(axis)
            vector = _simulation_vector(joint["axis"])
            if abs(math.hypot(*vector) - 1) > 1e-6:
                raise ValueError("Rotation axis must be a unit vector")
            if type(joint["sign"]) is not int or joint["sign"] not in (-1, 1):
                raise ValueError("Rotation sign must be -1 or 1")
            _simulation_vector([joint["zeroDegrees"], 0, 0])
    mounts = config["toolMounts"]
    if not isinstance(mounts, list) or len(mounts) > 4096:
        raise ValueError("Invalid toolMounts list")
    selections: dict[str, list[tuple[int, int]]] = {}
    names: dict[str, set[str]] = {}
    for mount in mounts:
        _simulation_object(mount, {"channelId", "tools", "carrierId", "target"})
        channel = _simulation_text(mount["channelId"])
        if channel not in {str(number) for number in range(1, channels + 1)}:
            raise ValueError("Unknown mount channel")
        if roles.get(_simulation_text(mount["carrierId"])) != "tool":
            raise ValueError("Mount requires a tool carrier")
        target = mount["target"]
        if isinstance(target, dict) and target.get("mode") == "fixed":
            _simulation_object(target, {"mode", "workpieceCarrierId"})
            targets = [target["workpieceCarrierId"]]
        else:
            if not isinstance(target, dict) or set(target) != {"mode", "allowedWorkpieceCarrierIds", "defaultWorkpieceCarrierId"}:
                raise ValueError("Invalid execution target")
            targets = target["allowedWorkpieceCarrierIds"]
            if target["mode"] != "execution" or not isinstance(targets, list) or not targets:
                raise ValueError("Invalid execution target")
            if target["defaultWorkpieceCarrierId"] not in targets:
                raise ValueError("Default target must be allowed")
        if any(roles.get(_simulation_text(identity)) != "workpiece" for identity in targets):
            raise ValueError("Target requires a workpiece carrier")
        if len(set(targets)) != len(targets):
            raise ValueError("Duplicate execution target")
        selector = mount["tools"]
        intervals = selections.setdefault(channel, [])
        selected_names = names.setdefault(channel, set())
        if isinstance(selector, dict) and selector.get("kind") == "numericRange":
            _simulation_object(selector, {"kind", "from", "to"})
            lower = _simulation_integer(selector["from"])
            upper = _simulation_integer(selector["to"])
            if lower > upper:
                raise ValueError("Reversed tool range")
            additions = [(lower, upper)]
        else:
            _simulation_object(selector, {"kind", "values"})
            values = selector["values"]
            if selector["kind"] != "identifiers" or not isinstance(values, list) or not 1 <= len(values) <= 4096:
                raise ValueError("Invalid exact tool selector")
            additions = []
            for item in values:
                kind, identity = _simulation_identifier(item)
                if kind is int:
                    additions.append((identity, identity))
                elif identity in selected_names:
                    raise ValueError("Overlapping tool assignments")
                else:
                    selected_names.add(identity)
        for lower, upper in additions:
            if any(lower <= end and start <= upper for start, end in intervals):
                raise ValueError("Overlapping tool assignments")
            intervals.append((lower, upper))
    return deepcopy(config)

@dataclass
class MachineConfig:
    """Configuration for a specific machine/control type."""
    name: str
    control_type: str  # "FANUC", "SIEMENS"
    variable_pattern: str  # Regex for variables, e.g. r"#(\d+)" or r"R(\d+)"
    variable_prefix: str   # Prefix for variables, e.g. "#" or "R"
    tool_range: Tuple[int, int]
    parser_name: str = "fanuc"
    lexer_name: str = "fanuc"
    machine_type: str = "MILL"
    channels: int = 1
    synchronization_strategy: str = "NONE"
    supported_gcode_groups: Tuple[str, ...] = field(default_factory=tuple)
    cycle_start_code: str = ""
    default_plane: str = "G17"
    default_feed_mode: str = "FEED_PER_MIN"
    rapid_feed_rate: Optional[float] = None
    a_axis_rollover: bool = False
    b_axis_rollover: bool = False
    c_axis_rollover: bool = False
    a_axis_shortest_path: bool = False
    b_axis_shortest_path: bool = False
    c_axis_shortest_path: bool = False
    polar_interpolate_axis: str = "Y"
    diameter_axes: Tuple[str, ...] = ()
    g96_reference_axis: Optional[str] = None
    circular_threading_enabled: bool = False
    step_cycle_pro_enabled: bool = False
    rotary_axis_planes: Dict[str, str] = field(default_factory=lambda: {"A": "YZ", "B": "XZ", "C": "XY"})
    seventh_axis_name: Optional[str] = None
    seventh_axis_maps_to: Optional[str] = None
    max_execution_nodes: int = 100000
    file_extensions: Dict[str, Any] = field(default_factory=dict)
    regex_patterns: Dict[str, Any] = field(default_factory=dict)
    tool_selection: Dict[str, Any] = field(default_factory=dict)
    axis_bindings: Dict[str, Any] = field(default_factory=dict)
    axes: Tuple[str, ...] = ()
    simulation: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if type(self.channels) is not int or not 1 <= self.channels <= 3:
            raise ValueError("channels must be between 1 and 3")
        if not isinstance(self.axes, (list, tuple)) or any(not isinstance(axis, str) or not axis.strip() for axis in self.axes) or len(set(self.axes)) != len(self.axes):
            raise ValueError("axes must contain unique nonempty IDs")
        self.axes = tuple(self.axes)
        if self.simulation is not None:
            self.simulation = validate_simulation_config(self.simulation, self.channels, self.axes)
        if not isinstance(self.axis_bindings, dict):
            raise ValueError("axis_bindings must be an object")
        for logical_axis, binding in self.axis_bindings.items():
            if not isinstance(logical_axis, str) or not logical_axis.isalpha() or not isinstance(binding, dict):
                raise ValueError("Invalid axis binding")
            defaults = binding.get("defaultByChannel", {})
            overrides = binding.get("mcodeOverrides", {})
            if set(binding) != {"defaultByChannel", "mcodeOverrides"} or not isinstance(defaults, dict) or not isinstance(overrides, dict):
                raise ValueError("Invalid axis binding definition")
            for channel, target in defaults.items():
                if str(channel) not in {str(number) for number in range(1, self.channels + 1)}:
                    raise ValueError("Axis binding references an unknown channel")
                self._validate_axis_binding_target(target)
            for code, target in overrides.items():
                if not isinstance(code, str) or not code.upper().startswith("M"):
                    raise ValueError("Axis binding override must be an M-code")
                self._validate_axis_binding_target(target)
        policy = self.tool_selection
        if not isinstance(policy, dict):
            raise ValueError("tool_selection must be an object")
        if not policy:
            return
        if policy.get("mode") not in {"direct", "packed", "station", "star"}:
            raise ValueError("Unsupported tool_selection mode")
        if policy.get("offset_scope") not in {"global", "tool"}:
            raise ValueError("Unsupported offset_scope")
        if type(policy.get("named_tools")) is not bool:
            raise ValueError("named_tools must be boolean")
        if policy["mode"] == "star":
            tool_digits = policy.get("tool_digits")
            if tool_digits != [3, 4]:
                raise ValueError("STAR tool_digits must be [3, 4]")
            offset_digits = policy.get("offset_digits")
            if offset_digits != [1, 2]:
                raise ValueError("STAR offset_digits must be [1, 2]")
        elif policy["mode"] not in {"direct", "star"}:
            digits = policy.get("offset_digits")
            if type(digits) is not int or not 1 <= digits <= 4:
                raise ValueError("offset_digits must be between 1 and 4")
        address = policy.get("offset_address")
        if address is not None and (not isinstance(address, str) or len(address) != 1 or not address.isalpha()):
            raise ValueError("offset_address must be a single letter")
        codes = policy.get("subtool_codes", [])
        if not isinstance(codes, list) or any(type(code) is not int or code < 100 for code in codes):
            raise ValueError("subtool_codes must contain full positive tool codes")

    def _validate_axis_binding_target(self, target: Any) -> None:
        if not isinstance(target, dict) or set(target) != {"targetCarrierId", "axisId"}:
            raise ValueError("Invalid axis binding target")
        if target["axisId"] not in self.axes or not isinstance(target["targetCarrierId"], str):
            raise ValueError("Axis binding references an unknown axis or carrier")

    def simulation_metadata(self) -> Dict[str, Any]:
        """Return immutable machine capabilities exposed through discovery."""
        canonical = json.dumps(
            asdict(self),
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        metadata = {
            "axes": list(self.axes),
            "availableChannels": self.channels,
            "profileRevision": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "supportedPoseContracts": [POSE_CONTRACT] if self.simulation and self.simulation["modelId"] in {"MILL_DEMO", "STAR_SR20R_IV_B", "STAR_SV20R", "STAR_SG42"} else [],
        }
        if self.simulation is not None:
            metadata["simulation"] = deepcopy(self.simulation)
        return metadata


# --- Machine Definitions ---

# Registry of configs
MACHINE_CONFIGS: Dict[str, MachineConfig] = {}

def load_machine_configs():
    global MACHINE_CONFIGS
    loaded_configs: Dict[str, MachineConfig] = {}
    try:
        try:
            config_text = files('ncplot7py').joinpath('config', 'machines.json').read_text(encoding='utf-8')
            data = json.loads(config_text)
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            package_config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'machines.json')
            legacy_config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'machines.json')
            config_path = package_config_path if os.path.exists(package_config_path) else legacy_config_path
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

        # First pass: load base configs
        for key, val in data.items():
            if isinstance(val, dict):
                loaded_configs[key] = MachineConfig(
                    name=val['name'],
                    control_type=val['control_type'],
                    variable_pattern=val['variable_pattern'],
                    variable_prefix=val['variable_prefix'],
                    parser_name=val.get('parser_name', 'siemens' if val.get('control_type') == 'SIEMENS' else 'fanuc'),
                    lexer_name=val.get('lexer_name', val.get('parser_name', 'siemens' if val.get('control_type') == 'SIEMENS' else 'fanuc')),
                    tool_range=tuple(val['tool_range']),
                    machine_type=val.get('machine_type', 'MILL'),
                    channels=val.get('channels', 1),
                    synchronization_strategy=val.get('synchronization_strategy', 'NONE'),
                    supported_gcode_groups=tuple(val.get('supported_gcode_groups', [])),
                    cycle_start_code=val.get('cycle_start_code', ''),
                    default_plane=val.get('default_plane', 'G17'),
                    default_feed_mode=val.get('default_feed_mode', 'FEED_PER_MIN'),
                    rapid_feed_rate=val.get('rapid_feed_rate'),
                    a_axis_rollover=val.get('a_axis_rollover', False),
                    b_axis_rollover=val.get('b_axis_rollover', False),
                    c_axis_rollover=val.get('c_axis_rollover', False),
                    a_axis_shortest_path=val.get('a_axis_shortest_path', False),
                    b_axis_shortest_path=val.get('b_axis_shortest_path', False),
                    c_axis_shortest_path=val.get('c_axis_shortest_path', False),
                    polar_interpolate_axis=val.get('polar_interpolate_axis', 'Y'),
                    diameter_axes=tuple(val.get('diameter_axes', [])),
                    g96_reference_axis=val.get('g96_reference_axis'),
                    circular_threading_enabled=val.get('circular_threading_enabled', False),
                    step_cycle_pro_enabled=val.get('step_cycle_pro_enabled', False),
                    rotary_axis_planes=dict(val.get('rotary_axis_planes', {"A": "YZ", "B": "XZ", "C": "XY"})),
                    seventh_axis_name=val.get('seventh_axis_name'),
                    seventh_axis_maps_to=val.get('seventh_axis_maps_to'),
                    max_execution_nodes=val.get('max_execution_nodes', 100000),
                    file_extensions=val.get('file_extensions', {}),
                    regex_patterns=val.get('regex_patterns', {}),
                    tool_selection=deepcopy(val.get('tool_selection', {})),
                    axis_bindings=deepcopy(val.get('axis_bindings', {})),
                    axes=val.get('axes', []),
                    simulation=val.get('simulation'),
                )
                
        # Second pass: resolve aliases
        for key, val in data.items():
            if isinstance(val, str) and val in loaded_configs:
                loaded_configs[key] = loaded_configs[val]
                
    except Exception as e:
        raise ValueError(f"Failed to load machines.json: {e}") from e
    MACHINE_CONFIGS = loaded_configs

load_machine_configs()

def get_machine_config(machine_name: str) -> MachineConfig:
    """Retrieve configuration for a given machine name."""
    return MACHINE_CONFIGS.get(machine_name) or MACHINE_CONFIGS.get('FANUC_MILL')

def get_machine_regex_patterns(control_type: str) -> Dict[str, Any]:
    """Return frontend regex metadata configured for a machine."""
    config = MACHINE_CONFIGS.get(control_type) or MACHINE_CONFIGS.get('FANUC_MILL')

    if config is None:
        return {}

    if config.name == 'FANUC_MILL' and control_type != 'FANUC_MILL':
        for key, c in MACHINE_CONFIGS.items():
            if c.control_type == control_type:
                config = c
                break

    patterns = deepcopy(config.regex_patterns)
    policy = config.tool_selection
    if policy:
        digits = len(str(config.tool_range[1]))
        number = rf"[1-9][0-9]{{0,{digits - 1}}}"
        mode = policy.get("mode", "direct")
        if mode == "star":
            tool_min, tool_max = policy.get("tool_digits", [3, 4])
            pattern = rf"T\s*(?=0*[0-9]{{{tool_min},{tool_max}}}(?![\d.]))0*([1-9][0-9]{{0,{tool_max - 1}}})(?![\d.])"
        elif mode == "direct":
            pattern = rf"T\s*0*([0-9]{{1,{digits}}})(?![\d.])"
            if policy.get("named_tools"):
                pattern = rf'(?:{pattern}|T\s*=\s*"[^"]+")'
        else:
            offset_digits = int(policy["offset_digits"])
            if mode == "packed":
                pattern = rf"T\s*0*({number})[0-9]{{{offset_digits}}}(?![\d.])"
            else:
                codes = "|".join(str(code) for code in policy.get("subtool_codes", []))
                zeros = "0" * offset_digits
                selections = rf"{number}{zeros}"
                capture = number
                if codes:
                    selections = rf"{codes}|{selections}"
                    capture = rf"{codes}|{capture}"
                pattern = rf"T\s*(?=0*(?:{selections})(?![\d.]))0*({capture})(?:{zeros})?(?![\d.])"
        patterns["tools"] = {
            "pattern": pattern,
            "description": "Tool identities generated from the machine tool_selection policy",
        }
    return patterns

def get_available_machines() -> List[Dict[str, str]]:
    """Return a list of available machines and their control types."""
    return [
        {"machineName": key, "controlType": val.name}
        for key, val in MACHINE_CONFIGS.items()
    ]