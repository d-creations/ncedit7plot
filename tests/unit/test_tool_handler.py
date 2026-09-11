import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.fanuc_machine.tool_handler import FanucToolHandler
from ncplot7py.domain.handlers.siemens_machine.tool_handler import SiemensToolHandler
from ncplot7py.domain.handlers.star_machine.tool_handler import StarFanucToolHandler
from ncplot7py.domain.machines import get_machine_config
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
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
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


if __name__ == "__main__":
    unittest.main()