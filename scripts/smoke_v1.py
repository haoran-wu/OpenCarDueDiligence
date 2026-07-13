#!/usr/bin/env python3
"""Deterministic OpenCarDueDiligence v1 end-to-end smoke.

This exercises the public FastAPI contract in-process: case creation, a listing
snapshot, generic OBD evidence, a PPI session, analysis/valuation, a traceable
negotiation draft, and both blocked and legal NJ-buyer/NY-title transport paths.
It does not require Redis, Docker, an LLM, paid data, or network access.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ["OCDD_DATA_ROOT"] = str(ROOT / "data")
# Keep the smoke deterministic after the 90-day rule-review window passes.
os.environ["OCDD_RULES_AS_OF"] = "2026-07-12"

from app.main import create_app  # noqa: E402


VEHICLE: dict[str, Any] = {
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
    "odometerMiles": 120_010,
}


def require(response: Any, expected: int, label: str) -> dict[str, Any]:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")
    body = response.json()
    if not isinstance(body, dict):
        raise AssertionError(f"{label}: expected a JSON object")
    return body


def comparable(index: int) -> dict[str, Any]:
    return {
        "title": f"2014 MINI Cooper S comparable {index + 1}",
        "askingPrice": 5_400 + index * 125,
        "mileage": 116_000 + index * 900,
        "location": "NY/NJ metro",
        "listedAt": f"2026-07-{index + 1:02d}T12:00:00Z",
        "sellerType": "private",
        "channel": "user_entry",
        "referenceKind": "asking",
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
        "bodyStyle": "hatchback",
        "distanceMiles": 20 + index * 8,
    }


def transaction_payload(transport_option: str) -> dict[str, Any]:
    return {
        "purchaseDate": "2026-07-12",
        "buyerResidenceState": "NJ",
        "licenseState": "NJ",
        "garagingState": "NJ",
        "registrationState": "NJ",
        "saleState": "NY",
        "titleState": "NY",
        "sellerType": "private",
        "titleStatus": "ORIGINAL",
        "lienStatus": "CLEAR",
        "identityTitleMatch": "MATCH",
        "vinMatch": "MATCH",
        "sellerAllowsPpi": True,
        "sellerAllowsBillOfSale": True,
        "sellerWillDiscloseOdometer": True,
        "insuranceActiveForVin": True,
        "transportOption": transport_option,
        "vehicle": VEHICLE,
        "currentInspectionStatus": "PASS",
        "currentEmissionsStatus": "PASS",
    }


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ocdd-smoke-") as temp_dir:
        app = create_app(database_path=Path(temp_dir) / "smoke.sqlite3", deployment_mode="local")
        with TestClient(app) as client:
            case = require(
                client.post(
                    "/v1/cases",
                    json={
                        "language": "zh-CN",
                        "buyerGoal": "Evidence-backed private-party purchase",
                        "allInBudget": 7_500,
                        "vehicle": VEHICLE,
                    },
                ),
                201,
                "create case",
            )
            case_id = case["id"]

            target = {
                "title": "2014 MINI Cooper S",
                "askingPrice": 6_000,
                "mileage": 120_010,
                "location": "Example City, NY",
                "sellerType": "private",
                "channel": "facebook_marketplace",
                "referenceKind": "asking",
                "vin": VEHICLE["vin"],
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
                "bodyStyle": "hatchback",
                "isTarget": True,
                "description": "User-captured visible listing snapshot",
            }
            listing = require(
                client.post(f"/v1/cases/{case_id}/listings/import", json={"listings": [target]}),
                201,
                "import listing",
            )
            assert listing["imported"] == 1

            scan = require(
                client.post(
                    f"/v1/cases/{case_id}/obd/scans",
                    json={
                        "scannerName": "ELM327 smoke fixture",
                        "vin": VEHICLE["vin"],
                        "milOn": False,
                        "dtcs": [{"code": "P0301", "status": "pending"}],
                        "readiness": [
                            {"name": "misfire", "status": "READY"},
                            {"name": "catalyst", "status": "READY"},
                        ],
                        "moduleCoverage": {
                            "powertrain": "SCANNED",
                            "abs": "NOT_SCANNED",
                            "srs": "NOT_SCANNED",
                            "body": "NOT_SCANNED",
                        },
                        "limitations": ["Generic emissions scan only"],
                    },
                ),
                201,
                "add OBD scan",
            )
            assert scan["moduleCoverage"]["abs"] == "NOT_SCANNED"

            ppi = require(
                client.post(
                    f"/v1/cases/{case_id}/inspections",
                    json={
                        "inspectionType": "ppi",
                        "inspector": "Independent shop smoke fixture",
                        "items": [
                            {
                                "key": "cooling_pressure_test",
                                "label": "Cooling-system pressure test",
                                "stage": "ppi",
                                "result": "PASS",
                                "notes": "No leak observed during this fixture",
                            }
                        ],
                    },
                ),
                201,
                "add PPI",
            )

            analysis = require(
                client.post(
                    f"/v1/cases/{case_id}/analyze",
                    json={"comparables": [comparable(index) for index in range(8)]},
                ),
                200,
                "analyze",
            )
            assert analysis["valuation"]["sampleCount"] == 8
            assert analysis["valuation"]["referenceKind"] == "asking_price_range"
            assert any(item["code"] == "DTC_P0301_pending" for item in analysis["findings"])
            assert any("ABS" in item for item in analysis["unknowns"])
            assert analysis["decision"] in {"INSPECT", "NEGOTIATE"}

            negotiation = require(
                client.post(
                    f"/v1/cases/{case_id}/negotiation/draft",
                    json={
                        "phase": "post_ppi",
                        "language": "zh-CN",
                        "askingPrice": 6_000,
                        "marketBaseline": analysis["valuation"]["weightedMedian"],
                        "allInBudget": 7_500,
                        # The endpoint must use the ledger's actual coverage;
                        # a smoke fixture may not inflate it to unlock a price.
                        "evidenceCoverage": analysis["coveragePercent"],
                        "buyerMandatoryCosts": 600,
                        "adjustments": [],
                    },
                ),
                200,
                "draft negotiation",
            )
            if analysis["coveragePercent"] < 40:
                assert negotiation["decision"] == "INSPECT_FIRST"
                assert negotiation["opening"] is None
                assert negotiation["ceiling"] is None
            else:
                assert negotiation["opening"] is not None
                assert negotiation["ceiling"] is not None
            assert any(item["label"] == "Evidence coverage reserve" for item in negotiation["trace"])

            illegal_plan = require(
                client.post(
                    f"/v1/cases/{case_id}/transaction-plan",
                    json=transaction_payload("seller_plate"),
                ),
                200,
                "seller-plate transaction gate",
            )
            assert illegal_plan["decision"] == "STOP"
            assert illegal_plan["canLegallyDriveAway"] is False
            assert next(gate for gate in illegal_plan["gates"] if gate["code"] == "legal_transport")["blocked"]

            legal_plan = require(
                client.post(
                    f"/v1/cases/{case_id}/transaction-plan",
                    json=transaction_payload("valid_temp_permit"),
                ),
                200,
                "legal NJ/NY transaction path",
            )
            # The route is generated, but the shipped official-source bundles
            # remain fail-closed until their named human signoff is recorded.
            assert legal_plan["decision"] == "INSPECT"
            assert legal_plan["canLegallyDriveAway"] is False
            assert not [gate for gate in legal_plan["gates"] if gate["blocked"]]

            persisted = require(client.get(f"/v1/cases/{case_id}"), 200, "read persisted case")
            return {
                "status": "ok",
                "caseId": case_id,
                "listingImported": listing["imported"],
                "obdFinding": "DTC_P0301_pending",
                "coveragePercent": analysis["coveragePercent"],
                "valuationSamples": analysis["valuation"]["sampleCount"],
                "negotiationDecision": negotiation["decision"],
                "illegalTransportDecision": illegal_plan["decision"],
                "legalTransportDecision": legal_plan["decision"],
                "persistedTransactionDecision": persisted["transactionPlan"]["decision"],
                "ppiEvidenceId": ppi["evidenceId"],
            }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
