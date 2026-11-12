# 10 — API & Data Contracts Specification

> **Document ID:** `IL-SPEC-010`  
> **Version:** `1.0.0`  
> **Status:** `LOCKED — P0 FULL-STACK CONTRACT SPECIFICATION`  
> **Backend Framework:** Python 3.11+ / FastAPI / Pydantic v2  
> **Base URL:** `http://localhost:8000/api/v1`  

---

## 1. API Design Principles & Authentication Envelope

All IntentLock REST endpoints are prefixed with `/api/v1`, accept and return `application/json`, and enforce strict Pydantic v2 validation (`extra="forbid"` on all mutating request bodies).

### 1.1 Persona JWT Authentication & RBAC Header
To make Separation of Duties (SoD) effortless to inspect and test in a single browser session while enforcing real cryptographic JWT verification on the backend:
- The frontend includes `Authorization: Bearer <signed_persona_jwt>` on every request.
- Switching personas in the UI calls `POST /api/v1/auth/switch`, which issues a freshly signed `HS256` JWT for one of the three human personas (`COORDINATOR`, `APPROVER`, or `BUYER`).
- Notice that the `AGENT` persona **cannot** be assumed via JWT and holds neither approval nor payment permissions.

| Persona ID | Display Name | Role Claim (`role`) | Allowed Operations | Forbidden Operations |
| :--- | :--- | :--- | :--- | :--- |
| `USR-COORD-ALICE` | Alice Chen | `COORDINATOR` | Create requests, ask Agent for proposals, revise carts ($v_1 \rightarrow v_{n+1}$), submit $v_n$ for approval | Cannot approve (`403`), cannot execute PayPal checkout (`403`) |
| `USR-APPR-BOB` | Bob Martinez | `APPROVER` | Review submitted cart versions, approve ($v_n \rightarrow$ `APPROVED_LOCKED` with TTL), reject ($v_n \rightarrow$ `REJECTED`) | Cannot approve own request (`403`), cannot create/capture PayPal orders (`403`) |
| `USR-BUYER-CHARLIE` | Charlie Vance | `BUYER` | Create PayPal Sandbox Order for `APPROVED_LOCKED` version, capture PayPal Order, trigger read-only `/reconcile` sync | Cannot edit carts (`403`), cannot approve carts (`403`), cannot manually override payment status (`403`/`409`) |

---

## 2. Standard Error Envelope

Every `4xx` or `5xx` error returned by the FastAPI backend adheres to a uniform `ErrorEnvelope` schema so the React frontend can render structured guardrail banners and link directly to the generated audit event.

```json
{
  "error": {
    "code": "GUARDRAIL_INTENT_HASH_DRIFT",
    "message": "Cart version integrity check failed: recomputed SHA-256 hash does not match the locked approval intent_hash.",
    "guardrail_violated": "G-01_INTENT_HASH_DRIFT",
    "audit_event_id": "AUD-94c1e0b2-77a1-4f33-9b12-0018a4e92d11",
    "http_status": 409,
    "timestamp_utc": "2026-11-11T19:30:00Z",
    "details": {
      "cart_version_id": "VER-3b7e91a4",
      "expected_intent_hash": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "actual_computed_hash": "sha256:4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"
    }
  }
}
```

---

## 3. Complete Endpoint Reference Matrix

