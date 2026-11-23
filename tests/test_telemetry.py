"""Broadcast decoders checked against frames from the attached logs."""

from __future__ import annotations

from pathlib import Path

from psa82.telemetry import PackTelemetry, apply_frame, decode_cells_14bit
from psa82.worker import Worker

FIXTURE = Path(__file__).parent / "fixtures" / "bench_snippet.csv"
CANDUMP = Path(__file__).parent / "fixtures" / "close_snippet.candump"


def test_four_cells_not_the_old_three_word_formula():
    data = bytes.fromhex("0837bcdf037bcdef")
    mux, cells = decode_cells_14bit(data)
    assert mux == 1
    assert cells == (3567, 3568, 3567, 3567)
    # The old shift formula turned the third word into ~1980 mV.
    old_third = (((data[5] << 8) | data[6]) >> 4)
    assert old_third < 2500
    assert cells[2] > 3000


def test_series_cells_are_the_first_96_slots():
    state = PackTelemetry()
    apply_frame(state, 0x334, bytes.fromhex("0037c8df037c8def"))
    apply_frame(state, 0x334, bytes.fromhex("c02ee0bb82ee0bb8"))
    assert state.cells_mv[0:4] == [3570, 3568, 3570, 3567]
    assert state.extra_cells_mv[0:4] == [3000, 3000, 3000, 3000]
    assert 3000 not in state.series_cells() or state.cells_mv[0] == 3000


def test_temperatures_and_voltage_sentinel():
    state = PackTelemetry()
    apply_frame(state, 0x3F4, bytes.fromhex("0034343434343434"))
    apply_frame(state, 0x3F4, bytes.fromhex("a0fefefefefefefe"))
    assert state.temp_pages[0] == [12.0] * 7
    assert state.temp_pages[5] == [None] * 7
    apply_frame(state, 0x2B4, bytes.fromhex("9c409c409c400000"))
    assert state.voltages_live is False
    assert state.voltages_v == [400.0, 400.0, 400.0]
    apply_frame(state, 0x2B4, bytes.fromhex("879281688bf80000"))
    assert state.voltages_live is True
    assert state.voltages_v[0] == 347.06


def test_manifest_and_contactor_and_fiat_handshake():
    state = PackTelemetry()
    apply_frame(state, 0x583, bytes.fromhex("030e340054186000"))
    assert state.cell_count_declared == 96
    assert state.temp_count_declared == 24
    assert state.manifest_ready is True
    apply_frame(state, 0x591, bytes.fromhex("0000000000000410"))
    assert state.contactor_state == "MAIN_CLOSED"
    apply_frame(state, 0x27A, bytes.fromhex("4e10000000000000"))
    assert state.handshake == "FIAT_PRE_CLOSE"
    apply_frame(state, 0x27A, bytes.fromhex("8e10000000000000"))
    assert state.handshake == "FIAT_CLOSE_STEP"
    apply_frame(state, 0x342, bytes.fromhex("7800412800000080"))
    assert state.precharge_flag == 0x41
    apply_frame(state, 0x2C6, bytes.fromhex("8b000200000a8400"))
    assert state.link_raw == 0x0A84
    apply_frame(state, 0x3B4, bytes.fromhex("743f90000056a30f"))
    assert state.tail_3b4 == "3f90000056a30f"


def test_replay_listen_sends_nothing_and_decodes_snippet():
    from psa82.transport import QueueTransport

    transport = QueueTransport(tx_enabled=False)
    worker = Worker(transport, tx_enabled=False)
    state = worker.listen(replay_path=str(FIXTURE))
    assert transport.tx == []
    assert state.cells_mv[0] is None
    assert state.cells_mv[4:8] == [3567, 3568, 3567, 3567]
    assert 12.0 in state.temperatures()
    assert state.cell_count_declared == 96
    assert state.handshake == "FIAT_CLOSE_STEP"
    assert state.precharge_flag == 0x41


def test_candump_close_states():
    worker = Worker(transport=None, tx_enabled=False)
    state = worker.listen(replay_path=str(CANDUMP))
    assert state.contactor_state == "MAIN_CLOSED"


def test_flood_note():
    state = PackTelemetry()
    for _ in range(9):
        apply_frame(state, 0x134, bytes(8))
    apply_frame(state, 0x334, bytes.fromhex("0837bcdf037bcdef"))
    assert "floods" in state.summary()
