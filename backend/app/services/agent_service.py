import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CartLineItem, CartVersion, Product, PurchaseRequest, User
from .audit_service import record_audit_event
from .cart_hash_service import (
    build_canonical_cart_dict,
    compute_intent_hash,
    serialize_canonical_json,
)
from .guardrails import (
    enforce_catalog_grounding_and_pricing,
    sanitize_and_check_prompt_injection,
)
from .llm_router import llm_router


def get_catalog_map(db: Session) -> dict[str, Product]:
    """Loads all active products from SQLite keyed by uppercase SKU."""
    products = (
        db.query(Product)
        .filter(Product.is_active == True)  # noqa: E712
        .order_by(Product.sku.asc())
        .all()
    )
    return {p.sku.upper(): p for p in products}


def build_catalog_system_prompt(
    products: list[Product],
    budget_limit_cents: Optional[int] = None,
    previous_version: Optional[CartVersion] = None,
) -> str:
    """
    Builds the catalog-grounded system prompt containing all 15 products
    (`sku`, `name`, `category`, `pack_size_desc`, `unit_price_usd`, `stock_available`, `recommended_rule`)
    and strict Unprivileged Proposer security boundaries.
    """
    catalog_rows: list[str] = [
        "| SKU | Product Name | Category | Pack Size (`pack_size_desc`) | Unit Price (USD) | Stock Available | Recommended Per-Person Rule |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :--- |",
    ]
    for p in sorted(products, key=lambda x: x.sku):
        unit_usd = f"${p.unit_price_cents / 100:.2f}"
        catalog_rows.append(
            f"| `{p.sku}` | {p.name} | {p.category} | {p.pack_size_desc} | {unit_usd} | {p.stock_available} | {p.recommended_rule} |"
        )
    catalog_table = "\n".join(catalog_rows)

    budget_clause = (
        f"Stated Budget Ceiling: ${budget_limit_cents / 100:.2f} USD ({budget_limit_cents} cents). "
        "Ensure the sum of (unit_price * quantity) stays at or below this ceiling."
        if budget_limit_cents
        else "No explicit budget ceiling stated; optimize for exact headcount/pack efficiency."
    )

    previous_cart_block = "None (Creating initial CartVersion v1)."
    if previous_version is not None:
        prev_items = [
            {
                "sku": li.sku,
                "product_name": li.product_name,
                "quantity": li.quantity,
                "unit_price_usd": f"${li.unit_price_cents / 100:.2f}",
                "line_total_usd": f"${li.line_total_cents / 100:.2f}",
                "selection_rationale": li.selection_rationale,
                "headcount_math": li.headcount_math,
            }
            for li in (previous_version.line_items or [])
        ]
        previous_cart_block = (
            f"Previous CartVersion v{previous_version.version_number} "
            f"(Total: ${previous_version.total_amount_cents / 100:.2f} USD):\n"
            + json.dumps(prev_items, indent=2)
        )

    return f"""You are the IntentLock Unprivileged Purchasing Proposer Agent for **Acme Workspace Supplies** (`MERCH-ACME-001`, Currency: `USD`).
Your sole responsibility is to translate the Coordinator's informal purchasing need (or revision instruction) into an accurate, well-explained cart proposal selected strictly from the 15-item catalog below.

### STRICT SECURITY & OPERATIONAL RULES:
1. **CATALOG GROUNDING ONLY (Guardrail G-01)**: You may ONLY select `sku` values from `SKU-001` through `SKU-015`. Never invent or hallucinate SKUs. If the user asks for an item not in the catalog (e.g., monitors, laptops, furniture, gift cards), do NOT substitute an unrelated item; instead report the unfulfilled item in `warnings`.
2. **EXPLICIT HEADCOUNT & PACK-SIZE MATH**: Always use each product's `recommended_rule` and `pack_size_desc` to calculate exact pack quantities using ceiling division. Show the explicit arithmetic in `headcount_math` (e.g., "ceil((4 engineers * 2 pens) / 12 pens per box) = 1 box").
3. **STOCK RESPECT (Guardrail G-02)**: Never propose a `quantity` greater than `stock_available`. If the user requests more than `stock_available`, cap `quantity` at `stock_available` and explain the cap in `warnings`.
4. **BUDGET RESPECT**: {budget_clause}
5. **ZERO PRIVILEGE / PRICE AUTHORITY (Guardrail G-03)**: You have ZERO authority to change prices, approve carts, or execute payments. The backend deterministically binds all unit prices from SQLite.
6. **FULL CART STATE REPLACEMENT**: When revising an existing cart version, return the COMPLETE updated list of `items` for the new cart version.

### LIVE ACME WORKSPACE SUPPLIES CATALOG (15 SKUs, USD):
{catalog_table}

### PRIOR CART VERSION CONTEXT:
{previous_cart_block}

### REQUIRED JSON OUTPUT FORMAT:
Respond ONLY with a valid JSON object matching this exact structure:
{{
  "overall_summary": "Clear executive summary of the proposed cart and pack-size strategy",
  "budget_notes": "Exact math comparing proposed cart total against any stated budget ceiling",
  "warnings": ["List any out-of-catalog items excluded, stock caps applied, or blocked override attempts"],
  "items": [
    {{
      "sku": "SKU-005",
      "quantity": 4,
      "selection_rationale": "Why this specific SKU was chosen for the team need",
      "headcount_math": "4 engineers x 1 notebook/person = 4 units ($64.00)"
    }}
  ]
}}"""


