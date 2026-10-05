import unittest
import importlib.machinery
import importlib.util
import io
import pathlib
import sys

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared import configure_logging, configure_i18n
from ncplot7py.shared.file_adapter import get_program

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CGI_PATH = _REPO_ROOT / "scripts" / "cgiserver.cgi"


def _load_cgiserver_module():
    loader = importlib.machinery.SourceFileLoader("cgiserver_for_mode_test", str(_CGI_PATH))
    spec = importlib.util.spec_from_loader("cgiserver_for_mode_test", loader)
    module = importlib.util.module_from_spec(spec)
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        loader.exec_module(module)
    finally:
        sys.stdout = old_stdout
    return module


class TestMachiningModeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_logging(console=False, web_buffer=True)
        configure_i18n()

    def test_star_mixed_machining_program_acceptance_contract(self):
        """Verify the exact sequence from the RFC acceptance test table:
        | Executed motion | Expected mode |
        | Turning feed | Turning |
        | Rapid while still in turning mode | Turning |
        | Feed after milling-mode switch | Milling |
        | Feed after switching back | Turning |
        """
        program_lines = [
            "M3 S2000",       # Start main spindle -> turning mode (also emits C0 reset)
            "G1 Z-10.0 F100",  # 1. Turning feed -> 'turning'
            "G0 X25.0",        # 2. Rapid while still in turning mode -> 'turning'
            "M36 S3500",      # Switch to power-driven milling tool
            "G1 X10.0 F200",   # 3. Feed after milling-mode switch -> 'milling'
            "M3 S1800",       # Switch back to turning (also emits C0 reset)
            "G1 Z-20.0 F100",  # 4. Feed after switching back -> 'turning'
        ]
        programs = get_program(program_lines, split_on_blank_line=True)
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-R_z_R"))
        ctrl = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        engine = NCExecutionEngine(ctrl)
        result = engine.get_Syncro_plot(programs, synch=False)

        self.assertEqual(len(result), 1)
        plot = result[0]["plot"]
        # M3 also performs C-axis reset to 0 in turning mode:
        # plot[0] is M3 C0 reset (turning)
        # plot[1] is G1 Z-10 turning feed (turning)
        # plot[2] is G0 X25 rapid in turning mode (turning)
        # plot[3] is G1 X10 feed after M36 (milling)
        # plot[4] is M3 C0 reset (turning)
        # plot[5] is G1 Z-20 turning feed (turning)
        self.assertEqual(len(plot), 6)

        # 1. Turning feed -> turning
        self.assertEqual(plot[1]["sourceCode"], "G01")
        self.assertEqual(plot[1]["traversal"], "FEED")
        self.assertEqual(plot[1]["machiningMode"], "turning")
        self.assertNotIn("motionContext", plot[1])

        # 2. Rapid while still in turning mode -> turning
        self.assertEqual(plot[2]["sourceCode"], "G00")
        self.assertEqual(plot[2]["traversal"], "RAPID")
        self.assertEqual(plot[2]["machiningMode"], "turning")

        # 3. Feed after milling-mode switch -> milling
        self.assertEqual(plot[3]["sourceCode"], "G01")
        self.assertEqual(plot[3]["traversal"], "FEED")
        self.assertEqual(plot[3]["machiningMode"], "milling")

        # 4. Feed after switching back -> turning
        self.assertEqual(plot[5]["sourceCode"], "G01")
        self.assertEqual(plot[5]["traversal"], "FEED")
        self.assertEqual(plot[5]["machiningMode"], "turning")

    def test_mode_follows_execution_order_in_repeated_calls_or_loops(self):
        """Mode must follow execution order, not simply the source line."""
        program_lines = [
            "#10 = 0",
            "WHILE [#10 LT 2] DO1",
            "IF [#10 EQ 0] GOTO 100",
            "M36 S3000",      # 2nd iteration: switch to milling
            "GOTO 200",
            "N100 M3 S1500",  # 1st iteration: start turning
            "N200 G1 X[10 + #10] F100",
            "#10 = #10 + 1",
            "END1",
        ]
        programs = get_program(program_lines, split_on_blank_line=True)
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_x-D_y-R_z_R"))
        ctrl = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        engine = NCExecutionEngine(ctrl)
        result = engine.get_Syncro_plot(programs, synch=False)

        plot = result[0]["plot"]
        # plot[0] is M3 C0 reset (turning)
        # plot[1] is 1st iteration of N200 G1 (turning)
        # plot[2] is 2nd iteration of N200 G1 (milling)
        self.assertEqual(len(plot), 3)
        self.assertEqual(plot[1]["sourceCode"], "G01")
        self.assertEqual(plot[1]["machiningMode"], "turning")
        self.assertEqual(plot[2]["sourceCode"], "G01")
        self.assertEqual(plot[2]["machiningMode"], "milling")

    def test_fanuc_turn_m3_m5_mode_switching(self):
        program_lines = [
            "M3 S1000",
            "G1 Z-5.0 F100",  # turning
            "G0 X30.0",       # turning rapid
            "M5",             # spindle stop -> milling mode
            "G1 X20.0 F150",  # milling feed
            "M3 S1200",       # switch back to turning
            "G1 Z-15.0 F100", # turning
        ]
        programs = get_program(program_lines, split_on_blank_line=True)
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
        ctrl = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        engine = NCExecutionEngine(ctrl)
        result = engine.get_Syncro_plot(programs, synch=False)

        plot = result[0]["plot"]
        # plot[0] is M3 C0 reset (turning)
        # plot[1] is G1 Z-5 turning feed (turning)
        # plot[2] is G0 X30 turning rapid (turning)
        # plot[3] is G1 X20 feed after M5 (milling)
        # plot[4] is M3 C0 reset (turning)
        # plot[5] is G1 Z-15 turning feed (turning)
        self.assertEqual(len(plot), 6)
        self.assertEqual(plot[1]["machiningMode"], "turning")
        self.assertEqual(plot[2]["machiningMode"], "turning")
        self.assertEqual(plot[3]["machiningMode"], "milling")
        self.assertEqual(plot[5]["machiningMode"], "turning")

    def test_fanuc_mill_and_siemens_mill_always_milling(self):
        # Fanuc Mill
        program_lines = [
            "M3 S3000",
            "G1 X10.0 Y10.0 F200",
            "G0 Z5.0",
            "M5",
            "G1 X20.0 Y20.0 F200",
        ]
        programs = get_program(program_lines, split_on_blank_line=True)
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"))
        ctrl = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        engine = NCExecutionEngine(ctrl)
        result = engine.get_Syncro_plot(programs, synch=False)
        plot = result[0]["plot"]
        self.assertEqual(len(plot), 3)
        for pt in plot:
            self.assertEqual(pt["machiningMode"], "milling")

        # Siemens Mill (newline-separated)
        siemens_prog = "G290\nG17 G90 G94\nM3 S3000\nG1 X10.0 Y10.0 F200\nG0 Z5.0\nM5\nG1 X20.0 Y20.0 F200\n"
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        ctrl = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        engine = NCExecutionEngine(ctrl)
        result = engine.get_Syncro_plot([siemens_prog], synch=False)
        plot = result[0]["plot"]
        self.assertEqual(len(plot), 3)
        for pt in plot:
            self.assertEqual(pt["machiningMode"], "milling")

    def test_cgiserver_execution_preserves_machining_mode_on_segments(self):
        cgiserver = _load_cgiserver_module()
        result = cgiserver.handle_execute_programs([{
            "machineName": "FANUC_STAR_x-D_y-R_z_R",
            "canalNr": "1",
            "program": "M3 S2000\nG1 Z-10 F100\nM36 S3000\nG1 X10 F200",
        }])
        self.assertTrue(result["success"])
        segments = result["canal"]["1"]["segments"]
        # segment[0] is M3 C0 reset (turning)
        # segment[1] is G1 Z-10 (turning)
        # segment[2] is G1 X10 (milling)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]["machiningMode"], "turning")
        self.assertEqual(segments[1]["machiningMode"], "turning")
        self.assertEqual(segments[2]["machiningMode"], "milling")
        for seg in segments:
            self.assertNotIn("motionContext", seg)

    def test_cgiserver_older_response_without_field_defaults_to_unknown(self):
        cgiserver = _load_cgiserver_module()
        # Older engine output without machiningMode
        result = cgiserver.build_segments_from_engine_output({
            "plot": [
                {
                    "x": [0.0, 1.0], "y": [0.0, 0.0], "z": [0.0, 0.0], "t": 1.0,
                    "geometry": "LINEAR", "traversal": "FEED", "sourceCode": "G01",
                    "motionContext": {"channelId": "1"},  # missing machiningMode
                },
                {
                    "x": [1.0, 2.0], "y": [0.0, 0.0], "z": [0.0, 0.0], "t": 1.0,
                    "geometry": "LINEAR", "traversal": "FEED", "sourceCode": "G01",
                    # no motionContext at all
                },
            ]
        })
        segments = result["segments"]
        self.assertEqual(segments[0]["machiningMode"], "unknown")
        self.assertEqual(segments[1]["machiningMode"], "unknown")
        for seg in segments:
            self.assertNotIn("motionContext", seg)
