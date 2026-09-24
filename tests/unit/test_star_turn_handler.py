import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.domain.exceptions import ExceptionNode
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.handlers.star_machine.automatic_coordinate_handler import StarAutomaticCoordinateHandler
from ncplot7py.domain.handlers.star_machine.g266_handler import StarG266Handler
from ncplot7py.domain.handlers.star_machine.mcode_modal import StarModalMCodeHandler
from ncplot7py.domain.handlers.star_machine.spindle_fluctuation_handler import StarSpindleFluctuationHandler
from ncplot7py.domain.handlers.star_machine.star_turn_handler import StarTurnHandler
from ncplot7py.domain.machines import get_machine_config


class TestStarTurnHandler(unittest.TestCase):
    def test_g125_records_z1_coordinate_and_consumes_z_parameter(self):
        handler = StarTurnHandler()
        state = CNCState()

        node = NCCommandNode(g_code_command={"G125"}, command_parameter={"Z": "10.0"})

        pts, dur = handler.handle(node, state)

        self.assertNotIn("Z", node.command_parameter)
        self.assertTrue(state.extra["star.coordinate.z1_set"])
        self.assertEqual(state.extra["star.coordinate.z1_command"], {"Z": 10.0})
        self.assertIsNone(pts)
        self.assertIsNone(dur)

    def test_g125_without_z_defaults_to_z_zero(self):
        handler = StarAutomaticCoordinateHandler()

        for parameters, expected in (
            ({}, {"Z": 0.0}),
            ({"W": "2.5"}, {"W": 2.5, "Z": 0.0}),
            ({"Z": "0"}, {"Z": 0.0}),
        ):
            with self.subTest(parameters=parameters):
                state = CNCState()
                handler.handle(
                    NCCommandNode(g_code_command={"G125"}, command_parameter=parameters),
                    state,
                )

                self.assertTrue(state.extra["star.coordinate.z1_set"])
                self.assertEqual(state.extra["star.coordinate.z1_command"], expected)

    def test_g125_rejects_unsupported_x_word(self):
        handler = StarAutomaticCoordinateHandler()
        state = CNCState()

        with self.assertRaises(ExceptionNode) as error:
            handler.handle(
                NCCommandNode(g_code_command={"G125"}, command_parameter={"Z": "10", "X": "5"}),
                state,
            )

        self.assertEqual(error.exception.code, 3622)

    def test_automatic_coordinate_sequence_tracks_dependencies(self):
        handler = StarAutomaticCoordinateHandler()
        state = CNCState()

        handler.handle(NCCommandNode(g_code_command={"G125"}, command_parameter={"Z": "10"}), state)
        handler.handle(NCCommandNode(g_code_command={"G131"}, command_parameter={"B": "2"}), state)
        handler.handle(NCCommandNode(g_code_command={"G133"}), state)
        handler.handle(NCCommandNode(g_code_command={"G132"}), state)

        self.assertTrue(state.extra["star.coordinate.pickup_set"])
        self.assertTrue(state.extra["star.coordinate.projection_stored"])
        self.assertTrue(state.extra["star.coordinate.path2_machining"])

    def test_automatic_coordinate_commands_allow_missing_pickup_length_setup(self):
        handler = StarAutomaticCoordinateHandler()
        state = CNCState()

        handler.handle(NCCommandNode(g_code_command={"G131"}), state)
        handler.handle(NCCommandNode(g_code_command={"G133"}), state)
        handler.handle(NCCommandNode(g_code_command={"G132"}), state)

        self.assertTrue(state.extra["star.coordinate.pickup_set"])
        self.assertTrue(state.extra["star.coordinate.projection_stored"])
        self.assertTrue(state.extra["star.coordinate.path2_machining"])

    def test_g266_maps_parameters_to_state_variables_and_pops(self):
        handler = StarTurnHandler()
        state = CNCState()

        params = {
            "A": "1.5",
            "W": "2.0",
            "S": "300",
            "F": "120.0",
            "B": "2.0",
            "X": "15.0",
            "Z": "15.0",
            "T": "100",
        }
        node = NCCommandNode(g_code_command={"G266"}, command_parameter=dict(params))

        pts, dur = handler.handle(node, state)

        # parameters should be removed from the node
        for k in params.keys():
            self.assertNotIn(k, node.command_parameter)

        # state.parameters should contain mapped numeric entries as floats
        expected = {
            "531": 1.5,  # A
            "530": 2.0,  # W
            "529": 300.0,  # S
            "522": 120.0,  # F
            "528": 2.0,  # B
            "524": 15.0,  # X
            "525": 15.0,  # Z
            "523": 100.0,  # T
        }
        for k, v in expected.items():
            self.assertIn(k, state.parameters)
            self.assertAlmostEqual(float(state.parameters[k]), float(v))

        self.assertIsNone(pts)
        self.assertIsNone(dur)

    def test_g300_is_noop(self):
        handler = StarTurnHandler()
        state = CNCState()

        node = NCCommandNode(g_code_command={"G300"}, command_parameter={"Z": "5.0"})

        pts, dur = handler.handle(node, state)

        # G300 should be a no-op: Z remains
        self.assertIn("Z", node.command_parameter)
        self.assertEqual(node.command_parameter["Z"], "5.0")
        self.assertIsNone(pts)
        self.assertIsNone(dur)

    def test_g266_rejects_missing_required_word_before_mutation(self):
        handler = StarG266Handler()
        state = CNCState()
        node = NCCommandNode(
            g_code_command={"G266"},
            command_parameter={"A": "1", "X": "2", "W": "3", "S": "4", "Z": "5", "B": "6"},
        )

        with self.assertRaises(ExceptionNode) as error:
            handler.handle(node, state)

        self.assertEqual(error.exception.code, 3686)
        self.assertEqual(state.parameters, {})
        self.assertIn("A", node.command_parameter)

    def test_g25_and_g26_toggle_spindle_fluctuation_monitoring(self):
        handler = StarSpindleFluctuationHandler()
        state = CNCState()

        handler.handle(NCCommandNode(g_code_command={"G26"}), state)
        self.assertTrue(state.extra["star.spindle.fluctuation_monitoring"])
        handler.handle(NCCommandNode(g_code_command={"G25"}), state)
        self.assertFalse(state.extra["star.spindle.fluctuation_monitoring"])

    def test_m9_returns_c_axis_to_zero_with_rapid_motion(self):
        handler = StarModalMCodeHandler(next_handler=MotionHandler())
        state = CNCState(axes={"X": 0.0, "Y": 0.0, "Z": 0.0, "C": 90.0})

        points, duration = handler.handle(NCCommandNode(command_parameter={"M": "9"}), state)

        self.assertEqual(state.get_modal("coolant_mode"), "M9")
        self.assertEqual(state.get_axis("C"), 0.0)
        self.assertTrue(points)
        self.assertEqual(points[-1].c, 0.0)

    def test_m8_and_m9_toggle_c_axis_pose_mode(self):
        handler = StarModalMCodeHandler()
        state = CNCState()

        handler.handle(NCCommandNode(command_parameter={"M": "8"}), state)
        self.assertEqual(state.extra["star.c_axis_mode"], "positionControlled")

        handler.handle(NCCommandNode(command_parameter={"M": "9"}), state)
        self.assertEqual(state.extra["star.c_axis_mode"], "spindleInvariant")

    def test_m9_resets_selected_star_spindle_axis(self):
        handler = StarModalMCodeHandler()
        state = CNCState(
            axes={"X": 0.0, "Y": 0.0, "Z": 0.0, "C1": 0.0, "C2": 0.0},
            machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"),
        )
        state.set_axis("C1", 90.0)
        state.set_axis("C2", 45.0)
        handler.handle(NCCommandNode(command_parameter={"M": "171"}), state)
        handler.handle(NCCommandNode(command_parameter={"M": "9"}), state)

        self.assertEqual(state.get_axis("C1"), 90.0)
        self.assertEqual(state.get_axis("C2"), 0.0)

    def test_m171_routes_bare_c_to_sub_spindle_axis(self):
        modal_handler = StarModalMCodeHandler()
        motion_handler = MotionHandler()
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))

        modal_handler.handle(NCCommandNode(command_parameter={"M": "171"}), state)
        motion_handler.handle(NCCommandNode(g_code_command={"G0"}, command_parameter={"C": "90"}), state)

        self.assertEqual(state.extra["star.targetCarrierId"], "subSpindle")
        self.assertEqual(state.extra["star.targetAxis"], "C2")
        self.assertEqual(state.get_axis("C2"), 90.0)


if __name__ == '__main__':
    unittest.main()
