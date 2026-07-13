export type CaseStatus =
  | "DISCOVERED"
  | "NEEDS_DATA"
  | "REMOTE_SCREENED"
  | "VIEW_SCHEDULED"
  | "SELF_INSPECTED"
  | "PPI_COMPLETE"
  | "NEGOTIATING"
  | "READY_TO_BUY"
  | "PURCHASED"
  | "REGISTERED"
  | "REJECTED";

export type Decision = "STOP" | "INSPECT" | "NEGOTIATE" | "BUY_CANDIDATE";
export type RetentionClass = "LOCAL" | "ANONYMOUS" | "ACCOUNT";
export type Confidence = "LOW" | "MEDIUM" | "HIGH";
export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type ComparisonRisk = "UNKNOWN" | Severity;
export type FindingStatus = "UNKNOWN" | "SUSPECTED" | "CONFIRMED" | "RESOLVED";
export type EvidenceKind =
  | "listing"
  | "history_report"
  | "title"
  | "lien_release"
  | "receipt"
  | "state_inspection"
  | "seller_message"
  | "photo"
  | "obd_scan"
  | "self_inspection"
  | "ppi"
  | "market_comparable"
  | "official_rule"
  | "other";

export interface VehicleSpec {
  vin?: string | null;
  year?: number | null;
  make?: string | null;
  model?: string | null;
  trim?: string | null;
  generation?: string | null;
  platform?: string | null;
  engine?: string | null;
  transmission?: string | null;
  drivetrain?: string | null;
  productionDate?: string | null;
  fuelType?:
    | "gasoline"
    | "diesel"
    | "hybrid"
    | "plug_in_hybrid"
    | "electric"
    | "other"
    | "unknown";
  bodyStyle?: string | null;
  odometerMiles?: number | null;
}

export interface SourceEnvelope {
  id: string;
  sourceType: string;
  provider: string;
  sourceUrl?: string | null;
  acquiredAt: string;
  observedAt: string;
  effectiveDate?: string | null;
  licenseName: string;
  redistribution: "allowed" | "restricted" | "unknown";
  credentialStorage: string;
  retentionPolicy: string;
  contentSha256: string;
  lastUpdatedAt: string;
}

export interface Evidence {
  id: string;
  sourceId: string;
  kind: EvidenceKind;
  label: string;
  excerpt?: string | null;
  page?: number | null;
  observedAt: string;
  metadata: Record<string, unknown>;
  isSensitive: boolean;
  redacted: boolean;
}

export interface MoneyRange {
  low: number;
  likely: number;
  high: number;
  currency: string;
}

export interface RepairScenario {
  id: string;
  label: string;
  system: string;
  probabilityLabel: "minimum" | "most_likely" | "worst_reasonable";
  cost: MoneyRange;
  confirmationTests: string[];
  evidenceIds: string[];
  confidence: Confidence;
  shopType: "diy" | "independent" | "specialist" | "dealer" | "mixed";
}

export interface RiskFinding {
  id: string;
  code: string;
  area: string;
  title: string;
  detail: string;
  severity: Severity;
  status: FindingStatus;
  evidenceIds: string[];
  nextChecks: string[];
  repairScenarios: RepairScenario[];
  decisionImpact?: Decision | null;
  blocksPurchase: boolean;
}

export interface ListingSnapshot {
  id: string;
  sourceId: string;
  evidenceId: string;
  contentSha256: string;
  sourceUrl?: string | null;
  title: string;
  askingPrice: number;
  currency: string;
  mileage?: number | null;
  location?: string | null;
  listedAt?: string | null;
  sellerType: "private" | "dealer" | "unknown";
  channel: string;
  referenceKind: "asking" | "sold" | "reference";
  vin?: string | null;
  year?: number | null;
  make?: string | null;
  model?: string | null;
  trim?: string | null;
  generation?: string | null;
  platform?: string | null;
  engine?: string | null;
  transmission?: string | null;
  drivetrain?: string | null;
  productionDate?: string | null;
  fuelType: "gasoline" | "diesel" | "hybrid" | "plug_in_hybrid" | "electric" | "other" | "unknown";
  bodyStyle?: string | null;
  distanceMiles?: number | null;
  isTarget: boolean;
  description?: string | null;
  capturedAt: string;
}

export interface DiagnosticCode {
  code: string;
  status: "stored" | "pending" | "permanent";
  description?: string | null;
  module: string;
}

export interface DiagnosticScan {
  id: string;
  sourceId: string;
  evidenceId: string;
  scannedAt: string;
  scannerName: string;
  vin?: string | null;
  milOn?: boolean | null;
  dtcs: DiagnosticCode[];
  readiness: Array<{ name: string; status: "READY" | "NOT_READY" | "NOT_SUPPORTED" | "UNKNOWN" }>;
  moduleCoverage: Record<string, "SCANNED" | "NOT_SCANNED" | "UNSUPPORTED" | "UNKNOWN">;
  freezeFrame: Record<string, string | number | boolean | null>;
  livePids: Record<string, string | number | boolean | null>;
  limitations: string[];
}

export interface ValuationResult {
  referenceKind: "asking_price_range" | "sold_price_range" | "reference_value_range" | "mixed_reference";
  channel: "private" | "dealer" | "unknown" | "mixed";
  weightedMedian?: number | null;
  q25: number;
  q75: number;
  sampleCount: number;
  radiusMiles: number;
  maxAgeDays: number;
  confidence: Confidence;
  lowSampleWarning: boolean;
  comparableListingIds: string[];
  excludedCount: number;
  calculatedAt: string;
}

export interface CaseStatusEvent {
  fromStatus?: CaseStatus | null;
  toStatus: CaseStatus;
  reason: string;
  evidenceIds: string[];
  occurredAt: string;
}

export interface CaseContext {
  id: string;
  status: CaseStatus;
  decision: Decision;
  language: "en" | "zh-CN";
  buyerGoal?: string | null;
  allInBudget?: number | null;
  vehicle: VehicleSpec;
  sources: SourceEnvelope[];
  evidence: Evidence[];
  history: Array<Record<string, unknown>>;
  listings: ListingSnapshot[];
  scans: DiagnosticScan[];
  inspections: Array<Record<string, unknown>>;
  findings: RiskFinding[];
  valuation?: ValuationResult | null;
  transactionContext?: Record<string, unknown> | null;
  transactionPlan?: Record<string, unknown> | null;
  coveragePercent: number;
  unknowns: string[];
  nextActions: string[];
  statusHistory: CaseStatusEvent[];
  retentionClass: RetentionClass;
  expiresAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ComparisonRow {
  caseId: string;
  rank: number;
  decision: Decision;
  askingPrice?: number | null;
  priceAttractiveness?: number | null;
  mechanicalRisk: ComparisonRisk;
  titleRisk: ComparisonRisk;
  coveragePercent: number;
  unresolvedPlanningExposure?: MoneyRange | null;
  reason: string;
}

export interface CompareResponse {
  ranked: ComparisonRow[];
  generatedAt: string;
}
