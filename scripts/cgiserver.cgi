#!/usr/bin/env python3
"""
CGI Server for NC-Edit7 Plot Interface
Handles machine data requests and returns plot data using the real ncplot7py engine.
"""

import sys
import json
import os
import re
import logging
import traceback
from typing import Dict, List, Any, Optional
from pathlib import Path

# Ensure ncplot7py/src is in sys.path
# This script is in ncplot7py/scripts/
# We want to add ncplot7py/src/ to sys.path
current_dir = Path(__file__).resolve().parent
package_src = current_dir.parent / "src"
if package_src.exists() and str(package_src) not in sys.path:
    sys.path.insert(0, str(package_src))

# Import ncplot7py internals
try:
    from ncplot7py.application.nc_execution import NCExecutionEngine
    from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl
    from ncplot7py.cli.main import bootstrap as cli_bootstrap
    from ncplot7py.domain.machines import (
        get_available_machines,
        get_machine_regex_patterns,
        get_machine_config,
        MachineConfig,
    )
    from ncplot7py.domain.cnc_state import CNCState
    from ncplot7py.domain.exceptions import ExceptionNode
except Exception as e:
    # If imports fail, we can't do much. We'll log it and fail later if needed.
    sys.stderr.write(f"Failed to import ncplot7py: {e}\n")
    sys.stderr.write(traceback.format_exc())
    NCExecutionEngine = None
    UniversalConfigDrivenControl = None
    cli_bootstrap = None
    get_available_machines = None
    get_machine_regex_patterns = None
    CNCState = None
    ExceptionNode = None

# Set content type for CGI
print("Content-Type: application/json")
print()

# Configure logging to stderr so it appears in server logs but doesn't break JSON output
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

def sanitize_program(program: str) -> str:
    """Conservative sanitizer exposed at module level for reuse and testing."""
    if not isinstance(program, str):
        return program

    # Remove parenthetical comments (single-line)
    # program = re.sub(r"\(.*?\)", "", program)
    # DISABLED: Siemens uses () for parameters (e.g. CYCLE800(...))
    # We should only remove comments if we are sure they are comments.
    # For now, let the parser handle comments.


    def sanitize_subcmd(sub: str) -> str:
        parts = [p for p in sub.strip().split() if p != ""]
        axis_re = re.compile(r'^([XYZIJKxyzijk])(?=[+-]?\d|=)')
        last_axis = {}
        others = []
        # record last index for axis tokens and keep others with position
        for i, p in enumerate(parts):
            m = axis_re.match(p)
            if m:
                last_axis[m.group(1).upper()] = i
            else:
                others.append((i, p))

        if not last_axis and not others:
            return sub.strip()

        axis_by_index = {idx: parts[idx] for idx in last_axis.values()}

        merged = []
        for i in range(len(parts)):
            if i in axis_by_index:
                merged.append(axis_by_index[i])
            else:
                # append any other token at this position
                for pos, val in others:
                    if pos == i:
                        merged.append(val)
                        break

        return " ".join(merged)

    sanitized_lines = []
    for line in program.splitlines():
        # split by semicolon but keep semantic separators
        subs = [s for s in line.split(";")]
        san_subs = [sanitize_subcmd(s) for s in subs]
        sanitized_lines.append(";".join([s for s in san_subs if s is not None]))

    return "\n".join(sanitized_lines)

