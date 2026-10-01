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

    def parse(self, nc_command_string: str, line_nr: Optional[int] = None) -> NCCommandNode:
        g_code_set: Set[str] = set()
        axis_coordinate_dict: Dict[str, str] = {}
        dddp_ccr_set: Set[str] = set()
        var_calculation_str = ""
        loop_code = ""
        is_dddp = False

        if nc_command_string is None:
            nc_command_string = ""

        masked_map: Dict[str, str] = {}
        mask_counter = 0

        def mask_match(match: re.Match) -> str:
            nonlocal mask_counter
            token = f"__masked_{mask_counter}__"
            masked_map[token] = match.group(0)
            mask_counter += 1
            return token

        def unmask_text(text: str) -> str:
            for key, value in reversed(list(masked_map.items())):
                text = text.replace(key, value)
            return text

        nc_line = re.sub(r'"[^"]*"', mask_match, nc_command_string)

        # Keep direct parser calls backward compatible; normal execution has
        # already performed this operation in the program lexer.
        nc_line = self._lexer.strip_comments(nc_line)

        siemens_statement = nc_line.strip()
        siemens_statement_upper = siemens_statement.upper()
        named_assignment_match = re.match(r"^(?:N\d+\s*)?([A-Z_][A-Z0-9_]*(?:\[[^\]]+\])?)\s*=", siemens_statement, re.IGNORECASE)
        named_assignment_target = named_assignment_match.group(1).split("[", 1)[0].upper() if named_assignment_match else ""
        is_multi_letter_axis_assignment = bool(re.match(r"^(?:LA\d+|MEAS|RND|RNDM|CHR|CHF|RP|AP|CR|AR|I1|J1|K1|X1|Y1|Z1|X2|Y2|Z2|X3|Y3|Z3)$", named_assignment_target))
        is_named_assignment = bool(named_assignment_match and len(named_assignment_target) > 1 and not is_multi_letter_axis_assignment)
        is_siemens_declaration = bool(re.match(r"^DEF\s+(INT|REAL|BOOL|CHAR|STRING(?:\[\d+\])?|AXIS|FRAME)\b", siemens_statement_upper))
        is_siemens_label = bool(re.match(r"^[A-Z_][A-Z0-9_]*:\s*$", siemens_statement_upper))
        is_siemens_control = bool(re.match(r"^(FOR|ENDFOR|IF|ELSE|ENDIF|WHILE|ENDWHILE|LOOP|ENDLOOP|REPEAT|GOTOF|GOTOB|GOTO|CASE|ENDCASE)\b", siemens_statement_upper))
        is_siemens_builtin_statement = bool(
            re.match(
                r"^(CYCLE\d+|POCKET\d+|HOLES\d+|SLOT\d+|LONGHOLE|WORKPIECE|MCALL|MSG|SETAL|STOPRE|NEWCONF|COMPCAD|TRAORI|TRAFOOF|TRANS|ATRANS|ROT|AROT|CTRANS|CROT|FRAME|NULLPUNKT|RET|GETEXET|WAITM|WAITMC|WAITE)\b",
                siemens_statement_upper,
            )
        )
        is_siemens_anchor = bool(
            re.match(r"^[A-Z_][A-Z_][A-Z0-9_]*(?:\s+[A-Z_][A-Z0-9_]*)*$", siemens_statement_upper)
            and len(siemens_statement_upper.split()[0]) > 1
            and not re.match(r"^(GOTO|IF|WHILE|END|DO|FOR|ELSE|CASE|DEFAULT|UNTIL|LOOP)", siemens_statement_upper)
        )
        is_siemens_anchor_with_text = bool(
            re.match(r"^[A-Z_][A-Z_][A-Z0-9_]*(?:\*+.*|\s+.*)$", siemens_statement_upper)
            and len(re.split(r"[\s*]", siemens_statement_upper, maxsplit=1)[0]) > 1
            and "=" not in siemens_statement_upper
            and not re.match(r"^(GOTO|IF|WHILE|END|DO|FOR|ELSE|CASE|DEFAULT|UNTIL|LOOP)", siemens_statement_upper)
        )

        if is_siemens_declaration or is_named_assignment or siemens_statement.startswith("$"):
            return NCCommandNode(variable_command=unmask_text(siemens_statement) or None, nc_code_line_nr=line_nr)

        if is_siemens_builtin_statement:
            return NCCommandNode(variable_command=unmask_text(siemens_statement) or None, nc_code_line_nr=line_nr)

        if is_siemens_label:
            return NCCommandNode(variable_command=unmask_text(siemens_statement), nc_code_line_nr=line_nr)

        if is_siemens_control:
            return NCCommandNode(loop_command=re.sub(r"\s+", "", unmask_text(siemens_statement)) or None, nc_code_line_nr=line_nr)

        if is_siemens_anchor or is_siemens_anchor_with_text:
            return NCCommandNode(variable_command=unmask_text(siemens_statement), nc_code_line_nr=line_nr)

        siemens_special_parameter = r"\b(?:SCC\s*\[[^\]]+\]|LIMS(?:\s*\[\s*\d+\s*\])?\s*=\s*[^\s;]+)"
        nc_line = re.sub(siemens_special_parameter, mask_match, nc_line, flags=re.IGNORECASE)

        siemens_pattern = r"(?:\b|(?<=\d))(CYCLE\d+|POCKET\d+|HOLES\d+|SLOT\d+|LONGHOLE|WORKPIECE|MCALL|REPEAT|MSG|SETAL|STOPRE|NEWCONF|COMPCAD|TRAORI|TRAFOOF|TRANS|ATRANS|ROT|AROT|FRAME|NULLPUNKT|RET|GETEXET|CP|PTP|PTPG0|FFWON|FFWOF|DIAMON|DIAMOF|DIAM90)\b(?:\s*\([^)]*\))?"
        nc_line = re.sub(siemens_pattern, mask_match, nc_line, flags=re.IGNORECASE)

        # Mask innermost parentheses first to protect spaces inside math
        prev_line = None
        while prev_line != nc_line:
            prev_line = nc_line
            nc_line = re.sub(r"\([^()]*\)", mask_match, nc_line)

        siemens_var_pattern = r"\$[A-Za-z0-9_]+(?:\[[^\]]*\])?"
        nc_line = re.sub(siemens_var_pattern, mask_match, nc_line, flags=re.IGNORECASE)

        named_param_value_pattern = r"(?<=[=\+\-\*\/\[\(,])\s*(?!__masked_)[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?"
        nc_line = re.sub(named_param_value_pattern, mask_match, nc_line, flags=re.IGNORECASE)

        multi_letter_axis_param_pattern = r"(?:^|\b|(?<=__))(?:LA\d+|MEAS|RND|RNDM|CHR|CHF|RP|AP|CR|AR|I1|J1|K1|X1|Y1|Z1|X2|Y2|Z2|X3|Y3|Z3)\s*=\s*(?:__masked_\d+__|[^\s;]+)"
        nc_line = re.sub(multi_letter_axis_param_pattern, mask_match, nc_line, flags=re.IGNORECASE)

        label_pattern = r"\b[A-Za-z_][A-Za-z0-9_]*:"
        nc_line = re.sub(label_pattern, mask_match, nc_line, flags=re.IGNORECASE)

        nc_line = re.sub(siemens_pattern, mask_match, nc_line, flags=re.IGNORECASE)

        nc_line = re.sub(" ", "", nc_line)
        if nc_line.startswith('/'):
            nc_line = nc_line[1:]

        if 'GOTO' in nc_line or 'IF' in nc_line or 'WHILE' in nc_line or 'END' in nc_line or 'DO' in nc_line:
            loop_code = nc_line
            nc_line = ""

        nc_line = re.sub(r"(SQRT|ASIN|ACOS|ATAN|SIN|COS|TAN|ABS|BIN|BCD|ROUND|FIX|FUP|(?<![=\+\-\*\/\[])(?:__masked_|[A-Z,]))", r" \1", nc_line)
        nc_line = nc_line.replace(" SQRT", "SQRT")
        nc_line = nc_line.replace(" ASIN", "ASIN")
        nc_line = nc_line.replace(" ACOS", "ACOS")
        nc_line = nc_line.replace(" ATAN", "ATAN")
        nc_line = nc_line.replace(" SIN", "SIN")
        nc_line = nc_line.replace(" COS", "COS")
        nc_line = nc_line.replace(" TAN", "TAN")
        nc_line = nc_line.replace(" ABS", "ABS")
        nc_line = nc_line.replace(" BIN", "BIN")
        nc_line = nc_line.replace(" BCD", "BCD")
        nc_line = nc_line.replace(" ROUND", "ROUND")
        nc_line = nc_line.replace(" FIX", "FIX")
        nc_line = nc_line.replace(" FUP", "FUP")

        codes = re.split(r"\s+", nc_line.strip()) if nc_line.strip() else []

        for code in codes:
            if not code:
                continue

            if code.startswith("__masked_"):
                original = masked_map.get(code, code)
                for key, value in reversed(list(masked_map.items())):
                    if key in original:
                        original = original.replace(key, value)

                multi_axis_match = re.match(r"^([A-Za-z]+\d*)=(.+)$", original)
                if multi_axis_match and len(multi_axis_match.group(1)) > 1:
                    axis_coordinate_dict[multi_axis_match.group(1)] = "=" + multi_axis_match.group(2)
                    continue

                if var_calculation_str:
                    var_calculation_str += " " + original
                else:
                    var_calculation_str = original
                continue

            if "__masked_" in code:
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
            elif re.match(r"^S\d+=", code, re.IGNORECASE):
                key, value = code.split("=", 1)
                axis_coordinate_dict[key.upper()] = "=" + value
            elif re.match(r"^[A-Z][0-9]+=", code):
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
                axis_coordinate_dict.update({code[:1]: code[1:]})
            elif code.startswith(('A', 'B', 'C', 'N', 'T', 'S', 'F', 'D', 'X', 'Y', 'Z', 'R', 'H', 'U', 'V', 'W', 'K', 'L', 'I', 'J', 'P', 'Q', 'x', 'y', 'z', 'u', 'v', 'w', 'r', 'g', 'j', 'p', 'i', 'k', 'l')):
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
                axis_coordinate_dict.update({key: code[1:]})

        return NCCommandNode(
            g_code_command=g_code_set,
            command_parameter=axis_coordinate_dict,
            loop_command=loop_code or None,
            variable_command=var_calculation_str or None,
            dddp_command=dddp_ccr_set,
            nc_code_line_nr=line_nr,
        )
