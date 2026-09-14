import unittest
import json
from copy import deepcopy
from dataclasses import asdict, replace
from unittest.mock import patch

from ncplot7py.domain.machines import get_machine_config, load_machine_configs
from ncplot7py.domain.simulation_contract import (
    POSE_CONTRACT, SimulationContractError, machine_simulation_metadata,
    validate_pose_request, validate_simulation_config,
)


def simulation():
    return {
        "schemaVersion": 1, "revision": 1, "modelId": "MILL_DEMO",
        "displayName": "MILL DEMO", "fidelity": "demo", "poseContract": POSE_CONTRACT,
        "carriers": [
            {"id": "spindle", "role": "tool",
             "referenceOrientationDegrees": [0, 0, 0], "rotationChain": []},
            {"id": "table", "role": "workpiece",
             "referenceOrientationDegrees": [0, 0, 0], "rotationChain": [
                {"axisId": "B", "axis": [0, 1, 0], "sign": 1, "zeroDegrees": 0},
            ]},
        ],
        "toolMounts": [{
            "channelId": "1", "tools": {"kind": "numericRange", "from": 0, "to": 10},
            "carrierId": "spindle",
            "target": {"mode": "fixed", "workpieceCarrierId": "table"},
        }],
    }


class TestSimulationContract(unittest.TestCase):
    def test_invalid_reload_preserves_entire_previous_registry(self):
        previous = get_machine_config("FANUC_MILL")
        data = asdict(previous)
        data["simulation"] = simulation()
        data["simulation"]["revision"] = 0
        with patch("ncplot7py.domain.machines.files") as resource:
            reader = resource.return_value.joinpath.return_value.read_text
            reader.return_value = json.dumps({"BROKEN": data})
            with self.assertRaisesRegex(ValueError, "Failed to load"):
                load_machine_configs()
        self.assertIs(get_machine_config("FANUC_MILL"), previous)

    def test_invalid_carrier_reference_and_transform_are_rejected(self):
        for field, value in (
            ("referenceOrientationDegrees", [0, 0, float("inf")]),
            ("id", "table"), ("unexpected", 1),
        ):
            data = simulation()
            data["carriers"][0][field] = value
            with self.assertRaises(ValueError):
                validate_simulation_config(data, 1, ("B",))
        data = simulation()
        data["toolMounts"][0]["target"]["workpieceCarrierId"] = "spindle"
        with self.assertRaises(ValueError):
            validate_simulation_config(data, 1, ("B",))

    def test_config_is_detached_and_not_automatic_pose_support(self):
        data = simulation()
        config = replace(
            get_machine_config("FANUC_MILL"), axes=("X", "Y", "Z", "B"), simulation=data,
        )
        metadata = machine_simulation_metadata(config)
        self.assertEqual(metadata["axes"], ["X", "Y", "Z", "B"])
        self.assertEqual(metadata["availableChannels"], 1)
        self.assertEqual(metadata["supportedPoseContracts"], [])
        data["revision"] = 20
        self.assertEqual(config.simulation["revision"], 1)
        changed = machine_simulation_metadata(replace(config, default_plane="G18"))
        self.assertNotEqual(metadata["profileRevision"], changed["profileRevision"])

    def test_numeric_and_named_ids_are_distinct_but_overlaps_reject(self):
        data = simulation()
        extra = deepcopy(data["toolMounts"][0])
        extra["tools"] = {"kind": "identifiers", "values": ["1"]}
        data["toolMounts"].append(extra)
        validate_simulation_config(data, 1, ("B",))
        for selector in (
            {"kind": "identifiers", "values": [1]},
            {"kind": "numericRange", "from": 10, "to": 20},
        ):
            extra["tools"] = selector
            with self.assertRaisesRegex(ValueError, "Overlapping"):
                validate_simulation_config(data, 1, ("B",))

    def test_invalid_config_is_not_silently_defaulted(self):
        for field, value in (
            ("schemaVersion", 2), ("revision", 0), ("poseContract", "future"),
        ):
            data = simulation()
            data[field] = value
            with self.assertRaises(ValueError):
                validate_simulation_config(data, 1, ("B",))
        with self.assertRaisesRegex(ValueError, "axis"):
            validate_simulation_config(simulation(), 1, ())
        data = simulation()
        data["toolMounts"][0]["channelId"] = "3"
        with self.assertRaisesRegex(ValueError, "channel"):
            validate_simulation_config(data, 2, ("B",))

    def test_pose_request_rejects_unknown_revision_and_unimplemented_producer(self):
        config = get_machine_config("FANUC_MILL")
        entry = {"program": "T1", "machineName": "FANUC_MILL", "canalNr": "1",
                 "simulation": {"profileRevision": "old", "tools": []}}
        payload = {
            "poseContract": POSE_CONTRACT,
            "toolPathMode": "center", "machinedata": [entry],
        }
        with self.assertRaises(SimulationContractError) as failure:
            validate_pose_request(payload, {"FANUC_MILL": config})
        self.assertEqual(failure.exception.code, "PROFILE_REVISION_MISMATCH")
        metadata = machine_simulation_metadata(config)
        entry["simulation"]["profileRevision"] = metadata["profileRevision"]
        with self.assertRaises(SimulationContractError) as failure:
            validate_pose_request(payload, {"FANUC_MILL": config})
        self.assertEqual(
            failure.exception.response()["errors"][0]["code"], "POSE_CONTRACT_UNSUPPORTED",
        )
        entry["simulation"]["tools"] = [{
            "toolNumber": 0, "reference": "millingTip",
            "mountingOrientationDegrees": [0, 0, 0],
        }]
        for change in (
            {"customMachineConfig": {}}, {"machineName": "missing"}, {"canalNr": "3"},
        ):
            invalid = deepcopy(payload)
            invalid["machinedata"][0].update(change)
            with self.assertRaises(SimulationContractError) as failure:
                validate_pose_request(invalid, {"FANUC_MILL": config})
            self.assertEqual(failure.exception.code, "SIMULATION_INPUT_INVALID")


if __name__ == "__main__":
    unittest.main()