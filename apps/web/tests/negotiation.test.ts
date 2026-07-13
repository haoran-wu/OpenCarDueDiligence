import { describe, expect, it } from "vitest";
import { ApiError } from "../lib/api";
import { demoCases } from "../lib/demo";
import { calculateNegotiation, eligibleNegotiationAdjustments, negotiationErrorMessage, reserveRate, shouldShowNegotiationArithmetic } from "../lib/negotiation";

describe("deterministic negotiation boundary", () => {
  it("uses the configured evidence reserve tiers", () => {
    expect(reserveRate(90)).toBe(0.02);
    expect(reserveRate(74)).toBe(0.05);
    expect(reserveRate(52)).toBe(0.1);
    expect(reserveRate(39)).toBeUndefined();
  });

  it("drafts initial screening questions without using valuation arithmetic", () => {
    const result = calculateNegotiation({
      phase: "initial_contact",
      language: "en",
      evidence_coverage: 0,
      adjustments: [],
    });

    expect(result.decision).toBe("INSPECT");
    expect(result.target).toBeUndefined();
    expect(result.opening).toBeUndefined();
    expect(result.ceiling).toBeUndefined();
    expect(result.reserve).toBe(0);
    expect(result.message).toContain("VIN");
    expect(result.message).toContain("maintenance records");
    expect(result.message).toContain("warning lights");
    expect(result.message).toContain("pre-purchase inspection");
    expect(shouldShowNegotiationArithmetic("initial_contact")).toBe(false);
    expect(shouldShowNegotiationArithmetic("conditional_offer")).toBe(true);
    expect(shouldShowNegotiationArithmetic("post_ppi")).toBe(true);
    expect(shouldShowNegotiationArithmetic("walk_away")).toBe(true);
  });

  it("does not double-deduct normal wear", () => {
    const result = calculateNegotiation({
      phase: "post_ppi",
      language: "en",
      asking_price: 6000,
      market_baseline: 6500,
      all_in_budget: 6500,
      evidence_coverage: 80,
      buyer_mandatory_costs: 500,
      adjustments: [
        { label: "coolant leak", category: "immediate_repair", amount: 600 },
        { label: "normal tire wear", category: "overdue_maintenance", amount: 500, normal_wear: false },
      ],
    });
    expect(result.reserve).toBe(325);
    expect(result.target).toBe(5075);
    expect(result.ceiling).toBeLessThanOrEqual(6000);
  });

  it("refuses a final ceiling below 40 percent evidence coverage", () => {
    const result = calculateNegotiation({
      phase: "conditional_offer",
      language: "en",
      asking_price: 5000,
      market_baseline: 5500,
      all_in_budget: 6000,
      evidence_coverage: 30,
      adjustments: [],
    });
    expect(result.decision).toBe("INSPECT");
    expect(result.ceiling).toBeUndefined();
    expect(result.message).toContain("inspection");
  });

  it("never proposes an opening above the all-in budget ceiling", () => {
    const result = calculateNegotiation({
      phase: "conditional_offer",
      language: "en",
      asking_price: 8000,
      market_baseline: 8000,
      all_in_budget: 3000,
      buyer_mandatory_costs: 500,
      evidence_coverage: 90,
      adjustments: [],
    });

    expect(result.ceiling).toBe(2500);
    expect(result.opening).toBeUndefined();
    expect(result.decision).toBe("STOP");
    expect(result.message).toContain("$2,500");
    expect(result.message).not.toContain("$7,440");
  });

  it("keeps suspected P0301 and P0420 branches out of automatic deductions", () => {
    const record = {
      ...demoCases[0],
      evidence: [
        { id: "scan-1", label: "Generic scan", source: "buyer", kind: "obd_scan", captured_at: "2026-07-13" },
      ],
      findings: ["P0301", "P0420"].map((code) => ({
        id: `finding-${code}`,
        title: `${code} diagnostic branch`,
        summary: "Confirmation required",
        level: "high" as const,
        status: "possible" as const,
        category: "mechanical" as const,
        evidence_ids: ["scan-1"],
        exposure_low: 150,
        exposure_high: 2_000,
      })),
    };

    expect(eligibleNegotiationAdjustments(record)).toEqual([]);
  });

  it("includes only a confirmed repair finding linked to eligible evidence", () => {
    const record = {
      ...demoCases[0],
      evidence: [
        { id: "scan-1", label: "Generic scan", source: "buyer", kind: "obd_scan", captured_at: "2026-07-13" },
        { id: "ppi-1", label: "Written PPI", source: "independent shop", kind: "ppi", captured_at: "2026-07-13" },
      ],
      findings: [
        {
          id: "suspected-misfire", title: "P0301 diagnostic branch", summary: "Confirmation required", level: "high" as const,
          status: "possible" as const, category: "mechanical" as const, evidence_ids: ["scan-1"], exposure_low: 100,
        },
        {
          id: "confirmed-leak", title: "Confirmed coolant leak", summary: "Pressure-test failure", level: "high" as const,
          status: "confirmed" as const, category: "mechanical" as const, evidence_ids: ["ppi-1"], exposure_low: 500,
        },
      ],
    };

    expect(eligibleNegotiationAdjustments(record)).toEqual([{
      label: "Confirmed coolant leak",
      category: "immediate_repair",
      amount: 500,
      finding_id: "confirmed-leak",
      evidence_ids: ["ppi-1"],
    }]);
  });

  it("explains negotiation evidence 422 responses without marking the API offline", () => {
    const error = new ApiError(
      "findingId does not identify an eligible finding linked to the supplied evidenceIds",
      422,
    );

    expect(negotiationErrorMessage(error, "zh-CN")).toContain("疑似报码");
    expect(negotiationErrorMessage(error, "en")).toContain("Suspected codes");
  });
});
