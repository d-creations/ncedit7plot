# ncplot7py CNC Machine Simulator

`ncplot7py` is a Python module for parsing and simulating NC/CNC programs. It executes programs against configurable CNC machine controls and returns plot-ready toolpath data, executed lines, variables, timing, and errors.

The CGI script in `scripts/cgiserver.cgi` is only an adapter for frontends such as NC-Edit7. The core project is the Python simulation engine and machine-control model.

## What It Does

- Parses FANUC and Siemens-style NC programs.
- Simulates CNC machine state through configurable controls.
- Generates toolpath segments for plotting.
- Tracks executed NC lines, runtime, variables, named Siemens symbols, and errors.
- Supports single-channel and multi-channel machine configurations.
- Exposes machine metadata and editor syntax patterns for frontend integrations.

## Installation

Install from PyPI:

```bash
pip install ncplot7py
```

To include optional 3D plotting dependencies (matplotlib):

```bash
pip install "ncplot7py[plotting]"
```

## Python Module Usage

The normal usage is to import the package and run NC code through a configured control and the execution engine.

```python
from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl

program = """
G90 G54
G0 X0 Y0 Z10
G1 X50 Y0 F300
M30
"""

state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
control = UniversalConfigDrivenControl(init_nc_states=[state])
engine = NCExecutionEngine(control)

result = engine.get_Syncro_plot([program])
errors = engine.errors
runtime = engine.get_cacluated_runtime()
```

## Visualizing Toolpaths with Matplotlib

When installed with the `[plotting]` extra, you can plot the resulting 3D toolpath:

```python
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from ncplot7py.application.nc_execution import NCExecutionEngine
from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.machines import get_machine_config
from ncplot7py.infrastructure.machines.base_stateful_control import UniversalConfigDrivenControl

program = """
G90 G54
G0 X0 Y0 Z10
G1 X50 Y0 F300
G1 X50 Y50
G1 X0 Y50
G1 X0 Y0
M30
"""

state = CNCState(machine_config=get_machine_config("SIEMENS_840DI"))
control = UniversalConfigDrivenControl(init_nc_states=[state])
engine = NCExecutionEngine(control)

result = engine.get_Syncro_plot([program])

# Extract X, Y, Z coordinates from the plot segments
all_x, all_y, all_z = [], [], []
for canal in result:
    for line in canal.get("plot", []):
        all_x.extend(line.get("x", []))
        all_y.extend(line.get("y", []))
        all_z.extend(line.get("z", []))

# 3D Toolpath Plot
fig = plt.figure()
ax = fig.add_subplot(111, projection="3d")
ax.plot(all_x, all_y, all_z, label="Toolpath", color="blue")
ax.set_xlabel("X [mm]")
ax.set_ylabel("Y [mm]")
ax.set_zlabel("Z [mm]")
ax.set_title("NC Toolpath Simulation")
plt.legend()
plt.show()
```

See the scripts in `scripts/` for more runnable examples.

## Machine Configuration

The default machine configurations are defined in `src/ncplot7py/config/machines.json` and include:

- `SIEMENS_840DI` - Siemens milling control
- `FANUC_MILL` - FANUC milling control
- `FANUC_TURN` - FANUC turning control
- `FANUC_STAR_x-D_y-R_z_R` - FANUC turn/mill Swiss-style control
- `FANUC_STAR_x-D_y-D_z_R` - FANUC turn/mill Swiss-style control with X and Y diameter axes

Machine configs define the control family, parser, channel count, supported handler groups, default modal state, axis behavior, syntax rules, and execution limits.

## Frontend and CGI Adapter

For compatibility with NC-Edit7 and other frontend clients, the repository includes `scripts/cgiserver.cgi`. It accepts JSON requests, calls the real Python simulation engine, and returns JSON plot data.

The CGI adapter supports requests such as:

```json
{
  "action": "list_machines"
}
```

and program execution requests such as:

```json
{
  "machinedata": [
    {
      "program": "G90 G54\nG0 X0 Y0 Z10\nG1 X50 Y0 F300\nM30",
      "machineName": "SIEMENS_840DI",
      "canalNr": "channel-1"
    }
  ]
}
```

`customMachineConfig` can be supplied in a request when a frontend needs to run with a custom machine definition.

Detailed CGI request and response documentation is in `docs/CGI_API.md`.

## Local Development

Install the package in editable mode from the repository root:

```bash
python -m pip install -e .
```

Run tests with the source package on `PYTHONPATH`:

```bash
PYTHONPATH=src python -m pytest
```

On PowerShell:

```powershell
$env:PYTHONPATH='src'; python -m pytest
```

## CGI Deployment

Only deploy the CGI script when a web server needs to expose the simulator through a CGI interface.

Example Apache setup:

```apache
ScriptAlias /ncplot7py/scripts/ /var/www/NC-Edit7/ncplot7py/scripts/

<Directory /var/www/NC-Edit7/ncplot7py/scripts>
    Options +ExecCGI
    AddHandler cgi-script .cgi
    Require all granted
</Directory>
```

Make the adapter executable on Unix-like systems:

```bash
chmod +x scripts/cgiserver.cgi
```

For local frontend development, a Vite proxy can spawn `scripts/cgiserver.cgi`, but this is still just an adapter around the Python simulation module.
