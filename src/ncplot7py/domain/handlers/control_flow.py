"""Control-flow handler for simple loop constructs in NC programs.

Supports a small subset of constructs found in some controllers:
- GOTO<pos>
- IF<cond> ... GOTO<pos>
- WHILE<cond> DO<pos> / END<pos> (basic skip-if-false behaviour)

This handler manipulates node linked pointers (`_next_ncCode`) so the
canal execution loop can jump to the desired node. It expects nodes to be
linked via `_next_ncCode` and `_before_ncCode` beforehand.
"""
from __future__ import annotations

from functools import lru_cache
import re
from typing import Optional, Tuple
import logging

from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.expression_evaluator import ExpressionEvaluator


@lru_cache(maxsize=512)
def _parse_fanuc_condition(cond_text: str) -> Optional[Tuple[str, str, str]]:
    text = cond_text.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    for op in ("GE", "LE", "GT", "LT", "EQ", "NE"):
        if op in text:
            left, right = text.split(op, 1)
            return op, left, right
    return None


@lru_cache(maxsize=512)
def _tokenize_loop_command(lc: str) -> Tuple[str, ...]:
    command = ControlFlowHandler.TOKEN_RE.sub(r" \1", lc)
    return tuple(t for t in command.split(" ") if t)


class ControlFlowHandler(Handler):
    TOKEN_RE = re.compile(r"(GOTO|THEN|IF|END|DO|WHILE)")
    _DO_RE = re.compile(r"DO(\d+)")
    _END_RE = re.compile(r"END(\d+)")

    def __init__(self, next_handler: Optional[Handler] = None):
        super().__init__(next_handler=next_handler)
        # use expression evaluator for evaluations
        self._eval_helper = ExpressionEvaluator()
        # runtime maps (populated by canal before execution)
        self._n_map = None
        self._do_map = None
        self._end_map = None
        self._nodes = None
        self._default_next = {}
        self._do_to_end = {}
        self._end_to_do = {}
        self._while_cond_by_do = {}
        self._loop_counters = {}

    def setup_maps(self, nodes: list[NCCommandNode]) -> None:
        """Precomputes lookup maps for N-labels and DO/END loops.
        Called by the canal before execution begins.
        """
        self._nodes = nodes
        self._n_map = {}
        self._do_map = {}
        self._end_map = {}
        self._default_next = {
            node: getattr(node, "_next_ncCode", None) for node in self._nodes
        }
        self._do_to_end = {}
        self._end_to_do = {}
        self._while_cond_by_do = {}
        self._loop_counters = {}
        open_do = {}

        for nd in self._nodes:
            try:
                nval = nd.command_parameter.get("N")
            except Exception:
                nval = None
            if nval is not None:
                try:
                    key = float(nval)
                    self._n_map[key] = nd
                except Exception:
                    pass
            # detect DO/END labels inside loop_command
            lc = getattr(nd, "loop_command", None)
            if lc:
                if "WHILE" in lc:
                    for t in _tokenize_loop_command(lc):
                        if t.startswith("WHILE"):
                            self._while_cond_by_do[nd] = t[5:]
                            break
                for m in self._DO_RE.findall(lc):
                    self._do_map.setdefault(m, []).append(nd)
                    open_do.setdefault(m, []).append(nd)
                for m in self._END_RE.findall(lc):
                    self._end_map.setdefault(m, []).append(nd)
                    starts = open_do.get(m)
                    if starts:
                        start = starts.pop()
                        self._do_to_end[start] = nd
                        self._end_to_do[nd] = start

    def _find_node_with_N(self, start: NCCommandNode, pos: str) -> Optional[NCCommandNode]:
        # Prefer lookup via precomputed map when available
        try:
            target = float(pos)
        except Exception:
            return None

        if getattr(self, "_n_map", None) is not None:
            return self._n_map.get(target)

        # fallback: search forward then backward
        node = start
        # search forwards
        while node is not None:
            try:
                nval = node.command_parameter.get("N")
            except Exception:
                nval = None
            if nval is not None:
                try:
                    if float(nval) == target:
                        return node
                except Exception:
                    pass
            node = getattr(node, "_next_ncCode", None)

        # search backwards
        node = start
        while node is not None:
            try:
                nval = node.command_parameter.get("N")
            except Exception:
                nval = None
            if nval is not None:
                try:
                    if float(nval) == target:
                        return node
                except Exception:
                    pass
            node = getattr(node, "_before_ncCode", None)

        return None

    def _find_end_for_do(self, start: NCCommandNode, pos: str) -> Optional[NCCommandNode]:
        # Normal execution uses the pair map built once by setup_maps().
        target = self._do_to_end.get(start)
        if target is not None:
            return target

        # Retain a linked-list fallback for direct use without setup_maps().
        node = start
        while node is not None:
            lc = node.loop_command
            if lc and f"END{pos}" in lc:
                return node
            node = getattr(node, "_next_ncCode", None)
        return None

    def _is_true(self, cond_text: str, state: CNCState) -> bool:
        parsed = _parse_fanuc_condition(str(cond_text or ""))
        if parsed is None:
            return False
        op, left, right = parsed
        try:
            lv = self._eval_helper.evaluate(left, state)
            rv = self._eval_helper.evaluate(right, state)
        except Exception:
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("_is_true failed eval for cond=%s left=%s right=%s", cond_text, left, right, exc_info=True)
            return False
        try:
            vf_lv = float(lv) if lv not in ("", None) else 0.0
            vf_rv = float(rv) if rv not in ("", None) else 0.0
        except ValueError:
            vf_lv = 0.0
            vf_rv = 0.0

        if op == "GT":
            return vf_lv > vf_rv
        if op == "LT":
            return vf_lv < vf_rv
        if op == "GE":
            return vf_lv >= vf_rv
        if op == "LE":
            return vf_lv <= vf_rv
        if op == "EQ":
            return vf_lv == vf_rv
        if op == "NE":
            return vf_lv != vf_rv
        return False

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[list], Optional[float]]:
        lc = node.loop_command
        if not lc:
            return super().handle(node, state)

        # A previous loop iteration may have changed this pointer. Always
        # begin from the immutable fall-through target captured at setup.
        if node in self._default_next:
            node._next_ncCode = self._default_next[node]

        tokens = _tokenize_loop_command(lc)

        # simple scan for IF...GOTO or plain GOTO
        for token in tokens:
            if token.startswith("IF"):
                cond = token[2:]
                if self._is_true(cond, state):
                    # find GOTO token in same command
                    for t2 in tokens:
                        if t2.startswith("GOTO"):
                            pos = t2[4:]
                            target = self._find_node_with_N(node, pos)
                            if target is None:
                                # nothing we can do; fallthrough
                                break
                            node._next_ncCode = target
                            break
                else:
                    # Condition false -> restore fallback pointer if previously modified
                    node._next_ncCode = self._default_next.get(node, getattr(node, "_next_ncCode", None))
                # whether true or false, stop processing IF
                break
            elif token.startswith("GOTO"):
                pos = token[4:]
                # GOTO may reference a DO-label or an N label
                target = None
                try:
                    key = float(pos)
                except Exception:
                    key = None
                if key is not None and self._n_map is not None:
                    target = self._n_map.get(key)
                if target is None and self._do_map is not None:
                    # do_map entries are lists; pick first
                    lst = self._do_map.get(pos)
                    if lst:
                        target = lst[0]
                if target is None:
                    target = self._find_node_with_N(node, pos)
                if target is not None:
                    node._next_ncCode = target
                break
            elif token.startswith("WHILE"):
                cond = token[5:]
                # if condition is false, skip forward to matching END
                if not self._is_true(cond, state):
                    # find DO token to get pos
                    for t2 in tokens:
                        if t2.startswith("DO"):
                            pos = t2[2:]
                            end_node = self._find_end_for_do(node, pos)
                            if end_node is not None:
                                node._next_ncCode = getattr(end_node, "_next_ncCode", None)
                            break
                # otherwise, continue into loop (no change, check next token)
                continue
            elif token.startswith("DO"):
                # DO may be a label or start of a counted loop. If the DO node
                # provides parameter 'L' we treat it as a loop counter.
                label = token[2:]
                # initialize loop counter if present on this node
                try:
                    lval = node.command_parameter.get("L")
                except Exception:
                    lval = None
                if lval is not None:
                    try:
                        cnt = int(float(self._eval_helper.evaluate(str(lval), state)))
                    except Exception:
                        try:
                            cnt = int(float(lval))
                        except Exception:
                            cnt = None
                    if cnt is not None:
                        # store counter by label so END can find it
                        self._loop_counters[label] = cnt
                break
            elif token.startswith("END"):
                label = token[3:]
                do_node = self._end_to_do.get(node)
                if do_node is None:
                    # fallback: search backward for a DO with same label
                    cur = getattr(node, "_before_ncCode", None)
                    while cur is not None:
                        cur_lc = cur.loop_command
                        if cur_lc and f"DO{label}" in cur_lc:
                            do_node = cur
                            break
                        cur = getattr(cur, "_before_ncCode", None)

                if do_node is not None:
                    # if there's a loop counter for this label, decrement and jump
                    cnt = self._loop_counters.get(label)
                    if cnt is not None:
                        if cnt > 1:
                            self._loop_counters[label] = cnt - 1
                            node._next_ncCode = getattr(do_node, "_next_ncCode", do_node)
                        else:
                            # completed loop
                            del self._loop_counters[label]
                    else:
                        # If this DO was actually a WHILE (e.g. "WHILE[...]DO<label>"),
                        # re-evaluate the condition here and jump back to the DO body
                        # if the condition still holds.
                        cond_text = self._while_cond_by_do.get(do_node)
                        if cond_text is None:
                            do_lc = getattr(do_node, "loop_command", None)
                            if do_lc and "WHILE" in do_lc:
                                for t3 in _tokenize_loop_command(do_lc):
                                    if t3.startswith("WHILE"):
                                        cond_text = t3[5:]
                                        self._while_cond_by_do[do_node] = cond_text
                                        break
                        if cond_text is not None:
                            try:
                                if self._is_true(cond_text, state):
                                    # condition still true -> jump back into loop body
                                    node._next_ncCode = getattr(do_node, "_next_ncCode", do_node)
                                else:
                                    # condition false -> ensure END falls through to next node
                                    node._next_ncCode = self._default_next.get(
                                        node, getattr(node, "_next_ncCode", None)
                                    )
                            except Exception:
                                pass
                break

        return super().handle(node, state)


__all__ = ["ControlFlowHandler"]
