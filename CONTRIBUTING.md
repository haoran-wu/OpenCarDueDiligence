# Contributing

Changes are welcome when they preserve the evidence boundary: unchecked facts
remain `UNKNOWN`, diagnostic codes create testable branches rather than parts
verdicts, and legal or transaction rules cite an official source plus review
date.

This is alpha software with safety, legal, privacy, and third-party-data
boundaries. A useful contribution makes uncertainty more visible; it does not
turn missing evidence into a green result.

## Before starting

- Search existing issues and pull requests.
- For a large feature, schema change, new provider, or new data source, open a
  proposal first so licensing and trust boundaries can be reviewed.
- Use synthetic or explicitly redistributable fixtures. Do not attach a real
  vehicle-history report merely to demonstrate a parser bug.
- Read [`docs/architecture.md`](docs/architecture.md),
  [`docs/data-governance.md`](docs/data-governance.md), and
  [`THIRD_PARTY_DATA.md`](THIRD_PARTY_DATA.md).

## Local setup

Python 3.12 and Node.js 20 match CI. From the repository root:

```bash
make bootstrap
make test
make typecheck
make build
make smoke
```

`make audit` and `make docker-config` are also required for a release-facing
change. The latter requires Docker Compose. The weekly official-source check
requires network access:

```bash
make audit
python scripts/check_rule_sources.py
make docker-config
```

## Pull requests

Keep a pull request focused and explain:

- the user problem and trust boundary;
- which deterministic behavior changed;
- tests and fixtures added;
- privacy, security, licensing, and retention effects;
- any remaining unknowns or required human/hardware review.

Do not describe an unreviewed rule, model pack, real-radio test, or reference
deployment as production-ready. UI screenshots and logs must use synthetic
identifiers and redacted text.

## Rules, knowledge, diagnostics, and provider data

Data contributions must include:

- exact applicability, including generation/platform, engine, transmission,
  drivetrain, and production date where relevant;
- source URL or stable origin, retrieval/effective date, and content hash;
- license/use basis and redistribution limits;
- evidence level and required confirmation test;
- named human review date when a legal, safety, repair, or model-specific claim
  is proposed for publication.

Community anecdotes may create a question to inspect. They cannot by themselves
confirm a defect, reduce value, or authorize a legal transaction step.

Do not copy proprietary diagnostic descriptions, labor times, prices, or paid
report prose into source files or fixtures. A provider plugin must declare its
credential, retention, license, and redistribution behavior.

## Privacy

Do not submit a real VIN, title, driver license, license plate tied to a person,
buyer or seller name/address, private message, marketplace cookie, provider
credential, paid history report, or unredacted service invoice to a public
issue, fixture, commit, screenshot, or CI log. If a security report needs
sensitive context, follow [`SECURITY.md`](SECURITY.md) instead.

## Licensing of contributions

Contributions are accepted under the license already governing the path being
modified:

- application and service code: AGPL-3.0-or-later;
- `packages/plugin-sdk`: Apache-2.0;
- first-party rules and knowledge under `data/`: CC BY-SA 4.0 unless a
  file-specific manifest says otherwise;
- documentation: the repository license unless the file says otherwise.

A public pull request does not silently transfer copyright or grant additional
proprietary relicensing rights. If maintainers want to include an external
contribution in a separately licensed commercial distribution, they must first
obtain an explicit contributor agreement for that contribution. Contributors
must have the right to submit everything they include.

## Review expectations

Maintainers may keep a technically correct change in draft when it lacks a
license basis, official source, named reviewer, real-hardware acceptance, or a
safe migration path. That is a release gate, not permission to weaken a
fail-closed result.

Before requesting final review, make sure the applicable commands above pass
and complete the pull-request checklist.
