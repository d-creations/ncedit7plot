import importlib.machinery
import importlib.util
import io
import pathlib
import sys
import unittest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CGI_PATH = _REPO_ROOT / "scripts" / "cgiserver.cgi"


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