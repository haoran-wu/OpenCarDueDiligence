import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CANONICAL_INSPECTION_ITEM_COUNT,
  CANONICAL_INSPECTION_STAGES,
  createInspectionTemplate,
} from "../lib/inspection-checklist";

type ChecklistSource = {
  default_result: string;
  stages: Array<{ id: string; items: Array<{ id: string }> }>;
};

describe("canonical five-stage inspection UI", () => {
  it("starts all 41 checks as unknown across all five stages", () => {
    const template = createInspectionTemplate();
    expect(CANONICAL_INSPECTION_ITEM_COUNT).toBe(41);
    expect(template).toHaveLength(5);
    expect(template.flatMap((stage) => stage.checks)).toHaveLength(41);
    expect(template.flatMap((stage) => stage.checks).every((check) => check.status === "unknown")).toBe(true);
    expect(template.flatMap((stage) => stage.checks).every((check) => check.label.includes(" / "))).toBe(true);
  });

  it("keeps every browser check ID in parity with the first-party YAML source", () => {
    const sourcePath = fileURLToPath(new URL("../../../data/checklists/five_stage_inspection_v1.yaml", import.meta.url));
    const source = JSON.parse(readFileSync(sourcePath, "utf8")) as ChecklistSource;
    const sourceIds = source.stages.flatMap((stage) => stage.items.map((item) => item.id));
    const browserIds = CANONICAL_INSPECTION_STAGES.flatMap((stage) => stage.items.map(([id]) => id));

    expect(source.default_result).toBe("UNKNOWN");
    expect(new Set(browserIds).size).toBe(41);
    expect(browserIds).toEqual(sourceIds);
  });
});
