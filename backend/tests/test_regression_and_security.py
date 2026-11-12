"""
Wave 3 Regression, Cryptographic Hardening, SQLite DDL Trigger,
Multi-LLM Failover Drill, and P1 Control Library / MCP Adapter Test Suite.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.database import SessionLocal, engine, install_sqlite_security_triggers
from app.intentlock_core import (
    canonicalize_cart,
    compute_intent_hash,
    mint_approval_lock,
    scrub_prompt_injection,
    verify_checkout_gate,
    verify_reconciliation_invariants,
)
from app.main import app
from app.models import ApprovalLock, AuditEvent, CartLineItem, CartVersion
from app.services import audit_service, guardrails


client = TestClient(app)


def test_sqlite_ddl_immutability_and_sod_triggers() -> None:
    """
    Verifies SEC-GAP-01: SQLite database-level triggers prevent:
    1. Updating or deleting rows in `audit_events` (LAW-07).
    2. Updating or deleting rows in `cart_line_items` (LAW-02).
    3. Mutating `intent_hash` or `total_amount_cents` on `cart_versions` (LAW-02).
    4. Inserting a self-approved `approval_locks` row at the SQL layer (LAW-03 / G-04).
    """
    install_sqlite_security_triggers(engine)
    db = SessionLocal()
    try:
        # 1. AuditEvent immutability
        ev = db.query(AuditEvent).first()
        assert ev is not None
        with pytest.raises((IntegrityError, OperationalError)):
            db.execute(
                text("UPDATE audit_events SET summary = 'TAMPERED' WHERE id = :id"),
                {"id": ev.id},
            )
            db.commit()
        db.rollback()

        with pytest.raises((IntegrityError, OperationalError)):
            db.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": ev.id})
            db.commit()
        db.rollback()

        # 2. CartLineItem immutability
        li = db.query(CartLineItem).first()
        assert li is not None
        with pytest.raises((IntegrityError, OperationalError)):
            db.execute(
                text("UPDATE cart_line_items SET quantity = 999 WHERE id = :id"),
                {"id": li.id},
            )
            db.commit()
        db.rollback()

        # 3. CartVersion cryptographic hash & amount immutability
        cv = db.query(CartVersion).first()
        assert cv is not None
        with pytest.raises((IntegrityError, OperationalError)):
            db.execute(
                text("UPDATE cart_versions SET total_amount_cents = 1 WHERE id = :id"),
                {"id": cv.id},
            )
            db.commit()
        db.rollback()

        # 4. ApprovalLock SQL-level Separation of Duties trigger
        with pytest.raises((IntegrityError, OperationalError)):
            db.execute(
                text(
                    """
                    INSERT INTO approval_locks (
                        id, request_id, cart_version_id, approver_id, decision,
                        comment, intent_hash, approval_signature, issued_at, expires_at
                    ) VALUES (
                        :id, 'REQ-SEED-ONBOARD-01', :cv_id, 'user-coord-alice', 'APPROVED',
                        'SQL bypass attempt', :hash, 'sig', :now, :now
                    )
                    """
                ),
                {
                    "id": f"APR-SQL-TEST-{uuid.uuid4().hex[:6]}",
                    "cv_id": f"CV-DUMMY-{uuid.uuid4().hex[:6]}",
                    "hash": "a" * 64,
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_pii_redaction_persisted_and_turn2_revision() -> None:
    """
    Verifies SEC-GAP-02: PII (emails, phone numbers, credit card PANs, SSNs)
    is scrubbed BEFORE being written to SQLite `PurchaseRequest.raw_need_text`
    and `CartVersion.source_prompt`, and remains scrubbed during Turn-2 revision.
    """
    res = client.post(
        "/api/v1/requests",
        headers={"X-Persona-Id": "user-coord-alice"},
        json={
            "title": "PII Redaction Regression Test",
            "raw_need_text": (
                "Order 2 dot-grid notebooks (SKU-005) for john.doe@example.com, "
                "phone 415-555-0199, card 4532-1111-2222-3333, SSN 123-45-6789."
            ),
            "budget_limit_cents": 15000,
        },
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    saved_text = data["raw_need_text"]
    assert "john.doe@example.com" not in saved_text
    assert "4532-1111-2222-3333" not in saved_text
    assert "123-45-6789" not in saved_text
    assert "[REDACTED" in saved_text

    # Turn-2 revision with PII
    req_id = data["id"]
    rev_res = client.post(
        f"/api/v1/requests/{req_id}/versions",
        headers={"X-Persona-Id": "user-coord-alice"},
        json={
            "revision_prompt": "Add 1 box of black gel pens (SKU-006) for manager@acme.org"
        },
    )
    assert rev_res.status_code == 200, rev_res.text
    rev_data = rev_res.json()
    v2_prompt = rev_data["active_version"]["source_prompt"]
    assert "manager@acme.org" not in v2_prompt
    assert "[REDACTED_EMAIL]" in v2_prompt


def test_sub_minute_5_second_demo_expiry_ttl() -> None:
    """
    Verifies SEC-GAP-03: Approving with `approval_ttl_seconds: 5` mints an
    ApprovalLock whose `expires_at - issued_at` is 5 seconds (not rounded to 60s).
    """
    create_res = client.post(
        "/api/v1/requests",
        headers={"X-Persona-Id": "user-coord-alice"},
        json={
            "title": "5-Second TTL Test",
            "raw_need_text": "Need 2 braided USB-C cables (SKU-009).",
            "budget_limit_cents": 10000,
        },
    )
    assert create_res.status_code in (200, 201)
    req_data = create_res.json()
    req_id = req_data["id"]
    ver_id = req_data["active_version"]["id"]

    sub_res = client.post(
        f"/api/v1/requests/{req_id}/versions/{ver_id}/submit",
        headers={"X-Persona-Id": "user-coord-alice"},
    )
    assert sub_res.status_code == 200

    app_res = client.post(
        f"/api/v1/requests/{req_id}/versions/{ver_id}/approve",
        headers={"X-Persona-Id": "user-approver-bob"},
        json={"comment": "Testing 5s demo expiry", "ttl_minutes": 1, "approval_ttl_seconds": 5},
    )
    assert app_res.status_code == 200
    lock = app_res.json()["active_version"]["approval_lock"]
    issued = datetime.fromisoformat(lock["issued_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(lock["expires_at"].replace("Z", "+00:00"))
    delta_sec = round((expires - issued).total_seconds())
    assert delta_sec == 5


def test_audit_log_secret_redaction_scrubber() -> None:
    """
    Verifies SEC-GAP-06: API keys and Bearer tokens are automatically redacted
    before being persisted to `audit_events`.
    """
    db = SessionLocal()
    try:
        fake_gemini = "AIza" + "SyB" + ("1234567890" * 3) + "1234"  # ggignore
        fake_groq = "gsk_" + "1234567890" + "abcdefghijklmnopqrstuvwxyz"  # ggignore
        fake_bearer = "Bearer " + "eyJhbGciOiJIUzI1NiIs" + "InR5cCI6IkpXVCJ9.dummy"  # ggignore
        ev = audit_service.record_audit_event(
            db=db,
            actor_id="user-coord-alice",
            actor_role="COORDINATOR",
            event_type="SECRET_SCRUB_TEST",
            summary=f"Testing accidental key {fake_gemini} in summary",
            metadata={
                "api_key": fake_groq,
                "nested": {"authorization": fake_bearer},
            },
        )
        db.commit()
        assert "AIzaSy" not in ev.summary
        assert "[REDACTED_SECRET]" in ev.summary
        assert "gsk_123456" not in ev.metadata_json
        assert "eyJhbGciOi" not in ev.metadata_json
    finally:
        db.close()


def test_llm_failover_drill_and_mcp_adapter_endpoints() -> None:
    """
    Verifies GAP-LLM-01 (`POST /api/v1/llm/test-failover`) and P1 MCP Adapter
    endpoints (`GET /api/v1/mcp/tools`, `POST /api/v1/mcp/invoke`) + `intentlock_core`.
    """
    # 1. Failover drill endpoint
    drill_res = client.post(
        "/api/v1/llm/test-failover",
        headers={"X-Persona-Id": "user-coord-alice"},
        json={"prompt": "Need 3 dot-grid notebooks (SKU-005) and 2 boxes of black gel pens (SKU-006)."},
    )
    assert drill_res.status_code == 200, drill_res.text
    drill_data = drill_res.json()
    assert drill_data["drill_status"] == "FAILOVER_RECOVERED"
    assert len(drill_data["grounded_items"]) >= 2
    assert drill_data["total_amount_cents"] > 0

    # 2. MCP Tools listing
    mcp_res = client.get("/api/v1/mcp/tools")
    assert mcp_res.status_code == 200
    mcp_data = mcp_res.json()
    assert mcp_data["count"] >= 6
    tool_names = {t["name"] for t in mcp_data["tools"]}
    assert "paypal_create_order" in tool_names
    assert "intentlock_list_catalog" in tool_names

    # 3. MCP Tool invocation
    inv_res = client.post(
        "/api/v1/mcp/invoke",
        headers={"X-Persona-Id": "user-buyer-charlie"},
        json={"tool_name": "intentlock_list_catalog", "arguments": {"category": "Breakroom & Coffee"}},
    )
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert inv_data["merchant_id"] == "MERCH-ACME-001"
    assert inv_data["count"] >= 3

    # 4. Standalone intentlock_core controls
    canon_dict, canon_json = canonicalize_cart(
        merchant_id="MERCH-ACME-001",
        currency="USD",
        request_id="REQ-CORE-01",
        version_number=1,
        items=[{"sku": "SKU-005", "unit_price_cents": 1600, "quantity": 2, "line_total_cents": 3200}],
    )
    ihash = compute_intent_hash(canon_json)
    lock = mint_approval_lock(
        cart_version_id="CV-CORE-01-V1",
        intent_hash=ihash,
        coordinator_id="user-coord-alice",
        approver_id="user-approver-bob",
        approver_role="APPROVER",
        ttl_seconds=600,
    )
    ok, errs = verify_checkout_gate(
        cart_version_id="CV-CORE-01-V1",
        merchant_id="MERCH-ACME-001",
        currency="USD",
        request_id="REQ-CORE-01",
        version_number=1,
        items=[{"sku": "SKU-005", "unit_price_cents": 1600, "quantity": 2, "line_total_cents": 3200}],
        approval_lock=lock,
    )
    assert ok is True
    assert errs == []
