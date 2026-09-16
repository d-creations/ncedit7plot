"""Validate pose requests against static machine simulation capabilities."""
from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING

from ncplot7py.domain.machines import POSE_CONTRACT

if TYPE_CHECKING:
    from ncplot7py.domain.machines import MachineConfig

POSE_CONTRACT = "workpiece-tool-reference-v1"


class SimulationContractError(ValueError):
    def __init__(self, code: str, message: str, channel: str | None = None):
        super().__init__(message)
        self.code = code
        self.channel = channel

    def as_dict(self) -> dict[str, Any]:
        error = {"code": self.code, "message": str(self)}
        if self.channel is not None:
            error["channelId"] = self.channel
        return error


def _object(value: Any, required: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"Expected exactly these fields: {sorted(required)}")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Expected a nonempty identifier of at most 256 characters")
    return value


def _integer(value: Any, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 9007199254740991:
        raise ValueError("Expected a safe integer in the supported range")
    return value


def _vector(value: Any) -> list:
    if not isinstance(value, list) or len(value) != 3 or any(
        type(component) not in (int, float) for component in value
    ):
        raise ValueError("Expected three finite numbers")
    return value


def _identifier(value: Any) -> tuple[type, Any]:
    if type(value) is int:
        _integer(value)
    else:
        _text(value)
        if value == "unknown":
            raise ValueError("unknown is reserved for unavailable tools")
    return type(value), value


def validate_pose_request(payload: Any, profiles: Mapping[str, MachineConfig]) -> None:
    """Fail explicitly instead of silently treating a pose request as path-only."""
    if not isinstance(payload, dict):
        return
    entries = payload.get("machinedata")
    if "poseContract" not in payload:
        if isinstance(entries, list) and any(
            isinstance(entry, dict) and "simulation" in entry for entry in entries
        ):
            raise SimulationContractError(
                "SIMULATION_INPUT_INVALID", "simulation requires poseContract",
            )
        return
    if payload["poseContract"] != POSE_CONTRACT:
        raise SimulationContractError(
            "POSE_CONTRACT_UNSUPPORTED", "Unsupported poseContract",
        )
    if payload.get("toolPathMode") != "center":
        raise SimulationContractError(
            "SIMULATION_INPUT_INVALID", "Pose output requires toolPathMode center",
        )
    channel = None
    try:
        if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
            raise ValueError("Expected 1..3 machine entries")
        channels = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Machine entries must be objects")
            raw_channel = entry.get("canalNr")
            if type(raw_channel) not in (str, int):
                raise ValueError("Invalid canalNr")
            channel = str(raw_channel)
            if channel in channels:
                raise ValueError("Duplicate channel")
            channels.add(channel)
            if not isinstance(entry.get("program"), str):
                raise ValueError("program must be a string")
            name = _text(entry.get("machineName"))
            if name not in profiles or "customMachineConfig" in entry:
                raise ValueError(
                    "Pose output requires an exact server profile; BYOC is unsupported"
                )
            config = profiles[name]
            if channel not in {str(number) for number in range(1, config.channels + 1)}:
                raise ValueError("Channel not supported by profile")
            simulation = _object(entry.get("simulation"), {"profileRevision", "tools"})
            revision = _text(simulation["profileRevision"])
            metadata = config.simulation_metadata()
            if revision != metadata["profileRevision"]:
                raise SimulationContractError(
                    "PROFILE_REVISION_MISMATCH", "Reload changed machine profile", channel,
                )
            tools = simulation["tools"]
            if not isinstance(tools, list) or len(tools) > 4096:
                raise ValueError("Invalid simulation tools")
            identifiers = set()
            for tool in tools:
                _object(tool, {"toolNumber", "reference", "mountingOrientationDegrees"})
                identity = _identifier(tool["toolNumber"])
                if identity in identifiers:
                    raise ValueError("Duplicate simulation tool")
                identifiers.add(identity)
                if tool["reference"] not in ("millingTip", "turningVirtualTip"):
                    raise ValueError("Unsupported tool reference")
                _vector(tool["mountingOrientationDegrees"])
            if POSE_CONTRACT not in metadata["supportedPoseContracts"]:
                raise SimulationContractError(
                    "POSE_CONTRACT_UNSUPPORTED", "Machine profile has no verified pose producer", channel,
                )
            if config.simulation["modelId"] not in {"MILL_DEMO", "STAR_SR20R_IV_B", "STAR_SV20R", "STAR_SG42"}:
                raise SimulationContractError(
                    "POSE_CONTRACT_UNSUPPORTED", "Machine pose output is not implemented for this profile", channel,
                )
    except SimulationContractError:
        raise
    except (ValueError, TypeError) as error:
        raise SimulationContractError(
            "SIMULATION_INPUT_INVALID", str(error), channel,
        ) from error