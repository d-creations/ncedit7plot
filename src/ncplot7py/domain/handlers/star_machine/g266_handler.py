"""Star G266 machining-data setup command."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exceptions import ExceptionTyps, raise_nc_error
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode


class StarG266Handler(Handler):
    """Validate G266 and map its machining data to Star macro variables."""

    ALLOWED_WORDS = {"A", "X", "W", "S", "Z", "B", "F", "K", "Q", "T"}
    REQUIRED_WORDS = {"A", "X", "W", "S", "Z", "B", "F"}
    VARIABLE_MAP = {
        "A": "531",
        "W": "530",
        "S": "529",
        "F": "522",
        "B": "528",
        "X": "524",
        "Z": "525",
        "T": "523",
    }

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List], Optional[float]]:
        codes = {str(code).strip().upper() for code in node.g_code}
        if "G266" not in codes:
            return super().handle(node, state)

        words = {str(word).upper() for word in node.command_parameter}
        invalid = words - self.ALLOWED_WORDS
        if invalid:
            self._error(node, 3685, "G266 contains unsupported words", ",".join(sorted(invalid)))

        missing = self.REQUIRED_WORDS - words
        if missing:
            self._error(node, 3686, "G266 is missing required words", ",".join(sorted(missing)))

        values: dict[str, float] = {}
        for word in words:
            try:
                values[word] = float(node.command_parameter[word])
            except (TypeError, ValueError):
                self._error(node, 3687, "G266 argument must be numeric", word)

        state.star_state.g266_parameters = dict(values)
        for word, variable in self.VARIABLE_MAP.items():
            if word in values:
                state.parameters[variable] = values[word]
        for word in words:
            node.command_parameter.pop(word, None)

        return super().handle(node, state)

    @staticmethod
    def _error(node: NCCommandNode, code: int, message: str, value: str) -> None:
        raise_nc_error(
            ExceptionTyps.NCCanalStarErrors,
            code,
            message=message,
            value=value,
            line=node.nc_code_line_nr or 0,
        )


__all__ = ["StarG266Handler"]