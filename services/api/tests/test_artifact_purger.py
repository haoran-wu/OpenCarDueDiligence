from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.artifact_purger import (
    SDK_LOGGER_NAMES,
    enforce_sdk_log_floor,
    heartbeat_is_fresh,
    purge_once,
)


class FakeStore:
    def __init__(self, removed: int) -> None:
        self.removed = removed
        self.seen_now: datetime | None = None

    def purge_expired(self, now: datetime) -> int:
        self.seen_now = now
        return self.removed


def test_independent_purge_pass_deletes_and_updates_heartbeat(tmp_path: Path) -> None:
    store = FakeStore(3)
    heartbeat = tmp_path / "purger" / "heartbeat"
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)

    assert purge_once(store, heartbeat_path=heartbeat, now=now) == 3  # type: ignore[arg-type]
    assert store.seen_now == now
    assert heartbeat.is_file()


def test_purger_healthcheck_requires_a_fresh_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    os.utime(heartbeat, (100.0, 100.0))

    assert heartbeat_is_fresh(heartbeat, max_age_seconds=60, now=159.0)
    assert not heartbeat_is_fresh(heartbeat, max_age_seconds=60, now=161.0)
    assert not heartbeat_is_fresh(tmp_path / "missing", max_age_seconds=60, now=100.0)


def test_purger_forces_s3_sdk_loggers_to_warning_or_higher() -> None:
    for name in SDK_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.DEBUG)
    logging.getLogger("botocore").setLevel(logging.ERROR)

    enforce_sdk_log_floor()

    assert logging.getLogger("boto3").level == logging.WARNING
    assert logging.getLogger("s3transfer").level == logging.WARNING
    assert logging.getLogger("botocore").level == logging.ERROR
