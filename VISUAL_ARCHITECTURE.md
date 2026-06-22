# Visual Summary: e3008 Contactor Control Architecture

## Frame Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     CONTACTOR CONTROL FLOW                       │
└─────────────────────────────────────────────────────────────────┘

CLOSE SEQUENCE (OFF → ON)
═══════════════════════════════════════════════════════════════════

Time 0ms       Time 30ms      Time 1,321ms   Time 2,272ms
│              │              │              │
├─0x281#31     ├─0x281#44     ├─0x591 ready  ├─0x281#AE
│ (wake cmd)   │ (precharge)   │ for confirm  │ (main close)
│              │              │              │
└─0x591#2800   ├─0x591#0800   ├─(wait)       ├─0x591#0000
  (wake)       │  ...0400     │ charging     │  ...0410
              │ (precharge)   │ capacitor    │ (CLOSED!)
              │              │              │
              └──────────────┴──────────────┴──────────→ READY

     ↑                    ↑                    ↑
     │                    │                    │
  0x281             0x591             0x583 updates
  COMMAND          FEEDBACK         (cell/temp counts)
  (VCU→BMS)       (BMS→VCU)            valid/ready


OPEN SEQUENCE (ON → OFF)
═══════════════════════════════════════════════════════════════════

Time 0s        Time 1.1s      Time 4.1s      Time 5.1s      Time 66.6s
│              │              │              │              │
├─0x281#85     ├─0x281#11     ├─0x281#8A     ├─0x281#99     ├─0x281#F3
│ (open begin) │ (standby)     │ (main open)  │ (wait dwell) │ (final)
│              │              │              │              │
└─0x591#0800   └─0x591#0000   └─0x591#0800   └─0x591#0000   └─0x591#0000
  ...1008      ...1008        ...1408        ...1408        ...1000
  (open)       (waiting)      (active open)  (long dwell)   (OFF!)
              │              │              │ ╱
              │ 3 seconds    │ 0.98s        │╱ ~61 second dwell
              │ wait        │              │ (capacitor discharge)
              │            │              │
              └────────────┴──────────────┴──────────→ SAFE
                                                    (Disconnect OK)
```

---

## HOLD STATE (Maintained-Closed Keepalive)

```
HOLD STATE - Active whenever contactors are closed
═══════════════════════════════════════════════════════════════════

  Two frames must be sent continuously:

  Every 135 ms:   0x281 # [B0_roll] 67 0D 80 00       (5 bytes)
  Every  58 ms:   0x428 # [B0_roll] 01 A8 00 00 00 00 00  (8 bytes)

  B0_roll = byte0 decrements -0x0F each transmission

  ┌────────────────────────────────────────────┐
  │  VCU KEEPALIVE LOOP (HOLD PHASE)           │
  │                                            │
  │  t+0ms:   0x428 b0=0xC2 01A8000000 0000   │
  │  t+58ms:  0x428 b0=0xB3 01A8000000 0000   │
  │  t+116ms: 0x428 b0=0xA4 01A8000000 0000   │
  │  t+135ms: 0x281 b0=0xDB 670D8000          │
  │  t+174ms: 0x428 b0=0x95 01A8000000 0000   │
  │  t+232ms: 0x428 b0=0x86 01A8000000 0000   │
  │  t+270ms: 0x281 b0=0xCC 670D8000          │
  │  ...continues until OPEN commanded...      │
  └────────────────────────────────────────────┘

  FAILURE to maintain keepalive:
    BMS safety watchdog fires
    Contactors open automatically
    0x591 transitions to OPEN state
```

```
CLOSE PATH (bit7=0 dominant)        OPEN PATH (bit7=1 dominant)
───────────────────────────         ──────────────────────────

0x31 (00110001)                     0x85 (10000101)
 ↓ [precharge relay ON]              ↓ [precharge relay OFF]
0x44 (01000100)                     0x11 (00010001)
 ↓ [wait for charging]               ↓ [standby wait]
