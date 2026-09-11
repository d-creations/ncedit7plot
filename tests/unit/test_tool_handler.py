import unittest
import re
from dataclasses import replace

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.fanuc_machine.tool_handler import FanucToolHandler
from ncplot7py.domain.handlers.siemens_machine.tool_handler import SiemensToolHandler
from ncplot7py.domain.handlers.star_machine.tool_handler import StarFanucToolHandler
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

    def test_star_t0400_uses_tool_four(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))

        StarFanucToolHandler().handle(NCCommandNode(command_parameter={"T": "0400"}), state)

        self.assertEqual(state.extra["active_tool_number"], 4)
        self.assertEqual(state.extra["current_tool_number"], 4)
        self.assertEqual(state.extra["current_tool_code"], 400)

    def test_star_t400_is_interpreted_as_tool_four_with_offset_zero(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))

        StarFanucToolHandler().handle(NCCommandNode(command_parameter={"T": "400"}), state)

        self.assertEqual(state.extra["current_tool_number"], 4)

    def test_packed_tool_and_offsets_are_independent(self):
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
        handler = FanucToolHandler()
        for code, offset in [("0102", 2), ("0103", 3), ("02", 2), ("00", 0)]:
            handler.handle(NCCommandNode(command_parameter={"T": code}), state)
            self.assertEqual(state.extra["active_tool_number"], 1)
            self.assertEqual(state.extra["active_offset_number"], offset)

    def test_star_wear_command_does_not_change_tool_or_reset_b(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-D_z_R.M.S"))
        handler = StarFanucToolHandler()
        handler.handle(NCCommandNode(command_parameter={"T": "400"}), state)
        state.set_axis("B", 25.0)
        handler.handle(NCCommandNode(command_parameter={"T": "02"}), state)
        self.assertEqual(state.extra["active_tool_number"], 4)
        self.assertEqual(state.extra["active_offset_number"], 2)
        self.assertEqual(state.get_axis("B"), 25.0)

    def test_star_subtools_keep_distinct_identity(self):
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
                ("T400", 4), ("T02", None), ("T3411", 3411),
                ("T3412", 3412), ("T0102", None),
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

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            replace(get_machine_config("FANUC_MILL"), tool_selection={"mode": "guess"})


if __name__ == "__main__":
    unittest.main()