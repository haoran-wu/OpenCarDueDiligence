import type {
  CompareResponse,
  ComparisonRisk,
  ComparisonRow,
  Decision,
  MoneyRange,
} from "@ocdd/contracts";
import type { RiskLevel } from "./types";

type UnknownRecord = Record<string, unknown>;

const risks = new Set<ComparisonRisk>([
  "UNKNOWN",
  "INFO",
  "LOW",
  "MEDIUM",
  "HIGH",
  "CRITICAL",
]);
const decisions = new Set<Decision>(["STOP", "INSPECT", "NEGOTIATE", "BUY_CANDIDATE"]);

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function finite(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function camelOrSnake(source: UnknownRecord, camel: string, snake: string): unknown {
  return source[camel] ?? source[snake];
}

export function comparisonRisk(value: unknown): ComparisonRisk {
  return typeof value === "string" && risks.has(value as ComparisonRisk)
    ? value as ComparisonRisk
    : "UNKNOWN";
}

export function comparisonRiskFromLevel(value: RiskLevel): ComparisonRisk {
  return ({
    unknown: "UNKNOWN",
    low: "LOW",
    moderate: "MEDIUM",
    high: "HIGH",
    critical: "CRITICAL",
  } as const)[value];
}

function moneyRange(value: unknown): MoneyRange | null {
  const source = record(value);
  const low = finite(source.low);
  const likely = finite(source.likely);
  const high = finite(source.high);
  if (low === undefined || likely === undefined || high === undefined) return null;
  return { low, likely, high, currency: typeof source.currency === "string" ? source.currency : "USD" };
}

function comparisonRow(value: unknown, index: number): ComparisonRow | undefined {
  const source = record(value);
  const caseId = camelOrSnake(source, "caseId", "case_id");
  if (typeof caseId !== "string" || !caseId) return undefined;
  const decisionValue = source.decision;
  const unresolvedPlanningExposure = moneyRange(camelOrSnake(
    source,
    "unresolvedPlanningExposure",
    "unresolved_planning_exposure",
  ));
  return {
    caseId,
    rank: finite(source.rank) ?? index + 1,
    decision: typeof decisionValue === "string" && decisions.has(decisionValue as Decision)
      ? decisionValue as Decision
      : "INSPECT",
    askingPrice: finite(camelOrSnake(source, "askingPrice", "asking_price")),
    priceAttractiveness: finite(camelOrSnake(source, "priceAttractiveness", "price_attractiveness")),
    mechanicalRisk: comparisonRisk(camelOrSnake(source, "mechanicalRisk", "mechanical_risk")),
    titleRisk: comparisonRisk(camelOrSnake(source, "titleRisk", "title_risk")),
    coveragePercent: finite(camelOrSnake(source, "coveragePercent", "coverage_percent")) ?? 0,
    unresolvedPlanningExposure,
    reason: typeof source.reason === "string" ? source.reason : "",
  };
}

/** Parse the untrusted API response without ever defaulting a missing axis to INFO. */
export function compareResponseFromApi(value: unknown): CompareResponse {
  const source = record(value);
  const ranked = Array.isArray(source.ranked)
    ? source.ranked.map(comparisonRow).filter((row): row is ComparisonRow => Boolean(row))
    : [];
  const generatedAt = camelOrSnake(source, "generatedAt", "generated_at");
  return {
    ranked,
    generatedAt: typeof generatedAt === "string" ? generatedAt : "",
  };
}

export function comparisonRiskClass(value: ComparisonRisk): string {
  return `risk-chip ${value.toLowerCase()}`;
}
