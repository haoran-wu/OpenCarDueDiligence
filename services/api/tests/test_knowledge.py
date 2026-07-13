from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.knowledge import KnowledgeManifest, KnowledgeRegistry
from app.main import create_app


def _claim() -> dict[str, object]:
    return {
        "id": "example-inspection-signal",
        "label": {"en": "Researched inspection signal", "zh": "经研究的检查信号"},
        "summary": {
            "en": "This fixture proves publication gating; it is not shipped data.",
            "zh": "该测试夹具仅验证发布闸门，并非随项目发布的数据。",
        },
        "symptoms": [{"en": "Example symptom", "zh": "示例症状"}],
        "associated_dtcs": ["P0301"],
        "stranding_or_safety_risk": {
            "en": "Inspection is required before drawing a conclusion.",
            "zh": "下结论前必须检查。",
        },
        "basic_obd_visibility": {
            "en": "A generic scanner may show a related powertrain code only.",
            "zh": "普通扫描器可能只能显示相关动力系统代码。",
        },
        "confirmation_tests": [{"en": "Independent test", "zh": "独立测试"}],
        "repair_scenarios": [
            {
                "level": "minimum",
                "description": {"en": "Minimum branch", "zh": "最小分支"},
            },
            {
                "level": "most_likely",
                "description": {"en": "Likely branch", "zh": "最可能分支"},
            },
            {
                "level": "worst_reasonable",
                "description": {"en": "Worst branch", "zh": "最坏合理分支"},
            },
        ],
        "evidence_grade": "A",
        "source_ids": ["source-one"],
        "reviewed_at": "2026-07-12",
    }


def _manifest(*, pack_status: str = "PUBLISHED", duplicate_pack: bool = False) -> dict[str, object]:
    pack: dict[str, object] = {
        "id": "mini-f56-b48-auto-fwd-2014",
        "publication_status": pack_status,
        "applicability": {
            "market": "US",
            "model_year_start": 2014,
            "model_year_end": 2014,
            "generations": ["F56"],
            "platforms": ["F56"],
            "engines": ["B48B20 2.0T"],
            "transmissions": ["Aisin 6-speed automatic"],
            "drivetrains": ["FWD"],
            "production_date_start": "2014-01-01",
            "production_date_end": "2014-12-31",
        },
        "claims": [_claim()],
        "sources": [
            {
                "id": "source-one",
                "title": "Test-only source",
                "publisher": "Test suite",
                "url_or_document_id": "fixture:source-one",
                "source_type": "test_fixture",
                "license_or_use_basis": "test-only",
                "retrieved_at": "2026-07-12",
                "supports_claim_ids": ["example-inspection-signal"],
            }
        ],
        "reviewed_at": "2026-07-12",
        "reviewer": "Test reviewer",
    }
    packs = [pack]
    if duplicate_pack:
        duplicate = json.loads(json.dumps(pack))
        duplicate["id"] = "mini-f56-b48-auto-fwd-2014-overlap"
        packs.append(duplicate)
    return {
        "schema_version": "1.0",
        "manifest_version": "test-only",
        "license": "test-only",
        "status": "test_fixture",
        "warning": "No real-world claim is contained in this fixture.",
        "governance": {},
        "placeholder_template": {},
        "families": [
            {
                "id": "mini-cooper-s",
                "make": "MINI",
                "model": "Cooper S",
                "vehicle_classes": ["passenger_car"],
                "generation_packs": [],
                "powertrain_packs": [],
                "applicability_packs": packs,
                "publication_status": "PUBLISHED",
            }
        ],
    }


def _vehicle(**updates: object) -> dict[str, object]:
    vehicle: dict[str, object] = {
        "year": 2014,
        "make": "MINI",
        "model": "Cooper S",
        "generation": "F56",
        "platform": "F56",
        "engine": "B48B20 2.0T",
        "transmission": "Aisin 6-speed automatic",
        "drivetrain": "FWD",
        "productionDate": "2014-08-15",
    }
    vehicle.update(updates)
    return vehicle


def _client_with_manifest(tmp_path: Path, manifest: dict[str, object]) -> TestClient:
    manifest_path = tmp_path / "knowledge.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    app = create_app(database_path=tmp_path / "knowledge.sqlite3", deployment_mode="local")
    app.state.knowledge_registry = KnowledgeRegistry.load(manifest_path)
    return TestClient(app)


