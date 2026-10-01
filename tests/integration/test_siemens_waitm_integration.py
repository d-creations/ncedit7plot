import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared import configure_logging, configure_i18n


class TestSiemensWaitmIntegration(unittest.TestCase):
    """Integration test verifying Siemens WAITM() wait-code command parsing and handling."""

    def setUp(self):
        configure_logging(console=False, web_buffer=True)
        configure_i18n()

    def test_siemens_waitm_execution_and_metadata(self):
        """Test multi-channel Siemens program using WAITM(marker, ch1, ch2)."""
        config = get_machine_config("SIEMENS_840DI")

        prog_ch1 = """
        G90 G0 X10 Y20 Z5
        WAITM(1, 1, 2)
        G1 X50 Y50 F1000
        WAITM(2, 1, 2)
        M30
        """

        prog_ch2 = """
        G90 G0 X0 Y0 Z10
        WAITM(1, 1, 2)
        G1 X20 Y20 F500
        WAITM(2, 1, 2)
        M30
        """

        control = UniversalConfigDrivenControl(
            count_of_canals=2,
            init_nc_states=[CNCState(machine_config=config), CNCState(machine_config=config)],
        )
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot([prog_ch1, prog_ch2], synch=False)

        # 1. Verification of execution
        self.assertEqual(len(engine.errors), 0, f"Execution errors: {engine.errors}")
        self.assertEqual(len(result), 2)
        for ch in result:
            self.assertIn("plot", ch)
            self.assertGreater(len(ch["plot"]), 0)

        # 2. Verify WAITM was recognized by WaitCodeHandler on executed nodes
        nodes_ch1 = control.get_exected_nodes(1)
        nodes_ch2 = control.get_exected_nodes(2)

        wait_markers_ch1 = [
            node.extra["wait_code"]["marker"]
            for node in nodes_ch1
            if hasattr(node, "extra") and "wait_code" in node.extra and node.extra["wait_code"]["type"] == "SIEMENS_WAIT"
        ]
        wait_markers_ch2 = [
            node.extra["wait_code"]["marker"]
            for node in nodes_ch2
            if hasattr(node, "extra") and "wait_code" in node.extra and node.extra["wait_code"]["type"] == "SIEMENS_WAIT"
        ]

        self.assertEqual(wait_markers_ch1, [1, 2])
        self.assertEqual(wait_markers_ch2, [1, 2])


if __name__ == "__main__":
    unittest.main()
