import type { CaseRecord, Language } from "./types";

/**
 * Produces the deliberately narrow label used by the mobile case switcher.
 * Only vehicle specification fields are accepted, so listing URLs, seller
 * details, locations, VINs, and internal case identifiers cannot leak here.
 */
export function mobileCaseLabel(vehicle: CaseRecord["vehicle"], index: number, language: Language): string {
  const trim = String(vehicle.trim || "").trim();
  const model = String(vehicle.model || "").trim();
  const modelAlreadyIncludesTrim = Boolean(trim) && (
    model.toLocaleLowerCase() === trim.toLocaleLowerCase()
    || model.toLocaleLowerCase().endsWith(` ${trim.toLocaleLowerCase()}`)
  );
  const label = [vehicle.year, vehicle.make, model, modelAlreadyIncludesTrim ? "" : trim]
    .filter((value) => value !== undefined && String(value).trim().length > 0)
    .map(String)
    .join(" ");
  if (label) return label;
  return `${language === "zh-CN" ? "车辆" : "Vehicle"} ${index + 1}`;
}
