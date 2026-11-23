"""ISO-TP (ISO 15765-2) for classic CAN, normal addressing, 8-byte padding.

The PSA 82 BMS talks UDS on 0x6B4 (tester) / 0x694 (ECU). Flow control in the
captures is always ``30 00 00`` (CTS, block size 0, STmin 0) and unused bytes
are padded with 0x00.
"""

from __future__ import annotations

FLOW_CONTROL = bytes((0x30, 0x00, 0x00))


class IsoTpError(ValueError):
    pass


def pad8(data: bytes) -> bytes:
    if len(data) > 8:
        raise IsoTpError(f"classic CAN frame is 8 bytes, got {len(data)}")
    return data + bytes(8 - len(data))


def encode_single_frame(payload: bytes) -> bytes:
    if not payload or len(payload) > 7:
        raise IsoTpError(f"single frame holds 1..7 bytes, got {len(payload)}")
    return pad8(bytes((len(payload),)) + payload)


def encode_frames(payload: bytes) -> list[bytes]:
    """Encode a payload. Multi-frame returns first frame then consecutive frames.

    The caller must wait for flow control after the first frame before sending
    the consecutive frames. Every request used by this worker fits in one frame.
    """
    if len(payload) <= 7:
        return [encode_single_frame(payload)]
    length = len(payload)
    first = bytes((0x10 | ((length >> 8) & 0x0F), length & 0xFF)) + payload[:6]
    frames = [pad8(first)]
    rest = payload[6:]
    seq = 1
    while rest:
        chunk = rest[:7]
        rest = rest[7:]
        frames.append(pad8(bytes((0x20 | seq,)) + chunk))
        seq = (seq + 1) & 0x0F
    return frames


class IsoTpReassembler:
    """Reassemble one direction of ISO-TP. Feed raw CAN data bytes."""

    def __init__(self) -> None:
        self.expected: int | None = None
        self.buf = bytearray()
        self.next_seq = 1
        self.seq_error = False

    def reset(self) -> None:
        self.expected = None
        self.buf = bytearray()
        self.next_seq = 1

    def feed(self, data: bytes) -> bytes | None:
        if not data:
            return None
        pci = data[0]
        kind = pci >> 4
        if kind == 0:
            length = pci & 0x0F
            self.reset()
            if length < 1 or length > 7 or len(data) < 1 + length:
                return None
            return bytes(data[1 : 1 + length])
        if kind == 1:
            length = ((pci & 0x0F) << 8) | data[1]
            self.expected = length
            self.buf = bytearray(data[2:8])
            self.next_seq = 1
            self.seq_error = False
            if len(self.buf) >= length:
                out = bytes(self.buf[:length])
                self.reset()
                return out
            return None
        if kind == 2:
            if self.expected is None:
                return None
            seq = pci & 0x0F
            if seq != self.next_seq:
                self.seq_error = True
            self.next_seq = (seq + 1) & 0x0F
            need = self.expected - len(self.buf)
            self.buf.extend(data[1 : 1 + min(7, need)])
            if len(self.buf) >= self.expected:
                out = bytes(self.buf[: self.expected])
                self.reset()
                return out
            return None
        return None
