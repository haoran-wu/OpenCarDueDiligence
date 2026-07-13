# Security Policy

OpenCarDueDiligence processes vehicle and transaction material that can contain
personal information. Treat a privacy or retention failure as a security
issue.

## Supported versions

This project has no supported stable release yet. Security fixes target the
current default branch while v0.1 remains alpha. Historical snapshots and
forks are not maintained by this policy.

## Reporting a vulnerability

Use the repository's **Security** tab and GitHub private vulnerability
reporting. Include the affected component, version/commit, impact, minimal
reproduction with synthetic data, and any suggested mitigation. Do not attach
real case material.

If private vulnerability reporting has not been enabled on the newly created
repository, contact the repository owner through a private method on their
GitHub profile and ask for a secure reporting channel. Do not put exploit
details or sensitive data in a public issue. General bugs without security or
privacy impact may use the bug-report template.

Maintainers should acknowledge a private report, triage severity and affected
versions, coordinate a fix and disclosure, and credit the reporter if requested
and safe. Alpha status is not a reason to disclose a reporter's identity or
case data.

## Sensitive material that must stay private

- Never report vulnerabilities that include a real VIN, title, driver license,
  license plate tied to a person, buyer/seller name or address, private message,
  marketplace cookie, provider credential, paid history report, or unredacted
  invoice in a public issue, pull request, log, screenshot, or fixture.
- S3 cloud originals are transient and target deletion within the configured
  TTL (one hour by default). The alpha reference broker is volatile and carries
  only encrypted OCR envelopes, but does not yet establish a whole-system
  deletion SLO. Logs must contain opaque case/evidence IDs only.
- VIN decode and transaction-context inputs use POST bodies. Do not put a VIN,
  identity comparison, title state, or other transaction context in a URL or
  query string, because access infrastructure commonly retains request URLs.
- The local OBD bridge is read-only, binds to loopback by default, and rejects
  clear-code, actuator, coding, and programming commands.
- The browser extension must never read or export cookies, run background
  marketplace crawls, or click a message Send button.
- `docker-compose.cloud.yml` is loopback-only and single-host reference code,
  not a public production configuration. Internet-facing deployments require
  an external trusted reverse proxy/API gateway with TLS termination,
  distributed rate limiting, and monitored retention/deletion alerts.
- The transient-originals bucket must have versioning and Object Lock disabled;
  otherwise a successful delete call may retain a historical version or be
  blocked from physically deleting the original.

This project is decision support, not a replacement for a licensed mechanic,
DMV, insurer, lender, or attorney.

## In scope

- case capability/authentication bypasses and cross-case access;
- retention, deletion, encryption, log-redaction, or archive-import failures;
- extension behavior that accesses cookies/private chats, background-crawls,
  or sends a message without an explicit final user action;
- OBD commands outside the reviewed read-only allowlist;
- report/evidence injection that changes deterministic safety, title, legal, or
  negotiation gates;
- dependency or deployment flaws exploitable in the reference code.

Third-party Marketplace, CARFAX, NMVTIS, OEM, DMV, cloud-provider, browser, or
vehicle vulnerabilities should be reported to their owners. Do not test this
project against a vehicle, seller account, or hosted service you do not own or
have explicit permission to assess.

## Dependency gates

CI runs `pip-audit` over the installed API, worker, and OBD runtime and fails on
known Python dependency vulnerabilities. It also runs `npm audit --omit=dev
--audit-level=high`, so high/critical production findings fail the build.

At the 2026-07-13 v0.1 candidate audit, the Python audit was clean after raising
the minimum supported `cryptography` and `pypdf` versions. npm reported one
upstream moderate PostCSS advisory through the stable Next.js package
(represented as two dependency findings). This is a dated audit snapshot, not
a promise about the current dependency graph. Do not run the proposed forced
fix: it selects an obsolete Next.js major. Track the stable framework fix and
keep all dynamic CSS/text values escaped in the meantime. Upstream tracker:
<https://github.com/vercel/next.js/issues/93604>.
