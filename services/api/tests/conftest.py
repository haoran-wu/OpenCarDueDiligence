from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(database_path=tmp_path / "test.sqlite3", deployment_mode="local")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def cloud_client(tmp_path: Path) -> TestClient:
    app = create_app(database_path=tmp_path / "cloud.sqlite3", deployment_mode="cloud")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def account_cloud_client(tmp_path: Path) -> TestClient:
    # A real deployment may enable this only behind its authenticated account
    # layer. Tests opt in explicitly rather than weakening the public default.
    app = create_app(
        database_path=tmp_path / "account-cloud.sqlite3",
        deployment_mode="cloud",
        account_retention_enabled=True,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def resolved_vehicle() -> dict[str, object]:
    return {
        "vin": "1TESTCAR000000001",
        "year": 2014,
        "make": "MINI",
        "model": "Cooper S",
        "trim": "S",
        "generation": "F56",
        "platform": "F56",
        "engine": "B48 2.0T",
        "transmission": "Aisin 6-speed automatic",
        "drivetrain": "FWD",
        "productionDate": "2014-08-15",
        "fuelType": "gasoline",
        "odometerMiles": 120010,
    }
