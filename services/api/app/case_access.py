"""Opaque per-case capability tokens for the anonymous cloud application."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from .repository import CaseRepository


TOKEN_BYTES = 32
CASE_TOKEN_HEADER = "X-OCDD-Case-Token"


def hash_case_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_case_token(repository: CaseRepository, case_id: str) -> str:
    """Return a token once and persist only its SHA-256 digest."""

    token = secrets.token_urlsafe(TOKEN_BYTES)
    repository.set_case_access_token_hash(case_id, hash_case_token(token))
    return token


def verify_case_token(repository: CaseRepository, case_id: str, token: str | None) -> bool:
    if not token:
        return False
    expected = repository.get_case_access_token_hash(case_id)
    if expected is None:
        return False
    return hmac.compare_digest(expected, hash_case_token(token))
