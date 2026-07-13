import type {
  CaseRecord,
  InspectionStage,
  Language,
  ListingImportInput,
  NegotiationRequest,
  NegotiationResponse,
  TransactionContextInput,
  TransactionPlan,
  VehicleSpec,
  VinDecodeResponse,
} from "./types";
import { caseRecordFromApi } from "./case-record";
import { accessTokenMap, caseAccessFor, rememberCaseAccess } from "./case-access";
import { compareResponseFromApi } from "./compare";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getApiBase(): string {
  return (process.env.NEXT_PUBLIC_OCDD_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE).replace(/\/$/, "");
}

export interface CaseAccess {
  /** Reserved for cloud deployments that issue a per-case capability token. */
  accessToken?: string;
}

function accessHeaders(access?: CaseAccess): Record<string, string> {
  return access?.accessToken ? { "X-OCDD-Case-Token": access.accessToken } : {};
}

function caseAccess(caseId: string, explicit?: CaseAccess): CaseAccess | undefined {
  return explicit || caseAccessFor(caseId);
}

function readableApiDetail(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const message = (item as { msg?: unknown }).msg;
      const location = (item as { loc?: unknown }).loc;
      if (typeof message !== "string") return [];
      const field = Array.isArray(location) ? location.filter((part) => part !== "body").join(".") : "";
      return [`${field ? `${field}: ` : ""}${message}`];
    });
    return messages.length ? messages.join("; ") : undefined;
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown; msg?: unknown }).message || (detail as { msg?: unknown }).msg;
    if (typeof message === "string") return message;
  }
  return undefined;
}

async function apiFetchWithResponse<T>(path: string, init?: RequestInit, access?: CaseAccess): Promise<{ data: T; response: Response }> {
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...accessHeaders(access), ...init?.headers },
    credentials: "omit",
  });
  const payload = await response.json().catch(() => undefined);
  if (!response.ok) {
    throw new ApiError(
      readableApiDetail(payload) || `Request failed (${response.status})`,
      response.status,
      payload,
    );
  }
  return { data: payload as T, response };
}

async function apiFetch<T>(path: string, init?: RequestInit, access?: CaseAccess): Promise<T> {
  return (await apiFetchWithResponse<T>(path, init, access)).data;
}

type ApiVehicleSpec = Omit<VehicleSpec, "production_date" | "fuel_type" | "body_style"> & {
  productionDate?: string;
  fuelType?: string;
  bodyStyle?: string;
};

type ApiVinDecodeResponse = Omit<VinDecodeResponse, "vehicle"> & { vehicle: ApiVehicleSpec };

