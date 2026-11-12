"""
IntentLock Core Controls (`app.intentlock_core.controls`)
Standalone, framework-agnostic implementation of IntentLock's cryptographic
and policy controls (P1 Reusable Control Library).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import settings
from app.services import cart_hash_service, guardrails


def canonicalize_cart(
    merchant_id: str,
    currency: str,
    request_id: str,
    version_number: int,
    items: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """
    Produces RFC 8785 / JCS canonical dictionary and canonical JSON string
    with items deterministically sorted by `sku` and integer-cent totals.
    """
    canonical_dict = cart_hash_service.build_canonical_cart_dict(
        merchant_id=merchant_id,
        currency=currency,
        request_id=request_id,
        version_number=version_number,
        items=items,
    )
    canonical_json = cart_hash_service.serialize_canonical_json(canonical_dict)
    return canonical_dict, canonical_json


def compute_intent_hash(canonical_json: str) -> str:
    """Computes lowercase 64-char hex SHA-256 `intent_hash` over canonical JSON."""
    return cart_hash_service.compute_intent_hash(canonical_json)


def mint_approval_lock(
    cart_version_id: str,
    intent_hash: str,
    coordinator_id: str,
    approver_id: str,
    approver_role: str,
    ttl_seconds: int = 1800,
    issued_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Enforces Separation of Duties (`G-04`) and mints an HMAC-SHA256 signed
    approval lock dictionary with UTC `issued_at` and `expires_at`.
    """
    guardrails.enforce_separation_of_duties(
        coordinator_id=coordinator_id,
        approver_user_id=approver_id,
        approver_role=approver_role,
    )
    now_utc = issued_at or datetime.now(timezone.utc)
    expires_utc = now_utc + timedelta(seconds=max(1, int(ttl_seconds)))
    issued_iso = cart_hash_service.format_utc_iso(now_utc)
    expires_iso = cart_hash_service.format_utc_iso(expires_utc)
    signature = cart_hash_service.compute_approval_signature(
        cart_version_id=cart_version_id,
        intent_hash=intent_hash,
        approver_id=approver_id,
        issued_at_iso=issued_iso,
        expires_at_iso=expires_iso,
    )
    return {
        "cart_version_id": cart_version_id,
        "intent_hash": intent_hash,
        "approver_id": approver_id,
        "issued_at": issued_iso,
        "expires_at": expires_iso,
        "approval_signature": signature,
    }


def verify_checkout_gate(
    cart_version_id: str,
    merchant_id: str,
    currency: str,
    request_id: str,
    version_number: int,
    items: list[dict[str, Any]],
    approval_lock: dict[str, Any],
    now_utc: Optional[datetime] = None,
) -> tuple[bool, list[str]]:
    """
    Verifies RFC 8785 SHA-256 `intent_hash`, HMAC-SHA256 `approval_signature`,
    UTC TTL expiration (`G-06`), and P0 scope constraints (`G-07`).
    """
    errors: list[str] = []
    canonical_dict, canonical_json = canonicalize_cart(
        merchant_id=merchant_id,
        currency=currency,
        request_id=request_id,
        version_number=version_number,
        items=items,
    )
    recomputed_hash = compute_intent_hash(canonical_json)
    locked_hash = str(approval_lock.get("intent_hash", ""))
    if recomputed_hash != locked_hash:
        errors.append(
            f"G-05 Drift: recomputed intent_hash '{recomputed_hash}' != locked '{locked_hash}'."
        )

    expected_sig = cart_hash_service.compute_approval_signature(
        cart_version_id=cart_version_id,
        intent_hash=locked_hash,
        approver_id=str(approval_lock.get("approver_id", "")),
        issued_at_iso=str(approval_lock.get("issued_at", "")),
        expires_at_iso=str(approval_lock.get("expires_at", "")),
    )
    if expected_sig != str(approval_lock.get("approval_signature", "")):
        errors.append("G-05 Signature Mismatch: HMAC-SHA256 approval_signature is invalid.")

    check_time = now_utc or datetime.now(timezone.utc)
    expires_str = str(approval_lock.get("expires_at", ""))
    if expires_str:
        expires_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        if check_time >= expires_dt:
            errors.append(f"G-06 Expired: lock expired at {expires_str}.")

    try:
        guardrails.enforce_p0_payment_scope(
            merchant_id=merchant_id,
            currency=currency,
            total_cents=int(canonical_dict["total_amount_cents"]),
            purchase_units_count=1,
            intent="CAPTURE",
        )
    except guardrails.GuardrailViolationError as exc:
        errors.append(exc.message)

    return len(errors) == 0, errors


def verify_reconciliation_invariants(
    approved_intent_hash: str,
    approved_amount_cents: int,
    paypal_order_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Standalone 6-invariant PayPal Orders v2 cryptographic reconciliation verifier.
    """
    order_status = str(paypal_order_payload.get("status", "")).upper()
    purchase_units = paypal_order_payload.get("purchase_units") or []
    check_single_pu = len(purchase_units) == 1
    pu0 = purchase_units[0] if purchase_units else {}
    custom_id = str(pu0.get("custom_id", ""))
    pu_amount = pu0.get("amount") or {}
    captures = ((pu0.get("payments") or {}).get("captures")) or []
    cap0 = captures[0] if captures else {}
    cap_status = str(cap0.get("status", "")).upper()
    cap_amount = cap0.get("amount") or pu_amount

    currency_code = str(cap_amount.get("currency_code") or pu_amount.get("currency_code") or "").upper()
    val_str = str(cap_amount.get("value") or pu_amount.get("value") or "0.00")
    try:
        captured_cents = int(round(float(val_str) * 100))
    except ValueError:
        captured_cents = -1

    checks = {
        "check_order_completed": order_status == "COMPLETED",
        "check_capture_completed": cap_status == "COMPLETED",
        "check_currency_usd": currency_code == "USD",
        "check_amount_exact": captured_cents == int(approved_amount_cents),
        "check_intent_hash_match": custom_id == approved_intent_hash,
        "check_single_purchase_unit": check_single_pu,
    }
    all_passed = all(checks.values())
    return {
        "verdict": "VERIFIED_MATCH" if all_passed else "MISMATCH_BLOCKED",
        "all_passed": all_passed,
        "checks": checks,
        "approved_intent_hash": approved_intent_hash,
        "paypal_custom_id_hash": custom_id,
        "approved_amount_cents": int(approved_amount_cents),
        "captured_amount_cents": captured_cents,
    }


def enforce_catalog_grounding(
    proposed_items: list[dict[str, Any]],
    catalog_map: dict[str, Any],
    budget_limit_cents: Optional[int] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Delegates to Guardrail G-01 & G-02 catalog grounding and integer-cent binding."""
    return guardrails.enforce_catalog_grounding_and_pricing(
        proposed_items=proposed_items,
        catalog_map=catalog_map,
        budget_limit_cents=budget_limit_cents,
    )


def scrub_prompt_injection(raw_text: str) -> tuple[str, list[str]]:
    """Delegates to Guardrail G-03 & PII redaction scrubber."""
    return guardrails.sanitize_and_check_prompt_injection(raw_text)
