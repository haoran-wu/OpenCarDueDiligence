# Publication-gated model knowledge

`model_family_manifests_v1.yaml` contains 20 discovery manifests. Each family
now has one source-screened **DRAFT** applicability pack drawn from an official
NHTSA recall signal. These are research notes, not reliability verdicts. None
has named human approval, none publishes a repair price, and the API never
returns their claims to buyers while either family or pack remains `DRAFT`.

The two review workbooks and their unresolved publication blockers live under
`data/knowledge/drafts/`. Rebuild the runtime draft inventory deterministically
with `python scripts/merge_knowledge_drafts.py`; the script refuses to merge a
published pack, named reviewer, or unreviewed planning cost.

## Runtime release gate

The API reads only `applicability_packs` for buyer-facing claims. A claim is
returned only when all of the following are true:

1. the exact make and model family is `PUBLISHED`;
2. `VehicleSpec` contains year, generation, platform, engine, transmission,
   drivetrain, and production date;
3. exactly one pack matches every field (inclusive year/date ranges; exact
   normalized string membership, never fuzzy or substring matching);
4. that pack is `PUBLISHED`, names its human reviewer and review date, contains
   all three repair scenarios, and has internally consistent source provenance.

Missing data, draft/retired/blocked status, near matches, or overlapping packs
produce `UNKNOWN / INSPECT` and no claims.

## Authoring shape

Work starts as `DRAFT`. Do not change either the family or pack to `PUBLISHED`
until the runtime schema and human review requirements pass.

```json
{
  "id": "unique-exact-pack-id",
  "publication_status": "DRAFT",
  "applicability": {
    "market": "US",
    "model_year_start": 2020,
    "model_year_end": 2020,
    "generations": ["exact generation identifier"],
    "platforms": ["exact platform identifier"],
    "engines": ["exact engine identifier"],
    "transmissions": ["exact transmission identifier"],
    "drivetrains": ["exact drivetrain identifier"],
    "production_date_start": "2020-01-01",
    "production_date_end": "2020-12-31"
  },
  "claims": [],
  "sources": [],
  "reviewed_at": null,
  "reviewer": null
}
```

The executable Pydantic schema is in `services/api/app/knowledge.py` and is
also exposed through FastAPI OpenAPI. The example above contains no mechanical
assertion and cannot be published in its empty state.
