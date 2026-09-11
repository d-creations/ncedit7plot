# CGI API for `scripts/cgiserver.cgi`

This document describes the CGI interface implemented by `scripts/cgiserver.cgi`.

## Overview
- The CGI script accepts a JSON POST and returns a JSON response.
- The script logs the request into a MariaDB table (if DB credentials are configured).
- The core processing runs the project's NC execution engine and returns syncro plot data.

## Request payload shapes
Two accepted shapes:

1) Object with `machinedata` list:

{
  "toolPathMode": "effective",
  "machinedata": [
    { "program": "<nc-program>", "machineName": "<machine>", "canalNr": <number-or-string> },
    ...
  ]
}

The optional top-level `toolPathMode` configures which coordinates the motion
handler should generate:

- `effective` (default): effective/programmed contour.
- `center`: tool-center path.

The value is stored in each channel's `CNCState` for the motion handler. Both
modes currently return the same coordinates; the distinction is reserved for
the later G41/G42 cutter-radius interpolation. An unknown value returns
`success: false`.

2) Direct list of machine-data objects:

[
  { "program": "<nc-program>", "machineName": "<machine>", "canalNr": "<canal>" },
  ...
]

Each machine-data entry must include `program`, `machineName`, and `canalNr`. An optional `customMachineConfig` dictionary can be included to override the machine configuration (Bring Your Own Config - BYOC).

## Allowed machine names
These are defined dynamically in `ncplot7py/config/machines.json`. Common defaults include:
- FANUC_STAR_x-D_y-R_z_R
- FANUC_STAR_x-D_y-D_z_R
- FANUC_TURN
- FANUC_MILL
- SIEMENS_840DI

## Bring Your Own Config (BYOC)
Instead of relying strictly on server-defined defaults, clients can dynamically configure the execution parameters by sending a `customMachineConfig` object within the request. If provided, these values override the settings derived from `machineName`. Example properties (all optional):
- `name` (str)
- `control_type` (str: "FANUC" or "SIEMENS")
- `variable_pattern` (str, e.g. `"#(\\d+)"`)
- `variable_prefix` (str, e.g. `"#"` or `"R"`)
- `tool_range` (list: `[min, max]`)
- `cycle_start_code` (str, e.g. `"M20"` or `"START:"`)
- `default_plane` (str)
- `default_feed_mode` (str)

## Validation rules
- Top-level must be an object containing `machinedata` or a list.
- Each entry must have `program`, `machineName`, and `canalNr`.
- `machineName` is highly recommended to be one of the known dynamic names to ensure proper default fallback logic, but can be a custom string if `customMachineConfig` is fully provided.
- `program` must NOT contain any of these characters: `(`, `)`, `{`, `}` — payloads containing them are rejected.

## Server-side preprocessing
- The script removes substrings matching `\(.*\)` from the program (comments in parentheses).
- Newlines are converted to semicolons: `\n` -> `;`.
- Spaces are removed from the program string.

## Side effects / logging
- The script attempts to insert a row into MariaDB `log.logNCR` with columns `IP` and `POST`.
- IP is taken from `REMOTE_ADDR` environment variable (trimmed to 19 characters) or "NAN" if missing.
- POST body is truncated when logged (approx 1000-1500 characters).
- MariaDB credentials must be provided in the running environment or script.

## Processing flow
- Builds initial `CNCState` instances per machine name.
- Sets X axis unit to `diameter` for lathe-style machines (SB12 and SR20, FANUC_T).
- Creates a `StatefulIsoTurnNCControl` with `count_of_canals`, `canal_names`, and initial `CNCState` list.
- Instantiates `NCExecutionEngine(control)` and calls `engine.get_Syncro_plot(programs, True)`.

## Response format
On success, a JSON object similar to:

{
  "canal": <engine_result>,
  "message": <message_stack>
}

- `canal` contains the syncro plot data returned by the execution engine.
- Each canal result includes `variables` for numeric register variables and `namedVariables` for Siemens named variables and flattened array elements such as `ANGLE_Z` and `CUSTOM_MC[3]`.
- `message` is the project's message stack (diagnostics/info accumulated during processing).

Each item in a canal's `segments` list includes motion semantics separately from timing:

```json
{
  "type": "RAPID",
  "geometry": "LINEAR",
  "traversal": "RAPID",
  "sourceCode": "G00",
  "lineNumber": 10,
  "toolNumber": 1,
  "points": [{"x": 0.0, "y": 0.0, "z": 0.0}]
}
```

