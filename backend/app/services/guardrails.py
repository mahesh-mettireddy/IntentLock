import re
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ApprovalLock, CartLineItem, CartVersion, Product
from .cart_hash_service import verify_cart_integrity


class GuardrailViolationError(Exception):
    """
    Deterministic Security & Financial Scope Guardrail Violation (G-01 through G-08).
    """

    def __init__(
        self,
        code: str,
        message: str,
        guardrail_id: str,
        metadata: Optional[dict[str, Any]] = None,
        http_status: int = 403,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.guardrail_id = guardrail_id
        self.metadata = metadata or {}
        self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "guardrail_id": self.guardrail_id,
            "http_status": self.http_status,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Layer 1: Pre-LLM PII Scrubber & Prompt Injection / Privilege Guardrail (G-03)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?:\+\d{1,2}\s?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
_PAN_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_BEARER_TOKEN_RE = re.compile(
    r"(?:sk-[a-zA-Z0-9_-]{16,}|AIza[0-9A-Za-z\-_]{20,}|gsk_[a-zA-Z0-9]{16,}|xai-[a-zA-Z0-9_-]{16,}|Bearer\s+[a-zA-Z0-9\-._~+/]+=*)"
)

_ADVERSARIAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions", re.IGNORECASE),
        "Attempted system instruction override ('ignore previous instructions')",
    ),
    (
        re.compile(r"system\s+override|developer\s+mode|jailbreak", re.IGNORECASE),
        "Attempted privilege escalation header ('SYSTEM OVERRIDE')",
    ),
    (
        re.compile(
            r"(?:set|change|override|force|discount|make)\s+(?:the\s+)?(?:unit\s+|catalog\s+|item\s+)?price\s+(?:of\s+[A-Za-z0-9\-]+\s+)?to\s+\$?\d+(?:\.\d+)?",
            re.IGNORECASE,
        ),
        "Attempted unit price manipulation directive",
    ),
    (
        re.compile(r"price\s*(?:=|:)\s*\$?0(?:\.01|\.00)?", re.IGNORECASE),
        "Attempted zero/penny price injection",
    ),
    (
        re.compile(
            r"auto[- ]?approve|override\s+approval|bypass\s+approv(?:al|er)|mark\s+(?:cart\s+)?(?:status\s+)?(?:as\s+)?approved|skip\s+manager",
            re.IGNORECASE,
        ),
        "Attempted Separation-of-Duties / self-approval bypass",
    ),
    (
        re.compile(
            r"mark\s+payment\s+completed|bypass\s+paypal|fake\s+paypal|capture[\s_-]*id\s*[:=]?\s*CAP-|set\s+status\s+to\s+captured",
            re.IGNORECASE,
        ),
        "Attempted payment fabrication or PayPal Sandbox bypass",
    ),
    (
        re.compile(
            r"\b(?:currency|pay\s+in|settle\s+in|switch\s+to)\s+(?:EUR|GBP|JPY|CAD|AUD|BTC|ETH|CHF|CNY|INR)\b|\bcurrency\s+EUR\b",
            re.IGNORECASE,
        ),
        "Attempted non-USD currency override (IntentLock enforces USD-only P0 policy)",
    ),
]


def sanitize_and_check_prompt_injection(raw_text: str) -> tuple[str, list[str]]:
    """
    1. Scrubs sensitive PII (emails, phone numbers, credit card PANs, SSNs, bearer tokens)
       before sending any text to external LLM APIs (`12-PRIVACY-COMPLIANCE.md`).
    2. Scans for adversarial prompt injection patterns (`G-03`: price overrides, auto-approval,
       payment fabrication, or currency manipulation).
    3. Strips adversarial override clauses non-destructively so legitimate product needs in the
       same sentence can still be proposed under strict DB catalog pricing (`G-01`), while
       returning explicit `[G-03 BLOCKED: ...]` guardrail warnings for the UI and audit ledger.
    """
    if not raw_text:
        return "", []

    sanitized = raw_text
    warnings: list[str] = []

    # 1. PII Redaction Pipeline
    if _BEARER_TOKEN_RE.search(sanitized):
        sanitized = _BEARER_TOKEN_RE.sub("[REDACTED_TOKEN]", sanitized)
        warnings.append(
            "[PII SCRUBBER: Bearer/API credential redacted before external LLM transmission]"
        )

    if _PAN_RE.search(sanitized):
        sanitized = _PAN_RE.sub("[REDACTED_PAN]", sanitized)
        warnings.append(
            "[PII SCRUBBER: Payment card PAN sequence redacted (Zero-PAN Compliance PCI-04)]"
        )

    if _SSN_RE.search(sanitized):
        sanitized = _SSN_RE.sub("[REDACTED_SSN]", sanitized)
        warnings.append(
            "[PII SCRUBBER: SSN pattern redacted before external LLM transmission]"
        )

    if _EMAIL_RE.search(sanitized):
        sanitized = _EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)
        warnings.append(
            "[PII SCRUBBER: Email address redacted before external LLM transmission]"
        )

    if _PHONE_RE.search(sanitized):
        sanitized = _PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
        warnings.append(
            "[PII SCRUBBER: Phone number redacted before external LLM transmission]"
        )

    # 2. Prompt Injection & Privilege Boundary Detection (G-03)
    detected_reasons: list[str] = []
    for pattern, description in _ADVERSARIAL_PATTERNS:
        if pattern.search(sanitized):
            detected_reasons.append(description)
            sanitized = pattern.sub("[STRIPPED_BY_G03]", sanitized)

    if detected_reasons:
        unique_reasons = "; ".join(dict.fromkeys(detected_reasons))
        warnings.append(
            "[G-03 BLOCKED: Attempted privilege/price override stripped — Agent has zero price or approval authority "
            f"({unique_reasons})]"
        )

    return sanitized.strip(), warnings


