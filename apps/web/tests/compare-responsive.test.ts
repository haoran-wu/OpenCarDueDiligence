import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../components/Dashboard.tsx", import.meta.url), "utf8");

describe("mobile comparison presentation", () => {
  it("keeps every decision-relevant field in a labeled mobile card", () => {
    for (const className of [
      "comparison-vehicle",
      "comparison-field",
      "comparison-rank",
    ]) {
      expect(dashboard).toContain(`className=\"${className}`);
    }
    expect(dashboard).toContain('className="comparison-field mini-coverage"');

    expect(dashboard).toContain("Mechanical risk");
    expect(dashboard).toContain("Title risk");
    expect(dashboard).toContain("row.askingPrice");
    expect(dashboard).toContain("row.coveragePercent");
    expect(dashboard).toContain("row.unresolvedPlanningExposure");
  });

  it("switches rows from a wide grid to two-column cards without hiding fields", () => {
    const mobileStart = css.indexOf("@media (max-width: 520px)");
    const mobileEnd = css.indexOf("@media (prefers-reduced-motion", mobileStart);
    const mobileCss = css.slice(mobileStart, mobileEnd);

    expect(mobileCss).toContain(".comparison-row { position: relative; min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(mobileCss).toContain(".mobile-label { display: block;");
    expect(mobileCss).not.toMatch(/\.comparison-field[^}]*display:\s*none/);
  });
});
