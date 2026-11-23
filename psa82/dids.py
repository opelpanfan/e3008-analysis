"""DID catalogue and decoders.

Scales that the 23 Nov 2026 cp2b session showed to be wrong are not applied.
Raw bytes are what the worker reports for those identifiers.
"""

from __future__ import annotations

# Read by the tool before every successful routine. Both stayed 0x00 / 0x00000000.
PRECONDITION_DIDS = (0xD866, 0xD802)

# Default automatic poll. All of these are reads (0x22) observed or confirmed
# as status bytes. None of them are writes.
DEFAULT_POLL_DIDS = (
    0xD812,  # latch byte; 0x00 in Add more PIDS, 0x01 on an earlier bench
    0xD813,
    0xD814,
    0xD800,
    0xD802,
    0xD866,
    0xD45A,  # 0x03 healthy packs, 0x04 on the latched pack (operator)
    0xD86D,  # balancing flag, 0x00 -> 0x01 confirmed on a Fiat pack
)

# Known reads the operator can add with --did. Scales below are deliberately raw.
OPTIONAL_READ_DIDS = {
    0xD810: "SoC candidate from an earlier bench (uint16 / 512). Not in the attached logs.",
    0xD815: "Displayed as about half of D438 on cp2b (175.7 V vs 351.2 V). Not pack voltage.",
    0xD816: "Current DID. cp2b read 0.00 A while 0x3B4 and 0x214 did not.",
    0xD817: "Temperature-like DID. cp2b showed ~0.9 C at room temp. Left raw.",
    0xD438: "Cell-sum voltage DID. cp2b showed 351.2 V. Scale is not applied here.",
    0xD879: "Coolant temperature DID. cp2b showed 20.0 C. Scale is not applied here.",
    0xD87D: "Temperature-like DID. cp2b showed ~0.2 C at room temp. Left raw.",
    0xD877: "Temperature-like DID. cp2b showed ~0.6 C at room temp. Left raw.",
    0xD440: "Cell millivolts, uint16 big-endian, 108 live values plus zero padding.",
    0xF18B: "ECU manufacturing date, 3-byte BCD YY MM DD.",
    0xF18C: "ECU serial, ASCII.",
    0xD901: "Pack serial, ASCII.",
}

# 2E D9 00 01 put a pack into a factory mode and collapsed insulation readings.
# No WriteDataByIdentifier of any DID is implemented.
FORBIDDEN_WRITE_DID = 0xD900
FORBIDDEN_WRITE_PAYLOAD = bytes((0x2E, 0xD9, 0x00, 0x01))


def _ascii(data: bytes) -> str:
    text = data.split(b"\x00", 1)[0]
    if text and all(32 <= b < 127 for b in text):
        return text.decode("ascii")
    return ""


def decode_did(did: int, data: bytes) -> str:
    """Human-readable decode. Ambiguous physical scales stay as raw hex."""
    raw = data.hex()
    if did == 0xD86D and len(data) == 1:
        flag = "balancing active" if data[0] == 0x01 else "balancing inactive" if data[0] == 0x00 else "unlisted value"
        return f"D86D {flag} raw={data[0]:02X}"
    if did == 0xD45A and len(data) == 1:
        note = {0x03: "value seen on healthy packs", 0x04: "value reported on the latched pack"}.get(data[0], "unlisted value")
        return f"D45A {note} raw={data[0]:02X}"
    if did == 0xD812 and len(data) == 1:
        return f"D812 latch byte raw={data[0]:02X}"
    if did == 0xD810 and len(data) == 2:
        value = (data[0] << 8) | data[1]
        return f"D810 raw={raw} prior-bench SoC candidate={value / 512:.2f}% (unconfirmed on this corpus)"
    if did in (0xD817, 0xD87D, 0xD877, 0xD879, 0xD815, 0xD438, 0xD816):
        return f"{did:04X} raw={raw} (no physical scale; cp2b scalers disagreed with room temperature or with D816=0 A)"
    if did == 0xD440 and len(data) >= 2:
        words = [(data[i] << 8) | data[i + 1] for i in range(0, len(data) - 1, 2)]
        live = [w for w in words if w]
        return f"D440 cells={len(live)} of {len(words)} words, min={min(live) if live else 0} max={max(live) if live else 0} mV"
    if did == 0xD46F:
        return f"D46F {len(data)} bytes raw={raw} (not a 12-byte / 96-bit mask)"
    if did in (0xD901, 0xF18C):
        text = _ascii(data)
        return f"{did:04X} ascii={text!r} raw={raw}" if text else f"{did:04X} raw={raw}"
    if did == 0xF18B and len(data) == 3 and all(b <= 0x99 for b in data):
        return f"F18B BCD date=20{data[0]:02X}-{data[1]:02X}-{data[2]:02X}"
    if did == 0xD802:
        return f"D802 raw={raw}"
    if did == 0xD866 and len(data) == 1:
        return f"D866 raw={data[0]:02X}"
    return f"{did:04X} raw={raw}"