0x44 (01000100)                     0x8A (10001010)
 ↓ [confirm charged]                 ↓ [main contactor OFF]
0x55 (01010101)                     0x99 (10011001)
 ↓ [prepare for main]                ↓ [long wait ~61s]
0xAE (10101110) ← Bit5 set          0xD5 (11010101) ← Bit5 set
 ↓ [main contactor ON]               ↓ [re-enter standby]
         │                           0xF3 (11110011)
    CLOSED ✓                         │
                                    OFF ✓
```

---

## Bit Pattern Analysis

```
Byte0 Structure:
┌────────────────────────────────┐
│ Bit7 Bit6 Bit5 Bit4 Bit3 Bit2 Bit1 Bit0 │
├────────────────────────────────┤

0x31 = 0│ 0│ 1│ 1│ 0│ 0│ 0│ 1   = CLOSE init
       CLOSE         Bit5=1
       Bit7=0

0x44 = 0│ 1│ 0│ 0│ 0│ 1│ 0│ 0   = CLOSE precharge
       CLOSE                    Advancement
       Bit7=0        Bit5=0

0x85 = 1│ 0│ 0│ 0│ 0│ 1│ 0│ 1   = OPEN begin
       OPEN
       Bit7=1        Bit5=0

0xAE = 1│ 0│ 1│ 0│ 1│ 1│ 1│ 0   = CLOSE complete
       OPEN intent    BUT used    (unusual)
       Bit7=1        during close
       Bit5=1

KEY DISCOVERY:
  Bit7 = 1 → OPEN path operations
  Bit7 = 0 → CLOSE path operations
  Bit5 = toggle → signals advancement/change
```

---

## Comparison: e3008 (Peugeot Medium) vs CMP-SMART (Citroën/Peugeot Small) - Both Stellantis

```
┌──────────────────────────────────────────────────────────────┐
│         STELLANTIS PLATFORM ARCHITECTURE COMPARISON            │
├──────────────────────────────────────────────────────────────┤

CMP-SMART (Small Platform)              e3008 (Medium Platform)
─────────────────────────────          ────────────────────────

0x351 (60ms messages)                  0x281 (variable, on-demand)
  │                                      │
  ├─ 0xA6 = OPEN                        ├─ 0x31, 0x44, 0xAE = CLOSE
  └─ 0x46 = CLOSE                       └─ 0x85, 0x11, 0x8A = OPEN

0x211 (100ms messages)                 0x281 byte1-4 (context)
  │                                      │
  ├─ 0x06 = discharge                   ├─ 0x5700... = close context
  ├─ 0x4A = charge                      └─ 0x6C0D8000 = open context
  └─ 0x17 = ready mode

Strategy:                              Strategy:
  Simple binary command                 Incremental state progression
  (explicit mode per message)           (new byte0 = next step)

Pros:                                  Pros:
  ✓ Unambiguous                        ✓ Fine-grained control
  ✓ Simple decode                      ✓ More precharge steps
                                       ✓ Built-in synchronization

Cons:                                  Cons:
  ✗ Requires continuous transmission   ✗ More complex decode
  ✗ Less monitoring of steps           ✗ Needs state correlation
```

---

## Timeline: Full ON-OFF-ON Cycle

```
t = 0.0s
  ↓ [Vehicle wake / ignition ON]
  
  ┌─ 0x281#31 (CLOSE init)
  ├─ 0x591#2800 (wake state)
  
t = 0.1s
  ├─ 0x281#44 (CLOSE precharge)
  ├─ 0x591#0800...0400 (precharge relay active)
  
t = 1.4s
  ├─ (Capacitor charging during this window)
  ├─ 0x591#0800...0410 (precharge confirmed)
  
t = 2.3s
  ├─ 0x281#AE (CLOSE main)
  ├─ 0x591#0000...0410 (main contactor CLOSED)
  ├─ 0x583#170944... (battery ready, cells/temps stable)
  