| Method | Path | Required Role | Summary |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/health` | Public | Liveness, SQLite WAL status, catalog item count, and active security invariants status. |
| `GET` | `/api/v1/llm/status` | Public | Live status of the 3-provider Multi-LLM Failover Router (Gemini $\rightarrow$ Groq $\rightarrow$ OpenRouter + Rule Engine) & PayPal Sandbox MCP connectivity. |
| `GET` | `/api/v1/auth/personas` | Public | Lists the 3 pre-configured human personas and current active token metadata. |
| `POST` | `/api/v1/auth/switch` | Public | Issues a signed `HS256` JWT for `USR-COORD-ALICE`, `USR-APPR-BOB`, or `USR-BUYER-CHARLIE`. |
| `GET` | `/api/v1/catalog` | Any Authenticated | Returns the 15 synthetic USD products (`SKU-001`..`SKU-015`) from *Acme Workspace Supplies* with integer-cent pricing and stock counts. |
| `GET` | `/api/v1/requests` | Any Authenticated | Lists all purchase requests with their latest cart version, approval status, and payment reconciliation status. |
| `GET` | `/api/v1/requests/{request_id}` | Any Authenticated | Returns full details of a purchase request, all historical cart versions ($v_1..v_n$), active `ApprovalLock`, and `PaymentTransaction`. |
| `POST` | `/api/v1/requests` | `COORDINATOR` | Creates a new purchase request from informal natural language needs and invokes the Agent to generate immutable `CartVersion` $v_1$ with explanation. |
| `POST` | `/api/v1/requests/{request_id}/versions` | `COORDINATOR` | Revises a cart via natural language feedback OR structured SKU/quantity adjustments, creating immutable `CartVersion` $v_{n+1}$ and superseding $v_n$. |
| `POST` | `/api/v1/requests/{request_id}/versions/{version_id}/submit` | `COORDINATOR` | Locks edits on $v_n$ and transitions state from `DRAFT` $\rightarrow$ `SUBMITTED_FOR_APPROVAL`. |
| `POST` | `/api/v1/requests/{request_id}/versions/{version_id}/approve` | `APPROVER` | Verifies SoD (`approver != coordinator`), computes canonical `intent_hash`, signs `ApprovalLock`, sets `expires_at`, and transitions $v_n \rightarrow$ `APPROVED_LOCKED`. |
| `POST` | `/api/v1/requests/{request_id}/versions/{version_id}/reject` | `APPROVER` | Rejects `SUBMITTED_FOR_APPROVAL` version $v_n$ with mandatory reason (`status = REJECTED`). |
| `POST` | `/api/v1/checkout/{version_id}/create-paypal-order` | `BUYER` | Verifies `ApprovalLock`, HMAC, and `now_utc < expires_at` (Gate 1); invokes PayPal MCP / Orders v2 `create_order` with `custom_id = intent_hash`. |
| `POST` | `/api/v1/checkout/{version_id}/capture-paypal-order` | `BUYER` | Verifies Pre-Capture TTL & Hash (Gate 2); captures PayPal Order; runs 7-point Reconciliation Engine; generates signed `EvidenceBundle`. |
| `POST` | `/api/v1/checkout/{version_id}/reconcile` | `BUYER` | Read-only synchronization with PayPal Sandbox `GET /v2/checkout/orders/{id}` to resolve `UNCERTAIN_NEEDS_SYNC` transactions without manual override. |
| `GET` | `/api/v1/requests/{request_id}/evidence` | Any Authenticated | Returns the cryptographically signed `EvidenceBundle` (Approved Cart vs. PayPal Capture diff, hashes, MCP trace, reconciliation checklist). |
| `GET` | `/api/v1/requests/{request_id}/timeline` | Any Authenticated | Returns the chronological, hash-chained audit trail (`audit_events`) for the request and verifies hash-chain continuity. |
| `POST` | `/api/v1/security/simulate-tamper` | Any Authenticated | Executes a safe, live red-team attack simulation (`TAMPER_CART_POST_APPROVAL`, `COORDINATOR_SELF_APPROVAL`, `PROMPT_INJECTION_PRICE_OVERRIDE`, `EXPIRED_APPROVAL_CAPTURE`, `OPERATOR_FAKE_PAYMENT_OVERRIDE`) and logs the guardrail block. |
| `GET` | `/api/v1/discovery/interviews` | Any Authenticated | Returns structured Coordinator/Approver/Operator user discovery insights and problem validation metrics. |
| `POST` | `/api/v1/evals/run` | Any Authenticated | Runs the deterministic & agentic evaluation suite (catalog accuracy, budget adherence, prompt injection immunity, hash determinism, reconciliation accuracy). |

---

## 4. Detailed Endpoint Request & Response Contracts

### 4.1 System Health & Multi-LLM Failover Status

#### `GET /api/v1/llm/status`
Returns real-time configuration and telemetry for the Multi-LLM Failover Router and PayPal Sandbox connection.

**Response `200 OK`:**
```json
{
  "active_provider": "gemini",
  "failover_chain": [
    {
      "priority": 1,
      "provider": "gemini",
      "model": "gemini-2.5-flash",
      "configured": true,
      "circuit_state": "CLOSED",
      "last_latency_ms": 640
    },
    {
      "priority": 2,
      "provider": "groq",
      "model": "llama-3.3-70b-versatile",
      "configured": true,
      "circuit_state": "CLOSED",
      "last_latency_ms": null
    },
    {
      "priority": 3,
      "provider": "openrouter",
      "model": "openai/gpt-4o-mini",
      "configured": true,
      "circuit_state": "CLOSED",
      "last_latency_ms": null
    },
    {
      "priority": 4,
      "provider": "deterministic_fallback",
      "model": "intentlock-rule-synthesizer-v1",
      "configured": true,
      "circuit_state": "ALWAYS_READY",
      "last_latency_ms": 4
    }
  ],
  "paypal_sandbox": {
    "environment": "SANDBOX",
    "api_base_url": "https://api-m.sandbox.paypal.com",
    "mcp_toolkit_enabled": true,
    "credentials_configured": true,
    "merchant_id": "MERCH-ACME-001",
    "merchant_name": "Acme Workspace Supplies",
    "currency": "USD"
  }
}
```

---

### 4.2 Persona Authentication Endpoints

#### `POST /api/v1/auth/switch`
**Request Body:**
```json
{
  "persona_id": "USR-COORD-ALICE"
}
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in_seconds": 86400,
  "persona": {
    "user_id": "USR-COORD-ALICE",
    "display_name": "Alice Chen",
    "role": "COORDINATOR",
    "department": "Operations & Workplace Experience",
    "permissions": [
      "request:create",
      "cart:revise",
      "cart:submit"
    ]
  }
}
```

---

### 4.3 Catalog Endpoint

#### `GET /api/v1/catalog`
**Response `200 OK`:**
```json
{
  "merchant_id": "MERCH-ACME-001",
  "merchant_name": "Acme Workspace Supplies",
  "currency": "USD",
  "total_items": 15,
  "items": [
    {
      "sku": "SKU-001",
      "name": "Ergonomic Mesh Task Chair",
      "category": "Seating",
      "description": "BIFMA-certified breathable mesh office chair with adjustable lumbar support.",
      "unit_price_cents": 18900,
      "unit_price_formatted": "$189.00",
      "currency": "USD",
      "stock_available": 25,
      "tags": ["ergonomic", "chair", "seating", "new-hire", "desk"]
    }
  ]
}
```

---

### 4.4 Purchase Request Creation & Agent Cart Proposal ($v_1$)

#### `POST /api/v1/requests`
Requires `role == COORDINATOR`. Creates a `PurchaseRequest`, invokes the Agent via the Multi-LLM Failover Router to translate the informal need into valid catalog items, prices them strictly on the server in integer USD cents, and persists immutable `CartVersion` $v_1$ (`status = "DRAFT"`).

**Request Body:**
```json
{
  "title": "Remote Onboarding Setup for 2 Backend Engineers",
  "natural_language_need": "We have two new backend engineers starting Monday. Each needs a USB-C multiport hub, a wireless mechanical keyboard, and a 1080p webcam. Keep the total under $350.",
  "budget_ceiling_cents": 35000
}
```

**Response `201 Created`:**
```json
{
  "request_id": "REQ-8f92a1c0",
  "title": "Remote Onboarding Setup for 2 Backend Engineers",
  "natural_language_need": "We have two new backend engineers starting Monday. Each needs a USB-C multiport hub, a wireless mechanical keyboard, and a 1080p webcam. Keep the total under $350.",
  "budget_ceiling_cents": 35000,
  "budget_ceiling_formatted": "$350.00",
  "coordinator_user_id": "USR-COORD-ALICE",
  "coordinator_name": "Alice Chen",
  "current_version_number": 1,
  "created_at_utc": "2026-11-11T19:25:00Z",
  "active_version": {
    "cart_version_id": "VER-1a4c88e1",
    "request_id": "REQ-8f92a1c0",
    "version_number": 1,
    "parent_version_id": null,
    "status": "DRAFT",
    "merchant_id": "MERCH-ACME-001",
    "merchant_name": "Acme Workspace Supplies",
    "currency": "USD",
    "total_amount_cents": 32400,
    "total_amount_formatted": "$324.00",
    "within_budget": true,
    "agent_explanation": "Selected 2x USB-C Multiport Hubs (SKU-004), 2x Wireless Mechanical Keyboards (SKU-006), and 2x 1080p HD Pro Webcams (SKU-005) from Acme Workspace Supplies. The total is $324.00, which is $26.00 under your $350.00 ceiling.",
    "llm_provider_used": "gemini:gemini-2.5-flash",
    "candidate_intent_hash": "sha256:6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
    "items": [
      {
        "sku": "SKU-004",
        "name": "USB-C Multiport Hub (7-in-1)",
        "unit_price_cents": 2900,
        "unit_price_formatted": "$29.00",
        "quantity": 2,
        "line_total_cents": 5800,
        "line_total_formatted": "$58.00",
        "item_rationale": "1 hub per engineer for connecting peripherals and external monitors."
      },
      {
        "sku": "SKU-005",
        "name": "1080p HD Pro Webcam with Privacy Shutter",
        "unit_price_cents": 4800,
        "unit_price_formatted": "$48.00",
        "quantity": 2,
        "line_total_cents": 9600,
        "line_total_formatted": "$96.00",
        "item_rationale": "1 webcam per remote engineer for team standups."
      },
      {
        "sku": "SKU-006",
        "name": "Tactile Wireless Mechanical Keyboard",
        "unit_price_cents": 8500,
        "unit_price_formatted": "$85.00",
        "quantity": 2,
        "line_total_cents": 17000,
        "line_total_formatted": "$170.00",
        "item_rationale": "1 mechanical keyboard per engineer as requested."
      }
    ],
    "approval_lock": null,
    "payment_transaction": null,
    "created_at_utc": "2026-11-11T19:25:01Z"
  }
}
```

---

### 4.5 Cart Revision ($v_n \rightarrow v_{n+1}$) & Submission

#### `POST /api/v1/requests/{request_id}/versions`
Requires `role == COORDINATOR`. Supports revising the cart either via natural language instruction to the Agent (`revision_instruction`) OR explicit line-item adjustments (`explicit_items`). Creates a new immutable `CartVersion` $v_{n+1}$ (`status = "DRAFT"`), marks $v_n$ as `SUPERSEDED`, and automatically revokes any prior `ApprovalLock` on $v_n$.

**Request Body:**
```json
{
  "revision_instruction": "Add 2 Ergonomic Wireless Vertical Mice (SKU-007) as well, and update our budget ceiling to $450.",
  "updated_budget_ceiling_cents": 45000,
  "explicit_items": null
}
```

#### `POST /api/v1/requests/{request_id}/versions/{version_id}/submit`
Requires `role == COORDINATOR`. Transitions $v_n$ from `DRAFT` $\rightarrow$ `SUBMITTED_FOR_APPROVAL`.

**Request Body:**
```json
{
  "submission_note": "Verified quantities with Engineering Manager. Ready for finance approval."
}
```

---

### 4.6 Cryptographic Approval & Rejection Endpoints

#### `POST /api/v1/requests/{request_id}/versions/{version_id}/approve`
Requires `role == APPROVER` AND `current_user.user_id != request.coordinator_user_id`. Computes the canonical JSON SHA-256 `intent_hash`, signs the HMAC `approval_signature`, sets `expires_at = now_utc + approval_ttl_seconds`, and transitions $v_n \rightarrow$ `APPROVED_LOCKED`.

**Request Body:**
```json
{
  "approval_note": "Approved for Q4 engineering onboarding budget.",
  "approval_ttl_seconds": 900
}
```

**Response `200 OK`:**
```json
{
  "cart_version_id": "VER-3b7e91a4",
  "version_number": 2,
  "status": "APPROVED_LOCKED",
  "approval_lock": {
    "approval_lock_id": "LOCK-7d21f09a",
    "cart_version_id": "VER-3b7e91a4",
    "request_id": "REQ-8f92a1c0",
    "version_number": 2,
    "approver_user_id": "USR-APPR-BOB",
    "approver_name": "Bob Martinez",
    "coordinator_user_id": "USR-COORD-ALICE",
    "intent_hash": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "approval_signature": "hmac-sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "approved_amount_cents": 40800,
    "approved_currency": "USD",
    "issued_at_utc": "2026-11-11T19:28:00Z",
    "expires_at_utc": "2026-11-11T19:43:00Z",
    "approval_note": "Approved for Q4 engineering onboarding budget.",
    "revoked": false
  }
}
```

#### `POST /api/v1/requests/{request_id}/versions/{version_id}/reject`
Requires `role == APPROVER`. Transitions $v_n$ from `SUBMITTED_FOR_APPROVAL` $\rightarrow$ `REJECTED`.

**Request Body:**
```json
{
  "rejection_reason": "Please remove the mechanical keyboards and use standard stock keyboards."
}
```

---

### 4.7 PayPal Sandbox Execution & Reconciliation Endpoints

#### `POST /api/v1/checkout/{version_id}/create-paypal-order`
Requires `role == BUYER`. Runs Gate 1 (verifies `APPROVED_LOCKED`, SoD, live canonical `intent_hash`, HMAC signature, and `now_utc < expires_at`). Invokes PayPal MCP `create_order` / Orders v2 `POST /v2/checkout/orders` with `purchase_units[0].custom_id = intent_hash`.

**Request Body:**
```json
{
  "idempotency_hint": "buyer-checkout-init"
}
```

**Response `201 Created`:**
```json
{
  "payment_transaction_id": "PAY-55c09e12",
  "cart_version_id": "VER-3b7e91a4",
  "payment_state": "PAYPAL_ORDER_CREATED",
  "paypal_order_id": "7XY12345AB678901C",
  "paypal_status": "CREATED",
  "intent_hash_bound": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "paypal_custom_id": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "paypal_invoice_id": "IL-VER-3b7e91a4-7d21f09a",
  "amount_cents": 40800,
  "amount_formatted": "$408.00",
  "currency": "USD",
  "approval_expires_at_utc": "2026-11-11T19:43:00Z",
  "approve_link": "https://www.sandbox.paypal.com/checkoutnow?token=7XY12345AB678901C",
  "mcp_tool_invoked": "paypal_mcp.create_order"
}
```

#### `POST /api/v1/checkout/{version_id}/capture-paypal-order`
Requires `role == BUYER`. Runs Gate 2 (re-verifies live canonical `intent_hash`, HMAC signature, and `now_utc < expires_at` right before capture). Invokes PayPal MCP `capture_order`, fetches authoritative order details via `get_order_details`, executes the 7-point Reconciliation Engine, and seals the `EvidenceBundle`.

**Request Body:**
```json
{
  "paypal_order_id": "7XY12345AB678901C",
  "payer_id": "SANDBOXBUYER99"
}
```

**Response `200 OK`:**
```json
{
  "payment_transaction_id": "PAY-55c09e12",
  "cart_version_id": "VER-3b7e91a4",
  "payment_state": "CAPTURED_VERIFIED",
  "paypal_order_id": "7XY12345AB678901C",
  "paypal_capture_id": "9AB98765CD432109E",
  "reconciliation": {
    "outcome": "VERIFIED",
    "verified_at_utc": "2026-11-11T19:31:15Z",
    "checks": {
      "internal_hash_integrity": true,
      "REC_01_order_completed": true,
      "REC_02_intent_is_capture": true,
      "REC_03_single_purchase_unit": true,
      "REC_04_custom_id_matches_intent_hash": true,
      "REC_05_currency_usd": true,
      "REC_06_amount_cents_match": true,
      "REC_07_capture_completed": true
    },
    "discrepancies": []
  },
  "evidence_bundle_id": "EVID-88a12f30"
}
```

#### `POST /api/v1/checkout/{version_id}/reconcile`
Requires `role == BUYER`. Accepts an empty JSON object `{}`. Queries PayPal Sandbox `GET /v2/checkout/orders/{paypal_order_id}` directly and runs the 7-point Reconciliation Engine to resolve `UNCERTAIN_NEEDS_SYNC` transactions.

---

## 5. Reference Pydantic v2 Data Models (`backend/app/schemas/contracts.py`)

```python
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RoleEnum(str, Enum):
    COORDINATOR = "COORDINATOR"
    APPROVER = "APPROVER"
    BUYER = "BUYER"


class CartVersionStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_FOR_APPROVAL = "SUBMITTED_FOR_APPROVAL"
    APPROVED_LOCKED = "APPROVED_LOCKED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    PAYPAL_ORDER_CREATED = "PAYPAL_ORDER_CREATED"
    BUYER_APPROVED = "BUYER_APPROVED"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    UNCERTAIN_NEEDS_SYNC = "UNCERTAIN_NEEDS_SYNC"
    CAPTURED_VERIFIED = "CAPTURED_VERIFIED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentProposedItem(StrictRequestModel):
    """Schema enforced on LLM structured output — notice unit_price is strictly excluded."""
    sku: str = Field(..., pattern=r"^SKU-(00[1-9]|01[0-5])$")
    quantity: int = Field(..., ge=1, le=50)
    item_rationale: str = Field(..., min_length=3, max_length=400)


class AgentCartProposalSchema(StrictRequestModel):
    items: list[AgentProposedItem] = Field(..., min_length=1, max_length=15)
    overall_explanation: str = Field(..., min_length=10, max_length=1500)


class CreatePurchaseRequestPayload(StrictRequestModel):
    title: str = Field(..., min_length=3, max_length=140)
    natural_language_need: str = Field(..., min_length=5, max_length=2000)
    budget_ceiling_cents: int = Field(..., gt=0, le=1_000_000)


