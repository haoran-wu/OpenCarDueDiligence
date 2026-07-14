# v1 readiness

OpenCarDueDiligence is currently a **v0.1 implementation candidate**, not a
signed-off v1 release. The repository intentionally fails closed where an
external fact, human review, licensed data source, or hardware acceptance is
still missing.

## Implemented and testable

| Area | Current state |
| --- | --- |
| Case and evidence ledger | API, persistence, source envelopes, hashes, encrypted attachments, and `.ocdd` import/export are implemented. |
| Buyer decisions | Deterministic `STOP / INSPECT / NEGOTIATE / BUY_CANDIDATE` analysis with unknown-evidence and evidence-coverage gates is implemented. |
| Listing and comparison | User-triggered extension capture, manual Web import, structured JSON API import, watchlist price history, conservative same-seller-type/reference-kind comparable selection, and multi-car comparison are implemented. CSV files can be preserved and parsed as evidence artifacts, but v0.1 does not yet turn arbitrary CSV rows into listing snapshots. Comparable admission is strict only for the configuration fields actually supplied; missing configuration stays unknown and cannot be treated as a match. Listing platforms are recorded but not yet separated into independent valuation populations. |
| History documents | Text-first PDF processing, OCR fallback, page/date/mileage provenance, and contradiction checks are implemented. |
| Inspection and diagnostics | Five-stage checklist and manual generic-OBD Web entry are implemented. Structured scan ingestion, a read-only BLE ELM327 bridge service, diagnostic branches, and four repair channels exist in the backend. Direct Web BLE pairing, scan-file upload, and the full scenario/channel cost UI are not implemented. |
| Negotiation | Traceable target/opening/ceiling calculation and four-stage bilingual message drafting are implemented. Messages are never sent automatically. |
| Transaction planning | NJ/NY/CT rule bundles, legal-drive-away gates, and official-source freshness checks are implemented. The Web form and offline demonstration plan have bilingual UI copy, but authoritative server-generated state-rule tasks are currently English source text. Unreviewed rules remain `INSPECT` and require DMV confirmation. |
| User interfaces | API-first bilingual Next.js PWA, traceable JSON/PDF report flow, Chrome MV3 extension, loading/empty/error states, and local/cloud Compose manifests are implemented. PDF findings resolve stable evidence IDs to available provider/page/locator/reference data. Chinese reports localize fixed system prose; evidence excerpts, provider names, user-entered text, and external DTC descriptions remain verbatim and are explicitly labeled as source text. The project does not claim general-purpose translation of third-party evidence. Chinese PDFs embed the bundled OFL-licensed Noto Sans SC font; missing or unusable font assets fail closed, and automated acceptance checks cover both extracted text and Poppler raster output. |
| Cloud privacy reference | Per-case capabilities, disabled case listing, encrypted uploads, transient raw artifacts, and redacted structured records are implemented as a reference deployment. |

## Known implementation gaps

- CSV is accepted as a document artifact, not yet as a row-to-listing batch
  importer; no authorized market feed is registered in the runnable app.
- Valuation produces an asking, sold, or external-reference range for one
  seller-type population. Negotiation applies evidence-bound deductions, but
  `ValuationResult` does not yet expose a separate repair-adjusted vehicle-value
  field or a calibrated one-year abnormal-repair forecast.
- The open repair-cost model has scenario ranges and four shop channels, but no
  licensed ZIP3 labor-time/rate corpus or validated invoice corpus. The Web UI
  currently summarizes a broad exposure range rather than exposing every
  minimum/likely/worst diagnostic branch and shop-channel estimate.
- All 20 model-family packs remain publication-gated DRAFT material, so the
  runnable buyer UI does not yet provide model-specific reliability claims.
- NHTSA VIN decoding and model-level recall signals are present; complaint,
  TSB, and NCAP ingestion are not yet implemented.
- The state-rule server returns authoritative task text in English. Full
  deterministic Chinese server-plan localization remains to be added.
- The extension has unit-tested payload boundaries but still needs acceptance
  against real, changing Marketplace DOM snapshots under an approved terms
  review.

## Required before the v1 label

1. A named reviewer must verify and sign the NJ, NY, and CT rule bundles. Until
   then the transaction engine must not claim that a buyer can legally drive
   away.
2. A named automotive reviewer must verify exact generation, engine,
   transmission, production-date applicability, confirmation tests, and cost
   evidence for all 20 model-family packs. They remain `DRAFT`; the runtime
   resolver returns `UNKNOWN/INSPECT` for unpublished claims.
3. The BLE bridge must pass the planned real reference-device and vehicle or
   standards-compliant simulator acceptance. Automated tests prove the command
   allowlist and Mode 04/write rejection, not real-radio compatibility.
4. The loopback-only local Compose stack is built, started, health-checked, and
   torn down in GitHub Actions. The cloud reference stack still needs an
   end-to-end acceptance run with PostgreSQL, Valkey, and an S3-compatible
   object store; static manifest validation does not replace that test. Its
   volatile broker still carries encrypted document envelopes, so public cloud
   acceptance also requires locator-only task dispatch or an independently
   verified equivalent retention control.
5. A public deployment needs managed KMS, TLS, secret rotation, a distributed
   rate limiter or gateway, monitoring, backups, and an independently operated
   one-hour S3 artifact purger. Development credentials in the reference
   Compose file are never production credentials, and the S3 deadline must not
   be represented as whole-system erasure until the broker gap is closed.
   PostgreSQL storage, WAL, replicas, snapshots, and backups also need explicit
   encryption and retention acceptance; application SQL deletion is not
   forensic erasure.
6. Deterministic analysis works without any LLM. The optional local Ollama
   adapter has isolated contract tests but is not yet exposed as an end-to-end
   report or UI route. The official project ships no hosted or paid LLM
   adapter and requires no API key.
7. Meta terms review is required before publishing a formal Marketplace
   provider. The extension is deliberately limited to a user click on the
   currently visible listing and never exports cookies, background-crawls, or
   clicks Send.
8. User-supplied history, valuation, labor-time, and repair-cost sources still
   require compatible rights. The official provider registry accepts only
   free/open data or user-supplied artifacts and does not redistribute CARFAX,
   ALLDATA, Mitchell, RepairPal, KBB, or Marketplace data.

## Release evidence

Run these commands from the repository root and archive their output with the
release candidate:

```bash
make test
npm run typecheck
npm run build
make smoke
make audit
python scripts/check_rule_sources.py
make docker-config
```

`make audit` fails on high or critical Node production advisories. A known
moderate PostCSS advisory inherited through the supported stable Next.js line
is documented in `SECURITY.md` and must be re-evaluated before release rather
than “fixed” with a forced downgrade to an obsolete Next.js major.

The v1 tag may be created only after every item above either passes or is
replaced by a documented, independently reviewed acceptance record. A low
budget, missing credential, or missing external reviewer is not permission to
turn an unknown into a green result.
