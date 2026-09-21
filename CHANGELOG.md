# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-09-21

### Added
- Siemens simulation profiles now accept both numeric tool ranges and arbitrary named tools through generic named-tool mounts.
- Added tool compensation support for configured tool radius and offset data.

### Fixed
- STAR `G161` now accepts parameter-only `A`/`D` blocks, omitted or zero `Q`, and execution without a preceding `M41`; endpoint movement can use the active modal feed.
- STAR `G125` now accepts a block without `Z` and treats it as `G125 Z0`.
- Pose mount lookup now matches numeric tool IDs represented as either integers or numeric strings, including channel-specific STAR tools.

---

## [0.1.4] - 2026-08-12

### Added
- Added CGI segment `geometry`, `traversal`, and `sourceCode` metadata for rapid, linear, clockwise-arc, and counterclockwise-arc motions.
- Added machine-specific modal M-code handlers for FANUC Mill, FANUC Turn, STAR, and Siemens Mill controls.
- Added separate FANUC Turn handlers for `G20/G21` units, `G80/G83/G84/G85/G87/G89` drilling cycles, `G92` threading, two-block `G76` multiple threading, optional `G36` circular threading, and `G68.1/G69.1` coordinate rotation.
- Added separate STAR handlers for `G25/G26` spindle fluctuation monitoring, `G125/G130-G133` automatic-coordinate state, validated `G266` setup, `G910/G920` B1 tilting, and option-gated `G161` Step Cycle Pro.
- Added machine capability settings for circular threading and Step Cycle Pro.
- Added classified primitive expansion for canned drilling and threading cycles so rapid, feed, linear, and arc phases remain distinguishable in CGI drawing output.

### Changed
- FANUC Turn and STAR `M3`/`M4` commands now return the C-axis to zero; STAR `M9` retains its C-axis return behavior.
- Spindle direction, coolant mode, and Siemens `M82`/`M83` probe state are now managed by the corresponding machine-specific M-code handler.
- Machine profiles now explicitly select control-specific tool, M-code, FANUC Turn, and STAR handlers instead of relying on implicit STAR handler injection.
- STAR `G161` now validates `X/Y/Z A F D Q`, enforces `G97`, `G99`, `M41`, and option prerequisites, and emits a timed `LINEAR/FEED/G161` net endpoint path.
- FANUC and STAR generated cycle movements now retain their original source code and editor line number after expansion into drawing segments.
- STAR `G69` is accepted as the machine-specific alias for FANUC `G69.1` coordinate-rotation cancellation.

### Fixed
- Fixed configured G0 movements with nonzero duration being returned as normal linear-feed segments.
- Fixed compound canned-cycle paths being returned as a single unclassified `UNKNOWN` drawing segment.
- Removed the obsolete backward-compatible generic `ToolHandler` import; tests and machine profiles now use explicit FANUC or STAR tool handlers.
- Added documented format, modal-state, option, path-mode, tool-range, and numeric-range validation for the implemented FANUC Turn and STAR G-codes.

---

## [0.1.3] - 2026-08-11

### Fixed
- Fixed FANUC `M99` failing to terminate program execution, which could incorrectly execute later blocks such as unreachable `#3000` alarms.
- Fixed Siemens `M30` failing to terminate execution before subsequent program blocks.

### Added
- Added `FANUC_STAR_x-D_y-R_z_R.M.S` and `FANUC_STAR_x-D_y-D_z_R.M.S` controls for STAR two-channel programs using `.M` for the main channel and `.S` for the secondary channel.
- Added separate G96/G97 speed-mode handlers for FANUC Turn, FANUC Mill, and Siemens controls.
- Added configurable `g96_reference_axis` machine settings and Siemens `SCC[axis]` runtime reference-axis selection.
- Added Siemens G93 inverse-time feed and G961/G962/G971/G972/G973 constant-cutting-speed variants.
- Added FANUC Turn and STAR `G50 S...` maximum spindle-speed clamps.
- Added Siemens `G25` minimum, `G26` maximum, and indexed spindle-speed limits.
- Added Siemens `LIMS` spindle-speed limiting independently of persistent G25/G26 limits.

### Changed
- Constant-cutting-speed timing now derives effective RPM from cutting speed and the configured or programmed reference-axis diameter.
- Feed-per-revolution timing now applies controller-specific minimum and maximum spindle-speed limits.
- Siemens G96/G97 variants now select or preserve G94/G95 feed modes according to Siemens semantics.

### Fixed
- Fixed G96 cutting speed being interpreted directly as RPM during machining-time calculation.
- Fixed Siemens speed modes incorrectly reusing the FANUC Turn handler.
- Fixed Siemens `SCC[...]`, `LIMS=...`, and indexed spindle-limit parsing.
- Fixed G973 incorrectly inheriting an active `LIMS` clamp.

---

## [0.1.2] - 2026-07-29

### Added
- Added FANUC custom macro alarm support for `#3000 = n (ALARM MESSAGE)` across all FANUC machine controls.
- Added a dedicated Siemens user alarm handler for `SETAL(<alarm_no>[,"Alarm text"])` commands.
- Added structured alarm details to `state.extra["alarms"]`, including the alarm code, message, and source line.

### Changed
- FANUC `#3000` and Siemens `SETAL` user alarms now stop NC code execution and propagate through the existing structured error path.
- Siemens `SETAL` alarm handling is separated from the general Siemens built-in command handler.

### Fixed
- Preserved FANUC parenthesized alarm messages while continuing to discard ordinary FANUC comments.
- Added Siemens `SETAL` alarm-number validation and explicit errors for malformed syntax while allowing configured alarm numbers outside the standard user-alarm range.

---

## [0.1.1] - 2026-07-28

### Added
- Added machine-specific NC program lexers selected through `lexer_name` in the machine configuration.
- Added a language frontend that composes the configured lexer and command parser for each machine control.
- Added source-aware lexer statements that retain original line and column information.
- Added a lexer registry for integrating additional controller dialects without changing the execution engine.

### Changed
- Moved program splitting and comment processing out of `NCExecutionEngine` and the command parser interface into machine-specific lexers.
- Updated config-driven controls to construct their parser and lexer frontend from `machines.json`.
- Corrected the Siemens syntax-highlighting comment rule to use semicolon comments.

### Fixed
- Fixed Siemens lines beginning with `;` being split and executed as NC commands.
- Fixed Siemens inline comments while preserving semicolons inside quoted strings and `SETAL(...);message` alarm text.
- Fixed nested FANUC parenthesis comments and prevented semicolons inside comments or quoted strings from splitting commands.
- Fixed `POCKET4` depth calculation: `DP=0` with `DPR>0` now correctly uses the relative depth instead of silently producing zero depth.
- Fixed `POCKET4` ignoring the `MID` parameter; the cycle now steps down by `MID` per pass and mills concentric circles at each depth level.

---

## [0.1.0] - 2026-06-24

### Changed
- Improved Siemens 840DI control (`SIEMENS_840DI`) handling and simulation accuracy.

---

## [0.0.1] - initial release

### Added
- Initial release of `ncplot7py`.
- FANUC and Siemens-style NC program parsing and simulation.
- Toolpath segment generation for plotting.
- Single-channel and multi-channel machine configuration support.
- CGI adapter (`scripts/cgiserver.cgi`) for NC-Edit7 frontend integration.
