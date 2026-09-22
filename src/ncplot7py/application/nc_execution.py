"""NC execution engine (renamed from `nc_analyzer`).

Provides `NCExecutionEngine` which is the new name for the orchestrator that
parses NC programs, delegates execution to an NC control implementation and
produces toolpath plot data. This keeps the public return values compatible
with the previous implementation.
"""
from __future__ import annotations

import time
from typing import List, Dict, Optional, Any, Tuple

from ncplot7py.shared import (
    configure_logging,
    get_logger,
    print_error,
    print_message,
    print_translated_error,
    get_message_stack,
    configure_i18n,
)
from ncplot7py.shared.registry import registry
from ncplot7py.domain.exceptions import ExceptionNode, ExceptionTyps


class NCExecutionEngine:
    """NC Execution Engine.

    This class preserves the original `get_Syncro_plot` return structure
    (a list of canal dictionaries, or `[[],[]]` on error) to avoid changing
    the public API while improving internal structure and naming.
    
    Errors encountered during execution are collected in the `errors` attribute
    and can be retrieved by the caller for display to the user.
    """

    def __init__(
        self,
        cnc_control: Any,
        lexer: Optional[Any] = None,
        frontend: Optional[Any] = None,
    ) -> None:
        """Initialize the engine.

        Parameters
        ----------
        cnc_control:
            An object implementing the NC control interface (run_nc_code_list,
            get_tool_path, get_exected_nodes, get_canal_name, get_canal_count,
            synchro_points).
        lexer:
            Optional source lexer override. Primarily useful for custom controls
            that do not expose a configured language frontend.
        frontend:
            Optional lexer/parser pair. Config-driven controls construct and
            expose this automatically from their machine configuration.
        """
        self.cnc_control = cnc_control
        self._frontend = frontend or getattr(cnc_control, "language_frontend", None)
        self._lexer = lexer
        self.caclulatet_runtime: float = -1.0
        self.errors: List[Dict[str, Any]] = []  # Collect errors for frontend reporting
        # If control offers canal count, use it, otherwise default to 1
        try:
            self.count_of_canals = int(self.cnc_control.get_canal_count())
        except Exception:
            self.count_of_canals = 1

        # Ensure logging and i18n are configured, but don't clobber a caller's
        # existing setup (e.g. web_buffer=True) if the logger is already configured,
        # otherwise errors logged here never reach frontends relying on
        # get_message_stack().
        if not get_logger().handlers:
            configure_logging(console=True, web_buffer=False)
        configure_i18n()
        
        # Default language for error messages
        self._error_lang = "en"
    
    def set_error_language(self, lang: str) -> None:
        """Set the language for error messages (e.g., 'en', 'de')."""
        self._error_lang = lang
    
    def _add_error(self, exc: Exception, line: int = 0, canal: int = 0) -> None:
        """Add an error to the errors list for reporting to frontend.
        
        Parameters
        ----------
        exc: Exception
            The exception that occurred
        line: int
            The NC line number where the error occurred (1-based)
        canal: int
            The canal number where the error occurred
        """
        if isinstance(exc, ExceptionNode):
            error_info = {
                "type": exc.typ.name if hasattr(exc.typ, 'name') else str(exc.typ),
                "code": exc.code,
                "line": exc.line if exc.line else line,
                "message": exc.localized(self._error_lang),
                "value": str(exc.value) if exc.value else "",
                "canal": canal,
            }
        else:
            error_info = {
                "type": "CNCError",
                "code": -1,
                "line": line,
                "message": str(exc),
                "value": "",
                "canal": canal,
            }
        self.errors.append(error_info)
        print_error(f"NC Error at line {line}, canal {canal}: {error_info['message']}")

    def get_cacluated_runtime(self) -> float:
        return self.caclulatet_runtime

    def _get_canal_state(self, canal_index: int) -> Optional[Any]:
        try:
            canals = getattr(self.cnc_control, "_canals", None)
            if isinstance(canals, dict):
                canal = canals.get(canal_index + 1)
                if canal is not None:
                    return getattr(canal, "_state", None)
        except Exception:
            pass
        return None

    def _get_last_executed_line(self, canal_number: int) -> int:
        try:
            executed_nodes = self.cnc_control.get_exected_nodes(canal_number)
        except Exception:
            return 0

        if not executed_nodes:
            return 0

        try:
            return int(getattr(executed_nodes[-1], "nc_code_line_nr", 0) or 0)
        except Exception:
            return 0

    def _get_canal_variables(self, canal_index: int) -> Dict[str, float]:
        state = self._get_canal_state(canal_index)
        if state is None:
            return {}

        parameters = getattr(state, "parameters", None)
        if not isinstance(parameters, dict):
            return {}

        variables: Dict[str, float] = {}
        for key, value in parameters.items():
            try:
                variables[str(key)] = float(value)
            except Exception:
                continue
        return variables

    def _get_canal_named_variables(self, canal_index: int) -> Dict[str, Any]:
        state = self._get_canal_state(canal_index)
        if state is None:
            return {}

        extra = getattr(state, "extra", None)
        if not isinstance(extra, dict):
            return {}
        siemens = extra.get("siemens")
        if not isinstance(siemens, dict):
            return {}

        named_variables: Dict[str, Any] = {}
        symbols = siemens.get("symbols", {})
        if isinstance(symbols, dict):
            for key, value in symbols.items():
                if isinstance(value, (int, float, bool, str)):
                    named_variables[str(key)] = value

        arrays = siemens.get("arrays", {})
        if isinstance(arrays, dict):
            for name, values in arrays.items():
                if not isinstance(values, (list, tuple)):
                    continue
                for index, value in enumerate(values):
                    if isinstance(value, (int, float, bool, str)):
                        named_variables[f"{name}[{index}]"] = value

        return named_variables

    def _ensure_parser(self):
        # Ensure a parser is registered (same strategy as cli.bootstrap)
        if registry.get("parser", "nc_command") is None:
            try:
                from ncplot7py.infrastructure.parsers.nc_command_parser import register as _reg_p

                _reg_p(registry)
            except Exception:
                # If parser registration fails, let parse attempts raise
                pass

    def _get_parser(self):
        if self._frontend is not None:
            return self._frontend.parser
        self._ensure_parser()
        parser_cls = registry.get("parser", "nc_command")
        if parser_cls is None:
            # try by interface name
            parser_cls = registry.get("parser", "BaseNCCommandParser")
        if parser_cls is None:
            raise RuntimeError("No NC command parser registered")
        parser_name = None
        try:
            state = self._get_canal_state(0)
            machine_config = getattr(state, "machine_config", None)
            parser_name = getattr(machine_config, "parser_name", None)
        except Exception:
            parser_name = None
        try:
            return parser_cls(parser_name=parser_name)
        except TypeError:
            return parser_cls()

    def _get_lexer(self):
        if self._lexer is not None:
            return self._lexer
        if self._frontend is not None:
            return self._frontend.lexer

        from ncplot7py.infrastructure.lexers import create_program_lexer

        lexer_name = None
        try:
            state = self._get_canal_state(0)
            machine_config = getattr(state, "machine_config", None)
            lexer_name = getattr(machine_config, "lexer_name", None)
            if lexer_name is None:
                lexer_name = getattr(machine_config, "parser_name", None)
        except Exception:
            lexer_name = None
        self._lexer = create_program_lexer(lexer_name)
        return self._lexer

    def get_Syncro_plot(
        self, programs: List[str], synch: bool, channel_number: Optional[int] = None
    ) -> List[Dict]:
        """Create the plot for the given NC `programs`.

        Parameters
        ----------
        programs: list[str]
            Each program is a string containing NC commands separated by ';'.
        synch: bool
            Whether to attempt synchronization across canals.

        Returns
        -------
        list[dict]
            A list of canal dictionaries in the same shape as the original
            implementation. On error returns `[[],[]]` to match previous API.
            Errors are also collected in the `errors` attribute for frontend reporting.
        """
        self.errors = []  # Reset errors for this run
        parser = None
        try:
            parser = self._get_parser()
            lexer = self._get_lexer()
        except Exception as e:
            self._add_error(e, line=0, canal=0)
            print_error(f"Parser setup failed: {e}")
            return [[], []]

        canal_number = 0
        tool_paths: List[Any] = []
        nodes: List[Any] = []
        error = False

        for program in programs:
            physical_channel = canal_number + 1
            # Parse program into a list of command nodes
            node_list = []
            statements = lexer.lex(program)
            for statement in statements:
                raw_line = statement.text
                source_line = statement.line
                # Skip empty commands for parsing, but keep source_line tied to editor line numbers.
                if not raw_line.strip():
                    continue
                
                try:
                    node = parser.parse(raw_line, source_line)
                    node_list.append(node)
                except Exception as parse_exc:
                    self._add_error(parse_exc, line=source_line, canal=canal_number + 1)
                    error = True
                    break

            if error:
                break

            # Delegate execution to control; many controls accept an iterable
            # of nodes. Keep canal numbering consistent with callers (+1).
            try:
                self.cnc_control.run_nc_code_list(node_list, canal_number + 1)
            except ExceptionNode as exc:
                # Handle structured NC errors with localization
                err_line = exc.line if exc.line else self._get_last_executed_line(canal_number + 1)
                self._add_error(exc, line=err_line, canal=canal_number+1)
                error = True
                break
            except Exception as exc:
                # Try to handle known control exception style (has log_route)
                log_route = getattr(exc, "log_route", None)
                if log_route:
                    # Try to format exception nodes using MessageCatalog when available
                    try:
                        from ncplot7py.domain.i18n import MessageCatalog

                        catalog = MessageCatalog()
                        for node in log_route:
                            if isinstance(node, ExceptionNode):
                                self._add_error(node, line=node.line, canal=canal_number+1)
                            else:
                                msg = catalog.format_exception(node)
                                print_error(msg)
                    except Exception:
                        self._add_error(exc, line=self._get_last_executed_line(canal_number + 1), canal=canal_number+1)
                else:
                    # generic parser/control error
                    self._add_error(exc, line=self._get_last_executed_line(canal_number + 1), canal=canal_number+1)
                error = True
                break

            # Try to collect results for this canal
            try:
                tool_paths.append(self.cnc_control.get_tool_path(canal_number + 1))
                nodes.append(self.cnc_control.get_exected_nodes(canal_number + 1))
            except ExceptionNode as exc:
                self._add_error(exc, line=exc.line if exc.line else 0, canal=canal_number+1)
                error = True
                break
            except Exception as exc:
                self._add_error(exc, line=0, canal=canal_number+1)
                error = True
                break

            canal_number += 1

        # Synchronize across canals if requested
        try:
            if not error and self.count_of_canals > 1 and synch:
                self.cnc_control.synchro_points(tool_paths, nodes)
        except ExceptionNode as e:
            self._add_error(e, line=e.line if e.line else 0, canal=0)
            error = True
        except Exception as e:
            log_route = getattr(e, "log_route", None)
            if log_route:
                try:
                    from ncplot7py.domain.i18n import MessageCatalog

                    catalog = MessageCatalog()
                    for node in log_route:
                        if isinstance(node, ExceptionNode):
                            self._add_error(node, line=node.line, canal=0)
                        else:
                            msg = catalog.format_exception(node)
                            print_error(msg)
                except Exception:
                    self._add_error(e, line=0, canal=0)
            else:
                self._add_error(e, line=0, canal=0)
            error = True

        # Build plots even if there were errors (partial results)
        # This allows the frontend to show what was successfully processed
        lines_list: List[Dict] = []
        runtime = 0.0
        canal_index = 0
        for tool_path in tool_paths:
            lines: List[Dict] = []
            linesExec: List[int] = []
            for line in tool_path:
                # each line expected to be (points_list, t)
                try:
                    l, t = line
                except Exception:
                    # unknown format, skip
                    continue
                x = []
                y = []
                z = []
                for point in l:
                    if point is not None:
                        x.append(getattr(point, "x", None))
                        y.append(getattr(point, "y", None))
                        z.append(getattr(point, "z", None))
                line_number = None
                motion_geometry = None
                motion_traversal = None
                motion_source_code = None
                execution_step = None
                tool_number = "unknown"
                if canal_index < len(nodes) and len(nodes[canal_index]) > len(lines):
                    motion_node = nodes[canal_index][len(lines)]
                    line_number = getattr(motion_node, "nc_code_line_nr", None)
                    motion_geometry = getattr(motion_node, "motion_geometry", None)
                    motion_traversal = getattr(motion_node, "motion_traversal", None)
                    motion_source_code = getattr(motion_node, "motion_source_code", None)
                    execution_step = getattr(motion_node, "execution_step", None)
                    tool_number = getattr(motion_node, "tool_number", "unknown")
                    if tool_number is None:
                        tool_number = "unknown"

                plot_line = {
                    "x": x,
                    "y": y,
                    "z": z,
                    "t": t,
                    "lineNumber": line_number,
                    "geometry": motion_geometry,
                    "traversal": motion_traversal,
                    "sourceCode": motion_source_code,
                    "executionStep": execution_step,
                    "toolNumber": tool_number,
                    "motionContext": getattr(motion_node, "motion_context", None) if canal_index < len(nodes) and len(nodes[canal_index]) > len(lines) else None,
                }
                physical_channel = canal_index + 1
                pose_channel = channel_number if channel_number is not None and len(tool_paths) == 1 else physical_channel
                state = self.cnc_control.get_nc_state(physical_channel)
                pose_tools = getattr(state, "extra", {}).get("pose_tools", {}) if state is not None else {}
                config = getattr(state, "machine_config", None) if state is not None else None
                context = plot_line["motionContext"]
                tool = pose_tools.get(tool_number) if isinstance(pose_tools, dict) else None
                if config is not None and getattr(config, "simulation", None) and tool is not None:
                    try:
                        point_data = [{"x": point_x, "y": point_y, "z": point_z} for point_x, point_y, point_z in zip(x, y, z)]
                        if config.simulation.get("modelId") == "MILL_DEMO":
                            from ncplot7py.domain.tool_pose import project_mill_demo_poses
                            plot_line["poses"] = project_mill_demo_poses(point_data, context, tool["mountingOrientationDegrees"])
                        elif config.simulation.get("modelId") in {"STAR_SR20R_IV_B", "STAR_SV20R", "STAR_SG42"}:
                            from ncplot7py.domain.tool_pose import project_fixed_target_poses
                            plot_line["poses"] = project_fixed_target_poses(
                                point_data, context, tool["mountingOrientationDegrees"],
                                config.simulation, str(pose_channel), tool_number, tool["reference"],
                            )
                    except Exception as pose_error:
                        self._add_error(pose_error, line=line_number or 0, canal=physical_channel)
                        error = True
                        break
                lines.append(plot_line)
                try:
                    runtime += float(t)
                except Exception:
                    pass

            self.caclulatet_runtime = runtime

            if len(tool_paths) == len(nodes):
                for node in nodes[canal_index]:
                    linesExec.append(getattr(node, "nc_code_line_nr", None))

            canal = {
                "plot": lines,
                "canalNr": self.cnc_control.get_canal_name(canal_index),
                "programExec": linesExec,
                "variables": self._get_canal_variables(canal_index),
                "namedVariables": self._get_canal_named_variables(canal_index),
            }
            canal_index += 1
            lines_list.append(canal)

        if lines_list:
            return lines_list

        # On error with no results, preserve prior API return value
        if error:
            print_message("Error in NC Code")
            print_message(get_message_stack())
        return [[], []]
