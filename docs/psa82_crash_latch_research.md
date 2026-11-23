# PSA 82 crash latch: research and bench plan

Date: 23 November 2026  
Pack: Peugeot e-3008 / Fiat 600e, 82 kWh, STLA / eCMP2 class BMS (`0x6B4` / `0x694`)  
Branch: `master-grok`

Confidence labels: **confirmed** means a cited source or a frame in this repository shows it. **Inferred** means the source is real but the meaning is our reading of it. **Unknown** means it was searched and not found, or two sources disagree.

## What tonight's bench already showed

Confirmed on cp2b, 23 November 2026, by Benas. Not re-run by this change.

The latched pack read `D812=01`, `D87F=01`, `D45A=04` (healthy packs read `03`), `D482=04`, `D811=00000020`, active `P1B7A-29`, plus `P1AF1-12`, `P10F7-13`, and the bench U-codes. HVIL `D869=00` (closed). `0x794` byte 0 was `0x48`.

The sequence `10 01`, `10 03`, `D866`/`D802`, `14 FF FF FF`, `10 03`, `31 01 DF 60` (`71 01 DF 60 01`), `31 03 DF 60` (`02` in about 260 ms), `10 01` moved `D812` from `01` to `05`, `D482` from `04` to `03`, and cleared `P1B7A-29`. `D87F` stayed `01`. `D45A` stayed `04`.

A 12 V power cycle put the latch back (`D812=01`, `D482=04`, `P1B7A-29` status `2F`). The same return-after-power-cycle was seen on 22 October. So DF60 changes the live latch and does not, by itself, stop the BMS writing it again at the next boot.

A 10 kΩ pull-down on connector pin 6 ("Info CRASH") cleared `P1AF1-12` and did not clear `P1B7A-29`.

## 1. Is 0x4C8 the crash frame we can send?

**Unknown for this pack. Do not transmit a guessed payload.**

Battery-Emulator's eCMP driver lists `CRASH_4C8` twice in a TODO of frames that are *not* implemented, and it says "STLA medium: Everything missing" and asks for full-vehicle logs:

- https://github.com/dalathegreat/Battery-Emulator/blob/main/Software/src/battery/ECMP-BATTERY.cpp (file header TODO, retrieved 23 Nov 2026)

The same file's `transmit_can()` never calls a `0x4C8` frame. The crash-labelled frame it does send is `0x010` (section 2).

A community DBC for the older PSA **AEE2010** architecture (208 / 2008 / 3008 II generation, not e-3008 gen2) names CAN id `1224` / `0x4C8` as `Etat_Crash`, DLC 3, sender `BSI___Kombiinstrument`, signals `Reserved_1`, `P223_CrashInfo`, `Reserved_2`:

- https://www.softechpro-solutions.com/can/peugeot-citroen-psa.html
- the same message list is mirrored from commaai/opendbc at https://cargeek.org/can/psa-aee2010-r3

That page does not give the bit positions, the period, a counter, a checksum, or the value that means "no crash". PSA-RE, which is the largest public PSA network corpus, says architecture `NEA2020` (2021+ cars, the generation of e-3008 gen2 / Fiat 600e) is not documented yet:

- https://github.com/prototux/PSA-RE

`0x4C8` does not appear in the Fiat 600e logs, the e-3008 candumps, `CONTACTOR RESET.csv`, or the battery-only idle log in this repository. The emulator therefore has `0x4C8` in the config as **UNVERIFIED** and refuses to transmit it, including if `--only 4C8` is passed.

## 2. The crash frame that is actually sourced: 0x010

**Confirmed bytes, period, and DLC. Inferred that they mean "no crash".**

Battery-Emulator defines:

```text
CAN id 0x010, DLC 1, comment "VCU_BCM_Crash 100ms"
data_010_CRC[8] = {0xB4, 0x96, 0x78, 0x5A, 0x3C, 0x1E, 0xF0, 0xD2}
counter_010 starts at 0 and is incremented before the table lookup,
so the first byte on the wire is 0x96, then 0x78, 0x5A, 0x3C, 0x1E, 0xF0, 0xD2, 0xB4.
```

Source: `ECMP-BATTERY.h` (`ECMP_010`, `data_010_CRC`) and `transmit_can()` in `ECMP-BATTERY.cpp`:

- https://github.com/dalathegreat/Battery-Emulator/blob/main/Software/src/battery/ECMP-BATTERY.h
- https://github.com/dalathegreat/Battery-Emulator/blob/main/Software/src/battery/ECMP-BATTERY.cpp

There is no CRC8 polynomial in that code. The eight values are a lookup table. The same table is used in the fault/idle state and in the contactor-close state, so Battery-Emulator does not change `0x010` when it wants the contactors shut.

`CONTACTOR RESET.csv` in this repository matches that table on the wire: 105 frames, SavvyCAN `LEN=1`, period median 100.0 ms (99.4–100.7 ms), byte 0 only the eight values above. `0x4C8` is absent from that file. The Fiat 600e logs and the e-3008 close candump also have no `0x010`. So this frame is on at least one Stellantis vehicle capture and in the eCMP emulator, and it is not on the battery-only bench captures. Whether the 82 kWh BMS requires it at boot is **inferred**, not confirmed.

