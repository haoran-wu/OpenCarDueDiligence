"""Deterministic selection of the current target-listing snapshot.

``is_target`` identifies snapshots for the vehicle being evaluated, not a
single mutable row.  Multiple target snapshots are therefore valid history.
Consumers that need the current observation must consistently choose the
latest ``captured_at`` value and use ``id`` as the deterministic tie-breaker.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from .models import ListingSnapshot


def _captured_at_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def latest_target_listing(
    listings: Sequence[ListingSnapshot],
    *,
    fallback_to_latest: bool = False,
) -> ListingSnapshot | None:
    """Return the current target without discarding older snapshots.

    ``fallback_to_latest`` preserves the historical valuation/comparison
    behavior for imported cases that have no explicit target marker, while
    still replacing the old order-dependent ``listings[0]`` fallback.
    """

    targets = [item for item in listings if item.is_target]
    candidates = targets or (list(listings) if fallback_to_latest else [])
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (_captured_at_utc(item.captured_at), item.id),
    )
