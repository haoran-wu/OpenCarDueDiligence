"""Database-backed exclusive leases for case-scoped destructive operations."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator
from uuid import uuid4

from .repository import CaseRepository


class CaseLeaseBusy(RuntimeError):
    """Another API worker currently owns the case mutation lease."""


@contextmanager
def exclusive_case_lease(
    repository: CaseRepository,
    case_id: str,
    *,
    ttl_seconds: float = 300,
    wait_seconds: float = 5,
    poll_seconds: float = 0.05,
) -> Iterator[str]:
    """Acquire a cross-worker case lease and release it by ownership token.

    The expiry recovers a lease from a crashed worker. The default TTL is well
    above the API's bounded document-worker timeout; deployments that increase
    that timeout must increase ``OCDD_CASE_LEASE_TTL_SECONDS`` as well.
    """

    if ttl_seconds <= 0:
        raise ValueError("case lease TTL must be positive")
    if wait_seconds < 0:
        raise ValueError("case lease wait cannot be negative")
    if poll_seconds <= 0:
        raise ValueError("case lease poll interval must be positive")
    token = uuid4().hex
    deadline = time.monotonic() + wait_seconds
    while True:
        now = datetime.now(timezone.utc)
        if repository.acquire_case_lease(
            case_id,
            token=token,
            expires_at=now + timedelta(seconds=ttl_seconds),
            now=now,
        ):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CaseLeaseBusy(f"case {case_id} is busy; retry the request")
        time.sleep(min(poll_seconds, remaining))
    try:
        yield token
    finally:
        repository.release_case_lease(case_id, token=token)
