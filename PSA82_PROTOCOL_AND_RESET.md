# PSA 82 kWh protocol and reset investigation

Date: 23 November 2026  
Packs: Peugeot e-3008 and Fiat 600e, Stellantis 82 kWh  
Bus: classic CAN, 500 kbit/s, 11-bit identifiers

This report reassembles the diagnostic sessions in the attached SavvyCAN logs, the battery-only captures already in `e3008 can dump/`, and the twelve vehicle candumps in that folder. Two further conclusions are taken from Benas's local parse and from the cp2b session of 23 November 2026, 20:14–20:20 Europe/Vilnius. Those two sources are named wherever a frame in this repository does not show them.

The bench worker in `psa82/` follows the sequences below. It listens unless `--enable-tx` is set, and it does not implement `WriteDataByIdentifier`.

## 1. What was actually in each capture

| Capture | Where | UDS on `0x6B4`/`0x694` | What it shows |
|---|---|---|---|
| `e3008 contactor clear.csv`, `CONTACTOR RESET.csv` | attachment | yes | `31 01 DD 35`, result `02` |
| `e3008 crash clear.csv`, `COLLISION RESET.csv` | attachment | yes | `31 01 DF 60`. Vehicle log polls `31 03` while status is `01` |
| `e3008 braker clear.csv` | attachment and repo | yes | `31 01 DD 0B` twice. Positive start has no status byte. This file has no `31 03` |
| `e3008 isolation clear.csv` | attachment and repo | yes | `31 01 DF 46`, result `02` |
| `e3008 undervoltage clear.csv` | attachment and repo | yes | `31 01 DF FC`, result `02` |
| `e3008 code clear.csv` | attachment and repo | yes | `19 02 26`, then `14 FF FF FF`, then `19 02 26` again |
| `e3008 diagnostics.csv`, `e3008 diagnostics 2 left.csv` | attachment and repo | yes | DTC reads only. The second file matches the post-clear set plus `U1601-87` |
| `e3008 idemtify.csv` | repo only | yes | Identification DIDs. No routines, no clear |
| `Add more PIDS test.csv` | attachment | yes | One extended DID sweep. `D812 = 00`. No `D810`, no `D86D` |
| `3008e 2025.csv`, `e3008.csv`, `e3008 idle.csv` | repo / attachment | no | Broadcast only. One `0x134` frame in `3008e 2025.csv` |
| `fiat 600e.csv`, `fiat 600e idle to on.csv` | attachment | no | Vehicle broadcast, including the contactor handshake |
| `fiat 600e DTC read.csv` | not attached (45 MB) | read-only, per local parse | About 150 DIDs. No clear, no routine |
| `fiat 600e charge 3kw.csv` | not attached | per local parse | BMS ignores `10 03` and `19 02` while charging with HV closed |
| `e3008 can dump/*.candump` | repo | no UDS | Vehicle contactor closes on `0x281` / `0x591` |

No capture in this set contains `SecurityAccess` (`0x27`), `WriteDataByIdentifier` (`0x2E`), or a programming session (`10 02`).

## 2. Transport

Tester request ID `0x6B4`, ECU response ID `0x694`. ISO-TP normal addressing. Every diagnostic frame is eight bytes, unused bytes `0x00`. The SavvyCAN `LEN` column is the significant byte count, not the CAN DLC.

Single-frame examples from the contactor log:

```text
6B4  02 10 03 00 00 00 00 00
694  06 50 03 00 C8 00 14 00
6B4  04 31 01 DD 35 00 00 00
694  05 71 01 DD 35 01 00 00
6B4  04 31 03 DD 35 00 00 00
694  05 71 03 DD 35 02 00 00
```

Flow control, sent by the tester after a first frame, is `30 00 00 00 00 00 00 00`.

`50 01` and `50 03` both return `00 C8 00 14`:

- P2 server max = `0x00C8` = 200 ms
- P2* server max = `0x0014` × 10 ms = 200 ms

