"""TX stays off unless enabled, and the verified routine order is the only one sent."""

from __future__ import annotations

import pytest

from psa82.actions import (
    CLEAR_DTC_CONFIRM,
    RequestRejected,
    ROUTINES,
    assert_payload_allowed,
    routine_steps,
)
from psa82.dids import FORBIDDEN_WRITE_PAYLOAD, decode_did
from psa82.isotp import IsoTpReassembler, encode_single_frame
from psa82.worker import Worker


class ScriptedEcu:
    def __init__(self):
        self.rx = []
        self.tx = []
        self.reasm = IsoTpReassembler()
        self.tx_enabled = True
        self.results_left = 2  # two "still running" answers, then done

    def send(self, can_id, data):
        self.tx.append((can_id, bytes(data)))
        if can_id != 0x6B4:
            return
        payload = self.reasm.feed(data)
        if payload is None:
            return
        for frame in self._respond(payload):
            self.rx.append((0x694, frame))

    def recv(self, timeout=None):
        if not self.rx:
            return None
        return self.rx.pop(0)

    def _respond(self, payload: bytes):
        if payload == bytes.fromhex("1001"):
            return [encode_single_frame(bytes.fromhex("500100c80014"))]
        if payload == bytes.fromhex("1003"):
            return [encode_single_frame(bytes.fromhex("500300c80014"))]
        if payload == bytes.fromhex("3e00"):
            return [encode_single_frame(bytes.fromhex("7e00"))]
        if payload == bytes.fromhex("22d866"):
            return [encode_single_frame(bytes.fromhex("62d86600"))]
        if payload == bytes.fromhex("22d802"):
            return [encode_single_frame(bytes.fromhex("62d80200000000"))]
        if payload == bytes.fromhex("22d812"):
            return [encode_single_frame(bytes.fromhex("62d81200"))]
        if payload == bytes.fromhex("22d86d"):
            return [encode_single_frame(bytes.fromhex("62d86d01"))]
        if payload == bytes.fromhex("22d45a"):
            return [encode_single_frame(bytes.fromhex("62d45a03"))]
        if payload == bytes.fromhex("22d817"):
            return [encode_single_frame(bytes.fromhex("62d81742"))]
        if payload[:1] == b"\x22":
            did = payload[1:]
            return [encode_single_frame(bytes((0x62,)) + did + b"\x00")]
        if payload[:2] == bytes.fromhex("3101"):
            return [encode_single_frame(bytes.fromhex("7101") + payload[2:4] + b"\x01")]
        if payload[:2] == bytes.fromhex("3103"):
            status = 0x01 if self.results_left else 0x02
            if self.results_left:
                self.results_left -= 1
            return [encode_single_frame(bytes.fromhex("7103") + payload[2:4] + bytes((status,)))]
        raise AssertionError(f"unexpected request {payload.hex()}")


def _payloads(ecu: ScriptedEcu) -> list[bytes]:
    reasm = IsoTpReassembler()
    out = []
    for _cid, frame in ecu.tx:
        done = reasm.feed(frame)
        if done:
            out.append(done)
    return out


def test_factory_write_and_unlisted_services_are_rejected():
    with pytest.raises(RequestRejected):
        assert_payload_allowed(FORBIDDEN_WRITE_PAYLOAD, context="poll")
    with pytest.raises(RequestRejected):
        assert_payload_allowed(bytes.fromhex("2ed81201"), context="routine")
    with pytest.raises(RequestRejected):
        assert_payload_allowed(bytes.fromhex("2701"), context="poll")
    with pytest.raises(RequestRejected):
        assert_payload_allowed(bytes.fromhex("14ffffff"), context="poll")
    with pytest.raises(RequestRejected):
        assert_payload_allowed(bytes.fromhex("3101dd35"), context="poll")
    with pytest.raises(RequestRejected):
        assert_payload_allowed(bytes.fromhex("3101ffff"), context="routine")
    with pytest.raises(RequestRejected):
        assert_payload_allowed(bytes.fromhex("1002"), context="routine")


def test_routine_order_matches_the_tool():
    steps = routine_steps(ROUTINES["contactor"], prelude_s=0.13, period_s=0.065)
    payloads = [step.payload for step in steps if step.op != "wait"]
    assert payloads == [
        bytes.fromhex("1001"),
        bytes.fromhex("1003"),
        bytes.fromhex("22d866"),
        bytes.fromhex("22d802"),
        bytes.fromhex("1003"),
        bytes.fromhex("3101dd35"),
        bytes.fromhex("3103dd35"),
        bytes.fromhex("1001"),
    ]


