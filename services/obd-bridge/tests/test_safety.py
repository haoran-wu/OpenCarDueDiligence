import pytest

from obd_bridge.safety import (
    FREEZE_FRAME_COMMANDS,
    LIVE_PID_COMMANDS,
    UnsafeCommandError,
    assert_read_only,
)


@pytest.mark.parametrize(
    "command",
    ["03", "07", "0A", "0101", "0902", "01 0C", "02 0C 00", "ATSP0"],
)
def test_read_commands_are_allowed(command: str) -> None:
    assert assert_read_only(command)


@pytest.mark.parametrize(
    "command",
    [
        "04",
        "14FFFF",
        "2E1234",
        "3101",
        "34AB",
        "AT SH 7E0",
        "DEADBEEF",
        "0106",  # Mode 01, but outside the reviewed PID subset
        "020601",  # Mode 02, unreviewed PID and frame
        "0904",  # Mode 09, but not the reviewed VIN request
    ],
)
def test_mutating_or_unknown_commands_are_blocked(command: str) -> None:
    with pytest.raises(UnsafeCommandError):
        assert_read_only(command)


def test_every_live_and_freeze_frame_command_is_allowlisted_and_never_mode_04() -> None:
    commands = (*LIVE_PID_COMMANDS, *FREEZE_FRAME_COMMANDS)
    assert commands
    assert all(assert_read_only(command) == command for command in commands)
    assert all(not command.startswith("04") for command in commands)
    with pytest.raises(UnsafeCommandError):
        assert_read_only("04")
