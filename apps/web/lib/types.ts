export type Language = "zh-CN" | "en";
export type Decision = "STOP" | "INSPECT" | "NEGOTIATE" | "BUY_CANDIDATE";
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
export type CheckStatus = "unknown" | "pass" | "warn" | "fail";
export type RiskLevel = "unknown" | "low" | "moderate" | "high" | "critical";

export interface VehicleSpec {
  vin?: string;
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  generation?: string;
  platform?: string;
  engine?: string;
  transmission?: string;
  drivetrain?: string;
  production_date?: string;
  fuel_type?: string;
  body_style?: string;
}

export interface ListingImportInput {
  source_url?: string;
  title: string;
  asking_price: number;
  mileage?: number;
  currency: string;
  location?: string;
  listed_at?: string;
  seller_type: "private" | "dealer" | "unknown";
  channel: string;
  reference_kind: "asking" | "sold" | "reference";
  vin?: string;
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  generation?: string;
  platform?: string;
  engine?: string;
  transmission?: string;
  drivetrain?: string;
  production_date?: string;
  fuel_type?: string;
  body_style?: string;
  distance_miles?: number;
  is_target: boolean;
}

export interface Evidence {
  id: string;
  label: string;
  source: string;
  kind?: string;
  captured_at: string;
  reference?: string;
  status?: "verified" | "unverified" | "conflict";
}

export interface RiskFinding {
  id: string;
  title: string;
  summary: string;
  level: RiskLevel;
  status: "confirmed" | "possible" | "cleared" | "unknown";
  category: "mechanical" | "history" | "title" | "seller" | "inspection";
  evidence_ids: string[];
  next_check?: string;
  exposure_low?: number;
  exposure_high?: number;
}

export interface RiskAxis {
  id: "price" | "mechanical" | "history" | "title" | "evidence";
  label: string;
  level: RiskLevel;
  note: string;
}

export interface ListingSnapshot {
  id: string;
  source_url?: string;
  title: string;
  asking_price: number;
  mileage?: number;
  currency: string;
  location?: string;
  seller_type: "private" | "dealer" | "unknown";
  channel: string;
  reference_kind?: "asking" | "sold" | "reference";
  listed_at?: string;
  distance_miles?: number;
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  generation?: string;
  platform?: string;
  engine?: string;
  transmission?: string;
  drivetrain?: string;
  production_date?: string;
  fuel_type?: string;
  body_style?: string;
  is_target?: boolean;
  captured_at: string;
}

export interface ValuationResult {
  market_label: "asking-price range" | "sold-price range" | "reference-value range";
  market_median?: number;
  q1?: number;
  q3?: number;
  sample_count: number;
  confidence: "low" | "medium" | "high";
  target?: number;
  opening?: number;
  ceiling?: number;
  asking_price?: number;
  repair_adjustment?: number;
  evidence_reserve?: number;
}

export interface InspectionCheck {
  id: string;
  label: string;
  status: CheckStatus;
  note?: string;
  evidence_ids?: string[];
}

export interface InspectionStage {
  id: "before" | "exterior" | "interior" | "drive" | "ppi";
  title: string;
  checks: InspectionCheck[];
  /** Required for PPI submission; use a role/shop label, not a person's name. */
  inspector?: string;
}

export interface TransactionTask {
  id: string;
  title: string;
  detail: string;
  status: "required" | "verify" | "blocked";
  official_url?: string;
  deadline?: string;
}

export interface TransactionPlan {
  decision: Decision;
  verified_as_of: string;
  hard_gates: TransactionTask[];
  tasks: TransactionTask[];
}

export interface DiagnosticSummary {
  coverage: string[];
  not_covered: string[];
  readiness: "ready" | "not_ready" | "unknown";
  codes: string[];
  note: string;
}

export interface CaseRecord {
  id: string;
  name: string;
  status: CaseStatus;
  decision: Decision;
  vehicle: VehicleSpec;
  listing: ListingSnapshot;
  comparable_listings?: ListingSnapshot[];
  coverage_percent: number;
  risk_axes: RiskAxis[];
  findings: RiskFinding[];
  evidence: Evidence[];
  valuation: ValuationResult;
  inspections: InspectionStage[];
  transaction_plan: TransactionPlan;
  diagnostics: DiagnosticSummary;
  unresolved_planning_exposure?: [number, number];
  updated_at: string;
}

export interface NegotiationRequest {
  phase: "initial_contact" | "conditional_offer" | "post_ppi" | "walk_away";
  language: Language;
  asking_price: number;
  market_baseline: number;
  all_in_budget: number;
  evidence_coverage: number;
  adjustments: Array<{
    label: string;
    category: "immediate_repair" | "overdue_maintenance" | "abnormal_risk";
    amount: number;
    normal_wear?: false;
    finding_id?: string;
    evidence_ids?: string[];
  }>;
  buyer_mandatory_costs?: number;
  seller_floor?: number;
}

export interface NegotiationResponse {
  target?: number;
  opening?: number;
  ceiling?: number;
  reserve: number;
  trace: Array<{ label?: string; amount?: number; explanation?: string }>;
  message: string;
  decision: Decision;
}

export interface TransactionContextInput {
  purchase_date: string;
  buyer_residence_state: "NJ" | "NY" | "CT";
  buyer_license_state: "NJ" | "NY" | "CT";
  garaging_state: "NJ" | "NY" | "CT";
  registration_state: "NJ" | "NY" | "CT";
  sale_state: "NJ" | "NY" | "CT";
  title_state: "NJ" | "NY" | "CT";
  seller_type: "private" | "dealer";
  title_name_matches: boolean;
  vin_matches: boolean;
  original_title_present: boolean;
  seller_allows_ppi: boolean | null;
  seller_allows_bill_of_sale: boolean | null;
  seller_discloses_odometer: boolean | null;
  lien_status: "none" | "released" | "unresolved" | "unknown";
  insurance_active_for_vin: boolean;
  legal_transport: "registered_plate" | "temporary_permit" | "tow" | "none";
}
