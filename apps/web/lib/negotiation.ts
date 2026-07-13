import { apiErrorMessage, isApiError } from "./api";
import type { CaseRecord, Decision, Language, NegotiationRequest, NegotiationResponse } from "./types";

const negotiationEvidenceKinds = new Set([
  "ppi",
  "history_report",
  "state_inspection",
  "receipt",
]);

/**
 * Build the conservative default deduction set accepted by the server ledger.
 * A pending/suspected DTC is a reason to inspect, never an automatic repair bill.
 */
export function eligibleNegotiationAdjustments(record: CaseRecord): NegotiationRequest["adjustments"] {
  const eligibleEvidenceIds = new Set(
    record.evidence
      .filter((item) => item.kind !== undefined && negotiationEvidenceKinds.has(item.kind))
      .map((item) => item.id),
  );

  return record.findings.flatMap((finding) => {
    if (
      finding.status !== "confirmed"
      || !["mechanical", "inspection"].includes(finding.category)
      || finding.exposure_low === undefined
      || finding.exposure_low <= 0
    ) return [];

    const evidenceIds = finding.evidence_ids.filter((id) => eligibleEvidenceIds.has(id));
    if (!evidenceIds.length) return [];

    return [{
      label: finding.title,
      category: "immediate_repair" as const,
      amount: finding.exposure_low,
      finding_id: finding.id,
      evidence_ids: evidenceIds,
    }];
  });
}

/** Keep HTTP business-rule failures online and turn common negotiation failures into an action. */
export function negotiationErrorMessage(error: unknown, language: Language): string {
  if (!isApiError(error) || error.status !== 422) {
    return apiErrorMessage(
      error,
      language,
      language === "zh-CN" ? "谈价消息生成失败" : "Negotiation request failed",
    );
  }

  const detail = error.message.toLowerCase();
  if (detail.includes("valuation") || detail.includes("comparables")) {
    return language === "zh-CN"
      ? "报价未生成：请先导入至少 5 辆符合条件的可比车并重新分析。"
      : "Offer not generated: import at least five eligible comparables and re-run the analysis first.";
  }
  if (
    detail.includes("finding")
    || detail.includes("evidence")
    || detail.includes("estimate")
    || detail.includes("adjustment")
  ) {
    return language === "zh-CN"
      ? "报价未生成：只有已确认、已关联合格证据并有维修金额依据的项目才能扣款。疑似报码只提示继续检查，不会自动扣款。"
      : "Offer not generated: only confirmed findings linked to eligible evidence and a supported repair amount can be deducted. Suspected codes remain inspection items and are not automatic deductions.";
  }
  return apiErrorMessage(error, language);
}

export function shouldShowNegotiationArithmetic(phase: NegotiationRequest["phase"]): boolean {
  return phase !== "initial_contact";
}

export function reserveRate(coverage: number): number | undefined {
  if (coverage >= 85) return 0.02;
  if (coverage >= 65) return 0.05;
  if (coverage >= 40) return 0.1;
  return undefined;
}

export function calculateNegotiation(input: NegotiationRequest): NegotiationResponse {
  if (input.phase === "initial_contact") {
    const message = input.language === "zh-CN"
      ? "你好，我对这辆车有兴趣。方便先提供 VIN，并确认原始 title 在你本人名下、没有未解除的 lien 吗？另外，是否有近期保养记录？目前有没有故障灯、漏油漏水、机械或电气问题？是否允许我安排独立购前检查？谢谢。"
      : "Hi, I’m interested in the car. Could you send the VIN and confirm that the original title is in your name with no unresolved lien? Do you have recent maintenance records? Are there any warning lights, leaks, mechanical or electrical issues I should know about? Are you comfortable with an independent pre-purchase inspection? Thank you.";
    return {
      reserve: 0,
      decision: "INSPECT",
      message,
      trace: [{ label: "Initial seller screening", amount: 0, explanation: "No valuation or price offer is used for initial contact." }],
    };
  }

  const rate = reserveRate(input.evidence_coverage);
  const reserve = rate === undefined ? 0 : Math.round(input.market_baseline * rate);
  const adjustments = input.adjustments
    .filter((item) => !item.normal_wear)
    .reduce((total, item) => total + Math.max(0, item.amount), 0);
  const target = Math.max(0, Math.round(input.market_baseline - adjustments - reserve));
  const openingDiscount = Math.min(input.market_baseline * 0.05, 1000);
  const openingCandidate = Math.max(0, Math.round(Math.min(input.asking_price, target) - openingDiscount));
  const ceilingByValue = Math.round(target + Math.min(input.market_baseline * 0.02, 500));
  const ceilingByBudget = Math.max(0, input.all_in_budget - (input.buyer_mandatory_costs || 0));
  const ceiling = Math.min(ceilingByValue, ceilingByBudget);
  const hasFeasibleOfferBand = openingCandidate <= ceiling;
  const decision: Decision = rate === undefined
    ? "INSPECT"
    : !hasFeasibleOfferBand || (input.seller_floor !== undefined && input.seller_floor > ceiling)
      ? "STOP"
      : "NEGOTIATE";
  const opening = decision === "STOP" ? undefined : openingCandidate;

  const money = (value: number) => `$${value.toLocaleString("en-US")}`;
  const isZh = input.language === "zh-CN";
  const message =
    decision === "INSPECT"
      ? isZh
        ? "目前关键证据不足，我想先完成独立检查，再提出有依据的报价。"
        : "I still need a few key records and an independent inspection before making an evidence-based offer."
      : input.phase === "walk_away" || decision === "STOP"
        ? isZh
          ? `谢谢你的坦诚。根据检查结果和我的总预算，我的最高价格是 ${money(ceiling)}。如果之后你愿意考虑，欢迎联系我。`
          : `Thanks for being upfront. Based on the inspection findings and my all-in budget, my ceiling is ${money(ceiling)}. Please reach out if that becomes workable.`
        : isZh
          ? `如果产权文件无误且车辆通过独立检查，我可以提出 ${money(opening || 0)} 的有条件报价。检查发现的项目都已计入这个价格。`
          : `Provided the title checks out and the car passes an independent inspection, I can make a conditional offer of ${money(opening || 0)}. The documented inspection items are reflected in that number.`;

  return {
    target: rate === undefined ? undefined : target,
    opening: rate === undefined ? undefined : opening,
    ceiling: rate === undefined ? undefined : ceiling,
    reserve,
    decision,
    message,
    trace: [
      { label: "Market baseline", amount: input.market_baseline },
      { label: "Documented adjustments", amount: -adjustments },
      { label: "Evidence reserve", amount: -reserve },
    ],
  };
}