Positive single-frame answers arrive in 2–16 ms, usually 6–10 ms. `TesterPresent` is `3E 00` (a response is required; `3E 80` does not appear). Spacing is about 1.0 s, with gaps up to about 2 s, and one 8.6 s gap in the contactor file before the tool entered the session again.

cp2b on 23 November answered `0x6B4 -> 0x694` at 500 kbit/s, 152 of 152 Autel DIDs.

## 3. Reset routine order

Across the attached routine files, and across the 14 successful runs in the local parse (`DD35`, `DF60`, `DF46`, `DFFC`, `DD0B` on two packs), the tool order is:

1. `10 01` default session. Response `50 01 00 C8 00 14`.
2. `10 03` extended session. Response `50 03 00 C8 00 14`.
3. Alternate `22 D8 66` and `22 D8 02` for about 6 s. In the attached contactor log that is 76 reads, median gap 74 ms (range 50–266 ms). The local parse of the wider set measured about 65 ms. Both answers stayed `62 D8 66 00` and `62 D8 02 00 00 00 00`.
4. `10 03` again, immediately before the routine.
5. `31 01 <RID>` with an empty option record.
6. `31 03 <RID>` until the status byte is `02`.
7. `10 01` to leave the extended session. The breaker file ends still in extended session; the other attached routine files do return to `10 01`.

There is no seed, no key, and no DID write in front of any of these.

The worker uses that order. The 6 s `D866`/`D802` loop is the observed prelude, not a proven interlock: every successful log showed zeros, and there is no capture of a non-zero value blocking a routine. The worker prints the values and continues. If `10 03` times out, it stops. That is the failure seen when a Fiat pack ignored `10 03` and `19 02` during a 3 kW charge with HV closed. It does not keep requesting.

### Routine results

| Routine | RID | Start response | Results | Timing in the attached logs |
|---|---|---|---|---|
| Contactor / switcher reinit | `DD35` | `71 01 DD 35 01` | `71 03 DD 35 02` on the first poll | Poll ~66 ms after the start response. Same on the bench file and on `CONTACTOR RESET.csv` |
| Crash / collision | `DF60` | `71 01 DF 60 01` | `02` means finished, `01` means still running | Bench file was already `02` at ~66 ms. `COLLISION RESET.csv` stayed `01` for nine polls (~0.8 s) and then returned `02` |
| Isolation | `DF46` | `71 01 DF 46 01` | `71 03 DF 46 02` | ~238 ms from start request to the results request |
| Undervoltage | `DFFC` | `71 01 DF FC 01` | `71 03 DF FC 02` | ~109 ms |
| Breaker | `DD0B` | `71 01 DD 0B` (no status byte) | not present in the attached file | Two starts, about 5.7 s apart. The 14-run set does poll `31 03` until `02`, so the worker polls and stops if the ECU rejects results |

`01` and `02` are the only routine status bytes in the logs.

### What these routines did not show

The attached routine files do not read `D812`, do not read DTCs, and do not change a contactor feedback frame inside a two-second window around the request. Cell millivolts move by about 1 mV. `D866` and `D802` stay zero before and after. So the logs prove that the ECU accepts each routine in extended session. They do not, by themselves, prove which latch or DTC each routine clears.

`D812` in `Add more PIDS test.csv` is `00`. An earlier bench had seen `01`. This corpus does not contain the transition.

`P0AA1-73` and `P1B7A-29` from that earlier bench are not in these DTC lists. The contactor-related code that is present, and that ClearDTC removed, is `P1B45-31`.

## 4. ClearDiagnosticInformation

`e3008 code clear.csv` is the only attached clear. It does not enter `10 03` inside the file. `19 02` and `14 FF FF FF` are answered anyway. The worker therefore does not open an extended session for a clear.

Request and response:

```text
6B4  04 14 FF FF FF 00 00 00
694  03 7F 14 78          at 208 ms, then every ~210 ms, five times
694  01 54                1072 ms after the request
```