- `geometry` is `LINEAR`, `ARC_CW`, or `ARC_CCW` when known.
- `traversal` is `RAPID` or `FEED` when known.
- `sourceCode` is the effective modal interpolation code (`G00`, `G01`, `G02`, or `G03`) when known.
- `type` remains the compatibility display value: `RAPID` for rapid traversal, otherwise the geometry value. It is `UNKNOWN` when the engine marks a generated path as having no single motion classification.
- The semantic fields can be `null` for legacy engine output or compound generated paths that do not have one motion classification.
- Implemented FANUC turning drilling cycles (`G83`, `G84`, `G85`, `G87`, and `G89`) are expanded into separate primitive segments. Every approach/retract segment has `geometry: "LINEAR"`, `traversal: "RAPID"`, and `sourceCode: "G00"`; every cutting/tapping/boring segment has `geometry: "LINEAR"`, `traversal: "FEED"`, and `sourceCode: "G01"`.
- Implemented FANUC threading cycles are also expanded. `G92` and `G76` thread cuts use `geometry: "LINEAR"`, `traversal: "FEED"`, and their original `sourceCode`; their positioning/retract movements use `LINEAR/RAPID/G00`. Optional `G36` circular threading uses `ARC_CCW/FEED/G36`.
- `G68.1` coordinate rotation rewrites program coordinates before ordinary motion handling, so resulting segments retain their normal `LINEAR`/arc geometry and `RAPID`/`FEED` traversal. `G69.1` cancels rotation; Star profiles also accept `G69` as the cancel alias.
- Star `G910/G920` B1 indexing emits `geometry: "LINEAR"`, `traversal: "RAPID"`, with `sourceCode` set to the original command. The engine stores the explicit tilted-coordinate reference, but does not claim the proprietary automatic X/Z tool-offset calculation without the Star programming formula.
- Star `G161` accepts required `A` and `D` values from `1..5`, optional nonnegative `Q`, and no preceding `M41`. A parameter-only block produces no drawing segment. When `X/Y/Z` is present, the explicit or active modal feed executes the endpoint as a timed `LINEAR/FEED/G161` segment. The segment represents the correct net path; detailed forward/back amplitude oscillations are not expanded without the machine formula.
- Other compound paths may still remain one points/duration entry. Clients should render `UNKNOWN` as an unclassified continuous path rather than infer rapid/feed from duration.
- Duration is not used to classify segments when semantic metadata is present.

On error, the script returns a JSON-like error message such as:

{"message_TEST": "<error>", "program": [ ... ]}

or

{"message_T": "<error>", "program": []}

(Exact shape may vary depending on where the exception was raised.)

## Example request (JSON body)

Single program (object with `machinedata`):

{
  "machinedata": [
    {
      "program": "N10 G00 X0 Y0\nN20 G01 X10 Y0",
      "machineName": "FANUC_STAR",
      "canalNr": 1
    }
  ]
}

Equivalent as a plain list:

[
  {
    "program": "N10 G00 X0 Y0\nN20 G01 X10 Y0",
      "machineName": "FANUC_STAR",
      "canalNr": "canal1"
  }
]

## Example PowerShell POST (replace URL)

```powershell
$json = @'
{
  "machinedata": [
    { "program": "N10 G00 X0 Y0\nN20 G01 X10 Y0", "machineName": "FANUC_STAR", "canalNr": 1 }
  ]
}
'@

Invoke-RestMethod -Uri 'https://your-server/cgi-bin/cgiserver.cgi' -Method Post -Body $json -ContentType 'application/json'
```

## Example response (success)

```json
{
  "canal": [ /* engine-specific syncro plot structure */ ],
  "message": [ /* diagnostic messages */ ]
}
```

## Notes / caveats
- The script has two `request_precheck` blocks; the later one is authoritative for validation.
- Ensure MariaDB credentials and connectivity are configured in the environment where the CGI runs.
- Clients need not pre-normalize newlines or spaces; the server will remove spaces and convert newlines to semicolons, but clients must avoid forbidden characters.

## Listing available machines (new)

The CGI supports a lightweight request to retrieve the available machine names and a simple control type description.

Request JSON body:

{
  "action": "list_machines"
}

or

{
  "action": "get_machines"
}

Response JSON body:

{
  "machines": [
    { "machineName": "FANUC_STAR", "controlType": "FANUC_STAR" },
    { "machineName": "SIEMENS_840DI", "controlType": "SIEMENS_840DI" },
    ...
  ]
}

This is useful for clients to discover supported machine names before sending processing requests.

## Getting multichannel line-alignment syntax

Request JSON body:

```json
{
  "action": "get_line_alignment_syntax"
}
```

The aliases `get_multichannel_alignment_syntax` and `get_sync_syntax` are also accepted. The response contains structured syntax for:

- Two-channel FANUC alignment using the same `M200` through `M899` code in both channels.
- Three-channel FANUC alignment using the same M code plus `P12`, `P13`, `P23`, or `P123` in each participating channel.
- Siemens alignment using the same `WAITM(<marker>)` value in each channel.

Example response:

```json
{
  "lineAlignmentSyntax": [
    {
      "controlType": "FANUC",
      "waitCodeRange": {"min": 200, "max": 899},
      "twoChannel": {
        "syntax": "M<waitCode>",
        "example": {"channel1": "M200", "channel2": "M200"}
      },
      "threeChannel": {
        "syntax": "M<waitCode> P<channels>",
        "selectors": ["P12", "P13", "P23", "P123"],
        "example": {
          "channel1": "M899 P123",
          "channel2": "M899 P123",
          "channel3": "M899 P123"
        }
      }
    },
    {
      "controlType": "SIEMENS",
      "syntax": "WAITM(<marker>)",
      "example": {"channel1": "WAITM(1)", "channel2": "WAITM(1)"}
    }
  ],
  "success": true
}
```

---

Generated from `scripts/cgiserver.cgi` in the repository. If you'd like, I can also add an automated test or a small example script under `scripts/` to POST a sample request and save the response.