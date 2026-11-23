# Quick Cross-Reference Index

**Complete Analysis Inventory - All Discoveries Mapped**

---

## By Discovery Type

### Contactor Command Frames
| Discovery | Primary Document | Secondary Reference |
|-----------|------------------|-------------------|
| 0x281 primary command frame | `0x281_COMMAND_FRAME_DECODED.md` | `CONTACTOR_CONTROL_ANALYSIS.md`, `COMPREHENSIVE_FINDINGS.md` |
| 0x281 byte0 CLOSE sequence (6 steps) | `0x281_COMMAND_FRAME_DECODED.md` | `VISUAL_ARCHITECTURE.md` |
| 0x281 byte0 OPEN sequence (6 steps) | `0x281_COMMAND_FRAME_DECODED.md` | `COMPREHENSIVE_FINDINGS.md` |
| 0x281 bit7 function (OPEN intent) | `0x281_COMMAND_FRAME_DECODED.md` | `CONTACTOR_CONTROL_ANALYSIS.md` |

### Supporting Control Frames (New Discovery)
| Discovery | Primary Document | Notes |
|-----------|------------------|-------|
| 0x026 byte0 correlation with state | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 70%+ correlation with transitions |
| 0x046 byte0 correlation with state | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 70%+ correlation with transitions |
| 0x186 byte0 correlation with state | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 70%+ correlation with transitions |
| 0x342 byte0 correlation with state | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 70%+ correlation with transitions |

### Watchdog & Mode Frames (New Discovery)
| Discovery | Primary Document | Equivalent |
|-----------|------------------|-----------|
| 0x428 watchdog counter (40ms) | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | CMP-SMART 0x351 byte7 counter |
| 0x428 byte0 sequence (0x0E-0xFF) | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 16 values, 0x0F increment |
| 0x353 mode indicator (binary) | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | CMP-SMART 0x211 charge/discharge |
| 0x353 values (0x00 vs 0x83) | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | Idle vs active driving |

### State Feedback Frames
| Discovery | Primary Document | Details |
|-----------|------------------|---------|
| 0x591 state machine (12 states) | `COMPREHENSIVE_FINDINGS.md` | All states mapped with timings |
| 0x591 OFF→ON timing (~2.3s) | `COMPREHENSIVE_FINDINGS.md` | Precharge ~1.3s + main ~1s |
| 0x591 ON→OFF timing (~120s) | `COMPREHENSIVE_FINDINGS.md` | 61s major dwell for capacitor discharge |
| 0x591 precharge states | `VISUAL_ARCHITECTURE.md` | 3 sub-states during precharge phase |

### Battery Telemetry Frames
| Discovery | Primary Document | Formula |
|-----------|------------------|---------|
| 0x334 cell voltages | `CELL_TEMP_STORAGE_MANUAL.md` | `mux=byte0>>3`, packed words -> `>>2/>>4/>>4` |
| 0x3F4 temperatures | `CELL_TEMP_STORAGE_MANUAL.md` | `slot=byte0>>6`, 7 channels, `tempC=raw-40` |
| 0x583 cell/temp counts | `CELL_TEMP_STORAGE_MANUAL.md` | readiness states + bytes5/6 = `24/96` |
| 0x353 SOC percentage | `CELL_TEMP_STORAGE_MANUAL.md` | byte3 (`0x83` = 83% in these captures) |

### CMP-SMART Comparison
| Topic | Document | Content |
|-------|----------|---------|
| Architecture comparison table | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | Side-by-side e3008 vs CMP-SMART |
| Watchdog concept | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 0x428 (e3008) vs 0x351 (CMP-SMART) |
| Mode indicator | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | 0x353 (e3008) vs 0x211 (CMP-SMART) |
| Command strategy difference | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | Distributed (e3008) vs centralized (CMP-SMART) |
| Manufacturer validation | `CONTACTOR_CONTROL_ANALYSIS.md` | Both Stellantis, different platforms |

---

## By Frame ID

