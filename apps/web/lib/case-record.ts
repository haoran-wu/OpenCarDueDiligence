import type {
  CaseRecord,
  CaseStatus,
  Decision,
  DiagnosticSummary,
  Evidence,
  InspectionStage,
  RiskAxis,
  RiskFinding,
  RiskLevel,
  TransactionPlan,
  ValuationResult,
  VehicleSpec,
} from "./types";
import { createInspectionTemplate } from "./inspection-checklist";

type UnknownRecord = Record<string, unknown>;

export function hasGenericPowertrainCoverage(coverage: string[]): boolean {
  return coverage.some((item) => item.trim().toLowerCase().includes("powertrain"));
}

const riskRank: Record<RiskLevel, number> = {
  unknown: 0,
  low: 1,
  moderate: 2,
  high: 3,
  critical: 4,
};

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function rows(value: unknown): UnknownRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function number(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && allowed.includes(value as T) ? value as T : fallback;
}

function camelOrSnake(source: UnknownRecord, camel: string, snake: string): unknown {
  return source[camel] ?? source[snake];
}

function latestTargetListing(listings: UnknownRecord[]): UnknownRecord {
  const targets = listings.filter((item) => item.isTarget === true || item.is_target === true);
  const candidates = targets.length ? targets : listings;
  return candidates.reduce<UnknownRecord>((latest, item) => {
    if (!Object.keys(latest).length) return item;
    const itemTime = Date.parse(text(camelOrSnake(item, "capturedAt", "captured_at")) || "") || 0;
    const latestTime = Date.parse(text(camelOrSnake(latest, "capturedAt", "captured_at")) || "") || 0;
    if (itemTime !== latestTime) return itemTime > latestTime ? item : latest;
    return (text(item.id) || "") > (text(latest.id) || "") ? item : latest;
  }, {});
}

function riskLevel(value: unknown): RiskLevel {
  return ({ INFO: "low", LOW: "low", MEDIUM: "moderate", HIGH: "high", CRITICAL: "critical" } as Record<string, RiskLevel>)[String(value)] || "unknown";
}

function categoryFor(area: string): RiskFinding["category"] {
  if (["engine", "transmission", "emissions", "electrical", "brakes"].includes(area)) return "mechanical";
  if (["title", "identity", "odometer"].includes(area)) return "title";
  if (area === "seller") return "seller";
  if (["structure", "safety"].includes(area)) return "inspection";
  return "history";
}

function findingStatus(value: unknown): RiskFinding["status"] {
  return ({ UNKNOWN: "unknown", SUSPECTED: "possible", CONFIRMED: "confirmed", RESOLVED: "cleared" } as Record<string, RiskFinding["status"]>)[String(value)] || "unknown";
}

function makeFindings(raw: UnknownRecord): RiskFinding[] {
  return rows(raw.findings).map((item, index) => {
    const scenarios = rows(camelOrSnake(item, "repairScenarios", "repair_scenarios"));
    const lows = scenarios.map((scenario) => number(record(scenario.cost).low)).filter((value): value is number => value !== undefined);
    const highs = scenarios.map((scenario) => number(record(scenario.cost).high)).filter((value): value is number => value !== undefined);
    const nextChecks = camelOrSnake(item, "nextChecks", "next_checks");
    const evidenceIds = camelOrSnake(item, "evidenceIds", "evidence_ids");
    const area = text(item.area) || "other";
    return {
      id: text(item.id) || `finding-${index}`,
      title: text(item.title) || text(item.code) || "Unlabeled finding",
      summary: text(item.detail) || "",
      level: riskLevel(item.severity),
      status: findingStatus(item.status),
      category: categoryFor(area),
      evidence_ids: Array.isArray(evidenceIds) ? evidenceIds.filter((entry): entry is string => typeof entry === "string") : [],
      next_check: Array.isArray(nextChecks) ? nextChecks.filter((entry): entry is string => typeof entry === "string").join("; ") : undefined,
      exposure_low: lows.length ? Math.min(...lows) : undefined,
      exposure_high: highs.length ? Math.max(...highs) : undefined,
    };
  });
}

