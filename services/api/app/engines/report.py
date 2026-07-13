"""Deterministic bilingual report rendering."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from ..models import CaseContext, Decision, Evidence, Language, ReportResponse
from .report_localization import (
    localize_action_zh,
    localize_finding_zh,
    localize_unknown_zh,
)


CJK_FONT_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "fonts"
    / "NotoSansSC[wght].ttf"
)
CJK_FONT_NAME = "OCDD-NotoSansSC"


class ReportRenderingError(RuntimeError):
    """The report cannot be rendered without a usable embedded font."""


def _evidence_index(case: CaseContext) -> list[Evidence]:
    """Attach non-sensitive source provenance without changing evidence text."""

    sources = {item.id: item for item in case.sources}
    indexed: list[Evidence] = []
    for evidence in case.evidence:
        metadata = dict(evidence.metadata)
        source = sources.get(evidence.source_id)
        if source:
            metadata.setdefault("source_provider", source.provider)
            metadata.setdefault("source_type", source.source_type)
        indexed.append(evidence.model_copy(update={"metadata": metadata}))
    return indexed


def evidence_reference(evidence: Evidence, language: Language) -> str:
    """Return a human-readable locator while retaining the stable evidence ID."""

    is_chinese = language == Language.ZH_CN
    metadata = evidence.metadata
    provider = metadata.get("source_provider") or metadata.get("provider")
    source_type = metadata.get("source_type")
    parts: list[str] = []
    if isinstance(provider, str) and provider.strip():
        parts.append(provider.strip())
    elif isinstance(source_type, str) and source_type.strip():
        parts.append(source_type.strip())
    else:
        parts.append(evidence.kind.value)
    if evidence.label and evidence.label not in parts:
        parts.append(evidence.label)
    if evidence.page is not None:
        parts.append(f"第 {evidence.page} 页" if is_chinese else f"page {evidence.page}")
    locator_labels = {
        "locator": "定位" if is_chinese else "locator",
        "reference": "参考" if is_chinese else "reference",
        "section": "章节" if is_chinese else "section",
        "record_reference": "记录" if is_chinese else "record",
    }
    seen: set[str] = set()
    for key, label in locator_labels.items():
        value = metadata.get(key)
        if not isinstance(value, (str, int, float)):
            continue
        rendered = str(value).strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        parts.append(f"{label}: {rendered}")
    parts.append(f"证据 ID: {evidence.id}" if is_chinese else f"evidence ID: {evidence.id}")
    return " · ".join(parts)


def evidence_references_for_finding(
    report: ReportResponse, evidence_ids: list[str]
) -> list[str]:
    """Resolve finding links through ``ReportResponse.evidence_index``."""

    indexed = {item.id: item for item in report.evidence_index}
    references: list[str] = []
    for evidence_id in evidence_ids:
        evidence = indexed.get(evidence_id)
        if evidence:
            references.append(evidence_reference(evidence, report.language))
        elif report.language == Language.ZH_CN:
            references.append(f"未解析的证据引用 · 证据 ID: {evidence_id}")
        else:
            references.append(f"Unresolved evidence reference · evidence ID: {evidence_id}")
    return references


def build_report(case: CaseContext, language: Language | None = None) -> ReportResponse:
    language = language or case.language
    if language == Language.ZH_CN:
        decision_text = {
            Decision.STOP: "发现阻断性问题；在独立证据解决之前不要交易。",
            Decision.INSPECT: "现有证据不足以购买；下一步是继续核实并完成独立购前检查。",
            Decision.NEGOTIATE: "已具备谈价基础，但报价必须以已确认的检查和维修成本为依据。",
            Decision.BUY_CANDIDATE: "这是可继续购买流程的候选车，不代表机械状况或title获得保证。",
        }[case.decision]
        summary = f"结论：{case.decision.value}。证据覆盖率 {case.coverage_percent:.0f}%。{decision_text}"
        disclaimer = (
            "本报告仅为决策支持，不替代独立技师、保险公司、DMV或律师。未检查项目保持“未知”；"
            "历史报告和无OBD报码都不能证明车辆机械状况正常。系统固定文案采用确定性中文本地化；"
            "证据来源名、摘录、用户输入和外部DTC描述保持原文，并明确标注为原文。"
        )
    else:
        decision_text = {
            Decision.STOP: "A blocking issue must be independently resolved before any transaction.",
            Decision.INSPECT: "The evidence is not sufficient to buy; continue verification and obtain an independent PPI.",
            Decision.NEGOTIATE: "There is enough evidence to negotiate, but every deduction must tie to a documented finding.",
            Decision.BUY_CANDIDATE: "The vehicle may proceed through the purchase workflow; this is not a mechanical or title guarantee.",
        }[case.decision]
        summary = f"Decision: {case.decision.value}. Evidence coverage: {case.coverage_percent:.0f}%. {decision_text}"
        disclaimer = (
            "Decision support only; not a substitute for an independent mechanic, insurer, DMV, or attorney. "
            "Unchecked items remain unknown. A history report or a code-free OBD scan does not prove mechanical condition."
        )
    findings = (
        [localize_finding_zh(item) for item in case.findings]
        if language == Language.ZH_CN
        else case.findings
    )
    unknowns = (
        [localize_unknown_zh(item) for item in case.unknowns]
        if language == Language.ZH_CN
        else case.unknowns
    )
    next_actions = (
        [localize_action_zh(item) for item in case.next_actions]
        if language == Language.ZH_CN
        else case.next_actions
    )
    return ReportResponse(
        case_id=case.id,
        language=language,
        decision=case.decision,
        summary=summary,
        valuation=case.valuation,
        findings=findings,
        evidence_index=_evidence_index(case),
        unknowns=unknowns,
        next_actions=next_actions,
        disclaimer=disclaimer,
    )


def render_report_pdf(report: ReportResponse) -> bytes:
    """Render a compact bilingual PDF from already-redacted structured facts."""
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    is_chinese = report.language == Language.ZH_CN
    font = "Helvetica"
    if is_chinese:
        if not CJK_FONT_PATH.is_file():
            raise ReportRenderingError(
                "bundled CJK report font is missing; refusing to emit an unreadable PDF"
            )
        try:
            try:
                pdfmetrics.getFont(CJK_FONT_NAME)
            except KeyError:
                pdfmetrics.registerFont(TTFont(CJK_FONT_NAME, str(CJK_FONT_PATH)))
            font = CJK_FONT_NAME
        except Exception as exc:
            raise ReportRenderingError(
                "bundled CJK report font could not be registered; refusing to emit an unreadable PDF"
            ) from exc
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "OCDDTitle", parent=styles["Title"], fontName=font, fontSize=18, leading=23, alignment=TA_LEFT
    )
    heading_style = ParagraphStyle(
        "OCDDHeading", parent=styles["Heading2"], fontName=font, fontSize=12, leading=16, spaceBefore=8
    )
    body_style = ParagraphStyle(
        "OCDDBody", parent=styles["BodyText"], fontName=font, fontSize=9, leading=13
    )
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"OpenCarDueDiligence {report.case_id}",
    )
    story = [
        Paragraph("OpenCarDueDiligence", title_style),
        Paragraph(escape(report.summary), body_style),
        Spacer(1, 8),
    ]
    findings_label = "风险与待核实项目" if is_chinese else "Findings and verification items"
    story.append(Paragraph(findings_label, heading_style))
    if report.findings:
        for finding in report.findings:
            citations = evidence_references_for_finding(report, finding.evidence_ids)
            if not citations:
                citations = ["未关联证据定位" if is_chinese else "No evidence locator linked"]
            citation_label = "证据定位" if is_chinese else "Evidence reference"
            rendered_citations = "<br/>".join(
                f"{escape(citation_label)}: {escape(item)}" for item in citations
            )
            line = (
                f"<b>{escape(finding.severity.value)} · {escape(finding.title)}</b><br/>"
                f"{escape(finding.detail)}<br/><font size='7'>{rendered_citations}</font>"
            )
            story.extend([Paragraph(line, body_style), Spacer(1, 5)])
    else:
        story.append(
            Paragraph(
                "尚无已确认的发现；未检查项目保持未知。"
                if is_chinese
                else "No confirmed finding; unchecked items remain unknown.",
                body_style,
            )
        )
    unknown_label = "仍未核实" if is_chinese else "Still unknown"
    story.append(Paragraph(unknown_label, heading_style))
    for item in report.unknowns:
        story.append(Paragraph(f"• {escape(item)}", body_style))
    action_label = "下一步" if is_chinese else "Next actions"
    story.append(Paragraph(action_label, heading_style))
    for item in report.next_actions:
        story.append(Paragraph(f"• {escape(item)}", body_style))
    evidence_label = "证据索引" if is_chinese else "Evidence index"
    story.append(Paragraph(evidence_label, heading_style))
    if report.evidence_index:
        for evidence in report.evidence_index:
            story.append(
                Paragraph(f"• {escape(evidence_reference(evidence, report.language))}", body_style)
            )
    else:
        story.append(
            Paragraph("尚无证据条目。" if is_chinese else "No evidence entries.", body_style)
        )
    story.extend([Spacer(1, 10), Paragraph(escape(report.disclaimer), body_style)])
    document.build(story)
    return buffer.getvalue()
