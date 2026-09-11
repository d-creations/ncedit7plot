import unittest

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl


class TestRadiusCompensationExecution(unittest.TestCase):
    def _execute(self, machine_name, program, tool_values, mode):
        state = CNCState(
            machine_config=get_machine_config(machine_name),
            tool_path_mode=mode,
        )
        state.extra["tool_compensation_data"] = tool_values
        control = UniversalConfigDrivenControl(init_nc_states=[state])
        return NCExecutionEngine(control).get_Syncro_plot([program], synch=False)[0]["plot"]

    def test_fanuc_center_mode_offsets_and_joins_g41_lines(self):
        plot = self._execute(
            "FANUC_MILL",
            "T1\nG17\nG41 G1 X10 Y0 F100\nG1 X10 Y10\nG40",
            {1: {"rValue": 1.0, "qValue": 3}},
            "center",
        )

        self.assertEqual(len(plot), 2)
        self.assertAlmostEqual(plot[0]["y"][0], 1.0)
        self.assertAlmostEqual(plot[0]["x"][-1], 9.0)
        self.assertAlmostEqual(plot[0]["y"][-1], 1.0)
        self.assertAlmostEqual(plot[1]["x"][0], 9.0)
        self.assertAlmostEqual(plot[1]["y"][0], 1.0)
        self.assertEqual({entry["toolNumber"] for entry in plot}, {1})

    def test_fanuc_effective_mode_keeps_programmed_lines(self):
        plot = self._execute(
            "FANUC_MILL",
            "T1\nG17\nG41 G1 X10 Y0 F100\nG1 X10 Y10\nG40",
            {1: {"rValue": 1.0}},
            "effective",
        )

        self.assertAlmostEqual(plot[0]["y"][0], 0.0)
        self.assertAlmostEqual(plot[0]["x"][-1], 10.0)
        self.assertAlmostEqual(plot[0]["y"][-1], 0.0)

    def test_siemens_named_tool_uses_same_center_path_projector(self):
        plot = self._execute(
            "SIEMENS_840DI",
            'T="CUTTER"\nG17\nG42 G1 X10 Y0 F100\nG40',
            {"CUTTER": {"rValue": 2.0}},
            "center",
        )

        self.assertEqual(len(plot), 1)
        self.assertEqual(plot[0]["toolNumber"], "CUTTER")
        self.assertAlmostEqual(plot[0]["y"][0], -2.0)
        self.assertAlmostEqual(plot[0]["y"][-1], -2.0)

    def test_siemens_numeric_tool_g41_joins_corner_and_g40_cancels(self):
        plot = self._execute(
            "SIEMENS_840DI",
            "T2\nG17\nG41 G1 X10 Y0 F100\nG1 X10 Y10\nG40 G1 X20 Y10",
            {2: {"rValue": 1.0}},
            "center",
        )

        self.assertEqual(len(plot), 3)
        self.assertAlmostEqual(plot[0]["x"][-1], 9.0)
        self.assertAlmostEqual(plot[0]["y"][-1], 1.0)
        self.assertAlmostEqual(plot[1]["x"][0], 9.0)
        self.assertAlmostEqual(plot[1]["y"][0], 1.0)
        self.assertAlmostEqual(plot[2]["y"][0], 10.0)
        self.assertAlmostEqual(plot[2]["y"][-1], 10.0)
        self.assertEqual({entry["toolNumber"] for entry in plot}, {2})


if __name__ == "__main__":
    unittest.main()