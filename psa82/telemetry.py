"""Passive decoders for PSA 82 broadcast frames.

Cell voltages on 0x334 are four 14-bit big-endian millivolt values. Groups
0..23 are the 96 series cells. Groups 24..26 are extra slots (fixed 3000 mV
on the bench, 0x3FFE on the vehicle). The older 3-word shift formula matches
cell 0 only.

Temperatures on 0x3F4 are raw bytes minus 40 C. 0xFE is not a real probe.

0x2B4 carries three big-endian voltages in 0.01 V. 0x9C40 (400.00 V) is the
bench sentinel used when those voltages are not live.

0x3B4 and 0x214 are not decoded as current. On cp2b those broadcasts disagreed
with DID D816, which read 0.00 A.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CELL_ID = 0x334
TEMP_ID = 0x3F4
MANIFEST_ID = 0x583
VOLTAGE_ID = 0x2B4
ENERGY_OR_TAIL_ID = 0x3B4
ALIVE_ID = 0x214
CONTACTOR_ID = 0x591
SOC_CANDIDATE_ID = 0x353
PACK_BYTE_ID = 0x5C6
FLOOD_ID = 0x134
HANDSHAKE_ID = 0x27A
LINK_ID = 0x2C6
PRECHARGE_FLAG_ID = 0x342

SERIES_CELLS = 96
CELL_GROUPS = 24
SENTINEL_MV = 3000
INVALID_MV = 0x3FFE
VOLTAGE_SENTINEL = 0x9C40
TEMP_INVALID = 0xFE

# Vehicle-bus frames that each carry four uint16 millivolt values.
# 27 IDs * 4 = 108 transport channels, the same width as DID D440.
VEHICLE_CELL_IDS = (
    0x6D3, 0x6D4, 0x6E1, 0x6E2, 0x6E7, 0x6E8, 0x6E9, 0x6EB,
    0x6ED, 0x6EE, 0x6EF,
    *range(0x6F0, 0x700),
)

# Full payload -> name, from the e3008 candump state map. Byte 0 / 6 / 7.
CONTACTOR_STATES = {
    bytes.fromhex("2800000000000000"): "WAKE",
    bytes.fromhex("0800000000000400"): "PRECHARGE",
    bytes.fromhex("0800000000000410"): "PRECHARGE_CONFIRMED",
    bytes.fromhex("0000000000000410"): "MAIN_CLOSED",
    bytes.fromhex("3800000000000000"): "SUPERSTATE_38",
    bytes.fromhex("2000000000000000"): "SUPERSTATE_20",
    bytes.fromhex("0800000000001008"): "OPEN_BEGIN",
    bytes.fromhex("0000000000001008"): "OPENING",
    bytes.fromhex("0800000000001408"): "OPEN_TRANSIENT",
    bytes.fromhex("0000000000001408"): "OPEN_TRANSIENT_2",
    bytes.fromhex("0000000000001000"): "OFF_STABLE",
}

# Fiat 600e idle-to-on, bytes 0..1 of 0x27A in the order they appeared.
FIAT_HANDSHAKE = {
    bytes.fromhex("4e10"): "FIAT_PRE_CLOSE",
    bytes.fromhex("8e10"): "FIAT_CLOSE_STEP",
    bytes.fromhex("8e14"): "FIAT_CLOSE_STEP_14",
    bytes.fromhex("8e34"): "FIAT_CLOSE_STEP_34",
    bytes.fromhex("8e38"): "FIAT_CLOSE_STEP_38",
    bytes.fromhex("4e58"): "FIAT_AFTER_CLOSE",
    bytes.fromhex("4f58"): "FIAT_HELD",
    bytes.fromhex("4f00"): "FIAT_OPEN_HOLD",
    bytes.fromhex("4f10"): "FIAT_OPEN_EDGE",
}


def decode_cells_14bit(data: bytes) -> tuple[int, tuple[int, int, int, int]] | None:
    if len(data) < 8:
        return None
    mux = data[0] >> 3
    c0 = (data[1] << 6) | (data[2] >> 2)
    c1 = ((data[2] & 0x03) << 12) | (data[3] << 4) | (data[4] >> 4)
    c2 = ((data[4] & 0x0F) << 10) | (data[5] << 2) | (data[6] >> 6)
    c3 = ((data[6] & 0x3F) << 8) | data[7]
    return mux, (c0, c1, c2, c3)


def decode_temps(data: bytes) -> tuple[int, list[float | None]] | None:
    if len(data) < 8:
        return None
    page = data[0] >> 5
    values: list[float | None] = []
    for raw in data[1:8]:
        values.append(None if raw == TEMP_INVALID else float(raw - 40))
    return page, values


def _u16(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


@dataclass
class PackTelemetry:
    cells_mv: list[int | None] = field(default_factory=lambda: [None] * (CELL_GROUPS * 4))
    extra_cells_mv: list[int | None] = field(default_factory=list)
    temp_pages: dict[int, list[float | None]] = field(default_factory=dict)
    cell_count_declared: int | None = None
    temp_count_declared: int | None = None
    manifest_ready: bool = False
    voltages_v: list[float] | None = None
    voltages_live: bool = False
    contactor_state: str | None = None
    contactor_raw: str | None = None
    handshake: str | None = None
    handshake_raw: str | None = None
    precharge_flag: int | None = None
    link_raw: int | None = None
    soc_byte: int | None = None
    id_5c6: str | None = None
    tail_3b4: str | None = None
    alive_214: str | None = None
    vehicle_cells_mv: dict[int, tuple[int, int, int, int]] = field(default_factory=dict)
    frames: int = 0
    id_counts: dict[int, int] = field(default_factory=dict)

    def series_cells(self) -> list[int]:
        return [v for v in self.cells_mv[:SERIES_CELLS] if v is not None and v != INVALID_MV]

    def temperatures(self) -> list[float]:
        found: list[float] = []
        for page in sorted(self.temp_pages):
            for value in self.temp_pages[page]:
                if value is not None:
                    found.append(value)
        return found

    def summary(self) -> str:
        lines = [f"frames={self.frames} ids={len(self.id_counts)}"]
        cells = self.series_cells()
        if cells:
            lines.append(
                f"cells={len(cells)} min={min(cells)} mV max={max(cells)} mV "
                f"mean={sum(cells) / len(cells):.1f} mV"
            )
        temps = self.temperatures()
        if temps:
            lines.append(f"temps={len(temps)} min={min(temps):.0f} C max={max(temps):.0f} C")
        if self.cell_count_declared is not None:
            # On the battery-only bus these bytes are the 24-probe / 96-cell manifest.
            # The Fiat vehicle 0x583 payload is a different frame, so the summary
            # keeps the byte positions rather than always calling them counts.
            lines.append(
                f"0x583 byte5={self.temp_count_declared} byte6={self.cell_count_declared} "
                f"ready={self.manifest_ready}"
            )
        if self.voltages_v is not None:
            shown = ", ".join(f"{v:.2f} V" for v in self.voltages_v)
            lines.append(f"0x2B4 {shown} live={self.voltages_live}")
        if self.contactor_state:
            lines.append(f"0x591 {self.contactor_state} raw={self.contactor_raw}")
        if self.handshake:
            lines.append(f"0x27A {self.handshake} raw={self.handshake_raw}")
        if self.precharge_flag is not None:
            lines.append(f"0x342 byte2={self.precharge_flag:02X}")
        if self.link_raw is not None:
            lines.append(f"0x2C6 link_raw={self.link_raw}")
        if self.soc_byte is not None:
            lines.append(f"0x353 byte3={self.soc_byte:02X} (not a confirmed SoC percent)")
        if self.tail_3b4 is not None:
            lines.append(f"0x3B4 tail={self.tail_3b4} (not scaled as current or energy)")
        flood = self.id_counts.get(FLOOD_ID, 0)
        if self.frames and flood / self.frames > 0.5:
            lines.append(
                f"0x134 is {flood}/{self.frames} frames. The pack floods this ID when nothing ACKs."
            )
        return "\n".join(lines)


def apply_frame(state: PackTelemetry, can_id: int, data: bytes) -> None:
    state.frames += 1
    state.id_counts[can_id] = state.id_counts.get(can_id, 0) + 1
    if can_id == CELL_ID:
        decoded = decode_cells_14bit(data)
        if decoded is None:
            return
        mux, cells = decoded
        if mux < CELL_GROUPS:
            base = mux * 4
            for offset, value in enumerate(cells):
                state.cells_mv[base + offset] = value
        else:
            while len(state.extra_cells_mv) < (mux - CELL_GROUPS + 1) * 4:
                state.extra_cells_mv.append(None)
            base = (mux - CELL_GROUPS) * 4
            for offset, value in enumerate(cells):
                state.extra_cells_mv[base + offset] = value
        return
    if can_id == TEMP_ID:
        decoded = decode_temps(data)
        if decoded is not None:
            page, values = decoded
            state.temp_pages[page] = values
        return
    if can_id == MANIFEST_ID and len(data) >= 7:
        state.temp_count_declared = data[5]
        state.cell_count_declared = data[6]
        state.manifest_ready = data[0:3] != bytes.fromhex("fdfdff")
        return
    if can_id == VOLTAGE_ID and len(data) >= 6:
        words = [_u16(data, 0), _u16(data, 2), _u16(data, 4)]
        state.voltages_v = [w / 100.0 for w in words]
        state.voltages_live = any(w != VOLTAGE_SENTINEL for w in words)
        return
    if can_id == CONTACTOR_ID and len(data) >= 8:
        raw = bytes(data[:8])
        state.contactor_raw = raw.hex()
        state.contactor_state = CONTACTOR_STATES.get(raw, "UNLISTED")
        return
    if can_id == HANDSHAKE_ID and len(data) >= 2:
        key = bytes(data[:2])
        state.handshake_raw = data[:4].hex()
        state.handshake = FIAT_HANDSHAKE.get(key, "UNLISTED")
        return
    if can_id == PRECHARGE_FLAG_ID and len(data) >= 3:
        state.precharge_flag = data[2]
        return
    if can_id == LINK_ID and len(data) >= 7:
        state.link_raw = _u16(data, 5)
        return
    if can_id == SOC_CANDIDATE_ID and len(data) >= 4:
        state.soc_byte = data[3]
        return
    if can_id == PACK_BYTE_ID:
        state.id_5c6 = data.hex()
        return
    if can_id == ENERGY_OR_TAIL_ID and len(data) >= 8:
        state.tail_3b4 = data[1:].hex()
        return
    if can_id == ALIVE_ID:
        state.alive_214 = data.hex()
        return
    if can_id in VEHICLE_CELL_IDS and len(data) >= 8:
        state.vehicle_cells_mv[can_id] = tuple(_u16(data, i) for i in (0, 2, 4, 6))  # type: ignore[assignment]