export const api = {
  health() {
    return apiFetch<{ status: string; version: string; deploymentMode: string }>("/health");
  },

  listCases() {
    return apiFetch<Array<Record<string, unknown>>>("/v1/cases").then((items) => items.map(caseRecordFromApi));
  },

  getCase(caseId: string, access?: CaseAccess) {
    return apiFetch<Record<string, unknown>>(`/v1/cases/${caseId}`, undefined, caseAccess(caseId, access)).then(caseRecordFromApi);
  },

  updateCaseStatus(caseId: string, status: CaseRecord["status"], reason: string, evidenceIds: string[] = [], access?: CaseAccess) {
    return apiFetch<Record<string, unknown>>(`/v1/cases/${caseId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, reason, evidenceIds }),
    }, caseAccess(caseId, access)).then(caseRecordFromApi);
  },

  deleteCase(caseId: string, access?: CaseAccess) {
    return apiFetch<void>(`/v1/cases/${caseId}`, { method: "DELETE" }, caseAccess(caseId, access));
  },

  createCase(input: {
    language: Language;
    buyer_goal?: string;
    all_in_budget?: number;
    vehicle?: VehicleSpec;
  }) {
    return apiFetchWithResponse<Record<string, unknown>>("/v1/cases", { method: "POST", body: JSON.stringify(input) }).then(({ data, response }) => {
      const created = caseRecordFromApi(data);
      const accessToken = response.headers.get("X-OCDD-Case-Token") || undefined;
      rememberCaseAccess(created.id, accessToken);
      return { case: created, accessToken };
    });
  },

  decodeVin(vin: string, modelYear?: number) {
    return apiFetch<ApiVinDecodeResponse>("/v1/vehicles/decode-vin", {
      method: "POST",
      body: JSON.stringify({ vin, ...(modelYear ? { modelYear } : {}) }),
    }).then((response): VinDecodeResponse => {
      const { productionDate, fuelType, bodyStyle, ...vehicle } = response.vehicle;
      return {
        ...response,
        vehicle: {
          ...vehicle,
          production_date: productionDate,
          fuel_type: fuelType,
          body_style: bodyStyle,
        },
      };
    });
  },

  importListings(caseId: string, listings: ListingImportInput[], access?: CaseAccess) {
    return apiFetch<{ caseId: string; imported: number; evidenceIds: string[]; listingIds: string[] }>(
      `/v1/cases/${caseId}/listings/import`,
      { method: "POST", body: JSON.stringify({ listings }) },
      caseAccess(caseId, access),
    );
  },

  listingHistory(caseId: string, access?: CaseAccess) {
    return apiFetch<{
      caseId: string;
      items: Array<{
        listingKey: string;
        title: string;
        sourceUrl?: string;
        observations: Array<{ listingId: string; askingPrice: number; capturedAt: string }>;
        absoluteChange?: number;
        percentChange?: number;
      }>;
    }>(`/v1/cases/${caseId}/listings/history`, undefined, caseAccess(caseId, access));
  },

  uploadArtifact(caseId: string, input: {
    filename: string;
    kind: string;
    media_type?: string;
    text?: string;
    content_base64?: string;
    label?: string;
    page?: number;
    sensitive_fields?: string[];
    title_owner_name?: string;
    seller_legal_name?: string;
  }, access?: CaseAccess) {
    return apiFetch<Record<string, unknown>>(`/v1/cases/${caseId}/artifacts`, {
      method: "POST",
      body: JSON.stringify(input),
    }, caseAccess(caseId, access));
  },

  addObdScan(caseId: string, input: Record<string, unknown>, access?: CaseAccess) {
    return apiFetch<Record<string, unknown>>(`/v1/cases/${caseId}/obd/scans`, {
      method: "POST",
      body: JSON.stringify(input),
    }, caseAccess(caseId, access));
  },

  analyze(caseId: string, input: { buyer_all_in_budget?: number; comparables?: unknown[] } = {}, access?: CaseAccess) {
    return apiFetch<{
      caseId: string;
      decision: string;
      coveragePercent: number;
      valuation?: unknown;
      findings: unknown[];
      unknowns: string[];
      nextActions: string[];
    }>(`/v1/cases/${caseId}/analyze`, { method: "POST", body: JSON.stringify(input) }, caseAccess(caseId, access));
  },

  report(caseId: string, language: Language, access?: CaseAccess) {
    return apiFetch<Record<string, unknown>>(`/v1/cases/${caseId}/report?language=${encodeURIComponent(language)}&format=json`, undefined, caseAccess(caseId, access));
  },

  async reportPdf(caseId: string, language: Language, access?: CaseAccess): Promise<Blob> {
    const response = await fetch(`${getApiBase()}/v1/cases/${caseId}/report?language=${encodeURIComponent(language)}&format=pdf`, {
      credentials: "omit",
      headers: accessHeaders(caseAccess(caseId, access)),
    });
    if (!response.ok) throw new ApiError(`PDF report failed (${response.status})`, response.status);
    return response.blob();
  },

  saveInspection(caseId: string, inspection: InspectionStage, access?: CaseAccess) {
    const stage = inspection.id === "before" ? "pre_visit" : inspection.id === "drive" ? "road_test" : inspection.id;
    const resultMap = { unknown: "UNKNOWN", pass: "PASS", warn: "CONCERN", fail: "FAIL" } as const;
    return apiFetch(`/v1/cases/${caseId}/inspections`, {
      method: "POST",
      body: JSON.stringify({
        inspectedAt: new Date().toISOString(),
        inspectionType: inspection.id === "ppi" ? "ppi" : "self",
        inspector: inspection.id === "ppi" ? inspection.inspector?.trim() || undefined : undefined,
        items: inspection.checks.map((check) => ({
          key: check.id,
          label: check.label,
          stage,
          result: resultMap[check.status],
          notes: check.note,
          evidenceIds: check.evidence_ids || [],
        })),
      }),
    }, caseAccess(caseId, access));
  },

  draftNegotiation(caseId: string, input: NegotiationRequest, access?: CaseAccess) {
    return apiFetch<{
      target?: number;
      opening?: number;
      ceiling?: number;
      evidenceReserve: number;
      decision: "INSPECT_FIRST" | "MAKE_OFFER" | "WALK_AWAY" | "WAIT";
      trace: Array<{ label: string; amount: number; applied: boolean; reason: string; evidenceIds: string[] }>;
      message: string;
    }>(`/v1/cases/${caseId}/negotiation/draft`, {
      method: "POST",
      body: JSON.stringify(input),
    }, caseAccess(caseId, access)).then((response): NegotiationResponse => ({
      target: response.target,
      opening: response.opening,
      ceiling: response.ceiling,
      reserve: response.evidenceReserve,
      decision: response.decision === "INSPECT_FIRST" ? "INSPECT" : response.decision === "WALK_AWAY" ? "STOP" : "NEGOTIATE",
      trace: response.trace.map((item) => ({ label: item.label, amount: item.amount, explanation: item.reason })),
      message: response.message,
    }));
  },

  transactionPlan(caseId: string, input: TransactionContextInput, vehicle: VehicleSpec, access?: CaseAccess) {
    const lienStatus = {
      none: "CLEAR",
      released: "RELEASE_ATTACHED",
      unresolved: "ACTIVE",
      unknown: "UNKNOWN",
    }[input.lien_status];
    const transportOption = {
      registered_plate: "valid_registration_and_plate",
      temporary_permit: "valid_temp_permit",
      tow: "tow",
      none: "undecided",
    }[input.legal_transport];
    const body = {
      purchaseDate: input.purchase_date,
      buyerResidenceState: input.buyer_residence_state,
      licenseState: input.buyer_license_state,
      garagingState: input.garaging_state,
      registrationState: input.registration_state,
      saleState: input.sale_state,
      titleState: input.title_state,
      sellerType: input.seller_type,
      titleStatus: input.title_status,
      lienStatus,
      identityTitleMatch: input.identity_title_match,
      vinMatch: input.vin_match,
      sellerAllowsPpi: input.seller_allows_ppi,
      sellerAllowsBillOfSale: input.seller_allows_bill_of_sale,
      sellerWillDiscloseOdometer: input.seller_discloses_odometer,
      insuranceActiveForVin: input.insurance_active_for_vin,
      transportOption,
      vehicle,
      currentInspectionStatus: "UNKNOWN",
      currentEmissionsStatus: "UNKNOWN",
    };
    return apiFetch<{
      decision: CaseRecord["decision"];
      canLegallyDriveAway: boolean;
      gates: Array<{ code: string; label: string; blocked: boolean; reason: string; evidenceNeeded?: string }>;
      steps: Array<{ order: number; title: string; detail: string; deadline?: string; officialUrl?: string; requiresConfirmation: boolean }>;
      rulesVerifiedAsOf?: string;
    }>(`/v1/cases/${caseId}/transaction-plan`, { method: "POST", body: JSON.stringify(body) }, caseAccess(caseId, access)).then((response): TransactionPlan => ({
      decision: response.decision,
      verified_as_of: response.rulesVerifiedAsOf || new Date().toISOString().slice(0, 10),
      hard_gates: response.gates.map((gate) => ({
        id: gate.code,
        title: gate.label,
        detail: `${gate.reason}${gate.evidenceNeeded ? ` Evidence needed: ${gate.evidenceNeeded}` : ""}`,
        status: gate.blocked ? "blocked" : "verify",
      })),
      tasks: response.steps.sort((a, b) => a.order - b.order).map((step) => ({
        id: String(step.order),
        title: step.title,
        detail: step.detail,
        status: step.requiresConfirmation ? "verify" : "required",
        official_url: step.officialUrl,
        deadline: step.deadline,
      })),
    }));
  },

  compare(caseIds: string[], accessTokens: Record<string, string> = {}, access?: CaseAccess) {
    return apiFetch<unknown>("/v1/compare", {
      method: "POST",
      body: JSON.stringify({ caseIds, accessTokens: Object.keys(accessTokens).length ? accessTokens : accessTokenMap(caseIds) }),
    }, access).then(compareResponseFromApi);
  },

  repairCostEstimate(input: Record<string, unknown>) {
    return apiFetch<Record<string, unknown>>("/v1/repair-cost/estimate", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  repairCostCompare(input: Record<string, unknown>) {
    return apiFetch<{
      label: string;
      zip3: string;
      estimates: Array<Record<string, unknown>>;
    }>("/v1/repair-cost/compare", { method: "POST", body: JSON.stringify(input) });
  },

  async exportCase(caseId: string, passphrase: string, access?: CaseAccess): Promise<Blob> {
    const response = await fetch(`${getApiBase()}/v1/cases/${caseId}/export`, {
      headers: { "X-OCDD-Passphrase": passphrase, ...accessHeaders(caseAccess(caseId, access)) },
      credentials: "omit",
    });
    if (!response.ok) throw new ApiError(`Case export failed (${response.status})`, response.status);
    return response.blob();
  },

  importCase(contentBase64: string, passphrase: string) {
    return apiFetchWithResponse<{ caseId: string; schemaVersion: string; integrityVerified: boolean }>("/v1/cases/import", {
      method: "POST",
      body: JSON.stringify({ contentBase64, passphrase }),
    }).then(({ data, response }) => {
      const accessToken = response.headers.get("X-OCDD-Case-Token") || undefined;
      rememberCaseAccess(data.caseId, accessToken);
      return { ...data, accessToken };
    });
  },
};

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** HTTP errors prove that the API responded; only transport failures mean offline. */
export function isApiConnectionFailure(error: unknown): boolean {
  return !isApiError(error);
}

/** Turn common API failures into concise user-facing English or Chinese copy. */
export function apiErrorMessage(error: unknown, language: Language, fallback?: string): string {
  if (isApiError(error)) {
    const statusCopy = language === "zh-CN"
      ? error.status === 401 || error.status === 403
        ? "没有权限访问此案件"
        : error.status === 404
          ? "没有找到请求的案件或资料"
          : error.status === 409
            ? "请求与当前案件状态冲突"
            : error.status === 413
              ? "上传内容超过大小限制"
              : error.status === 422
                ? "请求未通过业务规则校验"
                : error.status === 429
                  ? "请求过于频繁，请稍后再试"
                  : error.status !== undefined && error.status >= 500
                    ? "API 暂时无法完成请求"
                    : "API 请求失败"
      : error.status === 401 || error.status === 403
        ? "You do not have access to this case"
        : error.status === 404
          ? "The requested case or record was not found"
          : error.status === 409
            ? "The request conflicts with the current case state"
            : error.status === 413
              ? "The upload exceeds the size limit"
              : error.status === 422
                ? "The request did not pass the business rules"
                : error.status === 429
                  ? "Too many requests; please try again shortly"
                  : error.status !== undefined && error.status >= 500
                    ? "The API could not complete the request"
                    : "API request failed";
    return error.message && !error.message.startsWith("Request failed (")
      ? `${statusCopy}: ${error.message}`
      : statusCopy;
  }
  if (fallback) return fallback;
  return language === "zh-CN"
    ? "无法连接 API，请确认服务已启动后重试"
    : "Could not connect to the API. Check that the service is running and try again.";
}
