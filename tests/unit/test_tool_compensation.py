import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.tool_compensation import ToolCompensationState, ToolPathCompensator
from ncplot7py.shared.point import Point


class TestToolPathCompensator(unittest.TestCase):
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