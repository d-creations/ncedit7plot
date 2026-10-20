import unittest
import re
from dataclasses import replace

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.fanuc_machine.tool_handler import FanucToolHandler
from ncplot7py.domain.handlers.siemens_machine.tool_handler import SiemensToolHandler
from ncplot7py.domain.handlers.star_machine.tool_handler import StarFanucToolHandler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.domain.machines import get_machine_config, get_machine_regex_patterns
from ncplot7py.shared.nc_nodes import NCCommandNode


class TestToolHandler(unittest.TestCase):
    def test_fanuc_mill_t_activates_tool(self):
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"))
        handler = FanucToolHandler()

        handler.handle(NCCommandNode(command_parameter={"T": "2"}), state)

        self.assertEqual(state.extra["active_tool_number"], 2)
        self.assertEqual(state.extra["current_tool_number"], 2)

    def test_siemens_named_tool_activates_tool(self):
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        handler = SiemensToolHandler()

        handler.handle(NCCommandNode(command_parameter={"T": '"CUTTER"'}), state)
        self.assertEqual(state.extra["active_tool_name"], "CUTTER")

    def test_tool_zero_unloads_active_tool(self):
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"))
        handler = FanucToolHandler()

        handler.handle(NCCommandNode(command_parameter={"T": "1"}), state)
        handler.handle(NCCommandNode(command_parameter={"T": "0"}), state)

        self.assertNotIn("active_tool_number", state.extra)

    def test_star_full_t_code_selects_the_full_tool_identifier(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))

        StarFanucToolHandler().handle(NCCommandNode(command_parameter={"T": "2500"}), state)

        self.assertEqual(state.extra["active_tool_number"], 2500)
        self.assertEqual(state.extra["current_tool_number"], 2500)
        self.assertEqual(state.extra["current_tool_code"], 2500)

    def test_star_short_t_code_selects_offset_for_the_active_tool(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        handler = StarFanucToolHandler()

        handler.handle(NCCommandNode(command_parameter={"T": "2500"}), state)
        handler.handle(NCCommandNode(command_parameter={"T": "25"}), state)

        self.assertEqual(state.extra["active_tool_number"], 2500)
        self.assertEqual(state.extra["active_offset_number"], 25)

    def test_star_tool_change_returns_b_and_y_to_zero(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        handler = StarFanucToolHandler()
        state.set_axis("B", 25.0)
        state.set_axis("Y", 12.0)

        handler.handle(NCCommandNode(command_parameter={"T": "2500"}), state)

        self.assertEqual(state.get_axis("B"), 0.0)
        self.assertEqual(state.get_axis("Y"), 0.0)

    def test_packed_tool_and_offsets_are_independent(self):
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
        handler = FanucToolHandler()
        for code, offset in [("0102", 2), ("0103", 3), ("02", 2), ("00", 0)]:
            handler.handle(NCCommandNode(command_parameter={"T": code}), state)
            self.assertEqual(state.extra["active_tool_number"], 1)
            self.assertEqual(state.extra["active_offset_number"], offset)

    def test_star_generated_tool_return_keeps_rapid_metadata(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        state.set_axis("Y", 12.0)
        node = NCCommandNode(command_parameter={"T": "200"})

        points, _ = StarFanucToolHandler(next_handler=MotionHandler()).handle(node, state)

        self.assertGreater(len(points), 1)
        self.assertEqual(node.motion_geometry, "LINEAR")
        self.assertEqual(node.motion_traversal, "RAPID")
        self.assertEqual(node.motion_source_code, "G00")
        self.assertEqual(state.get_axis("Y"), 0.0)

    def test_star_stationary_tool_selection_does_not_fabricate_motion_metadata(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        node = NCCommandNode(command_parameter={"T": "200"})

        StarFanucToolHandler(next_handler=MotionHandler()).handle(node, state)

        self.assertIsNone(node.motion_geometry)

    def test_star_generated_return_does_not_overwrite_authored_feed_metadata(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        state.set_axis("Y", 12.0)
        node = NCCommandNode(g_code_command={"G1"}, command_parameter={"T": "200", "X": "4"})

        StarFanucToolHandler(next_handler=MotionHandler()).handle(node, state)

        self.assertEqual(node.motion_traversal, "FEED")
        self.assertEqual(node.motion_source_code, "G01")

    def test_star_wear_command_does_not_change_tool_or_reset_axes(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        handler = StarFanucToolHandler()
        handler.handle(NCCommandNode(command_parameter={"T": "2500"}), state)
        state.set_axis("B", 25.0)
        state.set_axis("Y", 12.0)
        handler.handle(NCCommandNode(command_parameter={"T": "02"}), state)
        self.assertEqual(state.extra["active_tool_number"], 2500)
        self.assertEqual(state.extra["active_offset_number"], 2)
        self.assertEqual(state.get_axis("B"), 25.0)
        self.assertEqual(state.get_axis("Y"), 12.0)

    def test_star_full_tool_codes_keep_distinct_identity(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        for code in [3411, 3412]:
            StarFanucToolHandler().handle(NCCommandNode(command_parameter={"T": str(code)}), state)
            self.assertEqual(state.extra["active_tool_number"], code)

    def test_quoted_numeric_siemens_tool_is_a_name(self):
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        SiemensToolHandler().handle(NCCommandNode(command_parameter={"T": '"12"'}), state)
        self.assertEqual(state.extra["active_tool_name"], "12")

    def test_detection_patterns_follow_execution_policy(self):
        cases = {
            "FANUC_MILL": [("T0102", 102), ("T02", 2)],
            "SIEMENS_840DI": [("T0012", 12)],
            "FANUC_TURN": [("T0102", 1), ("T0100", 1), ("T02", None)],
            "FANUC_STAR_x-D_y-D_z_R.M.S": [
                ("T2500", 2500), ("T25", None), ("T3411", 3411),
                ("T3412", 3412), ("T0102", 102),
            ],
        }
        for machine, samples in cases.items():
            definition = get_machine_regex_patterns(machine)["tools"]
            self.assertEqual(set(definition), {"pattern", "description"})
            pattern = definition["pattern"]
            for code, expected in samples:
                with self.subTest(machine=machine, code=code):
                    match = re.search(pattern, code)
                    self.assertEqual(int(match[1]) if match else None, expected)

    def test_decoding_uses_policy_not_machine_name(self):
        config = replace(get_machine_config("FANUC_TURN"), name="BUILDER_CUSTOM", control_type="CUSTOM")
        state = CNCState(machine_config=config)
        FanucToolHandler().handle(NCCommandNode(command_parameter={"T": "0102"}), state)
        self.assertEqual(state.extra["active_tool_number"], 1)
        self.assertEqual(state.extra["active_offset_number"], 2)

    def test_tool_change_moves_to_configured_tool_change_position_with_tool_override(self):
        config = replace(
            get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"),
            tool_change_position={
                "default": {"X": 20.0, "Y": 0.0, "B": 0.0},
                "by_tool": {
                    "1100": {"X": 40.0, "Y": 5.0, "B": 0.0},
                },
            },
        )
        state = CNCState(machine_config=config)
        handler = StarFanucToolHandler(next_handler=MotionHandler())

        # T2500 uses the default tool_change_position (X=20 in diameter -> 10 radius, Y=0, B=0)
        handler.handle(NCCommandNode(command_parameter={"T": "2500"}), state)
        self.assertEqual(state.get_axis("X"), 10.0)
        self.assertEqual(state.get_axis("Y"), 0.0)
        self.assertEqual(state.get_axis("B"), 0.0)

        # T1100 uses the tool-specific override if not overridden by handler class
        custom_handler = FanucToolHandler(next_handler=MotionHandler())
        custom_handler.handle(NCCommandNode(command_parameter={"T": "1100"}), state)
        self.assertEqual(state.get_axis("X"), 20.0)
        self.assertEqual(state.get_axis("Y"), 2.5)

    def test_g28_moves_to_configured_home_position(self):
        from ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group0_coordinate_set import GCodeGroup0CoordinateSetExecChainLink

        config = replace(
            get_machine_config("FANUC_TURN"),
            home_position={"X": 50.0, "Y": 15.0, "Z": 100.0},
        )
        state = CNCState(machine_config=config)
        state.set_axis("X", 5.0)
        state.set_axis("Y", 3.0)
        state.set_axis("Z", -20.0)
        chain = GCodeGroup0CoordinateSetExecChainLink(next_handler=MotionHandler())

        # G28 U0 V0 W0 -> moves X, Y, Z to configured home_position (X is diameter mode -> 50/2 = 25)
        node = NCCommandNode(g_code_command={"G28"}, command_parameter={"U": "0", "V": "0", "W": "0"})
        points, _ = chain.handle(node, state)

        self.assertIsNotNone(points)
        self.assertEqual(state.get_axis("X"), 25.0)
        self.assertEqual(state.get_axis("Y"), 15.0)
        self.assertEqual(state.get_axis("Z"), 100.0)

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            replace(get_machine_config("FANUC_MILL"), tool_selection={"mode": "guess"})


if __name__ == "__main__":
    unittest.main()