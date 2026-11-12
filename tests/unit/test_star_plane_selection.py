import math
import unittest

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionNode
from ncplot7py.domain.handlers.fanuc_turn_cnc.g92_threading_cycle import FanucG92ThreadingCycleHandler
from ncplot7py.domain.handlers.motion import MotionHandler
from ncplot7py.domain.handlers.star_machine.plane_selection_handler import StarPlaneSelectionHandler
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.tool_compensation import ToolCompensationState, ToolPathCompensator
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenCanal
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class TestStarPlaneSelection(unittest.TestCase):
    def test_selects_g117_g118_g119_and_switches_back_to_g18(self):
        handler = StarPlaneSelectionHandler()
        state = CNCState()

        for code, expected_plane in (
            ("G117", "Y_X"),
            ("G118", "Z_X"),
            ("G119", "Z_Y"),
            ("G18", "X_Z"),
        ):
            handler.handle(NCCommandNode(g_code_command={code}), state)
            self.assertEqual(state.channel_state.plane, expected_plane)
            self.assertEqual(state.extra["g_group_16_plane"], expected_plane)
            self.assertEqual(state.get_modal("g_group_16_plane_code"), code)

    def test_rejects_conflicting_plane_codes_in_same_block(self):
        handler = StarPlaneSelectionHandler()
        state = CNCState()

        with self.assertRaises(ExceptionNode) as error:
            handler.handle(NCCommandNode(g_code_command={"G18", "G118"}), state)

        self.assertEqual(error.exception.code, 120)

    def test_rejects_plane_selection_while_g41_g42_active_without_g40(self):
        handler = StarPlaneSelectionHandler()
        state = CNCState()
        state.set_modal("tool_nose_compensation", "G41")

        with self.assertRaises(ExceptionNode) as error:
            handler.handle(NCCommandNode(g_code_command={"G118"}), state)

        self.assertEqual(error.exception.code, 499)

        # Allowed when G40 cancels compensation in the block
        handler.handle(NCCommandNode(g_code_command={"G40", "G118"}), state)
        self.assertEqual(state.channel_state.plane, "Z_X")

    def test_g118_reverses_arc_direction_compared_to_g18(self):
        # Start at (X=2, Z=0), move to (X=0, Z=2) with R=2.0
        # In G18 (Z-X), G2 sweeps through the +X/+Z quadrant (mid ~ sqrt(2), sqrt(2))
        # In G118 (X-Z), G2 has the opposite arc direction (same path as G3 in G18),
        # so G3 in G118 matches G2 in G18.
        chain_g18 = StarPlaneSelectionHandler(next_handler=MotionHandler())
        state_g18 = CNCState(axes={"X": 2.0, "Y": 0.0, "Z": 0.0}, feed_rate=60.0)
        chain_g18.handle(NCCommandNode(g_code_command={"G18"}), state_g18)
        pts_g18_g2, _ = chain_g18.handle(
            NCCommandNode(g_code_command={"G2"}, command_parameter={"X": "0.0", "Z": "2.0", "R": "2.0"}),
            state_g18,
        )

        chain_g118 = StarPlaneSelectionHandler(next_handler=MotionHandler())
        state_g118_g2 = CNCState(axes={"X": 2.0, "Y": 0.0, "Z": 0.0}, feed_rate=60.0)
        chain_g118.handle(NCCommandNode(g_code_command={"G118"}), state_g118_g2)
        pts_g118_g2, _ = chain_g118.handle(
            NCCommandNode(g_code_command={"G2"}, command_parameter={"X": "0.0", "Z": "2.0", "R": "2.0"}),
            state_g118_g2,
        )

        state_g118_g3 = CNCState(axes={"X": 2.0, "Y": 0.0, "Z": 0.0}, feed_rate=60.0)
        chain_g118.handle(NCCommandNode(g_code_command={"G118"}), state_g118_g3)
        pts_g118_g3, _ = chain_g118.handle(
            NCCommandNode(g_code_command={"G3"}, command_parameter={"X": "0.0", "Z": "2.0", "R": "2.0"}),
            state_g118_g3,
        )

        mid_g18_g2 = pts_g18_g2[len(pts_g18_g2) // 2]
        mid_g118_g2 = pts_g118_g2[len(pts_g118_g2) // 2]
        mid_g118_g3 = pts_g118_g3[len(pts_g118_g3) // 2]

        # G118 G3 matches G18 G2 (+sqrt(2), +sqrt(2))
        self.assertAlmostEqual(mid_g118_g3.x, mid_g18_g2.x, places=5)
        self.assertAlmostEqual(mid_g118_g3.z, mid_g18_g2.z, places=5)
        # G118 G2 sweeps the opposite side of the chord from G18 G2
        self.assertNotAlmostEqual(mid_g118_g2.x, mid_g18_g2.x, places=2)

    def test_g117_and_g119_reverse_arc_directions_compared_to_g17_and_g19(self):
        chain = StarPlaneSelectionHandler(next_handler=MotionHandler())

        # G17 vs G117
        s_g17 = CNCState(axes={"X": 2.0, "Y": 0.0, "Z": 0.0}, feed_rate=60.0)
        chain.handle(NCCommandNode(g_code_command={"G17"}), s_g17)
        pts_g17, _ = chain.handle(
            NCCommandNode(g_code_command={"G3"}, command_parameter={"X": "0.0", "Y": "2.0", "R": "2.0"}),
            s_g17,
        )

        s_g117 = CNCState(axes={"X": 2.0, "Y": 0.0, "Z": 0.0}, feed_rate=60.0)
        chain.handle(NCCommandNode(g_code_command={"G117"}), s_g117)
        pts_g117, _ = chain.handle(
            NCCommandNode(g_code_command={"G2"}, command_parameter={"X": "0.0", "Y": "2.0", "R": "2.0"}),
            s_g117,
        )
        self.assertAlmostEqual(pts_g17[len(pts_g17) // 2].x, pts_g117[len(pts_g117) // 2].x, places=5)
        self.assertAlmostEqual(pts_g17[len(pts_g17) // 2].y, pts_g117[len(pts_g117) // 2].y, places=5)

        # G19 vs G119
        s_g19 = CNCState(axes={"X": 0.0, "Y": 2.0, "Z": 0.0}, feed_rate=60.0)
        chain.handle(NCCommandNode(g_code_command={"G19"}), s_g19)
        pts_g19, _ = chain.handle(
            NCCommandNode(g_code_command={"G3"}, command_parameter={"Y": "0.0", "Z": "2.0", "R": "2.0"}),
            s_g19,
        )

        s_g119 = CNCState(axes={"X": 0.0, "Y": 2.0, "Z": 0.0}, feed_rate=60.0)
        chain.handle(NCCommandNode(g_code_command={"G119"}), s_g119)
        pts_g119, _ = chain.handle(
            NCCommandNode(g_code_command={"G2"}, command_parameter={"Y": "0.0", "Z": "2.0", "R": "2.0"}),
            s_g119,
        )
        self.assertAlmostEqual(pts_g19[len(pts_g19) // 2].y, pts_g119[len(pts_g119) // 2].y, places=5)
        self.assertAlmostEqual(pts_g19[len(pts_g19) // 2].z, pts_g119[len(pts_g119) // 2].z, places=5)

    def test_ps0499_triggered_for_forbidden_functions_on_reversed_planes(self):
        handler = StarPlaneSelectionHandler()

        forbidden_cases = [
            ("G118", {"G71"}, {"U": "1.0", "R": "0.5"}),
            ("G118", {"G76"}, {"P": "010060", "Q": "100", "R": "0.05"}),
            ("G118", {"G83"}, {"Z": "10.0", "R": "0.0", "Q": "2000", "F": "0.1"}),
            ("G117", {"G90"}, {"X": "10.0", "Z": "20.0", "F": "0.1"}),
            ("G119", {"G94"}, {"X": "10.0", "Z": "20.0", "F": "0.1"}),
            ("G118", {"G92"}, {"X": "10.0", "Z": "20.0", "F": "1.0"}),
            ("G117", {"G92"}, {"X": "10.0", "Z": "20.0", "F": "1.0"}),
            ("G118", {"G107"}, {"C": "10.0"}),
            ("G118", {"G112"}, {}),
            ("G118", {"G31"}, {"Z": "10.0", "F": "100"}),
            # Helical interpolation on G118 (Z_X plane with Y/V word)
            ("G118", {"G2"}, {"X": "10.0", "Z": "10.0", "Y": "2.0", "R": "5.0"}),
            # Direct drawing dimension programming / chamfering on G118
            ("G118", {"G1"}, {"X": "10.0", "Z": "10.0", "A": "30.0"}),
        ]

        for plane_code, g_codes, params in forbidden_cases:
            with self.subTest(plane_code=plane_code, g_codes=g_codes, params=params):
                state = CNCState()
                handler.handle(NCCommandNode(g_code_command={plane_code}), state)
                with self.assertRaises(ExceptionNode) as error:
                    handler.handle(
                        NCCommandNode(g_code_command=set(g_codes), command_parameter=dict(params)),
                        state,
                    )
                self.assertEqual(error.exception.code, 499)

        # Comma cornering (,C / ,R) on G118 also raises PS0499
        state = CNCState()
        handler.handle(NCCommandNode(g_code_command={"G118"}), state)
        with self.assertRaises(ExceptionNode) as error:
            handler.handle(
                NCCommandNode(
                    g_code_command={"G1"},
                    command_parameter={"X": "10.0"},
                    dddp_command={",R0.5"},
                ),
                state,
            )
        self.assertEqual(error.exception.code, 499)

    def test_g92_is_allowed_on_g119_zy_plane(self):
        chain = StarPlaneSelectionHandler(next_handler=FanucG92ThreadingCycleHandler())
        state = CNCState(axes={"X": 0.0, "Y": 12.0, "Z": 0.0}, spindle_speed=1500.0)

        chain.handle(NCCommandNode(g_code_command={"G119"}), state)
        points, duration = chain.handle(
            NCCommandNode(
                g_code_command={"G92"},
                command_parameter={"Y": "10.0", "Z": "15.0", "F": "1.25"},
            ),
            state,
        )

        self.assertTrue(points)
        self.assertGreater(duration, 0.0)
        self.assertEqual(state.fanuc_state.threading_active, "G92")
        self.assertAlmostEqual(state.get_axis("Y"), 12.0)
        self.assertAlmostEqual(state.get_axis("Z"), 0.0)

    def test_tool_compensation_in_g118_preserves_star_tip_to_center_shift_and_inverts_normal(self):
        state = CNCState(
            machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"),
            tool_path_mode="center",
        )
        state.channel_state.plane = "Z_X"
        state.extra["active_tool_number"] = 1
        state.tool_compensation = ToolCompensationState(
            radius_mode="LEFT",
            radius=1.0,
            tip_orientation=3,
        )

        result = ToolPathCompensator().project([Point(0, 0, 0), Point(10, 0, 0)], state)
        # Move along +X in Z_X: left normal in (z, x) is (+1, 0) -> z -= 1.0, plus Q=3 shift (+1, +1) -> z=0.0, x+1.0
        self.assertEqual([(p.x, p.z) for p in result], [(1.0, 0.0), (11.0, 0.0)])

    def test_star_canal_wires_star_group_16_plane(self):
        state = CNCState(machine_config=get_machine_config("FANUC_STAR_SR20R_IV_B"))
        canal = UniversalConfigDrivenCanal("C1", init_state=state)
        canal.run_nc_code_list([
            NCCommandNode(g_code_command={"G118"}),
            NCCommandNode(g_code_command={"G1"}, command_parameter={"X": "10.0", "Z": "5.0", "F": "100.0"}),
        ])
        self.assertEqual(state.channel_state.plane, "Z_X")


if __name__ == "__main__":
    unittest.main()
