import { describe, expect, it } from "vitest";
import { buildLocalTransactionPlan } from "../lib/transaction";
import type { TransactionContextInput } from "../lib/types";

const readyContext = (overrides: Partial<TransactionContextInput> = {}): TransactionContextInput => ({
  purchase_date: "2026-07-12",
  buyer_residence_state: "NJ",
  buyer_license_state: "NJ",
  garaging_state: "NJ",
  registration_state: "NJ",
  sale_state: "NY",
  title_state: "NY",
  seller_type: "private",
  title_name_matches: true,
  vin_matches: true,
  original_title_present: true,
  seller_allows_ppi: true,
  seller_allows_bill_of_sale: true,
  seller_discloses_odometer: true,
  lien_status: "none",
  insurance_active_for_vin: true,
  legal_transport: "temporary_permit",
  ...overrides,
});

describe("local transaction gate semantics", () => {
  it("keeps unanswered seller questions at INSPECT, not STOP", () => {
    const plan = buildLocalTransactionPlan(readyContext({
      seller_allows_ppi: null,
      seller_allows_bill_of_sale: null,
      seller_discloses_odometer: null,
    }), "en");
    expect(plan.decision).toBe("INSPECT");
    expect(plan.hard_gates.filter((gate) => gate.status === "verify")).toHaveLength(3);
    expect(plan.hard_gates.some((gate) => gate.status === "blocked")).toBe(false);
  });

  it("stops when the seller explicitly refuses a PPI", () => {
    const plan = buildLocalTransactionPlan(readyContext({ seller_allows_ppi: false }), "en");
    expect(plan.decision).toBe("STOP");
    expect(plan.hard_gates).toContainEqual(expect.objectContaining({ id: "ppi", status: "blocked" }));
  });

  it("reaches BUY_CANDIDATE only after every hard gate is satisfied", () => {
    expect(buildLocalTransactionPlan(readyContext(), "en").decision).toBe("BUY_CANDIDATE");
  });
});