### 0x026
- **First mentioned:** `EXTENDED_ARCHITECTURE_ANALYSIS.md`
- **Analysis:** Byte0 changes at 70%+ of 0x591 transitions
- **Type:** Supporting control frame (handshake)
- **Significance:** Part of multi-frame coordination

### 0x046
- **First mentioned:** `EXTENDED_ARCHITECTURE_ANALYSIS.md`
- **Analysis:** Byte0 changes at 70%+ of 0x591 transitions
- **Type:** Supporting control frame (handshake)
- **Significance:** Part of multi-frame coordination

### 0x186
- **First mentioned:** `EXTENDED_ARCHITECTURE_ANALYSIS.md`
- **Analysis:** Byte0 changes at 70%+ of 0x591 transitions
- **Type:** Supporting control frame (handshake)
- **Significance:** Part of multi-frame coordination

### 0x281
- **Primary source:** `0x281_COMMAND_FRAME_DECODED.md`
- **Secondary:** `CONTACTOR_CONTROL_ANALYSIS.md`, `COMPREHENSIVE_FINDINGS.md`
- **Type:** Primary contactor command
- **Status:** FULLY DECODED

### 0x334
- **Source:** `CELL_TEMP_STORAGE_MANUAL.md`
- **Type:** Cell voltages telemetry
- **Formula:** `mux=byte0>>3`, packed extraction (`>>2/>>4/>>4`)
- **Status:** DECODED WITH PARTIAL CHANNEL MAP (96 total not fully mapped from 0x334 alone)

### 0x342
- **First mentioned:** `EXTENDED_ARCHITECTURE_ANALYSIS.md`
- **Analysis:** Byte0 changes at 70%+ of 0x591 transitions
- **Type:** Supporting control frame (handshake)
- **Significance:** Part of multi-frame coordination

### 0x353
- **Primary source:** `EXTENDED_ARCHITECTURE_ANALYSIS.md`
- **Type:** Mode indicator (charge/discharge)
- **Values:** 0x00 (idle) or 0x83 (active)
- **Equivalent:** CMP-SMART 0x211 byte2

### 0x3F4
- **Source:** `CELL_TEMP_STORAGE_MANUAL.md`
- **Type:** Temperature telemetry
- **Details:** `slot=byte0>>6`, 7 values per slot, `tempC=raw-40`
- **Status:** DECODED WITH PARTIAL PHYSICAL PROBE MAP

### 0x428
- **Primary source:** `EXTENDED_ARCHITECTURE_ANALYSIS.md`
- **Type:** Watchdog/keepalive counter
- **Sequence:** 0x0E → 0x1D → ... → 0xFF (16 steps)
- **Equivalent:** CMP-SMART 0x351 byte7 counter

### 0x583
- **Source:** `CELL_TEMP_STORAGE_MANUAL.md`
- **Type:** Battery validity + counts
- **Details:** state classes (`FDFD..`, `0000..`, `1509..`, `1709..`) and bytes5/6 manifest (`24/96`)
- **Status:** DECODED

### 0x591
- **Primary source:** `COMPREHENSIVE_FINDINGS.md`, `CONTACTOR_CONTROL_ANALYSIS.md`
- **Secondary:** `VISUAL_ARCHITECTURE.md`
- **Type:** Contactor state feedback
- **Details:** 12-state machine with full timing sequence
- **Status:** FULLY DECODED

---

## By File Purpose

### Implementation Guides
1. **0x281_COMMAND_FRAME_DECODED.md**
   - Who should read: Firmware developers implementing contactor control
   - Contains: Complete byte0 reference table, bit analysis, C code examples
   - Next step: Add 0x428 watchdog per `EXTENDED_ARCHITECTURE_ANALYSIS.md`

2. **EXTENDED_ARCHITECTURE_ANALYSIS.md**
   - Who should read: Architects, firmware developers, anyone understanding full system
   - Contains: Supporting frame coordination, watchdog/mode frames, CMP-SMART comparison
   - Prerequisite: Read `0x281_COMMAND_FRAME_DECODED.md` first

