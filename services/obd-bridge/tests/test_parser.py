import pytest

from obd_bridge.parser import (
    parse_dtc_response,
    parse_pid_responses,
    parse_pid_value,
    parse_vin_response,
    readiness_summary,
)


def test_parse_stored_dtc_response() -> None:
    assert parse_dtc_response("43 01 01 04 20 00 00\r>", 0x43) == ["P0101", "P0420"]


def test_readiness_does_not_call_unknown_ready() -> None:
    result = readiness_summary("41 01 82 07 65 04\r>")
    assert result["available"] is True
    assert result["mil_on"] is True
    assert result["dtc_count"] == 2
    assert "supported_mask" in result


def test_parse_multiframe_vin() -> None:
    response = (
        "49 02 01 31 54 45 53 54 43\r\n"
        "49 02 02 41 52 30 30 30 30\r\n"
        "49 02 03 30 30 30 30 31 00\r>"
    )
    assert parse_vin_response(response) == "1TESTCAR000000001"


@pytest.mark.parametrize(
    ("pid", "response", "key", "expected"),
    [
        (0x04, "41 04 80\r>", "calculated_engine_load_pct", 50.2),
        (0x05, "41 05 7B\r>", "engine_coolant_temperature_c", 83),
        (0x0B, "41 0B 64\r>", "intake_manifold_absolute_pressure_kpa", 100),
        (0x0C, "41 0C 1A F8\r>", "engine_rpm", 1726.0),
        (0x0D, "41 0D 58\r>", "vehicle_speed_kph", 88),
        (0x0F, "41 0F 50\r>", "intake_air_temperature_c", 40),
        (0x10, "41 10 01 F4\r>", "mass_air_flow_g_s", 5.0),
        (0x11, "41 11 40\r>", "absolute_throttle_position_pct", 25.1),
        (0x1F, "41 1F 01 2C\r>", "engine_run_time_seconds", 300),
        (0x42, "41 42 36 B0\r>", "control_module_voltage_v", 14.0),
    ],
)
def test_parse_reviewed_mode_01_live_pids(
    pid: int, response: str, key: str, expected: float | int
) -> None:
    assert parse_pid_value(response, mode=1, pid=pid) == (key, expected)


def test_parse_mode_02_freeze_frame_requires_matching_frame_number() -> None:
    assert parse_pid_value("42 05 00 6E\r>", mode=2, pid=0x05) == (
        "engine_coolant_temperature_c",
        70,
    )
    assert parse_pid_value("42 05 01 6E\r>", mode=2, pid=0x05) is None


def test_pid_parser_keeps_missing_short_and_negative_responses_unknown() -> None:
    assert parse_pid_value("NO DATA\r>", mode=1, pid=0x0C) is None
    assert parse_pid_value("41 0C 1A\r>", mode=1, pid=0x0C) is None
    assert parse_pid_value("7F 01 12\r>", mode=1, pid=0x0C) is None
    assert parse_pid_value("41 06 80\r>", mode=1, pid=0x06) is None


def test_parse_pid_response_maps_uses_wire_command_keys() -> None:
    raw = {
        "0105": "SEARCHING...\r41 05 78\r>",
        "010C": "41 0C 0F A0\r>",
        "020500": "42 05 00 64\r>",
        "020C00": "42 0C 00 0B B8\r>",
    }
    assert parse_pid_responses(raw, mode=1) == {
        "engine_coolant_temperature_c": 80,
        "engine_rpm": 1000.0,
    }
    assert parse_pid_responses(raw, mode=2) == {
        "engine_coolant_temperature_c": 60,
        "engine_rpm": 750.0,
    }
