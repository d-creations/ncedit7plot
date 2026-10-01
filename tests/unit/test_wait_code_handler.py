import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.handlers.wait_code import WaitCodeHandler
from ncplot7py.shared.nc_nodes import NCCommandNode


class TestWaitCodeHandler(unittest.TestCase):
    def setUp(self):
        self.handler = WaitCodeHandler()

    def test_extract_star_wait_m300(self):
        state = CNCState()
        node = NCCommandNode(command_parameter={"M": "300"})
        wait_info = WaitCodeHandler.extract_wait_code(node, state)
        self.assertIsNotNone(wait_info)
        self.assertEqual(wait_info["type"], "STAR_WAIT")
        self.assertEqual(wait_info["code"], 300)
        self.assertIsNone(wait_info["p"])

    def test_extract_star_wait_with_p(self):
        state = CNCState()
        node = NCCommandNode(command_parameter={"M": "500", "P": "12"})
        wait_info = WaitCodeHandler.extract_wait_code(node, state)
        self.assertIsNotNone(wait_info)
        self.assertEqual(wait_info["type"], "STAR_WAIT")
        self.assertEqual(wait_info["code"], 500)
        self.assertEqual(wait_info["p"], 12)

    def test_extract_star_special_wait_codes(self):
        state = CNCState()
        for code in (40, 41, 82, 83):
            node = NCCommandNode(command_parameter={"M": str(code)})
            wait_info = WaitCodeHandler.extract_wait_code(node, state)
            self.assertIsNotNone(wait_info)
            self.assertEqual(wait_info["code"], code)
            self.assertEqual(wait_info["p"], 12)

        for code in (131, 133):
            node = NCCommandNode(command_parameter={"M": str(code)})
            wait_info = WaitCodeHandler.extract_wait_code(node, state)
            self.assertIsNotNone(wait_info)
            self.assertEqual(wait_info["code"], code)
            self.assertEqual(wait_info["p"], 13)

    def test_extract_m171_m172_wait_codes(self):
        state_ch1 = CNCState()
        state_ch1.extra["path_number"] = 1
        for code in (171, 172):
            node = NCCommandNode(command_parameter={"M": str(code)})
            wait_info = WaitCodeHandler.extract_wait_code(node, state_ch1)
            self.assertIsNotNone(wait_info)
            self.assertEqual(wait_info["code"], code)
            self.assertEqual(wait_info["p"], 12)

        state_ch3 = CNCState()
        state_ch3.extra["path_number"] = 3
        for code in (171, 172):
            node = NCCommandNode(command_parameter={"M": str(code)})
            wait_info = WaitCodeHandler.extract_wait_code(node, state_ch3)
            self.assertIsNotNone(wait_info)
            self.assertEqual(wait_info["code"], code)
            self.assertEqual(wait_info["p"], 23)

    def test_extract_siemens_waitm(self):
        state = CNCState()
        node = NCCommandNode(variable_command="WAITM(1, 1, 2)")
        wait_info = WaitCodeHandler.extract_wait_code(node, state)
        self.assertIsNotNone(wait_info)
        self.assertEqual(wait_info["type"], "SIEMENS_WAIT")
        self.assertEqual(wait_info["marker"], 1)
        self.assertEqual(wait_info["channels"], ["1", "2"])

        # Also simple WAITM(5)
        node2 = NCCommandNode(variable_command="WAITM(5)")
        wait_info2 = WaitCodeHandler.extract_wait_code(node2, state)
        self.assertIsNotNone(wait_info2)
        self.assertEqual(wait_info2["type"], "SIEMENS_WAIT")
        self.assertEqual(wait_info2["marker"], 5)
        self.assertIsNone(wait_info2["channels"])

    def test_non_wait_m_code(self):
        state = CNCState()
        node = NCCommandNode(command_parameter={"M": "3"})
        wait_info = WaitCodeHandler.extract_wait_code(node, state)
        self.assertIsNone(wait_info)

    def test_handle_attaches_extra(self):
        state = CNCState()
        node = NCCommandNode(command_parameter={"M": "300"})
        pts, dur = self.handler.handle(node, state)
        self.assertIsNone(pts)
        self.assertIsNone(dur)
        self.assertIn("wait_code", node.extra)
        self.assertEqual(node.extra["wait_code"]["code"], 300)
        self.assertEqual(state.extra["last_wait_code"]["code"], 300)


if __name__ == '__main__':
    unittest.main()
