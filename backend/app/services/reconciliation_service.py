import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ApprovalLock,
    CartVersion,
    PayPalOrderRecord,
    Product,
    PurchaseRequest,
    ReconciliationRecord,
    User,
)
from .audit_service import record_audit_event
from .cart_hash_service import (
    build_canonical_cart_dict,
    compute_intent_hash,
    format_utc_iso,
    serialize_canonical_json,
)
from .paypal_mcp_service import cents_to_usd_str, usd_str_to_cents


def reconcile_order(
    db: Session,
    cart_version: CartVersion,
    approval_lock: ApprovalLock,
    paypal_record: PayPalOrderRecord,
    paypal_order_payload: dict[str, Any],
    actor: User,
) -> ReconciliationRecord:
    """
    Evaluates the 6 cryptographic & financial invariants comparing the authoritative
    PayPal Sandbox Order payload against the locked `CartVersion` and `ApprovalLock`:
      1. `check_order_completed`: `paypal_order_payload.get("status") == "COMPLETED"`
      2. `check_capture_completed`: `captures[0].get("status") == "COMPLETED"`
      3. `check_currency_usd`: `pu_amount.get("currency_code") == "USD"` and `capture_amount.get("currency_code") == "USD"`
      4. `check_amount_exact`: `usd_str_to_cents(capture_amount.get("value")) == cart_version.total_amount_cents`
      5. `check_intent_hash_match`: `pu.get("custom_id") == approval_lock.intent_hash == cart_version.intent_hash`
      6. `check_single_purchase_unit`: `len(paypal_order_payload.get("purchase_units", [])) == 1`

    Produces a `ReconciliationRecord` with a sealed Cryptographic Evidence Bundle (`evidence_bundle_json`
    + `evidence_bundle_sha256`), transitions `CartVersion` and `PurchaseRequest` statuses, decrements
    product stock atomically on `VERIFIED_MATCH`, and emits the corresponding hash-chained `AuditEvent`.
    """
    purchase_request = (
        db.query(PurchaseRequest)
        .filter(PurchaseRequest.id == cart_version.request_id)
        .first()
    )

    discrepancies: list[str] = []

    order_status = str(paypal_order_payload.get("status", "UNKNOWN")).upper()
    purchase_units = paypal_order_payload.get("purchase_units") or []

    # 6. check_single_purchase_unit
    check_single_purchase_unit = isinstance(purchase_units, list) and len(purchase_units) == 1
    if not check_single_purchase_unit:
        discrepancies.append(
            f"Invariant #6 failed (check_single_purchase_unit): expected 1 purchase_unit, found {len(purchase_units)}."
        )

    pu: dict[str, Any] = purchase_units[0] if purchase_units else {}
    pu_amount: dict[str, Any] = pu.get("amount") or {}
    pu_custom_id = str(pu.get("custom_id") or "")

    captures: list[dict[str, Any]] = (pu.get("payments") or {}).get("captures") or []
    first_capture: dict[str, Any] = captures[0] if captures else {}
    capture_status = str(first_capture.get("status", "NONE")).upper()
    capture_amount: dict[str, Any] = first_capture.get("amount") or pu_amount or {}

    # 1. check_order_completed
    check_order_completed = order_status == "COMPLETED"
    if not check_order_completed:
        discrepancies.append(
            f"Invariant #1 failed (check_order_completed): PayPal order status is '{order_status}', expected 'COMPLETED'."
        )

    # 2. check_capture_completed
    check_capture_completed = bool(captures) and capture_status == "COMPLETED"
    if not check_capture_completed:
        discrepancies.append(
            f"Invariant #2 failed (check_capture_completed): PayPal capture status is '{capture_status}', expected 'COMPLETED'."
        )

    # 3. check_currency_usd
    pu_currency = str(pu_amount.get("currency_code", "")).upper()
    cap_currency = str(capture_amount.get("currency_code", "")).upper()
    check_currency_usd = (
        pu_currency == "USD"
        and cap_currency == "USD"
        and str(cart_version.currency).upper() == "USD"
    )
    if not check_currency_usd:
        discrepancies.append(
            f"Invariant #3 failed (check_currency_usd): purchase_unit currency='{pu_currency}', "
            f"capture currency='{cap_currency}', expected 'USD'."
        )

    # 4. check_amount_exact
    try:
        captured_amount_cents = usd_str_to_cents(capture_amount.get("value", "0.00"))
    except ValueError:
        captured_amount_cents = -1

    try:
        pu_amount_cents = usd_str_to_cents(pu_amount.get("value", "0.00"))
    except ValueError:
        pu_amount_cents = -1

    approved_amount_cents = int(cart_version.total_amount_cents)
    check_amount_exact = (
        captured_amount_cents == approved_amount_cents
        and pu_amount_cents == approved_amount_cents
    )
    if not check_amount_exact:
        discrepancies.append(
            f"Invariant #4 failed (check_amount_exact): captured_amount_cents={captured_amount_cents} "
            f"(purchase_unit={pu_amount_cents}) != approved CartVersion.total_amount_cents={approved_amount_cents}."
        )

    # 5. check_intent_hash_match (also re-verify live canonical hash from CartLineItem rows)
    raw_items = [
        {
            "sku": li.sku,
            "unit_price_cents": int(li.unit_price_cents),
            "quantity": int(li.quantity),
            "line_total_cents": int(li.line_total_cents),
        }
        for li in cart_version.line_items
    ]
    try:
        canonical_dict = build_canonical_cart_dict(
            merchant_id=cart_version.merchant_id,
            currency=cart_version.currency,
            request_id=cart_version.request_id,
            version_number=cart_version.version_number,
            items=raw_items,
        )
        live_canonical_json = serialize_canonical_json(canonical_dict)
        live_intent_hash = compute_intent_hash(live_canonical_json)
    except Exception as exc:
        canonical_dict = {}
        live_intent_hash = "INVALID_CANONICAL_CART"
        discrepancies.append(f"Canonical cart recomputation failed during reconciliation: {exc}")

    check_intent_hash_match = (
        bool(pu_custom_id)
        and hmac.compare_digest(pu_custom_id, approval_lock.intent_hash)
        and hmac.compare_digest(approval_lock.intent_hash, cart_version.intent_hash)
        and hmac.compare_digest(cart_version.intent_hash, live_intent_hash)
    )
    if not check_intent_hash_match:
        discrepancies.append(
            f"Invariant #5 failed (check_intent_hash_match): PayPal custom_id='{pu_custom_id}', "
            f"approval_lock.intent_hash='{approval_lock.intent_hash}', "
            f"cart_version.intent_hash='{cart_version.intent_hash}', "
            f"live_recomputed_hash='{live_intent_hash}'."
        )

    # Determine Verdict & State Transitions
    all_six_passed = (
        check_order_completed
        and check_capture_completed
        and check_currency_usd
        and check_amount_exact
        and check_intent_hash_match
        and check_single_purchase_unit
    )

    non_status_failure = not (
        check_currency_usd
        and check_amount_exact
        and check_intent_hash_match
        and check_single_purchase_unit
    )

    already_captured_before = cart_version.status == "CAPTURED_VERIFIED"

    if all_six_passed:
        verdict = "VERIFIED_MATCH"
        cart_version.status = "CAPTURED_VERIFIED"
        if purchase_request:
            purchase_request.status = "CAPTURED_VERIFIED"
        paypal_record.paypal_status = "COMPLETED"
        if first_capture.get("id"):
            paypal_record.paypal_capture_id = str(first_capture["id"])

        # Decrement product stock_available atomically if not already decremented
        if not already_captured_before:
            for li in cart_version.line_items:
                prod = db.query(Product).filter(Product.sku == li.sku).first()
                if prod is not None:
                    prod.stock_available = max(0, int(prod.stock_available) - int(li.quantity))
    elif (
        not non_status_failure
        and (
            order_status in ("PENDING", "CREATED", "APPROVED")
            or capture_status == "PENDING"
            or not captures
        )
    ):
        verdict = "UNCERTAIN_PENDING"
        cart_version.status = "UNCERTAIN_NEEDS_SYNC"
        if purchase_request:
            purchase_request.status = "UNCERTAIN_NEEDS_SYNC"
        paypal_record.paypal_status = capture_status if captures else order_status
    else:
        verdict = "MISMATCH_BLOCKED"
        cart_version.status = "RECONCILIATION_MISMATCH"
        if purchase_request:
            purchase_request.status = "RECONCILIATION_MISMATCH"
        paypal_record.paypal_status = "MISMATCH"

    now = datetime.now(timezone.utc)
    rec_id = f"REC-{uuid.uuid4().hex[:10].upper()}"
    evid_id = f"EVID-{uuid.uuid4().hex[:10].upper()}"

    mcp_trace: dict[str, Any] = paypal_order_payload.get("_mcp_trace") or {}
    if not mcp_trace and paypal_record.raw_create_response_json:
        try:
            create_obj = json.loads(paypal_record.raw_create_response_json)
            mcp_trace = create_obj.get("_mcp_trace") or {}
        except Exception:
            mcp_trace = {}

    evidence_bundle: dict[str, Any] = {
        "evidence_bundle_id": evid_id,
        "reconciliation_id": rec_id,
        "request_id": cart_version.request_id,
        "request_title": purchase_request.title if purchase_request else "",
        "cart_version_id": cart_version.id,
        "version_number": cart_version.version_number,
        "merchant_id": cart_version.merchant_id,
        "merchant_name": settings.MERCHANT_NAME,
        "currency": cart_version.currency,
        "coordinator_id": purchase_request.coordinator_id if purchase_request else cart_version.created_by_id,
        "approver_id": approval_lock.approver_id,
        "buyer_id": actor.id,
        "approved_intent_hash": approval_lock.intent_hash,
        "cart_intent_hash": cart_version.intent_hash,
        "live_recomputed_intent_hash": live_intent_hash,
        "approval_lock_id": approval_lock.id,
        "approval_signature": approval_lock.approval_signature,
        "approval_issued_at_utc": format_utc_iso(approval_lock.issued_at),
        "approval_expires_at_utc": format_utc_iso(approval_lock.expires_at),
        "paypal_order_id": paypal_record.paypal_order_id,
        "paypal_capture_id": paypal_record.paypal_capture_id or first_capture.get("id"),
        "paypal_custom_id_echoed": pu_custom_id,
        "invoice_id": paypal_record.invoice_id,
        "execution_mode": paypal_record.execution_mode,
        "approved_amount_cents": approved_amount_cents,
        "approved_amount_usd": cents_to_usd_str(approved_amount_cents),
        "captured_amount_cents": max(0, captured_amount_cents),
        "captured_amount_usd": cents_to_usd_str(max(0, captured_amount_cents)),
        "verdict": verdict,
        "checks": {
            "check_order_completed": check_order_completed,
            "check_capture_completed": check_capture_completed,
            "check_currency_usd": check_currency_usd,
            "check_amount_exact": check_amount_exact,
            "check_intent_hash_match": check_intent_hash_match,
            "check_single_purchase_unit": check_single_purchase_unit,
        },
        "discrepancies": discrepancies,
        "line_items": [
            {
                "sku": li.sku,
                "product_name": li.product_name,
                "pack_size_desc": li.pack_size_desc,
                "unit_price_cents": li.unit_price_cents,
                "unit_price_usd": cents_to_usd_str(li.unit_price_cents),
                "quantity": li.quantity,
                "line_total_cents": li.line_total_cents,
                "line_total_usd": cents_to_usd_str(li.line_total_cents),
                "selection_rationale": li.selection_rationale,
                "headcount_math": li.headcount_math,
            }
            for li in cart_version.line_items
        ],
        "canonical_cart": canonical_dict,
        "mcp_tool_trace": mcp_trace,
        "sealed_at_utc": format_utc_iso(now),
    }

    evidence_bundle_json = serialize_canonical_json(evidence_bundle)
    evidence_bundle_sha256 = hashlib.sha256(evidence_bundle_json.encode("utf-8")).hexdigest()

    rec_record = ReconciliationRecord(
        id=rec_id,
        request_id=cart_version.request_id,
        cart_version_id=cart_version.id,
        paypal_order_id=paypal_record.paypal_order_id,
        verdict=verdict,
        check_order_completed=check_order_completed,
        check_capture_completed=check_capture_completed,
        check_currency_usd=check_currency_usd,
        check_amount_exact=check_amount_exact,
        check_intent_hash_match=check_intent_hash_match,
        check_single_purchase_unit=check_single_purchase_unit,
        approved_amount_cents=approved_amount_cents,
        captured_amount_cents=max(0, captured_amount_cents),
        approved_intent_hash=approval_lock.intent_hash,
        paypal_custom_id_hash=pu_custom_id,
        discrepancy_details_json=json.dumps(discrepancies),
        evidence_bundle_sha256=evidence_bundle_sha256,
        evidence_bundle_json=evidence_bundle_json,
        checked_at=now,
    )
    db.add(rec_record)
    db.flush()

    if verdict == "VERIFIED_MATCH":
        event_type = "ORDER_RECONCILED_VERIFIED"
        summary = (
            f"Automated 6-Invariant Reconciliation VERIFIED PayPal Order {paypal_record.paypal_order_id} "
            f"(${cents_to_usd_str(approved_amount_cents)} USD). Sealed Evidence Bundle {evid_id}."
        )
    elif verdict == "UNCERTAIN_PENDING":
        event_type = "ORDER_RECONCILIATION_UNCERTAIN"
        summary = (
            f"PayPal Order {paypal_record.paypal_order_id} is in {order_status}/{capture_status} state; "
            f"transitioned to UNCERTAIN_NEEDS_SYNC awaiting authoritative sync."
        )
    else:
        event_type = "ORDER_RECONCILIATION_MISMATCH"
        summary = (
            f"SECURITY HALT: Reconciliation detected invariant mismatch on PayPal Order "
            f"{paypal_record.paypal_order_id}: {'; '.join(discrepancies)}"
        )

    record_audit_event(
        db=db,
        actor_id=actor.id,
        actor_role=actor.role,
        event_type=event_type,
        summary=summary,
        request_id=cart_version.request_id,
        cart_version_id=cart_version.id,
        metadata={
            "reconciliation_id": rec_id,
            "paypal_order_id": paypal_record.paypal_order_id,
            "paypal_capture_id": paypal_record.paypal_capture_id,
            "verdict": verdict,
            "approved_amount_cents": approved_amount_cents,
            "captured_amount_cents": captured_amount_cents,
            "approved_intent_hash": approval_lock.intent_hash,
            "paypal_custom_id_hash": pu_custom_id,
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "discrepancies": discrepancies,
        },
    )

    return rec_record
