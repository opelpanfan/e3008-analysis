# e3008 BMS/VCU CAN findings (83% SOC)

## Files analyzed
- `e3008 can dump/e3008 off to on then in D pressed multiple times accelerator car did not moved as parking brake applied but some tention applied to wheels and then tyo off.candump`
- `e3008 can dump/e3008 contactors from off ton on.candump`
- `e3008 can dump/e3008 contactors on 83.candump`
- `e3008 can dump/e3008 from on to off.candump`
- `e3008 can dump/e3008 on to off 2.candump`

---

## Confirmed message meanings

## 0x353 (SOC marker)
- Seen as:
  - `353#0000000000` (startup / transient)
  - `353#0000008300` (stable)
- `0x83 = 131` decimal, interpreted as **83.0% SOC** (known vehicle state).

## 0x583 (cell/temp sensor counts + validity)
Observed payloads:
- `FDFDFF00000000` (invalid/not-ready)
- `00004100401860` (init/intermediate)
- `15094400401860` (stable mode A)
- `17094400401860` (stable mode B)

Inferred count bytes:
- `15 09 ...` => **21 cell groups, 9 temp sensors**
- `17 09 ...` => **23 cell groups, 9 temp sensors**

Notes:
- Startup always goes invalid -> intermediate -> stable.
- Depending on state/capture, stable is either `15 09` or `17 09`.

## 0x334 (cell voltages, multiplexed)
Empirical decode used:
- `mux = byte0 >> 3`
- `V1_mV = ((byte1<<8)|byte2) >> 2`
- `V2_mV = ((byte3<<8)|byte4) >> 4`
- `V3_mV = ((byte5<<8)|byte6) >> 4`

Main drive-request capture stats:
- decoded samples: **8550**
- raw min/max/avg: **912 / 4003 / 3725.28 mV**
- plausible values (3000..4300 mV): **8189 samples**
- plausible min/max/avg: **3300 / 4003 / 3849.3 mV**

Interpretation:
- Most cell values are realistic for 83% SOC.
- ~912 mV values are likely invalid placeholders or alternate packing in some mux frames.

## 0x3F4 (temperatures, multiplexed)
Empirical decode used:
- `slot = byte0 >> 6` (0..3)
- bytes 1..7 = seven sensor raws
- `Temp_C = raw - 40`

Main drive-request capture stats:
- samples: **3822**
- raw min/max: **40 / 69**
- converted min/max/avg: **0 / 29 / 25.04 C**
- channel coverage: **28 channels**

Interpretation:
- Typical pack temps ~25..29 C.
- Rare 0 C values likely startup/invalid edge values.

---

## Contactor state findings

Strongest state frame candidate: **0x591**.

### 0x591 byte-level state map (observed)
`0x591` payload behaves like a compact state machine. Observed states and byte layout:

- `2800000000000000` -> `[28 00 00 00 00 00 00 00]`
- `0800000000000400` -> `[08 00 00 00 00 00 04 00]`
- `0800000000000410` -> `[08 00 00 00 00 00 04 10]`
- `0000000000000410` -> `[00 00 00 00 00 00 04 10]`
- `3800000000000000` -> `[38 00 00 00 00 00 00 00]`
- `2000000000000000` -> `[20 00 00 00 00 00 00 00]`
- `0800000000000008` -> `[08 00 00 00 00 00 00 08]`
- `0800000000001008` -> `[08 00 00 00 00 00 10 08]`
- `0000000000001008` -> `[00 00 00 00 00 00 10 08]`
- `0800000000001408` -> `[08 00 00 00 00 00 14 08]`
- `0000000000001408` -> `[00 00 00 00 00 00 14 08]`
- `0000000000001000` -> `[00 00 00 00 00 00 10 00]`

Practical interpretation by bytes:
- **Byte0** (`0x28/0x08/0x00/0x38/0x20`) = high-level mode/superstate (wake, transition, ready, shutdown path)
- **Byte6** (`0x04/0x10/0x14`) = contactor/precharge phase bits
- **Byte7** (`0x10/0x08/0x00`) = phase confirmation/end-state marker

