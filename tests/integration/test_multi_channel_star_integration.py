import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.shared import configure_logging, configure_i18n


class TestMultiChannelStarIntegration(unittest.TestCase):
    """End-to-end integration test running multi-channel NC programs on a multi-axis Star lathe."""

    def setUp(self):
        configure_logging(console=False, web_buffer=True)
        configure_i18n()

    def test_multi_channel_axis_binding_and_wait_sync(self):
        """Test full program flow with 2 channels:
        - Logical axis mapping (X->X1, X->X2, C->C1, C->C2, B->B1)
        - Dynamic axis switching via M171/M172
        - Explicit axis syntax (e.g. Z3=...)
        - Wait-code synchronization (M300, M500 with P12)
        - Shared machine state (physical axes and common variables #500+)
        """
        config = get_machine_config("FANUC_STAR_SR20R_IV_B")

        # Two-channel NC programs
        # Channel 1:
        # - Sets common parameter #501=12.5
        # - Moves X, Z, C, B in Channel 1 (X1, Z1, C1, B1)
        # - Reaches barrier M300
        # - Switches to sub-spindle coordinate mode with M171 (X -> X2, C -> C2)
        # - Moves X and C
        # - Switches back with M172
        # - Reaches barrier M500 P12
        prog_ch1 = """
        G98;
        #501 = 12.5;
        G0 X20.0 Z10.0 C90.0 B30.0;
        M300;
        M171;
        G0 X14.0 C180.0;
        M172;
        G0 X30.0;
        M500 P12;
        """

        # Channel 2:
        # - Moves X, Z, C in Channel 2 (X2, Z2, C2)
        # - Reaches barrier M300
        # - Also executes M171 wait-code barrier with Ch1
        # - Reads common parameter #502 = #501 * 2
        # - Performs motion
        # - Reaches barrier M172 with Ch1
        # - Reaches barrier M500 P12
        prog_ch2 = """
        G98;
        G0 X10.0 Z5.0 C45.0;
        M300;
        M171;
        #502 = #501 * 2;
        G0 X8.0 Z15.0;
        M172;
        M500 P12;
        """

        control = UniversalConfigDrivenControl(
            count_of_canals=2,
            init_nc_states=[CNCState(machine_config=config), CNCState(machine_config=config)],
        )
        engine = NCExecutionEngine(control)

        result = engine.get_Syncro_plot([prog_ch1, prog_ch2], synch=True)

        # 1. Verification of execution results
        self.assertEqual(len(engine.errors), 0, f"Execution had errors: {engine.errors}")
        self.assertEqual(len(result), 2)
        for ch_res in result:
            self.assertIn("plot", ch_res)
            self.assertGreater(len(ch_res["plot"]), 0)

        # 2. Shared MachineState verification
        state1 = control.get_nc_state(1)
        state2 = control.get_nc_state(2)

        self.assertIsNotNone(state1)
        self.assertIsNotNone(state2)
        self.assertIs(state1.machine_state, state2.machine_state)

        # Common global parameter #501 written by Ch1 and #502 computed by Ch2
        self.assertAlmostEqual(state1.get_parameter(501), 12.5)
        self.assertAlmostEqual(state2.get_parameter(501), 12.5)
        self.assertAlmostEqual(state1.get_parameter(502), 25.0)
        self.assertAlmostEqual(state2.get_parameter(502), 25.0)

        # Verify physical axes on the shared machine state:
        # Ch1 moved B to 30.0 -> maps to B1
        self.assertAlmostEqual(state1.get_axis("B1"), 30.0)
        self.assertAlmostEqual(state2.get_axis("B1"), 30.0)

        # Ch1 M172 final motion was X30.0 (diameter 30.0 -> radius 15.0)
        self.assertAlmostEqual(state1.get_axis("X1"), 15.0)

        # Ch1 M171 moved X14.0 -> mapped to X2 (diameter 14.0 -> radius 7.0)
        # Ch2 then moved X8.0 -> mapped to X2 (diameter 8.0 -> radius 4.0)
        self.assertAlmostEqual(state2.get_axis("X2"), 4.0)

        # 3. WaitCodeHandler verification on executed nodes
        exec_nodes_ch1 = control.get_exected_nodes(1)
        exec_nodes_ch2 = control.get_exected_nodes(2)

        wait_nodes_ch1 = [
            node.extra.get("wait_code")
            for node in exec_nodes_ch1
            if hasattr(node, "extra") and "wait_code" in node.extra
        ]
        self.assertTrue(any(w["code"] == 300 for w in wait_nodes_ch1))
        self.assertTrue(any(w["code"] == 500 and w["p"] == 12 for w in wait_nodes_ch1))

        wait_nodes_ch2 = [
            node.extra.get("wait_code")
            for node in exec_nodes_ch2
            if hasattr(node, "extra") and "wait_code" in node.extra
        ]
        self.assertTrue(any(w["code"] == 300 for w in wait_nodes_ch2))
        self.assertTrue(any(w["code"] == 500 and w["p"] == 12 for w in wait_nodes_ch2))

    def test_o1234_two_channel_sr20r_iv_b_program_with_poses_and_compensation(self):
        """Run the full O1234 two-channel Star SR-20R IV Type B demo program with tool compensation and poses."""
        from ncplot7py.domain.tool_compensation import load_tool_data

        prog_p1 = """
((DEMO TEIL))

#531=20.0
#510=#531+1.0
G266A#531W40.0S3000X-2.0Z145.0F0.02B2.2K0.0
G97
G40M9
G125
G0M38
G300
G170
G99M3S500
M11
G0Z[#533-0.15]T0
M200
M20
G553
M10
G171
T100
G0X[#531+1.0]W-0.5M25
M192G0Z0.0
M27(CUT OFF CHECK)

N200
M03S2000
T200(TRUNING FRONT)
G0X[#531+1.0]Z0.0T02
G1X-0.5F0.02
G1W-0.5
G1Z0X0G41F0.1
G1X6.0F0.02
G1Z2.0X10.0
G1Z20.0
G1X9.8W.5
G1W0.5
G1X15.0
G1Z15.0
G1X21.0
G40
G0T0
N200
M03S1500
G0Z-5.0
T1100(ZENTER FRONT 4MM)
G0X0Y0T11
G0Z-1.0
G83Z10.0R0.0Q2000P1000F0.04
G80
G0Z-5.0
G0T0
T1200(DRILLING FRONT 4MM)
G0X0Y0T12
G0Z-1.0
G83Z10.0R0.0Q2000P1000F0.04
G80
G0Z-5.0
G0T0
M5
M36S3000

T3100(CROSS MILLING HOLE 4MM)
G0X[#531+1.0]Y0Z20.0T31
G19
#1 = [#531+1.0]
#2 = 4.0
#3 = -0.2
G1W-2.0G41
WHILE[#1GT#2]DO1
#1=[#1+#3]
G2W0.0K2.0U#3
END1
G0W2.0
G40
G0X[#531+1.0]Y0

G0X[#531+1.0]Y0Z20.0H180
G19
#1 = [#531+1.0]
#2 = 4.0
#3 = -0.2
G1W-2.0G41
WHILE[#1GT#2]DO1
#1=[#1+#3]
G2W0.0K2.0U#3
END1
G0W2.0
G40
G0X[#531+1.0]Y0
G0T0
M9
M38
M3S3000
T1300(TURNING INNERT FRONT 4MM)
G18
G0X6.0Y0T13
G0Z-1.0
G0G41Z0X5.5
G1X5.0,R0.2
G1Z5.0
G0X3.0
G0Z-5.0
G0T0
M5
M500
(CUT-OFF)
T100M3S#529
G0X[#531+1.0]Z[#530+#528+#533+0.02]T1
M82
M600
G1X#524F#522
M610
M83

M80
(BAR REPLACEMENT)
/G0X[#531+1.0]W-0.5
/G0W#528
/M98P7000
M81

M99
(@NCE-SIM:1 BEGIN SETUP)
(machineName="FANUC_STAR_SR20R_IV_B")
(material={"type":"cylinder","diameter":20,"length":45,"zeroVertex":0,"channelReferences":{"2":{"zeroVertex":1,"rotation":[180,0,0]}}})
(@NCE-SIM:1 END SETUP)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=100)
(description="Cut-Off Tool L 3 mm")
(Q=3)
(R=0.2)
(holder=[{"type":"turningHolderProfile","width":12,"depth":12,"outline":[[-0.5,1],[-0.5,40],[-12.5,40],[-12.5,14],[-7.5,9],[-7.5,1.367]],"stickOut":15,"position":[0,0,10]}])
(cutting=[{"type":"insert","shape":"L","ic":4.7625,"thickness":1.59,"noseRadius":0.2,"clearanceAngle":7,"width":3,"length":6.25,"zeroVertex":0,"rotation":[0,-45,0]}])
(orientation=[0,90,0])
(turning={"hand":"right","mount":"front","approachAngle":93,"activeCorner":"front-right","reference":"virtualTip"})
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=200)
(description="Turning Insert V 4.8 mm")
(Q=3)
(R=0.2)
(holder=[{"type":"turningHolderProfile","width":12,"depth":12,"outline":[[-0.5,1],[-0.5,40],[-12.5,40],[-12.5,14],[-7.5,9],[-7.5,1.367]],"stickOut":15,"position":[0,0,3]}])
(cutting=[{"type":"insert","shape":"V","ic":4.7625,"thickness":1.59,"noseRadius":0.2,"clearanceAngle":7,"zeroVertex":0,"position":[-8,0,0],"rotation":[0,19,0]}])
(orientation=[0,90,0])
(turning={"hand":"right","mount":"front","approachAngle":93,"activeCorner":"front-right","reference":"virtualTip"})
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=1100)
(description="Front Drill 4 mm")
(Q=0)
(R=2)
(holder=[{"type":"cylinder","diameter":4,"length":16,"stickOut":24}])
(cutting=[{"type":"drill","diameter":4,"length":24,"tipAngle":118}])
(orientation=[0,180,0])
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=1200)
(description="Drill 4 mm")
(Q=0)
(R=2)
(holder=[{"type":"cylinder","diameter":4,"length":16,"stickOut":24}])
(cutting=[{"type":"drill","diameter":4,"length":24,"tipAngle":118}])
(orientation=[0,180,0])
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=3100)
(description="Counter Face End Mill 1 mm")
(Q=9)
(R=0.5)
(holder=[{"type":"cylinder","diameter":1,"length":12,"stickOut":3}])
(cutting=[{"type":"endMill","diameter":1,"length":3}])
(orientation=[0,90,0])
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=1300)
(description="Inner Turn V \\u00d83 mm Upper \\u0028+X\\u0029")
(Q=2)
(R=0.1)
(holder=[{"type":"turningHolderProfile","width":4,"depth":2.3,"outline":[[-0.4,0.25],[-12,0.25],[-14,0.975],[-34,0.975],[-34,-3.025],[-14,-3.025],[-12,-2.05],[-0.4,-2.05]],"stickOut":12,"position":[-1,0,2.5]}])
(cutting=[{"type":"insert","shape":"V","ic":0.85,"thickness":0.9,"noseRadius":0.1,"clearanceAngle":7,"zeroVertex":2,"rotation":[0,-249.5,0]}])
(orientation=[0,270,0])
(turning={"hand":"right","mount":"back","approachAngle":93,"activeCorner":"back-left","reference":"virtualTip"})
(@NCE-SIM:1 END TOOL)
"""

        prog_p2 = """
G130
G40G99M9
M5
G0T0
T2000
M200
M20
G553
M75

M03S2000
T2100(TURNING BACK)
G0X[#531+1.0]Z0.0
G1X-0.5F0.02
G1W-0.5
G1Z0X0G41F0.1
G1X6.0F0.02
G1Z2.0X10.0
G1Z20.0
G1X9.8W.5
G1W0.5
G1X15.0
G1Z15.0
G1X21.0
G40
G0T0
M03S2000
T2200(DRILLING FRONT 4MM)
G0X0Y0T12
G0Z-1.0
G83Z5.0R0.0Q5000P1000F0.04
G80
G0Z-5.0
G0T0

T2300(MILLING HEXAGON)
M5
G17
M56S4000
M8
G0C0
G0Z-1.0X0Y0T23
G1X3.0Y2.0G41
#1 = 0.0
#2 = 4.0
WHILE[#1LT#2]DO1
G1Y3.5X0R0.2W0.1
G1X-3.0Y2.0R0.2W0.1
G1X-3.0Y-2.0R0.2W0.1
G1Y-3.5X0R0.2
G1X3.0Y-2.0R0.2
G1X3.0Y2.0
#1=[#1+0.5]
END1
G0X0Y0
G40
G0Z-1
G0T0
M9

(PARTS EJECTION)
/T2900M5
/G130
/G0Z42.5
/M11
/G4U1.0
/M84
/G28W0
/M27
/G0V100.0
/G4U1.0
/G0V-100.0
/M14
/T2000
/M15
M76
M500
(PICK-UP)
G900J50
T2000
M4S#529
M11
M82
G131B10.0
G0Z-5.0
M68
M14
G98G1Z20.0F2000.0
M15
G99M10
G133
M69
M600
M610
M68
G0W-20.0
M69
M83
G0T0
G28W0
G130
M5
M27
N50
M99
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=2000)
(description="Empty Tool \\u0028No Cutter\\u0029")
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=2900)
(description="Empty Tool \\u0028No Cutter\\u0029")
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=2100)
(description="Turning Insert V 4.8 mm")
(Q=3)
(R=0.2)
(holder=[{"type":"turningHolderProfile","width":12,"depth":12,"outline":[[-0.5,1],[-0.5,40],[-12.5,40],[-12.5,14],[-7.5,9],[-7.5,1.367]],"stickOut":15,"position":[0,0,3]}])
(cutting=[{"type":"insert","shape":"V","ic":4.7625,"thickness":1.59,"noseRadius":0.2,"clearanceAngle":7,"zeroVertex":0,"position":[-8,0,0],"rotation":[0,19,0]}])
(orientation=[0,90,0])
(turning={"hand":"right","mount":"front","approachAngle":93,"activeCorner":"front-right","reference":"virtualTip"})
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN SETUP)
(machineName="FANUC_STAR_SR20R_IV_B")
(material={"type":"cylinder","diameter":20,"length":45,"zeroVertex":0,"channelReferences":{"2":{"zeroVertex":1,"rotation":[180,0,0]}}})
(@NCE-SIM:1 END SETUP)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=2200)
(description="Drill 4 mm")
(Q=0)
(R=2)
(holder=[{"type":"cylinder","diameter":4,"length":16,"stickOut":24}])
(cutting=[{"type":"drill","diameter":4,"length":24,"tipAngle":118}])
(orientation=[0,180,0])
(@NCE-SIM:1 END TOOL)
(@NCE-SIM:1 BEGIN TOOL)
(toolNumber=2300)
(description="End Mill 0.5 mm")
(R=0.25)
(holder=[{"type":"cylinder","diameter":0.5,"length":12,"stickOut":3}])
(cutting=[{"type":"endMill","diameter":0.5,"length":3}])
(orientation=[0,180,90])
(@NCE-SIM:1 END TOOL)
"""

        config = get_machine_config("FANUC_STAR_SR20R_IV_B")
        state1 = CNCState(machine_config=config, tool_path_mode="center")
        state2 = CNCState(machine_config=config, tool_path_mode="center")

        load_tool_data(state1, [
            {"toolNumber": 100, "qValue": 3, "rValue": 0.2},
            {"toolNumber": 200, "qValue": 3, "rValue": 0.2},
            {"toolNumber": 1100, "qValue": 0, "rValue": 2.0},
            {"toolNumber": 1200, "qValue": 0, "rValue": 2.0},
            {"toolNumber": 3100, "qValue": 9, "rValue": 0.5},
            {"toolNumber": 1300, "qValue": 2, "rValue": 0.1},
        ], [])
        load_tool_data(state2, [
            {"toolNumber": 2000, "rValue": 0.0},
            {"toolNumber": 2900, "rValue": 0.0},
            {"toolNumber": 2100, "qValue": 3, "rValue": 0.2},
            {"toolNumber": 2200, "qValue": 0, "rValue": 2.0},
            {"toolNumber": 2300, "rValue": 0.25},
        ], [])

        state1.channel_state.pose_tools = {
            100: {"reference": "turningVirtualTip", "mountingOrientationDegrees": [0, 90, 0]},
            200: {"reference": "turningVirtualTip", "mountingOrientationDegrees": [0, 90, 0]},
            1100: {"reference": "millingTip", "mountingOrientationDegrees": [0, 180, 0]},
            1200: {"reference": "millingTip", "mountingOrientationDegrees": [0, 180, 0]},
            3100: {"reference": "millingTip", "mountingOrientationDegrees": [0, 90, 0]},
            1300: {"reference": "turningVirtualTip", "mountingOrientationDegrees": [0, 270, 0]},
        }
        state2.channel_state.pose_tools = {
            2000: {"reference": "millingTip", "mountingOrientationDegrees": [0, 0, 0]},
            2900: {"reference": "millingTip", "mountingOrientationDegrees": [0, 0, 0]},
            2100: {"reference": "turningVirtualTip", "mountingOrientationDegrees": [0, 90, 0]},
            2200: {"reference": "millingTip", "mountingOrientationDegrees": [0, 180, 0]},
            2300: {"reference": "millingTip", "mountingOrientationDegrees": [0, 180, 90]},
        }

        control = UniversalConfigDrivenControl(
            count_of_canals=2,
            init_nc_states=[state1, state2],
        )
        engine = NCExecutionEngine(control)
        result = engine.get_Syncro_plot([prog_p1, prog_p2], synch=True)

        self.assertEqual(len(engine.errors), 0, f"Execution had errors: {engine.errors}")
        self.assertEqual(len(result), 2)

        ch1_plot = result[0]["plot"]
        ch2_plot = result[1]["plot"]
        self.assertGreater(len(ch1_plot), 0)
        self.assertGreater(len(ch2_plot), 0)

        # Verify Channel 1 T3100 cross-milling arcs before (C1=0) and after H180 (C1=180 backside)
        t3100_arcs = [
            seg for seg in ch1_plot
            if seg["toolNumber"] == 3100 and seg["geometry"] == "ARC_CW"
        ]
        self.assertEqual(len(t3100_arcs), 172)  # 86 helical loops at C1=0 + 86 at C1=180

        c0_arcs = [seg for seg in t3100_arcs if seg["motionContext"]["endAxes"].get("C1") == 0.0]
        c180_arcs = [seg for seg in t3100_arcs if seg["motionContext"]["endAxes"].get("C1") == 180.0]
        self.assertEqual(len(c0_arcs), 86)
        self.assertEqual(len(c180_arcs), 86)

        # Both frontside (C1=0) and backside (C1=180) G19 G41 holes must have the same compensated 5.0mm span
        for arc in (c0_arcs[0], c0_arcs[-1], c180_arcs[0], c180_arcs[-1]):
            self.assertAlmostEqual(max(arc["y"]) - min(arc["y"]), 5.0, delta=0.05)
            self.assertAlmostEqual(max(arc["z"]) - min(arc["z"]), 5.0, delta=0.05)
            self.assertEqual(arc["poses"][0]["frameId"], "workpiece:mainSpindle")

        # C1=0 cuts from X=+10.5 down to +1.9; C1=180 cuts from X=-10.5 up to -1.9 in workpiece frame
        self.assertAlmostEqual(c0_arcs[0]["x"][0], 10.5, places=3)
        self.assertAlmostEqual(c0_arcs[-1]["x"][-1], 1.9, places=3)
        self.assertAlmostEqual(c180_arcs[0]["x"][0], -10.5, places=3)
        self.assertAlmostEqual(c180_arcs[-1]["x"][-1], -1.9, places=3)

        # Verify C1=180 tool pose orientation is rotated 180 degrees around Z relative to C1=0
        self.assertAlmostEqual(abs(c0_arcs[0]["poses"][0]["orientation"][1]), 0.70710678, places=5)
        self.assertAlmostEqual(abs(c0_arcs[0]["poses"][0]["orientation"][3]), 0.70710678, places=5)
        self.assertAlmostEqual(abs(c180_arcs[0]["poses"][0]["orientation"][0]), 0.70710678, places=5)
        self.assertAlmostEqual(abs(c180_arcs[0]["poses"][0]["orientation"][2]), 0.70710678, places=5)

        # Verify Channel 2 backside tools (T2100 turning, T2200 drilling, T2300 hexagon milling) emit subSpindle poses
        ch2_Moving_tools = {seg["toolNumber"] for seg in ch2_plot if seg.get("poses")}
        self.assertTrue({2000, 2100, 2200, 2300}.issubset(ch2_Moving_tools))
        for seg in ch2_plot:
            for pose in seg.get("poses", ()):
                self.assertEqual(pose["frameId"], "workpiece:subSpindle")

    def test_o1234fin_backside_runtime_and_m20_cycle_start_cutoff(self):
        """Verify backside (P2) calculated runtime is 2 min 40 sec (160s) +/- 10% and M20 start flag stops on 2nd hit."""
        from ncplot7py.domain.tool_compensation import load_tool_data

        prog_p2_backside = """
G130 
G40G99M9 
M5 
G0T0 
T2000
M200 
M20
 
M75
 
M03S800
T2400(TURNING BACK)
G18
G0X[#531+1.0]Z0.0
G1X-0.5F0.1
G1W-0.5
G1Z0X0G41F0.1
G1X6.0F0.1 
G1Z2.0X10.0
G1Z20.0
G1X9.8W.5
G1W0.5 
G1X15.0
G1Z15.0
G1X21.0
G40
G0T0 
M03S500
T2400(DRILLING FRONT 4MM)
G0X0Y0T12
G0Z-1.0
G83Z5.0R0.0Q5000P1000F0.1
G80
G0Z-5.0
G0T0 
 
T2400(MILLING HEXAGON) 
M5 
G17
M56S500
M8 
G0C0 
G0Z-1.0X0Y0T23 
G1X3.0Y2.0F0.1G41
#1=0.0 
#2=4.0 
WHILE[#1LT#2]DO1 
G1Y3.5X0R0.2W0.1 
G1X-3.0Y2.0R0.2W0.1
G1X-3.0Y-2.0R0.2W0.1 
G1Y-3.5X0R0.2
G1X3.0Y-2.0R0.2
G1X3.0Y2.0 
#1=[#1+0.5]
END1 
G0X0Y0 
G40
G0Z-1
G0T0 
M58
M9 
 
G18
M00
(PARTS EJECTION) 
/T2900M5 
/G130
/G0Z42.5 
/M11 
/G4U1.0
/M84 
/G28W0 
/M27 
/G0V100.0
/G4U1.0
/G0V-100.0 
/M14 
/T2000 
/M15 
M76
M500 
(PICK-UP)
G900J50
T2000
M4S#529
M11
M82
G131B10.0
G0Z-5.0
M68
M14
G98G1Z20.0F2000.0
M15
G99M10 
G133 
M69
M600 
M610 
M68
G0W-20.0 
M69
M83
G0T0 
G28W0
G130 
M5 
M27
N50
M99
"""

        config = get_machine_config("FANUC_STAR_SR20R_IV_B")
        self.assertEqual(config.cycle_start_code, "M20")

        state2 = CNCState(machine_config=config, tool_path_mode="center")
        state2.set_parameter("531", 20.0)
        state2.set_parameter("529", 3000.0)
        load_tool_data(state2, [
            {"toolNumber": 2000, "rValue": 0.0},
            {"toolNumber": 2900, "rValue": 0.0},
            {"toolNumber": 2100, "qValue": 3, "rValue": 0.2},
            {"toolNumber": 2200, "qValue": 0, "rValue": 2.0},
            {"toolNumber": 2300, "rValue": 0.25},
            {"toolNumber": 2400, "rValue": 0.25},
        ], [])

        control = UniversalConfigDrivenControl(
            count_of_canals=1,
            canal_names=["2"],
            init_nc_states=[state2],
        )
        engine = NCExecutionEngine(control)
        result = engine.get_Syncro_plot([prog_p2_backside], synch=False, channel_number=2)

        self.assertEqual(len(engine.errors), 0, f"Execution had errors: {engine.errors}")
        self.assertEqual(len(result), 1)

        # Target runtime: 2 min 40 sec = 160s +/- 10% ([144.0s, 176.0s])
        runtime = engine.get_cacluated_runtime()
        self.assertAlmostEqual(runtime, 160.0, delta=16.0)
        self.assertEqual(state2.channel_state.cycle_start_count, 1)

        # Verify that a second M20 in a looped/continued Star Fanuc program halts execution
        prog_with_second_m20 = (
            "G98\n"
            "G0 X10.0 Z0.0\n"
            "M20\n"
            "G1 Z10.0 F100.0\n"
            "M20\n"
            "G1 Z50.0 F100.0\n"
        )
        state_cutoff = CNCState(machine_config=config)
        ctrl_cutoff = UniversalConfigDrivenControl(count_of_canals=1, init_nc_states=[state_cutoff])
        eng_cutoff = NCExecutionEngine(ctrl_cutoff)
        res_cutoff = eng_cutoff.get_Syncro_plot([prog_with_second_m20], synch=False)

        self.assertEqual(len(eng_cutoff.errors), 0)
        self.assertEqual(state_cutoff.channel_state.cycle_start_count, 1)
        # Z10.0 after the first M20 executes, but Z50.0 after the second M20 is not reached
        z_endpoints = [seg["z"][-1] for seg in res_cutoff[0]["plot"] if seg["z"]]
        self.assertIn(10.0, z_endpoints)
        self.assertNotIn(50.0, z_endpoints)


if __name__ == "__main__":
    unittest.main()

