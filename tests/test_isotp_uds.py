"""ISO-TP and UDS against the code-clear capture."""

from __future__ import annotations

from psa82.isotp import FLOW_CONTROL, IsoTpReassembler, encode_frames, encode_single_frame, pad8
from psa82.uds import UdsClient, UdsNegativeResponse, parse_read_dtc

# Positive 59 02 from e3008 code clear.csv, before 14 FF FF FF.
DTC_BEFORE = bytes.fromhex(
    "5902ffe000062fd601872fc401816d1af1122fd10e872fd14a872f"
    "1586166d1a13962e10f7132f10f9132f0adc0164d15e872fd14e876d"
    "0562166d1aea166ddf00006d1b45316d"
)
DTC_AFTER = bytes.fromhex(
    "5902ffe000062fd10e872fd14a872f10f7132f10f9132f0adc0164d15e872f"
)

BEFORE_CODES = [
    "U2000-06", "U1601-87", "U0401-81", "P1AF1-12", "U110E-87", "U114A-87",
    "P1586-16", "P1A13-96", "P10F7-13", "P10F9-13", "P0ADC-01", "U115E-87",
    "U114E-87", "P0562-16", "P1AEA-16", "U1F00-00", "P1B45-31",
]
AFTER_CODES = [
    "U2000-06", "U110E-87", "U114A-87", "P10F7-13", "P10F9-13", "P0ADC-01", "U115E-87",
]


def test_single_frame_matches_log_padding():
    frame = encode_single_frame(bytes.fromhex("3101dd35"))
    assert frame == bytes.fromhex("043101dd35000000")
    assert pad8(FLOW_CONTROL) == bytes.fromhex("3000000000000000")


def test_reassemble_logged_dtc_response():
    frames = encode_frames(DTC_BEFORE)
    assert frames[0][:2] == bytes.fromhex("1047")
    reasm = IsoTpReassembler()
    done = None
    for frame in frames:
        done = reasm.feed(frame) or done
    assert done == DTC_BEFORE
    mask, records = parse_read_dtc(done)
    assert mask == 0xFF
    assert [rec.code for rec in records] == BEFORE_CODES
    assert records[0].status == 0x2F
    assert "confirmedDTC" in records[0].status_bits()
    mask, after = parse_read_dtc(DTC_AFTER)
    assert [rec.code for rec in after] == AFTER_CODES
    assert len(before_only(BEFORE_CODES, AFTER_CODES)) == 10


def before_only(before, after):
    return [code for code in before if code not in after]


class ScriptedEcu:
    def __init__(self, handler):
        self.handler = handler
        self.rx = []
        self.tx = []
        self.reasm = IsoTpReassembler()
        self.tx_enabled = True

    def send(self, can_id, data):
        self.tx.append((can_id, bytes(data)))
        if can_id != 0x6B4:
            return
        payload = self.reasm.feed(data)
        if payload is None:
            return
        for frame in self.handler(payload):
            self.rx.append((0x694, frame))

    def recv(self, timeout=None):
        if not self.rx:
            return None
        return self.rx.pop(0)


def test_client_accepts_pending_then_clear():
    calls = {"clear": 0}

    def handler(payload):
        if payload == bytes.fromhex("14ffffff"):
            calls["clear"] += 1
            return [
                encode_single_frame(bytes.fromhex("7f1478")),
                encode_single_frame(bytes.fromhex("54")),
            ]
        if payload == bytes.fromhex("190226"):
            body = DTC_BEFORE if calls["clear"] == 0 else DTC_AFTER
            return encode_frames(body)
        raise AssertionError(payload.hex())

    ecu = ScriptedEcu(handler)
    client = UdsClient(ecu, frame_timeout_s=0.01, pending_timeout_s=1.0)
    before = client.request(bytes.fromhex("190226"))
    cleared = client.request(bytes.fromhex("14ffffff"))
    after = client.request(bytes.fromhex("190226"))
    assert cleared == bytes.fromhex("54")
    assert [rec.code for rec in parse_read_dtc(before)[1]] == BEFORE_CODES
    assert [rec.code for rec in parse_read_dtc(after)[1]] == AFTER_CODES
    assert any(frame[:1] == b"\x30" for _cid, frame in ecu.tx)


def test_negative_response_is_raised():
    def handler(payload):
        return [encode_single_frame(bytes.fromhex("7f2222"))]

    client = UdsClient(ScriptedEcu(handler), frame_timeout_s=0.01)
    try:
        client.request(bytes.fromhex("22d812"))
    except UdsNegativeResponse as exc:
        assert exc.nrc == 0x22
    else:
        raise AssertionError("expected NRC")
