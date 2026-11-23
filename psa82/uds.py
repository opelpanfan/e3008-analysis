"""Small UDS client for the PSA 82 BMS (0x6B4 -> 0x694)."""

from __future__ import annotations

from dataclasses import dataclass

from psa82.isotp import FLOW_CONTROL, IsoTpReassembler, encode_single_frame, pad8

TESTER_ID = 0x6B4
ECU_ID = 0x694

NRC_RESPONSE_PENDING = 0x78

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


class UdsTimeout(TimeoutError):
    pass


class UdsNegativeResponse(RuntimeError):
    def __init__(self, service: int, nrc: int):
        self.service = service
        self.nrc = nrc
        name = NRC_NAMES.get(nrc, "unknown")
        super().__init__(f"NRC 0x{nrc:02X} {name} for service 0x{service:02X}")


@dataclass
class DtcRecord:
    code: str
    status: int

    def status_bits(self) -> list[str]:
        names = [
            "testFailed",
            "testFailedThisOperationCycle",
            "pendingDTC",
            "confirmedDTC",
            "testNotCompletedSinceLastClear",
            "testFailedSinceLastClear",
            "testNotCompletedThisOperationCycle",
            "warningIndicatorRequested",
        ]
        return [name for bit, name in enumerate(names) if self.status & (1 << bit)]


def decode_dtc_bytes(three: bytes) -> str:
    if len(three) < 3:
        return three.hex()
    a, b, c = three[0], three[1], three[2]
    prefix = "PCBU"[a >> 6]
    return f"{prefix}{a & 0x3F:02X}{b:02X}-{c:02X}"


def parse_read_dtc(payload: bytes) -> tuple[int, list[DtcRecord]]:
    """Parse a positive 59 02 response into (availability mask, records)."""
    if len(payload) < 3 or payload[0] != 0x59 or payload[1] != 0x02:
        raise ValueError(f"not a 59 02 response: {payload.hex()}")
    mask = payload[2]
    body = payload[3:]
    records: list[DtcRecord] = []
    for i in range(0, len(body) - 3, 4):
        records.append(DtcRecord(decode_dtc_bytes(body[i : i + 3]), body[i + 3]))
    return mask, records


def routine_status(payload: bytes) -> int | None:
    """Return the status byte of a 71 01/03 response, or None if it has none."""
    if len(payload) >= 5 and payload[0] == 0x71:
        return payload[4]
    return None


class UdsClient:
    def __init__(
        self,
        transport,
        tx_id: int = TESTER_ID,
        rx_id: int = ECU_ID,
        frame_timeout_s: float = 0.5,
        pending_timeout_s: float = 3.0,
    ) -> None:
        self.transport = transport
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.frame_timeout_s = frame_timeout_s
        self.pending_timeout_s = pending_timeout_s
        self.on_other = None  # optional (can_id, data) callback for broadcast frames

    def request(self, payload: bytes) -> bytes:
        if len(payload) > 7:
            raise NotImplementedError("this worker only sends single-frame UDS requests")
        self.transport.send(self.tx_id, encode_single_frame(payload))
        reasm = IsoTpReassembler()
        # Positive responses in the logs are 6-16 ms. Pending 0x78 repeats
        # about every 210 ms and the final 0x54 arrived at 1.07 s.
        waits = 0
        max_waits = int(self.pending_timeout_s / max(self.frame_timeout_s, 0.05)) + 8
        fc_sent = False
        while waits < max_waits:
            waits += 1
            msg = self.transport.recv(self.frame_timeout_s)
            if msg is None:
                if fc_sent:
                    continue
                raise UdsTimeout(f"no response to {payload.hex()}")
            cid, data = msg
            if cid != self.rx_id:
                if self.on_other is not None:
                    self.on_other(cid, data)
                continue
            if data and (data[0] >> 4) == 1 and not fc_sent:
                self.transport.send(self.tx_id, pad8(FLOW_CONTROL))
                fc_sent = True
            done = reasm.feed(data)
            if done is None:
                continue
            if len(done) >= 3 and done[0] == 0x7F and done[2] == NRC_RESPONSE_PENDING:
                reasm = IsoTpReassembler()
                fc_sent = False
                waits = 0
                continue
            if len(done) >= 3 and done[0] == 0x7F:
                raise UdsNegativeResponse(done[1], done[2])
            return done
        raise UdsTimeout(f"no final response to {payload.hex()}")
