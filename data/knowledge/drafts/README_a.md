# Vehicle knowledge research pack A

Status: **DRAFT — research input only**. This file is deliberately outside the
runtime manifest and has not been approved by a named human reviewer. It must
not be shown to users as published model knowledge.

The companion file, `families_a.json`, contains one narrowly scoped U.S.
safety signal for each of the first ten model families. Each signal is based on
an NHTSA campaign record plus the manufacturer's Part 573 filing hosted by
NHTSA. The entries are bilingual and describe screening and confirmation
branches only. They do not assert that an individual VIN is affected, that a
recall repair is incomplete, or that the listed symptom has been diagnosed.

## Selected signals

| Family | Draft applicability tuple | Official signal |
|---|---|---|
| Ford F-150 | MY 2011–2013; P415; 3.5L EcoBoost; 6R80; RWD/4WD | 19V075 / Ford 19S07 — intermittent output-speed-sensor signal and unintended first-gear downshift |
| Ford Escape | MY 2013; C520; 1.6L EcoBoost; 6F35; FWD/AWD | 13V583 / Ford 13S12 — localized cylinder-head overheating, oil leak and fire risk |
| Ford Explorer | MY 2016 subset; D4/U502; 2.3L EcoBoost; 6F35; FWD | 20V692 / Ford 20S63 — link-shaft bracket fracture and loss of motive power |
| Chevrolet Silverado 1500 | MY 2014–2018 subset; K2XX; 5.3L L83; 6L80; RWD/4WD | 19V645 / GM N192268490 — reduced brake vacuum assist |
| Chevrolet Equinox | MY 2014–2015 subset; Theta II; 2.4L LEA; 6T45; FWD/AWD | 22V165 / GM N212352530 — front-wiper module corrosion/failure |
| Ram 1500 | MY 2014–2018; DS; 3.0L EcoDiesel; 8HP70; RWD/4WD | 20V475 / FCA W58 — crankshaft tone-wheel delamination and possible stall |
| Toyota Camry | MY 2018–2019 non-hybrid subset; XV70/TNGA-K; A25A-FKS; UA80E; FWD | 21V890 / Toyota 21TA09 — vacuum-pump failure and reduced brake assist |
| Toyota Corolla Hatchback | MY 2019; E210/TNGA-C; M20A-FKS; K120 CVT; FWD | 18V901 / Toyota J17/J07 — torque-converter impeller separation and loss of motive power |
| Toyota RAV4 | MY 2019–2020 conventional subset; XA50/TNGA-K; A25A-FKS; UA80E; FWD | 20V064 / Toyota 20TA04 — engine-block porosity and coolant/oil leakage |
| Toyota Tacoma | MY 2016–2017 subset; N300; 2GR-FKS; AC60F; 4WD | 17V356 / Toyota H0H — crank-position-sensor malfunction, misfire and possible stall |

The production dates in the JSON come from the affected-vehicle date ranges in
the cited Part 573 filings. A narrower powertrain/drivetrain tuple is used where
the campaign covers a broader vehicle population; narrowing a recall population
does **not** establish VIN applicability.

## Safety and diagnostic treatment

- Each claim states whether the official signal can cause a loss of motive
  power, reduced brake assist, fire exposure, or reduced visibility.
- Basic generic OBD-II coverage is described conservatively. A code-free scan
  never clears a mechanical, brake, wiper, structure, body-module, or recall
  finding. Manufacturer modules and recall completion generally require an
  enhanced scan tool and/or OEM dealer records.
- Every claim requires a VIN-level NHTSA/OEM lookup and a physical or functional
  confirmation test appropriate to the failure mode.
- `minimum`, `most_likely`, and `worst_reasonable` scenarios are diagnostic or
  remedy branches, not parts-cannon prescriptions. Every `planning_cost_usd` is `null` and
  every cost confidence is `UNKNOWN`.
- Exact DTCs are intentionally absent unless the cited official filing supports
  them. Symptoms such as MIL illumination or misfire do not justify inventing a
  particular code.

## Link and schema checks performed 2026-07-13

- All 10 NHTSA campaign API URLs returned HTTP 200 JSON.
- All 10 manufacturer Part 573 URLs hosted at `static.nhtsa.gov` returned HTTP
  200 PDFs.
- `families_a.json` validates as a standalone `KnowledgeManifest` using
  `services/api/app/knowledge.py`.
- Additional structural assertions check 10 unique families, 10 unique packs,
  10 unique claims, resolvable source IDs, manifest status
  `draft_research_only`, DRAFT family/pack status, no named
  pack reviewer, `retrieved_at=2026-07-13`, and empty/UNKNOWN planning costs.

`claim.reviewed_at=2026-07-13` is present only because the current schema
requires the field. In this draft it means “preliminary source-screen date,”
not human approval. Pack-level `reviewed_at` and `reviewer` remain unset.

## Required human review before buyer-facing/runtime publication

The research files themselves are published in this source repository for
transparent review. “Publication” below means enabling a claim in runtime or
showing it as approved buyer guidance, which remains blocked while the pack is
`DRAFT`.

1. Confirm each generation/platform label and every engine/transmission/
   drivetrain combination against OEM build or service information. The recall
   filings establish the safety signal and broad affected population; they do
   not necessarily spell out every engineering platform code used in this
   research tuple.
2. Recheck the production-date boundary and whether it is a vehicle-build range
   rather than a component-production range.
3. Test a sample VIN both in NHTSA and the manufacturer portal. A model-level
   campaign cannot show whether a particular VIN is included or whether its
   remedy is complete.
4. Review the English and Chinese wording for technical accuracy and ensure the
   text does not imply prevalence, current defect status, or guaranteed remedy.
5. Confirm that referenced official documents may be linked under the project's
   provenance policy. This pack links sources and does not bundle or redistribute
   the PDFs.
6. Add region- and shop-type-specific repair costs only through the governed
   repair-cost pipeline; do not infer costs from these recall documents.
7. Record a named reviewer, review date, and approval decision before changing
   any family or pack from `DRAFT` to `PUBLISHED`.
