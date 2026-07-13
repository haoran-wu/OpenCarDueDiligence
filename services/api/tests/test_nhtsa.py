from __future__ import annotations

import hashlib
import json

import httpx
from fastapi.testclient import TestClient

from app.providers.nhtsa import NhtsaProvider


VIN = "1TESTCAR000000001"


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_decode_vin_uses_official_vpic_and_returns_provenance(
    client: TestClient,
) -> None:
    upstream = {
        "Count": 1,
        "Message": "Results returned successfully",
        "Results": [
            {
                "VIN": VIN,
                "ErrorCode": "0",
                "ErrorText": "0 - VIN decoded clean. Check Digit (9th position) is correct",
                "ModelYear": "2014",
                "Make": "MINI",
                "Model": "Hardtop",
                "Trim": "",
                "Series": "Cooper S",
                "BodyClass": "Hatchback/Liftback/Notchback",
                "VehicleType": "PASSENGER CAR",
                "Manufacturer": "BMW AG",
                "EngineModel": "B48",
                "DisplacementL": "2.0",
                "EngineCylinders": "4",
                "EngineConfiguration": "In-Line",
                "FuelTypePrimary": "Gasoline",
                "TransmissionStyle": "Automatic",
                "TransmissionSpeeds": "6",
                "DriveType": "FWD/Front-Wheel Drive",
                "PlantCity": "OXFORD",
                "PlantCountry": "ENGLAND",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "vpic.nhtsa.dot.gov"
        assert request.url.path == f"/api/vehicles/DecodeVinValuesExtended/{VIN}"
        assert request.url.params["format"] == "json"
        assert request.url.params["modelyear"] == "2014"
        return httpx.Response(200, json=upstream)

    client.app.state.nhtsa_provider = NhtsaProvider(
        transport=httpx.MockTransport(handler)
    )
    response = client.post(
        "/v1/vehicles/decode-vin", json={"vin": VIN, "modelYear": 2014}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decodeValid"] is True
    assert body["vehicle"]["make"] == "MINI"
    assert body["vehicle"]["model"] == "Hardtop"
    assert body["vehicle"]["trim"] == "Cooper S"
    assert body["vehicle"]["engine"] == "B48 / 2.0L / 4 cylinders / In-Line"
    assert body["vehicle"]["fuelType"] == "gasoline"
    assert body["vehicle"]["generation"] is None
    assert body["vehicle"]["platform"] is None
    assert body["source"]["provider"] == "NHTSA vPIC"
    assert body["source"]["sourceUrl"].startswith(
        f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{VIN}"
    )
    assert body["source"]["contentSha256"] == _canonical_hash(upstream)
    assert body["source"]["observedAt"].endswith("Z")
    assert any("recall repair completion" in item for item in body["limitations"])


def test_decode_vin_rejects_invalid_vin_before_network(client: TestClient) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client.app.state.nhtsa_provider = NhtsaProvider(
        transport=httpx.MockTransport(handler)
    )
    response = client.post(
        "/v1/vehicles/decode-vin", json={"vin": "WMWXI7C59ET988028"}
    )

    assert response.status_code == 422
    assert called is False
    assert "cannot contain I, O, or Q" in response.json()["detail"]


def test_model_recall_signals_are_never_presented_as_vin_completion(
    client: TestClient,
) -> None:
    upstream = {
        "Count": 1,
        "message": "Results returned successfully",
        "results": [
            {
                "NHTSACampaignNumber": "23V337000",
                "Manufacturer": "BMW of North America, LLC",
                "Component": "STRUCTURE:BODY",
                "ReportReceivedDate": "08/05/2023",
                "Summary": "Sample official recall summary",
                "Consequence": "Sample official consequence",
                "Remedy": "Dealers will inspect and repair as necessary.",
                "Notes": "Owners may contact the manufacturer.",
                "parkIt": False,
                "parkOutSide": "false",
                "overTheAirUpdate": "No",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.nhtsa.gov"
        assert request.url.path == "/recalls/recallsByVehicle"
        assert request.url.params["modelYear"] == "2014"
        assert request.url.params["make"] == "MINI"
        assert request.url.params["model"] == "Cooper"
        return httpx.Response(200, json=upstream)

    client.app.state.nhtsa_provider = NhtsaProvider(
        transport=httpx.MockTransport(handler)
    )
    response = client.post(
        "/v1/vehicles/recall-signals",
        json={"modelYear": 2014, "make": "MINI", "model": "Cooper"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "MODEL_YEAR_MAKE_MODEL_SIGNAL"
    assert body["count"] == 1
    assert body["recalls"][0]["nhtsaCampaignNumber"] == "23V337000"
    assert body["vehicleSpecific"] is False
    assert body["vinCompletionVerified"] is False
    assert "does not prove" in body["disclaimer"]
    assert body["source"]["provider"] == "NHTSA Recalls"
    assert body["source"]["contentSha256"] == _canonical_hash(upstream)
    assert body["officialVinLookupUrl"] == "https://www.nhtsa.gov/recalls"


def test_empty_recall_result_remains_model_level_unknown(client: TestClient) -> None:
    upstream: dict[str, object] = {"Count": 0, "results": []}
    client.app.state.nhtsa_provider = NhtsaProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=upstream)
        )
    )

    response = client.post(
        "/v1/vehicles/recall-signals",
        json={"modelYear": 2014, "make": "MINI", "model": "Cooper"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["vehicleSpecific"] is False
    assert body["vinCompletionVerified"] is False
    assert "specific VIN" in body["disclaimer"]


def test_recall_signal_contract_rejects_a_vin_field(client: TestClient) -> None:
    """The model endpoint must not imply that it performed a VIN lookup."""

    response = client.post(
        "/v1/vehicles/recall-signals",
        json={
            "modelYear": 2014,
            "make": "MINI",
            "model": "Cooper",
            "vin": VIN,
        },
    )

    assert response.status_code == 422


def test_nhtsa_http_failure_is_not_replaced_with_unattributed_data(
    client: TestClient,
) -> None:
    client.app.state.nhtsa_provider = NhtsaProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"message": "unavailable"})
        )
    )

    response = client.post(
        "/v1/vehicles/recall-signals",
        json={"modelYear": 2014, "make": "MINI", "model": "Cooper"},
    )

    assert response.status_code == 502
    assert "official service" in response.json()["detail"]


def test_nhtsa_timeout_is_reported_as_gateway_timeout(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client.app.state.nhtsa_provider = NhtsaProvider(
        transport=httpx.MockTransport(handler)
    )

    response = client.post("/v1/vehicles/decode-vin", json={"vin": VIN})

    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]