def build_segments_from_engine_output(canal_output: Dict[str, Any]) -> Dict[str, Any]:
    """Convert NCExecutionEngine canal output to the legacy response shape."""
    segments = []
    timing = []
    executed_node_lines = canal_output.get("programExec", [])
    motion_line_numbers = []
    line_timing = {}

    plot_list = canal_output.get("plot", [])

    for idx, entry in enumerate(plot_list):
        x = entry.get("x", [])
        y = entry.get("y", [])
        z = entry.get("z", [])
        t = entry.get("t", 0)

        # Build all points
        if len(x) == 0:
            continue
            
        points = []
        for i in range(len(x)):
            px = x[i]
            py = y[i] if i < len(y) else (y[-1] if len(y) > 0 else 0)
            pz = z[i] if i < len(z) else (z[-1] if len(z) > 0 else 0)
            points.append({"x": px, "y": py, "z": pz})

        has_motion_semantics = "geometry" in entry or "traversal" in entry
        geometry = entry.get("geometry")
        traversal = entry.get("traversal")
        source_code = entry.get("sourceCode")
        if traversal == "RAPID":
            segment_type = "RAPID"
        elif geometry:
            segment_type = geometry
        elif has_motion_semantics:
            segment_type = "UNKNOWN"
        else:
            segment_type = "RAPID" if (not t or float(t) == 0) else "LINEAR"

        seg = {
            "type": segment_type,
            "geometry": geometry,
            "traversal": traversal,
            "sourceCode": source_code,
            "lineNumber": entry.get("lineNumber") if entry.get("lineNumber") is not None else (executed_node_lines[idx] if idx < len(executed_node_lines) else None),
            "executionStep": entry.get("executionStep"),
            "toolNumber": entry.get("toolNumber", "unknown"),
            "points": points,
        }
        segments.append(seg)
        try:
            segment_time = float(t)
        except Exception:
            segment_time = 0.0
        timing.append(segment_time)
        motion_line_numbers.append(seg["lineNumber"])
        if seg["lineNumber"] is not None:
            line_key = str(seg["lineNumber"])
            line_timing[line_key] = line_timing.get(line_key, 0.0) + segment_time

    return {
        "segments": segments,
        "executedLines": motion_line_numbers,
        "executedNodeLines": executed_node_lines,
        "variables": canal_output.get("variables", {}) if isinstance(canal_output.get("variables", {}), dict) else {},
        "namedVariables": canal_output.get("namedVariables", {}) if isinstance(canal_output.get("namedVariables", {}), dict) else {},
        "timing": timing,
        "lineTiming": line_timing,
    }

def mock_parse_nc_program(program: str, machine_name: str) -> Dict[str, Any]:
    """
    Parse NC program and generate mock plot data (legacy behavior).
    """
    lines = [line.strip() for line in program.split('\n') if line.strip()]
    
    # Generate mock plot segments
    segments = []
    current_pos = {"x": 0, "y": 0, "z": 0}
    
    for i, line in enumerate(lines):
        # Simple G-code parsing for demo
        if line.startswith('G0') or line.startswith('G1'):
            # Extract coordinates
            new_pos = current_pos.copy()
            
            parts = line.split()
            for part in parts:
                if part.startswith('X'):
                    try:
                        new_pos['x'] = float(part[1:])
                    except ValueError:
                        pass
                elif part.startswith('Y'):
                    try:
                        new_pos['y'] = float(part[1:])
                    except ValueError:
                        pass
                elif part.startswith('Z'):
                    try:
                        new_pos['z'] = float(part[1:])
                    except ValueError:
                        pass
            
            # Create segment
            segment = {
                "type": "RAPID" if line.startswith('G0') else "LINEAR",
                "geometry": "LINEAR",
                "traversal": "RAPID" if line.startswith('G0') else "FEED",
                "sourceCode": "G0" if line.startswith('G0') else "G1",
                "lineNumber": i + 1,
                "executionStep": i,
                "toolNumber": "unknown",
                "points": [
                    current_pos.copy(),
                    new_pos.copy()
                ]
            }
            segments.append(segment)
            current_pos = new_pos
    
    return {
        "segments": segments,
        "executedLines": list(range(1, len(lines) + 1)),
        "variables": {},
        "namedVariables": {},
        "timing": [0.1] * len(lines)
    }

def engine_output_has_non_plot_data(engine_output: Any) -> bool:
    """Return True when the real engine produced useful non-geometry data."""
    if not isinstance(engine_output, list):
        return False

    for canal in engine_output:
        if not isinstance(canal, dict):
            continue
        if canal.get("programExec"):
            return True
        variables = canal.get("variables")
        if isinstance(variables, dict) and variables:
            return True
        named_variables = canal.get("namedVariables")
        if isinstance(named_variables, dict) and named_variables:
            return True
    return False

