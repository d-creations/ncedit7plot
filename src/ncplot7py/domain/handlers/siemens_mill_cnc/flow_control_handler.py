"""Siemens 840D flow-control handler."""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.handlers.siemens_mill_cnc.common import ensure_siemens_scope
from ncplot7py.domain.handlers.siemens_mill_cnc.variable_handler import SiemensExpressionEvaluator


class SiemensFlowControlHandler(Handler):
    """Handle Siemens labels, GOTO variants, IF skipping, and simple FOR loops."""

    _DO_LABEL_RE = re.compile(r"DO(\d+)$")
    _GOTO_RE = re.compile(r"^(GOTOF|GOTOB|GOTOC|GOTO)(.+)$", re.IGNORECASE)
    _IF_GOTO_RE = re.compile(r"^IF(.+?)(GOTOF|GOTOB|GOTO)(.+)$", re.IGNORECASE)
    _IF_PREFIX_RE = re.compile(r"^IF", re.IGNORECASE)
    _FOR_RE = re.compile(r"^FOR([A-Za-z_][A-Za-z0-9_]*)=(.+?)TO(.+)$", re.IGNORECASE)
    _WHILE_RE = re.compile(r"^WHILE(.+?)(?:DO\d+)?$", re.IGNORECASE)
    _UNTIL_RE = re.compile(r"^UNTIL\s*(.+)$", re.IGNORECASE)

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        self._nodes: list[NCCommandNode] = []
        self._labels: Dict[str, NCCommandNode] = {}
        self._for_to_end: Dict[NCCommandNode, NCCommandNode] = {}
        self._end_to_for: Dict[NCCommandNode, NCCommandNode] = {}
        self._while_to_end: Dict[NCCommandNode, NCCommandNode] = {}
        self._end_to_while: Dict[NCCommandNode, NCCommandNode] = {}
        self._if_to_else_or_end: Dict[NCCommandNode, NCCommandNode] = {}
        self._else_to_end: Dict[NCCommandNode, NCCommandNode] = {}
        self._repeat_to_until: Dict[NCCommandNode, NCCommandNode] = {}
        self._until_to_repeat: Dict[NCCommandNode, NCCommandNode] = {}
        self._loop_state: Dict[int, Dict[str, float | str]] = {}
        self._default_next: Dict[NCCommandNode, Optional[NCCommandNode]] = {}
        self._evaluator = SiemensExpressionEvaluator()

    def setup_maps(self, nodes: list[NCCommandNode]) -> None:
        self._nodes = list(nodes)
        self._labels = {}
        self._for_to_end = {}
        self._end_to_for = {}
        self._while_to_end = {}
        self._end_to_while = {}
        self._if_to_else_or_end = {}
        self._else_to_end = {}
        self._repeat_to_until = {}
        self._until_to_repeat = {}
        self._loop_state = {}
        self._default_next = {node: getattr(node, "_next_ncCode", None) for node in self._nodes}

        for node in self._nodes:
            command = (node.variable_command or "").strip()
            if command.endswith(":"):
                self._labels[command[:-1].upper()] = node

        stack: list[NCCommandNode] = []
        while_stack: list[NCCommandNode] = []
        while_stack_by_label: Dict[str, NCCommandNode] = {}
        if_stack: list[tuple[NCCommandNode, Optional[NCCommandNode]]] = []
        repeat_stack: list[NCCommandNode] = []
        for node in self._nodes:
            command = (node.loop_command or "").strip()
            if not command:
                continue
            upper = command.upper()
            if upper.startswith("FOR"):
                stack.append(node)
            elif upper == "ENDFOR" and stack:
                start = stack.pop()
                self._for_to_end[start] = node
                self._end_to_for[node] = start
            elif upper.startswith("WHILE"):
                while_stack.append(node)
                label_match = self._DO_LABEL_RE.search(upper)
                if label_match:
                    while_stack_by_label[label_match.group(1)] = node
            elif upper.startswith("END") and upper not in {"ENDIF", "ENDFOR", "ENDWHILE"}:
                label = upper[3:]
                start = while_stack_by_label.pop(label, None)
                if start is not None:
                    if start in while_stack:
                        while_stack.remove(start)
                    self._while_to_end[start] = node
                    self._end_to_while[node] = start
            elif upper == "ENDWHILE":
                start = while_stack.pop() if while_stack else None
                if start is not None:
                    self._while_to_end[start] = node
                    self._end_to_while[node] = start
            elif upper.startswith("IF") and "GOTO" not in upper:
                if_stack.append((node, None))
            elif upper == "ELSE" and if_stack:
                start, _ = if_stack[-1]
                self._if_to_else_or_end[start] = node
                if_stack[-1] = (start, node)
            elif upper == "ENDIF" and if_stack:
                start, else_node = if_stack.pop()
                self._if_to_else_or_end.setdefault(start, node)
                if else_node is not None:
                    self._else_to_end[else_node] = node
            elif upper == "REPEAT":
                repeat_stack.append(node)
            elif upper.startswith("UNTIL") and repeat_stack:
                start = repeat_stack.pop()
                self._repeat_to_until[start] = node
                self._until_to_repeat[node] = start

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[list], Optional[float]]:
        command = (node.loop_command or "").strip()
        if not command:
            if self._labels:
                scope = state.siemens_state.scope
                if scope and scope.get("labels") is not self._labels:
                    scope["labels"] = self._labels
            return super().handle(node, state)

        scope = ensure_siemens_scope(state)
        scope["labels"] = self._labels

        # Discard a jump left on this node by an earlier iteration before
        # evaluating the command against the current variable state.
        if node in self._default_next:
            node._next_ncCode = self._default_next[node]

        upper = command.upper()
        if upper.startswith(("GOTOF", "GOTOB", "GOTOC", "GOTO")):
            self._handle_goto(node, command)
        elif upper.startswith("IF"):
            self._handle_if(node, command, state)
        elif upper == "ELSE":
            end_node = self._else_to_end.get(node)
            if end_node is not None:
                node._next_ncCode = self._default_next.get(end_node)
        elif upper.startswith("FOR"):
            self._handle_for(node, command, state)
        elif upper == "ENDFOR":
            self._handle_endfor(node, state)
        elif upper.startswith("WHILE"):
            self._handle_while(node, command, state)
        elif upper.startswith("END") and upper not in {"ENDIF", "ENDFOR"}:
            self._handle_endwhile(node, state)
        elif upper == "REPEAT":
            pass  # enter block normally
        elif upper.startswith("UNTIL"):
            self._handle_until(node, command, state)
        return super().handle(node, state)

    def _handle_goto(self, node: NCCommandNode, command: str) -> None:
        match = self._GOTO_RE.match(command)
        if not match:
            return
        mode = match.group(1).upper()
        label = match.group(2).strip().upper()
        target = self._labels.get(label)
        if target is not None:
            node._next_ncCode = target
        elif mode != "GOTOC":
            return

    def _handle_if(self, node: NCCommandNode, command: str, state: CNCState) -> None:
        if "GOTO" in command.upper():
            single_line = self._IF_GOTO_RE.match(command)
            if single_line:
                condition, goto_mode, label = single_line.groups()
                if self._evaluator.is_true(condition, state):
                    self._handle_goto(node, goto_mode + label)
                return
        condition = self._IF_PREFIX_RE.sub("", command, count=1)
        if not self._evaluator.is_true(condition, state):
            target = self._if_to_else_or_end.get(node)
            if target is not None:
                node._next_ncCode = getattr(target, "_next_ncCode", None) if (target.loop_command or "").upper() == "ELSE" else target

    def _handle_for(self, node: NCCommandNode, command: str, state: CNCState) -> None:
        match = self._FOR_RE.match(command)
        if not match:
            return
        variable_name, start_expr, end_expr = match.groups()
        scope = ensure_siemens_scope(state)
        start_value = self._evaluator.evaluate(start_expr, state)
        end_value = self._evaluator.evaluate(end_expr, state)
        scope["symbols"][variable_name] = int(start_value) if float(start_value).is_integer() else start_value
        self._loop_state[id(node)] = {"variable": variable_name, "end": end_value}
        if start_value > end_value:
            end_node = self._for_to_end.get(node)
            if end_node is not None:
                node._next_ncCode = self._default_next.get(end_node)

    def _handle_endfor(self, node: NCCommandNode, state: CNCState) -> None:
        start_node = self._end_to_for.get(node)
        if start_node is None:
            return
        loop_info = self._loop_state.get(id(start_node))
        if not loop_info:
            return
        scope = ensure_siemens_scope(state)
        variable_name = str(loop_info["variable"])
        next_value = float(scope["symbols"].get(variable_name, 0.0)) + 1.0
        scope["symbols"][variable_name] = int(next_value) if next_value.is_integer() else next_value
        if next_value <= float(loop_info["end"]):
            node._next_ncCode = getattr(start_node, "_next_ncCode", None)
        else:
            node._next_ncCode = self._default_next.get(node)

    def _handle_while(self, node: NCCommandNode, command: str, state: CNCState) -> None:
        match = self._WHILE_RE.match(command)
        if not match:
            return
        condition = match.group(1)
        if not self._evaluator.is_true(condition, state):
            end_node = self._while_to_end.get(node)
            if end_node is not None:
                node._next_ncCode = self._default_next.get(end_node)

    def _handle_endwhile(self, node: NCCommandNode, state: CNCState) -> None:
        start_node = self._end_to_while.get(node)
        if start_node is not None:
            node._next_ncCode = start_node

    def _handle_until(self, node: NCCommandNode, command: str, state: CNCState) -> None:
        match = self._UNTIL_RE.match(command)
        if not match:
            return
        condition = match.group(1).strip()
        if not self._evaluator.is_true(condition, state):
            # condition is false, jump back to repeat
            start_node = self._until_to_repeat.get(node)
            if start_node is not None:
                node._next_ncCode = getattr(start_node, "_next_ncCode", None)

__all__ = ["SiemensFlowControlHandler"]