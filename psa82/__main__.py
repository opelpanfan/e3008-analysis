"""CLI for the PSA 82 bench worker.

Listen-only unless ``--enable-tx`` is passed. Reset routines and DTC clear
also require the matching ``--confirm`` token. They are never sent at startup.
"""

from __future__ import annotations

import argparse
import sys

from psa82 import __version__
from psa82.actions import CLEAR_DTC_CONFIRM, ROUTINES, require_tx
from psa82.dids import DEFAULT_POLL_DIDS, OPTIONAL_READ_DIDS
from psa82.transport import SocketCanTransport
from psa82.worker import Worker

LISTEN_ONLY_HINT = """
This process does not send CAN frames unless --enable-tx is set.
ACK is still a property of the SocketCAN controller. With no other node
acknowledging, the pack floods 0x134 (about 90% bus load). Once any controller
ACKs, it streams about 30 broadcast IDs instead. For a true no-ACK listen:

  sudo ip link set {channel} down
  sudo ip link set {channel} type can bitrate 500000 listen-only on
  sudo ip link set {channel} up
"""


def _parse_did(text: str) -> int:
    return int(text, 16)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="psa82", description="PSA 82 kWh bench worker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_channel(cmd, replay: bool = False, timed: bool = False) -> None:
        cmd.add_argument("--channel", default="vcan0", help="SocketCAN interface (default vcan0)")
        if replay:
            cmd.add_argument("--replay", help="SavvyCAN CSV or candump file. No socket is opened.")
        if timed:
            cmd.add_argument("--seconds", type=float, default=10.0, help="How long to listen")

    listen = sub.add_parser("listen", help="Decode broadcast frames. Never transmits.")
    add_channel(listen, replay=True, timed=True)

    poll = sub.add_parser("poll", help="One extended-session pass of ReadDataByIdentifier. No routines.")
    add_channel(poll)
    poll.add_argument("--enable-tx", action="store_true")
    poll.add_argument("--did", action="append", type=_parse_did, dest="dids")

    read = sub.add_parser("read-dtc", help="Manual 19 02. Not part of polling.")
    add_channel(read)
    read.add_argument("--enable-tx", action="store_true")
    read.add_argument("--mask", type=_parse_did, default=0x26)

    clear = sub.add_parser("clear-dtc", help="14 FF FF FF, only with --confirm CLEAR-DTC.")
    add_channel(clear)
    clear.add_argument("--enable-tx", action="store_true")
    clear.add_argument("--confirm", default=None)
    clear.add_argument("--mask", type=_parse_did, default=0x26)

    routine = sub.add_parser("routine", help="Run one verified reset routine.")
    add_channel(routine)
    routine.add_argument("name", choices=sorted(ROUTINES))
    routine.add_argument("--enable-tx", action="store_true")
    routine.add_argument("--confirm", default=None)
    routine.add_argument("--prelude-s", type=float, default=6.0)
    routine.add_argument("--period-s", type=float, default=0.065)

    sub.add_parser("routines", help="List routines and the blocked write. Sends nothing.")
    return parser


def _print_routines() -> None:
    print("Verified routines (sent only with --enable-tx and the confirm token):")
    seen = set()
    for name in sorted(ROUTINES):
        item = ROUTINES[name]
        if item.rid in seen and name in ("collision", "braker"):
            print(f"  {name:14} alias of RID {item.rid:04X}  confirm {item.confirm}")
            continue
        seen.add(item.rid)
        print(f"  {name:14} RID {item.rid:04X}  confirm {item.confirm}")
        print(f"                 {item.summary}")
    print(f"  clear-dtc      14 FF FF FF   confirm {CLEAR_DTC_CONFIRM}")
    print("Blocked: service 0x2E (WriteDataByIdentifier), including 2E D900 01.")
    print("Order: 10 01, 10 03, 22 D866/D802, 10 03, 31 01, 31 03 until 02, 10 01.")
    print("Automatic poll services: 0x10, 0x3E, 0x22. Manual: 0x19.")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "routines":
        _print_routines()
        return 0

    if args.command == "listen" and args.replay:
        worker = Worker(transport=None, tx_enabled=False)
        state = worker.listen(replay_path=args.replay)
        print(state.summary())
        return 0

    tx = bool(getattr(args, "enable_tx", False))
    if args.command != "listen" and not tx:
        print("TX is disabled. Re-run with --enable-tx. Nothing was sent.", file=sys.stderr)
        return 2
    try:
        if args.command == "routine":
            require_tx(tx, args.confirm, ROUTINES[args.name].confirm)
        elif args.command == "clear-dtc":
            require_tx(tx, args.confirm, CLEAR_DTC_CONFIRM)
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(LISTEN_ONLY_HINT.format(channel=args.channel).strip())
    if tx:
        print(f"TX enabled on {args.channel}.")
    transport = SocketCanTransport(args.channel, tx_enabled=tx)
    transport.open()
    worker = Worker(transport, tx_enabled=tx)
    try:
        if args.command == "listen":
            state = worker.run_listen_socket(args.seconds)
            print(state.summary())
            return 0
        if args.command == "poll":
            dids = tuple(args.dids) if args.dids else DEFAULT_POLL_DIDS
            unknown = [f"{did:04X}" for did in dids if did not in DEFAULT_POLL_DIDS | set(OPTIONAL_READ_DIDS)]
            if unknown:
                print("extra DIDs (still service 0x22 reads): " + ", ".join(unknown))
            for line in worker.poll_once(dids):
                print(line)
            return 0
        if args.command == "read-dtc":
            print(worker.read_dtc(args.mask).text())
            return 0
        if args.command == "clear-dtc":
            print(worker.clear_dtc(args.confirm).text())
            return 0
        if args.command == "routine":
            routine = ROUTINES[args.name]
            print(
                f"Routine {routine.name} RID {routine.rid:04X}. "
                f"Prelude {args.prelude_s:.2f}s of D866/D802 every {args.period_s * 1000:.0f} ms, "
                "then 31 01 / 31 03, then 10 01."
            )
            print(worker.run_routine(
                routine,
                args.confirm,
                prelude_s=args.prelude_s,
                period_s=args.period_s,
            ).text())
            return 0
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        transport.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
