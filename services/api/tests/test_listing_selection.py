from __future__ import annotations

from datetime import datetime, timezone

from app.listing_selection import latest_target_listing
from app.models import ListingSnapshot


def _snapshot(
    *, listing_id: str, captured_at: datetime, target: bool = True
) -> ListingSnapshot:
    return ListingSnapshot(
        id=listing_id,
        title=listing_id,
        asking_price=5000,
        is_target=target,
        captured_at=captured_at,
        source_id=f"source-{listing_id}",
        evidence_id=f"evidence-{listing_id}",
        content_sha256="a" * 64,
    )


def test_latest_target_uses_capture_time_then_id_without_mutating_history() -> None:
    old = _snapshot(
        listing_id="old",
        captured_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    same_time_lower_id = _snapshot(
        listing_id="latest-a",
        captured_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    same_time_higher_id = _snapshot(
        listing_id="latest-z",
        captured_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    listings = [same_time_lower_id, old, same_time_higher_id]

    selected = latest_target_listing(listings)

    assert selected is same_time_higher_id
    assert listings == [same_time_lower_id, old, same_time_higher_id]
    assert all(item.is_target for item in listings)


def test_latest_fallback_is_opt_in_and_order_independent() -> None:
    old = _snapshot(
        listing_id="comparable-old",
        captured_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        target=False,
    )
    latest = _snapshot(
        listing_id="comparable-new",
        captured_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        target=False,
    )

    assert latest_target_listing([latest, old]) is None
    assert latest_target_listing([latest, old], fallback_to_latest=True) is latest
