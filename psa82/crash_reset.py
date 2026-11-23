"""Guarded DF60 sequence. Sends nothing unless ``confirm`` is true."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from psa82.crash_guard import assert_crash_test_payload, baseline_reads, df60_payloads
from psa82.dids import decode_did
from psa82.uds import UdsClient, UdsNegativeResponse, UdsTimeout, parse_read_dtc, routine_status


@dataclass
class Trace:
    events: list[dict] = field(default_factory=list)

    def add(self, kind: str, **payload) -> None:
        self.events.append({"kind": kind, **payload})

    def text(self) -> str:
        lines = []
        for event in self.events:
            kind = event["kind"]
            if kind in ("tx", "rx"):
                lines.append(f"{kind.upper()} {event.get('hex', '')} {event.get('note', '')}".rstrip())
            else:
                lines.append(f"{kind}: {event.get('note', event)}")
        return "\n".join(lines) + "\n"

    def write(self, directory: Path, stem: str) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        text_path = directory / f"{stem}.txt"
        json_path = directory / f"{stem}.json"
        text_path.write_text(self.text(), encoding="utf-8")
        json_path.write_text(json.dumps(self.events, indent=2), encoding="utf-8")
        return text_path, json_path


def _request(client: UdsClient, payload: bytes, trace: Trace) -> bytes:
    assert_crash_test_payload(payload)
    trace.add("tx", hex=payload.hex())
    try:
        response = client.request(payload)
    except UdsNegativeResponse as exc:
        trace.add("nrc", hex=f"7f{exc.service:02x}{exc.nrc:02x}", note=str(exc))
        raise
    trace.add("rx", hex=response.hex(), note=_note(payload, response))
    return response


def _note(request: bytes, response: bytes) -> str:
    if request[0] == 0x22 and len(response) >= 3 and response[0] == 0x62:
        did = (request[1] << 8) | request[2]
        return decode_did(did, response[3:])
    if request[0] == 0x19 and response[:2] == b"\x59\x02":
        _mask, records = parse_read_dtc(response)
        return " ".join(f"{rec.code}/{rec.status:02X}" for rec in records) or "no DTCs"
    if request[0] == 0x31:
        status = routine_status(response)
        return f"routine status={status:02X}" if status is not None else response.hex()
    return ""


def read_baseline(client: UdsClient, trace: Trace, *, label: str) -> None:
    trace.add("phase", note=label)
    for payload in baseline_reads():
        try:
            _request(client, payload, trace)
        except UdsTimeout as exc:
            trace.add("timeout", note=f"{label} {payload.hex()} {exc}")
            raise


def run_df60(
    client: UdsClient,
    trace: Trace,
    *,
    prelude_s: float,
    period_s: float,
    clear_after: bool,
    sleeper,
) -> None:
    reads = 0
    if prelude_s > 0:
        if period_s <= 0:
            raise ValueError("period_s must be positive")
        reads = int(round(prelude_s / period_s))
    trace.add(
        "phase",
        note=(
            "DF60 order: 10 01, 10 03, D866/D802, 10 03, 31 01 DF60, "
            "31 03 until 02, "
            + ("14 FF FF FF, " if clear_after else "")
            + "10 01"
        ),
    )
    payloads = df60_payloads(reads, clear_after=clear_after)
    read_index = 0
    for payload in payloads:
        if payload[0] == 0x22 and payload[1:3] in (b"\xd8\x66", b"\xd8\x02"):
            _request(client, payload, trace)
            read_index += 1
            if read_index <= reads:
                sleeper(period_s)
            continue
        if payload == bytes((0x31, 0x03, 0xDF, 0x60)):
            _poll_results(client, trace, sleeper)
            continue
        _request(client, payload, trace)


def _poll_results(client: UdsClient, trace: Trace, sleeper, period_s: float = 0.07, timeout_s: float = 3.0) -> None:
    payload = bytes((0x31, 0x03, 0xDF, 0x60))
    polls = int(timeout_s / period_s) + 1
    for _ in range(polls):
        response = _request(client, payload, trace)
        status = routine_status(response)
        if status is None or status != 0x01:
            return
        sleeper(period_s)
    trace.add("phase", note="DF60 results still 01 when the poll window ended")


def run_guarded(
    client: UdsClient,
    *,
    confirm: bool,
    clear_after: bool,
    prelude_s: float,
    period_s: float,
    sleeper,
    reread: bool,
) -> Trace:
    trace = Trace()
    if not confirm:
        trace.add("phase", note="dry run: --confirm-tx was not passed, nothing was sent")
        return trace
    read_baseline(client, trace, label="baseline")
    run_df60(
        client,
        trace,
        prelude_s=prelude_s,
        period_s=period_s,
        clear_after=clear_after,
        sleeper=sleeper,
    )
    if reread:
        read_baseline(client, trace, label="after-wake")
    return trace


def write_trace(trace: Trace, directory: str | Path, stem: str) -> tuple[Path, Path]:
    return trace.write(Path(directory), stem)