The five `NRC 0x78` responses match P2* (200 ms). The positive response is `54` with no extra bytes.

DTC read is `19 02 26`. The mask `0x26` is `testFailedThisOperationCycle | pendingDTC | testFailedSinceLastClear`. The ECU reports availability `FF`.

Status byte reminder: bit 0 test failed, bit 1 failed this cycle, bit 2 pending, bit 3 confirmed, bit 4 not completed since clear, bit 5 failed since clear, bit 6 not completed this cycle, bit 7 warning indicator.

Seventeen DTCs before the clear, seven immediately after:

| DTC | Status before | After the clear |
|---|---|---|
| U2000-06 | 2F | still present |
| U1601-87 | 2F | gone in the immediate read, present again in `diagnostics 2 left` |
| U0401-81 | 6D | cleared |
| P1AF1-12 | 2F | cleared |
| U110E-87 | 2F | still present |
| U114A-87 | 2F | still present |
| P1586-16 | 6D | cleared |
| P1A13-96 | 2E | cleared |
| P10F7-13 | 2F | still present |
| P10F9-13 | 2F | still present |
| P0ADC-01 | 64 | still present, same status |
| U115E-87 | 2F | still present |
| U114E-87 | 6D | cleared |
| P0562-16 | 6D | cleared |
| P1AEA-16 | 6D | cleared |
| U1F00-00 | 6D | cleared |
| P1B45-31 | 6D | cleared |

The codes that stayed are mostly network timeouts (`U110E`, `U114A`, `U115E`, `U2000`, `U1601`) plus `P10F7-13`, `P10F9-13`, and `P0ADC-01`. On a pack that is not in a car, those U-codes are the ones that can be raised again before the follow-up read. `U1601-87` is the example: absent in the read 1.25 s after `54`, present in the later diagnostics file. `P0ADC-01` at status `64` (pending, failed since clear, test not completed this cycle) was not removed at all.

`14 FF FF FF` is the only clear request in the logs. The worker sends that group and no other.

Benas's note that a Fiat DTC clear cleared a contactor fault is not visible in the attached Fiat files. Those two files have no UDS. The 45 MB `fiat 600e DTC read.csv` was a read, not a clear.

## 5. DIDs

Positive reads, with the interpretation that is actually supported.

| DID | Length | Value in these logs | Reading |
|---|---|---|---|
| `D866` | 1 | `00` | Polled before every routine. Never changed |
| `D802` | 4 | `00 00 00 00` | Same |
| `D800` | 2 | `00 00` | Code-clear file |
| `D812` | 1 | `00` | Latch byte. Not `01` in this corpus |
| `D813` | 1 | `00` in code clear, `02` in the PID sweep | Status byte, not constant |
| `D814` | 1 | `00` | |
| `D45A` | 1 | `03` | Operator: `03` on healthy packs, `04` on the latched pack. `04` is not in these files |
| `D86D` | 1 | not in the attached files | Operator: went `00` to `01` on a Fiat pack when balancing became active |
| `D810` |  | not in the attached files | Earlier bench used uint16 / 512 as SoC percent. Not reconfirmed here |
| `D46F` | 20 | all zeros | 160 bits. It is not a 12-byte / 96-bit balance mask. `D470` is the same shape |
| `D440` | 240 | 120 × uint16, 108 non-zero | Cell millivolts, about 3601–3617 mV, then 12 zero words |
| `D4B5` | 216 | 108 × `0x0675` | Uniform. Not live cell voltage |
| `D901` | 14 | ASCII `3481280006744` | Pack serial in the PID sweep |
| `F18C` | 15 | ASCII `6086EA41631043` | Serial in `e3008 idemtify.csv` |
| `F18B` | 3 | `19 07 22` in the PID sweep, `03 06 24` in identify.csv | BCD `YY MM DD` when the bytes are BCD. Two captures, two values |
| `F0FE` | 24 | `ffff0000010203062401407401ffffff0002000001980995` | Identification block. Same in crash, diagnostics, and identify |
| `F080` | 22 | `9858423280002e9858423280ffffffffff01ffffffff` | identify.csv only |
| `F196` | 16 | sixteen `3F` | identify.csv. ASCII `?`, unread calibration area |
| `D879` |  | not in the attached files | cp2b coolant read 20.0 °C |

