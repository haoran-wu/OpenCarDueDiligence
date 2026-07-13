import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../components/Dashboard.tsx", import.meta.url), "utf8");

describe("listing import UI contract", () => {
  it("exposes target/comparable roles, evidence help, reference populations, and matching fields", () => {
    for (const phrase of [
      "Target vehicle",
      "Market comparable",
      "Enter only facts verified in this listing",
      "Asking price",
      "Sold price",
      "External reference value",
      "Distance from target (miles)",
      "Copy target config (verify each field)",
      "Generation",
      "Platform",
      "Production date",
      "Body style",
    ]) expect(dashboard).toContain(phrase);
  });

  it("keeps the long form scrollable and collapses role/config grids on a phone", () => {
    expect(css).toContain(".modal { width: min(570px, 100%); max-height: calc(100vh - 40px); overflow-y: auto;");
    expect(css).toContain(".modal.listing-import-modal { width: min(860px, 100%); }");
    const mobileStart = css.indexOf("@media (max-width: 520px)");
    const mobileEnd = css.indexOf("@media (prefers-reduced-motion", mobileStart);
    const mobileCss = css.slice(mobileStart, mobileEnd);
    expect(mobileCss).toContain(".form-pair, .form-triple, .state-grid, .listing-role { grid-template-columns: 1fr; }");
    expect(mobileCss).toContain(".modal.listing-import-modal { max-height: calc(100vh - 16px);");
  });
});
