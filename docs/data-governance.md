# Data and evidence governance

## Evidence hierarchy

1. Subject-vehicle PPI, direct measurements and full-system scan
2. Original title, official inspection record and VIN-specific invoice
3. User-provided vehicle-history report or approved NMVTIS report
4. OEM recall, TSB, maintenance schedule and NHTSA data
5. Listing snapshot, photos and seller statements
6. Community anecdotes

Community anecdotes may create an inspection question. They cannot alone
confirm a defect, reduce value, or trigger a rejection.

## Source manifest

Every source records its URL or local origin, observation time, effective date,
license, SHA-256 hash, retention class, and locator. First-party rule and
knowledge data uses CC BY-SA 4.0 unless a manifest states otherwise.

Third-party data is never assumed redistributable merely because it is on
GitHub. The official provider registry accepts only free/open sources or
artifacts supplied by the user for that user's case. CARFAX, NMVTIS,
proprietary labor guides, valuation feeds and manufacturer-specific diagnostic
text require their own rights and are never sold or bundled by this project.

## Freshness

- DMV/tax/permit/form rules: source pages checked weekly; human review at least
  every 90 days. Stale rules return `needs_verification`.
- Repair estimates: show region, shop type, assumptions, date and sample count;
  ranges older than 12 months are marked stale.
- Comparables: report observation date and distinguish asking from transaction
  prices.

## Case retention classes

The public cloud reference defaults every case to `ANONYMOUS` and expires it
after seven days. `ACCOUNT` retention is rejected unless the deployment owner
explicitly enables it behind an authenticated account layer; setting the flag
without such a layer is not a supported public configuration. Local cases use
`LOCAL` and remain on the user's machine until deletion.

## Case retention

- Local deployments default new cases to `LOCAL`; structured cases and their
  encrypted local attachments remain until the user deletes them. The local
  broker is volatile and worker parsing occurs in a memory-backed temporary
  mount. A case delete removes active records; it does not claim forensic
  erasure of SQLite pages, host snapshots/backups, or already-dispatched work.
- Cloud deployments default new cases to `ANONYMOUS`. The structured case is
  assigned `expiresAt` at creation (seven days by default, configured with
  `OCDD_ANONYMOUS_CASE_TTL_DAYS`) and is logically deleted from the active
  database after that time. PostgreSQL storage pages, WAL, replicas, snapshots,
  and backups follow the deployment operator's documented retention and
  encryption controls; the application does not claim forensic erasure.
- `ACCOUNT` must be explicitly requested and never receives an automatic
  expiry. The reference API does not infer login state; a cloud deployment's
  authentication layer is responsible for allowing this value only for an
  authenticated account.
- Deleting an SQLite/PostgreSQL case cascades to artifacts stored in that same
  database. Before deleting a cloud structured case, the API scans the
  dedicated S3 transient prefix and physically deletes objects whose opaque
  `case-id-hash` matches. If S3 deletion fails, the API returns 503 and keeps
  the structured case/capability so the request can be retried.
- Artifact upload and case deletion share a database-backed exclusive lease
  across API workers. This prevents a successful deletion from being followed
  by a late object write. Lease rows contain opaque ownership tokens and expire
  for crash recovery; their TTL must exceed the maximum document-processing
  request time.
- Every S3 original must have a timezone-aware `expires-at` value. Missing,
  malformed, or elapsed expiry metadata makes reads fail closed and causes the
  object to be deleted. With the reference defaults, access ends at 55 minutes,
  a separate sidecar scans every minute, and four minutes of operational buffer
  remain before the configured 60-minute maximum deletion window.
- The purger has its own container, S3 credentials, heartbeat, healthcheck and
  restart policy; it does not depend on API, PostgreSQL, Valkey, or request
  traffic. Its unhealthy state or an object-store outage must be alerted as a
  retention incident. Standard S3/MinIO lifecycle expiration is day-granular,
  so a bucket lifecycle rule may be a defense-in-depth orphan fallback but
  cannot establish compliance with the 60-minute window.
- The transient-originals bucket must have **versioning disabled** and
  **Object Lock disabled**. Versioning can preserve an older object behind a
  delete marker, while Object Lock can reject physical deletion. Use a
  dedicated bucket/prefix and verify these controls before accepting uploads.
- Purger and health logs disclose only aggregate counts and exception class
  names, never case IDs, object keys, filenames, or object contents.
- OCR task envelopes are encrypted before entering the reference Valkey
  broker. That broker has snapshots, AOF, and its data volume disabled, but an
  envelope can remain in volatile memory until consumed, revoked, or the
  broker restarts. The 60-minute claim above therefore applies to S3 originals
  only. Public cloud acceptance requires locator-only task dispatch (or an
  independently verified equivalent) before claiming whole-system erasure.

## Cloud ingestion minimization

- The decoded cloud artifact limit is 10 MiB by default. The base64/JSON ASGI
  envelope has a separate 14,046,552-byte cap. The stream counter remains
  authoritative when `Content-Length` is absent, malformed, or understated.
  Oversized requests return 413 before base64 decode, OCR dispatch, evidence
  mutation, or object persistence.
- Title and seller-message uploads are never written to cloud object storage or
  sent to OCR. The structured ledger contains a generic locator and hash only.
  A title identity result is `UNKNOWN` unless the client explicitly supplies
  `identityTitleMatch`; no owner name is an accepted structured field.
- Other uploaded documents may create conservative dated/mileage event facts,
  but cloud cases omit generic page excerpts and user-authored labels so an
  unrecognized human name cannot become long-lived structured text.
- Local `.ocdd` packages are not assumed de-identified. Cloud import removes
  buyer/listing/evidence/history/scan/inspection narrative fields and requires
  analysis to be rerun from the remaining structured facts.
- These restrictions do not apply to local mode, where originals remain in the
  encrypted local artifact store until case deletion.

## Reference abuse controls

The cloud API has a bounded in-process sliding-window limiter for case
creation/import and artifact uploads. It keys only on the direct ASGI peer and
ignores all forwarded-client-IP headers unless rate limiting is implemented by
a separately trusted ingress. The reference Uvicorn command disables proxy
headers; enabling them requires an explicit trusted proxy allowlist. Because
process memory is not shared, this guard
does not aggregate across workers or replicas. Every public multi-worker or
multi-replica deployment must enforce an additional distributed Valkey-backed
gateway/WAF limit; the in-process limiter is only the single-instance reference
backstop.

The reference Compose file publishes only loopback ports and is not a public
production topology. Public ingress must terminate TLS at an external trusted
reverse proxy/API gateway, enforce the distributed limiter there, and monitor
object-store availability, purger heartbeat, aggregate deletion failures, and
the configured retention SLO. Never expose the bundled MinIO console, API, or
Web/API host ports directly to the Internet.
