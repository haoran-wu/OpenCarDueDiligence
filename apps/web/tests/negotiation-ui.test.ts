import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../components/Dashboard.tsx", import.meta.url), "utf8");

describe("negotiation adjustment UI contract", () => {
  it("uses the conservative eligibility helper and lets the buyer remove a confirmed deduction", () => {
    expect(dashboard).toContain("eligibleNegotiationAdjustments(record)");
    expect(dashboard).toContain('type="checkbox"');
    expect(dashboard).toContain("toggleAdjustment(item.finding_id)");
    expect(dashboard).toContain("excludedFindingIds.has(item.finding_id)");
  });

  it("labels suspected findings as inspection-only instead of showing a repair deduction", () => {
    expect(dashboard).toContain('finding.status === "possible"');
    expect(dashboard).toContain("Needs inspection (not deducted)");
    expect(dashboard).toContain("待检查（不扣款）");
    expect(css).toContain(".deductions .inspection-only-note");
  });
});
