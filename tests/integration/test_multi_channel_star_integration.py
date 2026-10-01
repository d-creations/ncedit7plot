import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared import configure_logging, configure_i18n


class TestMultiChannelStarIntegration(unittest.TestCase):
    """End-to-end integration test running multi-channel NC programs on a multi-axis Star lathe."""

    def setUp(self):
        configure_logging(console=False, web_buffer=True)
        configure_i18n()

    def test_multi_channel_axis_binding_and_wait_sync(self):
        """Test full program flow with 2 channels:
        - Logical axis mapping (X->X1, X->X2, C->C1, C->C2, B->B1)
        - Dynamic axis switching via M171/M172
        - Explicit axis syntax (e.g. Z3=...)
        - Wait-code synchronization (M300, M500 with P12)
        - Shared machine state (physical axes and common variables #500+)
        """
        config = get_machine_config("FANUC_STAR_SR20R_IV_B")

        # Two-channel NC programs
        # Channel 1:
        # - Sets common parameter #501=12.5
        # - Moves X, Z, C, B in Channel 1 (X1, Z1, C1, B1)
        # - Reaches barrier M300
        # - Switches to sub-spindle coordinate mode with M171 (X -> X2, C -> C2)
        # - Moves X and C
        # - Switches back with M172
        # - Reaches barrier M500 P12
        prog_ch1 = """
        G98;
        #501 = 12.5;
        G0 X20.0 Z10.0 C90.0 B30.0;
        M300;
        M171;
        G0 X14.0 C180.0;
        M172;
        G0 X30.0;
        M500 P12;
        """

        # Channel 2:
        # - Moves X, Z, C in Channel 2 (X2, Z2, C2)
        # - Reaches barrier M300
        # - Also executes M171 wait-code barrier with Ch1
        # - Reads common parameter #502 = #501 * 2
        # - Performs motion
        # - Reaches barrier M172 with Ch1
        # - Reaches barrier M500 P12
        prog_ch2 = """
        G98;
        G0 X10.0 Z5.0 C45.0;
        M300;
        M171;
        #502 = #501 * 2;
        G0 X8.0 Z15.0;
        M172;
        M500 P12;
        """

        control = UniversalConfigDrivenControl(
            count_of_canals=2,
            init_nc_states=[CNCState(machine_config=config), CNCState(machine_config=config)],
        )
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot([prog_ch1, prog_ch2], synch=True)

        # 1. Verification of execution results
        self.assertEqual(len(engine.errors), 0, f"Execution had errors: {engine.errors}")
        self.assertEqual(len(result), 2)
        for ch_res in result:
            self.assertIn("plot", ch_res)
            self.assertGreater(len(ch_res["plot"]), 0)

        # 2. Shared MachineState verification
        state1 = control.get_nc_state(1)
        state2 = control.get_nc_state(2)

        self.assertIsNotNone(state1)
        self.assertIsNotNone(state2)
        self.assertIs(state1.machine_state, state2.machine_state)

        # Common global parameter #501 written by Ch1 and #502 computed by Ch2
        self.assertAlmostEqual(state1.get_parameter(501), 12.5)
        self.assertAlmostEqual(state2.get_parameter(501), 12.5)
        self.assertAlmostEqual(state1.get_parameter(502), 25.0)
        self.assertAlmostEqual(state2.get_parameter(502), 25.0)

        # Verify physical axes on the shared machine state:
        # Ch1 moved B to 30.0 -> maps to B1
        self.assertAlmostEqual(state1.get_axis("B1"), 30.0)
        self.assertAlmostEqual(state2.get_axis("B1"), 30.0)

        # Ch1 M172 final motion was X30.0 (diameter 30.0 -> radius 15.0)
        self.assertAlmostEqual(state1.get_axis("X1"), 15.0)

        # Ch1 M171 moved X14.0 -> mapped to X2 (diameter 14.0 -> radius 7.0)
        # Ch2 then moved X8.0 -> mapped to X2 (diameter 8.0 -> radius 4.0)
        self.assertAlmostEqual(state2.get_axis("X2"), 4.0)

        # 3. WaitCodeHandler verification on executed nodes
        exec_nodes_ch1 = control.get_exected_nodes(1)
        exec_nodes_ch2 = control.get_exected_nodes(2)

        wait_nodes_ch1 = [
            node.extra.get("wait_code")
            for node in exec_nodes_ch1
            if hasattr(node, "extra") and "wait_code" in node.extra
        ]
        self.assertTrue(any(w["code"] == 300 for w in wait_nodes_ch1))
        self.assertTrue(any(w["code"] == 500 and w["p"] == 12 for w in wait_nodes_ch1))

        wait_nodes_ch2 = [
            node.extra.get("wait_code")
            for node in exec_nodes_ch2
            if hasattr(node, "extra") and "wait_code" in node.extra
        ]
        self.assertTrue(any(w["code"] == 300 for w in wait_nodes_ch2))
        self.assertTrue(any(w["code"] == 500 and w["p"] == 12 for w in wait_nodes_ch2))


if __name__ == "__main__":
    unittest.main()
