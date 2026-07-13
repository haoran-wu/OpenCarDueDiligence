# Model-family research pack B (DRAFT)

`families_b.json` is a standalone, schema-valid research manifest for the ten
families assigned to pack B. It is **not** merged into the runtime manifest and
contains **zero published claims**. Every family and applicability pack is
`DRAFT`; each pack has `reviewer: null` and `reviewed_at: null`.

The claim-level `reviewed_at: 2026-07-13` field is required by the executable
schema. In this file it means only “desk-research snapshot date.” It does not
represent human review or approval.

## Selected official signals

| Family | Exact draft slice | Official signal | Primary official filing |
|---|---|---|---|
| Toyota Prius | 2010–2014 XW30/ZVW30 hybrid, production 2009-03-31–2014-02-04 | inverter IPM thermal stress / possible hybrid-system shutdown | [NHTSA 18V-684 Part 573](https://static.nhtsa.gov/odi/rcl/2018/RCLRPT-18V684-1808.PDF) |
| Honda Civic | 2016 tenth-generation FC2 4-door 2.0L CVT FWD, production 2015-03-17–2016-10-03 | VSA ECU software can prevent EPB application | [NHTSA 16V-725 Part 573](https://static.nhtsa.gov/odi/rcl/2016/RCLRPT-16V725-8766.PDF) |
| Honda Accord | 2019 tenth-generation CV1 1.5T CVT FWD subset, production 2018-10-27–2019-02-08 | low-pressure fuel-pump impeller deformation / stall | [NHTSA 20V-314 Part 573](https://static.nhtsa.gov/odi/rcl/2020/RCLRPT-20V314-2564.PDF) |
| Honda CR-V | 2007–2011 third-generation RE3/RE4 2.4L 5AT, production 2006-03-06–2011-12-05 | salt-belt rear-frame corrosion / trailing-arm detachment | [NHTSA 23V-228 Part 573](https://static.nhtsa.gov/odi/rcl/2023/RCLRPT-23V228-3230.PDF) |
| Nissan Rogue | 2014–2016 T32 2.5L Xtronic, production 2013-07-25–2016-12-31 | driver-footwell water/salt intrusion into dash harness connector | [NHTSA 22V-024 Part 573](https://static.nhtsa.gov/odi/rcl/2022/RCLRPT-22V024-3229.PDF) |
| Nissan Altima | 2013–2018 L33 2.5L Xtronic FWD, production 2012-03-06–2018-08-17 | secondary hood-latch binding / hood opening | [NHTSA 20V-315 Part 573](https://static.nhtsa.gov/odi/rcl/2020/RCLRPT-20V315-1575.PDF) |
| Jeep Grand Cherokee | 2014–2020 WK2 3.0L EcoDiesel 8AT 4WD, production 2012-12-19–2019-10-13 | crankshaft tone-wheel magnetic-material delamination / stall | [NHTSA 23V-411 Part 573](https://static.nhtsa.gov/odi/rcl/2023/RCLRPT-23V411-5922.PDF) |
| Jeep Wrangler | 2018–2023 JL 3.6L 6MT 4WD subset, production 2017-08-23–2023-02-16 | clutch pressure-plate overheating / fracture / fire | [NHTSA 23V-116 Part 573](https://static.nhtsa.gov/odi/rcl/2023/RCLRPT-23V116-1538.PDF) and [FCA recall instructions, revision 3](https://static.nhtsa.gov/odi/rcl/2023/RCRIT-23V116-7715.pdf) |
| Subaru Outback | 2020 BT 2.5L Lineartronic AWD subset, production 2019-07-15–2020-08-13 | TCU programming / drive-chain slip and possible breakage | [NHTSA 21V-955 Part 573](https://static.nhtsa.gov/odi/rcl/2021/RCLRPT-21V955-7341.PDF) |
| Subaru Forester | 2019 SK 2.5L Lineartronic AWD, production 2018-07-04–2019-03-21 | aluminum PCV-valve separation / oil entry / possible power loss | [NHTSA 19V-856 Part 573](https://static.nhtsa.gov/odi/rcl/2019/RCLRPT-19V856-4949.PDF) |

All eleven linked PDFs above returned HTTP 200 with `application/pdf` on
2026-07-13. Only NHTSA-hosted manufacturer filings and recall instructions were
used. The project stores links and concise factual metadata; it does not copy or
redistribute the source PDFs. The FCA repair-instruction source explicitly has
reproduction restrictions, so its use is link-only with a short factual remedy
summary.

## Buyer-facing/runtime publication blockers and required human review

These DRAFT research files are intentionally visible in the source repository
so contributors can audit them. They remain fail-closed at runtime; the
“publication” blockers below apply to presenting any entry as approved buyer
guidance, not to reviewing the draft source on GitHub.

1. **VIN-level applicability and completion:** a model/date match never proves
   that a specific VIN is included or that its recall is open. Confirm in both
   NHTSA and the OEM system immediately before a buyer-facing report.
2. **Mechanical-token audit:** the Part 573 filings establish model years,
   production windows, signal, consequence, and remedy, but several filings do
   not enumerate every platform/engine/transmission/drivetrain token. A human
   reviewer must cross-check these exact draft tokens against an official OEM
   build/VIN source. This is especially important for the Accord, CR-V, Rogue,
   Altima, Grand Cherokee, Wrangler, and Outback subset mappings.
3. **Plant/VIN boundaries:** NHTSA production windows are broad possible ranges
   and may include vehicles not sold in the US or vehicles not fitted with the
   suspect part. Do not convert these bounds into prevalence claims.
4. **Superseding campaigns:** check for amendments, superseding campaigns, and
   remedy revisions. The Wrangler pack already cites a later dealer instruction;
   exact VIN status still controls, and 2021 vehicles may also require review of
   NHTSA 24V-572 if applicable.
5. **No unsupported DTC mapping:** `associated_dtcs` is deliberately empty.
   Generic OBD limitations are stated, but no recall is reduced to a guessed DTC.
6. **No repair-price assertion:** all three scenario branches are diagnostic or
   campaign-handling paths. Every `planning_cost_usd` is `null` and every
   `cost_confidence` is `UNKNOWN`.
7. **Language and safety review:** a bilingual technical reviewer must confirm
   the Chinese terminology and ensure that stop-driving/tow language matches the
   current OEM instruction for the exact VIN.
8. **Source-use review:** verify final citation/redistribution treatment before
   publishing any derivative knowledge pack.

## Validation performed

The file was validated on 2026-07-13 with the repository's executable Pydantic
schema:

```bash
python -m json.tool data/knowledge/drafts/families_b.json >/dev/null
PYTHONPATH=services/api python - <<'PY'
from pathlib import Path
from app.knowledge import KnowledgeRegistry

registry = KnowledgeRegistry.load(
    Path("data/knowledge/drafts/families_b.json")
)
assert len(registry.manifest.families) == 10
assert all(f.publication_status.value == "DRAFT" for f in registry.manifest.families)
assert all(
    p.publication_status.value == "DRAFT"
    for f in registry.manifest.families
    for p in f.applicability_packs
)
assert all(
    scenario.planning_cost_usd is None
    and scenario.cost_confidence == "UNKNOWN"
    for f in registry.manifest.families
    for p in f.applicability_packs
    for claim in p.claims
    for scenario in claim.repair_scenarios
)
PY
```

Observed counts: 10 families, 10 draft packs, 10 draft claims, 0 published
claims.
