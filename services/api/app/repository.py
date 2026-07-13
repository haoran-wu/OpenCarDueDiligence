"""Structured case repositories.

SQLite is the local default. PostgreSQL is the reference cloud backend. Raw
artifacts are accessed through a separate TransientArtifactStore abstraction;
the artifact methods here are a local/fallback storage primitive only.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterable, Protocol

from .models import CaseContext


class CaseNotFoundError(KeyError):
    pass


class CaseRepository(Protocol):
    def create_case(self, case: CaseContext) -> CaseContext: ...
    def save_case(self, case: CaseContext) -> CaseContext: ...
    def get_case(self, case_id: str) -> CaseContext: ...
    def list_cases(self, case_ids: Iterable[str] | None = None) -> list[CaseContext]: ...
    def delete_case(self, case_id: str) -> bool: ...
    def purge_expired_cases(self, now: datetime | None = None) -> int: ...
    def set_case_access_token_hash(self, case_id: str, token_hash: str) -> None: ...
    def get_case_access_token_hash(self, case_id: str) -> str | None: ...
    def acquire_case_lease(
        self,
        case_id: str,
        *,
        token: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> bool: ...
    def release_case_lease(self, case_id: str, *, token: str) -> bool: ...

    def store_artifact(
        self,
        *,
        artifact_id: str,
        case_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        content_sha256: str,
        expires_at: datetime | None,
    ) -> None: ...

    def get_artifact_bytes(self, artifact_id: str) -> bytes | None: ...
    def delete_artifact(self, artifact_id: str) -> bool: ...
    def delete_case_artifacts(self, case_id: str) -> int: ...
    def purge_expired_artifacts(self, now: datetime | None = None) -> int: ...
    def artifact_count(self, case_id: str | None = None) -> int: ...


class SQLiteRepository:
    def __init__(self, database_path: str | Path = "./ocdd.sqlite3") -> None:
        self.database_path = str(database_path)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    retention_class TEXT NOT NULL DEFAULT 'LOCAL',
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    content BLOB NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    expires_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_expires
                    ON artifacts(expires_at) WHERE expires_at IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_artifacts_case ON artifacts(case_id);
                CREATE TABLE IF NOT EXISTS case_access (
                    case_id TEXT PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_leases (
                    case_id TEXT PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
                    token TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_case_leases_expires
                    ON case_leases(expires_at);
                """
            )
            # Lightweight forward migration for databases created before case
            # retention was part of the v1 schema. Existing cases are LOCAL by
            # default and therefore never silently become expiring cases.
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(cases)").fetchall()
            }
            if "retention_class" not in columns:
                connection.execute(
                    "ALTER TABLE cases ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'LOCAL'"
                )
            if "expires_at" not in columns:
                connection.execute("ALTER TABLE cases ADD COLUMN expires_at TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cases_expires "
                "ON cases(expires_at) WHERE expires_at IS NOT NULL"
            )

    def create_case(self, case: CaseContext) -> CaseContext:
        payload = case.model_dump_json(by_alias=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cases(
                    id, payload, retention_class, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    case.id,
                    payload,
                    case.retention_class.value,
                    case.expires_at.isoformat() if case.expires_at else None,
                    case.created_at.isoformat(),
                    case.updated_at.isoformat(),
                ),
            )
        return case

    def save_case(self, case: CaseContext) -> CaseContext:
        payload = case.model_dump_json(by_alias=False)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE cases
                SET payload = ?, retention_class = ?, expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload,
                    case.retention_class.value,
                    case.expires_at.isoformat() if case.expires_at else None,
                    case.updated_at.isoformat(),
                    case.id,
                ),
            )
            if cursor.rowcount != 1:
                raise CaseNotFoundError(case.id)
        return case

    def get_case(self, case_id: str) -> CaseContext:
        self.purge_expired_cases()
        self.purge_expired_artifacts()
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise CaseNotFoundError(case_id)
        return CaseContext.model_validate_json(row["payload"])

    def list_cases(self, case_ids: Iterable[str] | None = None) -> list[CaseContext]:
        self.purge_expired_cases()
        self.purge_expired_artifacts()
        with self._connect() as connection:
            if case_ids is None:
                rows = connection.execute("SELECT payload FROM cases ORDER BY updated_at DESC").fetchall()
            else:
                ids = list(dict.fromkeys(case_ids))
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                rows = connection.execute(
                    f"SELECT payload FROM cases WHERE id IN ({placeholders})", ids
                ).fetchall()
        return [CaseContext.model_validate_json(row["payload"]) for row in rows]

    def delete_case(self, case_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        return cursor.rowcount == 1

    def purge_expired_cases(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM cases
                WHERE expires_at IS NOT NULL
                  AND expires_at <= ?
                  AND NOT EXISTS (
                    SELECT 1 FROM case_leases
                    WHERE case_leases.case_id = cases.id
                      AND case_leases.expires_at > ?
                  )
                """,
                (now.isoformat(), now.isoformat()),
            )
        return cursor.rowcount

    def set_case_access_token_hash(self, case_id: str, token_hash: str) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO case_access(case_id, token_hash, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET token_hash = excluded.token_hash
                """,
                (case_id, token_hash, datetime.now(timezone.utc).isoformat()),
            )
            if cursor.rowcount != 1:
                raise CaseNotFoundError(case_id)

    def get_case_access_token_hash(self, case_id: str) -> str | None:
        self.purge_expired_cases()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT token_hash FROM case_access WHERE case_id = ?", (case_id,)
            ).fetchone()
        return str(row["token_hash"]) if row else None

    def acquire_case_lease(
        self,
        case_id: str,
        *,
        token: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        if not token:
            raise ValueError("case lease token cannot be empty")
        if now.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("case lease timestamps must include a timezone")
        now_text = now.astimezone(timezone.utc).isoformat()
        expiry_text = expires_at.astimezone(timezone.utc).isoformat()
        if expiry_text <= now_text:
            raise ValueError("case lease expiry must be in the future")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO case_leases(case_id, token, expires_at)
                SELECT id, ?, ? FROM cases WHERE id = ?
                ON CONFLICT(case_id) DO UPDATE SET
                    token = excluded.token,
                    expires_at = excluded.expires_at
                WHERE case_leases.expires_at <= ?
                """,
                (token, expiry_text, case_id, now_text),
            )
            acquired = cursor.rowcount == 1
            if not acquired:
                exists = connection.execute(
                    "SELECT 1 FROM cases WHERE id = ?", (case_id,)
                ).fetchone()
                if exists is None:
                    raise CaseNotFoundError(case_id)
        return acquired

    def release_case_lease(self, case_id: str, *, token: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM case_leases WHERE case_id = ? AND token = ?",
                (case_id, token),
            )
        return cursor.rowcount == 1

    def store_artifact(
        self,
        *,
        artifact_id: str,
        case_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        content_sha256: str,
        expires_at: datetime | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts(
                    id, case_id, filename, media_type, content, content_sha256, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    case_id,
                    filename,
                    media_type,
                    content,
                    content_sha256,
                    expires_at.isoformat() if expires_at else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_artifact_bytes(self, artifact_id: str) -> bytes | None:
        self.purge_expired_cases()
        self.purge_expired_artifacts()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        return bytes(row["content"]) if row else None

    def delete_artifact(self, artifact_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        return cursor.rowcount == 1

    def delete_case_artifacts(self, case_id: str) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM artifacts WHERE case_id = ?", (case_id,))
        return cursor.rowcount

    def purge_expired_artifacts(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now.isoformat(),),
            )
        return cursor.rowcount

    def artifact_count(self, case_id: str | None = None) -> int:
        self.purge_expired_cases()
        self.purge_expired_artifacts()
        with self._connect() as connection:
            if case_id:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM artifacts WHERE case_id = ?", (case_id,)
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS count FROM artifacts").fetchone()
        return int(row["count"])


class PostgresRepository:
    """Synchronous SQLAlchemy repository for the reference cloud deployment.

    It deliberately uses portable TEXT JSON for the structured document so the
    Pydantic schema remains the source of truth. PostgreSQL still supplies
    concurrency, backups, and managed durability.
    """

    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("PostgresRepository requires a PostgreSQL URL")
        from sqlalchemy import (
            Column,
            DateTime,
            ForeignKey,
            Index,
            LargeBinary,
            MetaData,
            String,
            Table,
            Text,
            create_engine,
            text,
        )

        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.metadata = MetaData()
        self.cases = Table(
            "cases",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("payload", Text, nullable=False),
            Column("retention_class", String, nullable=False, server_default="LOCAL"),
            Column("expires_at", DateTime(timezone=True), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.case_expiry_index = Index("idx_cases_expires", self.cases.c.expires_at)
        # Cloud production should use S3ArtifactStore. This table supports local
        # cloud development and preserves the same injectable store contract.
        self.artifacts = Table(
            "artifacts",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("case_id", String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            Column("filename", Text, nullable=False),
            Column("media_type", Text, nullable=False),
            Column("content", LargeBinary, nullable=False),
            Column("content_sha256", String(64), nullable=False),
            Column("expires_at", DateTime(timezone=True), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.case_access = Table(
            "case_access",
            self.metadata,
            Column(
                "case_id",
                String,
                ForeignKey("cases.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            Column("token_hash", String(64), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self.case_leases = Table(
            "case_leases",
            self.metadata,
            Column(
                "case_id",
                String,
                ForeignKey("cases.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            Column("token", String(64), nullable=False),
            Column("expires_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(self.engine)
        # ``create_all`` deliberately does not mutate an existing table, so
        # make the additive v1 migration explicit before using the columns.
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS "
                    "retention_class VARCHAR NOT NULL DEFAULT 'LOCAL'"
                )
            )
            connection.execute(
                text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL")
            )
        self.case_expiry_index.create(self.engine, checkfirst=True)

    def create_case(self, case: CaseContext) -> CaseContext:
        with self.engine.begin() as connection:
            connection.execute(
                self.cases.insert().values(
                    id=case.id,
                    payload=case.model_dump_json(by_alias=False),
                    retention_class=case.retention_class.value,
                    expires_at=case.expires_at,
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                )
            )
        return case

    def save_case(self, case: CaseContext) -> CaseContext:
        with self.engine.begin() as connection:
            result = connection.execute(
                self.cases.update()
                .where(self.cases.c.id == case.id)
                .values(
                    payload=case.model_dump_json(by_alias=False),
                    retention_class=case.retention_class.value,
                    expires_at=case.expires_at,
                    updated_at=case.updated_at,
                )
            )
        if result.rowcount != 1:
            raise CaseNotFoundError(case.id)
        return case

    def get_case(self, case_id: str) -> CaseContext:
        from sqlalchemy import select

        self.purge_expired_cases()
        self.purge_expired_artifacts()
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.cases.c.payload).where(self.cases.c.id == case_id)
            ).first()
        if row is None:
            raise CaseNotFoundError(case_id)
        return CaseContext.model_validate_json(row.payload)

    def list_cases(self, case_ids: Iterable[str] | None = None) -> list[CaseContext]:
        from sqlalchemy import select

        self.purge_expired_cases()
        self.purge_expired_artifacts()
        query = select(self.cases.c.payload).order_by(self.cases.c.updated_at.desc())
        if case_ids is not None:
            ids = list(dict.fromkeys(case_ids))
            if not ids:
                return []
            query = query.where(self.cases.c.id.in_(ids))
        with self.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [CaseContext.model_validate_json(row.payload) for row in rows]

    def delete_case(self, case_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(self.cases.delete().where(self.cases.c.id == case_id))
        return result.rowcount == 1

    def purge_expired_cases(self, now: datetime | None = None) -> int:
        from sqlalchemy import exists

        now = now or datetime.now(timezone.utc)
        active_lease = exists().where(
            self.case_leases.c.case_id == self.cases.c.id,
            self.case_leases.c.expires_at > now,
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                self.cases.delete()
                .where(self.cases.c.expires_at.is_not(None))
                .where(self.cases.c.expires_at <= now)
                .where(~active_lease)
            )
        return result.rowcount

    def set_case_access_token_hash(self, case_id: str, token_hash: str) -> None:
        from sqlalchemy.dialects.postgresql import insert

        statement = insert(self.case_access).values(
            case_id=case_id,
            token_hash=token_hash,
            created_at=datetime.now(timezone.utc),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[self.case_access.c.case_id],
            set_={"token_hash": statement.excluded.token_hash},
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
        if result.rowcount != 1:
            raise CaseNotFoundError(case_id)

    def get_case_access_token_hash(self, case_id: str) -> str | None:
        from sqlalchemy import select

        self.purge_expired_cases()
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.case_access.c.token_hash).where(
                    self.case_access.c.case_id == case_id
                )
            ).first()
        return str(row.token_hash) if row else None

    def acquire_case_lease(
        self,
        case_id: str,
        *,
        token: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> bool:
        from sqlalchemy import literal, select
        from sqlalchemy.dialects.postgresql import insert

        now = now or datetime.now(timezone.utc)
        if not token:
            raise ValueError("case lease token cannot be empty")
        if now.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("case lease timestamps must include a timezone")
        now = now.astimezone(timezone.utc)
        expires_at = expires_at.astimezone(timezone.utc)
        if expires_at <= now:
            raise ValueError("case lease expiry must be in the future")
        candidate = select(
            self.cases.c.id,
            literal(token),
            literal(expires_at),
        ).where(self.cases.c.id == case_id)
        statement = insert(self.case_leases).from_select(
            ["case_id", "token", "expires_at"], candidate
        )
        statement = statement.on_conflict_do_update(
            index_elements=[self.case_leases.c.case_id],
            set_={"token": token, "expires_at": expires_at},
            where=self.case_leases.c.expires_at <= now,
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            acquired = result.rowcount == 1
            if not acquired:
                exists_row = connection.execute(
                    select(self.cases.c.id).where(self.cases.c.id == case_id)
                ).first()
                if exists_row is None:
                    raise CaseNotFoundError(case_id)
        return acquired

    def release_case_lease(self, case_id: str, *, token: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                self.case_leases.delete().where(
                    self.case_leases.c.case_id == case_id,
                    self.case_leases.c.token == token,
                )
            )
        return result.rowcount == 1

    def store_artifact(
        self,
        *,
        artifact_id: str,
        case_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        content_sha256: str,
        expires_at: datetime | None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                self.artifacts.insert().values(
                    id=artifact_id,
                    case_id=case_id,
                    filename=filename,
                    media_type=media_type,
                    content=content,
                    content_sha256=content_sha256,
                    expires_at=expires_at,
                    created_at=datetime.now(timezone.utc),
                )
            )

    def get_artifact_bytes(self, artifact_id: str) -> bytes | None:
        from sqlalchemy import select

        self.purge_expired_cases()
        self.purge_expired_artifacts()
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.artifacts.c.content).where(self.artifacts.c.id == artifact_id)
            ).first()
        return bytes(row.content) if row else None

    def delete_artifact(self, artifact_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                self.artifacts.delete().where(self.artifacts.c.id == artifact_id)
            )
        return result.rowcount == 1

    def delete_case_artifacts(self, case_id: str) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                self.artifacts.delete().where(self.artifacts.c.case_id == case_id)
            )
        return result.rowcount

    def purge_expired_artifacts(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                self.artifacts.delete()
                .where(self.artifacts.c.expires_at.is_not(None))
                .where(self.artifacts.c.expires_at <= now)
            )
        return result.rowcount

    def artifact_count(self, case_id: str | None = None) -> int:
        from sqlalchemy import func, select

        self.purge_expired_cases()
        self.purge_expired_artifacts()
        query = select(func.count()).select_from(self.artifacts)
        if case_id:
            query = query.where(self.artifacts.c.case_id == case_id)
        with self.engine.connect() as connection:
            return int(connection.execute(query).scalar_one())