`D465` started a first frame of length `0x1AA` (426 bytes) and the tester sent another request without flow control, so that body is incomplete. `D492`, `D89E`, `F193`, and `F195` were pipelined the same way. The log does not prove them unsupported.

### Scales that must not be applied

On cp2b, Autel-style scaling of temperature DIDs was wrong at room temperature:

- `D817`, `D87D`, `D877` displayed about 0.9 °C, 0.2 °C, and 0.6 °C
- coolant `D879` displayed 20.0 °C
- `0x3F4` with `raw - 40` on the bench logs is 12 °C and 25 °C, which is the plausible one

`D815` displayed 175.7 V, half of the `D438` cell-sum display of 351.2 V. In the PID sweep the raw values are almost the same word (`D815 = 0x1864`, `D438 = 0x1863`), so a single scale cannot make one of them half the other. The worker prints both as raw.

`D816` read 0.00 A on cp2b. Broadcast values someone treated as current on `0x3B4` and `0x214` did not. The worker does not convert either ID to amps. See section 6.

`D810`, if a future read returns two bytes, is printed as raw and as `uint16 / 512` percent, labelled as the earlier bench candidate.

### Blocked write

`2E D9 00 01` is not implemented. A factory-mode write of `D900` collapsed insulation readings on a pack. The worker rejects every `0x2E`, in every context, before a frame is built. `22 D9 00` remains a normal read; the PID sweep got `62 D9 00 00`.

## 6. Broadcast telemetry

### Cells, `0x334`

Eight bytes, four 14-bit big-endian millivolt values, mux in `byte0 >> 3`:

```text
c0 = (b1 << 6) | (b2 >> 2)
c1 = ((b2 & 0x03) << 12) | (b3 << 4) | (b4 >> 4)
c2 = ((b4 & 0x0F) << 10) | (b5 << 2) | (b6 >> 6)
c3 = ((b6 & 0x3F) << 8) | b7
cell index = mux * 4 + {0,1,2,3}
```

Groups 0–23 are the 96 series cells. Replaying the contactor-clear log fills all 96, from 3554 mV to 3571 mV. Groups 24–26 are extra slots: 3000 mV (`0x0BB8`) on the battery bench, 3300 mV in the e3008 vehicle candumps, and `0x3FFE` on the Fiat logs. The close candump simply never emits mux 0, 5, 10, 15, or 20, so that file decodes 76 live series cells, all of them 3989–4004 mV.

The June 2026 3-word formula (`>> 2`, `>> 4`, `>> 4`) matches cell 0 only. Its third value on `08 37 BC DF 03 7B CD EF` is 1980 mV. The 14-bit decode of that same frame is 3567, 3568, 3567, 3567 mV. That is the correction to `CELL_TEMP_STORAGE_MANUAL.md`.

`0x583` on the battery-only bus still declares the pack. Stable payloads such as `03 0E 34 00 54 18 60 00` have byte 5 = 24 temperature probes and byte 6 = 96 cells. `FD FD FF` is the not-ready marker, seen once in `3008e 2025.csv`. The Fiat vehicle `0x583` is a different payload (`1A 00 39 00 00 22 66 00`). The worker prints byte 5 and byte 6 rather than calling the Fiat frame a 102-cell manifest.

