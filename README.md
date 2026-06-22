# e3008 CAN Reverse Analysis - Technical Research Documentation

Date: June 16, 2026  
Project status: Analysis complete; implementation guidance available

---

## Abstract

This repository documents reverse analysis of Peugeot e3008 CAN traffic with focus on battery contactor control, state feedback, battery telemetry, and platform-level architecture comparison with CMP-SMART (Stellantis small-car platform). The strongest validated finding is that `0x281` byte0 drives contactor state progression and `0x591` reports the resulting BMS state transitions.

The documentation below is organized as a research-style index: dataset, method, principal findings, confidence, limitations, reproducibility, and references to all technical artifacts.

---

## Dataset and Scope

- Source captures: [e3008 can dump](e3008%20can%20dump/)
- Capture count: 12 candump files
- Coverage basis: 252,607+ parsed CAN frames
- Primary operating point: SOC near 83%
- Supporting extraction/statistics file: [analysis_summary.txt](analysis_summary.txt)

Scope includes frame-level decoding, state transition correlation, timing behavior, and architecture inference. Hardware actuation validation is planned but outside this documentation-only scope.

---

## Methodology (Research Process)

1. Parse and normalize candump rows by timestamp, ID, payload.
2. Build per-ID timelines and unique payload sets.
3. Detect transition anchors on contactor feedback frame (`0x591`).
4. Correlate pre/post windows to identify candidate command frames.
5. Validate repeatability across all captures.
6. Compare behavior with CMP-SMART reference patterns.

Primary reasoning model used: temporal precedence (command must appear before state change), sequence consistency, and cross-file reproducibility.

---

## Primary Findings (Current Best-Supported)

### Core control and feedback
- `0x281` byte0: primary contactor command progression signal (VCU -> BMS)
- `0x591`: contactor/BMS state feedback sequence (BMS -> VCU)
- OFF -> ON close path: approximately 2.3s total
- ON -> OFF open path: approximately 120s total, including long safety dwell

### Additional architecture signals
- `0x428`: watchdog/counter-like repeating pattern (16-step cycle behavior)
- `0x583`: cell and temperature probe counts (`96` cells / `24` temp probes)
- `0x334`: multiplexed cell voltages
- `0x3F4`: multiplexed temperature probe values
- `0x353`: state of charge (SoC)
- Supporting correlated IDs observed around transitions: `0x026`, `0x046`, `0x186`, `0x342`

### Platform comparison
- e3008 and CMP-SMART are both Stellantis-related approaches with shared control philosophy.
- Observed implementation difference: e3008 appears more distributed/progressive versus simpler centralized toggling patterns in small-platform references.

For raw evidence tables and sequence-level details, use [COMPREHENSIVE_FINDINGS.md](COMPREHENSIVE_FINDINGS.md).

---

## Confidence and Limitations

### High-confidence conclusions
- `0x281` progression behavior preceding `0x591` transitions
- Repeatable timing/state ordering across captures
- Stable identification of core command/feedback relationship

### Partial/ongoing interpretation areas
- Complete semantics of supporting correlated frames
- Full meaning of all non-byte0 context bytes in some command-related frames
- Scaling and physical calibration of selected telemetry channels

### External validity limits
- Current corpus is dominated by one SOC region and specific test scenarios.
- Additional multi-SOC, temperature, and stress-condition captures are recommended.

---

## Reproducibility and Implementation Assets

- Firmware implementation starter: [main.cpp](main.cpp)
- Build configuration: [platformio.ini](platformio.ini)
- Detailed command decode and implementation notes: [0x281_COMMAND_FRAME_DECODED.md](0x281_COMMAND_FRAME_DECODED.md)

Recommended implementation sequence:
1. Implement `0x281` listener and state-machine logic.
2. Emit/validate `0x591` expected transitions.
3. Add watchdog/mode/supporting frame handling incrementally.
4. Validate timing and dwell windows against captured baselines.