### Reference Documents
1. **COMPREHENSIVE_FINDINGS.md**
   - Who should read: System integrators, hardware testers
   - Contains: All decoded frame IDs, empirical formulas, firmware rules
   - Cross-reference: For any frame specs not in specialized docs

2. **VISUAL_ARCHITECTURE.md**
   - Who should read: Anyone wanting graphical understanding
   - Contains: Flow diagrams, state machines, timelines
   - Best for: Understanding timing relationships

### Summary/Discovery Process
1. **DISCOVERY_SUMMARY.md**
   - Who should read: New readers, executives
   - Contains: Quick answer ("0x281 found!"), method, validation
   - Length: 5 minutes to understand

2. **ANALYSIS_COMPLETE_SUMMARY.md**
   - Who should read: Project managers, comprehensive reviewers
   - Contains: All discoveries, confidence levels, roadmap
   - Length: 10-15 minutes to fully understand

3. **CONTACTOR_CONTROL_ANALYSIS.md**
   - Who should read: Those interested in discovery process
   - Contains: Why 0x281 was non-obvious, CMP-SMART comparison
   - Historical value: Shows investigation methodology

### Quick Reference (This File)
- **Cross_Reference_Index.md**
- Who should read: Anyone looking for something specific
- Contains: Navigation guide to all discoveries

---

## By Use Case

### "I'm implementing BMS firmware"
1. Start: `0x281_COMMAND_FRAME_DECODED.md` (primary command)
2. Add: `EXTENDED_ARCHITECTURE_ANALYSIS.md` (watchdog 0x428, mode 0x353)
3. Reference: `COMPREHENSIVE_FINDINGS.md` (state feedback 0x591)
4. Supporting: `EXTENDED_ARCHITECTURE_ANALYSIS.md` (frames 0x026/0x046/0x186/0x342)

### "I'm validating on hardware"
1. Start: `VISUAL_ARCHITECTURE.md` (timing reference)
2. Check: `COMPREHENSIVE_FINDINGS.md` (firmware rules section)
3. Compare: `0x281_COMMAND_FRAME_DECODED.md` (byte0 sequences)
4. Verify: Timing latency (<100ms) per `COMPREHENSIVE_FINDINGS.md`

### "I'm comparing with CMP-SMART"
1. Primary: `EXTENDED_ARCHITECTURE_ANALYSIS.md` (entire Section "Comparison")
2. Details: `CONTACTOR_CONTROL_ANALYSIS.md` ("Comparison with CMP-SMART" section)
3. Validate: `README.md` (Key Findings Summary table)

### "I need to understand why e3008 is different"
1. Start: `EXTENDED_ARCHITECTURE_ANALYSIS.md` (architecture comparison)
2. Details: `ANALYSIS_COMPLETE_SUMMARY.md` (Why Stellantis chose distributed design)
3. Deep dive: `CONTACTOR_CONTROL_ANALYSIS.md` (Design philosophy)

### "I found a bug or unexpected behavior"
1. Check: `COMPREHENSIVE_FINDINGS.md` (firmware rules section - might be intentional)
2. Compare: `0x281_COMMAND_FRAME_DECODED.md` (expected sequence)
3. Timeline: `VISUAL_ARCHITECTURE.md` (correct timing)
4. Review: `EXTENDED_ARCHITECTURE_ANALYSIS.md` (supporting frames)

---

## Discovery Timeline

