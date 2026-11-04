"""Delegating NC command parser preserving the existing public interface."""
from __future__ import annotations

import re
from typing import Dict, Optional

from ncplot7py.domain import exceptions as domain_exceptions
from ncplot7py.infrastructure.parsers.fanuc_command_parser import FanucCommandParser
from ncplot7py.infrastructure.parsers.siemens_command_parser import SiemensCommandParser
from ncplot7py.interfaces.BaseNCCommandParser import BaseNCCommandParser


class NCCommandParserError(domain_exceptions.ExceptionNode):
    """Thin wrapper for parser errors (keeps ExceptionNode semantics)."""


class NCCommandStringParser(BaseNCCommandParser):
    """Delegate parsing to a Fanuc or Siemens parser while preserving the API."""

    _PARSER_MAP = {
        "fanuc": FanucCommandParser,
        "siemens": SiemensCommandParser,
    }
    _DEF_RE = re.compile(r"^DEF\s+(INT|REAL|BOOL|CHAR|STRING(?:\[\d+\])?|AXIS|FRAME)\b")
    _CONTROL_RE = re.compile(r"^(FOR|ENDFOR|IF|ELSE|ENDIF|WHILE|ENDWHILE|LOOP|ENDLOOP|REPEAT|GOTOF|GOTOB|GOTO|CASE|ENDCASE)\b")
    _BUILTIN_RE = re.compile(
        r"(?:^|\s)(CYCLE\d+|POCKET\d+|HOLES\d+|SLOT\d+|LONGHOLE|WORKPIECE|MCALL|MSG|SETAL|STOPRE|NEWCONF|COMPCAD|TRAORI|TRAFOOF|TRANS|ATRANS|ROT|AROT|CTRANS|CROT|FRAME|NULLPUNKT|RET|GETEXET|CP|PTP|PTPG0|FFWON|FFWOF|DIAMON|DIAMOF|DIAM90|G645)\b"
    )
    _LABEL_RE = re.compile(r"^[A-Z_][A-Z0-9_]*:\s*$")
    _ANCHOR_RE = re.compile(r"^[A-Z_][A-Z_][A-Z0-9_]*(?:\*+.*|\s+.*)?$")
    _NON_ANCHOR_PREFIX_RE = re.compile(r"^(GOTO|IF|WHILE|END|DO|FOR|ELSE|CASE|DEFAULT|UNTIL|LOOP)")
    _SPLIT_WS_STAR_RE = re.compile(r"[\s*]")
    _NAMED_ASSIGN_RE = re.compile(r"^[A-Z_][A-Z0-9_]*(?:\[[^\]]+\])?\s*=")
    _AXIS_ASSIGN_RE = re.compile(r"\b(?:LA\d+|X|Y|Z|A|B|C|F|R|RND|RNDM|CHR|CHF)\s*=\s*")

    def __init__(self, parser_name: Optional[str] = None):
        self._parser_name = (parser_name or "auto").lower()
        self._delegates: Dict[str, BaseNCCommandParser] = {}
        self._fixed_delegate: Optional[BaseNCCommandParser] = (
            self._PARSER_MAP[self._parser_name]() if self._parser_name in self._PARSER_MAP else None
        )

    def parse(self, nc_command_string: str, line_nr: Optional[int] = None):
        if self._fixed_delegate is not None:
            return self._fixed_delegate.parse(nc_command_string, line_nr)
        parser_name = self._resolve_parser_name(nc_command_string)
        return self._get_delegate(parser_name).parse(nc_command_string, line_nr)

    def _get_delegate(self, parser_name: str) -> BaseNCCommandParser:
        normalized = parser_name if parser_name in self._PARSER_MAP else "fanuc"
        if normalized not in self._delegates:
            self._delegates[normalized] = self._PARSER_MAP[normalized]()
        return self._delegates[normalized]

    def _resolve_parser_name(self, nc_command_string: str) -> str:
        if self._parser_name in self._PARSER_MAP:
            return self._parser_name
        return "siemens" if self._looks_like_siemens(nc_command_string or "") else "fanuc"

    def _looks_like_siemens(self, nc_command_string: str) -> bool:
        stripped = str(nc_command_string or "").strip()
        if not stripped:
            return False
        if stripped.startswith("$") or 'T="' in stripped:
            return True
        upper = stripped.upper()
        if upper.startswith("DEF") and self._DEF_RE.match(upper):
            return True
        if self._CONTROL_RE.match(upper):
            return True
        if self._BUILTIN_RE.search(upper):
            return True
        if ":" in upper and self._LABEL_RE.match(upper):
            return True
        if (
            self._ANCHOR_RE.match(upper)
            and len(self._SPLIT_WS_STAR_RE.split(upper, maxsplit=1)[0]) > 1
            and not self._NON_ANCHOR_PREFIX_RE.match(upper)
        ):
            return True
        if "=" in upper:
            if not upper.startswith("#") and self._NAMED_ASSIGN_RE.match(upper):
                return True
            if self._AXIS_ASSIGN_RE.search(upper):
                return True
        return False


def register(registry) -> None:
    """Register parser implementations in the project registry."""
    registry.register("parser", "nc_command", NCCommandStringParser)
    registry.register("parser", "fanuc", FanucCommandParser)
    registry.register("parser", "siemens", SiemensCommandParser)
    try:
        from ncplot7py.interfaces.BaseNCCommandParser import BaseNCCommandParser

        registry.register("parser", BaseNCCommandParser.__name__, NCCommandStringParser)
    except Exception:
        pass
