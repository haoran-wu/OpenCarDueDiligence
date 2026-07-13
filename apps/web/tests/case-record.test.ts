import { describe, expect, it } from "vitest";
import { caseRecordFromApi } from "../lib/case-record";

function baseCase(overrides: Record<string, unknown> = {}) {
  return {
    id: "case-1",
    status: "DISCOVERED",
    decision: "INSPECT",
    vehicle: { year: 2014, make: "MINI", model: "Cooper S", fuelType: "gasoline" },
    listings: [],
    sources: [],
    evidence: [],
    scans: [],
    inspections: [],
    findings: [],
    coveragePercent: 0,
    createdAt: "2026-07-13T00:00:00Z",
    updatedAt: "2026-07-13T00:00:00Z",
    ...overrides,
  };
}

describe("API case to UI record", () => {
  it("keeps every unchecked area unknown instead of borrowing demo passes", () => {
    const record = caseRecordFromApi(baseCase());

    expect(record.name).toBe("2014 MINI Cooper S");
    expect(record.listing.asking_price).toBe(0);
    expect(record.inspections.flatMap((stage) => stage.checks).every((check) => check.status === "unknown")).toBe(true);
    expect(record.diagnostics.readiness).toBe("unknown");
    expect(record.diagnostics.not_covered).toEqual(expect.arrayContaining(["ABS", "SRS"]));
    expect(record.risk_axes.find((axis) => axis.id === "mechanical")?.level).toBe("unknown");
    expect(record.transaction_plan.hard_gates).toEqual([]);
  });

  it("maps declared generic scan coverage, findings, evidence, and valuation", () => {
    const record = caseRecordFromApi(baseCase({
      coveragePercent: 72,
      listings: [{ id: "listing-1", title: "2014 MINI Cooper S", askingPrice: 5500, mileage: 120000, currency: "USD", sellerType: "private", channel: "facebook_marketplace", isTarget: true, capturedAt: "2026-07-13T00:00:00Z" }],
      sources: [{ id: "source-1", provider: "buyer", sourceType: "obd_scan" }],
      evidence: [{ id: "evidence-1", sourceId: "source-1", kind: "obd_scan", label: "Generic scan", observedAt: "2026-07-13T00:00:00Z", redacted: false }],
      scans: [{ dtcs: [{ code: "P0301", status: "pending" }], readiness: [{ name: "catalyst", status: "NOT_READY" }], moduleCoverage: { powertrain: "SCANNED", abs: "NOT_SCANNED", srs: "NOT_SCANNED", body: "NOT_SCANNED" } }],
      findings: [{ id: "finding-1", code: "DTC_P0301", area: "engine", title: "Cylinder 1 misfire signal", detail: "Diagnosis required", severity: "HIGH", status: "SUSPECTED", evidenceIds: ["evidence-1"], nextChecks: ["Inspect freeze frame"], repairScenarios: [{ cost: { low: 100, likely: 300, high: 1800 } }] }],
      valuation: { referenceKind: "asking_price_range", weightedMedian: 6200, q25: 5600, q75: 6900, sampleCount: 9, confidence: "MEDIUM" },
    }));

    expect(record.diagnostics.codes).toEqual(["P0301"]);
    expect(record.diagnostics.readiness).toBe("not_ready");
    expect(record.diagnostics.coverage).toEqual(["POWERTRAIN"]);
    expect(record.diagnostics.not_covered.join(" ")).toContain("ABS");
    expect(record.findings[0]).toMatchObject({ level: "high", status: "possible", exposure_low: 100, exposure_high: 1800 });
    expect(record.evidence[0]).toMatchObject({ source: "buyer", kind: "obd_scan", status: "unverified" });
    expect(record.valuation).toMatchObject({ market_median: 6200, sample_count: 9, confidence: "medium" });
  });

  it("selects the latest target snapshot by capture time and keeps input history intact", () => {
    const listings = [
      { id: "target-latest", title: "Refreshed listing", askingPrice: 5300, mileage: 121500, isTarget: true, capturedAt: "2026-07-13T12:00:00Z" },
      { id: "target-old", title: "Original listing", askingPrice: 6000, mileage: 120000, isTarget: true, capturedAt: "2026-07-12T12:00:00Z" },
    ];

    const record = caseRecordFromApi(baseCase({ listings }));

    expect(record.name).toBe("Refreshed listing");
    expect(record.listing).toMatchObject({ id: "target-latest", asking_price: 5300, mileage: 121500 });
    expect(listings).toHaveLength(2);
    expect(listings.every((listing) => listing.isTarget)).toBe(true);
  });

  it("includes only suspected or confirmed findings in unresolved repair planning exposure", () => {
    const record = caseRecordFromApi(baseCase({
      findings: [
        { id: "active", code: "ACTIVE", area: "engine", title: "Active", detail: "Pending", severity: "MEDIUM", status: "SUSPECTED", repairScenarios: [{ cost: { low: 100, likely: 250, high: 500 } }] },
        { id: "confirmed", code: "CONFIRMED", area: "brakes", title: "Confirmed", detail: "Outstanding", severity: "HIGH", status: "CONFIRMED", repairScenarios: [{ cost: { low: 400, likely: 500, high: 600 } }] },
        { id: "resolved", code: "RESOLVED", area: "transmission", title: "Resolved", detail: "Complete", severity: "HIGH", status: "RESOLVED", repairScenarios: [{ cost: { low: 2000, likely: 4000, high: 7000 } }] },
        { id: "unknown", code: "UNKNOWN", area: "electrical", title: "Unknown", detail: "Not established", severity: "HIGH", status: "UNKNOWN", repairScenarios: [{ cost: { low: 3000, likely: 5000, high: 8000 } }] },
      ],
    }));

    expect(record.unresolved_planning_exposure).toEqual([500, 1100]);
  });

  it("uses the listing ID as a deterministic tie-breaker", () => {
    const capturedAt = "2026-07-13T12:00:00Z";
    const record = caseRecordFromApi(baseCase({ listings: [
      { id: "target-z", title: "Tie winner", askingPrice: 5400, isTarget: true, capturedAt },
      { id: "target-a", title: "Tie loser", askingPrice: 5600, isTarget: true, capturedAt },
    ] }));

    expect(record.listing).toMatchObject({ id: "target-z", asking_price: 5400 });
  });
});
