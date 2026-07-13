"""Deterministic private-sale transaction planning for NJ, NY, and CT.

The engine deliberately separates legal/transaction gates from mechanical advice.
It reads versioned, JSON-compatible YAML rule bundles from ``data/rules`` and
never asks an LLM to infer DMV requirements.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from app.models import (
    Decision,
    InspectionResult,
    LienStatus,
    MatchStatus,
    SellerType,
    TitleStatus,
    TransactionContext,
    TransactionGate,
    TransactionPlan,
    TransactionStep,
    TransportOption,
)


SUPPORTED_STATES = frozenset({"NJ", "NY", "CT"})
DRIVING_OPTIONS = frozenset(
    {TransportOption.VALID_TEMP_PERMIT, TransportOption.VALID_REGISTRATION_AND_PLATE}
)
NON_DRIVING_TRANSPORT = frozenset({TransportOption.TOW, TransportOption.CARRIER})
ILLEGAL_TRANSPORT = frozenset(
    {
        TransportOption.SELLER_PLATE,
        TransportOption.BORROWED_PLATE,
        TransportOption.DRIVE_UNREGISTERED,
    }
)


def _data_root() -> Path:
    override = os.getenv("OCDD_DATA_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        return root if root.name == "data" else root / "data"
    return Path(__file__).resolve().parents[4] / "data"


def _as_of() -> date:
    override = os.getenv("OCDD_RULES_AS_OF")
    return date.fromisoformat(override) if override else date.today()


def _read_json_yaml(path: Path) -> dict[str, Any]:
    """Read rule files that intentionally use the JSON subset of YAML."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LookupError(f"Rule bundle not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON-compatible YAML rule bundle: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Rule bundle must be an object: {path}")
    return payload


def _load_common_bundle() -> dict[str, Any]:
    return _read_json_yaml(_data_root() / "rules" / "common" / "private_sale_v1.yaml")


def _load_state_bundle(state: str) -> dict[str, Any] | None:
    state = state.upper()
    candidates = sorted((_data_root() / "rules" / "states").glob(f"{state}-*.yaml"))
    return _read_json_yaml(candidates[-1]) if candidates else None


def _source_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["id"]: source for source in bundle.get("sources", [])}


def _source_for(bundle: dict[str, Any], support: str) -> dict[str, Any] | None:
    sources = bundle.get("sources", [])
    for source in sources:
        if support in source.get("supports", []):
            return source
    return sources[0] if sources else None


def _verified_date(bundle: dict[str, Any]) -> date:
    return date.fromisoformat(bundle["verified_at"])


def _is_stale(bundle: dict[str, Any], as_of: date) -> bool:
    verified = _verified_date(bundle)
    return (as_of - verified).days > int(bundle.get("refresh_after_days", 90))


def _deadline_text(bundle: dict[str, Any], deadline_id: str) -> str | None:
    for deadline in bundle.get("deadlines", []):
        if deadline.get("id") != deadline_id:
            continue
        duration = deadline.get("duration")
        unit = str(deadline.get("unit", "days")).replace("_", " ")
        consequence = deadline.get("consequence")
        result = f"Within {duration} {unit} of {deadline.get('anchor', 'the applicable date').replace('_', ' ')}"
        return f"{result}; {consequence}" if consequence else result
    return None


def _state_step(
    *,
    order: int,
    category: str,
    title: str,
    detail: str,
    bundle: dict[str, Any] | None,
    source_id: str | None = None,
    support: str | None = None,
    deadline: str | None = None,
    stale: bool = False,
) -> TransactionStep:
    source: dict[str, Any] | None = None
    if bundle:
        source = _source_map(bundle).get(source_id) if source_id else None
        source = source or (_source_for(bundle, support) if support else None)
    return TransactionStep(
        order=order,
        category=category,
        title=title,
        detail=detail,
        deadline=deadline,
        official_url=source.get("url") if source else None,
        verified_as_of=_verified_date(bundle) if bundle else None,
        requires_confirmation=stale or bundle is None,
    )


def _rule_message(common: dict[str, Any], rule_id: str, fallback: str) -> str:
    for rule in common.get("hard_stops", []):
        if rule.get("id") == rule_id:
            return str(rule.get("message_en") or fallback)
    return fallback


def _gate(
    code: str,
    label: str,
    blocked: bool,
    reason: str,
    evidence_needed: str | None = None,
) -> TransactionGate:
    return TransactionGate(
        code=code,
        label=label,
        blocked=blocked,
        reason=reason,
        evidence_needed=evidence_needed if blocked else None,
    )