def _supersede_prior_versions(
    db: Session,
    purchase_request: PurchaseRequest,
    actor: User,
    reason_summary: str,
) -> Optional[CartVersion]:
    """
    Marks any existing active CartVersion on `purchase_request` as `SUPERSEDED` (Guardrail G-05 Gate B)
    so that any prior `ApprovalLock` can no longer be used for PayPal checkout.
    Returns the previous latest `CartVersion` if one existed.
    """
    if purchase_request.status in ("CAPTURED_VERIFIED", "UNCERTAIN_NEEDS_SYNC", "CAPTURE_PENDING"):
        from app.services.guardrails import GuardrailViolationError

        raise GuardrailViolationError(
            code="ORDER_IN_FLIGHT_LOCKED",
            message=(
                f"Cannot revise PurchaseRequest '{purchase_request.id}' while payment is in "
                f"'{purchase_request.status}' state."
            ),
            guardrail_id="G-05",
            metadata={"request_id": purchase_request.id, "status": purchase_request.status},
            http_status=409,
        )

    existing_versions = (
        db.query(CartVersion)
        .filter(CartVersion.request_id == purchase_request.id)
        .order_by(CartVersion.version_number.asc())
        .all()
    )
    if not existing_versions:
        return None

    prev_latest = existing_versions[-1]
    for cv in existing_versions:
        if cv.status not in ("SUPERSEDED", "CAPTURED_VERIFIED"):
            old_status = cv.status
            cv.status = "SUPERSEDED"
            record_audit_event(
                db=db,
                actor_id=actor.id,
                actor_role=actor.role,
                event_type="CART_VERSION_SUPERSEDED",
                summary=(
                    f"CartVersion v{cv.version_number} ({cv.id}) transitioned from {old_status} "
                    f"to SUPERSEDED ({reason_summary}). Any prior approval lock on v{cv.version_number} is now un-executable."
                ),
                request_id=purchase_request.id,
                cart_version_id=cv.id,
                metadata={
                    "superseded_version_number": cv.version_number,
                    "previous_status": old_status,
                    "superseded_intent_hash": cv.intent_hash,
                    "had_approval_lock": cv.approval_lock is not None,
                },
            )
    db.flush()
    return prev_latest


