import importlib.machinery
import importlib.util
import io
import pathlib
import sys
import unittest
from unittest.mock import patch


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CGI_PATH = _REPO_ROOT / "scripts" / "cgiserver.cgi"


def _load_cgiserver_module():
    loader = importlib.machinery.SourceFileLoader("cgiserver_for_test", str(_CGI_PATH))
    spec = importlib.util.spec_from_loader("cgiserver_for_test", loader)
    module = importlib.util.module_from_spec(spec)
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        loader.exec_module(module)
    finally:
        sys.stdout = old_stdout
    return module


class TestCgiServerConversion(unittest.TestCase):
    def test_api_passes_independent_offsets_to_execution(self):
        cgiserver = _load_cgiserver_module()
        result = cgiserver.handle_execute_programs([{
            "machineName": "FANUC_MILL", "canalNr": "1",
            "program": "T1\nG17\nG41 D2 G1 X10 F100\nG40\nG41 D3 G1 X20\nG40",
            "toolValues": [{"toolNumber": 1}],
            "toolOffsets": [{"offsetNumber": 2, "rValue": 1}, {"offsetNumber": 3, "rValue": 2}],
        }], tool_path_mode="center")
        self.assertTrue(result["success"])
        self.assertFalse(result.get("errors"))
        segments = result["canal"]["1"]["segments"]
        self.assertEqual({segment["toolNumber"] for segment in segments}, {1})
        self.assertEqual(segments[0]["points"][0]["y"], 1)
        self.assertEqual(segments[-1]["points"][-1]["y"], 2)

    def test_api_rejects_duplicate_offset_data(self):
        cgiserver = _load_cgiserver_module()
        result = cgiserver.handle_execute_programs([{
            "machineName": "FANUC_MILL", "program": "T1",
            "toolOffsets": [{"offsetNumber": 2}, {"offsetNumber": 2}],
        }])
        self.assertFalse(result["success"])
        self.assertIn("Duplicate offset", result["message"][0])

    def test_line_alignment_syntax_describes_fanuc_and_siemens(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.handle_get_line_alignment_syntax()

        self.assertTrue(result["success"])
        fanuc, siemens = result["lineAlignmentSyntax"]
        self.assertEqual(fanuc["waitCodeRange"], {"min": 200, "max": 899})
        self.assertEqual(fanuc["twoChannel"]["example"], {"channel1": "M200", "channel2": "M200"})
        self.assertEqual(fanuc["threeChannel"]["selectors"], ["P12", "P13", "P23", "P123"])
        self.assertEqual(siemens["syntax"], "WAITM(<marker>)")
        self.assertEqual(siemens["example"], {"channel1": "WAITM(1)", "channel2": "WAITM(1)"})

    def test_segment_timing_uses_plot_editor_line_number(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.build_segments_from_engine_output(
            {
                "programExec": [1, 2, 10],
                "variables": {"1": 4.7},
                "namedVariables": {"ANGLE_Z": 36.5, "CUSTOM_MC[0]": 12.0},
                "plot": [
                    {
                        "x": [0.0, 1.0],
                        "y": [0.0, 0.0],
                        "z": [0.0, 0.0],
                        "t": 2.5,
                        "lineNumber": 10,
                        "executionStep": 5,
                        "toolNumber": 2,
                    }
                ],
            }
        )

        self.assertEqual(result["segments"][0]["lineNumber"], 10)
        self.assertEqual(result["segments"][0]["executionStep"], 5)
        self.assertEqual(result["segments"][0]["toolNumber"], 2)
        self.assertNotIn("toolState", result["segments"][0])
        self.assertNotIn("sourceProgramId", result["segments"][0])
        self.assertEqual(result["executedLines"], [10])
        self.assertEqual(result["executedNodeLines"], [1, 2, 10])
        self.assertEqual(result["variables"], {"1": 4.7})
        self.assertEqual(result["namedVariables"], {"ANGLE_Z": 36.5, "CUSTOM_MC[0]": 12.0})
        self.assertEqual(result["timing"], [2.5])
        self.assertEqual(result["lineTiming"], {"10": 2.5})

    def test_segment_type_uses_motion_metadata_instead_of_duration(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.build_segments_from_engine_output(
            {
                "plot": [
                    {
                        "x": [0.0, 1.0],
                        "y": [0.0, 0.0],
                        "z": [0.0, 0.0],
                        "t": 0.25,
                        "geometry": "LINEAR",
                        "traversal": "RAPID",
                        "sourceCode": "G00",
                    },
                    {
                        "x": [1.0, 2.0],
                        "y": [0.0, 1.0],
                        "z": [0.0, 0.0],
                        "t": 0.5,
                        "geometry": "ARC_CW",
                        "traversal": "FEED",
                        "sourceCode": "G02",
                    },
                ]
            }
        )

        rapid, arc = result["segments"]
        self.assertEqual(rapid["type"], "RAPID")
        self.assertEqual(rapid["geometry"], "LINEAR")
        self.assertEqual(rapid["traversal"], "RAPID")
        self.assertEqual(arc["type"], "ARC_CW")
        self.assertEqual(arc["sourceCode"], "G02")

    def test_explicitly_unknown_motion_semantics_do_not_infer_type_from_duration(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.build_segments_from_engine_output(
            {
                "plot": [
                    {
                        "x": [0.0, 0.0, 0.0],
                        "y": [0.0, 0.0, 0.0],
                        "z": [2.0, -5.0, 10.0],
                        "t": 0.0,
                        "geometry": None,
                        "traversal": None,
                        "sourceCode": None,
                    }
                ]
            }
        )

        segment = result["segments"][0]
        self.assertEqual(segment["type"], "UNKNOWN")
        self.assertIsNone(segment["geometry"])
        self.assertIsNone(segment["traversal"])

    def test_execute_program_preserves_explicit_and_modal_motion_metadata(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.handle_execute_programs(
            [
                {
                    "program": "G0 X10 Y0\nX20\nG1 X30 F600\nG2 X40 Y10 R10\nG3 X50 Y0 R10",
                    "machineName": "FANUC_MILL",
                    "canalNr": "1",
                }
            ]
        )

        segments = result["canal"]["1"]["segments"]
        self.assertEqual(
            [(segment["geometry"], segment["traversal"], segment["sourceCode"]) for segment in segments],
            [
                ("LINEAR", "RAPID", "G00"),
                ("LINEAR", "RAPID", "G00"),
                ("LINEAR", "FEED", "G01"),
                ("ARC_CW", "FEED", "G02"),
                ("ARC_CCW", "FEED", "G03"),
            ],
        )
        self.assertEqual([segment["type"] for segment in segments], ["RAPID", "RAPID", "LINEAR", "ARC_CW", "ARC_CCW"])

    def test_execute_program_accepts_center_tool_path_mode(self):
        cgiserver = _load_cgiserver_module()
        captured = {}

        class CapturingEngine:
            def __init__(self, control):
                captured["state"] = control.get_nc_state(1)
                self.errors = []

            def get_Syncro_plot(self, programs, synch):
                return [{"plot": [], "programExec": [1]}]

        with patch.object(cgiserver, "NCExecutionEngine", CapturingEngine):
            result = cgiserver.handle_execute_programs(
                [
                    {
                        "program": "G1 X1",
                        "machineName": "FANUC_MILL",
                        "canalNr": "1",
                        "toolValues": [
                            {
                                "toolNumber": 1,
                                "qValue": 3,
                                "rValue": 0.4,
                                "lengthValue": 120.5,
                                "edgeNumber": 2,
                            }
                        ],
                    }
                ],
                tool_path_mode="center",
            )

        self.assertTrue(result["success"])
        self.assertEqual(captured["state"].tool_path_mode, "center")
        self.assertEqual(
            captured["state"].extra["tool_compensation_data"][1],
            {
                "qValue": 3,
                "rValue": 0.4,
                "lengthValue": 120.5,
                "edgeNumber": 2,
            },
        )

    def test_execute_program_rejects_unknown_tool_path_mode(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.handle_execute_programs([], tool_path_mode="outside")

        self.assertFalse(result["success"])
        self.assertIn("Invalid toolPathMode", result["message"][0])

    def test_variable_only_siemens_program_does_not_fall_back_to_mock(self):
        cgiserver = _load_cgiserver_module()

        result = cgiserver.handle_execute_programs(
            [
                {
                    "program": "DEF REAL CUSTOM_MC[4]\nCUSTOM_MC[3]=12.5\nANGLE_Z=ATAN2(30,40)",
                    "machineName": "SIEMENS_840DI",
                    "canalNr": "1",
                }
            ]
        )

        canal = result["canal"]["1"]
        self.assertEqual(canal["segments"], [])
        self.assertAlmostEqual(canal["namedVariables"]["CUSTOM_MC[3]"], 12.5)
        self.assertAlmostEqual(canal["namedVariables"]["ANGLE_Z"], 36.869897, places=5)

    def test_siemens_cgi_preserves_named_variables_in_axis_expressions(self):
        cgiserver = _load_cgiserver_module()
        for axis_line in ["Y=Y_POS LA1=(R75 + Y_POS) RND = ECK_RND", "LA1=(R75 + Y_POS) Y=Y_POS RND = ECK_RND"]:
            with self.subTest(axis_line=axis_line):
                program = "\n".join(
                    [
                        "DEF REAL Y_POS = 640",
                        "DEF REAL ECK_RND = 12",
                        "R75 = -525",
                        axis_line,
                        "G1 X10",
                    ]
                )

                result = cgiserver.handle_execute_programs(
                    [
                        {
                            "program": program,
                            "machineName": "SIEMENS_840DI",
                            "canalNr": "1",
                        }
                    ]
                )

                self.assertIsNone(result.get("errors"))
                canal = result["canal"]["1"]
                self.assertAlmostEqual(canal["namedVariables"]["RND"], 12.0)
                self.assertIn(5, canal["executedNodeLines"])


if __name__ == "__main__":
    unittest.main()