This byte split is consistent across OFF->ON, ON steady, and ON->OFF logs.

### Exact contactor-closing timeline (decoded)
From `e3008 contactors from off ton on.candump`:

Reference start (`t0`) for the sequence:
- `1781634029.505921` : `281#3100000000`

Main close sequence on `0x591`:
1. `1781634029.514487` : `591#2800000000000000`
2. `1781634029.593816` : `591#0800000000000400`
3. `1781634030.885149` : `591#0800000000000410`
4. `1781634031.835909` : `591#0000000000000410`  (**close/ready reached**)

Timing between stages:
- stage1 -> stage2: ~**79 ms**
- stage2 -> stage3: ~**1.291 s**
- stage3 -> stage4: ~**0.951 s**
- total stage1 -> stage4: ~**2.321 s**

Companion validity/count frame `0x583` around the same close event:
1. `1781634030.597851` : `583#FDFDFF00000000` (invalid)
2. `1781634031.598338` : `583#00004100401860` (intermediate)
3. `1781634032.598764` : `583#17094400401860` (stable)

Interpretation of close sequence:
- `0x591` starts in wake/transition state (`2800...` then `0800...0400`).
- `0x591` moves to `...0410` before/while `0x583` finalizes.
- Final stable close condition is `0x591 == 0000000000000410` with stable `0x583` (`15 09...` or `17 09...`).

Additional close-associated companion IDs (same interval):
- `0x428` and `0x342` shift lower byte from `...01A8...`/`...0004...` with mode nibble changing from `0x40` to `0x60` near close window.
- `0x501` changes from `...FA000000` toward `...FA00004E` during close transition.
- `0x4F1` changes tail from `...53000000` toward `...5307F700` as contactor sequence completes.

Correlated values at key close transitions (`contactors from off ton on`):

At `591#0800000000000410` (`1781634030.885149`):
- `583` nearest: `FDFDFF00000000` (not yet stable, +0.287 s older)
- `342` near: `A200040000000060`
- `428` near: `B301A80000000000`
- `501` near: `0E000000FA00004E`
- `4F1` near: `0EBB93C753000000`

At `591#0000000000000410` (`1781634031.835909`):
- `583` nearest: `00004100401860` (intermediate, +0.238 s older)
- `342` near: `2A00040000000060`
- `428` near: `4A01A80000000000`
- `501` near: `E8000800FA00004E`
- `4F1` near: `98BB93C75307F700`

Then `583` reaches stable after close (`1781634032.598764`):
- `583#17094400401860`

Implication:
- Electrical close transition in `0x591` completes before full final BMS stable count frame appears.
- For robust logic, gate "ready-to-drive" with BOTH `0x591` closed-state AND stable `0x583`.

These are strong **context markers**, but `0x591` remains the most direct contactor-state indicator.

### OFF -> ON (contactor close flow)
Observed sequence in `contactors from off ton on` and `contactors on 83`:
1. `591#2800000000000000` (initial/wake)
2. `591#0800000000000400` (precharge / transition)
3. `591#0000000000000410` (closed/ready transition complete)
4. in ON-83 capture then reaches `591#3800000000000000` (steady ON-ready state)

At same time, 0x583 transitions:
- `FDFDFF...` -> `000041...` -> stable `170944...` or `150944...`

Interpretation:
- Contactors do not close immediately on wake.
- They close after BMS validity/counts become stable and 0x591 advances to `...0410`.

### ON -> OFF (contactor open flow)
Observed sequence in `from on to off` and `on to off 2`:
- `591#0000000000001008`
- `591#0000000000001408`
- `591#0000000000001000`

Detailed ON->OFF phase timing (from `from on to off`):
1. `2800000000000000` (entry)
2. `0800000000001008` (~1.10 s)
3. `0000000000001008` (~3.00 s)
4. `0800000000001408` (~0.98 s)
5. `0000000000001408` (~61.53 s)
6. `0000000000001008` (~53.62 s)
7. `0000000000001000` (final OFF state)

Interpretation:
- These `...100x` / `...1408` patterns are OFF transition states and final OFF-ready state.

---

## Trigger/action flow (inferred)

