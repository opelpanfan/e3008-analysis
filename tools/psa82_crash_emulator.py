#!/usr/bin/env python3
"""Print or transmit the sourced PSA 82 wake/crash frames.

Dry-run is the default: frames are printed and nothing is sent.
``--tx`` is required before a SocketCAN interface is opened.

0x4C8 is listed and then skipped. There is no sourced no-crash payload for it.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psa82.crash_frames import (  # noqa: E402
    CRASH_4C8_ID,
    FrameClock,
    UnverifiedFrame,
    crash_4c8_spec,
    sourced_frames,
)
from psa82.transport import SocketCanTransport  # noqa: E402


def _parse_only(text: str | None) -> frozenset[int] | None:
    if not text:
        return None
    ids = set()
    for part in text.split(","):
        part = part.strip().lower().replace("0x", "")
        if not part:
            continue
        ids.add(int(part, 16))
    return frozenset(ids)


def _format(can_id: int, payload: bytes) -> str:
    return f"{can_id:03X}#" + payload.hex()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PSA 82 crash/wake frame emulator")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--seconds", type=float, default=1.0, help="How long to print or transmit")
    parser.add_argument("--tx", action="store_true", help="Transmit. Without this flag nothing is sent.")
    parser.add_argument(
        "--only",
        help="Comma-separated CAN ids to include, for example 010 or 010,27A. 4C8 is refused.",
    )
    args = parser.parse_args(argv)

    print(crash_4c8_spec())
    print("Sourced frames:")
    for spec in sourced_frames():
        print(
            f"  {spec.can_id:03X} {spec.name} every {spec.period_s * 1000:.0f} ms "
            f"dlc={len(spec.payload)} {spec.status}: {spec.citation}"
        )
    try:
        clock = FrameClock(_parse_only(args.only))
    except UnverifiedFrame as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not args.tx:
        print("DRY RUN. Pass --tx to transmit on the SocketCAN interface.")
        _print_window(clock, args.seconds)
        return 0

    transport = SocketCanTransport(args.channel, tx_enabled=True)
    transport.open()
    stop = False

    def _stop(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    start = time.monotonic()
    try:
        while not stop and (time.monotonic() - start) <= args.seconds:
            now = time.monotonic() - start
            for can_id, payload in clock.pop_due(now):
                transport.send(can_id, payload)
                print(_format(can_id, payload))
            time.sleep(0.005)
    finally:
        transport.close()
        print("emulator stopped; socket closed")
    return 0


def _print_window(clock: FrameClock, seconds: float) -> None:
    step = 0.0
    while step <= seconds + 1e-9:
        for can_id, payload in clock.pop_due(step):
            print(f"t={step:6.3f}s {_format(can_id, payload)}")
        step = round(step + 0.05, 3)
    print(f"0x{CRASH_4C8_ID:03X} not scheduled")


if __name__ == "__main__":
    sys.exit(main())
