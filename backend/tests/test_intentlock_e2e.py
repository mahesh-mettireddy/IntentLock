import json
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_llm_router_status(client: TestClient):
    """
    1. Verifies /api/v1/health, /api/v1/llm/status, and runtime key injection /api/v1/llm/keys.
    """
    # Check /api/v1/health
    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200
    health = res_health.json()
    assert health["status"] == "healthy"
    assert health["app_name"] == "IntentLock"
    assert health["sqlite_wal_enabled"] is True
    assert health["catalog_sku_count"] == 15
    assert health["merchant_id"] == "MERCH-ACME-001"
    assert health["currency"] == "USD"
    assert health["audit_chain_verified"] is True
    assert isinstance(health["llm_providers"], list)
    assert len(health["llm_providers"]) == 5

    # Check /api/v1/llm/status
    res_status = client.get("/api/v1/llm/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "active_provider" in status_data
    assert "failover_chain" in status_data
    assert len(status_data["failover_chain"]) == 5
    assert "paypal_sandbox" in status_data
    assert status_data["paypal_sandbox"]["merchant_id"] == "MERCH-ACME-001"
    assert status_data["paypal_sandbox"]["currency"] == "USD"

    # Check runtime key injection & circuit breaker simulation on /api/v1/llm/keys
    res_keys = client.post(
        "/api/v1/llm/keys",
        json={
            "simulate_primary_failure": True,
        },
    )
    assert res_keys.status_code == 200
    keys_data = res_keys.json()
    assert "providers" in keys_data

    # Reset simulated failure so router is clean
    res_reset = client.post(
        "/api/v1/llm/keys",
        json={
            "simulate_primary_failure": False,
        },
    )
    assert res_reset.status_code == 200


def test_catalog_15_usd_products(client: TestClient):
    """
    2. Verifies 15 synthetic products (SKU-001..SKU-015) for MERCH-ACME-001 in USD.
    """
    res = client.get("/api/v1/catalog")
    assert res.status_code == 200
    products = res.json()
    assert isinstance(products, list)
    assert len(products) == 15

    skus = [p["sku"] for p in products]
    expected_skus = [f"SKU-{i:03d}" for i in range(1, 16)]
    assert skus == expected_skus

    for p in products:
        assert p["merchant_id"] == "MERCH-ACME-001"
        assert p["unit_price_cents"] > 0
        assert p["unit_price_usd"] == f"{p['unit_price_cents'] / 100:.2f}"
        assert p["stock_available"] > 0
        assert len(p["recommended_rule"]) > 5
        assert p["is_active"] is True


def test_personas_and_jwt_switch(client: TestClient):
    """
    3. Verifies switching between Coordinator Alice, Approver Bob, and Buyer Charlie.
    """
    res_list = client.get("/api/v1/auth/personas")
    assert res_list.status_code == 200
    personas = res_list.json()
    assert len(personas) == 3

    expected_roles = {
        "user-coord-alice": "COORDINATOR",
        "user-approver-bob": "APPROVER",
        "user-buyer-charlie": "BUYER",
    }
    for p in personas:
        assert p["id"] in expected_roles
        assert p["role"] == expected_roles[p["id"]]

    # Test switching to each persona (including uppercase spec aliases)
    for pid, expected_role in [
        ("user-coord-alice", "COORDINATOR"),
        ("USR-APPR-BOB", "APPROVER"),
        ("user-buyer-charlie", "BUYER"),
    ]:
        sw = client.post("/api/v1/auth/switch", json={"persona_id": pid})
        assert sw.status_code == 200
        body = sw.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 20
        assert body["persona"]["role"] == expected_role


def test_full_happy_path_lifecycle(client: TestClient):
    """
    4. Full E2E Lifecycle Verification:
       - Coordinator Alice creates a purchase request -> Agent generates Cart Version v1 with item rationales,
         headcount math, and canonical SHA-256 intent_hash.
       - Coordinator Alice revises quantities -> Mints immutable Cart Version v2 with new intent_hash and supersedes v1.
       - Coordinator Alice submits v2 for approval.
       - Coordinator Alice attempts to self-approve v2 -> Blocked with HTTP 403 (G-04 Separation of Duties) & logged!
       - Approver Bob approves v2 -> Creates ApprovalLock with intent_hash, HMAC-SHA256 approval_signature, and UTC expires_at.
       - Buyer Charlie creates PayPal Sandbox Order -> Verifies PayPal Orders v2 payload has 1 purchase unit, USD, and custom_id == intent_hash.
       - Buyer Charlie captures PayPal Sandbox Order -> Runs 6-invariant automated reconciliation, verifies VERIFIED_MATCH,
         generates SHA-256 signed Evidence Bundle, and verifies hash-chained audit timeline!
    """
    # 1. Authenticate as Coordinator Alice
    alice_token = client.post("/api/v1/auth/switch", json={"persona_id": "user-coord-alice"}).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    # 2. Coordinator Alice creates a purchase request (v1)
    create_res = client.post(
        "/api/v1/requests",
        headers=alice_headers,
        json={
            "title": "E2E Test: 4-Engineer Onboarding Supply Kit",
            "raw_need_text": (
                "We are onboarding 4 software engineers next Monday. Each needs a dot-grid notebook, "
                "black gel pens, a braided USB-C cable, and a 65W wall charger under $350."
            ),
            "budget_limit_cents": 35000,
        },
    )
    assert create_res.status_code == 201
    req_detail_v1 = create_res.json()
    request_id = req_detail_v1["id"]
    v1 = req_detail_v1["active_version"]
    assert v1 is not None
    assert v1["version_number"] == 1
    assert v1["status"] == "DRAFT"
    assert len(v1["intent_hash"]) == 64
    assert len(v1["line_items"]) >= 3
    for item in v1["line_items"]:
        assert len(item["selection_rationale"]) > 0
        assert len(item["headcount_math"]) > 0
        assert item["line_total_cents"] == item["unit_price_cents"] * item["quantity"]

    v1_id = v1["id"]
    v1_hash = v1["intent_hash"]

    # 3. Coordinator Alice revises quantities -> Mints immutable Cart Version v2 with new intent_hash and supersedes v1
    revise_res = client.post(
        f"/api/v1/requests/{request_id}/versions",
        headers=alice_headers,
        json={
            "revision_prompt": "Coordinator added 1x microfiber cleaning kit (SKU-013) to onboarding bundle.",
            "budget_limit_cents": 36000,
            "line_item_edits": [
                {"sku": "SKU-005", "quantity": 4},
                {"sku": "SKU-006", "quantity": 1},
                {"sku": "SKU-009", "quantity": 4},
                {"sku": "SKU-012", "quantity": 4},
                {"sku": "SKU-013", "quantity": 1},
            ],
        },
    )
    assert revise_res.status_code == 200
    req_detail_v2 = revise_res.json()
    v2 = req_detail_v2["active_version"]
    assert v2["version_number"] == 2
    assert v2["status"] == "DRAFT"
    v2_id = v2["id"]
    v2_hash = v2["intent_hash"]
    assert v2_hash != v1_hash
    # 4*1600 + 1*1450 + 4*1800 + 4*3800 + 1*2100 = 32350 cents ($323.50)
    assert v2["total_amount_cents"] == 32350

    # Verify v1 was marked SUPERSEDED
    versions_by_num = {v["version_number"]: v for v in req_detail_v2["versions"]}
    assert versions_by_num[1]["status"] == "SUPERSEDED"
    assert versions_by_num[2]["status"] == "DRAFT"

    # 4. Coordinator Alice submits v2 for approval
    submit_res = client.post(
        f"/api/v1/requests/{request_id}/versions/{v2_id}/submit",
        headers=alice_headers,
        json={"submission_note": "Submitted v2 for managerial approval."},
    )
    assert submit_res.status_code == 200
    submitted_detail = submit_res.json()
    assert submitted_detail["status"] == "SUBMITTED"
    assert submitted_detail["active_version"]["status"] == "SUBMITTED_FOR_APPROVAL"

    # 5. Coordinator Alice attempts to self-approve v2 -> Blocked with HTTP 403 (G-04 Separation of Duties)
    self_approve_res = client.post(
        f"/api/v1/requests/{request_id}/versions/{v2_id}/approve",
        headers=alice_headers,
        json={"comment": "Attempting self-approval", "ttl_minutes": 30},
    )
    assert self_approve_res.status_code == 403
    err_body = self_approve_res.json()
    assert err_body["code"] == "SOD_SELF_APPROVAL_FORBIDDEN"
    assert err_body["guardrail_violated"] == "G-04"
    assert err_body.get("audit_event_id") is not None

    # 6. Approver Bob approves v2 -> Mints ApprovalLock with intent_hash, HMAC-SHA256 signature, and UTC expires_at
    bob_token = client.post("/api/v1/auth/switch", json={"persona_id": "user-approver-bob"}).json()["access_token"]
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    approve_res = client.post(
        f"/api/v1/requests/{request_id}/versions/{v2_id}/approve",
        headers=bob_headers,
        json={
            "comment": "Verified pack math and $323.50 <= $360.00 budget. Approved & locked.",
            "ttl_minutes": 30,
            "expected_intent_hash": v2_hash,
        },
    )
    assert approve_res.status_code == 200
    approved_detail = approve_res.json()
    assert approved_detail["status"] == "APPROVED_LOCKED"
    locked_v2 = approved_detail["active_version"]
    assert locked_v2["status"] == "APPROVED_LOCKED"
    approval_lock = locked_v2["approval_lock"]
    assert approval_lock is not None
    assert approval_lock["decision"] == "APPROVED"
    assert approval_lock["approver_id"] == "user-approver-bob"
    assert approval_lock["intent_hash"] == v2_hash
    assert len(approval_lock["approval_signature"]) == 64
    assert approval_lock["is_expired"] is False

    # 7. Buyer Charlie creates PayPal Sandbox Order
    charlie_token = client.post("/api/v1/auth/switch", json={"persona_id": "user-buyer-charlie"}).json()["access_token"]
    charlie_headers = {"Authorization": f"Bearer {charlie_token}"}

    pp_create_res = client.post(
        f"/api/v1/checkout/{v2_id}/create-paypal-order",
        headers=charlie_headers,
        json={"expected_intent_hash": v2_hash},
    )
    assert pp_create_res.status_code == 200
    pp_order = pp_create_res.json()
    paypal_order_id = pp_order["paypal_order_id"]
    assert paypal_order_id is not None
    assert pp_order["currency"] == "USD"
    assert pp_order["amount_cents"] == 32350
    assert pp_order["custom_id_intent_hash"] == v2_hash
    assert pp_order["paypal_custom_id"] == v2_hash

    order_payload = pp_order["order_payload"]
    assert len(order_payload["purchase_units"]) == 1
    pu0 = order_payload["purchase_units"][0]
    assert pu0["custom_id"] == v2_hash
    assert pu0["amount"]["currency_code"] == "USD"
    assert pu0["amount"]["value"] == "323.50"

    # 8. Buyer Charlie captures PayPal Sandbox Order & triggers 6-Invariant Automated Reconciliation
    pp_capture_res = client.post(
        f"/api/v1/checkout/{v2_id}/capture-paypal-order",
        headers=charlie_headers,
        json={
            "paypal_order_id": paypal_order_id,
            "expected_intent_hash": v2_hash,
            "payer_id": "SANDBOX-BUYER-E2E",
        },
    )
    assert pp_capture_res.status_code == 200
    cap_data = pp_capture_res.json()
    assert cap_data["payment_state"] == "CAPTURED_VERIFIED"
    assert cap_data["paypal_capture_id"] is not None

    rec = cap_data["reconciliation"]
    assert rec["verdict"] == "VERIFIED_MATCH"
    assert rec["check_order_completed"] is True
    assert rec["check_capture_completed"] is True
    assert rec["check_currency_usd"] is True
    assert rec["check_amount_exact"] is True
    assert rec["check_intent_hash_match"] is True
    assert rec["check_single_purchase_unit"] is True
    assert rec["approved_amount_cents"] == 32350
    assert rec["captured_amount_cents"] == 32350
    assert rec["approved_intent_hash"] == v2_hash
    assert rec["paypal_custom_id_hash"] == v2_hash
    assert len(rec["evidence_bundle_sha256"]) == 64

    # 9. Verify Evidence Bundle endpoint & Hash-Chained Audit Timeline endpoint
    ev_res = client.get(f"/api/v1/requests/{request_id}/evidence", headers=charlie_headers)
    assert ev_res.status_code == 200
    ev_bundle = ev_res.json()
    assert ev_bundle["request_id"] == request_id
    assert ev_bundle["cart_version_id"] == v2_id
    assert ev_bundle["approved_intent_hash"] == v2_hash
    assert ev_bundle["paypal_custom_id_echoed"] == v2_hash
    assert ev_bundle["verdict"] == "VERIFIED_MATCH"

    tl_res = client.get(f"/api/v1/requests/{request_id}/timeline", headers=charlie_headers)
    assert tl_res.status_code == 200
    tl_data = tl_res.json()
    assert tl_data["chain_verified"] is True
    event_types = [e["event_type"] for e in tl_data["events"]]
    assert "AGENT_CART_PROPOSED" in event_types
    assert "CART_VERSION_SUPERSEDED" in event_types
    assert "CART_SUBMITTED_FOR_APPROVAL" in event_types
    assert "GUARDRAIL_BLOCKED_SELF_APPROVAL" in event_types
    assert "CART_VERSION_APPROVED_LOCKED" in event_types
    assert "PAYPAL_ORDER_CREATED" in event_types
    assert "PAYPAL_ORDER_CAPTURED" in event_types
    assert "ORDER_RECONCILED_VERIFIED" in event_types


def test_all_5_security_tamper_simulations(client: TestClient):
    """
    5. Tests POST /api/v1/security/simulate-tamper across all 5 attack vectors
       (both Pytest canonical names and UI TamperSimulatorModal aliases).
    """
    vectors = [
        ("CART_DRIFT_TOCTOU", 409, "G-05"),
        ("SELF_APPROVAL_SOD", 403, "G-04"),
        ("EXPIRED_APPROVAL_REPLAY", 409, "G-06"),
        ("MANUAL_PROVIDER_OVERRIDE", 403, "G-08"),
        ("PROMPT_INJECTION_PRICE_OVERRIDE", 422, "G-01"),
        # Also verify UI component scenario IDs from TamperSimulatorModal.tsx
        ("TAMPER_CART_POST_APPROVAL", 409, "G-05"),
        ("COORDINATOR_SELF_APPROVAL", 403, "G-04"),
        ("EXPIRED_APPROVAL_CAPTURE", 409, "G-06"),
        ("OPERATOR_FAKE_PAYMENT_OVERRIDE", 403, "G-08"),
    ]

    for scenario_name, expected_http, expected_guardrail_prefix in vectors:
        res = client.post(
            "/api/v1/security/simulate-tamper",
            json={
                "request_id": "REQ-SEED-ONBOARD-01",
                "cart_version_id": "CV-SEED-ONBOARD-01-V1",
                "scenario": scenario_name,
            },
        )
        assert res.status_code == 200, f"Failed on {scenario_name}: {res.text}"
        data = res.json()
        assert data["scenario"] == scenario_name
        assert data["blocked"] is True
        assert data["http_status_code"] == expected_http
        assert expected_guardrail_prefix in data["guardrail_triggered"]
        assert data["audit_event_uid"].startswith("AUD-")
        assert len(data["explanation"]) > 20


def test_discovery_interviews_and_evaluation_suite(client: TestClient):
    """
    6. Verifies GET /api/v1/discovery/interviews (3 coordinator interviews)
       and POST /api/v1/evals/run (all 12 benchmark scenarios pass with 100% guardrail enforcement).
    """
    # 1. Discovery Interviews
    intv_res = client.get("/api/v1/discovery/interviews")
    assert intv_res.status_code == 200
    interviews = intv_res.json()
    assert len(interviews) == 3
    ids = [i["id"] for i in interviews]
    assert ids == ["COORD-INT-01", "COORD-INT-02", "COORD-INT-03"]
    for intr in interviews:
        assert intr["baseline_completion_minutes"] > 10.0
        assert intr["intentlock_completion_seconds"] < 45.0
        assert intr["intentlock_corrections_count"] == 0
        assert len(intr["pain_points"]) >= 2

    # 2. Golden Evaluation Suite (15 Scenarios + M1..M6 Canonical Metrics)
    eval_res = client.post("/api/v1/evals/run", json={})
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["total_scenarios"] == 15
    assert eval_data["passed_scenarios"] == 15
    assert eval_data["pass_rate_pct"] == 100.0
    assert eval_data["sku_f1_score"] == 1.0
    assert eval_data["pack_math_accuracy_pct"] == 100.0
    assert eval_data["price_grounding_integrity_pct"] == 100.0
    assert eval_data["explanation_completeness_pct"] == 100.0
    assert eval_data["guardrail_enforcement_pct"] == 100.0
    assert eval_data["failover_recovery_pct"] == 100.0
    assert "M1_SKU_F1" in eval_data["metrics"]
    assert "M6_E2E_LATENCY_P95" in eval_data["metrics"]
    assert len(eval_data["results"]) == 15
    for r in eval_data["results"]:
        assert r["passed"] is True, f"Scenario {r['scenario_id']} failed: {r}"
