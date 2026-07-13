import type { Language, TransactionContextInput, TransactionPlan, TransactionTask } from "./types";

export function buildLocalTransactionPlan(context: TransactionContextInput, language: Language): TransactionPlan {
  const zh = language === "zh-CN";
  const gates: TransactionTask[] = [];
  const add = (id: string, title: string, detail: string, status: "blocked" | "verify") => {
    gates.push({ id, title, detail, status });
  };

  if (!context.original_title_present) add(
    "title",
    zh ? "原始 title 尚未核对" : "Original title not verified",
    zh ? "付款前必须查看可转让的原始产权证。" : "Inspect a transferable original title before payment.",
    "verify",
  );
  if (!context.title_name_matches) add(
    "name",
    zh ? "姓名尚未核对" : "Owner identity not verified",
    zh ? "卖家身份证姓名必须与 title 车主一致。" : "Seller ID must match the owner named on the title.",
    "verify",
  );
  if (!context.vin_matches) add(
    "vin",
    zh ? "VIN 尚未一致核对" : "VIN not verified",
    zh ? "title、车身和历史报告上的 VIN 必须完全一致。" : "VIN on the title, vehicle, and history report must match exactly.",
    "verify",
  );

  const sellerGate = (
    value: boolean | null,
    id: string,
    unknownTitle: string,
    refusedTitle: string,
    detail: string,
  ) => {
    if (value === null) add(id, unknownTitle, detail, "verify");
    else if (value === false) add(id, refusedTitle, detail, "blocked");
  };
  sellerGate(
    context.seller_allows_ppi,
    "ppi",
    zh ? "是否允许独立 PPI：未知" : "Independent PPI permission unknown",
    zh ? "卖家拒绝独立 PPI" : "Seller refused independent PPI",
    zh ? "先询问；明确拒绝独立购前检查时停止交易。" : "Ask first; stop if the seller explicitly refuses an independent pre-purchase inspection.",
  );
  sellerGate(
    context.seller_allows_bill_of_sale,
    "bill-of-sale",
    zh ? "是否签署 Bill of Sale：未知" : "Bill of sale agreement unknown",
    zh ? "卖家拒绝签署 Bill of Sale" : "Seller refused a bill of sale",
    zh ? "先确认卖家愿意签署包含 VIN、价格和日期的凭证。" : "Confirm the seller will sign a bill of sale with VIN, price, and date.",
  );
  sellerGate(
    context.seller_discloses_odometer,
    "odometer",
    zh ? "里程披露意愿：未知" : "Odometer disclosure unknown",
    zh ? "卖家拒绝里程披露" : "Seller refused odometer disclosure",
    zh ? "先确认卖家愿意完成适用的真实里程披露。" : "Confirm the seller will complete the applicable truthful odometer disclosure.",
  );

  if (context.lien_status === "unresolved") add(
    "lien",
    zh ? "Lien 未解除" : "Lien unresolved",
    zh ? "取得正式 lien release 后再付款。" : "Obtain an official lien release before payment.",
    "blocked",
  );
  if (context.lien_status === "unknown") add(
    "lien",
    zh ? "Lien 状态未知" : "Lien status unknown",
    zh ? "在付款前确认无有效 lien，或取得正式 release。" : "Confirm there is no active lien, or obtain a formal release, before payment.",
    "verify",
  );
  if (!context.insurance_active_for_vin) add(
    "insurance",
    zh ? "保险尚未生效" : "Insurance not active",
    zh ? "该 VIN 上路前必须已有生效保险。" : "Bind coverage to this VIN before driving.",
    "blocked",
  );
  if (context.legal_transport === "none") add(
    "transport",
    zh ? "没有合法运输方案" : "No legal transport",
    zh ? "Bill of sale 不能代替车牌；办理 permit、合法登记或拖车。" : "A bill of sale is not a plate; obtain a permit/registration or tow it.",
    "blocked",
  );

  const decision = gates.some((gate) => gate.status === "blocked")
    ? "STOP"
    : gates.some((gate) => gate.status === "verify")
      ? "INSPECT"
      : "BUY_CANDIDATE";
  return {
    decision,
    verified_as_of: "2026-07-12",
    hard_gates: gates,
    tasks: [
      {
        id: "sign",
        title: zh ? "签署 title 与 bill of sale" : "Sign title and bill of sale",
        detail: zh ? "核对 VIN、里程、成交价和日期，禁止涂改。" : "Verify VIN, mileage, price, and date; do not alter the title.",
        status: "required",
      },
      {
        id: "dmv",
        title: `${context.registration_state} ${zh ? "登记与缴税" : "title, registration, and tax"}`,
        detail: zh ? "按注册州官方 DMV 要求提交原始材料。" : "Submit originals under the registration state's official DMV rules.",
        status: "verify",
      },
    ],
  };
}
