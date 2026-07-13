"""User-refreshed listing history; no background scraping is performed."""

from __future__ import annotations

from collections import defaultdict

from ..models import (
    CaseContext,
    ListingPriceObservation,
    ListingWatchItem,
    ListingWatchlistResponse,
)


def build_watchlist(case: CaseContext) -> ListingWatchlistResponse:
    groups: dict[str, list] = defaultdict(list)
    for listing in case.listings:
        if listing.source_url:
            key = f"url:{listing.source_url}"
        elif listing.vin:
            key = f"vin:{listing.vin}"
        else:
            # Without a stable URL or VIN, do not merge two visually similar
            # listings and invent a price change.
            key = f"snapshot:{listing.id}"
        groups[key].append(listing)

    items: list[ListingWatchItem] = []
    for key, listings in groups.items():
        ordered = sorted(listings, key=lambda item: (item.captured_at, item.id))
        first, latest = ordered[0], ordered[-1]
        absolute_change = round(latest.asking_price - first.asking_price, 2)
        percent_change = (
            round(absolute_change / first.asking_price * 100, 2)
            if first.asking_price > 0
            else None
        )
        items.append(
            ListingWatchItem(
                key=key,
                title=latest.title,
                source_url=latest.source_url,
                channel=latest.channel,
                observations=[
                    ListingPriceObservation(
                        listing_id=listing.id,
                        asking_price=listing.asking_price,
                        captured_at=listing.captured_at,
                        evidence_id=listing.evidence_id,
                    )
                    for listing in ordered
                ],
                latest_price=latest.asking_price,
                absolute_change=absolute_change,
                percent_change=percent_change,
            )
        )
    items.sort(key=lambda item: (len(item.observations), item.key), reverse=True)
    return ListingWatchlistResponse(case_id=case.id, items=items)