function maxFindingLevel(findings: RiskFinding[], categories: RiskFinding["category"][]): RiskLevel {
  const relevant = findings.filter((finding) => categories.includes(finding.category) && finding.status !== "cleared");
  return relevant.reduce<RiskLevel>((highest, finding) => riskRank[finding.level] > riskRank[highest] ? finding.level : highest, "unknown");
}

function makeRiskAxes(findings: RiskFinding[], coverage: number, valuation: ValuationResult): RiskAxis[] {
  const priceLevel: RiskLevel = valuation.market_median === undefined || valuation.asking_price === undefined ? "unknown" : valuation.asking_price <= valuation.market_median ? "low" : valuation.q3 !== undefined && valuation.asking_price > valuation.q3 ? "high" : "moderate";
  const priceNote = valuation.market_median === undefined || valuation.asking_price === undefined ? "No usable asking-price comparison yet." : `Asking price compared with ${valuation.market_label}; ${valuation.sample_count} admitted comparable(s).`;
  const evidenceLevel: RiskLevel = coverage >= 85 ? "low" : coverage >= 65 ? "moderate" : coverage >= 40 ? "high" : "unknown";
  return [
    { id: "price", label: "价格吸引力 / Price", level: priceLevel, note: priceNote },
    { id: "mechanical", label: "机械风险 / Mechanical", level: maxFindingLevel(findings, ["mechanical", "inspection"]), note: findings.some((item) => ["mechanical", "inspection"].includes(item.category)) ? "Based on current findings; unchecked systems remain unknown." : "No mechanical or PPI evidence has been interpreted yet." },
    { id: "history", label: "历史记录 / History", level: maxFindingLevel(findings, ["history"]), note: findings.some((item) => item.category === "history") ? "Based on imported history evidence." : "No confirmed history conclusion yet." },
    { id: "title", label: "产权交易 / Title", level: maxFindingLevel(findings, ["title", "seller"]), note: findings.some((item) => ["title", "seller"].includes(item.category)) ? "Based on title and transaction findings." : "Title, seller identity, and lien status are not verified." },
    { id: "evidence", label: "证据覆盖 / Evidence", level: evidenceLevel, note: `${Math.round(coverage)}% deterministic evidence coverage; unknown is not treated as pass.` },
  ];
}

function makeEvidence(raw: UnknownRecord): Evidence[] {
  const sources = new Map(rows(raw.sources).map((source) => [text(source.id), source]));
  return rows(raw.evidence).map((item, index) => {
    const source = sources.get(text(camelOrSnake(item, "sourceId", "source_id")));
    const metadata = record(item.metadata);
    const page = number(item.page);
    return {
      id: text(item.id) || `evidence-${index}`,
      label: text(item.label) || "Evidence",
      source: text(source?.provider) || text(source?.sourceType) || text(item.kind) || "user",
      kind: text(item.kind),
      captured_at: text(camelOrSnake(item, "observedAt", "observed_at")) || "unknown",
      reference: page ? `page ${page}` : text(metadata.reference),
      status: metadata.conflict === true ? "conflict" : metadata.verified === true ? "verified" : "unverified",
    };
  });
}

function makeVehicle(value: unknown): VehicleSpec {
  const vehicle = record(value);
  return {
    vin: text(vehicle.vin),
    year: number(vehicle.year),
    make: text(vehicle.make),
    model: text(vehicle.model),
    trim: text(vehicle.trim),
    generation: text(vehicle.generation),
    platform: text(vehicle.platform),
    engine: text(vehicle.engine),
    transmission: text(vehicle.transmission),
    drivetrain: text(vehicle.drivetrain),
    production_date: text(camelOrSnake(vehicle, "productionDate", "production_date")),
    fuel_type: text(camelOrSnake(vehicle, "fuelType", "fuel_type")),
    body_style: text(camelOrSnake(vehicle, "bodyStyle", "body_style")),
  };
}

