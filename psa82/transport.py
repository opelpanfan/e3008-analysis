"""CAN transports. SocketCAN for the bench, queues for tests and log replay."""

from __future__ import annotations

import select
import socket
import struct

from psa82.actions import TxNotEnabled

CAN_FRAME = struct.Struct("=IB3x8s")
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x7FF


class SocketCanTransport:
    """Classic CAN socket. ``send`` raises unless ``tx_enabled`` is true.

    Opening the socket does not put the controller into listen-only mode.
    The controller ACKs frames whenever the interface is up in normal mode.
    That ACK is what stops the pack flooding 0x134. Use ``ip link`` as printed
    by the CLI when you need a true no-ACK listen.
    """

    def __init__(self, channel: str, tx_enabled: bool = False) -> None:
        self.channel = channel
        self.tx_enabled = tx_enabled
        self.sock: socket.socket | None = None

    def open(self) -> None:
        sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            sock.bind((self.channel,))
        except OSError as exc:
            sock.close()
            raise OSError(
                f"cannot bind SocketCAN channel {self.channel!r}: {exc}. "
                "Create it with: sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0"
            ) from exc
        self.sock = sock

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def send(self, can_id: int, data: bytes) -> None:
        if not self.tx_enabled:
            raise TxNotEnabled("SocketCAN TX is disabled on this transport")
        if self.sock is None:
            raise RuntimeError("SocketCAN socket is not open")
        if len(data) > 8:
            raise ValueError("classic CAN data is at most 8 bytes")
        payload = data + bytes(8 - len(data))
        flags = CAN_EFF_FLAG if can_id > CAN_SFF_MASK else 0
        self.sock.send(CAN_FRAME.pack(can_id | flags, len(data), payload))

    def recv(self, timeout: float | None = 0.0):
        if self.sock is None:
            raise RuntimeError("SocketCAN socket is not open")
        wait = 0.0 if timeout is None else timeout
        ready, _, _ = select.select([self.sock], [], [], wait)
        if not ready:
            return None
        raw = self.sock.recv(CAN_FRAME.size)
        can_id, dlc, data = CAN_FRAME.unpack(raw)
        if can_id & (CAN_RTR_FLAG | CAN_ERR_FLAG):
            return None
        can_id &= 0x1FFFFFFF
        dlc = min(dlc, 8)
        return can_id, bytes(data[:dlc])


class QueueTransport:
    """In-memory transport. RX is a queue of (id, data). TX is recorded."""

    def __init__(self, rx: list[tuple[int, bytes]] | None = None, tx_enabled: bool = True) -> None:
        self.rx = list(rx or [])
        self.tx: list[tuple[int, bytes]] = []
        self.tx_enabled = tx_enabled

    def send(self, can_id: int, data: bytes) -> None:
        if not self.tx_enabled:
            raise TxNotEnabled("queue transport TX is disabled")
        self.tx.append((can_id, bytes(data)))

    def recv(self, timeout: float | None = 0.0):
        if not self.rx:
            return None
        return self.rx.pop(0)