def test_shipped_family_manifests_are_honest_drafts(client: TestClient) -> None:
    response = client.get("/v1/knowledge/families")
    assert response.status_code == 200
    body = response.json()
    assert len(body["families"]) == 20
    assert all(
        family["publicationStatus"] == "DRAFT"
        and family["packCount"] == 1
        and family["publishedPackCount"] == 0
        and family["publishedClaimCount"] == 0
        for family in body["families"]
    )


def test_scaffold_family_never_releases_claims(client: TestClient) -> None:
    response = client.post(
        "/v1/knowledge/resolve",
        json={
            "year": 2020,
            "make": "Toyota",
            "model": "Camry",
            "generation": "XV70",
            "platform": "GA-K",
            "engine": "A25A-FKS",
            "transmission": "UA80E",
            "drivetrain": "FWD",
            "productionDate": "2020-01-15",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["knowledgeStatus"] == "UNKNOWN"
    assert body["decision"] == "INSPECT"
    assert body["claims"] == []
    assert "toyota-camry" in body["candidateFamilyIds"]
    assert any("publication_status:DRAFT" in reason for reason in body["blockedReasons"])


def test_missing_applicability_fields_are_named(client: TestClient) -> None:
    response = client.post(
        "/v1/knowledge/resolve",
        json={"year": 2020, "make": "Toyota", "model": "Camry"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["knowledgeStatus"] == "UNKNOWN"
    assert set(body["missingFields"]) == {
        "generation",
        "platform",
        "engine",
        "transmission",
        "drivetrain",
        "productionDate",
    }
    assert body["claims"] == []


def test_exact_published_pack_is_the_only_path_to_claims(tmp_path: Path) -> None:
    with _client_with_manifest(tmp_path, _manifest()) as client:
        response = client.post("/v1/knowledge/resolve", json=_vehicle())
    assert response.status_code == 200
    body = response.json()
    assert body["knowledgeStatus"] == "RESOLVED"
    assert body["decision"] == "INSPECT"
    assert body["matchedPackIds"] == ["mini-f56-b48-auto-fwd-2014"]
    assert [claim["id"] for claim in body["claims"]] == ["example-inspection-signal"]


@pytest.mark.parametrize(
    ("field", "near_match"),
    [
        ("engine", "B48B20"),
        ("transmission", "Aisin automatic"),
        ("drivetrain", "AWD"),
        ("generation", "F55"),
        ("platform", "UKL2"),
        ("productionDate", "2015-01-01"),
        ("year", 2015),
    ],
)
def test_near_matches_never_release_claims(
    tmp_path: Path, field: str, near_match: object
) -> None:
    with _client_with_manifest(tmp_path, _manifest()) as client:
        response = client.post(
            "/v1/knowledge/resolve", json=_vehicle(**{field: near_match})
        )
    body = response.json()
    assert body["knowledgeStatus"] == "UNKNOWN"
    assert body["decision"] == "INSPECT"
    assert body["claims"] == []


def test_matching_draft_pack_never_releases_claims(tmp_path: Path) -> None:
    manifest = _manifest(pack_status="DRAFT")
    # Draft packs may hold work-in-progress claims, but they are never returned.
    with _client_with_manifest(tmp_path, manifest) as client:
        response = client.post("/v1/knowledge/resolve", json=_vehicle())
    body = response.json()
    assert body["knowledgeStatus"] == "UNKNOWN"
    assert body["claims"] == []
    assert any("publication_status:DRAFT" in item for item in body["blockedReasons"])


def test_overlapping_published_packs_fail_closed(tmp_path: Path) -> None:
    with _client_with_manifest(tmp_path, _manifest(duplicate_pack=True)) as client:
        response = client.post("/v1/knowledge/resolve", json=_vehicle())
    body = response.json()
    assert body["knowledgeStatus"] == "UNKNOWN"
    assert body["claims"] == []
    assert "multiple_published_packs_match; applicability_is_ambiguous" in body[
        "blockedReasons"
    ]


def test_published_pack_schema_rejects_wildcards() -> None:
    manifest = _manifest()
    manifest["families"][0]["applicability_packs"][0]["applicability"]["engines"] = ["*"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="wildcards"):
        KnowledgeManifest.model_validate(manifest)


def test_published_pack_schema_requires_source_provenance() -> None:
    manifest = _manifest()
    manifest["families"][0]["applicability_packs"][0]["sources"] = []  # type: ignore[index]
    with pytest.raises(ValidationError, match="claims and sources"):
        KnowledgeManifest.model_validate(manifest)
