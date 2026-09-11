import importlib.machinery
import importlib.util
import io
import pathlib
import sys
import unittest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CGI_PATH = _REPO_ROOT / "scripts" / "cgiserver.cgi"

_O1000_PROGRAM = """O1000

G0G40G80
G50S10000
G97
M3S500
G130

M5
T2000

M1
N100M200P123(ANFANG DES PROGRAMMS)
M20
M75

M202P123(HAUPSPINDEL RESERVIERUNG FUR OBENREVOLVER)
M204P123(GRUPPE 1)
M206P123(ENDE DER GRUPPE 1)

M208P123(HAUPSPINDEL RESERVIERUNG FUR OBENREVOLVER)

M210P123(HAUPSPINDEL RESERVIERUNG FUR OBENREVOLVER)

M212P123(HAUPSPINDEL RESERVIERUNG FUR OBENREVOLVER)

M214P123(HAUPSPINDEL RESERVIERUNG FUR OBENREVOLVER)

M216P123(HAUPSPINDEL RESERVIERUNG FUR UNTENREVOLVER)

(OP 4.1.9 - SCHLICHTEN)
(T2525 - ALESAGE INTER DIA2.5)
/T2500
/G132
/G50S10000
/G96S200
/G99
/M4
/G18
/G0Z-3.T25
/X-10.Y0.
/X6.124
/Z6.496
/G1G42X6.Z6.F0.05
/X5.Z2.
/Z0.914
/G3X4.414Z0.207R1.
/G1X4.Z0.
/X-0.4
/G40X-0.4Z-0.5
/G0Z-3.
/X-10.
/G0T0
/G97
/M1

(OP 4.2.10 - SCHLICHTEN)
(T2222 - FRAISE A RAINURER DIA002)
/T2200
/G132
/G97
/G98
/M56S8000
/M8
/G0X-7.359C0.Z-5.T22
/G112
/G1X5.4F2000
/Z-1.
/Z0.2F100
/G41X4.F500
/X-1.2
/G2X-3.2R1.
/G1
/X2.
/
/G40X4.
/Z-5.F2000
/G113
/M58
/M9

(SCHLICHTEN)
/M56S8000
/G17
/M8
/G0C0.
/M6
/X5.4Y-2.5Z-5.
/Z-1.
/G1Z0.4F100
/G41X4.Y-1.5F500
/X-1.2
/G2X-3.2Y-0.5R1.
/G1Y1.
/X2.
/Y-2.5
/G40X4.Y-3.2
/G0Z-5.
/M58
/M7
/M9
/G0T0
M1
M76
T2900
G130
M5
G0Z20.
M14
M11
M84
G4X1.
M15
M27
T2000
(PICK-UP)
G900J50
M218P123
T2000
M5
M82
G131B0.
G0Z-5.M11
M68
M14
G98G1Z5.0F2000
M69
G99M10
G133
M15
G4
G4
M68
G0W-20.
M69
M83
G0T0
G130
N50
G28U0.W0.M5

M220P123(SYNCHRONISATION VON ENDE DES PROGRAMMS)
M99
"""


def _load_cgiserver_module():
    loader = importlib.machinery.SourceFileLoader(
        "cgiserver_for_compensation_integration",
        str(_CGI_PATH),
    )
    spec = importlib.util.spec_from_loader(
        "cgiserver_for_compensation_integration",
        loader,
    )
    module = importlib.util.module_from_spec(spec)
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        loader.exec_module(module)
    finally:
        sys.stdout = old_stdout
    return module


class TestToolRadiusCompensationIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cgiserver = _load_cgiserver_module()

    def test_o1000_reports_compensation_errors_without_mock_output(self):
        cases = [
            (
                "FANUC_TURN",
                [
                    {"qValue": 2, "toolNumber": 20},
                    {"qValue": 2, "rValue": 4, "toolNumber": 25},
                    {"qValue": 4, "rValue": 2, "toolNumber": 2000},
                ],
                -108,
                "FANUC_TURN",
                "/G1G42X6.Z6.F0.05",
            ),
            (
                "FANUC_MILL",
                [{"qValue": 4, "rValue": 2, "toolNumber": 2000}],
                -100,
                "25",
                "/G1G42X6.Z6.F0.05",
            ),
        ]
        for machine_name, tool_values, error_code, error_value, activation in cases:
            with self.subTest(machine=machine_name):
                result = self.cgiserver.handle_execute_programs(
                    [{
                        "canalNr": "2",
                        "customVariables": [],
                        "machineName": machine_name,
                        "program": _O1000_PROGRAM,
                        "toolValues": tool_values,
                    }],
                    tool_path_mode="center",
                )

                self.assertNotIn("(mock)", " ".join(result["message"]))
                self.assertTrue(result.get("hasErrors"), result.get("errors"))
                errors = [error for error in result["errors"] if error["code"] == error_code]
                self.assertTrue(errors, result["errors"])
                self.assertEqual(errors[0]["value"], error_value)
                self.assertEqual(
                    errors[0]["line"],
                    _O1000_PROGRAM.splitlines().index(activation) + 1,
                )

    def test_fanuc_mill_center_path_is_compensated_and_identified(self):
        result = self.cgiserver.handle_execute_programs(
            [
                {
                    "program": "T1\nG17\nG41 G1 X10 Y0 F100\nG1 X10 Y10\nG40",
                    "machineName": "FANUC_MILL",
                    "canalNr": "1",
                    "toolValues": [
                        {"toolNumber": 1, "qValue": 3, "rValue": 1.0}
                    ],
                }
            ],
            tool_path_mode="center",
        )

        self.assertTrue(result["success"])
        self.assertNotIn("(mock)", " ".join(result["message"]))
        segments = result["canal"]["1"]["segments"]
        self.assertEqual(len(segments), 2)
        self.assertEqual(
            [
                (segment["lineNumber"], segment["executionStep"], segment["toolNumber"])
                for segment in segments
            ],
            [(3, 2, 1), (4, 3, 1)],
        )
        self.assertAlmostEqual(segments[0]["points"][-1]["x"], 9.0)
        self.assertAlmostEqual(segments[0]["points"][-1]["y"], 1.0)
        self.assertAlmostEqual(segments[1]["points"][0]["x"], 9.0)
        self.assertAlmostEqual(segments[1]["points"][0]["y"], 1.0)

    def test_siemens_named_tool_center_path_is_compensated_and_identified(self):
        result = self.cgiserver.handle_execute_programs(
            [
                {
                    "program": 'T="CUTTER"\nG17\nG42 G1 X10 Y0 F100\nG40',
                    "machineName": "SIEMENS_840DI",
                    "canalNr": "1",
                    "toolValues": [
                        {"toolNumber": "CUTTER", "rValue": 2.0}
                    ],
                }
            ],
            tool_path_mode="center",
        )

        self.assertTrue(result["success"])
        self.assertNotIn("(mock)", " ".join(result["message"]))
        segments = result["canal"]["1"]["segments"]
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["lineNumber"], 3)
        self.assertEqual(segments[0]["executionStep"], 2)
        self.assertEqual(segments[0]["toolNumber"], "CUTTER")
        self.assertAlmostEqual(segments[0]["points"][0]["y"], -2.0)
        self.assertAlmostEqual(segments[0]["points"][-1]["y"], -2.0)


if __name__ == "__main__":
    unittest.main()