class ExplicitItemEdit(StrictRequestModel):
    sku: str = Field(..., pattern=r"^SKU-(00[1-9]|01[0-5])$")
    quantity: int = Field(..., ge=1, le=50)
    item_rationale: str | None = Field(default=None, max_length=400)


class CreateCartRevisionPayload(StrictRequestModel):
    revision_instruction: str | None = Field(default=None, max_length=2000)
    updated_budget_ceiling_cents: int | None = Field(default=None, gt=0, le=1_000_000)
    explicit_items: list[ExplicitItemEdit] | None = Field(default=None, min_length=1, max_length=15)


class ApproveCartVersionPayload(StrictRequestModel):
    approval_note: str = Field(default="Approved after line-item review.", max_length=500)
    approval_ttl_seconds: int = Field(default=900, ge=5, le=86400)


class RejectCartVersionPayload(StrictRequestModel):
    rejection_reason: str = Field(..., min_length=3, max_length=500)


class CapturePayPalOrderPayload(StrictRequestModel):
    paypal_order_id: str = Field(..., min_length=5, max_length=64)
    payer_id: str | None = Field(default=None, max_length=64)


class TamperScenarioEnum(str, Enum):
    TAMPER_CART_POST_APPROVAL = "TAMPER_CART_POST_APPROVAL"
    COORDINATOR_SELF_APPROVAL = "COORDINATOR_SELF_APPROVAL"
    PROMPT_INJECTION_PRICE_OVERRIDE = "PROMPT_INJECTION_PRICE_OVERRIDE"
    EXPIRED_APPROVAL_CAPTURE = "EXPIRED_APPROVAL_CAPTURE"
    OPERATOR_FAKE_PAYMENT_OVERRIDE = "OPERATOR_FAKE_PAYMENT_OVERRIDE"


class SimulateTamperPayload(StrictRequestModel):
    request_id: str
    cart_version_id: str
    scenario: TamperScenarioEnum


class EvidenceBundleResponse(BaseModel):
    evidence_bundle_id: str
    request_id: str
    cart_version_id: str
    version_number: int
    merchant_id: str
    currency: str
    coordinator_user_id: str
    approver_user_id: str
    buyer_user_id: str
    intent_hash: str
    approval_signature: str
    approval_issued_at_utc: datetime
    approval_expires_at_utc: datetime
    paypal_order_id: str
    paypal_capture_id: str
    paypal_custom_id_echoed: str
    paypal_invoice_id_echoed: str
    approved_total_cents: int
    captured_total_cents: int
    reconciliation_outcome: str
    reconciliation_checks: dict[str, bool]
    canonical_cart_json: dict[str, Any]
    evidence_signature: str
    sealed_at_utc: datetime
```