function makeValuation(raw: UnknownRecord, askingPrice?: number): ValuationResult {
  const valuation = record(raw.valuation);
  const referenceKind = text(camelOrSnake(valuation, "referenceKind", "reference_kind"));
  return {
    market_label: referenceKind === "sold_price_range" ? "sold-price range" : referenceKind === "reference_value_range" || referenceKind === "mixed_reference" ? "reference-value range" : "asking-price range",
    market_median: number(camelOrSnake(valuation, "weightedMedian", "weighted_median")),
    q1: number(valuation.q25),
    q3: number(valuation.q75),
    sample_count: number(camelOrSnake(valuation, "sampleCount", "sample_count")) || 0,
    confidence: enumValue(String(valuation.confidence || "").toLowerCase(), ["low", "medium", "high"] as const, "low"),
    asking_price: askingPrice,
  };
}

function makeInspections(raw: UnknownRecord): InspectionStage[] {
  const template = createInspectionTemplate();
  const statusMap = { UNKNOWN: "unknown", PASS: "pass", CONCERN: "warn", FAIL: "fail", NOT_APPLICABLE: "unknown" } as const;
  const stageMap: Record<string, InspectionStage["id"]> = { pre_visit: "before", exterior: "exterior", interior: "interior", road_test: "drive", ppi: "ppi" };
  for (const session of rows(raw.inspections)) {
    for (const item of rows(session.items)) {
      const stage = template.find((entry) => entry.id === stageMap[String(item.stage)]);
      const key = text(item.key);
      if (!stage || !key) continue;
      const current = stage.checks.find((check) => check.id === key);
      const mapped = statusMap[String(item.result) as keyof typeof statusMap] || "unknown";
      if (current) {
        current.status = mapped;
        current.note = text(item.notes);
        const evidenceIds = camelOrSnake(item, "evidenceIds", "evidence_ids");
        current.evidence_ids = Array.isArray(evidenceIds) ? evidenceIds.filter((entry): entry is string => typeof entry === "string") : [];
      } else {
        const evidenceIds = camelOrSnake(item, "evidenceIds", "evidence_ids");
        stage.checks.push({ id: key, label: text(item.label) || key, status: mapped, note: text(item.notes), evidence_ids: Array.isArray(evidenceIds) ? evidenceIds.filter((entry): entry is string => typeof entry === "string") : [] });
      }
    }
  }
  return template;
}

function makeDiagnostics(raw: UnknownRecord): DiagnosticSummary {
  const scans = rows(raw.scans);
  const scan = scans.at(-1);
  if (!scan) return { coverage: [], not_covered: ["ABS", "SRS", "body modules", "OEM modules"], readiness: "unknown", codes: [], note: "No OBD scan imported." };
  const coverageMap = record(camelOrSnake(scan, "moduleCoverage", "module_coverage"));
  const covered: string[] = [];
  const notCovered: string[] = [];
  for (const [module, state] of Object.entries(coverageMap)) {
    if (state === "SCANNED") covered.push(module.toUpperCase());
    else notCovered.push(`${module.toUpperCase()} (${String(state).toLowerCase()})`);
  }
  const monitorStates = rows(scan.readiness).map((item) => String(item.status));
  const readiness: DiagnosticSummary["readiness"] = monitorStates.includes("NOT_READY") ? "not_ready" : monitorStates.length && monitorStates.every((item) => item === "READY" || item === "NOT_SUPPORTED") ? "ready" : "unknown";
  const codes = rows(scan.dtcs).map((item) => text(item.code)).filter((entry): entry is string => Boolean(entry));
  return {
    coverage: covered,
    not_covered: notCovered.length ? notCovered : ["Coverage beyond declared modules is unknown"],
    readiness,
    codes,
    note: text(scan.notes) || `${codes.length} generic DTC record(s).`,
  };
}

