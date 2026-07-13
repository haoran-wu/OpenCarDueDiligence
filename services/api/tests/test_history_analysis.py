from datetime import date
from pathlib import Path

from app.engines.history import findings_from_history
from app.engines.risk import analyze_case
from app.evidence import extract_history_events
from app.models import (
    CaseContext,
    Evidence,
    EvidenceKind,
    HistoryEvent,
    ListingInput,
    ListingSnapshot,
    SourceEnvelope,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_negative_history_headings_do_not_become_damage_findings() -> None:
    events = extract_history_events(
        "01/01/2025 120,010 mi\nNo accidents or damage reported\nNo structural damage reported",
        "page-1",
    )
    assert not any("damage_reported" in event.event_type for event in events)


def test_history_extracts_separate_safety_emissions_and_owner_events() -> None:
    text = """
    03/02/2026 119,982 mi
    Failed safety inspection
    Failed emissions inspection
    03/30/2026 120,010 mi
    Passed safety inspection
    Passed emissions inspection
    01/30/2024 107,458 mi
    Title issued or updated - New owner reported
    4 Previous Owners
    """
    event_types = [event.event_type for event in extract_history_events(text, "page-2")]
    assert "safety_failed" in event_types
    assert "emissions_failed" in event_types
    assert "owner_change" in event_types
    assert "ownership_summary" in event_types


def test_carfax_fixture_rejects_summary_warranty_and_annual_mileage() -> None:
    text = (FIXTURE_DIR / "carfax_history_sanitized.txt").read_text()
    events = extract_history_events(text, "sanitized-carfax-page")

    assert any(
        event.event_date == date(2014, 5, 2) and event.mileage == 13_000
        for event in events
    )
    assert all(
        event.mileage is None
        for event in events
        if event.event_date in {date(2014, 1, 10), date(2014, 8, 16)}
    )
    assert any(
        event.event_date == date(2016, 2, 9) and event.mileage == 34_366
        for event in events
    )

    inspection_events = [
        event for event in events if event.event_date == date(2018, 3, 9)
    ]
    inspection_types = {event.event_type for event in inspection_events}
    assert "safety_passed" in inspection_types
    assert "emissions_failed" in inspection_types
    assert "emissions_passed" in inspection_types
    assert "safety_failed" not in inspection_types
    assert {event.mileage for event in inspection_events} == {68_671, 68_777}

    # These values are an annual-driving estimate, a warranty limit, and a
    # report summary. None is an odometer reading from a dated history row.
    assert not {15_000, 50_000, 133_250}.intersection(
        {event.mileage for event in events if event.mileage is not None}
    )
    assert not {
        date(2012, 9, 23),
        date(2025, 7, 14),
        date(2026, 7, 10),
    }.intersection({event.event_date for event in events if event.event_date})

    source = SourceEnvelope(
        id="sanitized-source",
        source_type="history_report",
        content_sha256="a" * 64,
    )
    evidence = Evidence(
        id="sanitized-carfax-page",
        source_id=source.id,
        kind=EvidenceKind.HISTORY_REPORT,
        label="De-identified regression fixture",
    )
    result = analyze_case(
        CaseContext(sources=[source], evidence=[evidence], history=events)
    )
    assert "ODOMETER_SEQUENCE_CONFLICT" not in {
        finding.code for finding in result.findings
    }


def test_carfax_owner_group_headers_do_not_create_an_owner_count() -> None:
    pages = (FIXTURE_DIR / "carfax_owner_summary_sanitized.txt").read_text().split("\f")
    events = [
        event
        for page_number, page in enumerate(pages, start=1)
        for event in extract_history_events(page, f"owner-page-{page_number}")
    ]

    ownership_summaries = [
        event for event in events if event.event_type == "ownership_summary"
    ]
    assert [event.description for event in ownership_summaries] == [
        "Report states an estimated owner count of 7."
    ]


def test_reverse_inspection_status_wording_stays_relation_aware() -> None:
    text = """
    02/01/2025 80,000 mi
    Safety inspection failed
    Emissions inspection passed
    02/10/2025 80,100 mi
    Safety inspection passed
    Emissions inspection failed
    """
    events = extract_history_events(text, "reverse-status-page")

    first = {
        event.event_type
        for event in events
        if event.event_date == date(2025, 2, 1)
    }
    second = {
        event.event_type
        for event in events
        if event.event_date == date(2025, 2, 10)
    }
    assert first == {"safety_failed", "emissions_passed"}
    assert second == {"safety_passed", "emissions_failed"}


def test_history_findings_detect_conflict_repeated_failures_and_record_gap() -> None:
    target_input = ListingInput(
        title="Clean title, no accidents",
        description="Never accident and no damage",
        asking_price=5500,
        is_target=True,
    )
    target = ListingSnapshot(
        **target_input.model_dump(),
        source_id="listing-source",
        evidence_id="listing-evidence",
        content_sha256="a" * 64,
    )
    case = CaseContext(
        listings=[target],
        history=[
            HistoryEvent(event_type="title_brand_reported", description="Rebuilt title", evidence_ids=["p1"]),
            HistoryEvent(event_type="accident_or_damage_reported", description="Accident reported", evidence_ids=["p2"]),
            HistoryEvent(event_type="emissions_failed", description="Failed", evidence_ids=["p3"]),
            HistoryEvent(event_type="emissions_failed", description="Failed", evidence_ids=["p4"]),
            HistoryEvent(event_type="service", event_date=date(2020, 1, 1), mileage=20_000, description="Service", evidence_ids=["p5"]),
            HistoryEvent(event_type="service", event_date=date(2023, 1, 2), mileage=60_100, description="Service", evidence_ids=["p6"]),
        ],
    )
    findings = findings_from_history(case)
    codes = {finding.code for finding in findings}
    assert "HISTORY_TITLE_BRAND" in codes
    assert "HISTORY_REPEATED_EMISSIONS_FAILURES" in codes
    assert "HISTORY_SERVICE_RECORD_GAP" in codes
    assert "LISTING_HISTORY_CONFLICT" in codes
    assert next(f for f in findings if f.code == "LISTING_HISTORY_CONFLICT").blocks_purchase
