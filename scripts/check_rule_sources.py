#!/usr/bin/env python3
"""Fingerprint official NJ/NY/CT rule sources and detect review drift.

HTML is reduced to normalized visible text before hashing so analytics scripts,
nonces, and formatting changes do not create meaningless alerts. PDF sources
are hashed byte-for-byte. This check is a review trigger, not proof that the
stored legal rule is still correct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RULE_ROOT = ROOT / "data" / "rules" / "states"
BASELINE = ROOT / "data" / "rules" / "source_fingerprints.json"
MAX_BYTES = 20 * 1024 * 1024

# Some state templates inject changing alerts, office-holder names, and footer
# promos outside the rule text. Hash a stable, source-specific content window
# where there is no semantic <main> element. Missing anchors fail the monitor
# rather than silently falling back to a noisy whole-page hash.
CONTENT_WINDOWS: dict[str, tuple[str, str]] = {
    "nj-casual-sales-tax": (
        "Motor Vehicle Casual Sales Frequently Asked Questions",
        "Last Updated:",
    ),
}


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _normalize_html(source_id: str, content: bytes) -> tuple[bytes, str]:
    parser = VisibleText()
    parser.feed(content.decode("utf-8", errors="replace"))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    window = CONTENT_WINDOWS.get(source_id)
    if window:
        start_marker, end_marker = window
        start = text.rfind(start_marker)
        end = text.find(end_marker, start + len(start_marker)) if start >= 0 else -1
        if start < 0 or end < 0 or end <= start:
            raise ValueError(f"content window anchors missing for {source_id}")
        text = text[start:end].strip()
        return text.encode("utf-8"), "normalized_visible_text_window"
    return text.encode("utf-8"), "normalized_visible_text"


def _official_sources() -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for path in sorted(RULE_ROOT.glob("*.yaml")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        for source in bundle.get("sources", []):
            sources.append(
                {
                    "jurisdiction": bundle["jurisdiction"],
                    "id": source["id"],
                    "url": source["url"],
                    "reviewed_at": source["verified_at"],
                }
            )
    return sources


def _fingerprint(source: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        source["url"],
        headers={"User-Agent": "OpenCarDueDiligence/0.1 rule-source-monitor"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
            context=ssl.create_default_context(),
        ) as response:
            content = response.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError("source exceeds 20 MiB monitor limit")
            media_type = response.headers.get_content_type()
            final_url = response.geturl()
            status = response.status
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {**source, "ok": False, "error": type(exc).__name__}

    try:
        if media_type == "application/pdf" or final_url.lower().endswith(".pdf"):
            normalized = content
            hash_basis = "raw_pdf"
        else:
            normalized, hash_basis = _normalize_html(source["id"], content)
    except ValueError as exc:
        return {**source, "ok": False, "error": str(exc)}
    return {
        **source,
        "ok": True,
        "status": status,
        "final_url": final_url,
        "media_type": media_type,
        "hash_basis": hash_basis,
        "content_sha256": hashlib.sha256(normalized).hexdigest(),
        "content_bytes": len(content),
    }


def run() -> dict[str, Any]:
    observed = [_fingerprint(source) for source in _official_sources()]
    previous: dict[str, dict[str, Any]] = {}
    if BASELINE.exists():
        saved = json.loads(BASELINE.read_text(encoding="utf-8"))
        previous = {item["id"]: item for item in saved.get("sources", [])}
    for item in observed:
        old = previous.get(item["id"])
        item["changed"] = bool(
            item.get("ok")
            and old
            and old.get("content_sha256") != item.get("content_sha256")
        )
    return {
        "schema_version": "1.0",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "note": "A hash match is only an automated signal; human review remains required every 90 days.",
        "sources": observed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true", help="emit stable fields suitable for the committed baseline")
    args = parser.parse_args()
    result = run()
    if args.baseline:
        result["sources"] = [
            {
                key: item[key]
                for key in (
                    "jurisdiction", "id", "url", "reviewed_at", "final_url",
                    "media_type", "hash_basis", "content_sha256",
                )
                if key in item
            }
            for item in result["sources"]
            if item.get("ok")
        ]
    print(json.dumps(result, indent=2, sort_keys=True))
    failed = [item for item in result["sources"] if item.get("ok") is False]
    changed = [item for item in result["sources"] if item.get("changed")]
    return 2 if failed else 1 if changed and not args.baseline else 0


if __name__ == "__main__":
    sys.exit(main())
