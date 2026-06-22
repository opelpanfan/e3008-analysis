# e3008 Battery Cell and Temperature Storage Manual

Date: June 22, 2026  
Scope: Reverse-analysis manual for how battery cell voltages and temperature probes are stored and transported on CAN

---

## Purpose

This document is the battery-telemetry companion to the contactor-control analysis.  
It focuses on four linked frames:

- `0x583` (battery telemetry manifest / readiness)
- `0x334` (multiplexed cell voltage transport)
- `0x3F4` (multiplexed temperature transport)
- `0x353` (SOC context)

The goal is to describe:

1. Byte-level structure
2. Multiplexing rules
3. Observed channel counts vs declared counts
4. Practical decoder logic with confidence grading

---

## Data Basis

- Capture folder: `e3008 can dump/`
- Files analyzed: 12 candump files
- Parsed frame basis: 933,460 total lines
- Primary evidence file for high-volume telemetry:  
  `e3008 off to on then in D pressed multiple times accelerator car did not moved as parking brake applied but some tention applied to wheels and then tyo off.candump`

Global counts across all files:

- `0x334`: 10,973 frames, 984 unique payloads
- `0x3F4`: 2,302 frames, 16 unique payloads
- `0x583`: 664 frames, 4 unique payloads
- `0x353`: 6,795 frames, 2 unique payloads

---

## Executive Findings

1. `0x583` is a 7-byte manifest-like frame whose stable payload contains `0x18` and `0x60` tail bytes, matching **24 temp probes** and **96 cells** respectively.
2. `0x334` is multiplexed by `byte0 >> 3`; observed mux range is `0..26`; each frame carries three packed voltage words.
3. `0x3F4` is multiplexed by `byte0 >> 6`; observed slot range is `0..3`; each frame carries seven raw temperature bytes.
4. `0x353` byte3 holds SOC (`0x83` in the 83% captures), providing context for plausibility checks.
5. Observed decoded channels are fewer than declared `96/24` in some files, indicating either selective publication windows, grouping, or alternate mapping in additional buses/states.

---

## 1) `0x583` Battery Manifest / Readiness Frame

### Wire Characteristics

- CAN ID: `0x583`
- DLC: **7** bytes in all observed files
- Typical rate: ~0.45 to ~1.0 Hz (scenario-dependent)

### Observed Payload States

| State class | Payload | Interpreted role |
|---|---|---|
| Invalid/startup | `FDFDFF00000000` | telemetry invalid/not ready |
| Init transition | `00004100401860` | startup handshake / preparing telemetry |
| Stable A | `15094400401860` | ready profile A |
| Stable B | `17094400401860` | ready profile B |

Aggregate occurrence counts:

- `17094400401860`: 379
- `15094400401860`: 271
- `FDFDFF00000000`: 7
- `00004100401860`: 7

### Byte Interpretation (Current Best Model)

For stable payload `17 09 44 00 40 18 60` (hex bytes):

- byte5 = `0x18` = **24** (temperature probe count)
- byte6 = `0x60` = **96** (cell count)

This matches your mapping request (`96/24`) and is more physically plausible as a pack-level manifest than interpreting bytes0/1 as total counts.

### About bytes0/1 (`0x15/0x17`, `0x09`)

Previous documentation interpreted bytes0/1 as direct counts (`21/9`, `23/9`).  
Current evidence suggests bytes0/1 are more likely **state/profile fields** (or subgroup counts), while bytes5/6 carry the pack-level manifest (`24/96`).

Confidence:

- bytes5/6 as 24/96 manifest: **High**
- bytes0/1 exact semantics: **Medium-Low** (not fully resolved)

---

## 2) `0x334` Multiplexed Cell Voltage Storage

### Wire Characteristics

- CAN ID: `0x334`
- DLC: 8 bytes
- Rate range in captures: ~4.2 to ~20.4 Hz
- Global byte0 values: `0x00, 0x08, 0x10, ..., 0xD0` (step size 8)

### Multiplexing Key

- `mux = byte0 >> 3`
- Observed mux values: `0..26`
- Main active set: `1..26` (mux `0` appears in some files, likely special/placeholder group)

### Packing Formula (Observed Decoder)

```
w1 = (byte1 << 8) | byte2
w2 = (byte3 << 8) | byte4
w3 = (byte5 << 8) | byte6

V1_mV = w1 >> 2
V2_mV = w2 >> 4
V3_mV = w3 >> 4
```

Channel indexing model:

```
base = (mux - 1) * 3
cell[base + 0] = V1_mV
cell[base + 1] = V2_mV
cell[base + 2] = V3_mV
```

### Example from Raw Capture

Frame: `334#083390CE43390CE4`

- mux = `0x08 >> 3 = 1`
- `w1=0x3390` -> `V1=3300 mV`
- `w2=0xCE43` -> `V2=3300 mV`
- `w3=0x390C` -> `V3=912 mV` (implausible)

This demonstrates why range filtering is required.

### Statistical Envelope (All Files)

- decoded values (raw): min 912 mV, max 4004 mV, mean 3736.97 mV
- plausible subset (3000..4300 mV): 30,937 samples
- plausible min/max/mean: 3300 / 4004 / 3854.67 mV

### Channel Coverage vs Declared Cell Count

- Observed indexed channels: 78 (`mux 1..26` x 3)
- Declared pack count from `0x583`: 96

