from __future__ import annotations

import re


class UnsafeCommandError(ValueError):
    """Raised before any command that could mutate vehicle state is sent."""


_SAFE_AT = {
    "ATZ",  # adapter reset only; does not write to the vehicle
    "ATE0",
    "ATL0",
    "ATS0",
    "ATH0",
    "ATSP0",
    "ATDPN",
    "ATI",
}

# Keep the generic live-data surface deliberately small. These are standard
# SAE J1979 emissions PIDs with simple, deterministic decoders. Adding a PID is
# a reviewed code change rather than something a request can select at runtime.
LIVE_PID_IDS = (
    0x04,  # calculated engine load
    0x05,  # engine coolant temperature
    0x0B,  # intake manifold absolute pressure
    0x0C,  # engine speed
    0x0D,  # vehicle speed
    0x0F,  # intake air temperature
    0x10,  # mass air flow rate
    0x11,  # absolute throttle position
    0x1F,  # run time since engine start
    0x42,  # control module voltage
)
FREEZE_FRAME_NUMBER = 0
READINESS_COMMAND = "0101"
LIVE_PID_COMMANDS = tuple(f"01{pid:02X}" for pid in LIVE_PID_IDS)
FREEZE_FRAME_COMMANDS = tuple(
    f"02{pid:02X}{FREEZE_FRAME_NUMBER:02X}" for pid in LIVE_PID_IDS
)

# Exact OBD request whitelist. Mode 01/02 are read-only service families, but
# accepting every possible PID would undermine the bridge's reviewed surface.
_SAFE_OBD = {
    READINESS_COMMAND,
    *LIVE_PID_COMMANDS,
    *FREEZE_FRAME_COMMANDS,
    "03",  # stored emissions DTCs
    "07",  # pending emissions DTCs
    "0902",  # VIN
    "0A",  # permanent emissions DTCs
}

# Explicitly document families that must never reach a transport.
_BLOCKED_PREFIXES = (
    "04",  # clear emissions DTCs/readiness
    "08",  # control operation
    "10",  # diagnostic session control
    "11",  # ECU reset
    "14",  # clear diagnostic information (UDS)
    "27",  # security access
    "2E",  # write data by identifier
    "2F",  # input/output control
    "31",  # routine control
    "34",  # request download/programming
    "36",  # transfer data
    "37",  # transfer exit
    "3D",  # write memory
)


def normalize_command(command: str) -> str:
    return re.sub(r"\s+", "", command).upper()


def assert_read_only(command: str) -> str:
    normalized = normalize_command(command)
    if not normalized:
        raise UnsafeCommandError("Empty OBD command")
    if normalized.startswith(_BLOCKED_PREFIXES):
        raise UnsafeCommandError(f"Vehicle-mutating command is blocked: {normalized}")
    if normalized in _SAFE_AT or normalized in _SAFE_OBD:
        return normalized
    raise UnsafeCommandError(f"Command is outside the read-only allowlist: {normalized}")
