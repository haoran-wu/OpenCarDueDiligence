#!/usr/bin/env python3
"""Merge source-screened knowledge drafts into the runtime manifest, fail-closed.

This command deliberately cannot publish a family or claim.  It makes draft
research visible to maintainers and to the API's coverage summary while the
runtime resolver continues to return UNKNOWN/INSPECT until named human review.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "data" / "knowledge" / "model_family_manifests_v1.yaml"
DRAFT_PATHS = (
    ROOT / "data" / "knowledge" / "drafts" / "families_a.json",
    ROOT / "data" / "knowledge" / "drafts" / "families_b.json",
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    base = _load(BASE_PATH)
    base_families = base["families"]
    if not isinstance(base_families, list):
        raise ValueError("runtime manifest families must be a list")

    drafts: dict[str, dict[str, object]] = {}
    for path in DRAFT_PATHS:
        payload = _load(path)
        families = payload.get("families")
        if not isinstance(families, list):
            raise ValueError(f"{path.name} families must be a list")
        for family in families:
            if not isinstance(family, dict) or not isinstance(family.get("id"), str):
                raise ValueError(f"{path.name} contains an invalid family")
            family_id = family["id"]
            if family_id in drafts:
                raise ValueError(f"duplicate draft family: {family_id}")
            if family.get("publication_status") != "DRAFT":
                raise ValueError(f"draft family is not DRAFT: {family_id}")
            packs = family.get("applicability_packs")
            if not isinstance(packs, list) or len(packs) != 1:
                raise ValueError(f"draft family must contain exactly one pack: {family_id}")
            for pack in packs:
                if not isinstance(pack, dict) or pack.get("publication_status") != "DRAFT":
                    raise ValueError(f"pack is not DRAFT: {family_id}")
                if pack.get("reviewer") is not None or pack.get("reviewed_at") is not None:
                    raise ValueError(f"draft pack must not claim human review: {family_id}")
                for claim in pack.get("claims", []):
                    for scenario in claim.get("repair_scenarios", []):
                        if scenario.get("planning_cost_usd") is not None:
                            raise ValueError(f"unreviewed pack contains a planning cost: {family_id}")
                        if scenario.get("cost_confidence") != "UNKNOWN":
                            raise ValueError(f"unreviewed pack contains cost confidence: {family_id}")
            drafts[family_id] = family

    ordered_ids = [family.get("id") for family in base_families if isinstance(family, dict)]
    if len(ordered_ids) != 20 or set(ordered_ids) != set(drafts):
        raise ValueError("draft families must match the 20-family runtime inventory exactly")

    base["manifest_version"] = "2026.07.13-draft-runtime"
    base["status"] = "source_screened_drafts_pending_human_review"
    base["warning"] = (
        "All 20 families include one source-screened DRAFT applicability pack. "
        "No family or claim is published: exact US applicability, wording, "
        "licensing, and bilingual content still require named human review."
    )
    governance = base.setdefault("governance", {})
    if not isinstance(governance, dict):
        raise ValueError("runtime governance must be an object")
    governance["draft_inputs"] = [path.relative_to(ROOT).as_posix() for path in DRAFT_PATHS]
    governance["runtime_draft_behavior"] = (
        "DRAFT packs are counted for research coverage but never returned as buyer-facing claims."
    )
    base["placeholder_template"]["publication_status"] = "DRAFT"
    base["families"] = [drafts[family_id] for family_id in ordered_ids]

    BASE_PATH.write_text(
        json.dumps(base, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
