import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionNode
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.machines import MachineConfig
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenCanal
from ncplot7py.shared.nc_nodes import NCCommandNode


class TestFanucThreadingCycles(unittest.TestCase):
    def _canal(self, machine="FANUC_TURN"):
        state = CNCState(
            axes={"X": 10.0, "Y": 0.0, "Z": 0.0, "C": 0.0},
            machine_config=get_machine_config(machine),
        )
        state.spindle_speed = 1000.0
        return state, UniversalConfigDrivenCanal("C1", init_state=state)

    @staticmethod
    def _all_points(canal):
        return [point for points, _duration in canal.get_tool_path() for point in points]

    def test_g92_expands_four_operations_and_returns_to_start(self):
        state, canal = self._canal()
        canal.run_nc_code_list([
            NCCommandNode(
                g_code_command={"G92"},
                command_parameter={"X": "16", "Z": "-10", "F": "2", "Q": "90000"},
                nc_code_line_nr=10,
            )
        ])

        points = self._all_points(canal)
        self.assertAlmostEqual(min(point.x for point in points), 8.0)
        self.assertAlmostEqual(min(point.z for point in points), -10.0)
        self.assertAlmostEqual(state.get_axis("X"), 10.0)
        self.assertAlmostEqual(state.get_axis("Z"), 0.0)
        self.assertEqual(state.extra["fanuc.threading.start_angle"], 90.0)
        nodes = canal.get_exec_nodes()
        self.assertEqual([node.motion_traversal for node in nodes], ["RAPID", "FEED", "RAPID", "RAPID"])
        self.assertEqual(nodes[1].motion_source_code, "G92")
        self.assertEqual({node.motion_geometry for node in nodes}, {"LINEAR"})
        self.assertEqual(nodes[1].motion_context["machiningMode"], "threading")
        self.assertEqual(nodes[1].motion_context["threading"], {"lead": 2.0, "startAngleDeg": 90.0})
        self.assertNotIn("threading", nodes[0].motion_context)
        self.assertNotEqual(nodes[0].motion_context["machiningMode"], "threading")

    def test_g92_is_modal_for_additional_depths(self):
        state, canal = self._canal()
        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G92"}, command_parameter={"X": "16", "Z": "-8", "F": "2"}),
            NCCommandNode(command_parameter={"X": "14"}),
        ])

        self.assertAlmostEqual(min(point.x for point in self._all_points(canal)), 7.0)
        self.assertAlmostEqual(state.get_axis("X"), 10.0)
        self.assertEqual(len(canal.get_tool_path()), 8)

    def test_g76_builds_rough_and_finishing_passes(self):
        state, canal = self._canal()
        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G76"}, command_parameter={"P": "011060", "Q": "100", "R": "200"}),
            NCCommandNode(
                g_code_command={"G76"},
                command_parameter={"X": "16", "Z": "-10", "P": "2000", "Q": "500", "F": "2"},
                nc_code_line_nr=20,
            ),
        ])

        depths = state.extra["fanuc.g76.pass_depths"]
        self.assertAlmostEqual(state.extra["fanuc.g76.setup"]["finishing_allowance"], 0.2)
        self.assertGreater(len(depths), 2)
        self.assertAlmostEqual(depths[-1], 2.0)
        self.assertAlmostEqual(state.get_axis("X"), 10.0)
        self.assertAlmostEqual(state.get_axis("Z"), 0.0)
        nodes = canal.get_exec_nodes()
        self.assertEqual(len(nodes), len(depths) * 4)
        self.assertEqual({node.motion_geometry for node in nodes}, {"LINEAR"})
        self.assertEqual({node.motion_traversal for node in nodes}, {"RAPID", "FEED"})
        self.assertEqual({node.motion_source_code for node in nodes}, {"G00", "G76"})
        self.assertEqual({node.nc_code_line_nr for node in nodes}, {20})
        feed_nodes = [node for node in nodes if node.motion_traversal == "FEED"]
        self.assertEqual(len(feed_nodes), len(depths))
        self.assertTrue(all(node.motion_context["machiningMode"] == "threading" for node in feed_nodes))
        self.assertTrue(all(node.motion_context["threading"] == {"lead": 2.0, "startAngleDeg": 0.0} for node in feed_nodes))

    def test_g76_requires_setup_block(self):
        _state, canal = self._canal()
        with self.assertRaises(ExceptionNode) as error:
            canal.run_nc_code_list([
                NCCommandNode(
                    g_code_command={"G76"},
                    command_parameter={"X": "16", "Z": "-10", "P": "2000", "Q": "500", "F": "2"},
                )
            ])
        self.assertEqual(error.exception.code, 763)

    def test_g76_rejects_decimal_depth_fields(self):
        _state, canal = self._canal()
        with self.assertRaises(ExceptionNode) as error:
            canal.run_nc_code_list([
                NCCommandNode(g_code_command={"G76"}, command_parameter={"P": "011060", "Q": "0.1", "R": "0.2"})
            ])
        self.assertEqual(error.exception.code, 769)

    def test_g36_generates_ccw_thread_arc_with_feed_semantics(self):
        state, canal = self._canal("FANUC_STAR_x-D_y-R_z_R")
        canal.run_nc_code_list([
            NCCommandNode(
                g_code_command={"G36"},
                command_parameter={"X": "16", "Z": "-4", "R": "5", "F": "2"},
                nc_code_line_nr=30,
            )
        ])

        self.assertAlmostEqual(state.get_axis("X"), 8.0)
        self.assertAlmostEqual(state.get_axis("Z"), -4.0)
        node = canal.get_exec_nodes()[0]
        self.assertEqual(node.motion_geometry, "ARC_CCW")
        self.assertEqual(node.motion_traversal, "FEED")
        self.assertEqual(node.motion_source_code, "G36")
        self.assertEqual(node.motion_context["machiningMode"], "threading")
        self.assertEqual(node.motion_context["threading"], {"lead": 2.0, "startAngleDeg": 0.0})
        self.assertGreater(len(canal.get_tool_path()[0][0]), 2)

    def test_g36_requires_machine_option(self):
        config = MachineConfig(
            name="TURN_WITHOUT_G36",
            control_type="FANUC",
            variable_pattern=r"#(\d+)",
            variable_prefix="#",
            tool_range=(0, 9999),
            machine_type="TURN",
            supported_gcode_groups=("fanuc_g36_circular_threading", "motion"),
        )
        state = CNCState(machine_config=config)
        state.spindle_speed = 1000.0
        canal = UniversalConfigDrivenCanal("C1", init_state=state)

        with self.assertRaises(ExceptionNode) as error:
            canal.run_nc_code_list([
                NCCommandNode(
                    g_code_command={"G36"},
                    command_parameter={"X": "8", "Z": "-4", "R": "5", "F": "2"},
                )
            ])
        self.assertEqual(error.exception.code, 360)

    def test_threading_command_cancels_drilling_cycle(self):
        state, canal = self._canal()
        state.extra["fanuc_turn_drilling_cycle"] = {"code": "G83"}
        state.set_modal("drilling_cycle", "G83")

        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G92"}, command_parameter={"X": "16", "Z": "-8", "F": "2"})
        ])

        self.assertNotIn("fanuc_turn_drilling_cycle", state.extra)
        self.assertIsNone(state.get_modal("drilling_cycle"))


if __name__ == "__main__":
    unittest.main()