| Date | Discovery | Document | Status |
|------|-----------|----------|--------|
| Session 1 | 0x334, 0x3F4, 0x583, 0x591 frames decoded | `COMPREHENSIVE_FINDINGS.md` | ✅ Complete |
| Session 2 | 0x281 as command frame identified | `CONTACTOR_CONTROL_ANALYSIS.md` | ✅ Complete |
| Session 2 | 0x281 byte0 full sequence mapped | `0x281_COMMAND_FRAME_DECODED.md` | ✅ Complete |
| Session 3 | CMP-SMART manufacturer corrected (Stellantis) | `CONTACTOR_CONTROL_ANALYSIS.md` | ✅ Complete |
| Session 4 | 0x428 watchdog discovered | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | ✅ Complete |
| Session 4 | 0x353 binary mode discovered | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | ✅ Complete |
| Session 4 | Supporting frames (0x026/0x046/0x186/0x342) identified | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | ✅ Complete |
| Session 4 | 30+ frames with CMP-SMART bytes found | `EXTENDED_ARCHITECTURE_ANALYSIS.md` | ✅ Complete |

---

## Verification Checklist

### Completeness
- ✅ All 0x591 state transitions identified and mapped
- ✅ All 0x281 byte0 progression values extracted
- ✅ 0x428 watchdog pattern fully characterized
- ✅ 0x353 mode values identified
- ✅ Supporting frame correlations quantified (70%+)
- ✅ CMP-SMART byte values cataloged (30+ frames)

### Cross-Dump Validation
- ✅ Analyzed all 12 candump files
- ✅ Patterns consistent across files
- ✅ Timing reproducible
- ✅ Byte sequences identical across captures

### Documentation
- ✅ Implementation guide created
- ✅ Reference specifications complete
- ✅ Timing diagrams provided
- ✅ CMP-SMART comparison documented
- ✅ C code examples provided
- ✅ Firmware rules specified

---

## What to Read Next

**By Time Available:**

| Time | Read |
|------|------|
| 5 min | `DISCOVERY_SUMMARY.md` (quick overview) |
| 10 min | `ANALYSIS_COMPLETE_SUMMARY.md` (comprehensive summary) |
| 20 min | `EXTENDED_ARCHITECTURE_ANALYSIS.md` (new discoveries) |
| 30 min | `0x281_COMMAND_FRAME_DECODED.md` (implementation) |
| 45 min | `COMPREHENSIVE_FINDINGS.md` (all frame specs) |
| 60 min | All of above + `VISUAL_ARCHITECTURE.md` (complete understanding) |

**By Role:**

| Role | Read |
|------|------|
| Executive | `ANALYSIS_COMPLETE_SUMMARY.md` (status/roadmap) |
| Firmware Developer | `0x281_COMMAND_FRAME_DECODED.md` + `EXTENDED_ARCHITECTURE_ANALYSIS.md` |
| Hardware Tester | `COMPREHENSIVE_FINDINGS.md` + `VISUAL_ARCHITECTURE.md` |
| System Architect | `EXTENDED_ARCHITECTURE_ANALYSIS.md` (full architecture) |
| Project Manager | `ANALYSIS_COMPLETE_SUMMARY.md` (complete status) |

---

## PSA 82 UDS and bench worker (November 2026)

| Topic | Where |
|---|---|
| Routine order `10 01`, `10 03`, `D866`/`D802`, `31 01`, `31 03` | `PSA82_PROTOCOL_AND_RESET.md` |
| Clear DTC `14 FF FF FF` and the 17-to-7 DTC list | `PSA82_PROTOCOL_AND_RESET.md` |
| `0x334` 4×14-bit, 96 series cells | `PSA82_PROTOCOL_AND_RESET.md` (supersedes the 3-word formula in `CELL_TEMP_STORAGE_MANUAL.md`) |
| Fiat `0x27A` / `0x342` / `0x2C6` handshake | `PSA82_PROTOCOL_AND_RESET.md` |
| e3008 candump close on `0x281` / `0x591` | `COMPREHENSIVE_FINDINGS.md`, `0x281_COMMAND_FRAME_DECODED.md` |
| Python worker `python -m psa82` | `psa82/` |

## Notes

- All discoveries are **validated against actual vehicle data** (252k+ CAN frames analyzed)
- All findings have **confidence levels** documented (see `ANALYSIS_COMPLETE_SUMMARY.md`)
- All patterns are **reproducible** across all 12 capture files
- All timing is **empirically measured** from vehicle captures, not theoretical

