import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { mobileCaseLabel } from "../lib/mobile-case-label";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../components/Dashboard.tsx", import.meta.url), "utf8");

describe("mobile case navigation", () => {
  it("labels options only from non-sensitive vehicle specification fields", () => {
    expect(mobileCaseLabel({ year: 2017, make: "Toyota", model: "Corolla", trim: "LE" }, 0, "en"))
      .toBe("2017 Toyota Corolla LE");
    expect(mobileCaseLabel({ year: 2014, make: "MINI", model: "Cooper S", trim: "S" }, 0, "en"))
      .toBe("2014 MINI Cooper S");
    expect(mobileCaseLabel({}, 1, "zh-CN")).toBe("车辆 2");
  });

  it("renders an accessible case selector and new-case action", () => {
    expect(dashboard).toContain('className="mobile-case-controls"');
    expect(dashboard).toContain('aria-label={language === "zh-CN" ? "选择候选车辆案件" : "Select vehicle case"}');
    expect(dashboard).toContain('className="mobile-new-case"');
    expect(dashboard).toContain("mobileCaseLabel(item.vehicle, index, language)");
    expect(dashboard).toContain('aria-label={language === "zh-CN" ? "添加车源" : "Add listing"}');
  });

  it("exposes the controls at mobile width without a fixed content width", () => {
    const mobileStart = css.indexOf("@media (max-width: 800px)");
    const mobileEnd = css.indexOf("@media (max-width: 520px)", mobileStart);
    const mobileCss = css.slice(mobileStart, mobileEnd);
    expect(mobileCss).toContain(".mobile-case-controls { width: 100%; min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto;");
    expect(mobileCss).toContain(".mobile-case-controls label { min-width: 0;");
    expect(mobileCss).toContain(".sidebar { position: static; height: 0;");
    expect(mobileCss).toContain("grid-template-columns: repeat(6, minmax(0, 1fr))");
    expect(mobileCss).not.toMatch(/\.mobile-case-controls[^}]*display:\s*none/);
  });
});
