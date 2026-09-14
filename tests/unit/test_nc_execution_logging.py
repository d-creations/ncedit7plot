import os
import sys
import unittest

# Ensure the package is importable when tests are run from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.exceptions import ExceptionNode, ExceptionTyps
from ncplot7py.shared import configure_logging, get_message_stack, clear_message_stack


class RaisingControl:
    """Fake control that raises an ExceptionNode during execution."""

    def get_canal_count(self):
        return 1

    def run_nc_code_list(self, node_list, canal):
        raise ExceptionNode(
            typ=ExceptionTyps.NCCodeErrors,
            code=-100,
            line=70,
            message="Tool radius compensation requires tool radius R",
            value=22,
        )

    def get_tool_path(self, canal):
        return []

    def get_exected_nodes(self, canal):
        return []

    def get_canal_name(self, idx):
        return f"C{idx}"

    def synchro_points(self, tool_paths, nodes):
        return None


class NCExecutionEngineLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        # Caller configures a web buffer before constructing the engine,
        # mirroring how frontends collect messages via get_message_stack().
        configure_logging(console=False, web_buffer=True)
        clear_message_stack()

    def test_engine_construction_preserves_caller_web_buffer(self):
        engine = NCExecutionEngine(RaisingControl())
        result = engine.get_Syncro_plot(["N70 G01 X0"], synch=False)

        self.assertEqual(result, [[], []])
        self.assertTrue(engine.errors, "engine.errors should contain the collected error")

        stack = get_message_stack()
        self.assertIn("Tool radius compensation", stack)


if __name__ == '__main__':
    unittest.main()
