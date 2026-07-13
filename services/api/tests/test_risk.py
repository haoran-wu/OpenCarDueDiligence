from __future__ import annotations

from datetime import date

from app.engines.risk import analyze_case, calculate_coverage
from app.models import (
    CaseContext,
    CaseStatus,
    Decision,
    DiagnosticScan,
    DtcEntry,
    DtcStatus,
    Evidence,
    EvidenceKind,
    InspectionItem,
    InspectionResult,
    InspectionSession,
    ModuleCoverage,
    ReadinessMonitor,
    ReadinessStatus,
    SourceEnvelope,
    VehicleSpec,
)


def _scan(*codes: str, readiness: list[ReadinessMonitor] | None = None) -> tuple[SourceEnvelope, Evidence, DiagnosticScan]:
    source = SourceEnvelope(source_type="obd_scan", content_sha256="a" * 64)
    evidence = Evidence(source_id=source.id, kind=EvidenceKind.OBD_SCAN, label="scan")
    scan = DiagnosticScan(
        source_id=source.id,
        evidence_id=evidence.id,
        dtcs=[DtcEntry(code=code, status=DtcStatus.PENDING) for code in codes],
        readiness=readiness or [],
    )
    return source, evidence, scan


def test_p0301_creates_diagnostic_branches_not_coil_replacement() -> None:
    source, evidence, scan = _scan("P0301")
    case = CaseContext(sources=[source], evidence=[evidence], scans=[scan])
    result = analyze_case(case)
    finding = next(item for item in result.findings if item.code.startswith("DTC_P0301"))
    assert len(finding.repair_scenarios) == 3
    assert {item.probability_label for item in finding.repair_scenarios} == {
        "minimum",
        "most_likely",
        "worst_reasonable",
    }
    assert "does not identify" in finding.detail
    assert "replace coil" not in finding.detail.lower()


def test_p0420_does_not_directly_condemn_catalyst() -> None:
    source, evidence, scan = _scan("P0420")
    result = analyze_case(CaseContext(sources=[source], evidence=[evidence], scans=[scan]))
    finding = next(item for item in result.findings if item.code.startswith("DTC_P0420"))
    assert "does not by itself prove" in finding.detail
    assert any("exhaust leaks" in check for check in finding.next_checks)


def test_not_ready_is_possible_reset_not_accusation() -> None:
    source, evidence, scan = _scan(
        readiness=[
            ReadinessMonitor(name="catalyst", status=ReadinessStatus.NOT_READY),
            ReadinessMonitor(name="evap", status=ReadinessStatus.NOT_READY),
        ]
    )
    result = analyze_case(CaseContext(sources=[source], evidence=[evidence], scans=[scan]))
    finding = next(item for item in result.findings if item.code.startswith("READINESS_NOT_READY"))
    assert "not proof" in finding.detail.lower()
    assert "weak/disconnected battery" in finding.detail


def test_exact_powertrain_coverage_requires_production_date() -> None:
    common = {
        "vin": "1TESTCAR000000001",
        "year": 2014,
        "make": "Example",
        "model": "Car",
        "generation": "G1",
        "platform": "P1",
        "engine": "2.0L",
        "transmission": "6AT",
        "drivetrain": "FWD",
        "fuel_type": "gasoline",
    }
    incomplete, incomplete_unknowns = calculate_coverage(
        CaseContext(vehicle=VehicleSpec(**common))
    )
    complete, complete_unknowns = calculate_coverage(
        CaseContext(
            vehicle=VehicleSpec(**common, production_date=date(2014, 8, 15))
        )
    )

    assert complete == incomplete + 10
    assert any("production date" in item for item in incomplete_unknowns)
    assert not any("production date" in item for item in complete_unknowns)


def test_unknown_placeholders_cannot_create_full_coverage_or_buy_candidate() -> None:
    vehicle = VehicleSpec(
        vin="1TESTCAR000000001",
        year=2014,
        make="Example",
        model="Car",
        generation="G1",
        platform="P1",
        engine="2.0L",
        transmission="6AT",
        drivetrain="FWD",
        production_date=date(2014, 8, 15),
    )
    sources: list[SourceEnvelope] = []
    evidence: list[Evidence] = []
    for kind in (
        EvidenceKind.TITLE,
        EvidenceKind.HISTORY_REPORT,
        EvidenceKind.RECEIPT,
    ):
        source = SourceEnvelope(source_type=kind.value, content_sha256="b" * 64)
        item = Evidence(source_id=source.id, kind=kind, label=f"{kind.value} placeholder")
        sources.append(source)
        evidence.append(item)

    scan_source, scan_evidence, scan = _scan(
        readiness=[ReadinessMonitor(name="catalyst", status=ReadinessStatus.READY)]
    )
    scan.vin = vehicle.vin
    scan.mil_on = False
    scan.module_coverage = {"powertrain": ModuleCoverage.SCANNED}
    sources.append(scan_source)
    evidence.append(scan_evidence)

    self_source = SourceEnvelope(source_type="self_inspection", content_sha256="c" * 64)
    self_evidence = Evidence(
        source_id=self_source.id,
        kind=EvidenceKind.SELF_INSPECTION,
        label="unknown self inspection",
    )
    ppi_source = SourceEnvelope(source_type="ppi", content_sha256="d" * 64)
    ppi_evidence = Evidence(
        source_id=ppi_source.id,
        kind=EvidenceKind.PPI,
        label="unknown PPI",
    )
    inspections = [
        InspectionSession(
            inspection_type="self",
            items=[
                InspectionItem(
                    key="vin_received",
                    label="VIN received",
                    stage="pre_visit",
                    result=InspectionResult.UNKNOWN,
                )
            ],
            source_id=self_source.id,
            evidence_id=self_evidence.id,
        ),
        InspectionSession(
            inspection_type="ppi",
            inspector="Example Shop",
            items=[
                InspectionItem(
                    key="structural_underbody",
                    label="Structure",
                    stage="ppi",
                    result=InspectionResult.UNKNOWN,
                )
            ],
            source_id=ppi_source.id,
            evidence_id=ppi_evidence.id,
        ),
    ]
    sources.extend([self_source, ppi_source])
    evidence.extend([self_evidence, ppi_evidence])
    case = CaseContext(
        vehicle=vehicle,
        sources=sources,
        evidence=evidence,
        scans=[scan],
        inspections=inspections,
    )

    coverage, unknowns = calculate_coverage(case)
    result = analyze_case(case)

    assert coverage < 40
    assert unknowns
    assert result.decision == Decision.INSPECT
    assert case.status != CaseStatus.READY_TO_BUY
