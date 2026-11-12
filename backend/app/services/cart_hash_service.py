import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import settings

CANONICAL_SCHEMA_VERSION = "IL-CANON-V1"


def format_utc_iso(dt: datetime | str) -> str:
    """Normalizes a datetime or ISO string to UTC ISO-8601 'YYYY-MM-DDTHH:MM:SSZ'."""
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_canonical_cart_dict(
    merchant_id: str,
    currency: str,
    request_id: str,
    version_number: int,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Constructs and validates the RFC 8785 / JCS canonical dictionary for a CartVersion.
    Sorts items ascending by `sku`, includes integer `unit_price_cents`, `quantity`,
    `line_total_cents`, and `total_amount_cents`.
    """
    canonical_items: list[dict[str, Any]] = []
    total_amount_cents = 0

    sorted_items = sorted(items, key=lambda x: str(x.get("sku", "")))
    for item in sorted_items:
        sku = str(item["sku"])
        unit_price_cents = int(item["unit_price_cents"])
        quantity = int(item["quantity"])
        line_total_cents = int(item.get("line_total_cents", unit_price_cents * quantity))

        if unit_price_cents * quantity != line_total_cents:
            raise ValueError(
                f"Arithmetic invariant violation for {sku}: "
                f"{unit_price_cents} * {quantity} != {line_total_cents}"
            )

        total_amount_cents += line_total_cents
        canonical_items.append(
            {
                "line_total_cents": line_total_cents,
                "quantity": quantity,
                "sku": sku,
                "unit_price_cents": unit_price_cents,
            }
        )

    return {
        "currency": str(currency),
        "items": canonical_items,
        "merchant_id": str(merchant_id),
        "request_id": str(request_id),
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "total_amount_cents": int(total_amount_cents),
        "version_number": int(version_number),
    }


def serialize_canonical_json(payload: dict[str, Any]) -> str:
    """Serializes dictionary to RFC 8785 JCS canonical JSON string."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_intent_hash(canonical_json: str) -> str:
    """Computes lowercase 64-character hex SHA-256 digest of the canonical JSON string."""
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_approval_signature(
    cart_version_id: str,
    intent_hash: str,
    approver_id: str,
    issued_at_iso: str | datetime,
    expires_at_iso: str | datetime,
) -> str:
    """Computes HMAC-SHA256 hex signature over the approval lock fields using INTENTLOCK_SIGNING_SECRET."""
    issued_str = format_utc_iso(issued_at_iso)
    expires_str = format_utc_iso(expires_at_iso)
    signing_input = f"{cart_version_id}|{intent_hash}|{approver_id}|{issued_str}|{expires_str}"
    return hmac.new(
        settings.INTENTLOCK_SIGNING_SECRET.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_cart_integrity(
    cart_version: Any,
    line_items: list[Any],
    approval_lock: Optional[Any] = None,
) -> tuple[bool, list[str]]:
    """
    Recomputes canonical JSON and SHA-256 intent_hash from DB line items,
    checking against cart_version.intent_hash and approval_lock.intent_hash + approval_signature.
    Returns (is_valid, list_of_discrepancy_errors).
    """
    errors: list[str] = []

    raw_items: list[dict[str, Any]] = []
    for li in line_items:
        if isinstance(li, dict):
            raw_items.append(
                {
                    "sku": li["sku"],
                    "unit_price_cents": int(li["unit_price_cents"]),
                    "quantity": int(li["quantity"]),
                    "line_total_cents": int(li["line_total_cents"]),
                }
            )
        else:
            raw_items.append(
                {
                    "sku": li.sku,
                    "unit_price_cents": int(li.unit_price_cents),
                    "quantity": int(li.quantity),
                    "line_total_cents": int(li.line_total_cents),
                }
            )

    try:
        canonical_dict = build_canonical_cart_dict(
            merchant_id=cart_version.merchant_id,
            currency=cart_version.currency,
            request_id=cart_version.request_id,
            version_number=cart_version.version_number,
            items=raw_items,
        )
        recomputed_json = serialize_canonical_json(canonical_dict)
        recomputed_hash = compute_intent_hash(recomputed_json)
    except Exception as exc:
        errors.append(f"Canonical hash computation failed: {exc}")
        return False, errors

    if int(canonical_dict["total_amount_cents"]) != int(cart_version.total_amount_cents):
        errors.append(
            f"Cart total drift detected: sum of line items is {canonical_dict['total_amount_cents']} cents "
            f"but cart_version.total_amount_cents is {cart_version.total_amount_cents} cents."
        )

    if recomputed_hash != cart_version.intent_hash:
        errors.append(
            f"Cart intent_hash mismatch: recomputed SHA-256 '{recomputed_hash}' != "
            f"stored cart_version.intent_hash '{cart_version.intent_hash}'."
        )

    if approval_lock is not None:
        if approval_lock.intent_hash != recomputed_hash:
            errors.append(
                f"Approval lock intent_hash drift: approval_lock.intent_hash '{approval_lock.intent_hash}' != "
                f"live recomputed hash '{recomputed_hash}'."
            )

        expected_sig = compute_approval_signature(
            cart_version_id=approval_lock.cart_version_id,
            intent_hash=approval_lock.intent_hash,
            approver_id=approval_lock.approver_id,
            issued_at_iso=format_utc_iso(approval_lock.issued_at),
            expires_at_iso=format_utc_iso(approval_lock.expires_at),
        )
        if not hmac.compare_digest(expected_sig, approval_lock.approval_signature):
            errors.append(
                "Approval lock HMAC-SHA256 signature verification failed: lock metadata or expiry was tampered."
            )

    return len(errors) == 0, errors