The emulator sends this frame by default when `--tx` is passed. It does not send the Battery-Emulator contactor-close variants (`0x0F0` byte 1 `0x20`, `0x27A = 4F 58 00 02 24`). Those are a different experiment.

## 3. Other frames the eCMP emulator uses to look like a car

**Confirmed as what Battery-Emulator sends. Not confirmed as what stops a crash re-latch.**

From the same `transmit_can()` and the wiki pinout:

| Frame | Period | What we do with it | Source |
|---|---|---|---|
| `0x010` VCU_BCM_Crash | 100 ms | Sent. DLC 1, table above | header + `CONTACTOR RESET.csv` |
| `0x27A` VCU_BSI_Wakeup | 50 ms | Sent only as the idle/fault payload `4F 00 00 00 00 00 00 00` | `ECMP-BATTERY.cpp` fault branch. The close payload is not sent |
| `0x382` BSIInfo | 100 ms | Sent, static `02 E0 00 00 00 00 00 00` | `ECMP_382` in the header |
| `0x552` VCU time/distance | 1 s | Not sent. It is a running counter, not a crash input | header comment on `ECMP_552` |
| `0x0F0`, `0x0F2`, `0x112`, `0x17B`, `0x345`, `0x3A2` | 10–100 ms | Not sent. The "normal" variants are the contactor-close set | `transmit_can()` |
| `0x4C8` | unknown | Not sent. No payload | TODO only |

Wiki wiring, separate from CAN: on an ë-C4 the crash **pin** (pin 6, green) is tied to permanent 12 V, and pins 11–12 are the HVIL loop. That is a hardware bias, not a CAN frame.

- https://dalathegreat.github.io/Battery-Emulator-Wiki/battery/stellantis_ecmp_citroen_ds_opel_peugeot/

The e-3008 / Fiat connector is not that ë-C4 table. Pin 6 "Info CRASH" with a 10 kΩ pull-down is tonight's bench note: it cleared `P1AF1-12` only. **Inferred:** `P1AF1` follows the wire, and `P1B7A` follows something else (a memorised flag and/or a missing CAN crash frame).

DeepWiki's summary of the same driver (transmitted VCU/OBC set, `D812` named contactor-open reason, `0x4F4` bit called crash memorized on the MysteryVan 50/75 kWh path) is a secondary write-up of that source, not an independent log:

- https://deepwiki.com/dalathegreat/Battery-Emulator/4.9-stellantis-ecmp-platform

## 4. What "reset following a crash" is

**Service name confirmed by a forum report. The UDS bytes of that menu item are inferred.**

A Vauxhall Corsa-F hybrid thread describes Diagbox / Launch X431 / Autel: traction-battery ECU, service action "reset following a crash". The tool refused until work related to `P1A30 01` was done. Posters disagree on whether the airbag ECU's stored crash record must be cleared first. No one posted the CAN bytes.

- https://www.vauxhallownersnetwork.co.uk/threads/vauxhall-corsa-f-hybrid-crash-shutdown-p1aed-p1aef-engine-doesnt-switch-on.913181/
- page 2 of the same thread: https://www.vauxhallownersnetwork.co.uk/threads/vauxhall-corsa-f-hybrid-crash-shutdown-p1aed-p1aef-engine-doesnt-switch-on.913181/page-2

Battery-Emulator names `04 31 01 DF 60` `ECMP_COLLISION_RESET_START` and `04 31 03 DF 60` the progress poll. That is the routine tonight's bench ran, and the only crash routine in the logs surveyed. **Inferred** that Diagbox's "reset following a crash" on this BMS is DF60. Not confirmed, because no Diagbox trace was captured.

Airbag-module dump services are a different ECU. A commercial write-up says Diagbox will not erase a deployed airbag record and that the record lives in the restraint module:

- https://autoecufile.com/psa-airbag-module-dump-crash-clear/

That page is about the restraint ECU, not the BMS. It does not give a BMS routine.

`D87F` stayed `01` through a successful DF60 tonight. Battery-Emulator names `D87F` `PID_WIRE_CRASH` and a different identifier, `D42F`, `PID_CRASH_COUNTER`. No public procedure was found that writes either one back to zero. Whether Diagbox can clear `D87F` is **unknown**. The test tool only reads it.

## 5. DID and DTC names