def run_mock_parser(machinedata: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run the mock parser for all programs in machinedata."""
    canal_results = {}
    messages = []
    
    for program_entry in machinedata:
        program = program_entry.get("program", "")
        machine_name = program_entry.get("machineName", "ISO_MILL")
        canal_nr = str(program_entry.get("canalNr", "1"))
        
        # Parse program
        try:
            result = mock_parse_nc_program(program, machine_name)
            canal_results[canal_nr] = result
            messages.append(f"Successfully processed {machine_name} canal {canal_nr} (mock)")
        except Exception as e:
            messages.append(f"Error processing {machine_name} canal {canal_nr}: {str(e)}")
    
    return {
        "canal": canal_results,
        "message": messages,
        "success": True
    }

def handle_list_machines() -> Dict[str, Any]:
    if get_available_machines is None:
        return {"machines": [], "success": False, "message": "ncplot7py not available"}

    machines = get_available_machines()

    # Add regex patterns to each machine
    for machine in machines:
        if get_machine_regex_patterns:
            machine["regexPatterns"] = get_machine_regex_patterns(machine["controlType"])
        config = get_machine_config(machine["machineName"])
        machine["variablePrefix"] = config.variable_prefix
        machine["fileExtensions"] = config.file_extensions

    return {
        "machines": machines,
        "success": True,
    }

def handle_get_line_alignment_syntax() -> Dict[str, Any]:
    """Return supported multichannel wait syntax for API clients."""
    return {
        "lineAlignmentSyntax": [
            {
                "controlType": "FANUC",
                "waitCodeRange": {"min": 200, "max": 899},
                "twoChannel": {
                    "syntax": "M<waitCode>",
                    "rule": "Use the same wait code in both channels.",
                    "example": {"channel1": "M200", "channel2": "M200"},
                },
                "threeChannel": {
                    "syntax": "M<waitCode> P<channels>",
                    "selectors": ["P12", "P13", "P23", "P123"],
                    "rule": "Use the same wait code and selector in every participating channel.",
                    "example": {
                        "channel1": "M899 P123",
                        "channel2": "M899 P123",
                        "channel3": "M899 P123",
                    },
                },
            },
            {
                "controlType": "SIEMENS",
                "syntax": "WAITM(<marker>)",
                "rule": "Use the same marker number in every channel to align.",
                "example": {"channel1": "WAITM(1)", "channel2": "WAITM(1)"},
            },
        ],
        "success": True,
    }

def handle_execute_programs(
    machinedata: List[Dict[str, Any]],
    tool_path_mode: str = "effective",
) -> Dict[str, Any]:
    tool_path_mode = str(tool_path_mode).strip().lower()
    if tool_path_mode not in {"effective", "center"}:
        return {
            "canal": {},
            "message": [
                f"Invalid toolPathMode '{tool_path_mode}'. Expected one of: effective, center"
            ],
            "success": False,
        }

    if NCExecutionEngine is None:
        return run_mock_parser(machinedata)

    # Ensure parser registration
    try:
        if cli_bootstrap:
            cli_bootstrap()
    except Exception:
        logging.exception("Bootstrap failed")

    # Build programs list, canal names, tool values, custom variables, and machine names
    programs: List[str] = []
    canal_names: List[str] = []
    tool_values_list: List[List[Dict[str, Any]]] = []
    custom_variables_list: List[List[Dict[str, Any]]] = []
    machine_names: List[str] = []
    custom_configs: List[Optional[MachineConfig]] = []

    for entry in machinedata:
        prog = entry.get("program", "")
        prog_sanitized = sanitize_program(prog)
        programs.append(prog_sanitized)
        canal_names.append(str(entry.get("canalNr", "1")))
        machine_names.append(str(entry.get("machineName", "FANUC_GENERIC")))
        
        custom_cfg_data = entry.get("customMachineConfig")
        if custom_cfg_data and isinstance(custom_cfg_data, dict):
            try:
                cfg = MachineConfig(
                    name=custom_cfg_data.get("name", "CUSTOM"),
                    control_type=custom_cfg_data.get("control_type", "FANUC"),
                    variable_pattern=custom_cfg_data.get("variable_pattern", r"#(\d+)"),
                    variable_prefix=custom_cfg_data.get("variable_prefix", "#"),
                    tool_range=tuple(custom_cfg_data.get("tool_range", (0, 9999))),
                    default_plane=custom_cfg_data.get("default_plane", "G17"),
                    default_feed_mode=custom_cfg_data.get("default_feed_mode", "FEED_PER_MIN"),
                    a_axis_rollover=custom_cfg_data.get("a_axis_rollover", False),
                    b_axis_rollover=custom_cfg_data.get("b_axis_rollover", False),
                    c_axis_rollover=custom_cfg_data.get("c_axis_rollover", False),
                    a_axis_shortest_path=custom_cfg_data.get("a_axis_shortest_path", False),
                    b_axis_shortest_path=custom_cfg_data.get("b_axis_shortest_path", False),
                    c_axis_shortest_path=custom_cfg_data.get("c_axis_shortest_path", False),
                    polar_interpolate_axis=custom_cfg_data.get("polar_interpolate_axis", "Y"),
                    diameter_axes=tuple(custom_cfg_data.get("diameter_axes", []))
                )
                custom_configs.append(cfg)
            except Exception as e:
                logging.warning(f"Failed to parse custom machine config: {e}")
                custom_configs.append(None)
        else:
            custom_configs.append(None)

        # Extract toolValues (Q quadrant 1-9 and R radius for tool compensation)
        tool_values = entry.get("toolValues", [])
        tool_values_list.append(tool_values)
        
        # Extract customVariables (user-defined variables)
        custom_vars = entry.get("customVariables", [])
        custom_variables_list.append(custom_vars)

    # Create initial CNC states with custom variables and tool data
    init_states = []
    for idx in range(len(programs)):
        if CNCState is not None:
            config = custom_configs[idx] if idx < len(custom_configs) and custom_configs[idx] is not None else get_machine_config(machine_names[idx])
            state = CNCState(
                machine_config=config,
                tool_path_mode=tool_path_mode,
            )
            # Set custom variables into state parameters
            custom_vars = custom_variables_list[idx] if idx < len(custom_variables_list) else []
            for var in custom_vars:
                var_name = str(var.get("name", ""))
                var_value = var.get("value", 0)
                if var_name:
                    try:
                        state.set_parameter(var_name, float(var_value))
                    except (ValueError, TypeError):
                        logging.warning(f"Invalid custom variable value: {var_name}={var_value}")
            
            # Store tool compensation values for later use by compensation handlers
            tool_vals = tool_values_list[idx] if idx < len(tool_values_list) else []
            tool_data = {}
            for tv in tool_vals:
                t_num = tv.get("toolNumber")
                if t_num is not None:
                    try:
                        key = int(t_num)
                    except ValueError:
                        key = str(t_num)

                    values = {
                        "qValue": tv.get("qValue"),  # Quadrant Q1-Q9
                        "rValue": tv.get("rValue"),  # Tool radius R
                    }
                    if "lengthValue" in tv:
                        values["lengthValue"] = tv.get("lengthValue")
                    if "edgeNumber" in tv:
                        values["edgeNumber"] = tv.get("edgeNumber")
                    tool_data[key] = values
            state.extra["tool_compensation_data"] = tool_data
            init_states.append(state)
        else:
            init_states.append(None)

    # Determine control type based on machine config
    first_machine = machine_names[0] if machine_names else ""
    config = custom_configs[0] if custom_configs and custom_configs[0] is not None else (get_machine_config(first_machine) if first_machine else None)
    
    is_siemens_mill = config is not None and config.control_type == "SIEMENS"

    engine_output = None
    errors: List[Dict[str, Any]] = []
    try:
        control = UniversalConfigDrivenControl(
            count_of_canals=len(programs), 
            canal_names=canal_names,
            init_nc_states=init_states if any(s is not None for s in init_states) else None
        )
        engine = NCExecutionEngine(control)
        engine_output = engine.get_Syncro_plot(programs, False)
        
        errors = getattr(engine, 'errors', [])
    except ExceptionNode as e:
        error_info = {
            "type": e.typ.name if hasattr(e.typ, 'name') else str(e.typ),
            "code": e.code,
            "line": e.line,
            "message": e.localized("en"),
            "value": str(e.value) if e.value else "",
        }
        errors.append(error_info)
        logging.warning("NC execution error: %s", error_info)
    except Exception as e:
        logging.warning("Real engine failed: %s. Falling back to mock parser.", e)

    use_mock = False
    if engine_output is None:
        use_mock = True
    else:
        total_points = 0
        for canal in engine_output:
            if isinstance(canal, dict):
                total_points += len(canal.get("plot", []))
            elif isinstance(canal, list):
                total_points += len(canal)
        
        if total_points == 0 and any(len(p.strip()) > 0 for p in programs) and not engine_output_has_non_plot_data(engine_output):
            logging.info("Real engine returned 0 points for non-empty program. Falling back to mock.")
            use_mock = True

    if use_mock:
        result = run_mock_parser(machinedata)
        if errors:
            result["errors"] = errors
        return result

    canal_results = {}
    messages = []
    for idx, canal in enumerate(engine_output):
        canal_nr = canal_names[idx] if idx < len(canal_names) else str(idx + 1)
        try:
            if isinstance(canal, list):
                canal = {"plot": canal, "programExec": []}

            converted = build_segments_from_engine_output(canal)
            canal_results[canal_nr] = converted
            messages.append(f"Successfully processed canal {canal_nr}")
        except Exception as e:
            logging.exception("Failed converting canal output for canal %s", canal_nr)
            return {
                "canal": canal_results,
                "message": [f"Conversion error for canal {canal_nr}: {str(e)}"],
                "success": False,
                "errors": errors,
            }

    response = {"canal": canal_results, "message": messages, "success": True}
    if errors:
        response["errors"] = errors
        response["hasErrors"] = True
    return response

def main():
    """Main CGI entry point"""
    try:
        request_method = os.environ.get("REQUEST_METHOD", "GET")
        
        if request_method != "POST":
            response = {
                "error": "Only POST requests are supported",
                "message_TEST": ["Method not allowed"]
            }
            print(json.dumps(response))
            return
        
        content_length = int(os.environ.get("CONTENT_LENGTH", 0))
        if content_length == 0:
            response = {
                "error": "Empty request body",
                "message_TEST": ["No data provided"]
            }
            print(json.dumps(response))
            return
        
        post_data = sys.stdin.read(content_length)
        request_data = json.loads(post_data)
        
        if "action" in request_data:
            action = request_data["action"]
            if action in ["list_machines", "get_machines"]:
                response = handle_list_machines()
            elif action in ["get_line_alignment_syntax", "get_multichannel_alignment_syntax", "get_sync_syntax"]:
                response = handle_get_line_alignment_syntax()
            else:
                response = {
                    "error": f"Unknown action: {action}",
                    "message_TEST": [f"Invalid action: {action}"]
                }
        
        elif "machinedata" in request_data:
            programs = request_data["machinedata"]
            response = handle_execute_programs(
                programs,
                request_data.get("toolPathMode", "effective"),
            )
        
        elif isinstance(request_data, list):
            response = handle_execute_programs(request_data)
        
        else:
            response = {
                "error": "Invalid request format",
                "message_TEST": ["Request must contain 'action' or 'machinedata'"]
            }
        
        print(json.dumps(response))
    
    except json.JSONDecodeError as e:
        response = {
            "error": "Invalid JSON",
            "message_TEST": [f"JSON parse error: {str(e)}"]
        }
        print(json.dumps(response))
    
    except Exception as e:
        response = {
            "error": "Internal server error",
            "message_TEST": [f"Server error: {str(e)}"]
        }
        print(json.dumps(response))

if __name__ == "__main__":
    main()