---

## Complete Linked Documentation Map (All .md Files)

### Research summaries and status
- [DISCOVERY_SUMMARY.md](DISCOVERY_SUMMARY.md) - concise discovery statement
- [ANALYSIS_COMPLETE_SUMMARY.md](ANALYSIS_COMPLETE_SUMMARY.md) - consolidated outcomes
- [SESSION_4_ADDITIONS.md](SESSION_4_ADDITIONS.md) - latest additions and changes

### Core technical evidence
- [COMPREHENSIVE_FINDINGS.md](COMPREHENSIVE_FINDINGS.md) - main evidence and decoded frame set
- [0x281_COMMAND_FRAME_DECODED.md](0x281_COMMAND_FRAME_DECODED.md) - deep decode for `0x281`
- [CELL_TEMP_STORAGE_MANUAL.md](CELL_TEMP_STORAGE_MANUAL.md) - deep decode for `0x583`/`0x334`/`0x3F4` telemetry storage
- [CONTACTOR_CONTROL_ANALYSIS.md](CONTACTOR_CONTROL_ANALYSIS.md) - evidence path for command discovery
- [EXTENDED_ARCHITECTURE_ANALYSIS.md](EXTENDED_ARCHITECTURE_ANALYSIS.md) - multi-frame architecture extensions

### Visual, comparative, and navigation aids
- [VISUAL_ARCHITECTURE.md](VISUAL_ARCHITECTURE.md) - visual sequence/timing overview
- [CMP_SMART_COMPARISON_VISUAL.md](CMP_SMART_COMPARISON_VISUAL.md) - comparative architecture summary
- [CROSS_REFERENCE_INDEX.md](CROSS_REFERENCE_INDEX.md) - lookup index by topic/frame/use-case

### Legacy/traceability documents
- [findings.md](findings.md) - earlier-stage findings snapshot
- [report_e3008_83soc.md](report_e3008_83soc.md) - initial SOC-specific report

---

## Reading Paths by Objective

### Fast orientation (5-10 min)
1. [DISCOVERY_SUMMARY.md](DISCOVERY_SUMMARY.md)
2. [ANALYSIS_COMPLETE_SUMMARY.md](ANALYSIS_COMPLETE_SUMMARY.md)
3. [VISUAL_ARCHITECTURE.md](VISUAL_ARCHITECTURE.md)

### Full technical review
1. [COMPREHENSIVE_FINDINGS.md](COMPREHENSIVE_FINDINGS.md)
2. [0x281_COMMAND_FRAME_DECODED.md](0x281_COMMAND_FRAME_DECODED.md)
3. [EXTENDED_ARCHITECTURE_ANALYSIS.md](EXTENDED_ARCHITECTURE_ANALYSIS.md)
4. [CONTACTOR_CONTROL_ANALYSIS.md](CONTACTOR_CONTROL_ANALYSIS.md)
5. [CMP_SMART_COMPARISON_VISUAL.md](CMP_SMART_COMPARISON_VISUAL.md)

### Firmware implementation focus
1. [0x281_COMMAND_FRAME_DECODED.md](0x281_COMMAND_FRAME_DECODED.md)
2. [CELL_TEMP_STORAGE_MANUAL.md](CELL_TEMP_STORAGE_MANUAL.md)
3. [COMPREHENSIVE_FINDINGS.md](COMPREHENSIVE_FINDINGS.md)
4. [main.cpp](src/main.cpp)
5. [platformio.ini](platformio.ini)

---

## Maintenance Protocol

When new findings are added:
1. Update the primary evidence file first (usually [COMPREHENSIVE_FINDINGS.md](COMPREHENSIVE_FINDINGS.md)).
2. Update lookup mapping in [CROSS_REFERENCE_INDEX.md](CROSS_REFERENCE_INDEX.md).
3. Update this README index so all documents remain discoverable.


