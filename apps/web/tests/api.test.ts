import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiErrorMessage, isApiConnectionFailure } from "../lib/api";
import { comparableListingImportForm, copyResolvedTargetConfiguration, listingImportPayload } from "../lib/listing-import";
import { demoCases } from "../lib/demo";
import { eligibleNegotiationAdjustments } from "../lib/negotiation";

const token = "capability-token-that-is-never-rendered";

function apiCase() {
  return {
    id: "cloud-case-1",
    status: "DISCOVERED",
    decision: "INSPECT",
    vehicle: { year: 2012, make: "FIAT", model: "500", fuelType: "gasoline" },
    listings: [], sources: [], evidence: [], scans: [], inspections: [], findings: [],
    coveragePercent: 0,
    createdAt: "2026-07-13T00:00:00Z",
    updatedAt: "2026-07-13T00:00:00Z",
  };
}

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

describe("web API client", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "window", { value: { sessionStorage: memoryStorage() }, configurable: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(globalThis, "window");
  });

  it("captures a cloud capability once and automatically sends it on later case calls", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(apiCase()), { status: 201, headers: { "Content-Type": "application/json", "X-OCDD-Case-Token": token } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(apiCase()), { status: 200, headers: { "Content-Type": "application/json" } }));

    const created = await api.createCase({ language: "en", vehicle: { year: 2012, make: "FIAT", model: "500" } });
    await api.getCase(created.case.id);

    expect(created.accessToken).toBe(token);
    const secondInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(secondInit.headers).toMatchObject({ "X-OCDD-Case-Token": token });
    expect(JSON.stringify(secondInit)).not.toContain("cloud-case-1?token");
  });

  it("maps an empty API list without inserting demo vehicles", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(api.listCases()).resolves.toEqual([]);
  });

  it("deletes exactly one case with its capability in a header", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(null, { status: 204 }));

    await api.deleteCase("cloud-case-1", { accessToken: token });

    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:8000/v1/cases/cloud-case-1");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "DELETE",
      credentials: "omit",
      headers: expect.objectContaining({ "X-OCDD-Case-Token": token }),
    });
    expect(String(fetchMock.mock.calls[0][0])).not.toContain(token);
  });

  it("decodes a VIN only through the local API and keeps the full mechanical VehicleSpec", async () => {
    const vin = "1TESTCAR000000001";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      vin,
      decodeValid: true,
      vehicle: {
        vin,
        year: 2014,
        make: "MINI",
        model: "Hardtop",
        trim: "Cooper S",
        engine: "B48 / 2.0L / 4 cylinders / In-Line",
        transmission: "Automatic / 6 speeds",
        drivetrain: "FWD/Front-Wheel Drive",
        fuelType: "gasoline",
        bodyStyle: "Hatchback/Liftback/Notchback",
      },
      decodedFields: {},
      source: { provider: "NHTSA vPIC", sourceUrl: "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/example" },
      documentationUrl: "https://vpic.nhtsa.dot.gov/api/Home/Index",
      limitations: ["A decode does not verify title."],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const decoded = await api.decodeVin(vin, 2014);

    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:8000/v1/vehicles/decode-vin");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ vin, modelYear: 2014 });
    expect(decoded.vehicle).toMatchObject({
      engine: "B48 / 2.0L / 4 cylinders / In-Line",
      transmission: "Automatic / 6 speeds",
      drivetrain: "FWD/Front-Wheel Drive",
      fuel_type: "gasoline",
      body_style: "Hatchback/Liftback/Notchback",
    });
    expect(String(fetchMock.mock.calls[0][0])).not.toContain(vin);
  });

  it("posts an admitted-comparable candidate with is_target false and exact matching facts", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      caseId: "cloud-case-1",
      imported: 1,
      evidenceIds: ["evidence-1"],
      listingIds: ["listing-1"],
    }), { status: 201, headers: { "Content-Type": "application/json" } }));
    const record = demoCases[0];
    const listing = listingImportPayload({
      ...copyResolvedTargetConfiguration(comparableListingImportForm(record), record.vehicle),
      title: "2017 Toyota Corolla LE comparable",
      asking_price: "7950",
      mileage: "90000",
      listed_date: "2026-07-01",
      distance_miles: "35",
      production_date: "2017-02-01",
      body_style: "sedan",
    });

    await api.importListings("cloud-case-1", [listing]);

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    const payload = JSON.parse(String(request.body));
    expect(payload.listings[0]).toMatchObject({
      is_target: false,
      reference_kind: "asking",
      seller_type: "private",
      channel: "facebook_marketplace",
      listed_at: "2026-07-01T12:00:00.000Z",
      distance_miles: 35,
      year: 2017,
      make: "Toyota",
      model: "Corolla",
      trim: "LE",
      generation: "E170",
      platform: "E170",
      engine: "1.8L 2ZR-FE I4",
      transmission: "CVT",
      drivetrain: "FWD",
      production_date: "2017-02-01",
      fuel_type: "gasoline",
      body_style: "sedan",
    });
  });

  it("treats a business-rule 422 as an online API response and localizes it", () => {
    const error = new ApiError(
      "A usable case valuation with at least five admitted comparables is required",
      422,
    );

    expect(isApiConnectionFailure(error)).toBe(false);
    expect(apiErrorMessage(error, "zh-CN")).toContain("请求未通过业务规则校验");
    expect(apiErrorMessage(error, "en")).toContain("business rules");
  });

  it("turns FastAPI field-validation arrays into a readable field error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      detail: [{
        type: "enum",
        loc: ["body", "vehicle", "fuel_type"],
        msg: "Input should be a supported fuel type",
      }],
    }), { status: 422, headers: { "Content-Type": "application/json" } }));

    await expect(api.createCase({
      language: "en",
      vehicle: { year: 2014, make: "MINI", model: "Cooper S", fuel_type: "gasoline" },
    })).rejects.toMatchObject({
      status: 422,
      message: "vehicle.fuel_type: Input should be a supported fuel type",
    });
  });

  it("submits only the eligible confirmed adjustment and maps a successful offer response", async () => {
    const record = {
      ...demoCases[0],
      evidence: [
        { id: "scan-1", label: "Generic scan", source: "buyer", kind: "obd_scan", captured_at: "2026-07-13" },
        { id: "ppi-1", label: "Written PPI", source: "independent shop", kind: "ppi", captured_at: "2026-07-13" },
      ],
      findings: [
        {
          id: "suspected-P0301", title: "P0301 branch", summary: "Needs diagnosis", level: "high" as const,
          status: "possible" as const, category: "mechanical" as const, evidence_ids: ["scan-1"], exposure_low: 100,
        },
        {
          id: "confirmed-leak", title: "Confirmed coolant leak", summary: "Written PPI", level: "high" as const,
          status: "confirmed" as const, category: "mechanical" as const, evidence_ids: ["ppi-1"], exposure_low: 500,
        },
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      target: 7_500,
      opening: 7_100,
      ceiling: 7_650,
      evidenceReserve: 450,
      decision: "MAKE_OFFER",
      trace: [{ label: "Confirmed coolant leak", amount: -500, applied: true, reason: "Supported by PPI", evidenceIds: ["ppi-1"] }],
      message: "Conditional offer",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const adjustments = eligibleNegotiationAdjustments(record);
    const result = await api.draftNegotiation("cloud-case-1", {
      phase: "conditional_offer",
      language: "en",
      asking_price: 8_200,
      market_baseline: 8_450,
      all_in_budget: 8_500,
      evidence_coverage: 74,
      adjustments,
      buyer_mandatory_costs: 500,
    });

    const payload = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(payload.adjustments).toEqual([{
      label: "Confirmed coolant leak",
      category: "immediate_repair",
      amount: 500,
      finding_id: "confirmed-leak",
      evidence_ids: ["ppi-1"],
    }]);
    expect(JSON.stringify(payload)).not.toContain("P0301");
    expect(result).toMatchObject({ decision: "NEGOTIATE", target: 7_500, opening: 7_100, ceiling: 7_650 });
  });

  it("marks an actual fetch transport failure as offline with localized copy", () => {
    const error = new TypeError("fetch failed");

    expect(isApiConnectionFailure(error)).toBe(true);
    expect(apiErrorMessage(error, "zh-CN")).toContain("无法连接 API");
    expect(apiErrorMessage(error, "en")).toContain("Could not connect to the API");
  });

  it("remembers an imported cloud capability and sends it only in the case header", async () => {
    const importedCase = { ...apiCase(), id: "imported-case-1" };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        caseId: "imported-case-1",
        schemaVersion: "1.0",
        integrityVerified: true,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json", "X-OCDD-Case-Token": token },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(importedCase), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));

    const imported = await api.importCase("ZW5jcnlwdGVk", "long-passphrase");
    await api.getCase(imported.caseId);

    expect(imported.accessToken).toBe(token);
    expect(String(fetchMock.mock.calls[0][0]).endsWith("/v1/cases/import")).toBe(true);
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(secondUrl.endsWith("/v1/cases/imported-case-1")).toBe(true);
    expect(secondUrl).not.toContain(token);
    expect((fetchMock.mock.calls[1][1] as RequestInit).headers).toMatchObject({
      "X-OCDD-Case-Token": token,
    });
  });

  it("submits canonical inspection facts without inventing a failure severity", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("{}", {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));

    await api.saveInspection("cloud-case-1", {
      id: "drive",
      title: "冷启动与试驾 / Cold start and road test",
      checks: [{
        id: "post_drive_scan",
        label: "试驾后再次扫描 / Re-scan after the road test",
        status: "warn",
        note: "Two monitors remain not ready.",
        evidence_ids: ["scan-evidence-1"],
      }],
    });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    const payload = JSON.parse(String(request.body)) as { items: Array<Record<string, unknown>> };
    expect(payload.items[0]).toMatchObject({
      key: "post_drive_scan",
      stage: "road_test",
      result: "CONCERN",
      notes: "Two monitors remain not ready.",
      evidenceIds: ["scan-evidence-1"],
    });
    expect(payload.items[0]).not.toHaveProperty("severityIfFailed");
    expect(payload.items[0]).not.toHaveProperty("severity_if_failed");
  });

  it("sends an inspector assertion for a canonical PPI session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("{}", {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));

    await api.saveInspection("cloud-case-1", {
      id: "ppi",
      title: "Lift PPI",
      inspector: "Independent MINI specialist",
      checks: [{ id: "structural_underbody", label: "Structural underbody", status: "pass" }],
    });

    const payload = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(payload).toMatchObject({
      inspectionType: "ppi",
      inspector: "Independent MINI specialist",
    });
  });

  it("sends transient title identity inputs only in the artifact request body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("{}", {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));

    await api.uploadArtifact("cloud-case-1", {
      filename: "title.pdf",
      kind: "title",
      content_base64: "c2Vuc2l0aXZl",
      title_owner_name: "Jane Owner",
      seller_legal_name: "Jane Owner",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain("Jane Owner");
    expect(JSON.parse(String((init as RequestInit).body))).toMatchObject({
      title_owner_name: "Jane Owner",
      seller_legal_name: "Jane Owner",
    });
  });
});
