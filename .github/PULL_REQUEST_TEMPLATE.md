## Summary

Describe the user/developer problem and the smallest change that addresses it.

## Trust boundary

- Which deterministic output, evidence rule, or workflow changes?
- What remains `UNKNOWN`, requires confirmation, or fails closed?
- Can this affect `STOP`, legal drive-away, safety, title, valuation, retention,
  or automatic actions?

## Verification

List the exact commands and results. Use synthetic or redistributable fixtures.

```text
make test
make typecheck
make build
make smoke
```

## Checklist

- [ ] I kept the change focused and documented remaining limitations.
- [ ] I added/updated tests for deterministic behavior and failure paths.
- [ ] I did not commit personal data, real case material, secrets, cookies,
      paid reports, proprietary labor/diagnostic text, or unlicensed data.
- [ ] I recorded provenance, applicability, dates, and license/redistribution
      limits for any source or data change.
- [ ] I did not claim an unreviewed rule, model pack, real-hardware path, or
      reference deployment is production-ready.
- [ ] I reviewed privacy, retention, security, and migration effects.
- [ ] I updated public documentation and contracts when behavior changed.
- [ ] I ran `make audit` and `make docker-config` when the change is
      release/dependency/deployment-facing, or explained why they were skipped.

## Screenshots or reports

Optional. Use synthetic identifiers and redact all personal or licensed source
text. For report changes, include both extracted-text and raster-render checks.