| Item | Name we can cite | Confidence |
|---|---|---|
| `D812` | Battery-Emulator: `PID_CONT_REASON_OPEN` (0xD812). Tonight: `01` called Vehicle impact, `05` after DF60. The enum is not published | Name confirmed in source. Value `01` = impact is the bench label, not a cited enum |
| `D87F` | `PID_WIRE_CRASH` | Confirmed as the name in `ECMP-BATTERY.h`. Staying `01` after DF60 is tonight's bench |
| `D48D` | `PID_CAN_CRASH` | Name confirmed. Not in tonight's checklist |
| `D42F` | `PID_CRASH_COUNTER` | Name confirmed. Not read tonight |
| `D45A` | `PID_BMS_STATE`. Bench: `03` healthy, `04` latched, unchanged by DF60 | Name confirmed. The 03/04 meaning is the bench, not the header |
| `D482` | Not in the Battery-Emulator PID list. Bench: `04` latched, `03` after DF60, `04` again after power cycle | Unknown name |
| `D811` | `PID_BATTERY_STATE`. Tonight `00000020` | Name confirmed. The 4-byte value is not decoded |
| `D869` | `PID_HVIL_STATE`. Tonight `00` = closed | Name confirmed. `00` = closed is the bench label |
| `D815` | `PID_PACK_VOLTAGE` in Battery-Emulator. A PyPSADiag note also calls `D815` pack current and `D810` pack voltage, and says scaling was not decoded | Conflicting. Leave raw. PyPSADiag discussion: https://github.com/Barracuda09/PyPSADiag/discussions/159 |
| `P1AF1` | "Collision information line" | https://dot.report/dtc/P1A — short label, no failure-type byte |
| `P1AED` | "Collision detected by the traction battery". Autel on a 2020 Peugeot 2008 BMU_CTE1: `P1AED:01` "Vehicle impact detected — Electrical fault" | https://dot.report/dtc/P1A and the Autel PDF linked from search (report id `c4263c2268214bbfa06785f52b65a0f1`) |
| `P1AEF` | Forum: "Invalid vehicle impact information received by the CAN". Autel, on the VCU of that 2008: "Collision detected by traction battery — Mechanic fault" | Corsa thread above. Different ECU than the BMS |
| `P1B79-15` | Benas: "Vehicle Crash Information Wire Circuit" | Not found in the public lists checked. Treat as bench/service-tool text |
| `P1B7A` | Peugeot row on opendtc is "No description available". Chery and Mitsubishi texts for the same number are other makers' codes and do not apply | https://opendtc.net/dtc/P1B7A — **unknown** for PSA |
| `P10F7-13` | Not found as a PSA traction-battery definition in the sources above | **Unknown** |

`P1B7A-29` cleared when DF60 returned `02`, and it came back as `P1B7A-29/2F` after the 12 V cycle. That behaviour is tonight's bench, not a published definition.

## 6. What the tools will and will not send

`tools/psa82_crash_emulator.py` prints the schedule and sends nothing unless `--tx` is passed. Default transmit set: `0x010`, idle `0x27A`, `0x382`. `--only 010` sends the crash byte alone. `--only 4C8` exits 2 and sends nothing.

`tools/psa82_crash_reset_test.py` prints the UDS list and sends nothing unless `--confirm-tx` is passed. The order is the verified one, with `14 FF FF FF` only after DF60 and only with `--clear-after`. Tonight's run put the clear *before* DF60; this script does not offer that order. `--with-emulator` starts the sourced frames on the same bus. By default those frames stop before the wake wait, which matches "stop TX and wait for pack sleep". `--hold-emulator-across-wake` leaves them running through the wait, which is the experiment for "the BMS re-latches because the crash input is missing at boot".

Refused before a frame is built: `0x2E` (so `2E D900 01` and `2E D46E`), `0x27`, `0x11`, `0x28`, `0x85`, `0x2F`, `0x31` subfunction `02`, any routine other than `DF60`, and `DFE1` in particular. Logs go to `crash-logs/*.txt` and `crash-logs/*.json` (gitignored).

The transport is the repository's SocketCAN socket (`psa82/transport.py`), not the python-can package, so the tests have no extra dependency.

## 7. Bench plan, for approval before anyone passes `--confirm-tx`

1. Leave pin 6 as it is. Do not send `0x4C8`. Do not send `2E` or `DFE1`.
2. With the pack already awake, run `python tools/psa82_crash_emulator.py --only 010 --seconds 2` and read the dry-run. The first data byte must be `96`, then `78 5a 3c 1e f0 d2 b4`.
3. If that print is right, transmit only `0x010` for a few minutes (`--tx --only 010 --seconds 180 --channel can0`) and read `D812`, `D87F`, `D45A`, `P1B7A`. Expectation to test, not a prediction we can cite: `0x010` alone may do nothing, because it was absent from the Fiat and battery-only logs.
4. Power-cycle 12 V while `0x010` is still transmitting (`--hold-emulator-across-wake` on the reset tool, or leave the emulator running in another shell). Read the same DIDs after wake. This is the re-latch test. Stop if `D45A` or `D869` moves in a way that is not the latch.
5. Only after that, repeat with the default emulator set (`0x010` + idle `0x27A` + `0x382`). Still no `0x0F0` / close-`0x27A`.
6. DF60 itself: `python tools/psa82_crash_reset_test.py --channel can0 --confirm-tx --clear-after --wake-wait 30`. Cycle 12 V during the wait. Compare baseline and after-wake in `crash-logs/`.
7. A captured `0x4C8` from a live e-3008 or 600e, with the car not in a crash state, is what would move that id out of UNVERIFIED. Until that frame exists, the config stays empty.
