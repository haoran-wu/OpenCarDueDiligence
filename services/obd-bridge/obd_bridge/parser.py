from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .safety import FREEZE_FRAME_NUMBER, LIVE_PID_IDS


PidScalar = float | int | str | bool | None


@dataclass(frozen=True)
class PidDefinition:
    key: str
    byte_count: int
    decode: Callable[[bytes], float | int]


PID_DEFINITIONS: dict[int, PidDefinition] = {
    0x04: PidDefinition("calculated_engine_load_pct", 1, lambda data: round(data[0] * 100 / 255, 1)),
    0x05: PidDefinition("engine_coolant_temperature_c", 1, lambda data: data[0] - 40),
    0x0B: PidDefinition("intake_manifold_absolute_pressure_kpa", 1, lambda data: data[0]),
    0x0C: PidDefinition("engine_rpm", 2, lambda data: round((data[0] * 256 + data[1]) / 4, 2)),
    0x0D: PidDefinition("vehicle_speed_kph", 1, lambda data: data[0]),
    0x0F: PidDefinition("intake_air_temperature_c", 1, lambda data: data[0] - 40),
    0x10: PidDefinition("mass_air_flow_g_s", 2, lambda data: round((data[0] * 256 + data[1]) / 100, 2)),
    0x11: PidDefinition("absolute_throttle_position_pct", 1, lambda data: round(data[0] * 100 / 255, 1)),
    0x1F: PidDefinition("engine_run_time_seconds", 2, lambda data: data[0] * 256 + data[1]),
    0x42: PidDefinition("control_module_voltage_v", 2, lambda data: round((data[0] * 256 + data[1]) / 1000, 3)),
}

if set(PID_DEFINITIONS) != set(LIVE_PID_IDS):  # fail closed during development/import
    raise RuntimeError("PID decoder table and read-only command allowlist differ")


def clean_hex(response: str) -> str:
    lines: list[str] = []
    for raw in response.replace(">", "").splitlines():
        line = raw.strip().upper()
        if not line or line.startswith(("SEARCHING", "BUS INIT")):
            continue
        if any(token in line for token in ("NO DATA", "STOPPED", "ERROR", "UNABLE TO CONNECT")):
            continue
        line = re.sub(r"[^0-9A-F]", "", line)
        if line:
            lines.append(line)
    return "".join(lines)


def _decode_dtc(first: int, second: int) -> str:
    prefix = "PCBU"[(first & 0xC0) >> 6]
    digit_1 = (first & 0x30) >> 4
    digit_2 = first & 0x0F
    digit_3 = (second & 0xF0) >> 4
    digit_4 = second & 0x0F
    return f"{prefix}{digit_1}{digit_2:X}{digit_3:X}{digit_4:X}"


def parse_dtc_response(response: str, positive_service: int) -> list[str]:
    payload = clean_hex(response)
    marker = f"{positive_service:02X}"
    marker_index = payload.find(marker)
    if marker_index < 0:
        return []
    data = payload[marker_index + 2 :]
    codes: list[str] = []
    for offset in range(0, len(data) - 3, 4):
        try:
            first = int(data[offset : offset + 2], 16)
            second = int(data[offset + 2 : offset + 4], 16)
        except ValueError:
            continue
        if first == 0 and second == 0:
            continue
        codes.append(_decode_dtc(first, second))
    return list(dict.fromkeys(codes))


def parse_vin_response(response: str) -> str | None:
    # Mode 09 PID 02 commonly repeats 49 02 and a frame index per line. Collect
    # the data bytes after each marker before decoding; then fall back to the
    # full payload for adapters that already reassemble ISO-TP frames.
    collected = bytearray()
    for raw_line in response.replace(">", "").splitlines():
        pairs = re.findall(r"\b[0-9A-Fa-f]{2}\b", raw_line)
        values = [int(pair, 16) for pair in pairs]
        for index in range(len(values) - 2):
            if values[index : index + 2] == [0x49, 0x02]:
                data_start = index + 2
                if data_start < len(values) and values[data_start] <= 0x20:
                    data_start += 1  # response/frame counter
                collected.extend(values[data_start:])
                break

    candidates = [bytes(collected)]
    payload = clean_hex(response)
    if payload:
        candidates.append(bytes.fromhex(payload))
    for raw_bytes in candidates:
        printable = "".join(chr(byte) if 32 <= byte <= 126 else " " for byte in raw_bytes)
        candidate = "".join(re.findall(r"[A-HJ-NPR-Z0-9]", printable))
        if len(candidate) >= 17:
            return candidate[:17]
    for candidate in re.findall(r"[A-HJ-NPR-Z0-9]{17}", response.upper()):
        return candidate
    return None


def readiness_summary(response: str) -> dict[str, str | int | bool]:
    payload = clean_hex(response)
    marker_index = payload.find("4101")
    if marker_index < 0 or len(payload) < marker_index + 12:
        return {"available": False, "raw": payload}
    a = int(payload[marker_index + 4 : marker_index + 6], 16)
    b = int(payload[marker_index + 6 : marker_index + 8], 16)
    c = int(payload[marker_index + 8 : marker_index + 10], 16)
    d = int(payload[marker_index + 10 : marker_index + 12], 16)
    mil_on = bool(a & 0x80)
    dtc_count = a & 0x7F
    compression_ignition = bool(b & 0x08)
    # C/D contain supported and incomplete bits. Keep raw masks so the API
    # never pretends an unsupported monitor was ready.
    return {
        "available": True,
        "mil_on": mil_on,
        "dtc_count": dtc_count,
        "compression_ignition": compression_ignition,
        "supported_mask": f"{b:02X}{c:02X}",
        "incomplete_mask": f"{d:02X}",
        "raw": payload,
    }


def parse_pid_value(
    response: str,
    *,
    mode: int,
    pid: int,
    frame_number: int = FREEZE_FRAME_NUMBER,
) -> tuple[str, float | int] | None:
    """Decode one reviewed generic OBD PID response.

    Mode 01 positive responses begin with ``41 <pid>``. Mode 02 responses begin
    with ``42 <pid> <frame>``. Missing, short, negative, or malformed responses
    stay absent instead of being converted into a reassuring default value.
    """

    definition = PID_DEFINITIONS.get(pid)
    if definition is None or mode not in (1, 2):
        return None

    payload = clean_hex(response)
    marker = f"{mode + 0x40:02X}{pid:02X}"
    if mode == 2:
        marker += f"{frame_number:02X}"
    marker_index = payload.find(marker)
    if marker_index < 0:
        return None

    data_hex = payload[marker_index + len(marker) :]
    required_hex = definition.byte_count * 2
    if len(data_hex) < required_hex:
        return None
    try:
        data = bytes.fromhex(data_hex[:required_hex])
        value = definition.decode(data)
    except (ValueError, IndexError, ZeroDivisionError):
        return None
    return definition.key, value


def parse_pid_responses(
    raw_responses: Mapping[str, str],
    *,
    mode: int,
    frame_number: int = FREEZE_FRAME_NUMBER,
) -> dict[str, PidScalar]:
    """Normalize only the fixed PID allowlist from a scan's raw responses."""

    parsed: dict[str, PidScalar] = {}
    for pid in LIVE_PID_IDS:
        command = f"01{pid:02X}" if mode == 1 else f"02{pid:02X}{frame_number:02X}"
        decoded = parse_pid_value(
            raw_responses.get(command, ""),
            mode=mode,
            pid=pid,
            frame_number=frame_number,
        )
        if decoded is not None:
            key, value = decoded
            parsed[key] = value
    return parsed
