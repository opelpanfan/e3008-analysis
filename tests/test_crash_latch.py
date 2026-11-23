"""Crash-frame encoding and the DF60 allow-list."""

from __future__ import annotations

import pytest

from psa82.actions import RequestRejected
from psa82.crash_frames import (
    VCU_BCM_CRASH_TABLE,
    FrameClock,
    UnverifiedFrame,
    iter_vcu_bcm_crash,
    vcu_bcm_crash_byte,
)
from psa82.crash_guard import FACTORY_WRITE, ISOLATION_DISABLE, assert_crash_test_payload, df60_payloads
from psa82.crash_reset import run_guarded
from psa82.isotp import IsoTpReassembler, encode_single_frame


def test_010_cycle_matches_battery_emulator_and_the_contactor_log():
    assert vcu_bcm_crash_byte(0) == 0x96
    cycle = iter_vcu_bcm_crash(8)
    assert cycle[0] == bytes((0x96,))
    assert {byte[0] for byte in cycle} == set(VCU_BCM_CRASH_TABLE)
    assert [byte[0] for byte in cycle] == [0x96, 0x78, 0x5A, 0x3C, 0x1E, 0xF0, 0xD2, 0xB4]


def test_default_schedule_omits_unverified_4c8():
    clock = FrameClock()
    sent = []
    for step in range(0, 17):
        sent.extend(clock.pop_due(step * 0.05))
    ids = {can_id for can_id, _payload in sent}
    assert 0x4C8 not in ids
    assert 0x010 in ids
    crash = [payload for can_id, payload in sent if can_id == 0x010]
    assert crash[0] == b"\x96"
    assert len(crash[0]) == 1
    with pytest.raises(UnverifiedFrame):
        FrameClock(frozenset({0x4C8}))


def test_allow_list_blocks_factory_write_isolation_disable_and_resets():
    for payload in (
        FACTORY_WRITE,
        bytes.fromhex("2ed46e00"),
        ISOLATION_DISABLE,
        bytes.fromhex("3101dfe1"),
        bytes.fromhex("2701"),
        bytes.fromhex("1101"),
        bytes.fromhex("280003"),
        bytes.fromhex("8502"),
        bytes.fromhex("2f0000"),
        bytes.fromhex("3102df60"),
        bytes.fromhex("3101dd35"),
    ):
        with pytest.raises(RequestRejected):
            assert_crash_test_payload(payload)


def test_df60_order_puts_the_clear_after_the_routine():
    without = df60_payloads(2, clear_after=False)
    assert without == [
        bytes.fromhex("1001"),
        bytes.fromhex("1003"),
        bytes.fromhex("22d866"),
        bytes.fromhex("22d802"),
        bytes.fromhex("1003"),
        bytes.fromhex("3101df60"),
        bytes.fromhex("3103df60"),
        bytes.fromhex("1001"),
    ]
    with_clear = df60_payloads(0, clear_after=True)
    assert with_clear[-3:] == [
        bytes.fromhex("3103df60"),
        bytes.fromhex("14ffffff"),
        bytes.fromhex("1001"),
    ]
    assert bytes.fromhex("2ed90001") not in with_clear


class _Ecu:
    def __init__(self):
        self.tx = []
        self.rx = []
        self.reasm = IsoTpReassembler()
        self.tx_enabled = True

    def send(self, can_id, data):
        self.tx.append((can_id, bytes(data)))
        payload = self.reasm.feed(data)
        if payload is None:
            return
        self.rx.append((0x694, encode_single_frame(self._answer(payload))))

    def recv(self, timeout=None):
        if not self.rx:
            return None
        return self.rx.pop(0)

    def _answer(self, payload: bytes) -> bytes:
        if payload == bytes.fromhex("1001"):
            return bytes.fromhex("500100c80014")
        if payload == bytes.fromhex("1003"):
            return bytes.fromhex("500300c80014")
        if payload == bytes.fromhex("3e00"):
            return bytes.fromhex("7e00")
        if payload[0] == 0x22:
            return bytes((0x62,)) + payload[1:] + b"\x00"
        if payload == bytes.fromhex("190226") or payload == bytes.fromhex("1902ff"):
            return bytes.fromhex("5902ff")
        if payload == bytes.fromhex("3101df60"):
            return bytes.fromhex("7101df6001")
        if payload == bytes.fromhex("3103df60"):
            return bytes.fromhex("7103df6002")
        if payload == bytes.fromhex("14ffffff"):
            return bytes.fromhex("54")
        raise AssertionError(payload.hex())


def _uds(ecu: _Ecu) -> list[bytes]:
    reasm = IsoTpReassembler()
    out = []
    for _cid, frame in ecu.tx:
        done = reasm.feed(frame)
        if done:
            out.append(done)
    return out


def test_confirmed_run_sends_df60_and_not_a_write():
    from psa82.uds import UdsClient

    ecu = _Ecu()
    trace = run_guarded(
        UdsClient(ecu, frame_timeout_s=0.05),
        confirm=True,
        clear_after=True,
        prelude_s=0.13,
        period_s=0.065,
        sleeper=lambda _s: None,
        reread=False,
    )
    sent = _uds(ecu)
    assert bytes.fromhex("3101df60") in sent
    assert sent.count(bytes.fromhex("3103df60")) == 1
    assert bytes.fromhex("14ffffff") in sent
    assert sent.index(bytes.fromhex("3101df60")) < sent.index(bytes.fromhex("14ffffff"))
    assert all(payload[0] != 0x2E for payload in sent)
    assert all(payload[:4] != bytes.fromhex("3102dfe1") for payload in sent)
    assert any(event["kind"] == "tx" for event in trace.events)


def test_dry_run_sends_nothing():
    from psa82.uds import UdsClient

    ecu = _Ecu()
    trace = run_guarded(
        UdsClient(ecu),
        confirm=False,
        clear_after=False,
        prelude_s=6.0,
        period_s=0.065,
        sleeper=lambda _s: (_ for _ in ()).throw(AssertionError("slept")),
        reread=False,
    )
    assert ecu.tx == []
    assert "dry run" in trace.text()
