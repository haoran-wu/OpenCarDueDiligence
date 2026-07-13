"""Independent S3 transient-original purger.

This process deliberately does not import or depend on the FastAPI app. It can
therefore enforce object expiry while the API is restarting or unhealthy.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .artifact_store import S3ArtifactStore


logger = logging.getLogger("ocdd.artifact_purger")
DEFAULT_HEARTBEAT = "/tmp/ocdd-artifact-purger.heartbeat"
SDK_LOGGER_NAMES = ("boto3", "botocore", "s3transfer")


def enforce_sdk_log_floor() -> None:
    """Prevent object-store SDK debug/info logs from exposing request details."""

    for name in SDK_LOGGER_NAMES:
        dependency_logger = logging.getLogger(name)
        if dependency_logger.level == logging.NOTSET or dependency_logger.level < logging.WARNING:
            dependency_logger.setLevel(logging.WARNING)


enforce_sdk_log_floor()


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def store_from_environment() -> S3ArtifactStore:
    bucket = os.getenv("OCDD_S3_BUCKET")
    if not bucket:
        raise ValueError("OCDD_S3_BUCKET is required by the artifact purger")
    return S3ArtifactStore(
        bucket=bucket,
        prefix=os.getenv("OCDD_S3_PREFIX", "ocdd-transient"),
        endpoint_url=os.getenv("OCDD_S3_ENDPOINT_URL") or os.getenv("OCDD_S3_ENDPOINT"),
        region_name=os.getenv("OCDD_S3_REGION"),
    )


def purge_once(
    store: S3ArtifactStore,
    *,
    heartbeat_path: Path,
    now: datetime | None = None,
) -> int:
    removed = store.purge_expired(now or datetime.now(timezone.utc))
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.touch()
    return removed


def heartbeat_is_fresh(
    heartbeat_path: Path,
    *,
    max_age_seconds: int,
    now: float | None = None,
) -> bool:
    try:
        modified = heartbeat_path.stat().st_mtime
    except FileNotFoundError:
        return False
    current = time.time() if now is None else now
    return current - modified <= max_age_seconds


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="purge expired OCDD S3 originals")
    parser.add_argument("--once", action="store_true", help="run one purge pass and exit")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="exit successfully only when the independent purger heartbeat is fresh",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    interval = _positive_int("OCDD_ARTIFACT_PURGE_INTERVAL_SECONDS", 60)
    heartbeat_path = Path(os.getenv("OCDD_ARTIFACT_PURGER_HEARTBEAT", DEFAULT_HEARTBEAT))
    if args.healthcheck:
        max_age = _positive_int(
            "OCDD_ARTIFACT_PURGER_HEALTH_MAX_AGE_SECONDS",
            max(180, interval * 3),
        )
        return 0 if heartbeat_is_fresh(heartbeat_path, max_age_seconds=max_age) else 1

    try:
        store = store_from_environment()
    except Exception as exc:
        logger.error("artifact purger configuration failed (%s)", type(exc).__name__)
        return 1

    while True:
        started = time.monotonic()
        try:
            removed = purge_once(store, heartbeat_path=heartbeat_path)
        except Exception as exc:
            # Never log bucket keys, case identifiers, filenames, or provider
            # exception text. Exiting lets the container restart policy retry.
            logger.error("artifact purge pass failed (%s)", type(exc).__name__)
            return 1
        logger.info("artifact purge pass complete; removed=%d", removed)
        if args.once:
            return 0
        remaining = max(0.1, interval - (time.monotonic() - started))
        time.sleep(remaining)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("OCDD_LOG_LEVEL", "INFO"))
    sys.exit(main())