def _registration_fee_summary(bundle: dict[str, Any]) -> str:
    state = bundle["jurisdiction"]
    if state == "NJ":
        return (
            "Budget $60 for a standard title ($85 with one lien; $110 with two), "
            "vehicle-dependent registration, and 6.625% sales tax unless exempt."
        )
    if state == "NY":
        return (
            "Budget the applicable registration charge, $50 title fee, and state/local "
            "sales tax calculated by DMV; a private sale uses DTF-802."
        )
    return (
        "For a regular CT passenger vehicle, current listed components include $120 "
        "registration, $5 plate, $25 title, $10 administrative, applicable Clean Air/"
        "Passport-to-the-Parks and other conditional fees, plus 6.35% private-sale tax "
        "(7.75% over $50,000) on the higher of bill-of-sale or NADA average trade-in value."
    )


def _build_gates(context: TransactionContext, common: dict[str, Any]) -> tuple[list[TransactionGate], bool, bool]:
    """Return gates, whether a definitive stop exists, and whether evidence is incomplete."""

    gates: list[TransactionGate] = []
    definitive_stop = False
    incomplete = False

    if context.title_status == TitleStatus.ORIGINAL:
        gates.append(_gate("title_document", "Original transferable title", False, "Original title reported present."))
    elif context.title_status in {TitleStatus.MISSING, TitleStatus.ALTERED, TitleStatus.ALREADY_ASSIGNED}:
        definitive_stop = True
        rule = "missing_original_title" if context.title_status == TitleStatus.MISSING else "title_altered"
        gates.append(
            _gate(
                "title_document",
                "Original transferable title",
                True,
                _rule_message(common, rule, "Do not pay until title is corrected."),
                "Correct original ownership document issued or accepted by the title state",
            )
        )
    elif context.title_status == TitleStatus.BRANDED:
        incomplete = True
        gates.append(
            _gate(
                "branded_title_review",
                "Branded-title suitability",
                True,
                "A branded title may be transferable, but insurance, inspection, value, and repair documentation require specialist review.",
                "Brand details, repair evidence, enhanced inspection requirements, and written insurance eligibility",
            )
        )
    else:
        incomplete = True
        gates.append(
            _gate(
                "title_document",
                "Original transferable title",
                True,
                "Title status has not been verified.",
                "Inspect the original title, assignment chain, brands, and alteration/lien areas",
            )
        )

    if context.lien_status in {LienStatus.CLEAR, LienStatus.RELEASE_ATTACHED}:
        gates.append(_gate("lien_clearance", "Lien clearance", False, "Lien is reported clear or an acceptable release is attached."))
    elif context.lien_status == LienStatus.ACTIVE:
        definitive_stop = True
        gates.append(
            _gate(
                "lien_clearance",
                "Lien clearance",
                True,
                _rule_message(common, "unreleased_lien", "Do not pay with an active lien."),
                "Original lien release or a lender-controlled payoff/title-transfer process",
            )
        )
    else:
        incomplete = True
        gates.append(_gate("lien_clearance", "Lien clearance", True, "Lien status is unknown.", "Title/lien record and any original lien release"))

    for code, label, value, mismatch_rule, evidence in (
        ("seller_title_identity", "Seller identity matches titled owner", context.identity_title_match, "seller_title_identity_mismatch", "In-person ID-to-title match or documented signing authority"),
        ("vin_match", "VIN matches vehicle and ownership documents", context.vin_match, "vin_mismatch", "Dashboard, door-label, title, and diagnostic VIN match"),
    ):
        if value == MatchStatus.MATCH:
            gates.append(_gate(code, label, False, "Match reported."))
        elif value == MatchStatus.MISMATCH:
            definitive_stop = True
            gates.append(_gate(code, label, True, _rule_message(common, mismatch_rule, "Do not pay: mismatch."), evidence))
        else:
            incomplete = True
            gates.append(_gate(code, label, True, "Match has not been verified.", evidence))

    for code, label, value, rule_id, evidence in (
        ("ppi_permission", "Independent PPI permitted", context.seller_allows_ppi, "seller_refuses_ppi", "Written seller permission and an inspection appointment"),
        ("bill_of_sale", "Signed bill of sale available", context.seller_allows_bill_of_sale, "seller_refuses_bill_of_sale", "Seller agreement to sign a complete bill of sale"),
        ("odometer_disclosure", "Odometer disclosure available", context.seller_will_disclose_odometer, "odometer_disclosure_refused", "Required odometer statement on title or state form"),
    ):
        if value is True:
            gates.append(_gate(code, label, False, "Seller agreed."))
        elif value is False:
            definitive_stop = True
            gates.append(_gate(code, label, True, _rule_message(common, rule_id, "Seller refused a required safeguard."), evidence))
        else:
            incomplete = True
            gates.append(_gate(code, label, True, "Seller response is unknown.", evidence))

    if context.transport_option in ILLEGAL_TRANSPORT:
        definitive_stop = True
        gates.append(
            _gate(
                "legal_transport",
                "Legal transport from the sale",
                True,
                _rule_message(common, "illegal_transport_plate", "The selected transport method is illegal."),
                "Tow/carrier booking or a valid plate/permit issued for this vehicle",
            )
        )
    elif context.transport_option == TransportOption.UNDECIDED:
        incomplete = True
        gates.append(_gate("legal_transport", "Legal transport from the sale", True, "No lawful transport option has been selected.", "Tow/carrier booking or valid permit/registration for this vehicle"))
    else:
        gates.append(_gate("legal_transport", "Legal transport from the sale", False, f"Selected option: {context.transport_option.value}."))

    insurance_needed_to_drive = context.transport_option in DRIVING_OPTIONS
    if insurance_needed_to_drive and not context.insurance_active_for_vin:
        definitive_stop = True
        gates.append(
            _gate(
                "vin_insurance",
                "Insurance active for this VIN",
                True,
                _rule_message(common, "drive_without_vin_insurance", "Do not drive without VIN-specific insurance."),
                "Insurance ID card, declaration page, or binder acceptable to the issuing state",
            )
        )
    else:
        reason = "Insurance is reported active for the VIN." if context.insurance_active_for_vin else "Not required to tow/carrier the vehicle; bind coverage before any later road use."
        gates.append(_gate("vin_insurance", "Insurance active for this VIN", False, reason))

    if context.registration_state != context.buyer_residence_state or context.garaging_state != context.registration_state:
        incomplete = True
        gates.append(
            _gate(
                "residence_garaging_registration",
                "Residence, garaging, and registration basis",
                True,
                "The supplied residence, garaging, and registration states differ; eligibility and insurance rating must be confirmed using the real addresses.",
                "Written insurer confirmation and registration-state eligibility",
            )
        )

    return gates, definitive_stop, incomplete


