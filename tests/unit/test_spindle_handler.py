import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.handlers.star_machine.spindle_handler import StarSpindleHandler
from ncplot7py.domain.handlers.fanuc_turn_cnc.spindle_handler import FanucTurnSpindleHandler
from ncplot7py.domain.handlers.fanuc_mill_cnc.mcode_modal import FanucMillModalMCodeHandler
from ncplot7py.domain.handlers.siemens_mill_cnc.mcode_modal import SiemensMillModalMCodeHandler
from ncplot7py.shared.nc_nodes import NCCommandNode


class TestSpindleHandler(unittest.TestCase):
    def test_cnc_state_initial_machining_mode_is_unknown(self):
        state = CNCState()
        self.assertEqual(state.get_machining_mode(), "unknown")
        self.assertEqual(state.machining_mode, "unknown")
        self.assertEqual(state.spindle_state, {})

    def test_star_spindle_turning_and_milling_modes(self):
        handler = StarSpindleHandler()
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))

        # Initially unknown
        self.assertEqual(state.get_machining_mode(), "unknown")

        # M3 turning spindle start
        handler.handle(NCCommandNode(command_parameter={"M": "3", "S": "2000"}), state)
        self.assertEqual(state.get_machining_mode(), "turning")
        self.assertEqual(state.get_modal("spindle_direction"), "M3")
        self.assertEqual(state.spindle_speed, 2000.0)
        self.assertEqual(state.spindle_state["main"]["direction"], "M3")
        self.assertTrue(state.spindle_state["main"]["active"])

        # M5 spindle stop -> mode remains turning until mode-switch
        handler.handle(NCCommandNode(command_parameter={"M": "5"}), state)
        self.assertEqual(state.get_machining_mode(), "turning")
        self.assertFalse(state.spindle_state["main"]["active"])

        # M36 power-driven milling tool start
        handler.handle(NCCommandNode(command_parameter={"M": "36", "S": "4000"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")
        self.assertEqual(state.spindle_state["PowerDrivenTools"]["direction"], "M36")
        self.assertEqual(state.spindle_state["PowerDrivenTools"]["tool"], "PowerDrivenTool1")
        self.assertTrue(state.spindle_state["PowerDrivenTools"]["active"])

        # M38 power-driven tool stop
        handler.handle(NCCommandNode(command_parameter={"M": "38"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")
        self.assertFalse(state.spindle_state["PowerDrivenTools"]["active"])

        # Switch back to turning with M4
        handler.handle(NCCommandNode(command_parameter={"M": "4", "S": "1500"}), state)
        self.assertEqual(state.get_machining_mode(), "turning")
        self.assertEqual(state.get_modal("spindle_direction"), "M4")
        self.assertTrue(state.spindle_state["main"]["active"])

    def test_star_spindle_path2_power_driven_tools(self):
        handler = StarSpindleHandler()
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))

        # M56 power-driven tool on PATH2
        handler.handle(NCCommandNode(command_parameter={"M": "56", "S": "5000"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")
        self.assertEqual(state.spindle_state["PowerDrivenTools"]["direction"], "M56")
        self.assertEqual(state.spindle_state["PowerDrivenTools"]["tool"], "PowerDrivenTool3")
        self.assertTrue(state.spindle_state["PowerDrivenTools"]["active"])

        # M58 stop
        handler.handle(NCCommandNode(command_parameter={"M": "58"}), state)
        self.assertFalse(state.spindle_state["PowerDrivenTools"]["active"])

        # M46 / M47 / M48
        handler.handle(NCCommandNode(command_parameter={"M": "47", "S": "3500"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")
        self.assertEqual(state.spindle_state["PowerDrivenTools"]["direction"], "M47")
        self.assertEqual(state.spindle_state["PowerDrivenTools"]["tool"], "PowerDrivenTool2")
        self.assertTrue(state.spindle_state["PowerDrivenTools"]["active"])
        handler.handle(NCCommandNode(command_parameter={"M": "48"}), state)
        self.assertFalse(state.spindle_state["PowerDrivenTools"]["active"])

    def test_fanuc_turn_spindle_turning_and_m5_milling(self):
        handler = FanucTurnSpindleHandler()
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))

        # Initially unknown
        self.assertEqual(state.get_machining_mode(), "unknown")

        # M3 -> turning
        handler.handle(NCCommandNode(command_parameter={"M": "3", "S": "1200"}), state)
        self.assertEqual(state.get_machining_mode(), "turning")
        self.assertTrue(state.spindle_state["main"]["active"])

        # M5 -> stops turning spindle, subsequent mode is milling
        handler.handle(NCCommandNode(command_parameter={"M": "5"}), state)
        self.assertFalse(state.spindle_state["main"]["active"])
        self.assertEqual(state.get_machining_mode(), "milling")

        # M3 -> switches back to turning
        handler.handle(NCCommandNode(command_parameter={"M": "3"}), state)
        self.assertEqual(state.get_machining_mode(), "turning")
        self.assertTrue(state.spindle_state["main"]["active"])

    def test_fanuc_mill_m3_m4_m5_is_always_milling(self):
        handler = FanucMillModalMCodeHandler()
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"))

        self.assertEqual(state.get_machining_mode(), "unknown")

        handler.handle(NCCommandNode(command_parameter={"M": "3", "S": "6000"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")

        handler.handle(NCCommandNode(command_parameter={"M": "5"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")

        handler.handle(NCCommandNode(command_parameter={"M": "4"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")

    def test_siemens_mill_m3_m4_m5_is_always_milling(self):
        handler = SiemensMillModalMCodeHandler()
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))

        self.assertEqual(state.get_machining_mode(), "unknown")

        handler.handle(NCCommandNode(command_parameter={"M": "3", "S": "8000"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")

        handler.handle(NCCommandNode(command_parameter={"M": "5"}), state)
        self.assertEqual(state.get_machining_mode(), "milling")