On the car, a second cell map uses one ID per four uint16 millivolts: `0x6D3`, `0x6D4`, `0x6E1`, `0x6E2`, `0x6E7`–`0x6E9`, `0x6EB`, `0x6ED`–`0x6EF`, `0x6F0`–`0x6FF`. That is 27 IDs × 4 = 108 channels, the same live count as `D440`. Those IDs are absent on the battery-only bench. Several neighbouring IDs (`0x6D1`, `0x6D2`, `0x6E0`, `0x6E3`–`0x6E6`) are raw bytes around `0x3F`–`0x42` (about 23–26 °C with the `raw - 40` rule), not cell frames. They are not ISO-TP, even though a PCI classifier will mistake `0x0E` and `0x3x` for a single frame or flow control.

### Temperatures, `0x3F4`

`page = byte0 >> 5` (0..7), seven temperatures, degrees C = raw − 40. `0xFE` is empty. The bench pages that are populated read 12 °C and 25 °C. Fiat leaves the upper pages at `0xFE`.

### Voltages, `0x2B4`

Three uint16 big-endian values, 0.01 V per bit.

- Fiat idle-to-on, one sample: 347.06 V, 331.28 V, 358.32 V. 347.06 V matches 96 cells near 3.616 V.
- Battery bench, contactors not live: `9C 40 9C 40 9C 40 00 00` = 400.00 V three times. That value is the sentinel.

`0x4D4` repeats the 400.00 V sentinel in bytes 1–2 on the bench.

### Not pack voltage, not current

`0x5C6` is absent on every battery-only log. On the Fiat logs it is a 1 Hz frame whose first two bytes sit near `0x3C` (60). That is not a 345 V pack voltage.

`0x353` byte 3 is `0x00` or occasionally `0x38` / `0x83` on the bench, while cell voltage stays near 3.57 V in both the `0x38` file and the `0x83` file. It is not a trustworthy SoC. The Fiat `0x353` is a different multi-byte frame. The SoC DID `D810` was not read here.

`0x3B4` is 10 Hz. Byte 0 counts down by `0x0F`. The bench tail is `3F 90 00 00 56 A3 0F`. The Fiat tail is `00 00 00 00 59 F2 17`. Treating that tail as current disagrees with `D816 = 0.00 A` on cp2b, and the bench-versus-Fiat difference is not a calibrated amp reading either. The worker stores the tail and does not scale it.

`0x214` on the bench is 100 Hz and the payload is a rolling byte 0 followed by seven zeros. It is an alive counter, not a current.

`0x254` is static in both Fiat files (`29 B4 2A C8 27 E8 00 00`) and static on the bench (`00 00 00 00 00 00 4C 7C`).

### Contactor handshake, two different captures

**e3008 candumps in this repo** (`e3008 contactors from off ton on.candump` and the other eleven). The close is still the one already documented:

- `0x281` byte 0 changes (`31` at the close instant, then a rolling hold)
- `0x591` walks `28 00..` → `08 00..04 00` → `08 00..04 10` → `00 00..04 10` in about 2.3 s
- `0x27A` in that same close only steps `18 0E` → `08 0E`
- `0x342` byte 2 becomes `04`, not `41`

The ESP32 `state591Name()` in `src/main.cpp` compares those signatures at the wrong byte offsets (it looks for `0x10` at byte 4). The candump bytes use byte 6 and byte 7. The Python decoder uses the candump layout.

**Fiat 600e, attached logs.** `0x591` stays `38 00 00 00 00 00 00 00` through both the close and the later open, so it does not track this handshake. `0x281` keeps rolling (`xx 51 ..` or `xx 62 0E ..`) and is not the edge.

`fiat 600e idle to on.csv`, time from the start of the file:

| t (s) | Frame |
|---|---|
| 0.046 | `0x27A = 4E 10 00 00` |
| 10.122 | `0x342` byte 2 steps `01` → `41` |
| 10.148 | `0x27A = 8E 10 00 00` |
| 10.198 | `0x27A = 8E 14 00 00 ..20` |
| 10.248 | `0x27A = 8E 34 00 00 ..20` |
| 10.40–10.8 | `0x2C6` link word climbs, see below |
| 11.648 | `0x27A = 8E 38` then `4E 58` then `4F 58` |

