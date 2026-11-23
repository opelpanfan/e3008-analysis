#!/usr/bin/env python3
"""Guarded PSA 82 crash-latch reset.

Default is a dry run: the UDS list is printed and nothing is sent.
``--confirm-tx`` is required before any frame goes on the bus.

Order when confirmed:

1. Baseline reads: D812, D87F, D45A, D482, D811, D869, D866, D802, then 19 02 26 and 19 02 FF.
2. Optional sourced emulator (``--with-emulator``), never 0x4C8.
3. 10 01, 10 03, D866/D802, 10 03, 31 01 DF60, 31 03 until 02.
4. ``--clear-after`` sends 14 FF FF FF only after DF60 returns.
5. 10 01, stop the emulator, wait, read the baseline again.

Refused: 0x2E (including D900 and D46E), 0x27, 0x11, 0x28, 0x85, 0x2F, 0x31 0x02, routine DFE1.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psa82.crash_frames import FrameClock, crash_4c8_spec  # noqa: E402
from psa82.crash_guard import df60_payloads  # noqa: E402
from psa82.crash_reset import read_baseline, run_df60, write_trace, Trace  # noqa: E402
from psa82.transport import SocketCanTransport  # noqa: E402
from psa82.uds import UdsClient  # noqa: E402


class _SendLock:
    def __init__(self, inner, lock: threading.Lock) -> None:
        self._inner = inner
        self._lock = lock
        self.tx_enabled = True

    def send(self, can_id: int, data: bytes) -> None:
        with self._lock:
            self._inner.send(can_id, data)

    def recv(self, timeout: float | None = 0.0):
        return self._inner.recv(timeout)


def _emulator(transport, stop: threading.Event, lock: threading.Lock) -> None:
    clock = FrameClock()
    start = time.monotonic()
    while not stop.is_set():
        now = time.monotonic() - start
        with lock:
            for can_id, payload in clock.pop_due(now):
                transport.send(can_id, payload)
        stop.wait(0.005)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded DF60 crash-latch test")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--confirm-tx", action="store_true", help="Required. Without it, nothing is sent.")
    parser.add_argument("--with-emulator", action="store_true", help="Also send the sourced 0x010/0x27A/0x382 frames.")
    parser.add_argument("--hold-emulator-across-wake", action="store_true")
    parser.add_argument("--clear-after", action="store_true", help="Send 14 FF FF FF only after DF60 returns.")
    parser.add_argument("--prelude-s", type=float, default=6.0)
    parser.add_argument("--period-s", type=float, default=0.065)
    parser.add_argument("--wake-wait", type=float, default=20.0, help="Seconds to wait after TX stops. 0 skips the reread.")
    parser.add_argument("--log-dir", default="crash-logs")
    args = parser.parse_args(argv)

    reads = int(round(args.prelude_s / args.period_s)) if args.prelude_s > 0 else 0
    print(crash_4c8_spec())
    print("UDS that would be sent:")
    for payload in df60_payloads(reads, clear_after=args.clear_after):
        print(" ", payload.hex())
    if args.with_emulator:
        print("Emulator: 0x010, idle 0x27A (4F 00..), 0x382. 0x4C8 stays off.")
    else:
        print("Emulator off. Pass --with-emulator to add the sourced frames.")
    if not args.confirm_tx:
        print("DRY RUN. Pass --confirm-tx to send. Nothing was transmitted.")
        return 0

    transport = SocketCanTransport(args.channel, tx_enabled=True)
    transport.open()
    lock = threading.Lock()
    wrapped = _SendLock(transport, lock)
    client = UdsClient(wrapped)
    stop = threading.Event()
    thread = None
    trace = Trace()
    stem = datetime.now(timezone.utc).strftime("crash-reset-%Y%m%dT%H%M%SZ")
    try:
        if args.with_emulator:
            thread = threading.Thread(target=_emulator, args=(transport, stop, lock), daemon=True)
            thread.start()
            trace.add("phase", note="emulator started (0x010, 0x27A idle, 0x382)")
        read_baseline(client, trace, label="baseline")
        run_df60(
            client,
            trace,
            prelude_s=args.prelude_s,
            period_s=args.period_s,
            clear_after=args.clear_after,
            sleeper=time.sleep,
        )
        if thread is not None and not args.hold_emulator_across_wake:
            stop.set()
            thread.join(timeout=1.0)
            thread = None
            trace.add("phase", note="emulator stopped before the wake wait")
        if args.wake_wait > 0:
            trace.add("phase", note=f"waiting {args.wake_wait:.0f}s for a 12 V cycle")
            print(f"TX for DF60 is finished. Cycle 12 V if that is the test, then this waits {args.wake_wait:.0f}s.")
            time.sleep(args.wake_wait)
            read_baseline(client, trace, label="after-wake")
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=1.0)
        transport.close()
        text_path, json_path = write_trace(trace, args.log_dir, stem)
        print(trace.text())
        print(f"wrote {text_path} and {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
