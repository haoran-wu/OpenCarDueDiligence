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
- A cloud upload is transient. The worker extracts pages, creates hashes and
  evidence locators, and removes its encrypted temporary source immediately.
  S3 originals carry an expiry timestamp and are purged by a dedicated
  sidecar that does not depend on API health. The default access cutoff is 55
  minutes, the purge scan is every minute, and the configured deletion ceiling
  is 60 minutes. A failed purger healthcheck or object-store outage is a
  retention incident. Title and identity names become only an equality result
  in cloud data.
- Model-level recalls, complaints, community reports, and generic DTCs are
  hypotheses or context. Only evidence from the subject vehicle can confirm a
  current-vehicle finding.

## Deployments

The domain API and JSON contracts are identical in both modes.

- Local: SQLite, encrypted filesystem, Redis worker, localhost OBD bridge.
- Cloud: PostgreSQL, encrypted object storage, Redis worker, managed key
  service, independent transient-object purger. Anonymous structured cases
  expire after seven days.

LLM adapters are downstream of deterministic outputs. Removing all LLM keys
must not change valuation numbers, transaction hard stops, risk severities, or
required inspections.
