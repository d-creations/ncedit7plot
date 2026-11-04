"""NC command node definitions used to represent parsed NC/G-code commands.

This module provides an `NCCommandNode` class following the shape of the
user-provided example but adapted to the project's style and typing. The
node keeps optional `_next_ncCode` and `_before_ncCode` attributes for
interop with linked-list implementations that expect those fields.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Set

from ..interfaces.BaseNCCommandNode import BaseNCCommandNode


class NCCommandNode(BaseNCCommandNode):
    """A node representing a single NC command.

    Attributes are kept intentionally simple and use standard Python types.
    _next_ncCode and _before_ncCode are provided for compatibility with
    linked-list implementations that expect those attributes.
    """

    __slots__ = (
        "_g_code",
        "_command_parameter",
        "_loop_command",
        "_variable_command",
        "_dddp_command",
        "_nc_code_line_nr",
        "_motion_geometry",
        "_motion_traversal",
        "_motion_source_code",
        "_generated_motion_segments",
        "_execution_step",
        "_tool_number",
        "_motion_context",
        "extra",
        "_next_ncCode",
        "_before_ncCode",
    )

    def __init__(
        self,
        g_code_command: Optional[Set[str]] = None,
        command_parameter: Optional[Dict[str, str]] = None,
        loop_command: Optional[str] = None,
        variable_command: Optional[str] = None,
        dddp_command: Optional[Set[str]] = None,
        nc_code_line_nr: Optional[int] = None,
    ) -> None:
        # store data in private attributes to avoid colliding with the
        # abstract-property names exposed by the interface
        self._g_code: Set[str] = set(g_code_command) if g_code_command else set()
        self._command_parameter: Dict[str, str] = dict(command_parameter) if command_parameter else {}
        self._loop_command = loop_command
        self._variable_command = variable_command
        self._dddp_command: Set[str] = set(dddp_command) if dddp_command else set()
        self._nc_code_line_nr: Optional[int] = nc_code_line_nr
        self._motion_geometry: Optional[str] = None
        self._motion_traversal: Optional[str] = None
        self._motion_source_code: Optional[str] = None
        self._generated_motion_segments: List[Dict[str, object]] = []
        self._execution_step: Optional[int] = None
        self._tool_number: Optional[object] = None
        self._motion_context: Optional[Dict[str, object]] = None
        self.extra: Dict[str, Any] = {}

        # Optional pointers for linked-list style containers
        self._next_ncCode: Optional["NCCommandNode"] = None
        self._before_ncCode: Optional["NCCommandNode"] = None

    # Implement abstract properties from BaseNCCommandNode
    @property
    def g_code(self) -> Set[str]:
        return self._g_code

    @property
    def command_parameter(self) -> Dict[str, str]:
        return self._command_parameter

    @property
    def loop_command(self) -> Optional[str]:
        return self._loop_command

    @property
    def variable_command(self) -> Optional[str]:
        return self._variable_command

    @property
    def dddp_command(self) -> Set[str]:
        return self._dddp_command

    @property
    def nc_code_line_nr(self) -> Optional[int]:
        return self._nc_code_line_nr

    @property
    def motion_geometry(self) -> Optional[str]:
        return self._motion_geometry

    @property
    def motion_traversal(self) -> Optional[str]:
        return self._motion_traversal

    @property
    def motion_source_code(self) -> Optional[str]:
        return self._motion_source_code

    @property
    def generated_motion_segments(self) -> List[Dict[str, object]]:
        return self._generated_motion_segments

    @property
    def execution_step(self) -> Optional[int]:
        return self._execution_step

    @property
    def tool_number(self) -> Optional[object]:
        return self._tool_number

    @property
    def motion_context(self) -> Optional[Dict[str, object]]:
        return self._copy_motion_context(self._motion_context)

    @staticmethod
    def _copy_motion_context(ctx: Optional[Dict[str, object]]) -> Optional[Dict[str, object]]:
        if ctx is None:
            return None
        copied: Dict[str, object] = dict(ctx)
        if "startAxes" in copied and isinstance(copied["startAxes"], dict):
            copied["startAxes"] = dict(copied["startAxes"])
        if "endAxes" in copied and isinstance(copied["endAxes"], dict):
            copied["endAxes"] = dict(copied["endAxes"])
        if "toolOffset" in copied and isinstance(copied["toolOffset"], dict):
            copied["toolOffset"] = dict(copied["toolOffset"])
        return copied

    def set_motion_metadata(self, geometry: str, traversal: str, source_code: str) -> None:
        self._motion_geometry = geometry
        self._motion_traversal = traversal
        self._motion_source_code = source_code

    def set_generated_motion_segments(self, segments: List[Dict[str, object]]) -> None:
        self._generated_motion_segments = list(segments)

    def set_execution_metadata(
        self,
        execution_step: int,
        tool_number: Optional[object],
        motion_context: Optional[Dict[str, object]] = None,
    ) -> None:
        self._execution_step = execution_step
        self._tool_number = tool_number
        self._motion_context = self._copy_motion_context(motion_context)

    def __str__(self) -> str:
        parts = ["NC COMMAND: "]
        if self.g_code:
            parts.append("G,codes=")
            parts.append(",".join(sorted(self.g_code)))
        if self.command_parameter:
            parts.append(" params=")
            parts.append(",".join(f"{k}={v}" for k, v in self.command_parameter.items()))
        if self.nc_code_line_nr is not None:
            parts.append(f" line={self.nc_code_line_nr}")
        return "".join(parts)

    def copy(self, include_segments: bool = True) -> "NCCommandNode":
        """Return a copy of the node (pointers are not deeply copied).

        The original example copied next pointers shallowly; here we copy
        node attributes but keep `_next_ncCode` as a shallow reference
        to avoid copying an entire list structure.
        """
        node = NCCommandNode(
            g_code_command=set(self._g_code) if self._g_code else None,
            command_parameter=dict(self._command_parameter) if self._command_parameter else None,
            loop_command=self._loop_command,
            variable_command=self._variable_command,
            dddp_command=set(self._dddp_command) if self._dddp_command else None,
            nc_code_line_nr=self._nc_code_line_nr,
        )
        node._next_ncCode = self._next_ncCode
        node._before_ncCode = self._before_ncCode
        node._motion_geometry = self._motion_geometry
        node._motion_traversal = self._motion_traversal
        node._motion_source_code = self._motion_source_code
        if include_segments and self._generated_motion_segments:
            node._generated_motion_segments = deepcopy(self._generated_motion_segments)
        node._execution_step = self._execution_step
        node._tool_number = self._tool_number
        node._motion_context = self._copy_motion_context(self._motion_context)
        if self.extra:
            node.extra = deepcopy(self.extra)
        return node

    def __del__(self) -> None:
        # Break pointers to help garbage collection in long-lived lists.
        self._next_ncCode = None
        self._before_ncCode = None

    def __iter__(self):
        # Return an iterator for convenience; by default just yield this node.
        yield self

