"""Allow-list for the crash-latch bench sequence.

Refused, with no partial frame built:

- any WriteDataByIdentifier (0x2E), including 2E D900 01 and 2E D46E
- SecurityAccess (0x27), ECUReset (0x11), CommunicationControl (0x28)
- ControlDTCSetting (0x85), InputOutputControl (0x2F)
- RoutineControl stop (0x31 0x02) and any routine other than DF60 start/results
- routine DFE1 in particular (31 02 DF E1 disables isolation monitoring)
"""

from __future__ import annotations

from psa82.actions import RequestRejected

BASELINE_DIDS = (
    0xD812,
    0xD87F,
    0xD45A,
    0xD482,
    0xD811,
    0xD869,
    0xD866,
    0xD802,
)
CRASH_ROUTINE = 0xDF60
CLEAR_PAYLOAD = bytes((0x14, 0xFF, 0xFF, 0xFF))
ISOLATION_DISABLE = bytes((0x31, 0x02, 0xDF, 0xE1))
FACTORY_WRITE = bytes((0x2E, 0xD9, 0x00, 0x01))


def assert_crash_test_payload(payload: bytes) -> None:
    if not payload:
        raise RequestRejected("empty payload")
    sid = payload[0]
    if sid == 0x2E or payload.startswith(FACTORY_WRITE):
        did = ((payload[1] << 8) | payload[2]) if len(payload) >= 3 else 0
        raise RequestRejected(
            f"WriteDataByIdentifier 0x{did:04X} is refused. "
            "2E D900 01 collapsed insulation readings and must not be sent."
        )
    if sid in (0x27, 0x11, 0x28, 0x85, 0x2F):
        raise RequestRejected(f"service 0x{sid:02X} is not part of the crash-latch test")
    if payload[:4] == ISOLATION_DISABLE[:4] or (
        len(payload) >= 4 and payload[0] == 0x31 and payload[2:4] == b"\xdf\xe1"
    ):
        raise RequestRejected("routine DFE1 is refused; 31 02 DF E1 disables isolation monitoring")
    if sid == 0x31:
        if len(payload) < 4 or payload[1] not in (0x01, 0x03):
            raise RequestRejected("only routine start 31 01 DF60 and results 31 03 DF60 are allowed")
        rid = (payload[2] << 8) | payload[3]
        if rid != CRASH_ROUTINE or payload[4:]:
            raise RequestRejected(f"routine 0x{rid:04X} is refused in the crash-latch test")
        return
    if sid == 0x14:
        if payload != CLEAR_PAYLOAD:
            raise RequestRejected("ClearDiagnosticInformation is only 14 FF FF FF, and only after DF60")
        return
    if sid == 0x22:
        if len(payload) != 3:
            raise RequestRejected("ReadDataByIdentifier must be 22 DID_HI DID_LO")
        did = (payload[1] << 8) | payload[2]
        if did not in BASELINE_DIDS:
            raise RequestRejected(f"DID {did:04X} is outside the crash-latch baseline set")
        return
    if sid == 0x19:
        if len(payload) != 3 or payload[1] != 0x02 or payload[2] not in (0x26, 0xFF):
            raise RequestRejected("DTC read is only 19 02 26 or 19 02 FF")
        return
    if sid == 0x10 and payload in (bytes((0x10, 0x01)), bytes((0x10, 0x03))):
        return
    if sid == 0x3E and payload == bytes((0x3E, 0x00)):
        return
    raise RequestRejected(f"payload {payload.hex()} is outside the crash-latch allow-list")


def baseline_reads() -> list[bytes]:
    frames = [bytes((0x10, 0x03)), bytes((0x3E, 0x00))]
    for did in BASELINE_DIDS:
        frames.append(bytes((0x22, (did >> 8) & 0xFF, did & 0xFF)))
    frames.append(bytes((0x19, 0x02, 0x26)))
    frames.append(bytes((0x19, 0x02, 0xFF)))
    for frame in frames:
        assert_crash_test_payload(frame)
    return frames


def df60_payloads(prelude_reads: int, *, clear_after: bool) -> list[bytes]:
    """UDS payloads of the verified order, without the wait steps.

    ``prelude_reads`` is the number of alternating D866/D802 reads.
    ClearDiagnosticInformation is appended only when ``clear_after`` is set,
    and it is placed after the results request, before the return to the
    default session.
    """
    frames = [bytes((0x10, 0x01)), bytes((0x10, 0x03))]
    for i in range(prelude_reads):
        did = 0xD866 if i % 2 == 0 else 0xD802
        frames.append(bytes((0x22, (did >> 8) & 0xFF, did & 0xFF)))
    frames.append(bytes((0x10, 0x03)))
    frames.append(bytes((0x31, 0x01, 0xDF, 0x60)))
    frames.append(bytes((0x31, 0x03, 0xDF, 0x60)))
    if clear_after:
        frames.append(CLEAR_PAYLOAD)
    frames.append(bytes((0x10, 0x01)))
    for frame in frames:
        assert_crash_test_payload(frame)
    return frames
