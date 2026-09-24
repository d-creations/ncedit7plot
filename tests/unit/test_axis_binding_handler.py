import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.handlers.axis_binding import AxisBindingHandler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenCanal
from ncplot7py.shared.nc_nodes import NCCommandNode


class TestAxisBindingHandler(unittest.TestCase):
    def test_channel_1_default_axis_mapping(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        state.extra["path_number"] = 1
        canal = UniversalConfigDrivenCanal("C1", init_state=state)

        self.assertEqual(state.extra["axis_map"]["X"], "X1")
        self.assertEqual(state.extra["axis_map"]["Y"], "Y1")
        self.assertEqual(state.extra["axis_map"]["Z"], "Z1")
        self.assertEqual(state.extra["axis_map"]["B"], "B1")
        self.assertEqual(state.extra["axis_map"]["C"], "C1")
        self.assertEqual(state.extra["target_carriers"]["B"], "tiltingToolUnit")
        self.assertEqual(state.extra["target_carriers"]["C"], "mainSpindle")

    def test_channel_2_default_axis_mapping(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        state.extra["path_number"] = 2
        canal = UniversalConfigDrivenCanal("C2", init_state=state)

        self.assertEqual(state.extra["axis_map"]["X"], "X2")
        self.assertEqual(state.extra["axis_map"]["Y"], "Y2")
        self.assertEqual(state.extra["axis_map"]["Z"], "Z2")
        self.assertEqual(state.extra["axis_map"]["C"], "C2")
        self.assertEqual(state.extra["target_carriers"]["C"], "subSpindle")

    def test_channel_3_default_axis_mapping_on_sv20r(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SV20R"))
        state.extra["path_number"] = 3
        canal = UniversalConfigDrivenCanal("C3", init_state=state)

        self.assertEqual(state.extra["axis_map"]["X"], "X3")
        self.assertEqual(state.extra["axis_map"]["Y"], "Y3")
        self.assertEqual(state.extra["axis_map"]["Z"], "Z3")

    def test_mcode_override_switches_axis_and_carrier(self):
        handler = AxisBindingHandler()
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        state.extra["path_number"] = 1
        AxisBindingHandler.apply_bindings(state)

        self.assertEqual(state.extra["axis_map"]["C"], "C1")
        self.assertEqual(state.extra["star.targetAxis"], "C1")

        # Command M171 override
        node = NCCommandNode(command_parameter={"M": "171"})
        handler.handle(node, state)

        self.assertEqual(state.extra["axis_map"]["C"], "C2")
        self.assertEqual(state.extra["target_carriers"]["C"], "subSpindle")
        self.assertEqual(state.extra["star.targetAxis"], "C2")
        self.assertEqual(state.extra["star.targetCarrierId"], "subSpindle")
        self.assertEqual(state.extra["star.path_mode"], "M171")

        # Command M172 override back
        node = NCCommandNode(command_parameter={"M": "172"})
        handler.handle(node, state)

        self.assertEqual(state.extra["axis_map"]["C"], "C1")
        self.assertEqual(state.extra["target_carriers"]["C"], "mainSpindle")
        self.assertEqual(state.extra["star.targetAxis"], "C1")
        self.assertEqual(state.extra["star.targetCarrierId"], "mainSpindle")
        self.assertEqual(state.extra["star.path_mode"], "M172")

    def test_channel_motions_update_corresponding_physical_axes(self):
        # Channel 1: G0 X20.0 Z10.0 C90.0
        state1 = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        canal1 = UniversalConfigDrivenCanal("C1", init_state=state1)
        canal1.run_nc_code_list([
            NCCommandNode(g_code_command={"G0"}, command_parameter={"X": "20.0", "Z": "10.0", "C": "90.0"})
        ])

        # Note: X1 is a diameter axis, so radius is 10.0
        self.assertAlmostEqual(state1.get_axis("X1"), 10.0)
        self.assertAlmostEqual(state1.get_axis("Z1"), 10.0)
        self.assertAlmostEqual(state1.get_axis("C1"), 90.0)

        # Channel 2: G0 X10.0 Z5.0 C45.0
        state2 = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        canal2 = UniversalConfigDrivenCanal("C2", init_state=state2)
        canal2.run_nc_code_list([
            NCCommandNode(g_code_command={"G0"}, command_parameter={"X": "10.0", "Z": "5.0", "C": "45.0"})
        ])

        self.assertAlmostEqual(state2.get_axis("X2"), 5.0)
        self.assertAlmostEqual(state2.get_axis("Z2"), 5.0)
        self.assertAlmostEqual(state2.get_axis("C2"), 45.0)

    def test_b_axis_mapping_to_b1_in_channel_1(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        canal = UniversalConfigDrivenCanal("C1", init_state=state)
        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G0"}, command_parameter={"B": "30.0"})
        ])

        self.assertAlmostEqual(state.get_axis("B1"), 30.0)
        self.assertAlmostEqual(state.get_axis("B"), 30.0)


if __name__ == "__main__":
    unittest.main()
