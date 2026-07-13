import asyncio

import pytest
from fastapi.testclient import TestClient

import obd_bridge.service as service
from obd_bridge.safety import UnsafeCommandError
from obd_bridge.service import app
from obd_bridge.transport import MockElmTransport


client = TestClient(app)
TEST_TOKEN = "unit-test-local-bridge-token"


@pytest.fixture(autouse=True)
def configured_bridge_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "TOKEN", TEST_TOKEN)


def test_mock_scan_is_read_only_and_reports_coverage() -> None:
    response = client.post(
        "/v1/scan",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "mock_responses": {
                "ATI": "ELM327 v1.5\r>",
                "0101": "41 01 00 07 65 04\r>",
                "03": "43 03 01 00 00\r>",
                "07": "NO DATA\r>",
                "0A": "NO DATA\r>",
                "0902": "NO DATA\r>",
                "0105": "41 05 7B\r>",
                "010C": "41 0C 1A F8\r>",
                "0142": "41 42 36 B0\r>",
                "020500": "42 05 00 6E\r>",
                "020C00": "42 0C 00 0B B8\r>",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["codes"] == [{"code": "P0301", "status": "stored"}]
    assert body["module_coverage"] == ["generic_powertrain_emissions"]
    assert body["live_pids"] == {
        "engine_coolant_temperature_c": 83,
        "engine_rpm": 1726.0,
        "control_module_voltage_v": 14.0,
    }
    assert body["freeze_frame"] == {
        "engine_coolant_temperature_c": 70,
        "engine_rpm": 750.0,
    }
    assert any("ABS" in limitation for limitation in body["limitations"])


def test_bridge_requires_token() -> None:
    assert client.post("/v1/scan", json={"mock_responses": {}}).status_code == 401


def test_scan_transport_never_receives_mode_04_or_unreviewed_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[str] = []

    class RecordingMockTransport(MockElmTransport):
        async def query(self, command: str) -> str:
            observed.append(command.replace(" ", "").upper())
            return await super().query(command)

    monkeypatch.setattr(service, "MockElmTransport", RecordingMockTransport)
    response = client.post(
        "/v1/scan",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"mock_responses": {}},
    )
    assert response.status_code == 200
    assert observed
    assert "04" not in observed
    assert all(not command.startswith("04") for command in observed)

    transport = RecordingMockTransport({})
    with pytest.raises(UnsafeCommandError):
        asyncio.run(transport.query("04"))


def test_bridge_fails_closed_when_token_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "TOKEN", None)

    response = client.post(
        "/v1/scan",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"mock_responses": {}},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "OCDD_OBD_BRIDGE_TOKEN is not configured"
