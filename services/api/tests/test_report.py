from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess

from pypdf import PdfReader
import pytest

from app.engines import report as report_engine
from app.engines.report import (
    ReportRenderingError,
    build_report,
    evidence_references_for_finding,
    render_report_pdf,
)
from app.models import (
    CaseContext,
    Decision,
    Evidence,
    EvidenceKind,
    FindingStatus,
    Language,
    RiskArea,
    RiskFinding,
    Severity,
    SourceEnvelope,
)


def _traced_case() -> CaseContext:
    source = SourceEnvelope(
        id="source-carfax",
        source_type="history_report",
        provider="CARFAX user-provided report",
        content_sha256="a" * 64,
    )
    evidence = Evidence(
        id="evidence-page-7",
        source_id=source.id,
        kind=EvidenceKind.HISTORY_REPORT,
        label="Owner 4 inspection row",
        excerpt="Failed safety inspection; failed emissions inspection",
        page=7,
        metadata={
            "locator": "Detailed History / Owner 4",
            "reference": "2026-03-02 inspection row",
        },
    )
    finding = RiskFinding(
        id="finding-safety",
        code="HISTORY_SAFETY_FAILURE",
        area=RiskArea.SAFETY,
        title="A safety inspection failure appears in the history",
        detail="The history does not identify whether the failed item was minor or safety-critical. Verify the failure sheet and completed repair.",
        severity=Severity.HIGH,
        status=FindingStatus.SUSPECTED,
        evidence_ids=[evidence.id],
        next_checks=[
            "Obtain the failed inspection sheet, repair invoice, and current PPI confirmation"
        ],
        decision_impact=Decision.INSPECT,
    )
    return CaseContext(
        id="report-case",
        language=Language.EN,
        decision=Decision.INSPECT,
        coverage_percent=35,
        sources=[source],
        evidence=[evidence],
        findings=[finding],
        unknowns=["No OBD scan is recorded"],
        next_actions=[
            "Arrange an independent pre-purchase inspection and keep the engine cold for arrival"
        ],
    )


def test_report_resolves_finding_evidence_to_source_page_and_locator() -> None:
    report = build_report(_traced_case(), Language.EN)

    reference = evidence_references_for_finding(
        report, report.findings[0].evidence_ids
    )[0]
    assert "CARFAX user-provided report" in reference
    assert "Owner 4 inspection row" in reference
    assert "page 7" in reference
    assert "locator: Detailed History / Owner 4" in reference
    assert "reference: 2026-03-02 inspection row" in reference
    assert "evidence ID: evidence-page-7" in reference
    assert report.evidence_index[0].metadata["source_provider"] == (
        "CARFAX user-provided report"
    )
    assert report.evidence_index[0].excerpt == (
        "Failed safety inspection; failed emissions inspection"
    )


def test_pdf_contains_resolved_evidence_reference_not_only_opaque_id() -> None:
    report = build_report(_traced_case(), Language.EN)

    pdf = render_report_pdf(report)
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages
    )

    assert "CARFAX user-provided report" in extracted
    assert "page 7" in extracted
    assert "Detailed History / Owner 4" in extracted
    assert "evidence ID: evidence-page-7" in extracted
    assert "Evidence index" in extracted


def test_chinese_report_localizes_fixed_prose_and_labels_source_text() -> None:
    case = _traced_case()
    custom = RiskFinding(
        code="INSPECTION_CUSTOM_CHECK",
        area=RiskArea.OTHER,
        title="Technician-specific free text",
        detail="Customer supplied note remains verbatim",
        severity=Severity.MEDIUM,
        evidence_ids=["evidence-page-7"],
        next_checks=["Resolve or price this item using the written PPI finding"],
    )
    case.findings.append(custom)

    report = build_report(case, Language.ZH_CN)

    fixed = report.findings[0]
    source_owned = report.findings[1]
    assert fixed.title == "历史记录中出现安全验车失败"
    assert "安全关键问题" in fixed.detail
    assert fixed.next_checks == ["取得验车失败单、维修发票及当前 PPI 确认。"]
    assert report.unknowns == ["尚未记录 OBD 扫描。"]
    assert report.next_actions == ["安排独立购前检查（PPI），并要求到场时保持冷车。"]
    assert source_owned.title.endswith("Technician-specific free text")
    assert source_owned.title.startswith("原文（检查项目")
    assert source_owned.detail.endswith("Customer supplied note remains verbatim")
    assert "证据来源名、摘录、用户输入和外部DTC描述保持原文" in report.disclaimer
    # Localization creates report copies; it must not rewrite the evidence ledger.
    assert case.findings[0].title == "A safety inspection failure appears in the history"
    assert case.evidence[0].excerpt == (
        "Failed safety inspection; failed emissions inspection"
    )


def test_chinese_pdf_embeds_font_and_keeps_extractable_text() -> None:
    report = build_report(_traced_case(), Language.ZH_CN)

    pdf = render_report_pdf(report)
    reader = PdfReader(BytesIO(pdf))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    fonts = reader.pages[0]["/Resources"]["/Font"]
    font_records = [font.get_object() for font in fonts.values()]

    assert "历史记录中出现安全验车失败" in extracted
    assert "第 7 页" in extracted
    assert any("/FontFile2" in record.get("/FontDescriptor", {}) for record in font_records)


def test_chinese_pdf_fails_closed_when_bundled_font_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(report_engine, "CJK_FONT_PATH", tmp_path / "missing.ttf")

    with pytest.raises(ReportRenderingError, match="font is missing"):
        render_report_pdf(build_report(_traced_case(), Language.ZH_CN))


def test_chinese_pdf_fails_closed_when_bundled_font_is_unusable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corrupt_font = tmp_path / "corrupt.ttf"
    corrupt_font.write_bytes(b"not a TrueType font")
    monkeypatch.setattr(report_engine, "CJK_FONT_PATH", corrupt_font)
    monkeypatch.setattr(report_engine, "CJK_FONT_NAME", "OCDD-Corrupt-Font-Test")

    with pytest.raises(ReportRenderingError, match="could not be registered"):
        render_report_pdf(build_report(_traced_case(), Language.ZH_CN))


def _ppm_content_bbox(path: Path) -> tuple[int, int, int]:
    raw = path.read_bytes()
    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s", raw)
    assert header is not None and int(header.group(3)) == 255
    width, height = int(header.group(1)), int(header.group(2))
    pixels = raw[header.end() :]
    assert len(pixels) == width * height * 3
    points: list[tuple[int, int]] = []
    for offset in range(0, len(pixels), 3):
        if min(pixels[offset : offset + 3]) < 245:
            pixel = offset // 3
            points.append((pixel % width, pixel // width))
    assert points
    xs, ys = zip(*points)
    return len(points), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler is unavailable")
@pytest.mark.parametrize("language", [Language.EN, Language.ZH_CN])
def test_poppler_raster_contains_visible_report_content(
    language: Language, tmp_path: Path
) -> None:
    pdf_path = tmp_path / f"report-{language.value}.pdf"
    output_prefix = tmp_path / f"report-{language.value}"
    pdf_path.write_bytes(render_report_pdf(build_report(_traced_case(), language)))

    subprocess.run(
        [
            str(shutil.which("pdftoppm")),
            "-f",
            "1",
            "-singlefile",
            "-r",
            "96",
            str(pdf_path),
            str(output_prefix),
        ],
        check=True,
        capture_output=True,
    )
    nonwhite, bbox_width, bbox_height = _ppm_content_bbox(
        output_prefix.with_suffix(".ppm")
    )

    assert nonwhite > 500
    assert bbox_width > 200
    assert bbox_height > 100
