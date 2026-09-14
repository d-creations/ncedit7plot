import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.lexers import SiemensProgramLexer
from ncplot7py.infrastructure.machines.base_stateful_control import BaseStatefulCanal, UniversalConfigDrivenControl
from ncplot7py.infrastructure.parsers.nc_command_parser import NCCommandStringParser


class _Point:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class _Node:
    def __init__(self, nr):
        self.nc_code_line_nr = nr


class FakeControlHappy:
    def __init__(self):
        self._ran = []
        self._state = CNCState(machine_config=get_machine_config("FANUC_MILL"))

    def get_canal_count(self):
        return 1

    def get_nc_state(self, canal: int):
        return self._state

    def run_nc_code_list(self, node_list, canal):
        # accept list of nodes
        self._ran.append((list(node_list), canal))

    def get_tool_path(self, canal: int):
        # return two lines: first with one point and time 0.5, second with one point and time 1.0
        return [([_Point(1, 1, 1)], 0.5), ([_Point(2, 2, 2)], 1.0)]

    def get_exected_nodes(self, canal: int):
        return [_Node(0), _Node(1)]

    def get_canal_name(self, idx: int):
        return f"C{idx}"

    def synchro_points(self, tool_paths, nodes):
        # no-op
        return None


class FakeControlError:
    def get_nc_state(self, canal: int):
        return CNCState(machine_config=get_machine_config("FANUC_MILL"))

    def get_canal_count(self):
        return 1

    def run_nc_code_list(self, node_list, canal):
        # raise a generic error
        raise RuntimeError("control failed")


class _ParserNode:
    def __init__(self, nr):
        self.nc_code_line_nr = nr


class FakeParser:
    def __init__(self):
        self.calls = []

    def parse(self, raw_line, line_nr=None):
        self.calls.append((raw_line, line_nr))
        return _ParserNode(line_nr)


class FakeParserRaisesOnLine:
    def __init__(self, line_nr):
        self.line_nr = line_nr
        self.calls = []

    def parse(self, raw_line, line_nr=None):
        self.calls.append((raw_line, line_nr))
        if line_nr == self.line_nr:
            raise ValueError("parse failed")
        return _ParserNode(line_nr)


class _RaisingChain:
    def handle(self, node, state):
        if node.nc_code_line_nr == 7:
            raise ValueError("could not convert string to float: '[]'")
        return None, 0.0


class FakeControlWrappedExecutionError:
    def __init__(self):
        self._canal = BaseStatefulCanal("C1")
        self._canal._chain = _RaisingChain()

    def get_canal_count(self):
        return 1

    def get_nc_state(self, canal: int):
        return self._canal._state

    def run_nc_code_list(self, node_list, canal):
        self._canal.run_nc_code_list(node_list)

    def get_tool_path(self, canal: int):
        return self._canal.get_tool_path()

    def get_exected_nodes(self, canal: int):
        return self._canal.get_exec_nodes()

    def get_canal_name(self, idx: int):
        return "C1"

    def synchro_points(self, tool_paths, nodes):
        return None