`fiat 600e.csv` open, about 135 s into the file: `0x342` byte 2 steps `41` → `81` and then `81` → `01`, and `0x27A` returns to `4E 10`. That matches the reported `81 → 01` at open. `41` is the close edge and appears about 26 ms before `8E 10`.

`0x2C6` during that close: bytes 5–6 are a uint16 that was 0 before the `8E` steps and then climbs `0x0A84`, `0x14B8`, `0x1C90` … toward about `0x3948` (14664 counts) with the shape of an RC precharge. A volt scale is not confirmed (0.01 V would be only ~147 V). The worker exposes `link_raw` and does not print volts for it. Bytes 1–2 stay `0x0002` until they become `0x02FF` near the end of the ramp, and a small signed word at bytes 3–4 appears at the same time.

### `0x134` when nothing ACKs

Battery-only and vehicle logs in this repository contain `0x134` once, or not at all. Those captures were acknowledged by a car or by another controller. On cp2b, with the interface in listen-only and no other node acknowledging, the pack floods `0x134` at about 90% bus load. As soon as a controller ACKs, the flood stops and the pack streams the ~30 broadcast IDs seen in the battery-only CSVs (31 IDs including the two UDS addresses).

ACK is done by the CAN controller, not by a UDS response. The worker never sends a frame unless `--enable-tx` is set, but a SocketCAN interface that is up in normal mode still ACKs. A true no-ACK listen is:

```text
sudo ip link set CHANNEL down
sudo ip link set CHANNEL type can bitrate 500000 listen-only on
sudo ip link set CHANNEL up
```

## 7. What changed relative to the June 2026 notes

- `0x334` is a 96-cell, 4×14-bit map. The 3-word formula is retired for new code.
- UDS reset path is `0x6B4`/`0x694`, extended session, no security, routines `DD35`, `DF60`, `DF46`, `DFFC`, `DD0B`, and clear `14 FF FF FF` with five `7F 14 78` then `54`.
- Fiat close/open edges in the attached logs are `0x27A` and `0x342` byte 2, with `0x2C6` ramping during precharge. The e3008 candumps still show `0x281` / `0x591`. Both stand; they are different captures.
- `D46F` is 20 bytes, not a 96-bit mask. `D440` is 108 live millivolt words.
- `D86D` and `D45A` are the balance flag and the healthy/latched marker from the operator. `D810` was not read in this set.
- `2E D900 01` is a known-bad write and is blocked.
- `0x3B4`, `0x214`, `0x5C6`, and `0x353` are not given current, pack-voltage, or SoC scales.

## 8. Running the worker

From the repository root, with `PYTHONPATH` set by `pyproject.toml` for pytest:

```text
python -m pytest
python -m psa82 routines
python -m psa82 listen --channel vcan0 --seconds 10
python -m psa82 listen --replay "e3008 can dump/e3008 contactors from off ton on.candump"
python -m psa82 poll --channel can0 --enable-tx
python -m psa82 read-dtc --channel can0 --enable-tx
python -m psa82 clear-dtc --channel can0 --enable-tx --confirm CLEAR-DTC
python -m psa82 routine contactor --channel can0 --enable-tx --confirm ROUTINE-DD35
```

Confirm tokens are `ROUTINE-DD35`, `ROUTINE-DF60`, `ROUTINE-DD0B`, `ROUTINE-DF46`, `ROUTINE-DFFC`, and `CLEAR-DTC`. A wrong token sends nothing. `--enable-tx` is required for any transmit, including the read-only poll and `read-dtc`.

Default poll DIDs are `D812`, `D813`, `D814`, `D800`, `D802`, `D866`, `D45A`, `D86D`. Add a read with `--did D810`. Polling never sends `0x19`, `0x14`, `0x31`, or `0x2E`.

On cp2b, pass the SocketCAN name that the interface actually has (`can0` is typical; `vcan0` is the default so a bench machine is not touched by accident).
