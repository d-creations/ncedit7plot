import logging
from typing import List, Type, Any, Optional, Sequence, Tuple, Dict

from ncplot7py.domain.exec_chain import Handler


HANDLER_REGISTRY: Dict[str, Tuple[str, str]] = {
    # Core
    "axis_binding": ("ncplot7py.domain.handlers.axis_binding", "AxisBindingHandler"),
    "variable": ("ncplot7py.domain.handlers.variable", "VariableHandler"),
    "fanuc_alarm": ("ncplot7py.domain.handlers.fanuc_alarm", "FanucAlarmHandler"),
    "control_flow": ("ncplot7py.domain.handlers.control_flow", "ControlFlowHandler"),

    # Base
    "motion": ("ncplot7py.domain.handlers.motion", "MotionHandler"),
    "modal": ("ncplot7py.domain.handlers.modal", "ModalHandler"),
    "fanuc_mill_mcode_modal": ("ncplot7py.domain.handlers.fanuc_mill_cnc.mcode_modal", "FanucMillModalMCodeHandler"),
    "fanuc_turn_mcode_modal": ("ncplot7py.domain.handlers.fanuc_turn_cnc.mcode_modal", "FanucTurnModalMCodeHandler"),
    "star_mcode_modal": ("ncplot7py.domain.handlers.star_machine.mcode_modal", "StarModalMCodeHandler"),
    "siemens_mill_mcode_modal": ("ncplot7py.domain.handlers.siemens_mill_cnc.mcode_modal", "SiemensMillModalMCodeHandler"),
    "star_spindle": ("ncplot7py.domain.handlers.star_machine.spindle_handler", "StarSpindleHandler"),
    "fanuc_turn_spindle": ("ncplot7py.domain.handlers.fanuc_turn_cnc.spindle_handler", "FanucTurnSpindleHandler"),
    "spindle_speed": ("ncplot7py.domain.handlers.modal", "ModalHandler"),
    "wait_code": ("ncplot7py.domain.handlers.wait_code", "WaitCodeHandler"),
    "fanuc_tool_handler": ("ncplot7py.domain.handlers.fanuc_machine.tool_handler", "FanucToolHandler"),
    "siemens_tool_handler": ("ncplot7py.domain.handlers.siemens_machine.tool_handler", "SiemensToolHandler"),
    "star_fanuc_tool_handler": ("ncplot7py.domain.handlers.star_machine.tool_handler", "StarFanucToolHandler"),
    "cycle_end": ("ncplot7py.domain.handlers.cycle_end", "CycleEnd"),

    # Generic & Fanuc
    "group_0_coordinate_set": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group0_coordinate_set", "GCodeGroup0CoordinateSetExecChainLink"),
    "fanuc_turn_spindle_limit": ("ncplot7py.domain.handlers.fanuc_turn_cnc.spindle_limit_handler", "FanucTurnSpindleLimitHandler"),
    "fanuc_turn_units": ("ncplot7py.domain.handlers.fanuc_turn_cnc.unit_handler", "FanucTurnUnitHandler"),
    "fanuc_g92_threading": ("ncplot7py.domain.handlers.fanuc_turn_cnc.g92_threading_cycle", "FanucG92ThreadingCycleHandler"),
    "fanuc_g76_threading": ("ncplot7py.domain.handlers.fanuc_turn_cnc.g76_threading_cycle", "FanucG76ThreadingCycleHandler"),
    "fanuc_g36_circular_threading": ("ncplot7py.domain.handlers.fanuc_turn_cnc.g36_circular_threading", "FanucG36CircularThreadingHandler"),
    "fanuc_coordinate_rotation": ("ncplot7py.domain.handlers.fanuc_turn_cnc.coordinate_rotation_handler", "FanucCoordinateRotationHandler"),
    "fanuc_turn_drilling_cycles": ("ncplot7py.domain.handlers.fanuc_turn_cnc.drilling_cycle_handler", "FanucTurnDrillingCycleHandler"),
    "group_2_speed_mode": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group2_speed_mode", "FanucTurnSpeedModeHandler"),
    "group_5_feed_mode": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group5_feed_mode", "GCodeGroup5FeedModeExecChainLink"),
    "group_16_plane": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group16_plane", "GCodeGroup16PlaneExecChainLink"),
    "group_21_polar": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group21_polar_co", "GCodeGroup21PolarCoExecChainLink"),
    "precheck": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_precheck", "GcodePreCheckExecChainLink"),
    "fanuc_precheck": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_precheck", "GcodePreCheckExecChainLink"),
    "cornering": ("ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_cornering", "FanucCorneringHandler"),

    # Fanuc Mill Specific
    "fanuc_mill_groups": ("ncplot7py.domain.handlers.fanuc_mill_cnc.gcode_groups", "FanucMillGCodeGroupValidator"),
    "fanuc_mill_feed_mode": ("ncplot7py.domain.handlers.fanuc_mill_cnc.gcode_group5_feed_mode", "FanucMillGroup5FeedModeHandler"),
    "fanuc_mill_speed_mode": ("ncplot7py.domain.handlers.fanuc_mill_cnc.gcode_speed_mode", "FanucMillSpeedModeHandler"),
    "fanuc_mill_work_offset": ("ncplot7py.domain.handlers.fanuc_mill_cnc.gcode_work_offset", "FanucMillWorkOffsetHandler"),
    "fanuc_mill_plane": ("ncplot7py.domain.handlers.fanuc_mill_cnc.gcode_group2_plane", "FanucMillGroup2PlaneHandler"),
    "fanuc_cutter_comp": ("ncplot7py.domain.handlers.fanuc_mill_cnc.cutter_comp_handler", "FanucCutterCompCommandHandler"),

    # Turn Mill Star
    "star_spindle_fluctuation": ("ncplot7py.domain.handlers.star_machine.spindle_fluctuation_handler", "StarSpindleFluctuationHandler"),
    "star_automatic_coordinate": ("ncplot7py.domain.handlers.star_machine.automatic_coordinate_handler", "StarAutomaticCoordinateHandler"),
    "star_g266": ("ncplot7py.domain.handlers.star_machine.g266_handler", "StarG266Handler"),
    "star_b1_tilting": ("ncplot7py.domain.handlers.star_machine.b1_tilting_handler", "StarB1TiltingHandler"),
    "star_g161_step_cycle": ("ncplot7py.domain.handlers.star_machine.g161_step_cycle_handler", "StarG161StepCycleHandler"),
    "star_turn": ("ncplot7py.domain.handlers.star_machine.star_turn_handler", "StarTurnHandler"),

    # Siemens Specific
    "siemens_alarm": ("ncplot7py.domain.handlers.siemens_mill_cnc.alarm_handler", "SiemensAlarmHandler"),
    "siemens_variables": ("ncplot7py.domain.handlers.siemens_mill_cnc.variable_handler", "SiemensVariableHandler"),
    "siemens_flow_control": ("ncplot7py.domain.handlers.siemens_mill_cnc.flow_control_handler", "SiemensFlowControlHandler"),
    "siemens_builtins": ("ncplot7py.domain.handlers.siemens_mill_cnc.builtin_handler", "SiemensBuiltinHandler"),
    "siemens_frames": ("ncplot7py.domain.handlers.siemens_mill_cnc.frame_handler", "SiemensFrameHandler"),
    "siemens_transformations": ("ncplot7py.domain.handlers.siemens_mill_cnc.transformation_handler", "SiemensTransformationHandler"),
    "siemens_path_mode": ("ncplot7py.domain.handlers.siemens_mill_cnc.path_mode_handler", "SiemensPathModeHandler"),
    "siemens_mode": ("ncplot7py.domain.handlers.siemens_mill_cnc.mode_handler", "SiemensModeHandler"),
    "siemens_named_cycles": ("ncplot7py.domain.handlers.siemens_mill_cnc.cycles_handler", "SiemensNamedCyclesHandler"),
    "siemens_iso_cycles": ("ncplot7py.domain.handlers.siemens_mill_cnc.cycles_handler", "SiemensISOCyclesHandler"),
    "siemens_iso_feed": ("ncplot7py.domain.handlers.siemens_mill_cnc.feed_handler", "SiemensISOFeedHandler"),
    "siemens_iso_speed": ("ncplot7py.domain.handlers.siemens_mill_cnc.speed_handler", "SiemensISOSpeedHandler"),
    "siemens_plane": ("ncplot7py.domain.handlers.siemens_mill_cnc.gcode_group6_plane", "SiemensGroup6PlaneHandler"),
    "siemens_iso_polar": ("ncplot7py.domain.handlers.siemens_mill_cnc.polar_handler", "SiemensISOPolarHandler"),
    "siemens_iso_tool_length": ("ncplot7py.domain.handlers.siemens_mill_cnc.tool_length_handler", "SiemensISOToolLengthHandler"),
    "siemens_iso_cutter_comp": ("ncplot7py.domain.handlers.siemens_mill_cnc.cutter_comp_handler", "SiemensISOCutterCompHandler"),
    "siemens_iso_coordinate": ("ncplot7py.domain.handlers.siemens_mill_cnc.coordinate_handler", "SiemensISOCoordinateHandler"),
    "siemens_iso_inch_metric": ("ncplot7py.domain.handlers.siemens_mill_cnc.unit_handler", "SiemensISOInchMetricHandler"),
    "siemens_iso_misc": ("ncplot7py.domain.handlers.siemens_mill_cnc.misc_handler", "SiemensISOMiscHandler"),
    "siemens_motion": ("ncplot7py.domain.handlers.siemens_mill_cnc.motion_handler", "SiemensMotionHandler"),
}


