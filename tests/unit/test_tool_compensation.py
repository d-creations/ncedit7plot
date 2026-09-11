import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.tool_compensation import ToolCompensationState, ToolPathCompensator, ToolDataResolver, load_tool_data
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.exceptions import ExceptionNode
from ncplot7py.shared.point import Point


class TestToolPathCompensator(unittest.TestCase):
    def test_one_tool_can_select_multiple_global_offsets(self):
        state = CNCState(machine_config=get_machine_config("FANUC_TURN"))
        load_tool_data(state, [{"toolNumber": 1, "rValue": 99}], [
            {"offsetNumber": 2, "rValue": 0.4, "qValue": 3},
            {"offsetNumber": 3, "rValue": 0.8, "qValue": 4},
        ])
        state.extra["active_tool_number"] = 1
        for register, radius in [(2, 0.4), (3, 0.8)]:
            state.extra["active_offset_number"] = register
            self.assertEqual(ToolDataResolver().resolve(state).radius, radius)
        state.extra["active_offset_number"] = 4
        with self.assertRaises(ExceptionNode):
            ToolDataResolver().resolve(state)
        state.extra["active_offset_number"] = 0
        self.assertIsNone(ToolDataResolver().resolve(state).radius)

    def test_siemens_offsets_are_scoped_by_exact_tool_identifier(self):
        state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
        load_tool_data(state, [{"toolNumber": 1}, {"toolNumber": "1"}], [
            {"toolNumber": 1, "offsetNumber": 2, "rValue": 3},
            {"toolNumber": "1", "offsetNumber": 2, "rValue": 4},
        ])
        state.extra["active_offset_number"] = 2
        state.extra["active_tool_number"] = 1
        self.assertEqual(ToolDataResolver().resolve(state).radius, 3)
        state.extra.pop("active_tool_number")
        state.extra["active_tool_name"] = "1"
        self.assertEqual(ToolDataResolver().resolve(state).radius, 4)

    def test_tool_data_validation_is_atomic(self):
        state = CNCState(machine_config=get_machine_config("FANUC_MILL"))
        load_tool_data(state, [{"toolNumber": "1", "rValue": 2}], [])
        for offsets in [
            [{"offsetNumber": 2, "rValue": float("nan")}],
            [{"offsetNumber": 2}, {"offsetNumber": 2}],
            [{"offsetNumber": 2, "toolNumber": 1}],
        ]:
            with self.assertRaises(ValueError):
                load_tool_data(state, [{"toolNumber": 1}], offsets)
            self.assertIn("1", state.extra["tool_compensation_data"])

    def _state(self, mode="LEFT"):
        state = CNCState(tool_path_mode="center")
        state.extra["g_group_16_plane"] = "X_Y"
        state.extra["active_tool_number"] = 1
        state.tool_compensation = ToolCompensationState(radius_mode=mode, radius=1.0)
        return state

    def test_g41_offsets_left_and_joins_consecutive_lines(self):
        state = self._state("LEFT")
        compensator = ToolPathCompensator()

        first = compensator.project([Point(0, 0, 0), Point(10, 0, 0)], state)
        second = compensator.project([Point(10, 0, 0), Point(10, 10, 0)], state)

        self.assertEqual((first[0].x, first[0].y), (0.0, 1.0))
        self.assertEqual((first[-1].x, first[-1].y), (9.0, 1.0))
        self.assertEqual((second[0].x, second[0].y), (9.0, 1.0))
        self.assertEqual((second[-1].x, second[-1].y), (9.0, 10.0))

    def test_g42_offsets_right(self):
        state = self._state("RIGHT")

        result = ToolPathCompensator().project(
            [Point(0, 0, 0), Point(10, 0, 0)],
            state,
        )

        self.assertEqual([(point.x, point.y) for point in result], [(0.0, -1.0), (10.0, -1.0)])

    def test_effective_mode_keeps_programmed_points(self):
        state = self._state("LEFT")
        state.tool_path_mode = "effective"
        points = [Point(0, 0, 0), Point(10, 0, 0)]

        result = ToolPathCompensator().project(points, state)

        self.assertIs(result, points)
        self.assertEqual([(point.x, point.y) for point in result], [(0, 0), (10, 0)])


if __name__ == "__main__":
    unittest.main()