async def propose_initial_cart_for_request(
    db: Session,
    coordinator: User,
    title: str,
    raw_need_text: str,
    budget_limit_cents: Optional[int] = None,
    simulate_failover_providers: Optional[list[str]] = None,
) -> tuple[PurchaseRequest, CartVersion]:
    """
    Creates a new `PurchaseRequest`, runs pre-LLM PII scrubbing and Prompt Injection Guardrail `G-03`,
    invokes `llm_router.generate_cart_proposal(...)`, grounds SKUs and prices via `G-01`/`G-02`,
    computes the RFC 8785 canonical JSON and SHA-256 `intent_hash`, and persists immutable `CartVersion` v1.
    """
    catalog_map = get_catalog_map(db)
    products_list = list(catalog_map.values())

    # 1. Layer 1 Guardrail: Pre-LLM PII Scrubber & G-03 Prompt Injection Check
    sanitized_prompt, pre_warnings = sanitize_and_check_prompt_injection(raw_need_text)

    request_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    purchase_request = PurchaseRequest(
        id=request_id,
        title=title.strip(),
        raw_need_text=sanitized_prompt.strip(),
        coordinator_id=coordinator.id,
        budget_limit_cents=budget_limit_cents,
        status="DRAFT",
        active_version_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(purchase_request)
    db.flush()

    if pre_warnings:
        record_audit_event(
            db=db,
            actor_id=coordinator.id,
            actor_role=coordinator.role,
            event_type="GUARDRAIL_G03_PRE_LLM_SCAN",
            summary=f"Pre-LLM Guardrail G-03 / PII Scrubber triggered on request {request_id}.",
            request_id=request_id,
            metadata={"warnings": pre_warnings, "sanitized_prompt": sanitized_prompt},
        )

    # 2. Build catalog-grounded system prompt & invoke Multi-LLM Failover Router
    system_prompt = build_catalog_system_prompt(
        products=products_list,
        budget_limit_cents=budget_limit_cents,
        previous_version=None,
    )
    user_prompt = (
        f"Purchase Request Title: {title}\n"
        f"Coordinator Need: {sanitized_prompt}\n"
        + (
            f"Budget Limit: ${budget_limit_cents / 100:.2f} USD ({budget_limit_cents} cents)\n"
            if budget_limit_cents
            else ""
        )
    )

    proposal_dict, telemetry = await llm_router.generate_cart_proposal(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        catalog_items=products_list,
        budget_limit_cents=budget_limit_cents,
        previous_items=None,
        simulate_failover_providers=simulate_failover_providers,
    )

    # 3. Layer 2 Guardrails: G-01 (Catalog Grounding & DB Price Lookup) & G-02 (Stock Cap)
    validated_items, post_warnings = enforce_catalog_grounding_and_pricing(
        proposed_items=proposal_dict.get("items", []),
        catalog_map=catalog_map,
        budget_limit_cents=budget_limit_cents,
    )

    # Ensure at least one valid item exists so canonical hash invariants hold
    if not validated_items and products_list:
        default_prod = catalog_map.get("SKU-005") or products_list[0]
        validated_items = [
            {
                "sku": default_prod.sku,
                "product_name": default_prod.name,
                "pack_size_desc": default_prod.pack_size_desc,
                "unit_price_cents": int(default_prod.unit_price_cents),
                "quantity": 1,
                "line_total_cents": int(default_prod.unit_price_cents),
                "selection_rationale": "Default starter item selected because no valid catalog SKUs matched the prompt.",
                "headcount_math": f"1 x {default_prod.pack_size_desc}",
            }
        ]
        post_warnings.append(
            f"[G-01 NOTICE: No valid catalog SKUs remained after filtering; initialized draft with 1x {default_prod.sku} ({default_prod.name}) for Coordinator review]"
        )

    combined_warnings: list[str] = []
    for w in pre_warnings + list(proposal_dict.get("warnings", [])) + post_warnings:
        if w and w not in combined_warnings:
            combined_warnings.append(w)

    # 4. Compute RFC 8785 Canonical JSON & SHA-256 intent_hash
    version_number = 1
    cart_version_id = f"CV-{request_id.replace('REQ-', '')}-V{version_number}"

    canonical_dict = build_canonical_cart_dict(
        merchant_id=settings.MERCHANT_ID,
        currency=settings.CURRENCY,
        request_id=request_id,
        version_number=version_number,
        items=validated_items,
    )
    canonical_json = serialize_canonical_json(canonical_dict)
    intent_hash = compute_intent_hash(canonical_json)
    total_amount_cents = int(canonical_dict["total_amount_cents"])

    cart_version = CartVersion(
        id=cart_version_id,
        request_id=request_id,
        version_number=version_number,
        status="DRAFT",
        created_by_id=coordinator.id,
        source_prompt=sanitized_prompt.strip(),
        agent_summary=str(proposal_dict.get("overall_summary", "")),
        agent_budget_notes=str(proposal_dict.get("budget_notes", "")),
        agent_warnings_json=json.dumps(combined_warnings),
        llm_provider_used=str(telemetry.get("provider_used", "google_gemini")),
        llm_model_used=str(telemetry.get("model_used", settings.GEMINI_MODEL)),
        llm_failover_hops=int(telemetry.get("failover_hops", 0)),
        llm_latency_ms=int(telemetry.get("latency_ms", 0)),
        currency=settings.CURRENCY,
        merchant_id=settings.MERCHANT_ID,
        total_amount_cents=total_amount_cents,
        canonical_payload_json=canonical_json,
        intent_hash=intent_hash,
        created_at=now,
    )
    db.add(cart_version)
    db.flush()

    for item in validated_items:
        db.add(
            CartLineItem(
                cart_version_id=cart_version_id,
                sku=item["sku"],
                product_name=item["product_name"],
                pack_size_desc=item["pack_size_desc"],
                unit_price_cents=item["unit_price_cents"],
                quantity=item["quantity"],
                line_total_cents=item["line_total_cents"],
                selection_rationale=item["selection_rationale"],
                headcount_math=item["headcount_math"],
            )
        )
    db.flush()

    purchase_request.active_version_id = cart_version_id
    purchase_request.status = "DRAFT"
    purchase_request.updated_at = datetime.now(timezone.utc)
    db.flush()

    record_audit_event(
        db=db,
        actor_id=coordinator.id,
        actor_role=coordinator.role,
        event_type="AGENT_CART_PROPOSED",
        summary=(
            f"Agent proposed immutable CartVersion v1 ({cart_version_id}) totaling "
            f"${total_amount_cents / 100:.2f} USD via {cart_version.llm_provider_used}:{cart_version.llm_model_used} "
            f"(intent_hash={intent_hash[:16]}...)."
        ),
        request_id=request_id,
        cart_version_id=cart_version_id,
        metadata={
            "version_number": version_number,
            "total_amount_cents": total_amount_cents,
            "intent_hash": intent_hash,
            "llm_telemetry": telemetry,
            "guardrail_warnings": combined_warnings,
            "item_count": len(validated_items),
        },
    )

    db.commit()
    db.refresh(purchase_request)
    db.refresh(cart_version)
    return purchase_request, cart_version


async def revise_cart_with_agent(
    db: Session,
    purchase_request: PurchaseRequest,
    coordinator: User,
    revision_prompt: str,
    budget_limit_cents: Optional[int] = None,
    simulate_failover_providers: Optional[list[str]] = None,
) -> CartVersion:
    """
    Translates a natural-language revision prompt against the previous CartVersion into a new
    immutable `CartVersion` $v_{n+1}$, automatically marking $v_n$ as `SUPERSEDED` (Guardrail G-05).
    """
    catalog_map = get_catalog_map(db)
    products_list = list(catalog_map.values())

    effective_budget = (
        budget_limit_cents if budget_limit_cents is not None else purchase_request.budget_limit_cents
    )
    if budget_limit_cents is not None:
        purchase_request.budget_limit_cents = budget_limit_cents

    prev_latest = _supersede_prior_versions(
        db=db,
        purchase_request=purchase_request,
        actor=coordinator,
        reason_summary="Natural-language cart revision requested by Coordinator",
    )
    next_version_number = (prev_latest.version_number + 1) if prev_latest else 1

    previous_items_dicts: list[dict[str, Any]] = []
    if prev_latest and prev_latest.line_items:
        for li in prev_latest.line_items:
            previous_items_dicts.append(
                {
                    "sku": li.sku,
                    "quantity": li.quantity,
                    "selection_rationale": li.selection_rationale,
                    "headcount_math": li.headcount_math,
                }
            )

    sanitized_revision, pre_warnings = sanitize_and_check_prompt_injection(revision_prompt)

    if pre_warnings:
        record_audit_event(
            db=db,
            actor_id=coordinator.id,
            actor_role=coordinator.role,
            event_type="GUARDRAIL_G03_PRE_LLM_SCAN",
            summary=f"Pre-LLM Guardrail G-03 / PII Scrubber triggered during cart revision on {purchase_request.id}.",
            request_id=purchase_request.id,
            metadata={"warnings": pre_warnings, "sanitized_revision": sanitized_revision},
        )

    sanitized_original_need, _ = sanitize_and_check_prompt_injection(purchase_request.raw_need_text or "")
    system_prompt = build_catalog_system_prompt(
        products=products_list,
        budget_limit_cents=effective_budget,
        previous_version=prev_latest,
    )
    user_prompt = (
        f"Original Need: {sanitized_original_need}\n"
        f"Coordinator Revision Instruction (for Version v{next_version_number}): {sanitized_revision}\n"
    )

    proposal_dict, telemetry = await llm_router.generate_cart_proposal(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        catalog_items=products_list,
        budget_limit_cents=effective_budget,
        previous_items=previous_items_dicts,
        simulate_failover_providers=simulate_failover_providers,
    )

    validated_items, post_warnings = enforce_catalog_grounding_and_pricing(
        proposed_items=proposal_dict.get("items", []),
        catalog_map=catalog_map,
        budget_limit_cents=effective_budget,
    )

    if not validated_items and previous_items_dicts:
        validated_items, _ = enforce_catalog_grounding_and_pricing(
            proposed_items=previous_items_dicts,
            catalog_map=catalog_map,
            budget_limit_cents=effective_budget,
        )

    combined_warnings: list[str] = []
    for w in pre_warnings + list(proposal_dict.get("warnings", [])) + post_warnings:
        if w and w not in combined_warnings:
            combined_warnings.append(w)

    cart_version_id = f"CV-{purchase_request.id.replace('REQ-', '')}-V{next_version_number}-{uuid.uuid4().hex[:4].upper()}"
    canonical_dict = build_canonical_cart_dict(
        merchant_id=settings.MERCHANT_ID,
        currency=settings.CURRENCY,
        request_id=purchase_request.id,
        version_number=next_version_number,
        items=validated_items,
    )
    canonical_json = serialize_canonical_json(canonical_dict)
    intent_hash = compute_intent_hash(canonical_json)
    total_amount_cents = int(canonical_dict["total_amount_cents"])
    now = datetime.now(timezone.utc)

    new_version = CartVersion(
        id=cart_version_id,
        request_id=purchase_request.id,
        version_number=next_version_number,
        status="DRAFT",
        created_by_id=coordinator.id,
        source_prompt=sanitized_revision.strip(),
        agent_summary=str(proposal_dict.get("overall_summary", "")),
        agent_budget_notes=str(proposal_dict.get("budget_notes", "")),
        agent_warnings_json=json.dumps(combined_warnings),
        llm_provider_used=str(telemetry.get("provider_used", "google_gemini")),
        llm_model_used=str(telemetry.get("model_used", settings.GEMINI_MODEL)),
        llm_failover_hops=int(telemetry.get("failover_hops", 0)),
        llm_latency_ms=int(telemetry.get("latency_ms", 0)),
        currency=settings.CURRENCY,
        merchant_id=settings.MERCHANT_ID,
        total_amount_cents=total_amount_cents,
        canonical_payload_json=canonical_json,
        intent_hash=intent_hash,
        created_at=now,
    )
    db.add(new_version)
    db.flush()

    for item in validated_items:
        db.add(
            CartLineItem(
                cart_version_id=cart_version_id,
                sku=item["sku"],
                product_name=item["product_name"],
                pack_size_desc=item["pack_size_desc"],
                unit_price_cents=item["unit_price_cents"],
                quantity=item["quantity"],
                line_total_cents=item["line_total_cents"],
                selection_rationale=item["selection_rationale"],
                headcount_math=item["headcount_math"],
            )
        )
    db.flush()

    purchase_request.active_version_id = cart_version_id
    purchase_request.status = "DRAFT"
    purchase_request.updated_at = now
    db.flush()

    record_audit_event(
        db=db,
        actor_id=coordinator.id,
        actor_role=coordinator.role,
        event_type="AGENT_CART_PROPOSED",
        summary=(
            f"Agent created revised immutable CartVersion v{next_version_number} ({cart_version_id}) "
            f"totaling ${total_amount_cents / 100:.2f} USD (new intent_hash={intent_hash[:16]}...)."
        ),
        request_id=purchase_request.id,
        cart_version_id=cart_version_id,
        metadata={
            "version_number": next_version_number,
            "previous_version_number": prev_latest.version_number if prev_latest else None,
            "total_amount_cents": total_amount_cents,
            "intent_hash": intent_hash,
            "llm_telemetry": telemetry,
            "guardrail_warnings": combined_warnings,
        },
    )

    db.commit()
    db.refresh(purchase_request)
    db.refresh(new_version)
    return new_version


def revise_cart_quantities(
    db: Session,
    purchase_request: PurchaseRequest,
    coordinator: User,
    line_item_edits: list[dict[str, Any]],
    budget_limit_cents: Optional[int] = None,
    source_note: str = "Manual Coordinator SKU/quantity adjustment",
) -> CartVersion:
    """
    Supports manual line-item quantity adjustments by the Coordinator.
    Creates a new immutable `CartVersion` $v_{n+1}$ with deterministically recomputed
    prices (`G-01`), stock caps (`G-02`), and SHA-256 `intent_hash`, while superseding $v_n$ (`G-05`).
    """
    catalog_map = get_catalog_map(db)
    effective_budget = (
        budget_limit_cents if budget_limit_cents is not None else purchase_request.budget_limit_cents
    )
    if budget_limit_cents is not None:
        purchase_request.budget_limit_cents = budget_limit_cents

    prev_latest = _supersede_prior_versions(
        db=db,
        purchase_request=purchase_request,
        actor=coordinator,
        reason_summary=source_note,
    )
    next_version_number = (prev_latest.version_number + 1) if prev_latest else 1

    # Preserve existing rationales if the Coordinator only adjusted quantity on an existing SKU
    prior_rationale_by_sku: dict[str, tuple[str, str]] = {}
    if prev_latest and prev_latest.line_items:
        for li in prev_latest.line_items:
            prior_rationale_by_sku[li.sku.upper()] = (li.selection_rationale, li.headcount_math)

    normalized_edits: list[dict[str, Any]] = []
    for edit in line_item_edits or []:
        if hasattr(edit, "model_dump"):
            edit_dict = edit.model_dump()
        elif isinstance(edit, dict):
            edit_dict = dict(edit)
        else:
            edit_dict = {
                "sku": getattr(edit, "sku", ""),
                "quantity": getattr(edit, "quantity", 1),
                "selection_rationale": getattr(edit, "selection_rationale", None),
                "headcount_math": getattr(edit, "headcount_math", None),
            }

        sku = str(edit_dict.get("sku", "")).strip().upper()
        qty = int(edit_dict.get("quantity", 1))
        prev_rat, _ = prior_rationale_by_sku.get(sku, ("", ""))

        normalized_edits.append(
            {
                "sku": sku,
                "quantity": qty,
                "selection_rationale": edit_dict.get("selection_rationale")
                or prev_rat
                or f"Manually selected/updated by Coordinator ({coordinator.name}).",
                "headcount_math": edit_dict.get("headcount_math")
                or f"Coordinator adjusted quantity to {qty} unit(s).",
            }
        )

    validated_items, warnings = enforce_catalog_grounding_and_pricing(
        proposed_items=normalized_edits,
        catalog_map=catalog_map,
        budget_limit_cents=effective_budget,
    )

    if not validated_items:
        raise ValueError("Cannot create a CartVersion with zero valid catalog line items.")

    cart_version_id = f"CV-{purchase_request.id.replace('REQ-', '')}-V{next_version_number}-{uuid.uuid4().hex[:4].upper()}"
    canonical_dict = build_canonical_cart_dict(
        merchant_id=settings.MERCHANT_ID,
        currency=settings.CURRENCY,
        request_id=purchase_request.id,
        version_number=next_version_number,
        items=validated_items,
    )
    canonical_json = serialize_canonical_json(canonical_dict)
    intent_hash = compute_intent_hash(canonical_json)
    total_amount_cents = int(canonical_dict["total_amount_cents"])
    now = datetime.now(timezone.utc)

    budget_notes = (
        f"Updated cart total is ${total_amount_cents / 100:.2f} ({total_amount_cents} cents) against "
        f"${effective_budget / 100:.2f} ceiling."
        if effective_budget
        else f"Updated cart total is ${total_amount_cents / 100:.2f} ({total_amount_cents} cents)."
    )

    new_version = CartVersion(
        id=cart_version_id,
        request_id=purchase_request.id,
        version_number=next_version_number,
        status="DRAFT",
        created_by_id=coordinator.id,
        source_prompt=source_note,
        agent_summary=(
            f"Coordinator {coordinator.name} manually updated line-item quantities to create "
            f"immutable CartVersion v{next_version_number} (${total_amount_cents / 100:.2f} USD)."
        ),
        agent_budget_notes=budget_notes,
        agent_warnings_json=json.dumps(warnings),
        llm_provider_used="coordinator_manual_edit",
        llm_model_used="deterministic-catalog-pricing-v1",
        llm_failover_hops=0,
        llm_latency_ms=1,
        currency=settings.CURRENCY,
        merchant_id=settings.MERCHANT_ID,
        total_amount_cents=total_amount_cents,
        canonical_payload_json=canonical_json,
        intent_hash=intent_hash,
        created_at=now,
    )
    db.add(new_version)
    db.flush()

    for item in validated_items:
        db.add(
            CartLineItem(
                cart_version_id=cart_version_id,
                sku=item["sku"],
                product_name=item["product_name"],
                pack_size_desc=item["pack_size_desc"],
                unit_price_cents=item["unit_price_cents"],
                quantity=item["quantity"],
                line_total_cents=item["line_total_cents"],
                selection_rationale=item["selection_rationale"],
                headcount_math=item["headcount_math"],
            )
        )
    db.flush()

    purchase_request.active_version_id = cart_version_id
    purchase_request.status = "DRAFT"
    purchase_request.updated_at = now
    db.flush()

    record_audit_event(
        db=db,
        actor_id=coordinator.id,
        actor_role=coordinator.role,
        event_type="CART_VERSION_MANUAL_EDIT",
        summary=(
            f"Coordinator {coordinator.name} edited cart quantities -> minted immutable CartVersion "
            f"v{next_version_number} ({cart_version_id}, total=${total_amount_cents / 100:.2f} USD, "
            f"intent_hash={intent_hash[:16]}...)."
        ),
        request_id=purchase_request.id,
        cart_version_id=cart_version_id,
        metadata={
            "version_number": next_version_number,
            "previous_version_number": prev_latest.version_number if prev_latest else None,
            "total_amount_cents": total_amount_cents,
            "intent_hash": intent_hash,
            "warnings": warnings,
        },
    )

    db.commit()
    db.refresh(purchase_request)
    db.refresh(new_version)
    return new_version
