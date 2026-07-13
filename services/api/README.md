# OpenCarDueDiligence API

The API is deterministic by default: evidence, valuation, risk gates, repair
branches, negotiation arithmetic, and transaction rules work without an LLM.

```bash
python -m pip install -e '.[test]'
uvicorn app.main:app --reload --port 8000
pytest
```

Public JSON uses camelCase and accepts camelCase or snake_case. Raw cloud
artifacts have a 60-minute maximum deletion window by default; reports only
reference redacted structured evidence. The encrypted `.ocdd` export excludes
attachments by default. In the reference Compose deployment, S3 access expires
at 55 minutes and an API-independent sidecar scans every 60 seconds, normally
deleting by minute 56 and leaving four minutes of operational buffer. Treat an
unhealthy purger or
object-store outage as a retention incident; no software can promise physical
deletion while storage is unavailable.

Report findings resolve each stable evidence ID through the response
`evidenceIndex` and render the available provider, evidence label, page, and
structured locator/reference in PDF output. A missing ledger entry is shown as
an unresolved reference rather than silently reduced to an opaque ID. For
`zh-CN`, fixed system findings, unknowns, next checks, and next actions use
deterministic translations. Provider names, evidence excerpts, user-entered
inspection text, and externally supplied DTC descriptions are preserved
verbatim and labeled as source text; the API does not claim to translate
third-party evidence.

Chinese PDF generation embeds the bundled, unmodified Noto Sans SC variable
font from `app/assets/fonts`. The wheel and Docker image include the font and
its SIL Open Font License 1.1. Rendering fails closed with a report-generation
error if that asset is absent or unusable; it never falls back to a host-only
CID/system-font reference that can produce a visually blank rasterized PDF.

In cloud mode, case creation and `.ocdd` import return a random capability once
in the `X-OCDD-Case-Token` response header. The API stores only its SHA-256
digest. Send that header on every subsequent `/v1/cases/{id}` request; losing it
means the anonymous case cannot be recovered. Cloud case enumeration is
disabled, and `/v1/compare` requires an `accessTokens` mapping covering every
case ID. Use HTTPS: a bearer capability is only as private as its transport and
client-side storage. Case capabilities are not a substitute for account auth;
account-mode deployments must still bind cases to principals at their gateway.

Set `OCDD_DATABASE_URL=postgresql+psycopg://...` for the reference cloud
database and configure `OCDD_S3_BUCKET` (plus optional endpoint/region/KMS
variables) for transient originals. SQLite plus an AES-GCM artifact envelope is
the local default; SQLite is not presented as the production cloud backend.
Use a dedicated bucket with both versioning and Object Lock disabled. A delete
marker in a versioned bucket is not physical deletion, and Object Lock can
prevent TTL/case deletion, so either setting violates this transient-store
design. Do not share the bucket or prefix with unrelated objects.
`OCDD_ARTIFACT_TTL_SECONDS`, `OCDD_ARTIFACT_PURGE_INTERVAL_SECONDS`, and
`OCDD_ARTIFACT_EXPIRY_SAFETY_MARGIN_SECONDS` control the deletion ceiling,
sidecar cadence, and early access cutoff. The margin must be at least one purge
interval. Standard S3 lifecycle expiry is day-granular and is only suitable as
a longer-stop fallback, not as evidence of meeting the 60-minute window.

Deleting a case first deletes every S3 original whose opaque case hash matches,
then deletes the structured case. If S3 is unavailable, the API returns 503 and
retains the structured case/capability so deletion can be retried. Object reads
also fail closed and delete the object if expiry metadata is absent, malformed,
or elapsed.

Cloud artifact uploads are capped twice: the ASGI stream is counted before JSON
parsing (`OCDD_ARTIFACT_REQUEST_MAX_BYTES`, 14,046,552 bytes by default), and
the decoded/text artifact is checked before base64 decoding or worker dispatch
(`OCDD_ARTIFACT_MAX_BYTES`, 10 MiB by default). Both failures return HTTP 413
without saving a source, evidence row, or object. Local mode keeps a 25 MiB
decoded default for evidence usefulness.

The reference cloud process also applies bounded, direct-peer sliding-window
limits to case creation/import and artifact upload (30 and 20 requests/minute,
configured with `OCDD_CLOUD_CASE_CREATE_PER_MINUTE` and
`OCDD_CLOUD_ARTIFACT_UPLOAD_PER_MINUTE`). It deliberately ignores
`X-Forwarded-For`, `Forwarded`, and similar headers because the app cannot
authenticate their sender. The reference API container starts Uvicorn with
`--no-proxy-headers`; an operator may opt in only with an explicit trusted
`--forwarded-allow-ips` boundary. This is only single-process/single-instance defense:
a public multi-worker or multi-replica deployment **must** add a distributed
Valkey-backed API-gateway/WAF limit at its trusted ingress.

`docker-compose.cloud.yml` is a loopback-only single-host reference: every
published port binds to `127.0.0.1`. A public production deployment still
requires an external trusted reverse proxy/API gateway for TLS termination,
distributed rate limiting, authentication where applicable, and monitoring of
API, object-store, purger heartbeat, deletion failures, and retention SLOs.

In cloud mode, title and seller-message artifacts are hashed in memory but are
not dispatched to OCR and are never written to the transient artifact store.
Their filename, label, body, title number, address, and human names do not enter
the structured case. A title evidence row retains only a caller-supplied
`identityTitleMatch` enum (`MATCH`, `MISMATCH`, or `UNKNOWN`); omission always
persists `UNKNOWN`, never an inferred match. Other cloud documents can produce
allowlisted dated/mileage history facts, but their generic free-text excerpts
and user labels are omitted. Cloud `.ocdd` import reapplies this policy and
strips local free-text fields instead of treating an encrypted package as
already de-identified. Local mode continues to retain encrypted originals and
redacted excerpts until case deletion.

Document extraction defaults to in-process parsing for tests and simple local
runs. Set `OCDD_DOCUMENT_PROCESSOR=celery`, `OCDD_REDIS_URL`, and a shared
32-byte URL-safe-base64 `OCDD_WORKER_ENVELOPE_KEY` to enable OCR workers. API
startup fails if Celery mode has no valid key, and an unavailable worker returns
HTTP 503 without accepting or persisting the upload.

Optional language rendering remains disabled unless a caller explicitly builds
the local adapter with `create_optional_local_llm_provider`. Ollama uses
`OCDD_LLM_PROVIDER=ollama` and `OCDD_OLLAMA_MODEL`, with optional
`OCDD_OLLAMA_BASE_URL` and `OLLAMA_API_KEY`. The official distribution has no
hosted or paid LLM adapter and never requires an API key. Missing configuration
fails closed, while the complete deterministic analysis continues without a
provider. The adapter receives structured facts only, cannot mutate a case,
and rejects generated prose that introduces a new numeric value or protected
decision label.

Interactive API documentation is available at `/docs`.

Vehicle-family knowledge is deliberately fail-closed:

```text
GET  /v1/knowledge/families
POST /v1/knowledge/resolve     # request body is a VehicleSpec
```

The 20 shipped family manifests each contain one official-source-screened
`DRAFT` pack, not a completed reliability guide. Claims are returned only from
one unambiguous `PUBLISHED` pack whose year, generation, platform, engine,
transmission, drivetrain, and production-date range all match exactly. The
shipped drafts therefore remain `UNKNOWN / INSPECT`, with missing fields and
blocking reasons exposed until named human review.
