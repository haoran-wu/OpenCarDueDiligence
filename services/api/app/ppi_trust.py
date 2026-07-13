"""Trust boundary for independent pre-purchase inspection artifacts."""

from __future__ import annotations

from .models import CaseContext, EvidenceKind


PPI_ARTIFACT_BINDING_BASIS = "server_ingested_ppi_artifact"
MIN_SUBSTANTIVE_PPI_TEXT_CHARS = 20


def trusted_ppi_artifact_evidence_ids(case: CaseContext) -> set[str]:
    """Return PPI evidence IDs bound to a substantive server-ingested artifact.

    An inspection-session receipt is generated from the same user submission
    as the checklist and therefore cannot prove that an independent report
    exists. Trust requires a pre-existing uploaded PPI artifact with a
    server-set binding basis, a digest that matches its source envelope, and
    enough extracted text to be more than a binary or label placeholder.
    """

    sources = {source.id: source for source in case.sources}
    trusted: set[str] = set()
    for evidence in case.evidence:
        if evidence.kind != EvidenceKind.PPI or evidence.page is None:
            continue
        source = sources.get(evidence.source_id)
        if (
            source is None
            or source.source_type != EvidenceKind.PPI.value
            or source.provider != "user-upload"
        ):
            continue
        metadata = evidence.metadata
        artifact_id = metadata.get("artifact_id")
        digest = metadata.get("content_sha256")
        extracted_chars = metadata.get("extracted_text_chars")
        if (
            isinstance(artifact_id, str)
            and bool(artifact_id.strip())
            and digest == source.content_sha256
            and metadata.get("ppi_artifact_binding_basis") == PPI_ARTIFACT_BINDING_BASIS
            and isinstance(extracted_chars, int)
            and not isinstance(extracted_chars, bool)
            and extracted_chars >= MIN_SUBSTANTIVE_PPI_TEXT_CHARS
        ):
            trusted.add(evidence.id)
    return trusted


__all__ = [
    "MIN_SUBSTANTIVE_PPI_TEXT_CHARS",
    "PPI_ARTIFACT_BINDING_BASIS",
    "trusted_ppi_artifact_evidence_ids",
]
