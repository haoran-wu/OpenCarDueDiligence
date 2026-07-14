import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../components/Dashboard.tsx", import.meta.url), "utf8");

describe("production product UI contract", () => {
  it("uses semantic SVG navigation and avoids prototype-only visual artifacts", () => {
    expect(dashboard).toContain('from "lucide-react"');
    expect(dashboard).not.toMatch(/icon:\s*["'][⌂▤↔§≋]["']/);
    expect(dashboard).not.toContain("01 / SCREEN");
    expect(dashboard).not.toContain("DETERMINISTIC BOUNDARY");
    expect(css).not.toContain("translateY(-1px)");
    expect(css).not.toContain(".price-track");
  });

  it("keeps modal focus inside, supports Escape, and restores the invoking control", () => {
    expect(dashboard).toContain('role="dialog"');
    expect(dashboard).toContain('aria-modal="true"');
    expect(dashboard).toContain('event.key === "Escape"');
    expect(dashboard).toContain('event.key !== "Tab"');
    expect(dashboard).toContain("previousFocus?.focus()");
  });

  it("keeps decision colors distinct and switches the document language", () => {
    expect(css).toContain(".decision.negotiate { color: var(--info);");
    expect(css).toContain(".decision.buy_candidate { color: var(--success);");
    expect(dashboard).toContain("document.documentElement.lang = value");
    expect(dashboard).toContain("riskAxisNote(record, axis, language)");
    expect(dashboard).not.toContain("record.language !== language");
    expect(dashboard).toContain("Findings and evidence remain in their source language");
    expect(dashboard).toContain('.filter((finding) => finding.status !== "cleared")');
  });

  it("discloses local and cloud storage modes without making false privacy promises", () => {
    const tabletCss = css.slice(
      css.indexOf("@media (max-width: 1180px)"),
      css.indexOf("@media (max-width: 900px)"),
    );
    expect(dashboard).toContain("const health = await api.health()");
    expect(dashboard).toContain('health.deploymentMode === "cloud"');
    expect(dashboard).toContain("Cloud service connected");
    expect(dashboard).toContain('className="mobile-storage-status"');
    expect(tabletCss).toContain(".mobile-storage-status { min-width: 0; display: flex;");
    expect(tabletCss).toContain("flex: 0 0 100%");
    expect(dashboard).not.toContain("Sensitive originals stay on this device");
    expect(dashboard).not.toContain("Local by default");
    expect(dashboard).not.toContain("encrypted in transit");
    expect(dashboard).not.toContain("Permanently delete this case");
    expect(dashboard).not.toContain("confirm permanent deletion");
    expect(dashboard).toContain("This removes records from active application storage");
    expect(dashboard).toContain("WAL/backups");
  });
});
