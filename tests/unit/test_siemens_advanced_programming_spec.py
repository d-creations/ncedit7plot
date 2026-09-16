import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.machines.base_stateful_control import HANDLER_REGISTRY
from ncplot7py.shared.nc_nodes import NCCommandNode


class TestSiemensAdvancedProgrammingSpec(unittest.TestCase):
    """Executable specification for planned Siemens advanced programming support.

    These tests are expected to fail until the Siemens-specific handlers from
    docs/SIEMENS_ADVANCED_PROGRAMMING_PLAN.md are implemented and registered.
    """

    def test_siemens_advanced_handlers_are_registered_before_cycles(self):
        expected_handlers = [
            "siemens_alarm",
            "siemens_variables",
            "siemens_flow_control",
            "siemens_builtins",
            "siemens_frames",
            "siemens_transformations",
            "siemens_path_mode",
        ]

        for handler_name in expected_handlers:
            self.assertIn(handler_name, HANDLER_REGISTRY)

        config = get_machine_config("SIEMENS_840DI")
        groups = list(config.supported_gcode_groups)

        for handler_name in expected_handlers:
            self.assertIn(handler_name, groups)

        first_cycle_index = groups.index("siemens_named_cycles")
        for handler_name in expected_handlers:
            self.assertLess(groups.index(handler_name), first_cycle_index)

    def test_variable_handler_defines_arrays_and_named_assignments(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.variable_handler import SiemensVariableHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        handler = SiemensVariableHandler()

        handler.handle(NCCommandNode(variable_command="DEF REAL CUSTOM_MC[30]"), state)
        handler.handle(NCCommandNode(variable_command="DEF INT IAngleBasis = 3"), state)
        handler.handle(NCCommandNode(variable_command="CUSTOM_MC[3]=12.5"), state)
        handler.handle(NCCommandNode(variable_command="ANGLE_Z=ATAN2(30.5,80.1)"), state)

        siemens = state.extra["siemens"]
        self.assertEqual(siemens["types"]["CUSTOM_MC"], "REAL")
        self.assertEqual(len(siemens["arrays"]["CUSTOM_MC"]), 30)
        self.assertAlmostEqual(siemens["arrays"]["CUSTOM_MC"][3], 12.5)
        self.assertEqual(siemens["symbols"]["IAngleBasis"], 3)
        self.assertAlmostEqual(siemens["symbols"]["ANGLE_Z"], 20.8455, places=3)

    def test_flow_control_gotof_jumps_to_named_label(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.flow_control_handler import SiemensFlowControlHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        handler = SiemensFlowControlHandler()

        node_jump = NCCommandNode(loop_command="GOTOFQUADRANT_00", nc_code_line_nr=1)
        node_skipped = NCCommandNode(g_code_command={"G1"}, command_parameter={"X": "999"}, nc_code_line_nr=2)
        node_label = NCCommandNode(variable_command="QUADRANT_00:", nc_code_line_nr=3)
        node_target = NCCommandNode(g_code_command={"G1"}, command_parameter={"X": "10"}, nc_code_line_nr=4)
        nodes = [node_jump, node_skipped, node_label, node_target]

        for previous, next_node in zip(nodes, nodes[1:]):
            previous._next_ncCode = next_node
            next_node._before_ncCode = previous

        handler.setup_maps(nodes)
        handler.handle(node_jump, state)

        self.assertIs(node_jump._next_ncCode, node_label)

    def test_flow_control_for_loop_updates_counter_and_repeats_body(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.flow_control_handler import SiemensFlowControlHandler
        from ncplot7py.domain.handlers.siemens_mill_cnc.variable_handler import SiemensVariableHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        variable_handler = SiemensVariableHandler()
        flow_handler = SiemensFlowControlHandler()

        variable_handler.handle(NCCommandNode(variable_command="DEF INT iStepsZ01"), state)

        node_for = NCCommandNode(loop_command="ForiStepsZ01=1to3", nc_code_line_nr=1)
        node_body = NCCommandNode(variable_command="CUSTOM_COUNT=iStepsZ01", nc_code_line_nr=2)
        node_end = NCCommandNode(loop_command="ENDFOR", nc_code_line_nr=3)
        nodes = [node_for, node_body, node_end]

        for previous, next_node in zip(nodes, nodes[1:]):
            previous._next_ncCode = next_node
            next_node._before_ncCode = previous

        flow_handler.setup_maps(nodes)
        flow_handler.handle(node_for, state)
        self.assertEqual(state.extra["siemens"]["symbols"]["iStepsZ01"], 1)

        flow_handler.handle(node_end, state)
        self.assertIs(node_end._next_ncCode, node_body)
        self.assertEqual(state.extra["siemens"]["symbols"]["iStepsZ01"], 2)

    def test_frame_handler_stores_chained_uifr_frame(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.frame_handler import SiemensFrameHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        handler = SiemensFrameHandler()

        state.extra["siemens"] = {
            "symbols": {
                "ORIGIN_GP": 1,
                "VALUATION_X": 10.0,
                "VALUATION_Y": 20.0,
                "VALUATION_Z1": -5.0,
                "ANGLE_X": 1.0,
                "ANGLE_Y": 2.0,
                "ANGLE_Z": 3.0,
            },
            "types": {},
            "arrays": {},
            "labels": {},
            "flow": {},
            "system_variables": {},
            "frames": {},
        }

        node = NCCommandNode(
            variable_command="$P_UIFR[ORIGIN_GP]=CTRANS(X,VALUATION_X,Y,VALUATION_Y,Z,VALUATION_Z1):CROT(X,ANGLE_X,Y,ANGLE_Y,Z,ANGLE_Z)"
        )
        handler.handle(node, state)

        frame = state.extra["siemens"]["frames"][1]
        self.assertEqual(frame["translation"], {"X": 10.0, "Y": 20.0, "Z": -5.0})
        self.assertEqual(frame["rotation"], {"X": 1.0, "Y": 2.0, "Z": 3.0})

    def test_alarm_and_builtin_handlers_have_separate_responsibilities(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.alarm_handler import SiemensAlarmHandler
        from ncplot7py.domain.handlers.siemens_mill_cnc.builtin_handler import SiemensBuiltinHandler
        from ncplot7py.domain.exceptions import ExceptionNode, ExceptionTyps

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        builtin_handler = SiemensBuiltinHandler()
        alarm_handler = SiemensAlarmHandler()

        builtin_handler.handle(NCCommandNode(variable_command="SPOS=180", nc_code_line_nr=23), state)
        builtin_handler.handle(NCCommandNode(variable_command="RET", nc_code_line_nr=24), state)
        with self.assertRaises(ExceptionNode) as caught:
            alarm_handler.handle(NCCommandNode(variable_command='SETAL(65000,"Axis distance too small")', nc_code_line_nr=22), state)

        self.assertEqual(caught.exception.typ, ExceptionTyps.CNCError)
        self.assertEqual(caught.exception.code, 65000)
        self.assertEqual(state.extra["alarms"][-1]["code"], 65000)
        self.assertEqual(state.extra["alarms"][-1]["message"], "Axis distance too small")
        self.assertEqual(state.extra["alarms"][-1]["line"], 22)
        self.assertEqual(state.extra["siemens"]["spindle_position"], 180.0)
        self.assertEqual(state.extra["siemens.c_axis_mode"], "positionControlled")
        self.assertEqual(state.extra["siemens.c_axis_position"], 180.0)
        self.assertTrue(state.extra["program_returned"])

    def test_transformation_handler_toggles_traori_trafoof(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.transformation_handler import SiemensTransformationHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        handler = SiemensTransformationHandler()

        handler.handle(NCCommandNode(variable_command="TRAORI"), state)
        self.assertTrue(state.extra["siemens"]["transformations"]["TRAORI"]["active"])

        handler.handle(NCCommandNode(variable_command="TRAFOOF"), state)
        self.assertFalse(state.extra["siemens"]["transformations"]["TRAORI"]["active"])

    def test_path_mode_handler_records_g64(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.path_mode_handler import SiemensPathModeHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        handler = SiemensPathModeHandler()

        handler.handle(NCCommandNode(g_code_command={"G64"}), state)

        self.assertEqual(state.extra["siemens"]["path_mode"], "G64")

    def test_coordinate_handler_activates_g54_and_bypasses_with_g53(self):
        from ncplot7py.domain.handlers.siemens_mill_cnc.coordinate_handler import SiemensISOCoordinateHandler

        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        state.extra["siemens"] = {
            "symbols": {},
            "types": {},
            "arrays": {},
            "labels": {},
            "flow": {},
            "system_variables": {},
            "frames": {1: {"translation": {"X": 10.0, "Y": 20.0, "Z": 0.0}, "rotation": {}}},
            "transformations": {},
            "path_mode": None,
        }
        handler = SiemensISOCoordinateHandler()

        handler.handle(NCCommandNode(g_code_command={"G54"}), state)
        self.assertEqual(state.extra["active_work_offset_index"], 1)
        self.assertEqual(state.offsets["X"], 10.0)
        self.assertEqual(state.offsets["Y"], 20.0)

        handler.handle(NCCommandNode(g_code_command={"G53"}, command_parameter={"X": "0"}), state)
        self.assertTrue(state.extra["siemens"]["bypass_work_offset_once"])


if __name__ == "__main__":
    unittest.main()