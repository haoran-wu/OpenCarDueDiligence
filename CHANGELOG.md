# Changelog

All notable changes to OpenCarDueDiligence are documented here. The project is
still alpha software and uses GitHub prereleases until its v1 acceptance gates
are complete.

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
