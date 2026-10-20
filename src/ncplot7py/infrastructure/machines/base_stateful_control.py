import re
from typing import Dict, List, Optional, Tuple, Sequence, Type, Any

from ncplot7py.interfaces.BaseNCCanal import NCControl as BaseNCControlInterface
from ncplot7py.interfaces.BaseNCControl import NCCanal as BaseNCCanalInterface
from ncplot7py.domain.canal_interpreter import CanalProgramInterpreter
from ncplot7py.domain.cnc_state import CNCState, MachineState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.tool_compensation import ToolPathCompensator
from ncplot7py.infrastructure.handler_chain_builder import HANDLER_REGISTRY, HandlerChainBuilder
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


def _plane_from_default_code(default_plane: str) -> str:
    plane_code = str(default_plane or "").upper()
    if plane_code == "G18":
        return "X_Z"
    if plane_code == "G19":
        return "Y_Z"
    return "X_Y"


class BaseStatefulCanal(BaseNCCanalInterface):
    """Base canal delegating step-by-step program execution to CanalProgramInterpreter."""

    def __init__(self, name: str, init_state: Optional[CNCState] = None):
        self._name = name
        self._state = init_state or CNCState()
        match = re.search(r"(\d+)$", str(name))
        if self._state.channel_state.path_number is None:
            self._state.channel_state.path_number = int(match.group(1)) if match else 1
        self._tool_path_compensator = ToolPathCompensator()
        self._interpreter = CanalProgramInterpreter(self._tool_path_compensator)
        self._initialize_configured_target()
        self._chain = None
        self._control_handler = None
        self._nodes: List[NCCommandNode] = []
        self._tool_path: List[Tuple[List[Point], float]] = []
        self._tool_nodes: List[NCCommandNode] = []
        self._exec_sequence: List[NCCommandNode] = []

    def _initialize_configured_target(self) -> None:
        CanalProgramInterpreter.initialize_configured_target(self._name, self._state)

    def get_name(self) -> str:
        return self._name

    def get_tool_path(self) -> List[Tuple[List[Point], float]]:
        return self._tool_path

    def get_exec_nodes(self) -> List[NCCommandNode]:
        if hasattr(self, "_tool_nodes") and self._tool_nodes:
            return self._tool_nodes
        return getattr(self, "_exec_sequence", self._nodes)

    def _capture_motion_context(self, start_axes: Optional[Dict[str, float]] = None) -> Dict[str, object]:
        return CanalProgramInterpreter.capture_motion_context(self._name, self._state, start_axes)

    def _resolve_motion_target(self) -> Optional[Dict[str, str]]:
        return CanalProgramInterpreter.resolve_motion_target(self._name, self._state)

    @staticmethod
    def _axis_for_workpiece(simulation: Dict[str, object], carrier_id: str) -> str:
        return CanalProgramInterpreter.axis_for_workpiece(simulation, carrier_id)

    def _get_handler(self, handler_type: Type) -> Optional[Any]:
        """Utility to retrieve a specific instance of a handler from the chain."""
        current = self._chain
        while current is not None:
            if isinstance(current, handler_type):
                return current
            current = getattr(current, "next_handler", None)
        return None

    def run_nc_code_list(self, linked_code_list: List[NCCommandNode]) -> None:
        self._nodes = list(linked_code_list)
        self._tool_path = []
        self._tool_nodes = []
        self._exec_sequence = []
        self._interpreter.execute(
            self._name,
            self._nodes,
            self._state,
            self._chain,
            tool_path=self._tool_path,
            tool_nodes=self._tool_nodes,
            exec_sequence=self._exec_sequence,
        )