class HandlerChainBuilder:
    """Builder for constructing a Chain of Responsibility for CNC handlers.
    
    Handlers are added in the order they should execute (first added = first executed).
    The builder automatically wires them together from last to first when build() is called.
    """
    
    def __init__(self):
        self._handlers: List[Type[Handler] | Any] = []

    def add(self, handler: Type[Handler] | Any) -> "HandlerChainBuilder":
        """Adds a handler class to the end of the chain (it will be executed after all previously added handlers).
        
        Args:
            handler: Either a Handler class (which will be automatically instantiated) 
                     or an already instantiated Handler object.
        """
        self._handlers.append(handler)
        return self

    def add_if_importable(self, module_path: str, class_name: str) -> "HandlerChainBuilder":
        """Attempts to dynamically import and add a handler class to the sequence.
        If the import fails, it silently skips it, acting as a fallback mechanism.
        """
        import importlib
        try:
            module = importlib.import_module(module_path)
            handler_class = getattr(module, class_name)
            self._handlers.append(handler_class)
        except (ImportError, AttributeError):
            pass
        return self

    def build(self) -> Optional[Handler]:
        """Wires up the added handlers in reverse order.
        
        Returns:
            The first Handler in the chain (head), or None if the chain is empty.
        """
        current_next = None
        # Wire from end of list back to the start
        for handler_entry in reversed(self._handlers):
            if isinstance(handler_entry, type):
                # It's an uninstantiated class
                current = handler_entry(next_handler=current_next)
            else:
                # It's an already instantiated object
                current = handler_entry
                if hasattr(current, 'next_handler'):
                    current.next_handler = current_next
            current_next = current
            
        return current_next

    @classmethod
    def from_groups(cls, groups: Sequence[str], registry: Optional[Dict[str, Tuple[str, str]]] = None) -> Optional[Handler]:
        """Construct a handler chain from a sequence of configured group identifiers."""
        active_registry = registry if registry is not None else HANDLER_REGISTRY
        builder = cls()
        for group in groups:
            if group in active_registry:
                mod_path, cls_name = active_registry[group]
                builder.add_if_importable(mod_path, cls_name)
            else:
                logging.getLogger(__name__).warning("Handler for group '%s' not found in HANDLER_REGISTRY.", group)
        return builder.build()


__all__ = ["HANDLER_REGISTRY", "HandlerChainBuilder"]