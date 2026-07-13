from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def test_user_refreshed_listing_snapshots_preserve_price_change(client: TestClient) -> None:
    case_id = client.post("/v1/cases", json={"language": "en"}).json()["id"]
    now = datetime.now(timezone.utc)
    base = {
        "title": "2014 MINI Cooper S",
        "sourceUrl": "https://example.test/listing/123",
        "channel": "facebook_marketplace",
        "isTarget": True,
    }
    for price, captured in ((6000, now - timedelta(days=2)), (5500, now)):
        response = client.post(
            f"/v1/cases/{case_id}/listings/import",
            json={"listings": [{**base, "askingPrice": price, "capturedAt": captured.isoformat()}]},
        )
        assert response.status_code == 201, response.text

    response = client.get(f"/v1/cases/{case_id}/listings/history")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert [row["askingPrice"] for row in item["observations"]] == [6000, 5500]
    assert item["absoluteChange"] == -500
    assert item["percentChange"] == -8.33


def test_unstable_listing_identity_never_invents_price_history(client: TestClient) -> None:
    case_id = client.post("/v1/cases", json={"language": "en"}).json()["id"]
    response = client.post(
        f"/v1/cases/{case_id}/listings/import",
        json={
            "listings": [
                {"title": "Similar listing", "askingPrice": 5000},
                {"title": "Similar listing", "askingPrice": 4500},
            ]
        },
    )
    assert response.status_code == 201
    history = client.get(f"/v1/cases/{case_id}/listings/history").json()
    assert len(history["items"]) == 2
    assert all(len(item["observations"]) == 1 for item in history["items"])
