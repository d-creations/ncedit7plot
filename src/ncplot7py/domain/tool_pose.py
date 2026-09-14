"""Pure workpiece-frame pose projection for verified demo profiles."""
from __future__ import annotations

import math
from typing import Any


class ToolPoseError(ValueError):
    """Raised when a requested pose cannot be resolved from execution data."""


def _matrix_multiply(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [[sum(left[row][index] * right[index][column] for index in range(3))
             for column in range(3)] for row in range(3)]


def _rotation_x(degrees: float) -> list[list[float]]:
    radians = math.radians(degrees)
    cosine, sine = math.cos(radians), math.sin(radians)
    return [[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]]


def _rotation_y(degrees: float) -> list[list[float]]:
    radians = math.radians(degrees)
    cosine, sine = math.cos(radians), math.sin(radians)
    return [[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]]


def _rotation_z(degrees: float) -> list[list[float]]:
    radians = math.radians(degrees)
    cosine, sine = math.cos(radians), math.sin(radians)
    return [[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]]


def _quaternion(matrix: list[list[float]]) -> list[float]:
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        quaternion = [(matrix[2][1] - matrix[1][2]) / scale,
                      (matrix[0][2] - matrix[2][0]) / scale,
                      (matrix[1][0] - matrix[0][1]) / scale, 0.25 * scale]
    elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2
        quaternion = [0.25 * scale, (matrix[0][1] + matrix[1][0]) / scale,
                      (matrix[0][2] + matrix[2][0]) / scale, (matrix[2][1] - matrix[1][2]) / scale]
    elif matrix[1][1] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2
        quaternion = [(matrix[0][1] + matrix[1][0]) / scale, 0.25 * scale,
                      (matrix[1][2] + matrix[2][1]) / scale, (matrix[0][2] - matrix[2][0]) / scale]
    else:
        scale = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2
        quaternion = [(matrix[0][2] + matrix[2][0]) / scale, (matrix[1][2] + matrix[2][1]) / scale,
                      0.25 * scale, (matrix[1][0] - matrix[0][1]) / scale]
    length = math.sqrt(sum(value * value for value in quaternion))
    if not math.isfinite(length) or length == 0:
        raise ToolPoseError("POSE_COORDINATES_UNRESOLVED: invalid orientation")
    return [value / length for value in quaternion]


def project_mill_demo_poses(points: list[dict[str, float]], context: dict[str, Any], mounting: list[float]) -> list[dict[str, Any]]:
    """Project MILL_DEMO B/C table orientation for points already in workpiece XYZ."""
    start_axes, end_axes = context.get("startAxes"), context.get("endAxes")
    if not isinstance(start_axes, dict) or not isinstance(end_axes, dict) or any(
        axis not in axes for axes in (start_axes, end_axes) for axis in ("B", "C")
    ):
        raise ToolPoseError("POSE_COORDINATES_UNRESOLVED: MILL_DEMO requires captured B and C axes")
    values = [start_axes["B"], start_axes["C"], end_axes["B"], end_axes["C"], *mounting]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ToolPoseError("POSE_COORDINATES_UNRESOLVED: non-finite pose input")
    mount = _matrix_multiply(_rotation_z(mounting[2]), _matrix_multiply(_rotation_y(mounting[1]), _rotation_x(mounting[0])))
    poses, previous = [], None
    for index, point in enumerate(points):
        coordinates = [point.get(axis) for axis in ("x", "y", "z")]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in coordinates):
            raise ToolPoseError("POSE_COORDINATES_UNRESOLVED: non-finite point")
        progress = index / (len(points) - 1) if len(points) > 1 else 1
        b = float(start_axes["B"]) + (float(end_axes["B"]) - float(start_axes["B"])) * progress
        c = float(start_axes["C"]) + (float(end_axes["C"]) - float(start_axes["C"])) * progress
        orientation = _matrix_multiply(_rotation_z(-c), _matrix_multiply(_rotation_y(-b), mount))
        quaternion = _quaternion(orientation)
        if previous is not None and sum(left * right for left, right in zip(previous, quaternion)) < 0:
            quaternion = [-value for value in quaternion]
        poses.append({"position": coordinates, "orientation": quaternion,
                      "reference": "millingTip", "frameId": "workpiece:tableBC"})
        previous = quaternion
    return poses