def test_routine_is_not_sent_without_tx_or_token():
    ecu = ScriptedEcu()
    worker = Worker(ecu, tx_enabled=False, sleeper=lambda _s: None)
    with pytest.raises(PermissionError):
        worker.run_routine(ROUTINES["contactor"], "ROUTINE-DD35", prelude_s=0)
    assert ecu.tx == []

    worker.tx_enabled = True
    with pytest.raises(PermissionError):
        worker.run_routine(ROUTINES["crash"], "ROUTINE-DD35", prelude_s=0)
    assert ecu.tx == []


def test_routine_sends_verified_sequence_and_polls_until_done():
    ecu = ScriptedEcu()
    worker = Worker(ecu, tx_enabled=True, sleeper=lambda _s: None)
    result = worker.run_routine(
        ROUTINES["isolation"],
        "ROUTINE-DF46",
        prelude_s=0.13,
        period_s=0.065,
    )
    sent = _payloads(ecu)
    assert sent[:4] == [
        bytes.fromhex("1001"),
        bytes.fromhex("1003"),
        bytes.fromhex("22d866"),
        bytes.fromhex("22d802"),
    ]
    assert bytes.fromhex("3101df46") in sent
    assert sent.count(bytes.fromhex("3103df46")) == 3  # 01, 01, 02
    assert sent[-1] == bytes.fromhex("1001")
    assert "routine finished" in " ".join(result.notes)
    assert all(payload[0] != 0x2E for payload in sent)
    assert all(payload[0] != 0x14 for payload in sent)


def test_each_catalog_routine_is_gated():
    for name, routine in ROUTINES.items():
        ecu = ScriptedEcu()
        worker = Worker(ecu, tx_enabled=True, sleeper=lambda _s: None)
        worker.run_routine(routine, routine.confirm, prelude_s=0)
        sent = _payloads(ecu)
        assert any(p[:2] == bytes.fromhex("3101") and p[2:4] == routine.rid.to_bytes(2, "big") for p in sent)


def test_poll_is_read_only_and_refuses_when_tx_is_off():
    ecu = ScriptedEcu()
    worker = Worker(ecu, tx_enabled=False, sleeper=lambda _s: None)
    with pytest.raises(PermissionError):
        worker.poll_once()
    assert ecu.tx == []
    worker.tx_enabled = True
    lines = worker.poll_once((0xD812, 0xD86D, 0xD45A, 0xD817))
    text = "\n".join(lines)
    sent = _payloads(ecu)
    assert sent[0] == bytes.fromhex("1003")
    assert sent[1] == bytes.fromhex("3e00")
    assert bytes.fromhex("22d86d") in sent
    assert sent[-1] == bytes.fromhex("1001")
    assert all(p[0] in (0x10, 0x3E, 0x22) for p in sent)
    assert "balancing active" in text
    assert "healthy packs" in text
    assert "no physical scale" in text


def test_ambiguous_dids_are_not_given_a_false_unit():
    assert "no physical scale" in decode_did(0xD817, bytes.fromhex("42"))
    assert "no physical scale" in decode_did(0xD815, bytes.fromhex("1864"))
    assert "unconfirmed" in decode_did(0xD810, bytes.fromhex("6400"))
    assert "not a 12-byte" in decode_did(0xD46F, bytes(20))


def test_cli_rejects_a_bad_token_without_opening_can():
    from psa82.__main__ import main

    assert main(["routines"]) == 0
    assert main(["routine", "contactor", "--enable-tx", "--confirm", "NOPE"]) == 2
    assert main(["clear-dtc", "--enable-tx", "--confirm", "ROUTINE-DD35"]) == 2
    assert main(["listen", "--replay", str(__import__("pathlib").Path(__file__).parent / "fixtures" / "bench_snippet.csv")]) == 0


def test_clear_dtc_requires_its_own_token():
    ecu = ScriptedEcu()
    worker = Worker(ecu, tx_enabled=True, sleeper=lambda _s: None)
    with pytest.raises(PermissionError):
        worker.clear_dtc("ROUTINE-DD35")
    assert ecu.tx == []
    assert CLEAR_DTC_CONFIRM != ROUTINES["contactor"].confirm
