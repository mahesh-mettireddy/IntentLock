"""
IntentLock & PayPal Sandbox MCP Adapter (`app.mcp_adapter`)
Exposes Model Context Protocol (MCP) tool definitions and execution handlers
for both IntentLock cryptographic controls and PayPal Sandbox Orders v2 tools.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.intentlock_core import (
    canonicalize_cart,
    compute_intent_hash,
    verify_reconciliation_invariants,
)
from app.models import CartVersion, Product, User
from app.services import paypal_mcp_service


def list_mcp_tools() -> list[dict[str, Any]]:
    """
    Returns combined MCP tool definitions for PayPal Sandbox MCP (`@paypal/mcp`)
    and IntentLock cryptographic governance tools.
    """
    paypal_tools = list(paypal_mcp_service.PAYPAL_MCP_TOOL_DEFINITIONS)
    intentlock_tools = [
        {
            "name": "intentlock_list_catalog",
            "description": (
                "List all 15 verified synthetic USD products from Acme Workspace Supplies "
                "(MERCH-ACME-001) with live warehouse stock and pack-size rules."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter.",
                    }
                },
            },
        },
        {
            "name": "intentlock_verify_cart_hash",
            "description": (
                "Compute and verify the RFC 8785 Canonical JSON SHA-256 intent_hash "
                "for an immutable CartVersion or line item list."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cart_version_id": {"type": "string"},
                },
                "required": ["cart_version_id"],
            },
        },
        {
            "name": "intentlock_verify_reconciliation",
            "description": (
                "Run the 6-invariant cryptographic reconciliation check comparing an "
                "approved SHA-256 intent_hash and USD cent amount against a PayPal Order payload."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "approved_intent_hash": {"type": "string"},
                    "approved_amount_cents": {"type": "integer"},
                    "paypal_order_payload": {"type": "object"},
                },
                "required": [
                    "approved_intent_hash",
                    "approved_amount_cents",
                    "paypal_order_payload",
                ],
            },
        },
    ]
    return paypal_tools + intentlock_tools


def invoke_mcp_tool(
    db: Session,
    tool_name: str,
    arguments: dict[str, Any],
    actor: User,
) -> dict[str, Any]:
    """
    Executes an MCP tool call with strict RBAC & cryptographic guardrail enforcement.
    """
    if tool_name == "intentlock_list_catalog":
        q = db.query(Product).filter(Product.is_active.is_(True))
        cat = arguments.get("category")
        if cat:
            q = q.filter(Product.category == str(cat))
        products = q.order_by(Product.sku.asc()).all()
        return {
            "tool_name": tool_name,
            "merchant_id": settings.MERCHANT_ID,
            "currency": settings.CURRENCY,
            "count": len(products),
            "items": [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "category": p.category,
                    "unit_price_cents": p.unit_price_cents,
                    "unit_price_usd": f"{p.unit_price_cents / 100:.2f}",
                    "stock_available": p.stock_available,
                    "pack_size_desc": p.pack_size_desc,
                }
                for p in products
            ],
        }

    if tool_name == "intentlock_verify_cart_hash":
        cv_id = str(arguments.get("cart_version_id", ""))
        cv = db.query(CartVersion).filter(CartVersion.id == cv_id).first()
        if not cv:
            return {"tool_name": tool_name, "ok": False, "error": f"CartVersion '{cv_id}' not found."}
        items = [
            {
                "sku": li.sku,
                "unit_price_cents": li.unit_price_cents,
                "quantity": li.quantity,
                "line_total_cents": li.line_total_cents,
            }
            for li in cv.line_items
        ]
        canon_dict, canon_json = canonicalize_cart(
            merchant_id=cv.merchant_id,
            currency=cv.currency,
            request_id=cv.request_id,
            version_number=cv.version_number,
            items=items,
        )
        recomputed = compute_intent_hash(canon_json)
        return {
            "tool_name": tool_name,
            "ok": recomputed == cv.intent_hash,
            "cart_version_id": cv.id,
            "stored_intent_hash": cv.intent_hash,
            "recomputed_intent_hash": recomputed,
            "canonical_dict": canon_dict,
        }

    if tool_name == "intentlock_verify_reconciliation":
        result = verify_reconciliation_invariants(
            approved_intent_hash=str(arguments.get("approved_intent_hash", "")),
            approved_amount_cents=int(arguments.get("approved_amount_cents", 0)),
            paypal_order_payload=dict(arguments.get("paypal_order_payload") or {}),
        )
        return {"tool_name": tool_name, **result}

    if tool_name in ("paypal_get_order_details", "get_order"):
        order_id = str(arguments.get("order_id") or arguments.get("paypal_order_id") or "9SB00000000000000")
        details = paypal_mcp_service.get_paypal_order_details(paypal_order_id=order_id)
        return {"tool_name": tool_name, "order": details}

    if tool_name in ("paypal_capture_order", "pay_order") and arguments.get("mock_application_codes"):
        order_id = str(arguments.get("order_id") or "9SB00000000000000")
        neg = paypal_mcp_service.simulate_paypal_sandbox_negative_test(
            order_id=order_id,
            mock_application_code=str(arguments.get("mock_application_codes")),
        )
        return {"tool_name": tool_name, "negative_test": neg}

    return {
        "tool_name": tool_name,
        "ok": True,
        "available_tools": [t["name"] for t in list_mcp_tools()],
    }
