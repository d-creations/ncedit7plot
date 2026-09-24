from __future__ import annotations

import re
from typing import Dict, Optional, Set

from ncplot7py.domain import exceptions as domain_exceptions
from ncplot7py.infrastructure.lexers.fanuc_program_lexer import FanucProgramLexer
from ncplot7py.interfaces.BaseNCCommandParser import BaseNCCommandParser
from ncplot7py.shared.nc_nodes import NCCommandNode


class FanucCommandParser(BaseNCCommandParser):
    """Parse Fanuc-style NC/G-code lines into NCCommandNode instances."""

    _lexer = FanucProgramLexer()

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

        if re.search(r"#\s*3000\s*=", nc_command_string, re.IGNORECASE):
            return NCCommandNode(
                variable_command=nc_command_string.strip(),
                nc_code_line_nr=line_nr,
            )

        nc_line = re.sub(r'"[^"]*"', mask_match, nc_command_string)
        # Keep direct parser calls backward compatible; normal execution has
        # already performed this operation in the program lexer.
        nc_line = self._lexer.strip_comments(nc_line)
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
                if var_calculation_str:
                    var_calculation_str += " " + original
                else:
                    var_calculation_str = original
                continue

            if "__masked_" in code:
                for key, value in masked_map.items():
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
                for key, value in masked_map.items():
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
            elif re.match(r"^[A-Z][0-9]+=", code) and not re.match(r"^[A-Za-z][0-9]+=", code):
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
                # Check for explicit multi-character axis assignment like Z3=25.0, X2=10.0, C2=180.0
                multi_match = re.match(r"^([A-Za-z]\d+)=(.*)$", code)
                if multi_match:
                    key = multi_match.group(1).upper()
                    val = multi_match.group(2)
                else:
                    key = code[:1]
                    val = code[1:]
                if key in axis_coordinate_dict:
                    domain_exceptions.raise_nc_error(
                        domain_exceptions.ExceptionTyps.NCCodeErrors,
                        -2,
                        message="Duplication of parameter",
                        value=code,
                        line=line_nr or 0,
                        source_line=nc_command_string,
                    )
                axis_coordinate_dict.update({key: val})

        return NCCommandNode(
            g_code_command=g_code_set,
            command_parameter=axis_coordinate_dict,
            loop_command=loop_code or None,
            variable_command=var_calculation_str or None,
            dddp_command=dddp_ccr_set,
            nc_code_line_nr=line_nr,
        )