# Convenience wrapper for defense-in-depth LLM prompt PII & injection scrubbing (SEC-GAP-02)
def sanitize_prompt_for_llm(raw_text: str) -> str:
    """
    Scrubs emails, phone numbers, credit card PANs, SSNs, bearer tokens, and G-03
    override directives from `raw_text` and returns the clean string.
    """
    return sanitize_and_check_prompt_injection(raw_text)[0]


# ---------------------------------------------------------------------------
# Layer 2: Catalog Grounding (`G-01`) & Inventory Quantity Bounds (`G-02`)
# ---------------------------------------------------------------------------


def enforce_catalog_grounding_and_pricing(
    proposed_items: list[dict[str, Any]],
    catalog_map: dict[str, Product],
    budget_limit_cents: Optional[int] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Enforces Guardrails G-01 and G-02:
    - G-01 (Catalog Grounding & Price Integrity):
      Rejects any SKU not in `catalog_map` (or inactive).
      Ignores any price or total suggested by the LLM and binds authoritative
      `unit_price_cents = product.unit_price_cents` and
      `line_total_cents = unit_price_cents * quantity` in exact integer cents.
      Consolidates duplicate SKUs deterministically.
    - G-02 (Inventory & Quantity Bounds):
      Ensures `quantity >= 1`. If `quantity > product.stock_available`, caps
      `quantity = product.stock_available` (or drops if 0 stock) and appends a
      transparent warning explaining the stock cap.
    """
    warnings: list[str] = []
    consolidated: dict[str, dict[str, Any]] = {}

    for raw_item in proposed_items or []:
        sku = str(raw_item.get("sku", "")).strip().upper()
        if not sku:
            continue

        # G-01: Must exist in authoritative SQLite catalog
        product = catalog_map.get(sku)
        if product is None or not getattr(product, "is_active", True):
            warnings.append(
                f"[G-01 BLOCKED: Hallucinated or out-of-catalog SKU '{sku}' rejected — "
                f"only Acme Workspace Supplies SKU-001..SKU-015 are permitted]"
            )
            continue

        # Detect if caller/LLM attempted to inject an unauthorized unit price
        llm_suggested_price = raw_item.get("unit_price_cents") or raw_item.get("price_cents")
        if (
            llm_suggested_price is not None
            and int(llm_suggested_price) != int(product.unit_price_cents)
        ):
            warnings.append(
                f"[G-01 ENFORCED: Ignored non-authoritative price ({llm_suggested_price} cents) for {sku}; "
                f"bound authoritative SQLite catalog price {product.unit_price_cents} cents (${product.unit_price_cents / 100:.2f})]"
            )

        try:
            raw_qty = int(raw_item.get("quantity", 1))
        except (TypeError, ValueError):
            raw_qty = 1

        if raw_qty < 1:
            warnings.append(
                f"[G-02 BLOCKED: Invalid non-positive quantity ({raw_qty}) for {sku} ({product.name}) rejected]"
            )
            continue

        rationale = str(
            raw_item.get("selection_rationale")
            or raw_item.get("item_rationale")
            or f"Selected from Acme Workspace Supplies catalog ({product.category})."
        ).strip()
        headcount_math = str(
            raw_item.get("headcount_math")
            or raw_item.get("headcount_or_pack_math")
            or f"{raw_qty} x {product.pack_size_desc}"
        ).strip()

        if sku in consolidated:
            consolidated[sku]["quantity"] += raw_qty
            if rationale and rationale not in consolidated[sku]["selection_rationale"]:
                consolidated[sku]["selection_rationale"] += f" | {rationale}"
        else:
            consolidated[sku] = {
                "sku": sku,
                "quantity": raw_qty,
                "selection_rationale": rationale,
                "headcount_math": headcount_math,
            }

    validated_items: list[dict[str, Any]] = []
    running_total_cents = 0

    for sku in sorted(consolidated.keys()):
        entry = consolidated[sku]
        product = catalog_map[sku]
        requested_qty = int(entry["quantity"])
        stock_avail = int(product.stock_available)

        # G-02: Inventory & Quantity Bound Check
        if stock_avail <= 0:
            warnings.append(
                f"[G-02 STOCK CAP: {sku} ({product.name}) has 0 units available in stock and was excluded from the cart]"
            )
            continue

        if requested_qty > stock_avail:
            warnings.append(
                f"[G-02 STOCK CAP: Requested {requested_qty} units of {sku} ({product.name}), "
                f"but only {stock_avail} units are available in warehouse stock. Quantity automatically capped at {stock_avail}]"
            )
            final_qty = stock_avail
            entry["headcount_math"] = (
                f"{entry['headcount_math']} (Capped from {requested_qty} to {stock_avail} max stock by Guardrail G-02)"
            )
        else:
            final_qty = requested_qty

        # G-01: Deterministic integer cent arithmetic from SQLite product record
        unit_price_cents = int(product.unit_price_cents)
        line_total_cents = unit_price_cents * final_qty
        running_total_cents += line_total_cents

        validated_items.append(
            {
                "sku": sku,
                "product_name": product.name,
                "pack_size_desc": product.pack_size_desc,
                "unit_price_cents": unit_price_cents,
                "quantity": final_qty,
                "line_total_cents": line_total_cents,
                "selection_rationale": entry["selection_rationale"],
                "headcount_math": entry["headcount_math"],
            }
        )

    if budget_limit_cents is not None and budget_limit_cents > 0 and running_total_cents > budget_limit_cents:
        over_cents = running_total_cents - budget_limit_cents
        warnings.append(
            f"[BUDGET WARNING: Proposed cart total ${running_total_cents / 100:.2f} exceeds stated budget ceiling "
            f"${budget_limit_cents / 100:.2f} by ${over_cents / 100:.2f}]"
        )

    if running_total_cents > settings.MAX_ORDER_CENTS:
        warnings.append(
            f"[G-07 SCOPE WARNING: Proposed cart total ${running_total_cents / 100:.2f} exceeds P0 single-order cap "
            f"of ${settings.MAX_ORDER_CENTS / 100:.2f}]"
        )

    return validated_items, warnings


# ---------------------------------------------------------------------------
# Layer 3: RBAC Separation of Duties (`G-04`), Intent Lock (`G-05`) & Expiry (`G-06`)
# ---------------------------------------------------------------------------


def enforce_separation_of_duties(
    coordinator_id: str,
    approver_user_id: str,
    approver_role: str,
) -> None:
    """
    Guardrail G-04: Separation of Duties (RBAC).
    Raises `GuardrailViolationError("SOD_SELF_APPROVAL_FORBIDDEN", ..., "G-04")`
    if `coordinator_id == approver_user_id` or `approver_role != "APPROVER"`.
    """
    normalized_role = (approver_role or "").strip().upper()
    if normalized_role != "APPROVER":
        raise GuardrailViolationError(
            code="SOD_SELF_APPROVAL_FORBIDDEN",
            message=(
                f"Guardrail G-04 Violation: Persona '{approver_user_id}' has role '{approver_role}', "
                "which is forbidden from approving carts. Only an authenticated APPROVER may sign an ApprovalLock."
            ),
            guardrail_id="G-04",
            metadata={
                "coordinator_id": coordinator_id,
                "approver_user_id": approver_user_id,
                "approver_role": approver_role,
            },
            http_status=403,
        )

    if coordinator_id.strip() == approver_user_id.strip():
        raise GuardrailViolationError(
            code="SOD_SELF_APPROVAL_FORBIDDEN",
            message=(
                f"Guardrail G-04 Violation: Separation of Duties forbids Coordinator '{coordinator_id}' "
                "from approving their own purchase request."
            ),
            guardrail_id="G-04",
            metadata={
                "coordinator_id": coordinator_id,
                "approver_user_id": approver_user_id,
                "approver_role": approver_role,
            },
            http_status=403,
        )


def enforce_intent_lock_integrity(
    cart_version: CartVersion,
    line_items: list[CartLineItem] | list[dict[str, Any]],
    approval_lock: Optional[ApprovalLock] = None,
    expected_intent_hash: Optional[str] = None,
) -> None:
    """
    Guardrail G-05: Cryptographic Intent Lock (TOCTOU Drift Prevention).
    Uses `cart_hash_service.verify_cart_integrity` to recompute the RFC 8785 canonical JSON
    and SHA-256 `intent_hash`, verifying against `cart_version.intent_hash`,
    `approval_lock.intent_hash`, and `approval_lock.approval_signature`.
    Raises `GuardrailViolationError("INTENT_HASH_DRIFT_DETECTED", ..., "G-05")` on any mismatch.
    """
    if cart_version.status == "SUPERSEDED":
        raise GuardrailViolationError(
            code="INTENT_HASH_DRIFT_DETECTED",
            message=(
                f"Guardrail G-05 Violation: CartVersion '{cart_version.id}' (v{cart_version.version_number}) "
                "has been SUPERSEDED by a newer cart edit. Stale approvals cannot be executed."
            ),
            guardrail_id="G-05",
            metadata={
                "cart_version_id": cart_version.id,
                "version_number": cart_version.version_number,
                "status": cart_version.status,
                "stored_intent_hash": cart_version.intent_hash,
            },
            http_status=409,
        )

    if approval_lock is None:
        raise GuardrailViolationError(
            code="INTENT_HASH_DRIFT_DETECTED",
            message=(
                f"Guardrail G-05 Violation: CartVersion '{cart_version.id}' has no active cryptographic "
                "ApprovalLock. Unapproved carts cannot proceed to payment."
            ),
            guardrail_id="G-05",
            metadata={"cart_version_id": cart_version.id, "status": cart_version.status},
            http_status=409,
        )

    if getattr(approval_lock, "decision", "APPROVED") != "APPROVED":
        raise GuardrailViolationError(
            code="INTENT_HASH_DRIFT_DETECTED",
            message=(
                f"Guardrail G-05 Violation: ApprovalLock '{approval_lock.id}' decision is "
                f"'{approval_lock.decision}', not 'APPROVED'."
            ),
            guardrail_id="G-05",
            metadata={
                "approval_lock_id": approval_lock.id,
                "decision": approval_lock.decision,
            },
            http_status=409,
        )

    is_valid, errors = verify_cart_integrity(
        cart_version=cart_version,
        line_items=line_items,
        approval_lock=approval_lock,
    )

    if expected_intent_hash and expected_intent_hash.strip() != approval_lock.intent_hash:
        is_valid = False
        errors.append(
            f"Caller expected_intent_hash '{expected_intent_hash}' does not match "
            f"locked approval_lock.intent_hash '{approval_lock.intent_hash}'."
        )

    if not is_valid:
        raise GuardrailViolationError(
            code="INTENT_HASH_DRIFT_DETECTED",
            message=(
                "Guardrail G-05 Violation: Cryptographic intent lock verification failed — "
                f"post-approval cart drift or signature tamper detected ({'; '.join(errors)})."
            ),
            guardrail_id="G-05",
            metadata={
                "cart_version_id": cart_version.id,
                "version_number": cart_version.version_number,
                "cart_intent_hash": cart_version.intent_hash,
                "approval_intent_hash": approval_lock.intent_hash,
                "expected_intent_hash": expected_intent_hash,
                "discrepancies": errors,
            },
            http_status=409,
        )


def enforce_approval_not_expired(approval_lock: ApprovalLock) -> None:
    """
    Guardrail G-06: Expiry TTL Enforcement.
    Verifies `datetime.now(timezone.utc) < approval_lock.expires_at`.
    Raises `GuardrailViolationError("APPROVAL_LOCK_EXPIRED", ..., "G-06")` if expired.
    """
    if approval_lock is None:
        raise GuardrailViolationError(
            code="APPROVAL_LOCK_EXPIRED",
            message="Guardrail G-06 Violation: Missing ApprovalLock record.",
            guardrail_id="G-06",
            metadata={},
            http_status=409,
        )

    now_utc = datetime.now(timezone.utc)
    expires_at = approval_lock.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)

    if now_utc >= expires_at:
        raise GuardrailViolationError(
            code="APPROVAL_LOCK_EXPIRED",
            message=(
                f"Guardrail G-06 Violation: ApprovalLock '{approval_lock.id}' expired at "
                f"{expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')} (current UTC: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}). "
                "Please clone/revise the cart version to request fresh managerial approval."
            ),
            guardrail_id="G-06",
            metadata={
                "approval_lock_id": approval_lock.id,
                "cart_version_id": approval_lock.cart_version_id,
                "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "checked_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            http_status=409,
        )


# ---------------------------------------------------------------------------
# Layer 4: PayPal P0 Payment Scope (`G-07`) & Anti-Fabrication Reconciliation (`G-08`)
# ---------------------------------------------------------------------------


def enforce_p0_payment_scope(
    merchant_id: str,
    currency: str,
    total_cents: int,
    purchase_units_count: int = 1,
    intent: str = "CAPTURE",
) -> None:
    """
    Guardrail G-07: Single Merchant / Single Order / Single Purchase Unit / Full Capture / USD-Only.
    Enforces:
    - `merchant_id == "MERCH-ACME-001"`
    - `currency == "USD"`
    - `0 < total_cents <= 500000` ($5,000.00 ceiling)
    - `purchase_units_count == 1`
    - `intent == "CAPTURE"`
    """
    if merchant_id != settings.MERCHANT_ID:
        raise GuardrailViolationError(
            code="PAYPAL_P0_SCOPE_VIOLATION",
            message=(
                f"Guardrail G-07 Violation: Unauthorized merchant '{merchant_id}'. "
                f"IntentLock P0 strictly locks orders to '{settings.MERCHANT_ID}' ({settings.MERCHANT_NAME})."
            ),
            guardrail_id="G-07",
            metadata={"merchant_id": merchant_id, "expected_merchant_id": settings.MERCHANT_ID},
            http_status=422,
        )

    if (currency or "").upper() != "USD":
        raise GuardrailViolationError(
            code="PAYPAL_P0_SCOPE_VIOLATION",
            message=(
                f"Guardrail G-07 Violation: Unsupported currency '{currency}'. "
                "IntentLock P0 strictly requires 'USD' settlement."
            ),
            guardrail_id="G-07",
            metadata={"currency": currency, "expected_currency": "USD"},
            http_status=422,
        )

    if int(total_cents) <= 0 or int(total_cents) > settings.MAX_ORDER_CENTS:
        raise GuardrailViolationError(
            code="PAYPAL_P0_SCOPE_VIOLATION",
            message=(
                f"Guardrail G-07 Violation: Order total {total_cents} cents (${total_cents / 100:.2f}) is outside "
                f"the authorized P0 transaction bounds ($0.01 to ${settings.MAX_ORDER_CENTS / 100:.2f})."
            ),
            guardrail_id="G-07",
            metadata={"total_cents": total_cents, "max_order_cents": settings.MAX_ORDER_CENTS},
            http_status=422,
        )

    if int(purchase_units_count) != 1:
        raise GuardrailViolationError(
            code="PAYPAL_P0_SCOPE_VIOLATION",
            message=(
                f"Guardrail G-07 Violation: Multi-purchase-unit or split orders are prohibited "
                f"(got purchase_units_count={purchase_units_count}, expected 1)."
            ),
            guardrail_id="G-07",
            metadata={"purchase_units_count": purchase_units_count},
            http_status=422,
        )

    if (intent or "").upper() != "CAPTURE":
        raise GuardrailViolationError(
            code="PAYPAL_P0_SCOPE_VIOLATION",
            message=(
                f"Guardrail G-07 Violation: Payment intent '{intent}' is prohibited. "
                "IntentLock P0 enforces full atomic 'CAPTURE' only."
            ),
            guardrail_id="G-07",
            metadata={"intent": intent, "expected_intent": "CAPTURE"},
            http_status=422,
        )


def enforce_anti_fabrication_reconciliation(attempt_manual_override: bool = False) -> None:
    """
    Guardrail G-08: Anti-Fabrication Reconciliation Guardrail.
    Blocks any attempt by an operator, coordinator, or agent to manually mark a transaction
    as paid/captured/verified without an authoritative PayPal Sandbox verification response.
    """
    if attempt_manual_override:
        raise GuardrailViolationError(
            code="MANUAL_PAYMENT_FABRICATION_FORBIDDEN",
            message=(
                "Guardrail G-08 Violation: Manual payment status override is strictly prohibited. "
                "Transactions can only transition to CAPTURED_VERIFIED via authoritative PayPal Sandbox "
                "Orders v2 verification matching the locked SHA-256 intent_hash."
            ),
            guardrail_id="G-08",
            metadata={"attempt_manual_override": True},
            http_status=403,
        )
