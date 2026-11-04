from __future__ import annotations

import re
from typing import Dict, Optional, Set

from ncplot7py.domain import exceptions as domain_exceptions
from ncplot7py.infrastructure.lexers.siemens_program_lexer import SiemensProgramLexer
from ncplot7py.interfaces.BaseNCCommandParser import BaseNCCommandParser
from ncplot7py.shared.nc_nodes import NCCommandNode


class SiemensCommandParser(BaseNCCommandParser):
    """Parse Siemens-style NC/G-code lines into NCCommandNode instances."""

    _lexer = SiemensProgramLexer()
    _STRING_LITERAL_RE = re.compile(r'"[^"]*"')
    _NAMED_ASSIGN_RE = re.compile(r"^(?:N\d+\s*)?([A-Z_][A-Z0-9_]*(?:\[[^\]]+\])?)\s*=", re.IGNORECASE)
    _MULTI_LETTER_AXIS_RE = re.compile(
        r"^(?:LA\d+|MEAS|RND|RNDM|CHR|CHF|RP|AP|CR|AR|I1|J1|K1|X1|Y1|Z1|X2|Y2|Z2|X3|Y3|Z3)$"
    )
    _DEF_RE = re.compile(r"^DEF\s+(INT|REAL|BOOL|CHAR|STRING(?:\[\d+\])?|AXIS|FRAME)\b")
    _LABEL_STATEMENT_RE = re.compile(r"^[A-Z_][A-Z0-9_]*:\s*$")
    _CONTROL_RE = re.compile(r"^(FOR|ENDFOR|IF|ELSE|ENDIF|WHILE|ENDWHILE|LOOP|ENDLOOP|REPEAT|GOTOF|GOTOB|GOTO|CASE|ENDCASE)\b")
    _BUILTIN_STATEMENT_RE = re.compile(
        r"^(CYCLE\d+|POCKET\d+|HOLES\d+|SLOT\d+|LONGHOLE|WORKPIECE|MCALL|MSG|SETAL|STOPRE|NEWCONF|COMPCAD|TRAORI|TRAFOOF|TRANS|ATRANS|ROT|AROT|CTRANS|CROT|FRAME|NULLPUNKT|RET|GETEXET|WAITM|WAITMC|WAITE)\b"
    )
    _ANCHOR_RE = re.compile(r"^[A-Z_][A-Z_][A-Z0-9_]*(?:\s+[A-Z_][A-Z0-9_]*)*$")
    _ANCHOR_WITH_TEXT_RE = re.compile(r"^[A-Z_][A-Z_][A-Z0-9_]*(?:\*+.*|\s+.*)$")
    _NON_ANCHOR_PREFIX_RE = re.compile(r"^(GOTO|IF|WHILE|END|DO|FOR|ELSE|CASE|DEFAULT|UNTIL|LOOP)")
    _SPLIT_WS_STAR_RE = re.compile(r"[\s*]")
    _WHITESPACE_RE = re.compile(r"\s+")
    _SPECIAL_PARAM_RE = re.compile(r"\b(?:SCC\s*\[[^\]]+\]|LIMS(?:\s*\[\s*\d+\s*\])?\s*=\s*[^\s;]+)", re.IGNORECASE)
    _SIEMENS_INLINE_RE = re.compile(
        r"(?:\b|(?<=\d))(CYCLE\d+|POCKET\d+|HOLES\d+|SLOT\d+|LONGHOLE|WORKPIECE|MCALL|REPEAT|MSG|SETAL|STOPRE|NEWCONF|COMPCAD|TRAORI|TRAFOOF|TRANS|ATRANS|ROT|AROT|FRAME|NULLPUNKT|RET|GETEXET|CP|PTP|PTPG0|FFWON|FFWOF|DIAMON|DIAMOF|DIAM90)\b(?:\s*\([^)]*\))?",
        re.IGNORECASE,
    )
    _INNER_PAREN_RE = re.compile(r"\([^()]*\)")
    _SIEMENS_VAR_RE = re.compile(r"\$[A-Za-z0-9_]+(?:\[[^\]]*\])?", re.IGNORECASE)
    _NAMED_PARAM_VAL_RE = re.compile(
        r"(?<=[=\+\-\*\/\[\(,])\s*(?!__masked_)[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?",
        re.IGNORECASE,
    )
    _MULTI_AXIS_PARAM_RE = re.compile(
        r"(?:^|\b|(?<=__))(?:LA\d+|MEAS|RND|RNDM|CHR|CHF|RP|AP|CR|AR|I1|J1|K1|X1|Y1|Z1|X2|Y2|Z2|X3|Y3|Z3)\s*=\s*(?:__masked_\d+__|[^\s;]+)",
        re.IGNORECASE,
    )
    _LABEL_INLINE_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*:", re.IGNORECASE)
    _TOKEN_BOUNDARY_RE = re.compile(
        r"(SQRT|ASIN|ACOS|ATAN|SIN|COS|TAN|ABS|BIN|BCD|ROUND|FIX|FUP|(?<![=\+\-\*\/\[])(?:__masked_|[A-Z,]))"
    )
    _FUNC_SPACE_RE = re.compile(r" (SQRT|ASIN|ACOS|ATAN|SIN|COS|TAN|ABS|BIN|BCD|ROUND|FIX|FUP)")
    _MULTI_AXIS_ASSIGN_RE = re.compile(r"^([A-Za-z]+\d*)=(.+)$")
    _SPINDLE_ASSIGN_RE = re.compile(r"^S\d+=", re.IGNORECASE)
    _VAR_ASSIGN_RE = re.compile(r"^[A-Z][0-9]+=")
    _PARAM_PREFIXES = (
        'A', 'B', 'C', 'N', 'T', 'S', 'F', 'D', 'X', 'Y', 'Z', 'R', 'H',
        'U', 'V', 'W', 'K', 'L', 'I', 'J', 'P', 'Q',
        'x', 'y', 'z', 'u', 'v', 'w', 'r', 'g', 'j', 'p', 'i', 'k', 'l',
    )

    def parse(self, nc_command_string: str, line_nr: Optional[int] = None) -> NCCommandNode:
        g_code_set: Set[str] = set()
        axis_coordinate_dict: Dict[str, str] = {}
        dddp_ccr_set: Set[str] = set()
        var_calculation_str = ""
        loop_code = ""
        is_dddp = False

        if not nc_command_string:
            return NCCommandNode(nc_code_line_nr=line_nr)

        masked_map: Dict[str, str] = {}
        mask_counter = 0

        def mask_match(match: re.Match) -> str:
            nonlocal mask_counter
            token = f"__masked_{mask_counter}__"
            masked_map[token] = match.group(0)
            mask_counter += 1
            return token

        def unmask_text(text: str) -> str:
            if not masked_map:
                return text
            for key, value in reversed(list(masked_map.items())):
                if key in text:
                    text = text.replace(key, value)
            return text

        nc_line = self._STRING_LITERAL_RE.sub(mask_match, nc_command_string) if '"' in nc_command_string else nc_command_string

        # Keep direct parser calls backward compatible; normal execution has
        # already performed this operation in the program lexer.
        if ';' in nc_line:
            nc_line = self._lexer.strip_comments(nc_line)

        siemens_statement = nc_line.strip()
        if not siemens_statement:
            return NCCommandNode(nc_code_line_nr=line_nr)

        if siemens_statement.startswith("$"):
            return NCCommandNode(variable_command=unmask_text(siemens_statement) or None, nc_code_line_nr=line_nr)

        siemens_statement_upper = siemens_statement.upper()
        if siemens_statement_upper.startswith("DEF") and self._DEF_RE.match(siemens_statement_upper):
            return NCCommandNode(variable_command=unmask_text(siemens_statement) or None, nc_code_line_nr=line_nr)

        if "=" in siemens_statement:
            named_assignment_match = self._NAMED_ASSIGN_RE.match(siemens_statement)
            if named_assignment_match:
                named_assignment_target = named_assignment_match.group(1).split("[", 1)[0].upper()
                if len(named_assignment_target) > 1 and not self._MULTI_LETTER_AXIS_RE.match(named_assignment_target):
                    return NCCommandNode(variable_command=unmask_text(siemens_statement) or None, nc_code_line_nr=line_nr)

        if self._BUILTIN_STATEMENT_RE.match(siemens_statement_upper):
            return NCCommandNode(variable_command=unmask_text(siemens_statement) or None, nc_code_line_nr=line_nr)

        if ":" in siemens_statement_upper and self._LABEL_STATEMENT_RE.match(siemens_statement_upper):
            return NCCommandNode(variable_command=unmask_text(siemens_statement), nc_code_line_nr=line_nr)

        if self._CONTROL_RE.match(siemens_statement_upper):
            return NCCommandNode(loop_command=self._WHITESPACE_RE.sub("", unmask_text(siemens_statement)) or None, nc_code_line_nr=line_nr)

        if len(siemens_statement_upper) >= 2 and (siemens_statement_upper[0].isalpha() or siemens_statement_upper[0] == "_") and (siemens_statement_upper[1].isalpha() or siemens_statement_upper[1] == "_"):
            if not self._NON_ANCHOR_PREFIX_RE.match(siemens_statement_upper):
                if self._ANCHOR_RE.match(siemens_statement_upper) and len(siemens_statement_upper.split()[0]) > 1:
                    return NCCommandNode(variable_command=unmask_text(siemens_statement), nc_code_line_nr=line_nr)
                if (
                    "=" not in siemens_statement_upper
                    and self._ANCHOR_WITH_TEXT_RE.match(siemens_statement_upper)
                    and len(self._SPLIT_WS_STAR_RE.split(siemens_statement_upper, maxsplit=1)[0]) > 1
                ):
                    return NCCommandNode(variable_command=unmask_text(siemens_statement), nc_code_line_nr=line_nr)

        if "SCC" in siemens_statement_upper or "LIMS" in siemens_statement_upper:
            nc_line = self._SPECIAL_PARAM_RE.sub(mask_match, nc_line)

        nc_line = self._SIEMENS_INLINE_RE.sub(mask_match, nc_line)

        # Mask innermost parentheses first to protect spaces inside math
        if "(" in nc_line:
            prev_line = None
            while prev_line != nc_line:
                prev_line = nc_line
                nc_line = self._INNER_PAREN_RE.sub(mask_match, nc_line)

        if "$" in nc_line:
            nc_line = self._SIEMENS_VAR_RE.sub(mask_match, nc_line)

        nc_line = self._NAMED_PARAM_VAL_RE.sub(mask_match, nc_line)
        if "=" in nc_line:
            nc_line = self._MULTI_AXIS_PARAM_RE.sub(mask_match, nc_line)

        if ":" in nc_line:
            nc_line = self._LABEL_INLINE_RE.sub(mask_match, nc_line)

        if " " in nc_line:
            nc_line = nc_line.replace(" ", "")
        if nc_line.startswith('/'):
            nc_line = nc_line[1:]

        if 'GOTO' in nc_line or 'IF' in nc_line or 'WHILE' in nc_line or 'END' in nc_line or 'DO' in nc_line:
            loop_code = nc_line
            nc_line = ""

        if nc_line:
            nc_line = self._TOKEN_BOUNDARY_RE.sub(r" \1", nc_line)
            nc_line = self._FUNC_SPACE_RE.sub(r"\1", nc_line)
            codes = nc_line.split()
        else:
            codes = []

        for code in codes:
            if code.startswith("__masked_"):
                original = masked_map.get(code, code)
                for key, value in reversed(list(masked_map.items())):
                    if key in original:
                        original = original.replace(key, value)

                if "=" in original:
                    multi_axis_match = self._MULTI_AXIS_ASSIGN_RE.match(original)
                    if multi_axis_match and len(multi_axis_match.group(1)) > 1:
                        axis_coordinate_dict[multi_axis_match.group(1)] = "=" + multi_axis_match.group(2)
                        continue

                if var_calculation_str:
                    var_calculation_str += " " + original
                else:
                    var_calculation_str = original
                continue

            if masked_map and "__masked_" in code:
                for key, value in reversed(list(masked_map.items())):
                    if key in code:
                        code = code.replace(key, value)

            if is_dddp:
                dddp_ccr_set.add("," + code)
                is_dddp = False
                continue
            if code.startswith('G'):
                g_code_set.add(code)
            elif code.startswith('#'):
                var_calculation_str = nc_line
                for key, value in reversed(list(masked_map.items())):
                    var_calculation_str = var_calculation_str.replace(key, value)

                if g_code_set or axis_coordinate_dict:
                    domain_exceptions.raise_nc_error(
                        domain_exceptions.ExceptionTyps.NCCodeErrors,
                        -3,
                        message="Duplication of macro and NC command",
                        value=nc_command_string,
                        line=line_nr or 0,
                        source_line=nc_command_string,
                    )
            elif '=' in code and self._SPINDLE_ASSIGN_RE.match(code):
                key, value = code.split("=", 1)
                axis_coordinate_dict[key.upper()] = "=" + value
            elif '=' in code and self._VAR_ASSIGN_RE.match(code):
                if var_calculation_str:
                    var_calculation_str += " " + code
                else:
                    var_calculation_str = code
            elif code.startswith(','):
                if len(code) > 1:
                    dddp_ccr_set.add(code)
                    continue
                is_dddp = True
            elif is_dddp and (code.startswith(',R') or code.startswith(',C') or code.startswith(',A')):
                dddp_ccr_set.add(code)
            elif code.startswith('M'):
                axis_coordinate_dict[code[:1]] = code[1:]
            elif code.startswith(self._PARAM_PREFIXES):
                key = code[:1]
                if key in axis_coordinate_dict:
                    domain_exceptions.raise_nc_error(
                        domain_exceptions.ExceptionTyps.NCCodeErrors,
                        -2,
                        message="Duplication of parameter",
                        value=code,
                        line=line_nr or 0,
                        source_line=nc_command_string,
                    )
                axis_coordinate_dict[key] = code[1:]

        return NCCommandNode(
            g_code_command=g_code_set,
            command_parameter=axis_coordinate_dict,
            loop_command=loop_code or None,
            variable_command=var_calculation_str or None,
            dddp_command=dddp_ccr_set,
            nc_code_line_nr=line_nr,
        )
