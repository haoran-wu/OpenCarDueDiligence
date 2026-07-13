# OpenCarDueDiligence

[![CI](https://github.com/haoran-wu/OpenCarDueDiligence/actions/workflows/ci.yml/badge.svg)](https://github.com/haoran-wu/OpenCarDueDiligence/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

OpenCarDueDiligence is a bilingual, evidence-first used-car due-diligence
toolkit for U.S. private-party buyers. It combines listing snapshots, user-provided
history reports, VIN/safety data, OBD observations, inspection findings,
transparent valuation, negotiation guidance, and state-specific transaction
steps without turning an LLM into the source of truth.

> [!WARNING]
> **Alpha / evaluation software.** This repository is a **v0.1 implementation
> candidate**, not a signed-off v1 release and not a public production service.
> Do not rely on it alone to buy, register, insure, value, or diagnose a
> vehicle. See [`docs/v1-readiness.md`](docs/v1-readiness.md) for the remaining
> human, hardware, deployment, licensing, and security acceptance gates.

The project is useful as a structured second opinion: it keeps an evidence
ledger, exposes what is still unknown, turns codes and symptoms into tests
rather than parts verdicts, and produces a reviewable inspection, negotiation,
and transaction checklist. It is not an autonomous buyer, a vehicle warranty,
or a substitute for an independent pre-purchase inspection (PPI).

## Intended workflow

1. Create a case and add a reviewed listing snapshot.
2. Import only reports, photos, scans, and records that you are authorized to
   use for that case.
3. Resolve the exact engine, transmission, drivetrain, body style, and
   production date instead of analyzing a model name alone.
4. Complete the five-stage self-inspection and obtain an independent PPI for
   material mechanical or structural uncertainty.
5. Re-run deterministic analysis; inspect every cited source and unknown.
6. Use the negotiation and transaction outputs as checklists, then verify
   current requirements with the relevant DMV, insurer, and professionals.

## What is implemented

- FastAPI case/evidence/valuation/risk/negotiation/transaction API
- bilingual Next.js dashboard plus a user-triggered Chrome extension
- JSON/PDF reports with human-readable evidence references (provider, page,
  locator/reference, and stable evidence ID). Chinese reports deterministically
  localize system-owned findings, unknowns, and next actions; evidence excerpts,
  provider names, user notes, and external DTC descriptions remain verbatim and
  are explicitly labeled as source text rather than silently translated. The
  API embeds the bundled OFL-licensed Noto Sans SC font in Chinese PDFs and
  fails closed if the font is missing or cannot be registered, avoiding a
  text-extractable but visually blank report.
- deterministic NJ/NY/CT private-sale rule packs
- five-stage inspection, generic DTC diagnostic trees, and publication-gated
  20-family model manifests (one official-source DRAFT pack per family; all
  buyer-facing claims remain blocked pending exact applicability review)
- read-only BLE ELM327 bridge plus scan-file imports
- local Docker stack with SQLite/Redis and a loopback-only cloud reference
  stack

## Deliberate boundaries

- No background Marketplace crawling, cookie access, automatic message send,
  payment, signature, purchase, or vehicle programming.
- No bundled CARFAX, NMVTIS, KBB, RepairPal, ALLDATA, Mitchell, Marketplace,
  or other proprietary dataset. Users must bring data they may lawfully use.
- No claim that generic OBD covers ABS, SRS, body, hybrid, or OEM modules.
- No claim that a model-level recall result proves a VIN-specific remedy.
- No published reliability claim from the 20 draft model-family manifests
  until an automotive reviewer signs the exact applicability.
- No legal-drive-away approval from the unreviewed NJ/NY/CT rule packs. Stale
  or unsigned rules require direct DMV confirmation.

## Quick start

Prerequisites for the Docker path are Git and Docker Engine/Desktop with
Compose v2. From the repository root:

```bash
cp .env.example .env
```

The checked-in worker envelope key is a public development fallback. Before
importing any real personal document, generate a new key and set it as
`OCDD_WORKER_ENVELOPE_KEY` in `.env`:

```bash
python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

After saving that value in `.env`, start the stack:

```bash
docker compose up --build
```

Then open `http://localhost:3000`. API documentation is at
`http://localhost:8000/docs`; the local OBD bridge defaults to
`http://127.0.0.1:8765` and should normally run directly on the host so it can
access Bluetooth. The dashboard starts empty: choose **New case**, add a
listing, and leave anything you have not actually checked as unknown.

Useful root commands:

```bash
make bootstrap       # Python editable installs + npm ci
make test            # all Python and TypeScript tests
make typecheck       # TypeScript type checking
make build           # production web/extension/package builds
make smoke           # in-process candidate journey, including NJ/NY title gates
make audit           # Python dependency audit + high/critical Node gate
make docker-config   # validate both Compose manifests
```

The local Compose stack runs `web`, `api`, `worker`, and `redis`, stores
structured data in SQLite, and wraps attachment blobs in AES-GCM envelopes.
API and Web ports bind to
`127.0.0.1` by default because local mode has no remote-user authentication;
do not change them to an all-interface bind on a shared or untrusted network.
It does **not** expose Bluetooth to a container. Start the read-only bridge on
macOS/Linux directly instead:

```bash
source .venv/bin/activate
export OCDD_OBD_BRIDGE_TOKEN='replace-with-a-random-local-token'
uvicorn obd_bridge.service:app --app-dir services/obd-bridge \
  --host 127.0.0.1 --port 8765
```

The loopback-only, single-host cloud reference adds PostgreSQL and an
S3-compatible MinIO store. Its defaults are development credentials only; all
published host ports bind to `127.0.0.1`. It is not a public production
configuration:

```bash
docker compose -f docker-compose.cloud.yml config --quiet
docker compose -f docker-compose.cloud.yml up --build
```

Before any public deployment, replace every database/object-store credential,
set `NEXT_PUBLIC_OCDD_API_URL` to the browser-reachable HTTPS API origin, and
use managed KMS. Put the services behind an external reverse proxy/API gateway
that terminates TLS and provides distributed rate limiting and monitored
alerts; do not expose these Compose ports directly. The transient-originals
bucket must have versioning and Object Lock disabled so physical deletion does
not leave an older version or retained object behind.
Anonymous cloud cases use a one-time `X-OCDD-Case-Token` capability returned
only on create/import; clients must retain it and send it on every case request.
The reference API stores only a digest and disables cloud case listing. Do not
put this token in URLs, analytics, logs, screenshots, or an unencrypted export.
The Web app is API-first and shows loading, empty, and error states without
inserting sample vehicles. `NEXT_PUBLIC_OCDD_ENABLE_DEMO=true` is an explicit
UI-development-only opt-in. The reference browser client stores capabilities
by opaque case ID in session storage and sends them only in the request header;
closing the browser session removes that recovery copy.

Development without Docker:

```bash
make bootstrap
make dev-api       # terminal 1
make dev-web       # terminal 2
```

This path requires Python 3.11+ (3.12 is used in CI), Node.js 20+, npm, and
Redis/OCR services when exercising the Celery path. Docker installs the worker's
Poppler and English/Simplified-Chinese Tesseract packages. A simple in-process
API run can parse text PDFs without the OCR worker.

### Chrome extension

Build the extension and load the unpacked directory in a Chromium browser:

```bash
npm --workspace @ocdd/extension run build
```

Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**,
and select `apps/extension/dist`. The extension asks the user to review the
visible fields before import. It can fill reviewed message text into a visible
composer, but it never clicks Send.

Marketplace markup changes frequently. The extraction boundary is unit tested,
but real-site compatibility and terms approval are still v1 acceptance gates.

## Repository map

```text
apps/web              Next.js buyer workspace
apps/extension        user-triggered Chrome MV3 helper
services/api          deterministic FastAPI domain service
services/worker       transient text extraction and OCR
services/obd-bridge   loopback-only, read-only BLE ELM327 service
packages/contracts    shared TypeScript contracts
packages/plugin-sdk   Apache-2.0 provider interfaces
data                  first-party rules, checklists, and draft knowledge
docs                  architecture, governance, safety, and release gates
```

## Testing

The complete local acceptance sequence is:

```bash
make test
make typecheck
make build
make smoke
make audit
python scripts/check_rule_sources.py
make docker-config
```

The live source check needs network access, and `make docker-config` requires
Docker Compose. Passing automated tests does not replace the real BLE,
container-stack, DMV-rule, or automotive-review gates listed in
[`docs/v1-readiness.md`](docs/v1-readiness.md).

## Non-negotiable behavior

- Unknown evidence remains unknown; absence of a code is not proof of health.
- DTCs produce diagnostic branches, not a forced parts replacement.
- No seller trust decision may use name, ethnicity, or neighborhood.
- The extension never background-scrapes or sends a message automatically.
- Insurance, bill of sale, and title do not by themselves authorize driving;
  transaction plans require a legal registration/plate/permit or transport.

## Licensing

The application is dual licensed under AGPL-3.0-or-later or a separate
commercial license. The plugin SDK is Apache-2.0. First-party rule/knowledge
data is CC BY-SA 4.0 unless its manifest says otherwise. The bundled Noto Sans
SC report font remains under the SIL Open Font License 1.1; see
`services/api/app/assets/fonts/README.md` and `NOTICE.md`.

See [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`SECURITY.md`](SECURITY.md), [`THIRD_PARTY_DATA.md`](THIRD_PARTY_DATA.md), and
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) before opening an issue or pull
request. Never post a real VIN, title, identity document, seller address,
private conversation, paid report, provider credential, or marketplace cookie
in this public repository.
