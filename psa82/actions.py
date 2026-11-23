"""Operator-confirmed diagnostic actions.

The routine order is the one observed across the successful tool runs:

    10 01 -> 10 03 -> alternate 22 D866 / 22 D802 -> 10 03 -> 31 01 -> 31 03 until 02 -> 10 01

Nothing here sends by itself. ``worker.Worker`` is what puts frames on the bus,
and only after the TX gate and the confirmation token have been checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from psa82.dids import FORBIDDEN_WRITE_PAYLOAD, PRECONDITION_DIDS

# Result byte 0x02 is "finished OK" in every routine that returned one.
# 0x01 is "still running" (seen on DF60 / collision reset).
ROUTINE_RUNNING = 0x01
ROUTINE_DONE = 0x02

CLEAR_DTC_PAYLOAD = bytes((0x14, 0xFF, 0xFF, 0xFF))
READ_DTC_MASK = 0x26  # 19 02 26, the mask in the code-clear capture


@dataclass(frozen=True)
class Routine:
    name: str
    rid: int
    confirm: str
    summary: str
    # Attached braker log returned 71 01 DD 0B with no status byte and no 31 03.
    # The broader 14-run set polled 31 03 until 02, so the worker polls, and
    # stops if the ECU rejects results instead of retrying forever.
    poll_results: bool = True


ROUTINES: dict[str, Routine] = {
    "contactor": Routine(
        "contactor",
        0xDD35,
        "ROUTINE-DD35",
        "Contactor / switcher reinit. Start 71 01 DD 35 01, results 02.",
    ),
    "crash": Routine(
        "crash",
        0xDF60,
        "ROUTINE-DF60",
        "Crash / collision latch clear. Vehicle logs needed repeated 31 03 while status stayed 01.",
    ),
    "collision": Routine(
        "collision",
        0xDF60,
        "ROUTINE-DF60",
        "Alias of crash (DF60).",
    ),
    "breaker": Routine(
        "breaker",
        0xDD0B,
        "ROUTINE-DD0B",
        "Breaker clear. Attached log: positive start with no status byte.",
    ),
    "braker": Routine(
        "braker",
        0xDD0B,
        "ROUTINE-DD0B",
        "Alias of breaker (DD0B).",
    ),
    "isolation": Routine(
        "isolation",
        0xDF46,
        "ROUTINE-DF46",
        "Isolation clear. Start 01, results 02.",
    ),
    "undervoltage": Routine(
        "undervoltage",
        0xDFFC,
        "ROUTINE-DFFC",
        "Undervoltage clear. Start 01, results 02.",
    ),
}

ALLOWED_ROUTINE_IDS = frozenset(item.rid for item in ROUTINES.values())
CLEAR_DTC_CONFIRM = "CLEAR-DTC"

POLL_SERVICES = frozenset({0x10, 0x3E, 0x22})
MANUAL_READ_SERVICES = frozenset({0x19})


class RequestRejected(PermissionError):
    """The payload is outside the service and routine allowlist."""


class TxNotEnabled(PermissionError):
    """Transmission was not explicitly enabled."""


class ConfirmationRequired(PermissionError):
    """The operator confirmation token did not match."""


def require_tx(tx_enabled: bool, confirm: str | None, expected: str) -> None:
    if not tx_enabled:
        raise TxNotEnabled(
            "TX is disabled. Listen-only is the default; pass --enable-tx to send anything."
        )
    if confirm != expected:
        raise ConfirmationRequired(
            f"refusing to send. Pass --confirm {expected} to run this action."
        )


def assert_payload_allowed(payload: bytes, *, context: str) -> None:
    """Reject anything the worker must never transmit.

    ``context`` is ``poll``, ``routine``, ``clear``, or ``read_dtc``.
    """
    if not payload:
        raise RequestRejected("empty UDS payload")
    if payload[0] == 0x2E or payload.startswith(FORBIDDEN_WRITE_PAYLOAD):
        raise RequestRejected(
            "WriteDataByIdentifier (0x2E) is not implemented. "
            "2E D900 01 collapsed insulation readings on a pack and must not be sent."
        )
    sid = payload[0]
    if context == "poll" and sid not in POLL_SERVICES:
        raise RequestRejected(
            f"automatic poll may send only 0x10, 0x3E, 0x22; refused 0x{sid:02X}"
        )
    if context == "read_dtc" and sid not in MANUAL_READ_SERVICES | {0x3E}:
        raise RequestRejected(f"read-dtc may send only 0x19; refused 0x{sid:02X}")
    if context == "clear" and sid not in {0x14, 0x19, 0x3E}:
        raise RequestRejected(f"clear-dtc may send only 0x14 and 0x19; refused 0x{sid:02X}")
    if context == "routine" and sid not in POLL_SERVICES | {0x31}:
        raise RequestRejected(f"routine context refused service 0x{sid:02X}")
    if sid == 0x14 and payload != CLEAR_DTC_PAYLOAD:
        raise RequestRejected("ClearDiagnosticInformation is only allowed as 14 FF FF FF")
    if sid == 0x31:
        if len(payload) < 4:
            raise RequestRejected("routine request is short")
        sub = payload[1]
        rid = (payload[2] << 8) | payload[3]
        if sub not in (0x01, 0x03):
            raise RequestRejected("only routine start (31 01) and results (31 03) are allowed")
        if rid not in ALLOWED_ROUTINE_IDS:
            raise RequestRejected(f"routine 0x{rid:04X} is not one of the verified reset routines")
        if payload[4:]:
            raise RequestRejected("verified routines were sent with no option record")
    if sid == 0x22 and len(payload) != 3:
        raise RequestRejected("ReadDataByIdentifier must be exactly 22 DID_HI DID_LO")
    if sid == 0x10 and (len(payload) != 2 or payload[1] not in (0x01, 0x03)):
        raise RequestRejected("session control is only 10 01 or 10 03")
    if sid == 0x3E and payload != bytes((0x3E, 0x00)):
        raise RequestRejected("TesterPresent is only 3E 00, matching the logs")
    if sid == 0x19 and (len(payload) != 3 or payload[1] != 0x02):
        raise RequestRejected("ReadDTCInformation is only 19 02 <mask>, matching the logs")


@dataclass(frozen=True)
class Step:
    op: str  # "uds" or "wait" or "poll_results"
    payload: bytes = b""
    delay_s: float = 0.0
    context: str = "routine"


def routine_steps(
    routine: Routine,
    *,
    prelude_s: float = 6.0,
    period_s: float = 0.065,
) -> list[Step]:
    """Build the verified tool order. ``prelude_s`` 0 skips the D866/D802 loop."""
    steps = [
        Step("uds", bytes((0x10, 0x01))),
        Step("uds", bytes((0x10, 0x03))),
    ]
    reads = 0
    if prelude_s > 0:
        if period_s <= 0:
            raise ValueError("period_s must be positive when prelude_s is positive")
        reads = int(round(prelude_s / period_s))
    for i in range(reads):
        did = PRECONDITION_DIDS[i % 2]
        steps.append(Step("uds", bytes((0x22, (did >> 8) & 0xFF, did & 0xFF))))
        steps.append(Step("wait", delay_s=period_s))
    steps.append(Step("uds", bytes((0x10, 0x03))))
    rid_hi, rid_lo = (routine.rid >> 8) & 0xFF, routine.rid & 0xFF
    steps.append(Step("uds", bytes((0x31, 0x01, rid_hi, rid_lo))))
    if routine.poll_results:
        steps.append(Step("poll_results", bytes((0x31, 0x03, rid_hi, rid_lo))))
    steps.append(Step("uds", bytes((0x10, 0x01))))
    for step in steps:
        if step.op == "uds" or step.op == "poll_results":
            assert_payload_allowed(step.payload, context="routine")
    return steps


def clear_dtc_steps(mask: int = READ_DTC_MASK) -> list[Step]:
    before = bytes((0x19, 0x02, mask & 0xFF))
    steps = [
        Step("uds", before, context="clear"),
        Step("uds", CLEAR_DTC_PAYLOAD, context="clear"),
        Step("uds", before, context="clear"),
    ]
    for step in steps:
        assert_payload_allowed(step.payload, context="clear")
    return steps


def read_dtc_steps(mask: int = READ_DTC_MASK) -> list[Step]:
    payload = bytes((0x19, 0x02, mask & 0xFF))
    assert_payload_allowed(payload, context="read_dtc")
    return [Step("uds", payload, context="read_dtc")]
