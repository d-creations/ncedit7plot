import unittest
import re
from unittest.mock import mock_open, patch

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain import machines
from ncplot7py.domain.handlers.fanuc_mill_cnc.gcode_speed_mode import FanucMillSpeedModeHandler
from ncplot7py.domain.handlers.fanuc_turn_cnc.gcode_group2_speed_mode import FanucTurnSpeedModeHandler
from ncplot7py.domain.handlers.siemens_mill_cnc.speed_handler import SiemensISOSpeedHandler
from ncplot7py.domain.machines import MachineConfig, get_machine_config, get_machine_regex_patterns
from ncplot7py.infrastructure.machines.base_stateful_control import HANDLER_REGISTRY, UniversalConfigDrivenCanal


class TestMachineSetup(unittest.TestCase):
    def setUp(self):
        self._machine_configs = machines.MACHINE_CONFIGS.copy()

    def tearDown(self):
        machines.MACHINE_CONFIGS = self._machine_configs

    def test_unknown_machine_name_falls_back_to_generic_config(self):
        config = get_machine_config("DOES_NOT_EXIST")

        self.assertEqual(config.name, "FANUC_MILL")

    def test_cnc_state_defaults_to_generic_machine_config(self):
        state = CNCState()

        self.assertEqual(state.machine_config.name, "FANUC_MILL")

    def test_initial_plane_comes_from_machine_default_plane(self):
        custom_turn_mill = MachineConfig(
            name="TEST_TURN_MILL_G19",
            control_type="FANUC",
            variable_pattern=r'#(\d+)',
            variable_prefix='#',
            tool_range=(0, 99),
            machine_type="TURN_MILL",
            default_plane="G19",
            supported_gcode_groups=("motion",),
        )
        state = CNCState(machine_config=custom_turn_mill)

        canal = UniversalConfigDrivenCanal("C1", init_state=state)

        self.assertEqual(canal._state.extra["g_group_16_plane"], "Y_Z")

    def test_machine_config_can_define_rapid_feed_rate(self):
        custom_turn = MachineConfig(
            name="TEST_TURN_RAPID",
            control_type="FANUC",
            variable_pattern=r'#(\d+)',
            variable_prefix='#',
            parser_name="fanuc",
            tool_range=(0, 99),
            machine_type="TURN",
            supported_gcode_groups=("motion",),
            rapid_feed_rate=1200.0,
        )

        self.assertEqual(custom_turn.rapid_feed_rate, 1200.0)

    def test_fanuc_and_siemens_define_g96_reference_axis(self):
        for machine_name in ["FANUC_TURN", "FANUC_MILL", "SIEMENS_840DI"]:
            with self.subTest(machine=machine_name):
                self.assertEqual(get_machine_config(machine_name).g96_reference_axis, "X")

    def test_load_machine_configs_prefers_package_local_config(self):
        mocked_open = mock_open(read_data='{}')

        with patch("ncplot7py.domain.machines.files", side_effect=FileNotFoundError), patch(
            "ncplot7py.domain.machines.os.path.exists", return_value=True
        ), patch(
            "builtins.open", mocked_open
        ):
            machines.load_machine_configs()

        package_config_path = machines.os.path.join(
            machines.os.path.dirname(machines.__file__), '..', 'config', 'machines.json'
        )
        mocked_open.assert_called_once_with(package_config_path, 'r', encoding='utf-8')

    def test_load_machine_configs_falls_back_to_legacy_config(self):
        mocked_open = mock_open(read_data='{}')

        with patch("ncplot7py.domain.machines.files", side_effect=FileNotFoundError), patch(
            "ncplot7py.domain.machines.os.path.exists", return_value=False
        ), patch(
            "builtins.open", mocked_open
        ):
            machines.load_machine_configs()

        legacy_config_path = machines.os.path.join(
            machines.os.path.dirname(machines.__file__), '..', '..', '..', 'config', 'machines.json'
        )
        mocked_open.assert_called_once_with(legacy_config_path, 'r', encoding='utf-8')

    def test_star_machine_group_aliases_are_registered(self):
        self.assertEqual(
            HANDLER_REGISTRY["spindle_speed"],
            ("ncplot7py.domain.handlers.modal", "ModalHandler"),
        )

    def test_star_m_s_machine_configs_define_channel_extensions_and_diameter_axes(self):
        cases = [
            ("FANUC_STAR_x-D_y-R_z_R.M.S", ("X",)),
            ("FANUC_STAR_x-D_y-D_z_R.M.S", ("X", "Y")),
        ]

        for machine_name, expected_diameter_axes in cases:
            with self.subTest(machine=machine_name):
                config = get_machine_config(machine_name)

                self.assertEqual(config.name, machine_name)
                self.assertEqual(config.diameter_axes, expected_diameter_axes)
                self.assertEqual(config.channels, 2)
                self.assertEqual(config.file_extensions["main"], [".M"])
                self.assertEqual(config.file_extensions["channels"], {"1": [".M"], "2": [".S"]})

    def test_speed_mode_handlers_are_control_specific(self):
        cases = [
            ("FANUC_TURN", FanucTurnSpeedModeHandler),
            ("FANUC_MILL", FanucMillSpeedModeHandler),
            ("SIEMENS_840DI", SiemensISOSpeedHandler),
        ]

        for machine_name, expected_handler in cases:
            with self.subTest(machine=machine_name):
                state = CNCState(machine_config=get_machine_config(machine_name))
                canal = UniversalConfigDrivenCanal("C1", init_state=state)

                self.assertIsNotNone(canal._get_handler(expected_handler))

        self.assertEqual(
            HANDLER_REGISTRY["siemens_iso_speed"],
            ("ncplot7py.domain.handlers.siemens_mill_cnc.speed_handler", "SiemensISOSpeedHandler"),
        )
        self.assertEqual(
            HANDLER_REGISTRY["wait_code"],
            ("ncplot7py.domain.handlers.wait_code", "WaitCodeHandler"),
        )

    def test_siemens_frontend_regex_patterns_include_advanced_commands_and_variables(self):
        patterns = get_machine_regex_patterns("SIEMENS_840DI")

        keyword_pattern = patterns["keywords"]["pattern"]
        for keyword in [ "MCALL", "M30"]:
            self.assertRegex(keyword, keyword_pattern)

        variable_pattern = patterns["variables"]["pattern"]
        for variable in ["R10", "$AA_MW[X]", "$P_UIFR[ORIGIN_GP]", "CUSTOM_MC[3]", "ANGLE_Z"]:
            self.assertRegex(variable, variable_pattern)

    def test_fanuc_frontend_keyword_pattern_accepts_zero_padded_tools(self):
        patterns = get_machine_regex_patterns("FANUC_STAR_x-D_y-R_z_R")

        for pattern in [
            patterns["keywords"]["pattern"],
            patterns["keywords"]["codes"]["extended_tools"]["pattern"],
        ]:
            with self.subTest(pattern=pattern):
                self.assertRegex("T500", f"^(?:{pattern})$")
                self.assertRegex("T0500", f"^(?:{pattern})$")
                self.assertNotRegex("T050", f"^(?:{pattern})$")

    def test_frontend_regex_patterns_come_from_machine_config(self):
        configured_patterns = {"keywords": {"pattern": "CUSTOM_KEYWORD"}}
        machines.MACHINE_CONFIGS["CUSTOM_MACHINE"] = MachineConfig(
            name="CUSTOM_MACHINE",
            control_type="CUSTOM",
            variable_pattern=r"V(\d+)",
            variable_prefix="V",
            tool_range=(1, 10),
            regex_patterns=configured_patterns,
        )

        result = get_machine_regex_patterns("CUSTOM_MACHINE")

        self.assertEqual(result, configured_patterns)
        self.assertIsNot(result, configured_patterns)

    def test_siemens_editor_syntax_rules_include_advanced_commands_and_variables(self):
        import json
        import os

        config_path = os.path.join(os.path.dirname(machines.__file__), "..", "config", "machines.json")
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)

        rules = data["SIEMENS_840DI"]["syntax_rules"]
        by_token = {}
        for rule in rules:
            if isinstance(rule["token"], str):
                by_token.setdefault(rule["token"], []).append(rule["regex"])

        keyword_patterns = by_token["keyword.control"]
        siemens_keyword_pattern = next(pattern for pattern in keyword_patterns if "MCALL" in pattern)

        self.assertIn("MCALL", siemens_keyword_pattern)
        self.assertIn("variable.other.system.siemens", by_token)
        self.assertIn("variable.other.named.siemens", by_token)

        for machine_name, machine_config in data.items():
            for rule in machine_config.get("syntax_rules", []):
                with self.subTest(machine=machine_name, token=rule["token"]):
                    self.assertIsNone(re.compile(rule["regex"]).match(""))

    def test_machine_configs_expose_parser_name_by_control_family(self):
        self.assertEqual(get_machine_config("FANUC_MILL").parser_name, "fanuc")
        self.assertEqual(get_machine_config("FANUC_TURN").parser_name, "fanuc")
        self.assertEqual(get_machine_config("SIEMENS_840DI").parser_name, "siemens")


if __name__ == '__main__':
    unittest.main()