## Closing trigger flow (OFF -> ON)
1. Vehicle wake/request (ignition/ready request; likely VCU action).
2. BMS starts publishing valid count/status path:
   - `0x583: FDFDFF -> 000041 -> 15/17 09 ...`
3. `0x591` advances through transition bits:
   - `2800...` -> `0800...0400` -> `...0410`
4. ON-ready steady state appears (`3800...` in ON capture).

**Practical software trigger for "contactors closed":**
- `0x591 == 0000000000000410` OR `0x591 == 3800000000000000`
- and `0x583` in stable form (`150944...` or `170944...`).

Recommended hardened close logic:
1. Detect close-candidate when `0x591` enters `...0410` family.
2. Confirm with stable `0x583` (`150944...` or `170944...`) within next 1.5 s window.
3. Promote to READY only if both persist for at least 2 consecutive frames each.

## Opening trigger flow (ON -> OFF)
1. OFF/shutdown request (ignition off / mode change).
2. `0x591` shifts to OFF transition states:
   - `...1008` -> `...1408` -> `...1000`
3. Contactor open complete when stable OFF signature persists.

**Practical software trigger for "contactors open":**
- `0x591` in persistent `...1000` / `...1008` family.

Recommended hardened open logic:
1. Detect open-request path at `0x591 ...1008` or `...1408`.
2. Confirm OPEN only at persistent `0x591 == 0000000000001000`.
3. Apply debounce of >=2 consecutive `...1000` frames to avoid transient state flips.

---

## Additional high-value observations

### `0x591` dwell durations are very repeatable
- OFF->ON captures repeatedly show:
   - short wake (`28..`) -> short precharge (`08..0400`) -> intermediate (`08..0410`) -> stable close (`00..0410`)
- ON->OFF captures repeatedly show:
   - `..1008` and `..1408` long dwell windows before final `..1000`

This repeatability is strong evidence that `0x591` is the correct contactor state source.

### `0x583` behavior by operating state
- OFF->ON: transitions invalid -> intermediate -> stable
- ON steady / ON->OFF: often remains stable (`170944...` in one file; mixed `170944...`/`150944...` in another)

Interpretation:
- `0x583` is better as a **BMS validity/count gate** than as direct contactor command/state.

### Drive request session confirms full close->open cycle
In `off->on then D pedal then off` capture, `0x591` includes:
- close path to `380000...` (ON steady)
- later shutdown path via `...1008`/`...1408`
- final `...1000` at end

So this single long file contains complete power-state transition evidence plus pedal torque activity.

---

## Pedal in D with parking brake applied (current/torque evidence)

Best dynamic candidate: **0x154**
- Pattern: `FFFC FFFC xxxx 0000`
- Third word (`xxxx`) varies with pedal demand.

Measured in main drive-request capture:
- third word min/max/mean: **0 / 652 / 50.44**
- strong demand bursts between approx:
  - **1781634852.468 -> 1781634908.702**
- peak sample:
  - `154#FFFCFFFC028C0000` (0x028C = **652**) at `1781634866.523973`

Interpretation:
- This matches repeated accelerator presses while car was held by parking brake.
- Car does not move, but torque/current request activity is clearly present.

Secondary dynamic IDs (likely drivetrain-related, not fully decoded yet):
- `0x214`
- `0x2C6`

---

## Implementation-ready rules (for firmware logger)

1. **Battery ready** when:
   - `0x583` payload is `15094400401860` or `17094400401860`.
2. **Contactor closed** when:
   - `0x591` is `0000000000000410` or `3800000000000000` (with rule 1 true).
3. **Contactor opening/open** when:
   - `0x591` transitions to `0000000000001008` / `0000000000001408` / `0000000000001000`.
4. **Pedal-torque activity** metric:
   - `0x154.word3` (bytes 4..5 as big-endian unsigned).
   - flag high demand if `word3 >= 200`.

---

## Confidence
- High: IDs `0x334`, `0x3F4`, `0x583`, `0x353`, and `0x591` state sequencing.
- Medium: exact semantic naming of each `0x591` bit and exact physical scaling of `0x154.word3`.
