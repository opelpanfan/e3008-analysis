# e3008 CAN analysis report (SOC 83%)

## Scope
- Main session: `e3008 off to on then in D pressed multiple times accelerator car did not moved as parking brake applied but some tention applied to wheels and then tyo off.candump`
- Reference sessions for contactors: 
  - `e3008 contactors from off ton on.candump`
  - `e3008 contactors on 83.candump`
  - `e3008 from on to off.candump`
  - `e3008 on to off 2.candump`

## Parsing summary
- Parsed frames in main file: **252,607**
- Timestamp span after sorting: **1781634813.010335 → 1781639103.595778** (about 4290.6 s)
- Note: file contains out-of-order timestamp blocks near beginning/end.

## Battery counts frame (0x583)
Observed payload families in main file:
- `FDFDFF00000000` (1x)
- `00004100401860` (1x)
- `15094400401860` (162x)
- `17094400401860` (4x)

Interpretation (probable): first two bytes are counts.
- `0x15 0x09` => **21 cell groups / 9 temp sensors**
- `0x17 0x09` => **23 cell groups / 9 temp sensors**

Transition pattern during startup/contactors is consistent across capture files:
- invalid -> init -> stable counts.

## Cell voltages frame (0x334)
Using empirical decode from logs:
- mux = `byte0 >> 3`
- `V1_mV = ((byte1<<8)|byte2) >> 2`
- `V2_mV = ((byte3<<8)|byte4) >> 4`
- `V3_mV = ((byte5<<8)|byte6) >> 4`

Computed from main file:
- decoded samples: **8,550**
- raw min/max/avg: **912 / 4003 / 3725.28 mV**
- plausible-range samples (3000..4300 mV): **8,189**
- plausible min/max/avg: **3300 / 4003 / 3849.3 mV**

Remarks:
- The ~912 mV values are likely invalid/placeholder decode artifacts for some mux positions.
- Most decoded values are in normal EV range around 3.8–4.0 V at 83% SOC.

## Cell temperatures frame (0x3F4)
Using empirical decode from logs:
- slot = `byte0 >> 6` (0..3)
- seven temps per frame from bytes 1..7
- probable conversion: `Temp_C = raw - 40`

Computed from main file:
- temp samples: **3,822**
- raw min/max: **40 / 69**
- converted min/max/avg: **0 / 29 / 25.04 °C**
- index coverage: **28 channels** (4 slots × 7)

Remarks:
- Most channels cluster around 25–29°C.
- Rare 0°C equivalent comes from raw=40 and may be invalid edge/startup value.

## SOC frame evidence
Frame 0x353 in main file toggles then stabilizes:
- `0000000000` seen 23 times early startup
- `0000008300` seen 1755 times (SOC byte = 0x83 => 83)

## Contactor/open-close candidate state frames
Most consistent contactor-state candidate: **0x591** (state-like bitfield)

### OFF -> ON transition (contactors from off ton on)
Sequence observed:
1) `2800000000000000`
2) `0800000000000400`
3) `0000000000000410` (stable)

### ON steady (contactors on 83)
Sequence evolves to:
- `3800000000000000` appears repeatedly after `...0410` stage.

### ON -> OFF transition (from on to off)
Observed states include:
- `0000000000001008`
- `0000000000001408`
- `0000000000001000`

Interpretation:
- 0x591 likely encodes BMS/contactor state bits and is suitable for contactor-state detection.
- 0x583 and 0x591 together provide robust state confidence.

## Candidate traction/current-draw frames during pedal-with-brake
Strong candidate: **0x154**
- payload shape often: `FFFC FFFC xxxx 0000` (as 16-bit words)
- first two signed words are constant -4
- third word is dynamic and likely torque/current related

Main file statistics for 0x154 third word:
- min/max/mean: **0 / 652 / 50.44**
- common values: 20, 12, 0, 16, 24, 28
- high events >200 occur in burst clusters between approximately:
  - **1781634852.468 → 1781634908.702**
- absolute peak:
  - ts **1781634866.523973**, value **652**, payload `FFFCFFFC028C0000`

Interpretation:
- This burst window matches expected repeated pedal requests in D while parking brake prevents movement.
- Scaling is not yet confirmed; if scale is 0.1, peak is ~65.2 units.

Secondary candidates for driveline activity:
- 0x214 (very high variability, 1654 unique payloads)
- 0x2C6 (very high variability, 5264 unique payloads)

These likely carry dynamic driveline/control values but need byte-level reverse mapping.

## Practical decoder recommendations
1. Use 0x591 as primary contactor-state machine input.
2. Use 0x583 as validity/count frame and startup-state marker.
3. Decode 0x334 and 0x3F4 with above formulas and apply plausibility filters.
4. Use 0x154 word3 as primary provisional current/torque demand signal for pedal events.
5. Add state-dependent filtering (OFF/ON/TRANSITION) to reduce false min/max artifacts.
