"""Periodic frames for the PSA 82 crash-latch bench.

0x4C8 has no sourced payload. Battery-Emulator lists ``CRASH_4C8`` as a frame
that still needs a vehicle log, and it does not transmit it. The crash frame
that source does transmit, and that ``CONTACTOR RESET.csv`` contains, is
``0x010`` / ``VCU_BCM_Crash``: DLC 1, 100 ms, byte 0 cycling through eight
fixed values.

Nothing in this module opens a socket.
"""

from __future__ import annotations

from dataclasses import dataclass

# dalathegreat/Battery-Emulator Software/src/battery/ECMP-BATTERY.h
# uint8_t data_010_CRC[8] = {0xB4, 0x96, 0x78, 0x5A, 0x3C, 0x1E, 0xF0, 0xD2};
# CAN id 0x010, DLC 1, comment "VCU_BCM_Crash 100ms".
# transmit_can() does counter_010 = (counter_010 + 1) % 8 before indexing,
# and counter_010 starts at 0, so the first transmitted byte is 0x96.
VCU_BCM_CRASH_ID = 0x010
VCU_BCM_CRASH_PERIOD_S = 0.100
VCU_BCM_CRASH_TABLE = (0xB4, 0x96, 0x78, 0x5A, 0x3C, 0x1E, 0xF0, 0xD2)

# Idle / fault payload. The contactor-close payload 4F 58 00 02 24 is not used.
VCU_BSI_WAKE_ID = 0x27A
VCU_BSI_WAKE_PERIOD_S = 0.050
VCU_BSI_WAKE_IDLE = bytes.fromhex("4f00000000000000")

BSI_INFO_ID = 0x382
BSI_INFO_PERIOD_S = 0.100
BSI_INFO_STATIC = bytes.fromhex("02e0000000000000")

CRASH_4C8_ID = 0x4C8


class UnverifiedFrame(RuntimeError):
    """A frame has no sourced payload, so it must not be transmitted."""


@dataclass(frozen=True)
class PeriodicFrame:
    can_id: int
    name: str
    period_s: float
    payload: bytes
    status: str
    citation: str


def vcu_bcm_crash_byte(step: int) -> int:
    """Byte 0 after ``step`` increments, matching Battery-Emulator.

    ``step`` 0 is the counter value before the first tick. The first frame
    therefore uses table index 1 (0x96).
    """
    index = (step + 1) % len(VCU_BCM_CRASH_TABLE)
    return VCU_BCM_CRASH_TABLE[index]


def iter_vcu_bcm_crash(count: int, start_step: int = 0) -> list[bytes]:
    return [bytes((vcu_bcm_crash_byte(start_step + i),)) for i in range(count)]


def sourced_frames() -> tuple[PeriodicFrame, ...]:
    """Frames with a published payload. 0x4C8 is not among them."""
    return (
        PeriodicFrame(
            VCU_BCM_CRASH_ID,
            "VCU_BCM_Crash",
            VCU_BCM_CRASH_PERIOD_S,
            bytes((vcu_bcm_crash_byte(0),)),
            "sourced",
            "Battery-Emulator ECMP-BATTERY.h data_010_CRC; "
            "CONTACTOR RESET.csv DLC 1 at 100 ms, same eight bytes",
        ),
        PeriodicFrame(
            VCU_BSI_WAKE_ID,
            "VCU_BSI_Wakeup_idle",
            VCU_BSI_WAKE_PERIOD_S,
            VCU_BSI_WAKE_IDLE,
            "sourced",
            "Battery-Emulator ECMP_27A fault/idle payload 4F 00..; "
            "not the contactor-close payload 4F 58 00 02 24",
        ),
        PeriodicFrame(
            BSI_INFO_ID,
            "BSIInfo_382",
            BSI_INFO_PERIOD_S,
            BSI_INFO_STATIC,
            "sourced",
            "Battery-Emulator ECMP_382 static 02 E0 00.., 100 ms",
        ),
    )


def crash_4c8_spec() -> str:
    return (
        "0x4C8 CRASH_4C8 is UNVERIFIED and is not transmitted. "
        "Battery-Emulator lists it in a TODO and does not define its bytes. "
        "AEE2010 community DBCs name a 3-byte Etat_Crash from the BSI, "
        "without a no-crash value, and that architecture is not the e-3008 gen2 bus. "
        "Pass a captured payload later; this tool will not invent one."
    )


class FrameClock:
    """Periodic schedule. Asking for 0x4C8 raises; it has no payload."""

    def __init__(self, only: frozenset[int] | None = None) -> None:
        self.only = only if only is not None else frozenset(spec.can_id for spec in sourced_frames())
        if CRASH_4C8_ID in self.only:
            raise UnverifiedFrame(crash_4c8_spec())
        unknown = self.only - {spec.can_id for spec in sourced_frames()}
        if unknown:
            raise UnverifiedFrame(
                "refusing unsourced CAN id(s): " + ", ".join(f"0x{i:03X}" for i in sorted(unknown))
            )
        self._next: dict[int, float] = {can_id: 0.0 for can_id in self.only}
        self._crash_step = 0

    def pop_due(self, now_s: float) -> list[tuple[int, bytes]]:
        due: list[tuple[int, bytes]] = []
        for spec in sourced_frames():
            if spec.can_id not in self._next:
                continue
            if now_s + 1e-9 < self._next[spec.can_id]:
                continue
            due.append((spec.can_id, self._payload(spec)))
            self._next[spec.can_id] += spec.period_s
        return due

    def _payload(self, spec: PeriodicFrame) -> bytes:
        if spec.can_id != VCU_BCM_CRASH_ID:
            return spec.payload
        byte = vcu_bcm_crash_byte(self._crash_step)
        self._crash_step += 1
        return bytes((byte,))
