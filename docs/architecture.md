# Architecture

OpenCarDueDiligence is an evidence system with an optional language layer, not
an autonomous purchasing bot.

```text
current-page import / PDF / image / OBD / inspection
                         |
                         v
                 SourceEnvelope + Evidence
                         |
             deterministic facts and findings
              /          |            \
       valuation     risk gates     state rules
              \          |            /
                         v
          decision + negotiation + transaction plan
                         |
                         v
             optional bilingual LLM explanation
```

## Trust boundaries

- The Chrome extension reads one visible page only after a user gesture. It
  never exports cookies, visits result pages in the background, or presses
  Send.
- The OBD bridge is a loopback-only, token-protected read service. Every
  command passes a hard read-only allowlist before transport.
- A cloud S3 original is transient. The worker extracts pages, creates hashes
  and evidence locators, and removes its encrypted temporary source immediately.
  S3 objects carry an expiry timestamp and are purged by a dedicated
  sidecar that does not depend on API health. The default access cutoff is 55
  minutes, the purge scan is every minute, and the configured deletion ceiling
  is 60 minutes. The reference OCR broker is non-persistent but can retain an
  encrypted envelope in volatile memory until delivery or restart, so the
  alpha does not claim whole-system 60-minute erasure. A failed purger
  healthcheck or object-store outage is a retention incident. Title and
  identity names become only an equality result in cloud data.
- Model-level recalls, complaints, community reports, and generic DTCs are
  hypotheses or context. Only evidence from the subject vehicle can confirm a
  current-vehicle finding.

## Deployments

The domain API and JSON contracts are identical in both modes.

- Local: SQLite, encrypted attachment filesystem, a volatile Valkey worker
  queue, a memory-backed worker temporary directory, and localhost OBD bridge.
- Cloud: PostgreSQL, encrypted object storage, a volatile Valkey worker queue,
  managed key service, and independent transient-object purger. Anonymous
  structured cases are logically deleted from the active database after seven
  days. PostgreSQL pages, WAL, replicas, snapshots, and backups remain an
  operator retention boundary. Public acceptance additionally requires
  locator-only asynchronous document dispatch or an equivalent verified
  broker-retention control.

The optional local Ollama adapter is downstream of deterministic outputs.
Removing all model configuration
must not change valuation numbers, transaction hard stops, risk severities, or
required inspections.
