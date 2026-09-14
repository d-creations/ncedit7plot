import unittest
import math

from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenCanal as UniversalConfigDrivenCanal
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group2_speed_mode import SpeedMode
from ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group5_feed_mode import FeedMode


class TestFanucModals(unittest.TestCase):
    def test_g20_converts_new_input_without_converting_existing_position(self):
        cstate = CNCState(axes={"X": 10.0, "Y": 0.0, "Z": 0.0})
        cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal("C1", init_state=cstate)

        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G20", "G1"}, command_parameter={"Z": "1", "F": "2"}),
        ])

        self.assertEqual(cstate.get_modal("units"), "G20")
        self.assertEqual(cstate.get_axis("X"), 10.0)
        self.assertAlmostEqual(cstate.get_axis("Z"), 25.4)
        self.assertAlmostEqual(cstate.feed_rate, 50.8)

    def test_g21_restores_metric_input(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal("C1", init_state=cstate)

        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G20"}),
            NCCommandNode(g_code_command={"G21", "G1"}, command_parameter={"Z": "2"}),
        ])

        self.assertEqual(cstate.get_modal("units"), "G21")
        self.assertAlmostEqual(cstate.get_axis("Z"), 2.0)

    def test_fanuc_mill_g0_remains_active_for_axis_only_blocks(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_MILL")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        nodes = [
            NCCommandNode(g_code_command={'G0'}, command_parameter={'X': '0.0', 'Y': '0.0', 'Z': '20.0'}),
            NCCommandNode(g_code_command=set(), command_parameter={'Z': '-10.0', 'F': '180.0'}),
            NCCommandNode(g_code_command=set(), command_parameter={'X': '20.0'}),
            NCCommandNode(g_code_command=set(), command_parameter={'Y': '20.0'}),
        ]

        canal.run_nc_code_list(nodes)

        self.assertEqual(cstate.get_modal('G_GROUP_1'), 'G00')
        self.assertAlmostEqual(cstate.get_axis('X'), 20.0)
        self.assertAlmostEqual(cstate.get_axis('Y'), 20.0)
        self.assertAlmostEqual(cstate.get_axis('Z'), -10.0)
        self.assertEqual(len(canal.get_tool_path()), 4)

    def test_g96_sets_surface_speed_mode(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        node = NCCommandNode(g_code_command={'G96'}, command_parameter={})
        canal.run_nc_code_list([node])
        self.assertIn('surface_speed_mode', cstate.extra)
        val = cstate.extra['surface_speed_mode']
        # Accept both Enum and string values
        self.assertTrue(val == SpeedMode.CONSTANT_CUTSPEED or val == SpeedMode.CONSTANT_CUTSPEED.value)

    def test_g97_sets_constant_rev(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        node = NCCommandNode(g_code_command={'G97'}, command_parameter={})
        canal.run_nc_code_list([node])
        self.assertIn('surface_speed_mode', cstate.extra)
        val = cstate.extra['surface_speed_mode']
        self.assertTrue(val == SpeedMode.CONSTANT_REV or val == SpeedMode.CONSTANT_REV.value)

    def test_g98_and_g99_conflict_raises(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        node = NCCommandNode(g_code_command={'G98','G99'}, command_parameter={})
        # Running should raise an exception from the handler; capture via unittest
        with self.assertRaises(Exception):
            canal.run_nc_code_list([node])

    def test_g98_sets_feed_per_min(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        node = NCCommandNode(g_code_command={'G98'}, command_parameter={})
        canal.run_nc_code_list([node])
        self.assertIn('feed_mode', cstate.extra)
        val = cstate.extra['feed_mode']
        self.assertTrue(val == FeedMode.FEED_PER_MIN or val == FeedMode.FEED_PER_MIN.value)

    def test_g99_sets_feed_per_rev(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        node = NCCommandNode(g_code_command={'G99'}, command_parameter={})
        canal.run_nc_code_list([node])
        self.assertIn('feed_mode', cstate.extra)
        val = cstate.extra['feed_mode']
        self.assertTrue(val == FeedMode.FEED_PER_REV or val == FeedMode.FEED_PER_REV.value)

    def test_g96_g99_duration_uses_x_diameter(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        nodes = [
            NCCommandNode(g_code_command={'G0'}, command_parameter={'X': '100'}),
            NCCommandNode(g_code_command={'G96', 'G99', 'G1'}, command_parameter={'Z': '-100', 'S': '200', 'F': '0.2'}),
        ]

        canal.run_nc_code_list(nodes)

        _points, duration = canal.get_tool_path()[-1]
        expected_rpm = 1000.0 * 200.0 / (math.pi * 100.0)
        self.assertAlmostEqual(duration, 100.0 / (0.2 * expected_rpm / 60.0))

    def test_g96_face_cut_uses_average_x_diameter(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal('C1', init_state=cstate)
        nodes = [
            NCCommandNode(g_code_command={'G0'}, command_parameter={'X': '100'}),
            NCCommandNode(g_code_command={'G96', 'G99', 'G1'}, command_parameter={'X': '50', 'S': '200', 'F': '0.2'}),
        ]

        canal.run_nc_code_list(nodes)

        _points, duration = canal.get_tool_path()[-1]
        expected_rpm = 1000.0 * 200.0 / (math.pi * 75.0)
        self.assertAlmostEqual(duration, 25.0 / (0.2 * expected_rpm / 60.0))

    def test_g50_s_caps_g96_without_becoming_commanded_speed(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_TURN")
        canal = UniversalConfigDrivenCanal("C1", init_state=cstate)

        canal.run_nc_code_list([NCCommandNode(g_code_command={"G50"}, command_parameter={"S": "1000"})])

        self.assertIsNone(cstate.spindle_speed)
        self.assertEqual(cstate.extra["spindle_speed_maximum"], 1000.0)

        nodes = [
            NCCommandNode(g_code_command={"G0"}, command_parameter={"X": "100"}),
            NCCommandNode(
                g_code_command={"G1", "G96", "G99"},
                command_parameter={"Z": "-100", "S": "400", "F": "0.2"},
            ),
        ]
        canal.run_nc_code_list(nodes)

        _points, duration = canal.get_tool_path()[-1]
        self.assertAlmostEqual(duration, 30.0)

    def test_m3_and_m4_return_c_axis_to_zero_for_fanuc_turn_profiles(self):
        for machine_name in ("FANUC_TURN", "FANUC_STAR_x-D_y-R_z_R"):
            for m_code in ("3", "4"):
                with self.subTest(machine_name=machine_name, m_code=m_code):
                    cstate = CNCState(axes={"X": 0.0, "Y": 0.0, "Z": 0.0, "C": 90.0})
                    cstate.machine_config = get_machine_config(machine_name)
                    canal = UniversalConfigDrivenCanal("C1", init_state=cstate)

                    canal.run_nc_code_list([NCCommandNode(g_code_command=set(), command_parameter={"M": m_code})])

                    self.assertEqual(cstate.get_modal("spindle_direction"), f"M{m_code}")
                    self.assertEqual(cstate.get_axis("C"), 0.0)
                    points, _duration = canal.get_tool_path()[-1]
                    self.assertEqual(points[-1].c, 0.0)

    def test_fanuc_mill_m3_sets_spindle_without_moving_c_axis(self):
        cstate = CNCState(axes={"X": 0.0, "Y": 0.0, "Z": 0.0, "C": 90.0})
        cstate.machine_config = get_machine_config("FANUC_MILL")
        canal = UniversalConfigDrivenCanal("C1", init_state=cstate)

        canal.run_nc_code_list([NCCommandNode(command_parameter={"M": "03"})])

        self.assertEqual(cstate.get_modal("spindle_direction"), "M3")
        self.assertEqual(cstate.get_axis("C"), 0.0)
        self.assertEqual(canal.get_tool_path(), [])

    def test_fanuc_mill_coolant_codes_are_modal(self):
        cstate = CNCState(); cstate.machine_config = get_machine_config("FANUC_MILL")
        canal = UniversalConfigDrivenCanal("C1", init_state=cstate)

        canal.run_nc_code_list([
            NCCommandNode(command_parameter={"M": "8"}),
            NCCommandNode(command_parameter={"M": "9"}),
        ])

        self.assertEqual(cstate.get_modal("coolant_mode"), "M9")


if __name__ == '__main__':
    unittest.main()
