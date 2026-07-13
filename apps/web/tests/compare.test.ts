import { describe, expect, it } from "vitest";
import {
  compareResponseFromApi,
  comparisonRisk,
  comparisonRiskClass,
} from "../lib/compare";

describe("comparison risk mapping", () => {
  it("preserves explicit UNKNOWN and gives it the gray UI class", () => {
    const response = compareResponseFromApi({
      ranked: [{
        caseId: "empty-case",
        rank: 1,
        decision: "INSPECT",
        mechanicalRisk: "UNKNOWN",
        titleRisk: "UNKNOWN",
        coveragePercent: 0,
        reason: "unchecked",
      }],
      generatedAt: "2026-07-13T00:00:00Z",
    });

    expect(response.ranked[0]).toMatchObject({
      mechanicalRisk: "UNKNOWN",
      titleRisk: "UNKNOWN",
    });
    expect(comparisonRiskClass(response.ranked[0].mechanicalRisk)).toBe("risk-chip unknown");
  });

  it("fails closed to UNKNOWN for absent or unrecognized API values", () => {
    expect(comparisonRisk(undefined)).toBe("UNKNOWN");
    expect(comparisonRisk("SAFE")).toBe("UNKNOWN");
    const response = compareResponseFromApi({
      ranked: [{ case_id: "legacy-case", rank: 1, decision: "INSPECT" }],
    });
    expect(response.ranked[0].mechanicalRisk).toBe("UNKNOWN");
    expect(response.ranked[0].titleRisk).toBe("UNKNOWN");
  });

  it("maps the explicitly named unresolved planning exposure field", () => {
    const response = compareResponseFromApi({
      ranked: [{
        case_id: "repair-case",
        rank: 1,
        decision: "INSPECT",
        unresolved_planning_exposure: { low: 500, likely: 750, high: 1100 },
      }],
    });

    expect(response.ranked[0].unresolvedPlanningExposure).toEqual({
      low: 500,
      likely: 750,
      high: 1100,
      currency: "USD",
    });
  });
});