class BaseStatefulControl(BaseNCControlInterface):
    """Base class for stateful controls managing multiple canals to reduce duplication."""

    def __init__(
        self,
        canal_class: Type,
        count_of_canals: int = 1,
        canal_names: Optional[Sequence[str]] = None,
        init_nc_states: Optional[Sequence[Optional[CNCState]]] = None
    ) -> None:
        self.count_of_canals = int(count_of_canals)
        
        if canal_names is None:
            names = [f"C{i+1}" for i in range(self.count_of_canals)]
        elif isinstance(canal_names, str):
            names = [canal_names for _ in range(self.count_of_canals)]
        else:
            names = list(canal_names)
        if len(names) < self.count_of_canals:
            names.extend(f"C{i+1}" for i in range(len(names), self.count_of_canals))

        init_states = list(init_nc_states) if init_nc_states is not None else [None] * self.count_of_canals
        if len(init_states) < self.count_of_canals:
            init_states.extend([None] * (self.count_of_canals - len(init_states)))

        # Coordinate shared MachineState across canals if not explicitly isolated
        shared_machine_state: Optional[MachineState] = None
        for s in init_states:
            if s is not None and getattr(s, "machine_state", None) is not None:
                shared_machine_state = s.machine_state
                break

        self._canals: Dict[int, Any] = {}
        for idx in range(self.count_of_canals):
            st = init_states[idx]
            if st is None:
                st = CNCState()
                init_states[idx] = st
            if shared_machine_state is None and st.machine_state is not None:
                shared_machine_state = st.machine_state
            elif shared_machine_state is not None:
                st.machine_state = shared_machine_state
            self._canals[idx + 1] = canal_class(names[idx], st)

    def get_canal_name(self, canal: int) -> str:
        c = self._canals.get(canal)
        if c is not None:
            if hasattr(c, "get_name"):
                return c.get_name()
            if hasattr(c, "_name"):
                return c._name
        return f"C{canal}"

    def run_nc_code_list(self, linked_code_list: List[NCCommandNode], canal: int) -> None:
        c = self._canals.get(canal)
        if c is None:
            raise IndexError(f"Canal {canal} not configured")
        c.run_nc_code_list(linked_code_list)

    def get_tool_path(self, canal: int) -> List[Tuple[List[Point], float]]:
        c = self._canals.get(canal)
        if c is None:
            return []
        return c.get_tool_path()

    def get_exected_nodes(self, canal: int) -> List[NCCommandNode]:
        c = self._canals.get(canal)
        if c is None:
            return []
        if hasattr(c, "get_exec_nodes"):
            return c.get_exec_nodes()
        return []

    def get_canal_count(self) -> int:
        return self.count_of_canals

    def get_nc_state(self, canal: int) -> Optional[CNCState]:
        c = self._canals.get(canal)
        if c is None:
            return None
        if hasattr(c, "state"):
            return getattr(c, "state")
        if hasattr(c, "_state"):
            return getattr(c, "_state")
        return None

    def synchro_points(self, tool_paths, nodes):
        return None


class UniversalConfigDrivenCanal(BaseStatefulCanal):
    """Canal dynamically built from the machine config's `supported_gcode_groups`."""
    
    def __init__(self, name: str, init_state: Optional[CNCState] = None):
        super().__init__(name, init_state)

        if self._state.machine_config is None:
            self._state.machine_config = get_machine_config("FANUC_MILL")

        default_plane = _plane_from_default_code(self._state.machine_config.default_plane)
        self._state.channel_state.plane = default_plane
        if "siemens_mode" in self._state.machine_config.supported_gcode_groups:
            self._state.siemens_state.siemens_mode = False

        self._chain = HandlerChainBuilder.from_groups(
            self._state.machine_config.supported_gcode_groups,
            registry=HANDLER_REGISTRY,
        )


class UniversalConfigDrivenControl(BaseStatefulControl):
    """Generic CNC Control driven entirely by `machines.json` via `UniversalConfigDrivenCanal`."""
    
    def __init__(self, count_of_canals: int = 1, canal_names: Optional[Sequence[str]] = None, init_nc_states: Optional[Sequence[CNCState]] = None) -> None:
        if count_of_canals == 1 and init_nc_states and init_nc_states[0] and init_nc_states[0].machine_config:
            if init_nc_states[0].machine_config.channels > 1:
                count_of_canals = init_nc_states[0].machine_config.channels
                
        self._synchro_strategy = "NONE"
        if init_nc_states and init_nc_states[0] and init_nc_states[0].machine_config:
            self._synchro_strategy = init_nc_states[0].machine_config.synchronization_strategy

        super().__init__(UniversalConfigDrivenCanal, count_of_canals, canal_names, init_nc_states)

        from ncplot7py.infrastructure.nc_language_frontend import create_language_frontend

        state = self.get_nc_state(1)
        machine_config = getattr(state, "machine_config", None)
        self.language_frontend = create_language_frontend(machine_config)

    def synchro_points(self, tool_paths, nodes):
        if self._synchro_strategy == "STAR_WAIT":
            from ncplot7py.infrastructure.machines.star_canal_syncro import CanalSynchro
            syn = CanalSynchro(tool_paths, nodes)
            syn.synchro_points()
        return None


__all__ = [
    "BaseStatefulCanal",
    "BaseStatefulControl",
    "UniversalConfigDrivenCanal",
    "UniversalConfigDrivenControl",
    "HANDLER_REGISTRY",
]