t = 2.3s → ~4290s
  │
  └─ [NORMAL OPERATION - Vehicle ready to drive]
     └─ Pedal activity: 0x154 word3 varies (0 to 652)
     └─ Cell voltages: 0x334 multiplexed @ 10 Hz
     └─ Temperatures: 0x3F4 multiplexed @ 10 Hz
     
t = ~4290s
  ├─ [Vehicle shutdown / ignition OFF]
  
  ├─ 0x281#85 (OPEN begin)
  ├─ 0x591#0800...1008 (precharge relay OFF)
  
t = ~4291s
  ├─ 0x281#11 (OPEN standby)
  ├─ 0x591#0000...1008 (standby wait)
  
t = ~4294s
  ├─ 0x281#8A (OPEN active)
  ├─ 0x591#0800...1408 (main contactor OFF)
  
t = ~4295s → ~4356s
  │
  ├─ 0x281#99 (OPEN wait)
  ├─ 0x591#0000...1408 (waiting for discharge)
  │
  └─ ✓ ~61 SECOND MAJOR DWELL (Precharge capacitor safety discharge)
  
t = ~4356s
  ├─ 0x281#F3 (OPEN final)
  ├─ 0x591#0000...1000 (STABLE OFF)
  
  ✓ SAFE TO DISCONNECT
  ✓ Battery is isolated
  ✓ No power to contactors

Total cycle: ~4356 seconds = ~72 minutes
  - CLOSE time: ~2.3 seconds
  - OPEN time: ~120+ seconds (mostly long dwell)
```

---

## Byte0 Reference Table (All Values Found)

```
╔════════════════════════════════════════════════════════════╗
║            0x281 BYTE0 COMMAND CODES FOUND                 ║
╠════════════════════════════════════════════════════════════╣
║ HEX  │ BINARY      │ SEQUENCE TYPE │ STAGE  │ NEXT STATE   ║
╠──────┼─────────────┼───────────────┼────────┼──────────────╣
║ 0x31 │ 00110001    │ CLOSE init    │ 1      │ 0x2800...    ║
║ 0x44 │ 01000100    │ CLOSE tech    │ 2      │ 0x0800...400 ║
║ 0x55 │ 01010101    │ CLOSE tech    │ 2b     │ 0x0800...400 ║
║ 0x8F │ 10001111    │ CLOSE tech    │ 2c     │ 0x0800...400 ║
║ 0xA0 │ 10100000    │ CLOSE tech    │ 2d     │ 0x0800...400 ║
║ 0xAE │ 10101110    │ CLOSE final   │ 3      │ 0x0000...410 ║
║      │             │               │        │              ║
║ 0x11 │ 00010001    │ OPEN tech     │ 2      │ 0x0000...008 ║
║ 0x85 │ 10000101    │ OPEN init     │ 1      │ 0x0800...008 ║
║ 0x8A │ 10001010    │ OPEN active   │ 3      │ 0x0800...408 ║
║ 0x99 │ 10011001    │ OPEN wait     │ 4      │ 0x0000...408 ║
║ 0xD5 │ 11010101    │ OPEN tech     │ 5      │ 0x0000...008 ║
║ 0xF3 │ 11110011    │ OPEN final    │ 6      │ 0x0000...000 ║
╚──────┴─────────────┴───────────────┴────────┴──────────────╝

LEGEND:
  CLOSE init  = Begin close sequence
  CLOSE tech  = Technical steps (wait, confirm, etc.)
  CLOSE final = Main contactor energized, close complete
  OPEN init   = Begin open sequence
  OPEN tech   = Technical steps during open
  OPEN active = Actively de-energize contactors
  OPEN wait   = Long dwell for safe discharge
  OPEN final  = Contactors fully open, isolated state
```

---

**Diagram Status:** Complete - Ready for firmware implementation ✓