function makeTransactionPlan(raw: UnknownRecord): TransactionPlan {
  const plan = record(camelOrSnake(raw, "transactionPlan", "transaction_plan"));
  if (!Object.keys(plan).length) return { decision: "INSPECT", verified_as_of: "—", hard_gates: [], tasks: [] };
  const gates = rows(plan.gates);
  const steps = rows(plan.steps);
  return {
    decision: enumValue(plan.decision, ["STOP", "INSPECT", "NEGOTIATE", "BUY_CANDIDATE"] as const, "INSPECT"),
    verified_as_of: text(camelOrSnake(plan, "rulesVerifiedAsOf", "rules_verified_as_of")) || "—",
    hard_gates: gates.map((gate, index) => ({
      id: text(gate.code) || `gate-${index}`,
      title: text(gate.label) || "Transaction gate",
      detail: [text(gate.reason), text(camelOrSnake(gate, "evidenceNeeded", "evidence_needed"))].filter(Boolean).join(" "),
      status: gate.blocked === true ? "blocked" : "verify",
    })),
    tasks: steps.map((step, index) => ({
      id: String(number(step.order) || index + 1),
      title: text(step.title) || "Transaction task",
      detail: text(step.detail) || "",
      status: step.requiresConfirmation === true || step.requires_confirmation === true ? "verify" : "required",
      official_url: text(camelOrSnake(step, "officialUrl", "official_url")),
      deadline: text(step.deadline),
    })),
  };
}

export function caseRecordFromApi(value: unknown): CaseRecord {
  const raw = record(value);
  const listings = rows(raw.listings);
  const target = latestTargetListing(listings);
  const vehicle = makeVehicle(raw.vehicle);
  const askingPrice = number(camelOrSnake(target, "askingPrice", "asking_price"));
  const coverage = number(camelOrSnake(raw, "coveragePercent", "coverage_percent")) || 0;
  const findings = makeFindings(raw);
  const decision = enumValue<Decision>(raw.decision, ["STOP", "INSPECT", "NEGOTIATE", "BUY_CANDIDATE"], "INSPECT");
  const status = enumValue<CaseStatus>(raw.status, ["DISCOVERED", "NEEDS_DATA", "REMOTE_SCREENED", "VIEW_SCHEDULED", "SELF_INSPECTED", "PPI_COMPLETE", "NEGOTIATING", "READY_TO_BUY", "PURCHASED", "REGISTERED", "REJECTED"], "DISCOVERED");
  const name = text(target.title) || [vehicle.year, vehicle.make, vehicle.model, vehicle.trim].filter(Boolean).join(" ") || "Untitled vehicle";
  const valuation = makeValuation(raw, askingPrice);
  const unresolvedFindings = findings.filter((finding) =>
    finding.status === "possible" || finding.status === "confirmed");
  const lowExposure = unresolvedFindings.reduce((sum, finding) => sum + (finding.exposure_low || 0), 0);
  const highExposure = unresolvedFindings.reduce((sum, finding) => sum + (finding.exposure_high || 0), 0);
  return {
    id: text(raw.id) || "missing-case-id",
    language: enumValue(raw.language, ["en", "zh-CN"] as const, "en"),
    name,
    status,
    decision,
    vehicle,
    all_in_budget: number(camelOrSnake(raw, "allInBudget", "all_in_budget")),
    listing: {
      id: text(target.id) || `placeholder-${text(raw.id) || "case"}`,
      source_url: text(camelOrSnake(target, "sourceUrl", "source_url")),
      title: text(target.title) || name,
      asking_price: askingPrice,
      mileage: number(target.mileage) ?? number(camelOrSnake(record(raw.vehicle), "odometerMiles", "odometer_miles")),
      currency: text(target.currency) || "USD",
      location: text(target.location),
      seller_type: enumValue(target.sellerType ?? target.seller_type, ["private", "dealer", "unknown"] as const, "unknown"),
      channel: text(target.channel) || "user_entry",
      is_target: target.isTarget === true || target.is_target === true,
      captured_at: text(camelOrSnake(target, "capturedAt", "captured_at")) || text(camelOrSnake(raw, "createdAt", "created_at")) || new Date(0).toISOString(),
    },
    coverage_percent: coverage,
    risk_axes: makeRiskAxes(findings, coverage, valuation),
    findings,
    evidence: makeEvidence(raw),
    valuation,
    inspections: makeInspections(raw),
    transaction_plan: makeTransactionPlan(raw),
    diagnostics: makeDiagnostics(raw),
    unresolved_planning_exposure: lowExposure || highExposure ? [lowExposure, highExposure] : undefined,
    updated_at: text(camelOrSnake(raw, "updatedAt", "updated_at")) || new Date(0).toISOString(),
  };
}

export function explicitDemoCases(cases: CaseRecord[]): CaseRecord[] {
  return structuredClone(cases);
}
