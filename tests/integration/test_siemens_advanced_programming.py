import unittest

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionNode
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl
from ncplot7py.infrastructure.parsers.nc_command_parser import NCCommandStringParser


class NCParser:
    def __init__(self):
        self.parser = NCCommandStringParser()

    def parse(self, code):
        nodes = []
        for index, line in enumerate(code.strip().split("\n"), 1):
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("("):
                continue
            if ";" in line:
                line = line.split(";", 1)[0].strip()
            nodes.append(self.parser.parse(line, index))
        return nodes


class TestSiemensAdvancedProgrammingIntegration(unittest.TestCase):
    def setUp(self):
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        self.control = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        self.parser = NCParser()

    def test_advanced_programming_features_execute_together(self):
        code = """
        G290
        G17 G90 G94
        DEF INT IDX=0
        DEF REAL Custom_MC[4]
        DEF REAL BASE_X=12
        DEF REAL ANGLE_Z
        Custom_MC[0]=BASE_X+8
        Custom_MC[1]=SQRT(81)
        ANGLE_Z=ATAN2(30,40)
        $P_UIFR[1]=CTRANS(X,Custom_MC[0],Y,Custom_MC[1],Z,-2):CROT(X,1,Y,2,Z,ANGLE_Z)
        G54
        G64
        TRAORI
        M82
        SPOS=180
        FOR IDX=1 TO 3
            G1 X=IDX Y=Custom_MC[1] Z=-2 F120
        ENDFOR
        WHILE IDX LT 5 DO1
            G1 X=IDX Y=0 Z=-3 F120
            IDX=IDX+1
        END1
        GOTOF AFTER_SKIP
        G1 X999 Y999 Z999 F120
        AFTER_SKIP:
        STOPRE
        TRAFOOF
        M83
        RET
        SETAL(65000,"Programmed user alarm")
        """

        nodes = self.parser.parse(code)
        with self.assertRaises(ExceptionNode):
            self.control.run_nc_code_list(nodes, 1)

        state = self.control.get_nc_state(1)
        path = self.control.get_tool_path(1)
        siemens = state.extra["siemens"]

        self.assertTrue(path)
        self.assertAlmostEqual(siemens["arrays"]["Custom_MC"][0], 20.0)
        self.assertAlmostEqual(siemens["arrays"]["Custom_MC"][1], 9.0)
        self.assertAlmostEqual(siemens["symbols"]["ANGLE_Z"], 36.869897, places=5)
        self.assertEqual(siemens["symbols"]["IDX"], 5)

        self.assertEqual(state.extra["active_work_offset_index"], 1)
        self.assertEqual(state.offsets["X"], 20.0)
        self.assertEqual(state.offsets["Y"], 9.0)
        self.assertEqual(state.offsets["Z"], -2.0)
        self.assertEqual(siemens["frames"][1]["rotation"]["Z"], siemens["symbols"]["ANGLE_Z"])
        self.assertEqual(siemens["path_mode"], "G64")
        self.assertFalse(siemens["transformations"]["TRAORI"]["active"])
        self.assertFalse(siemens["probe_enabled"])
        self.assertEqual(siemens["spindle_position"], 180.0)
        self.assertTrue(state.extra["program_returned"])
        self.assertEqual(state.extra["alarms"][-1]["code"], 65000)
        self.assertEqual(state.extra["alarms"][-1]["message"], "Programmed user alarm")
        self.assertTrue(siemens["preprocess_stops"])

        visited_points = [point for segment, _duration in path for point in segment]
        self.assertTrue(any(abs(point.x + 3.0) < 0.001 and abs(point.y + 9.0) < 0.001 for point in visited_points))
        self.assertTrue(any(abs(point.x + 4.0) < 0.001 and abs(point.y) < 0.001 and abs(point.z + 3.0) < 0.001 for point in visited_points))
        self.assertFalse(any(abs(point.x - 999.0) < 0.001 for point in visited_points))

    def test_execution_output_exposes_named_variables_and_arrays(self):
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        control = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state])
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot(
            [
                "DEF REAL CUSTOM_MC[4]\n"
                "DEF REAL ANGLE_Z\n"
                "CUSTOM_MC[0]=20\n"
                "CUSTOM_MC[3]=12.5\n"
                "ANGLE_Z=ATAN2(30,40)\n"
                "G1 X1 F120"
            ],
            synch=False,
        )

        named_variables = result[0]["namedVariables"]

        self.assertAlmostEqual(named_variables["ANGLE_Z"], 36.869897, places=5)
        self.assertEqual(named_variables["CUSTOM_MC[0]"], 20.0)
        self.assertEqual(named_variables["CUSTOM_MC[3]"], 12.5)


if __name__ == "__main__":
    unittest.main()