def build_transaction_plan(context: TransactionContext | Mapping[str, Any]) -> TransactionPlan:
    """Build an evidence-gated, source-linked private-sale transaction plan.

    A mapping is accepted for CLI/plugin callers; it is validated through the same
    Pydantic schema as API requests.  No raw seller name is required or retained.
    """

    if not isinstance(context, TransactionContext):
        context = TransactionContext.model_validate(context)

    common = _load_common_bundle()
    as_of = _as_of()
    requested_states = {context.sale_state, context.title_state, context.registration_state}
    bundles = {state: _load_state_bundle(state) for state in requested_states}
    available = {state: bundle for state, bundle in bundles.items() if bundle is not None}
    stale_states = {state for state, bundle in available.items() if _is_stale(bundle, as_of)}
    pending_human_signoff = {
        state
        for state, bundle in available.items()
        if bundle.get("provenance", {}).get("human_reviewed") is not True
    }
    unsupported_states = requested_states - available.keys()

    transfer_bundle = bundles.get(context.title_state) or bundles.get(context.sale_state)
    sale_bundle = bundles.get(context.sale_state)
    registration_bundle = bundles.get(context.registration_state)
    transfer_stale = context.title_state in stale_states or (transfer_bundle is sale_bundle and context.sale_state in stale_states)
    sale_stale = context.sale_state in stale_states
    registration_stale = context.registration_state in stale_states
    transfer_requires_confirmation = transfer_stale or context.title_state in pending_human_signoff or (
        transfer_bundle is sale_bundle and context.sale_state in pending_human_signoff
    )
    sale_requires_confirmation = sale_stale or context.sale_state in pending_human_signoff
    registration_requires_confirmation = registration_stale or context.registration_state in pending_human_signoff

    gates, definitive_stop, incomplete = _build_gates(context, common)
    warnings: list[str] = []

    if pending_human_signoff:
        incomplete = True
        warnings.append(
            "Official-source bundles were machine-checked but still await maintainer human signoff "
            f"for: {', '.join(sorted(pending_human_signoff))}. Confirm material fees, forms, "
            "eligibility, and permit availability with the linked DMV before acting."
        )

    if context.seller_type != SellerType.PRIVATE:
        incomplete = True
        warnings.append("This planner contains private-party rules only; dealer/unknown-seller transactions require a separate rule bundle.")
    if unsupported_states:
        incomplete = True
        warnings.append(f"No v1 official rule bundle is installed for: {', '.join(sorted(unsupported_states))}; confirm every requirement with the relevant DMV.")
    for state in sorted(stale_states):
        verified = _verified_date(available[state])
        warnings.append(f"{state} rules were last verified on {verified.isoformat()} and are older than {available[state].get('refresh_after_days', 90)} days; confirm with the official DMV before acting.")
    if stale_states:
        incomplete = True
    if context.title_state != context.sale_state:
        warnings.append("The title state differs from the sale state; confirm that the title-state assignment is valid and that the sale state can issue the selected transport credential.")
    if context.title_status == TitleStatus.BRANDED:
        warnings.append("A branded title can affect insurability, inspection, financing, value, and future resale even when transfer is legally possible.")
    if context.current_inspection_status in {InspectionResult.CONCERN, InspectionResult.FAIL}:
        incomplete = True
        warnings.append("Current inspection status requires resolution or written state-specific confirmation before road use/registration.")
    elif context.current_inspection_status == InspectionResult.UNKNOWN:
        incomplete = True
        warnings.append("Current inspection status is UNKNOWN and remains an unverified requirement, not a pass.")
    if context.current_emissions_status in {InspectionResult.CONCERN, InspectionResult.FAIL}:
        incomplete = True
        warnings.append("Current emissions status requires diagnosis and state-specific confirmation; a later pass does not identify the original cause by itself.")
    elif context.current_emissions_status == InspectionResult.UNKNOWN:
        incomplete = True
        warnings.append("Current emissions status is UNKNOWN and remains an unverified requirement, not a pass.")

    steps: list[TransactionStep] = []
    order = 10
    steps.append(
        _state_step(
            order=order,
            category="pre_payment",
            title="Clear every ownership and identity gate before payment",
            detail="Inspect the original title, match the seller's ID to the titled owner or documented authority, match VIN in all locations, and verify lien status. Record only match/mismatch—not the raw seller name—in cloud data.",
            bundle=transfer_bundle,
            support="ownership",
            stale=transfer_requires_confirmation,
        )
    )
    order += 10
    steps.append(
        _state_step(
            order=order,
            category="pre_payment",
            title="Complete the independent PPI before committing",
            detail="Keep the engine cold for the initial check, preserve diagnostic reports, and do not treat a history report or clean generic OBD scan as a substitute for the PPI.",
            bundle=transfer_bundle,
            support="buyer_tasks",
            stale=transfer_requires_confirmation,
        )
    )

    if transfer_bundle:
        for task in sorted(transfer_bundle.get("seller_tasks", []), key=lambda item: item.get("order", 0)):
            order += 10
            steps.append(
                _state_step(
                    order=order,
                    category="signing",
                    title=task["id"].replace("-", " ").title(),
                    detail=task["text_en"],
                    bundle=transfer_bundle,
                    source_id=task.get("source_id"),
                    stale=transfer_requires_confirmation,
                )
            )

    order += 10
    insurance_detail = (
        f"Bind coverage to the VIN using the true {context.garaging_state} garaging address and obtain documentation acceptable to the plate/permit issuer. "
        "Insurance plus a bill of sale alone does not authorize an unregistered vehicle to be driven."
    )
    steps.append(
        _state_step(
            order=order,
            category="insurance",
            title="Bind VIN-specific insurance before any road use",
            detail=insurance_detail,
            bundle=registration_bundle,
            support="insurance",
            stale=registration_requires_confirmation,
        )
    )

    order += 10
    if context.transport_option in NON_DRIVING_TRANSPORT:
        transport_detail = "Use the booked tow or carrier. The buyer must not display or use the seller's or another vehicle's plates."
    elif context.transport_option == TransportOption.VALID_TEMP_PERMIT:
        transport_detail = f"Use only the valid temporary/in-transit credential issued for this VIN. For a {context.sale_state} sale, carry the assigned ownership document, permit/registration, and required insurance."
    elif context.transport_option == TransportOption.VALID_REGISTRATION_AND_PLATE:
        transport_detail = "Drive only after the registration and plate are issued for this vehicle and VIN-specific insurance is active."
    elif context.transport_option in ILLEGAL_TRANSPORT:
        transport_detail = "Do not drive with the selected option. Replace it with a tow/carrier or a valid temporary permit/registration issued for this vehicle."
    else:
        transport_detail = f"Before pickup, choose either tow/carrier or a valid {context.sale_state} in-transit/temporary credential that applies to this buyer and destination."
    steps.append(
        _state_step(
            order=order,
            category="transport",
            title="Use a lawful pickup and transport method",
            detail=transport_detail,
            bundle=sale_bundle,
            support="transport",
            deadline=_deadline_text(sale_bundle, "in_transit_validity") if sale_bundle else None,
            stale=sale_requires_confirmation,
        )
    )

    if registration_bundle:
        for task in sorted(registration_bundle.get("buyer_tasks", []), key=lambda item: item.get("order", 0)):
            if "insure" in task["id"] or task.get("phase") in {"before_driving", "at_sale"}:
                continue
            order += 10
            deadline_id = "title_transfer" if context.registration_state == "NJ" else "out_of_state_purchase_registration"
            steps.append(
                _state_step(
                    order=order,
                    category="title_registration",
                    title=task["id"].replace("-", " ").title(),
                    detail=task["text_en"],
                    bundle=registration_bundle,
                    source_id=task.get("source_id"),
                    deadline=_deadline_text(registration_bundle, deadline_id),
                    stale=registration_requires_confirmation,
                )
            )

        forms = [form["id"] for form in registration_bundle.get("forms", [])]
        if context.registration_state == "NJ" and context.title_state == "NJ":
            forms = [form_id for form_id in forms if form_id != "OS-SS-UTA"]
        order += 10
        steps.append(
            _state_step(
                order=order,
                category="title_registration",
                title=f"Prepare {context.registration_state} forms and original documents",
                detail=f"Applicable v1 form set: {', '.join(forms)}. Bring originals and verify each conditional requirement with the official agency.",
                bundle=registration_bundle,
                support="forms",
                stale=registration_requires_confirmation,
            )
        )

        order += 10
        steps.append(
            _state_step(
                order=order,
                category="tax_fee",
                title=f"Pay {context.registration_state} title, registration, and tax charges",
                detail=_registration_fee_summary(registration_bundle),
                bundle=registration_bundle,
                support="sales_tax",
                stale=registration_requires_confirmation,
            )
        )

        order += 10
        inspection_detail = (
            f"Current inspection: {context.current_inspection_status.value}; current emissions: {context.current_emissions_status.value}. "
            "Complete any destination-state inspection, emissions, or VIN-verification requirement. UNKNOWN remains unverified, not passed."
        )
        steps.append(
            _state_step(
                order=order,
                category="inspection_emissions",
                title=f"Complete {context.registration_state} inspection and emissions requirements",
                detail=inspection_detail,
                bundle=registration_bundle,
                support="inspection",
                stale=registration_requires_confirmation,
            )
        )
    else:
        order += 10
        steps.append(
            _state_step(
                order=order,
                category="title_registration",
                title=f"Confirm {context.registration_state} title and registration requirements",
                detail="No maintained v1 rule bundle is installed; contact the official DMV before payment or transport.",
                bundle=None,
                stale=True,
            )
        )

    if definitive_stop:
        decision = Decision.STOP
    elif incomplete:
        decision = Decision.INSPECT
    else:
        decision = Decision.BUY_CANDIDATE

    blocking_payment_gate = any(
        gate.blocked
        for gate in gates
        if gate.code
        in {
            "title_document",
            "branded_title_review",
            "lien_clearance",
            "seller_title_identity",
            "vin_match",
            "bill_of_sale",
            "odometer_disclosure",
            "legal_transport",
            "vin_insurance",
            "residence_garaging_registration",
        }
    )
    can_legally_drive_away = bool(
        context.transport_option in DRIVING_OPTIONS
        and context.insurance_active_for_vin
        and not blocking_payment_gate
        and not stale_states
        and not pending_human_signoff
        and not unsupported_states
    )

    verified_dates = [_verified_date(bundle) for bundle in available.values()]
    return TransactionPlan(
        decision=decision,
        can_legally_drive_away=can_legally_drive_away,
        gates=gates,
        steps=sorted(steps, key=lambda item: item.order),
        warnings=warnings,
        rules_verified_as_of=min(verified_dates) if verified_dates else None,
    )


__all__ = ["build_transaction_plan"]
