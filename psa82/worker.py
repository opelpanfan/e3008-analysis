"""Bench worker. Listen-only until TX is enabled and a token is presented."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from psa82.actions import (
    CLEAR_DTC_CONFIRM,
    Routine,
    Step,
    TxNotEnabled,
    assert_payload_allowed,
    clear_dtc_steps,
    read_dtc_steps,
    require_tx,
    routine_steps,
)
from psa82.csvlog import iter_log
from psa82.dids import DEFAULT_POLL_DIDS, decode_did
from psa82.telemetry import PackTelemetry, apply_frame
from psa82.actions import ROUTINE_DONE, ROUTINE_RUNNING
from psa82.uds import UdsClient, UdsNegativeResponse, UdsTimeout, parse_read_dtc, routine_status


@dataclass
class ActionResult:
    name: str
    responses: list[bytes] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dtcs_before: list[str] = field(default_factory=list)
    dtcs_after: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [self.name, *self.notes]
        if self.dtcs_before:
            lines.append("DTC before: " + ", ".join(self.dtcs_before))
        if self.dtcs_after:
            lines.append("DTC after: " + ", ".join(self.dtcs_after))
        return "\n".join(lines)


class Worker:
    def __init__(self, transport, tx_enabled: bool = False, sleeper=None) -> None:
        self.transport = transport
        self.tx_enabled = tx_enabled
        self.telemetry = PackTelemetry()
        self.uds = UdsClient(transport)
        self.uds.on_other = lambda cid, data: apply_frame(self.telemetry, cid, data)
        self.sleep = sleeper if sleeper is not None else time.sleep
        self._results_poll_s = 0.07
        self._results_timeout_s = 3.0

    def ingest(self, can_id: int, data: bytes) -> None:
        apply_frame(self.telemetry, can_id, data)

    def listen(self, frames=None, replay_path: str | None = None) -> PackTelemetry:
        """Decode frames. Does not transmit."""
        if frames is None and replay_path is not None:
            frames = iter_log(replay_path)
        if frames is None:
            if not hasattr(self.transport, "recv"):
                return self.telemetry
            while True:
                msg = self.transport.recv(0.5)
                if msg is None:
                    break
                self.ingest(*msg)
            return self.telemetry
        for can_id, data in frames:
            self.ingest(can_id, data)
        return self.telemetry

    def run_listen_socket(self, seconds: float) -> PackTelemetry:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            msg = self.transport.recv(0.2)
            if msg is not None:
                self.ingest(*msg)
        return self.telemetry

    def _exchange(self, payload: bytes, context: str) -> bytes:
        if not self.tx_enabled:
            raise TxNotEnabled("TX is disabled")
        assert_payload_allowed(payload, context=context)
        return self.uds.request(payload)

    def poll_once(self, dids: tuple[int, ...] = DEFAULT_POLL_DIDS) -> list[str]:
        """One extended-session pass of ReadDataByIdentifier. Requires TX."""
        if not self.tx_enabled:
            raise TxNotEnabled(
                "poll transmits 10 03 / 22 / 3E / 10 01. Pass --enable-tx. It does not run routines."
            )
        lines: list[str] = []
        self._exchange(bytes((0x10, 0x03)), "poll")
        self._exchange(bytes((0x3E, 0x00)), "poll")
        try:
            for did in dids:
                payload = bytes((0x22, (did >> 8) & 0xFF, did & 0xFF))
                try:
                    response = self._exchange(payload, "poll")
                except UdsNegativeResponse as exc:
                    lines.append(f"{did:04X} {exc}")
                    continue
                if len(response) >= 3 and response[0] == 0x62:
                    lines.append(decode_did(did, response[3:]))
                else:
                    lines.append(f"{did:04X} raw={response.hex()}")
        finally:
            try:
                self._exchange(bytes((0x10, 0x01)), "poll")
            except (UdsTimeout, UdsNegativeResponse) as exc:
                lines.append(f"return to default session failed: {exc}")
        return lines

    def read_dtc(self, mask: int = 0x26) -> ActionResult:
        if not self.tx_enabled:
            raise TxNotEnabled("read-dtc transmits 19 02. Pass --enable-tx.")
        result = ActionResult("read-dtc")
        for step in read_dtc_steps(mask):
            response = self._exchange(step.payload, "read_dtc")
            result.responses.append(response)
            _record_dtcs(result, response, which="before")
        return result

    def clear_dtc(self, confirm: str | None) -> ActionResult:
        require_tx(self.tx_enabled, confirm, CLEAR_DTC_CONFIRM)
        result = ActionResult("clear-dtc")
        for index, step in enumerate(clear_dtc_steps()):
            response = self._exchange(step.payload, "clear")
            result.responses.append(response)
            if step.payload[0] == 0x19:
                which = "before" if index == 0 else "after"
                _record_dtcs(result, response, which=which)
            elif step.payload[0] == 0x14:
                result.notes.append(f"clear response {response.hex()}")
        return result

    def run_routine(
        self,
        routine: Routine,
        confirm: str | None,
        *,
        prelude_s: float = 6.0,
        period_s: float = 0.065,
    ) -> ActionResult:
        require_tx(self.tx_enabled, confirm, routine.confirm)
        result = ActionResult(routine.name)
        result.notes.append(routine.summary)
        steps = routine_steps(routine, prelude_s=prelude_s, period_s=period_s)
        try:
            self._run_steps(steps, result)
        except UdsTimeout as exc:
            result.notes.append(
                f"stopped: {exc}. A Fiat pack ignored 10 03 and 19 02 while charging with HV closed."
            )
        return result

    def _run_steps(self, steps: list[Step], result: ActionResult) -> None:
        for step in steps:
            if step.op == "wait":
                if step.delay_s:
                    self.sleep(step.delay_s)
                continue
            if step.op == "poll_results":
                self._poll_results(step.payload, result)
                continue
            response = self._exchange(step.payload, step.context)
            result.responses.append(response)
            if step.payload[:2] == bytes((0x22, 0xD8)):
                did = (step.payload[1] << 8) | step.payload[2]
                if len(response) >= 3 and response[0] == 0x62:
                    result.notes.append(decode_did(did, response[3:]))

    def _poll_results(self, payload: bytes, result: ActionResult) -> None:
        deadline = time.monotonic() + self._results_timeout_s
        # Tests inject a sleeper and a monotonic clock still advances only with
        # real time. Bound the polls by count as well so a fast sleeper cannot
        # spin, and a slow ECU is still covered for the observed ~0.8 s.
        polls = int(self._results_timeout_s / self._results_poll_s) + 1
        for _ in range(polls):
            try:
                response = self._exchange(payload, "routine")
            except UdsNegativeResponse as exc:
                result.notes.append(f"results request rejected: {exc}")
                return
            result.responses.append(response)
            status = routine_status(response)
            if status is None:
                result.notes.append(f"results response had no status byte: {response.hex()}")
                return
            if status == ROUTINE_DONE:
                result.notes.append(f"routine finished status={status:02X}")
                return
            if status != ROUTINE_RUNNING:
                result.notes.append(f"routine status={status:02X} response={response.hex()}")
                return
            if time.monotonic() >= deadline:
                break
            self.sleep(self._results_poll_s)
        result.notes.append("routine results still 01 when the poll window ended")


def _record_dtcs(result: ActionResult, response: bytes, *, which: str) -> None:
    try:
        _mask, records = parse_read_dtc(response)
    except ValueError:
        result.notes.append(f"DTC response {response.hex()}")
        return
    rendered = [f"{rec.code} st={rec.status:02X}" for rec in records]
    if which == "before":
        result.dtcs_before = rendered
    else:
        result.dtcs_after = rendered
    result.notes.append(f"{which} {len(records)} DTC(s)")
