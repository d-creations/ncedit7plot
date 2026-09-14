# CGI API for `scripts/cgiserver.cgi`

This document describes the CGI interface implemented by `scripts/cgiserver.cgi`.

## Simulation negotiation and R0 (2026-09-14)

One POST executes all selected channels together. Simulation configuration and
request negotiation are implemented; workpiece tool-pose production is not.
Discovery includes `axes`, `availableChannels`, `profileRevision`,
`supportedPoseContracts`, and `simulation` when configured. The fingerprint
covers all loaded execution/simulation fields. Undeclared axes are `[]`.

Configuration `simulation` requires schemaVersion=1, revision, modelId,
displayName, fidelity (demo/configured), poseContract, carriers and toolMounts.
Carriers declare ID, role, referenceOrientationDegrees and rotationChain.
Mounts declare channelId, numericRange/identifiers, tool carrier and fixed or
execution-resolved target. Invalid references, transforms, unknown fields and
overlapping selections reject the configuration load atomically.

The pose-request shape is:

```json
{
  "toolPathMode": "center",
  "poseContract": "workpiece-tool-reference-v1",
  "machinedata": [{
    "machineName": "FANUC_MILL", "canalNr": "1", "program": "T1",
    "toolValues": [{"toolNumber": 1, "rValue": 0}],
    "simulation": {
      "profileRevision": "copy-the-exact-discovery-value",
      "tools": [{"toolNumber": 1, "reference": "millingTip", "mountingOrientationDegrees": [0, 0, 0]}]
    }
  }]
}
```

This is a negotiation example, not enabled pose execution. Currently
supportedPoseContracts is empty. Validated requests return
POSE_CONTRACT_UNSUPPORTED before execution, not downgraded XYZ data. Stale
revisions return PROFILE_REVISION_MISMATCH. Invalid pose data, unknown profiles
and pose-mode customMachineConfig return SIMULATION_INPUT_INVALID. The error
envelope is `{success:false, canal:{}, message:[...], errors:[{code,message,channelId?}]}`.
Path-only requests omit poseContract and the per-entry simulation field.

Explicit rValue=0 is valid in toolValues and positive-numbered toolOffsets.
G41/G42 remain selected but generate zero radius displacement. Zero is not
missing data or a fallback to a nonzero tool default. Negative/missing radius
fails compensation activation. Register zero remains cancellation, not storage.

Execution errors and unavailable engines return success=false, never mock or
partial success. A valid empty plot succeeds. Success reports
executionOrigin="engine". Clients must check success before consuming paths.

## Overview
- The CGI script accepts a JSON POST and returns a JSON response.
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

The optional top-level `toolPathMode` selects which coordinates the output
pipeline returns:

- `effective` (default): effective/programmed contour.
- `center`: tool-center path.

The value is stored independently in each channel's `CNCState`. In `center`
mode, FANUC mill and Siemens ISO `G41/G42` paths are offset by the active
tool's `rValue`; `G40` cancels the offset. The current implementation uses the
generated polyline, so arcs are compensated at their configured tessellation
resolution. Turning tool-nose compensation and dynamic TCP modes are not yet
implemented. An unknown mode returns `success: false`.

2) Direct list of machine-data objects:

[
  { "program": "<nc-program>", "machineName": "<machine>", "canalNr": "<canal>" },
  ...
]

Each machine-data entry must include `program`, `machineName`, and `canalNr`. An optional `customMachineConfig` dictionary can be included to override the machine configuration (Bring Your Own Config - BYOC).

An entry may include `toolValues`. Each item requires `toolNumber` and accepts
optional compensation values:

- `qValue`: tool-tip orientation/quadrant.
- `rValue`: cutter or tool-nose radius, including explicit zero.
- `lengthValue`: tool length reserved for length/TCP compensation.
- `edgeNumber`: cutting-edge/offset identifier reserved for later lookup.

The CGI stores supplied values in that channel's `CNCState`. `lengthValue` and
`edgeNumber` are preserved but do not yet change generated geometry.

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
- Program syntax is interpreted by the selected parser; the old blanket parenthesis/brace rejection is not present in this script.

## Server-side preprocessing
- The sanitizer preserves line boundaries, normalizes token spacing and keeps the last duplicated numeric XYZ/IJK token in each semicolon-delimited part.
- Parenthesis removal is disabled because Siemens uses parentheses in commands. The API does not strip all spaces or convert newlines into semicolons.

## Side effects / logging
- Diagnostics go to stderr. The current script has no MariaDB request-logging operation.

## Processing flow
- Builds initial `CNCState` instances per machine name.
- Loads tool/offset data into independent channel states; units follow configured execution handlers.
- Creates a `UniversalConfigDrivenControl` with channel names and initial states.
- Instantiates `NCExecutionEngine(control)` once and calls `engine.get_Syncro_plot(programs, False)`.

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
  "executionStep": 5,
  "toolNumber": 2,
  "points": [{"x": 0.0, "y": 0.0, "z": 0.0}]
}
```

- `geometry` is `LINEAR`, `ARC_CW`, or `ARC_CCW` when known.
- `traversal` is `RAPID` or `FEED` when known.
- `sourceCode` is the effective modal interpolation code (`G00`, `G01`, `G02`, or `G03`) when known.
- `executionStep` is the zero-based executed-command occurrence in its channel. Generated cycle segments from the same command share one step.
- `toolNumber` is the active numeric tool, named-tool string, or `"unknown"` when no active tool can be determined.
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
  "success": true,
  "executionOrigin": "engine",
  "canal": {"1": {"segments": []}},
  "message": []
}
```

## Notes / caveats
- Clients should send original program lines rather than applying obsolete CGI preprocessing rules.
- API/config identifiers remain exact. The existing execution parser can turn quoted numeric Siemens tool names such as T="1" into numeric IDs; this separate issue is not fixed by the R0 update.

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