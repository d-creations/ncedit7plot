import unittest

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.tool_compensation import load_tool_data
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl


class TestRadiusCompensationExecution(unittest.TestCase):
    def test_zero_radius_keeps_compensation_active_for_register_change(self):
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"), tool_path_mode="center")
        load_tool_data(state, [{"toolNumber": 1}], [
            {"offsetNumber": 2, "rValue": 0}, {"offsetNumber": 3, "rValue": 2},
        ])
        engine = NCExecutionEngine(UniversalConfigDrivenControl(init_nc_states=[state]))
        result = engine.get_Syncro_plot(["T1\nG17\nD2\nG41 G1 X10 Y0 F100\nD3 G1 X20 Y0"], synch=False)
        self.assertFalse(engine.errors)
        self.assertEqual(result[0]["plot"][0]["y"][-1], 0)
        self.assertEqual(result[0]["plot"][-1]["y"][-1], 2)

    def test_zero_radius_is_valid_for_milling_turning_and_swiss_profiles(self):
        for machine_name, selection, tool_id in (
            ("FANUC_MILL", "T1", 1),
            ("FANUC_TURN", "T0101", 1),
            ("FANUC_STAR_x-D_y-R_z_R", "T100\nT01", 1),
            ("SIEMENS_840DI", 'T="CUTTER"', "CUTTER"),
        ):
            for command in ("G41", "G42"):
                with self.subTest(machine=machine_name, command=command):
                    plot = self._execute(
                        machine_name,
                        selection + f"\nG17\n{command} G1 X10 Y0 F100\nG1 X20 Y0\nG40",
                        {tool_id: {"rValue": 0}}, "center",
                    )
                    self.assertTrue(plot)
                    self.assertEqual(plot[-1]["toolNumber"], tool_id)
                    self.assertEqual(plot[-1]["y"][-1], 0)

    def test_fanuc_entry_uses_next_executed_variable_motion(self):
        for machine_name, selection, endpoint in (
            ("FANUC_MILL", "T1", 10),
            ("FANUC_TURN", "T0101", 20),
            ("FANUC_STAR_x-D_y-R_z_R", "T100\nT01", 20),
        ):
            for command, expected_x in (("G41", 9), ("G42", 11)):
                with self.subTest(machine=machine_name, command=command):
                    plot = self._execute(
                        machine_name,
                        selection + f"\nG17\n#1=5\n{command} G1 X{endpoint} Y0 F100\n"
                        "#1=#1+5\nGOTO100\nG1 X0 Y-100\n"
                        f"N100 G1 X{endpoint} Y#1\nG40",
                        {1: {"rValue": 1.0, "qValue": 0}},
                        "center",
                    )
                    entry, contour = plot[-2:]
                    self.assertEqual((entry["x"][0], entry["y"][0]), (0, 0))
                    self.assertAlmostEqual(entry["x"][-1], expected_x)
                    self.assertAlmostEqual(entry["y"][-1], 0)
                    self.assertAlmostEqual(contour["x"][0], expected_x)
                    self.assertAlmostEqual(contour["y"][0], 0)
                    self.assertAlmostEqual(contour["y"][-1], 10)

    def test_fanuc_profiles_share_g17_compensation(self):
        for machine_name, selection, endpoint in (
            ("FANUC_MILL", "T1", 10),
            ("FANUC_TURN", "T0101", 20),
            ("FANUC_STAR_x-D_y-R_z_R", "T100\nT01", 20),
        ):
            with self.subTest(machine=machine_name):
                plot = self._execute(
                    machine_name,
                    selection + f"\nG17\nG41 G1 X{endpoint} Y0 F100\nG1 X{endpoint} Y10\nG40",
                    {1: {"rValue": 1.0, "qValue": 3}},
                    "center",
                )
                if machine_name.startswith("FANUC_STAR"):
                    self.assertEqual(len(plot), 3)
                    plot = plot[1:]
                self.assertEqual(len(plot), 2)
                self.assertAlmostEqual(plot[0]["x"][-1], 9.0)
                self.assertAlmostEqual(plot[0]["y"][-1], 1.0)
                self.assertAlmostEqual(plot[1]["x"][0], 9.0)
                self.assertAlmostEqual(plot[1]["y"][0], 1.0)

    def test_d_changes_radius_without_changing_tool_identity(self):
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"), tool_path_mode="center")
        load_tool_data(state, [{"toolNumber": 1}], [
            {"offsetNumber": 2, "rValue": 1},
            {"offsetNumber": 3, "rValue": 2},
        ])
        control = UniversalConfigDrivenControl(init_nc_states=[state])
        program = "T1\nG17\nD2\nG41 G1 X10 F100\nD3 G1 X20\nG40"
        plot = NCExecutionEngine(control).get_Syncro_plot([program], synch=False)[0]["plot"]
        self.assertEqual(len(plot), 2)
        self.assertEqual({entry["toolNumber"] for entry in plot}, {1})
        self.assertAlmostEqual(plot[0]["y"][0], 1)
        self.assertAlmostEqual(plot[1]["y"][-1], 2)

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

    def test_star_turn_q_value_changes_g18_center_path(self):
        program = "T100\nT01\nG18\nG41 G1 X20 Z0 F100\nG1 X20 Z10\nG40"
        q1_plot = self._execute(
            "FANUC_STAR_x-D_y-R_z_R",
            program,
            {1: {"rValue": 1.0, "qValue": 1}},
            "center",
        )
        q3_plot = self._execute(
            "FANUC_STAR_x-D_y-R_z_R",
            program,
            {1: {"rValue": 1.0, "qValue": 3}},
            "center",
        )

        self.assertNotEqual(q1_plot[-1]["x"], q3_plot[-1]["x"])
        self.assertNotEqual(q1_plot[-1]["z"], q3_plot[-1]["z"])
        self.assertAlmostEqual(q1_plot[-1]["x"][-1], 8.0)
        self.assertAlmostEqual(q1_plot[-1]["z"][-1], 9.0)
        self.assertAlmostEqual(q3_plot[-1]["x"][-1], 10.0)
        self.assertAlmostEqual(q3_plot[-1]["z"][-1], 11.0)


if __name__ == "__main__":
    unittest.main()