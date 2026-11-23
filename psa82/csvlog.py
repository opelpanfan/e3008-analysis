"""Readers for SavvyCAN CSV logs and candump text."""

from __future__ import annotations

import csv
import re
from pathlib import Path

_CANDUMP = re.compile(
    r"\((?P<ts>[0-9.]+)\)\s+\S+\s+(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)"
)


def _data_bytes(row: dict, keys: tuple[str, ...]) -> bytes:
    out = bytearray()
    for key in keys:
        value = (row.get(key) or "").strip()
        if not value:
            break
        out.append(int(value, 16))
    return bytes(out)


def iter_savvycan(path: str | Path):
    """Yield (can_id, data) from a SavvyCAN CSV export.

    The LEN column is the ISO-TP significant length, not the CAN DLC. Data
    columns are the padded frame, so all present D1..D8 bytes are kept.
    """
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                can_id = int(row["ID"], 16)
            except (KeyError, TypeError, ValueError):
                continue
            data = _data_bytes(row, ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"))
            yield can_id, data


def iter_candump(path: str | Path):
    with open(path, errors="replace") as handle:
        for line in handle:
            match = _CANDUMP.search(line)
            if not match:
                continue
            can_id = int(match.group("id"), 16)
            data = bytes.fromhex(match.group("data"))
            yield can_id, data


def iter_log(path: str | Path):
    name = str(path).lower()
    if name.endswith(".csv"):
        yield from iter_savvycan(path)
    else:
        yield from iter_candump(path)