This mismatch is a central open item. Most likely explanations:

1. `0x334` exposes a **subset/window** of full cells in these operating states.
2. Some cell values are encoded in a secondary frame or alternate pack mode.
3. One or more words in `0x334` are not always single-cell values (mixed packing/profile-dependent semantics).

Confidence:

- mux key and packed-word extraction: **High**
- exact 96-cell one-to-one reconstruction from only `0x334`: **Not yet complete**

---

## 3) `0x3F4` Multiplexed Temperature Storage

### Wire Characteristics

- CAN ID: `0x3F4`
- DLC: 8 bytes
- Rate range in captures: ~1.1 to ~5.9 Hz
- Observed byte0 set: `0x00,0x20,0x40,0x60,0x80,0xA0,0xC0,0xE0`

### Multiplexing Key

- `slot = byte0 >> 6` -> observed `0..3`

Primary recurring slot markers are often `0x20,0x60,0xA0,0xE0`; additional `0x00/0x40/0x80/0xC0` variants appear in several captures, indicating a secondary mode/flag within byte0 lower bits.

### Value Decode

```
base = slot * 7
raw_i = byte[i+1]   // i=0..6
tempC = raw_i - 40
```

So each frame provides 7 probes for one slot.

### Statistical Envelope (All Files)

- decoded temperature range: 0..29 C
- mean: 25.06 C
- observed indexed channels: 28 (`4 slots x 7`)

### Channel Coverage vs Declared Probe Count

- Observed channels through this mapping: 28
- Declared probes from `0x583`: 24

Interpretation options:

1. 28 transport channels include non-physical/derived/reserved entries.
2. 24 are physical probes; 4 channels are duplicated, virtual, or conditional.
3. Byte0 secondary mode bit toggles map meaning of some channels.

Confidence:

- slot mux and `raw-40` transform: **High**
- strict physical probe identity map (`T1..T24`): **Medium-Low**

---

## 4) `0x353` SOC Context Channel

### Wire Characteristics

- CAN ID: `0x353`
- DLC: 5 bytes
- Byte3 holds SOC in observed captures

Observed values:

- `0x83` (dominant, 6,735 frames) -> 83% context
- `0x00` (startup transient, 60 frames)

SOC is useful to sanity-check voltage and temperature plausibility windows when comparing sessions.

---

## 5) Startup and Steady-State Temporal Behavior

Typical startup progression (primary long capture):

1. `0x353`: transient `00` values appear first.
2. `0x3F4`: repeated baseline payloads (`...4141...`) appear during early init.
3. `0x583`: `FDFD...` -> `00004100401860` -> stable `150944...`/`170944...`.
4. `0x334` and `0x3F4` continue in periodic multiplex cadence during ON and OFF transitions.

`0x583` is therefore a good **telemetry readiness gate** before trusting decoded channels.

---

## 6) Recommended Decoder Rules (Implementation Grade)

### Readiness Gate

Treat telemetry as fully valid only after `0x583` reaches stable class:

- `15094400401860` or `17094400401860`

### Cell Voltage Path (`0x334`)

1. Compute `mux = byte0 >> 3`.
2. Skip `mux == 0` unless specifically investigating special pages.
3. Decode `V1/V2/V3` with shifts (`>>2`, `>>4`, `>>4`).
4. Accept plausibility window (for this dataset) `3000..4300 mV`.
5. Track per-mux fill state; do not assume all 96 cells are present from one sweep.

### Temperature Path (`0x3F4`)

1. Compute `slot = byte0 >> 6`.
2. Decode 7 values: `tempC = raw - 40`.
3. Keep expected window `-30..80 C` (dataset shows 0..29 C).
4. Maintain slot freshness timestamps; mixed slot rates are normal.

### SOC Path (`0x353`)

1. Read byte3 as SOC percent in this dataset.
2. Treat `0x00` as startup transient unless persistent.

---

## 7) Confidence Matrix

| Topic | Confidence | Notes |
|---|---|---|
| `0x583` stable payload classes | High | repeated in all scenario types |
| `0x583` bytes5/6 = 24/96 | High | exact hex-to-decimal match and persistent tail bytes |
| `0x334` mux and bit-shift decode | High | stable extraction and realistic mV distributions |
| `0x3F4` slot and `raw-40` decode | High | stable channels and physically plausible temperatures |
| Exact physical map for all 96 cells | Medium-Low | only 78 channels directly reconstructed from current formula |
| Exact physical map for all 24 probes | Medium-Low | 28 decoded channels observed; likely includes virtual/reserved slots |

---

## 8) Open Questions and Next Validation Campaign

1. Identify whether additional cell pages exist on another CAN ID (or another bus segment).
2. Determine whether `mux=0` in `0x334` is sentinel, metadata, or alternate data page.
3. Resolve `0x3F4` byte0 bit5 role (`0x20` family vs `0x00` family).
4. Correlate thermal transients under load/charging to map physical probe positions.
5. Capture at different SOC bands (20%, 50%, 95%) to test scaling invariance.

---

## 9) Practical Conclusion

For implementation today:

- Use `0x583` as manifest + readiness gate (`24/96` from bytes5/6).
- Decode `0x334` and `0x3F4` exactly as above, with plausibility filtering.
- Treat full one-to-one physical indexing as an active research item rather than solved.

This yields a robust telemetry pipeline now, while preserving room for final channel-map refinement in future captures.
