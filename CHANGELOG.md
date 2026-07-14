# Changelog

All notable changes to OpenCarDueDiligence are documented here. The project is
still alpha software and uses GitHub prereleases until its v1 acceptance gates
are complete.

## 0.1.0-alpha.3 - 2026-07-13

### Added

- a restrained production UI system with consistent SVG icons, semantic
  decision colors, responsive buyer-workflow navigation, and a guided first-run
  experience;
- accessible modal focus trapping, Escape-to-close, focus restoration, and
  mobile access to every case action;
- readable FastAPI field-validation errors and explicit fuel-type selectors;
- source-language disclosure for case findings that are intentionally not
  machine-translated.

### Changed

- the overview is decision-first: current recommendation, three priority
  checks, evidence coverage, repair exposure, market context, and the next safe
  action are presented before secondary details;
- evidence, inspection, negotiation, transaction, and comparison screens use
  progressive disclosure and buyer-facing language instead of API terminology;
- market ranges no longer imply that an offer boundary exists; opening, target,
  and ceiling values appear only after those values have actually been
  calculated;
- the mobile shell now uses one compact application header, an always-visible
  storage-mode disclosure, and a no-overflow bottom workflow bar down to 360 px;
- local and cloud deployments now show distinct, truthful storage disclosures;
  both reference brokers disable disk persistence, worker plaintext temporary
  files use memory-backed mounts, and the documentation scopes its 60-minute
  deletion target to S3 originals.

### Boundaries

- switching interface language does not machine-translate seller text,
  evidence excerpts, or findings already stored in another source language;
  the interface labels that boundary instead.
- the volatile encrypted OCR queue remains a documented public-cloud
  acceptance gap until task dispatch is locator-only or equivalently verified.
- case deletion means removal from active application storage, not forensic
  erasure of database pages, WAL/backups, snapshots, or container layers.

## 0.1.0-alpha.2 - 2026-07-13

### Added

- one-command local quickstart with private secret generation, health checks,
  browser launch, status, and safe stop/delete-data commands;
- a user-clicked, no-key NHTSA vPIC VIN decoder in the new-case and target-
  listing flows, with manual fallback and explicit privacy/title-verification
  disclosures;
- a release guard that rejects official paid-provider credentials, proprietary
  application licensing, and the former Redis server image;
- an explicit free-software commitment and provider access-cost metadata;
- per-case permanent deletion in the buyer UI, guarded by explicit confirmation.

### Changed

- the official application is now AGPL-3.0-or-later only, with no paid or
  proprietary edition;
- the default queue is the BSD-3-Clause Valkey server;
- optional prose rendering is local Ollama only; deterministic analysis needs
  no LLM, model, account, or API key;
- vehicle-history reports are presented as optional user-supplied evidence,
  not as a required CARFAX purchase;
- title status, seller/title identity, and VIN matching now use explicit
  unknown/match/mismatch states so known fatal mismatches reach `STOP`;
- an unscanned case now says “no DTC scan data” instead of implying that no
  codes were reported.

### Boundaries

- PPI, insurance, tax, registration, permits, towing, repairs, OBD hardware,
  optional reports, and self-hosting infrastructure can still carry external
  real-world costs. The project does not sell or receive commission from them.