class TestNCExecutionEngine(unittest.TestCase):
    def test_siemens_movements_capture_numeric_and_named_active_tools(self):
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        control = UniversalConfigDrivenControl(init_nc_states=[state])
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot(
            ['T1\nG1 X10 F100\nT="CUTTER"\nG1 X20'],
            synch=False,
        )

        plot = result[0]["plot"]
        self.assertEqual(len(plot), 2)
        self.assertEqual(
            [
                (entry["lineNumber"], entry["executionStep"], entry["toolNumber"])
                for entry in plot
            ],
            [
                (2, 1, 1),
                (4, 3, "CUTTER"),
            ],
        )

    def test_drilling_cycle_plot_contains_classified_primitive_segments(self):
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
        control = UniversalConfigDrivenControl(init_nc_states=[state])
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot(
            ["T0202\nG98\nG83 Z-4 R-1 Q2000 F100"],
            synch=False,
        )

        plot = result[0]["plot"]
        self.assertGreater(len(plot), 1)
        self.assertEqual({entry["geometry"] for entry in plot}, {"LINEAR"})
        self.assertEqual({entry["traversal"] for entry in plot}, {"RAPID", "FEED"})
        self.assertEqual({entry["sourceCode"] for entry in plot}, {"G00", "G01"})
        self.assertEqual({entry["lineNumber"] for entry in plot}, {3})
        self.assertEqual({entry["executionStep"] for entry in plot}, {2})
        self.assertEqual({entry["toolNumber"] for entry in plot}, {2})

    def test_g92_plot_contains_classified_threading_primitives(self):
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
        state.spindle_speed = 1000.0
        control = UniversalConfigDrivenControl(init_nc_states=[state])
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot(
            ["G92 X-2 Z-4 F1"],
            synch=False,
        )

        plot = result[0]["plot"]
        self.assertEqual(len(plot), 4)
        self.assertEqual({entry["geometry"] for entry in plot}, {"LINEAR"})
        self.assertEqual({entry["traversal"] for entry in plot}, {"RAPID", "FEED"})
        self.assertEqual({entry["sourceCode"] for entry in plot}, {"G00", "G92"})
        self.assertEqual({entry["lineNumber"] for entry in plot}, {1})

    def test_happy_path_returns_plot_structure(self):
        ctrl = FakeControlHappy()
        engine = NCExecutionEngine(ctrl)
        programs = ["G1 X1 Y1 Z1;G1 X2 Y2 Z2"]
        result = engine.get_Syncro_plot(programs, synch=False)
        parsed_nodes, _ = ctrl._ran[0]
        self.assertEqual(len(parsed_nodes), 2)
        # one canal
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        canal = result[0]
        self.assertIn("plot", canal)
        self.assertEqual(canal["canalNr"], "C0")
        plot = canal["plot"]
        self.assertEqual(len(plot), 2)
        self.assertEqual(plot[0]["x"], [1])
        self.assertEqual(plot[0]["y"], [1])
        self.assertEqual(plot[0]["z"], [1])
        self.assertEqual(plot[0]["t"], 0.5)
        self.assertEqual(plot[1]["x"], [2])
        self.assertEqual(canal["programExec"], [0, 1])

    def test_control_error_returns_empty_lists(self):
        ctrl = FakeControlError()
        engine = NCExecutionEngine(ctrl)
        programs = ["G1 X1 Y1 Z1"]
        result = engine.get_Syncro_plot(programs, synch=False)
        self.assertEqual(result, [[], []])

    def test_newline_separated_program_is_split_into_multiple_nodes(self):
        ctrl = FakeControlHappy()
        engine = NCExecutionEngine(ctrl)
        programs = ["G1 X1 Y1 Z1\nG1 X2 Y2 Z2"]
        engine.get_Syncro_plot(programs, synch=False)
        self.assertEqual(len(ctrl._ran), 1)
        parsed_nodes, canal = ctrl._ran[0]
        self.assertEqual(canal, 1)
        self.assertEqual(len(parsed_nodes), 2)

    def test_blank_lines_are_preserved_for_line_numbering(self):
        ctrl = FakeControlHappy()
        engine = NCExecutionEngine(ctrl)
        fake_parser = FakeParser()
        engine._get_parser = lambda: fake_parser

        programs = ["G1 X1 Y1 Z1\n\nCOMMENT\nG1 X2 Y2 Z2"]
        engine.get_Syncro_plot(programs, synch=False)

        self.assertEqual(
            fake_parser.calls,
            [
                ("G1 X1 Y1 Z1", 1),
                ("COMMENT", 3),
                ("G1 X2 Y2 Z2", 4),
            ],
        )

    def test_semicolon_commands_keep_editor_line_numbering(self):
        ctrl = FakeControlHappy()
        engine = NCExecutionEngine(ctrl)
        fake_parser = FakeParser()
        engine._get_parser = lambda: fake_parser

        programs = ["G1 X1 Y1 Z1;_Pre_Position\nSTOPRE\nG1 X2 Y2 Z2;Messen"]
        engine.get_Syncro_plot(programs, synch=False)

        self.assertEqual(
            fake_parser.calls,
            [
                ("G1 X1 Y1 Z1", 1),
                ("_Pre_Position", 1),
                ("STOPRE", 2),
                ("G1 X2 Y2 Z2", 3),
                ("Messen", 3),
            ],
        )

    def test_siemens_comment_line_is_not_split_into_executable_code(self):
        ctrl = FakeControlHappy()
        engine = NCExecutionEngine(ctrl, lexer=SiemensProgramLexer())
        parser = NCCommandStringParser(parser_name="siemens")
        engine._get_parser = lambda: parser

        engine.get_Syncro_plot([";G1 X1 Y1 Z1\nG1 X2 Y2 Z2 ; comment"], synch=False)

        parsed_nodes, _ = ctrl._ran[0]
        self.assertEqual(len(parsed_nodes), 1)
        self.assertIn("G1", parsed_nodes[0].g_code)
        self.assertEqual(parsed_nodes[0].command_parameter.get("X"), "2")

    def test_parse_error_stops_execution_immediately(self):
        ctrl = FakeControlHappy()
        engine = NCExecutionEngine(ctrl)
        fake_parser = FakeParserRaisesOnLine(2)
        engine._get_parser = lambda: fake_parser

        result = engine.get_Syncro_plot(["G1 X1\nBAD\nG1 X2"], synch=False)

        self.assertEqual(result, [[], []])
        self.assertEqual(len(engine.errors), 1)
        self.assertEqual(engine.errors[0]["line"], 2)
        self.assertEqual(fake_parser.calls, [("G1 X1", 1), ("BAD", 2)])
        self.assertEqual(ctrl._ran, [])

    def test_execution_error_reports_current_node_line(self):
        ctrl = FakeControlWrappedExecutionError()
        engine = NCExecutionEngine(ctrl)
        fake_parser = FakeParser()
        engine._get_parser = lambda: fake_parser

        programs = ["N1\nN2\nN3\nN4\nN5\nN6\nBAD\nN8\nN9\nN10\nN11\nN12\nN13\nN14"]
        result = engine.get_Syncro_plot(programs, synch=False)

        self.assertEqual(result, [[], []])
        self.assertTrue(engine.errors)
        self.assertEqual(engine.errors[0]["line"], 7)
        self.assertIn("could not convert string to float", engine.errors[0]["message"])

if __name__ == "__main__":
    unittest.main()
