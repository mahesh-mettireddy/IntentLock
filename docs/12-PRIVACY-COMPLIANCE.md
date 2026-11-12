# 12 — Privacy, Compliance & Financial Governance Implementation Plan (`IntentLock`)

**Document ID:** `GOV-COMPLIANCE-012`  
**Version:** `1.0.0`  
**Status:** Production-Grade Reference  
**System:** IntentLock — Approval-Aware Purchasing Agent Web Application  
**Regulatory & Control Alignment:** PCI-DSS v4.0 (SAQ-A Out-of-Scope / Zero-PAN), SOC 2 Type II (CC6.1, CC7.2, CC8.1), SOX Section 404 (Automated Procurement & Separation of Duties Controls), OWASP LLM Top 10 (LLM01, LLM06, LLM07, LLM08)

---

## 1. Executive Governance Summary

Autonomous or AI-assisted purchasing systems introduce severe compliance hazards when language models are permitted to handle payment credentials, mutate financial state, or transmit unredacted employee/customer PII to third-party inference providers.

IntentLock is architected from the ground up around **four verifiable compliance pillars**:

1. **Zero-PAN / Zero-Vaulting Payment Architecture:** IntentLock never collects, transmits, processes, or stores Primary Account Numbers (PANs), CVVs, bank routing details, or buyer funding credentials.
2. **Pre-Inference Data Minimization & PII Redaction:** All natural-language coordinator inputs pass through a deterministic regex + structural PII scrubber (`backend/app/services/guardrails.py`) *before* leaving the application boundary to any external LLM API.
3. **Cryptographic Non-Repudiation & Separation of Duties (SoD):** Every cart state transition, human approval lock, and PayPal Sandbox capture is bound to an RFC 8785 canonical SHA-256 `intent_hash`, HMAC-SHA256 signature, and append-only audit trail.
4. **Hard Technical Scope Enforcement:** Code-level guardrails prevent live-money execution, multi-currency conversion, split captures, recurring mandates, or autonomous agent spend.

---

## 2. Zero-PAN / Zero-Vaulting Payment Architecture

### 2.1 Payment Data Flow Boundary

```mermaid
sequenceDiagram
    autonumber
    actor Buyer as Buyer / Operator (Browser)
    participant UI as IntentLock Frontend (React)
    participant API as IntentLock Backend (FastAPI)
    participant PP as PayPal Sandbox (Orders v2 + JS SDK)

    Buyer->>UI: Clicks "Execute Approved Purchase" (Locked Version v_n)
    UI->>API: POST /api/v1/orders/{id}/create-paypal-order (intent_hash)
    API->>API: Verify ApprovalLock status, TTL, and SHA-256 intent_hash
    API->>PP: POST /v2/checkout/orders (amount, USD, custom_id=intent_hash)
    PP-->>API: Return paypal_order_id (Status: CREATED)
    API-->>UI: Return paypal_order_id + approval URL / SDK token
    Buyer->>PP: Authenticates & consents inside PayPal Sandbox UI/Popup (PAN/Credentials stay inside PayPal)
    PP-->>UI: Payer approval callback (paypal_order_id)
    UI->>API: POST /api/v1/orders/{id}/capture (paypal_order_id, intent_hash)
    API->>PP: GET/POST /v2/checkout/orders/{id}/capture
    PP-->>API: Capture receipt (capture_id, custom_id=intent_hash, COMPLETED)
    API->>API: Reconcile custom_id == intent_hash & USD amount; record immutable Evidence Bundle
```

### 2.2 PCI-DSS Scope Elimination Controls

| Control ID | Control Name | Technical Implementation in IntentLock | Verification Method |
| :--- | :--- | :--- | :--- |
| **PCI-01** | **Zero Cardholder Data (CHD) Ingestion** | No API schema (`backend/app/schemas.py`) or database table (`backend/app/models.py`) contains fields for card numbers, expiration dates, CVV, or billing street addresses. | Automated schema inspection in `test_intentlock_e2e.py`. |
| **PCI-02** | **Delegated Payer Authentication** | Buyer authentication and funding source selection occur exclusively within PayPal Sandbox's hosted checkout / JS SDK context. | Network trace shows zero credential payloads hitting `127.0.0.1:8000`. |
| **PCI-03** | **Ephemeral OAuth2 Token Handling** | `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are loaded strictly from server-side environment variables and exchanged for short-lived bearer tokens in memory; tokens are never persisted to SQLite or exposed to the frontend. | Inspect `GET /api/v1/requests/{id}/evidence` — zero bearer tokens or client secrets in output. |
| **PCI-04** | **Prompt Card-Number Rejection** | If a user accidentally pastes a 13–19 digit Luhn-valid credit card number into the natural-language request box, the pre-LLM guardrail immediately scrubs it to `[REDACTED_PAYMENT_CARD]` and logs a `PII_REDACTED` warning before calling any LLM. | Unit test with synthetic Visa/Mastercard test numbers in prompt input. |

---

## 3. Data Minimization & PII Redaction Before LLM Transmission

### 3.1 Threat Model: External Multi-LLM Inference

Because IntentLock routes natural-language supply requests across external LLM providers (`Gemini`, `Groq`, `xAI/Grok`, `OpenRouter`, `OpenAI`), raw user text could inadvertently contain employee email addresses, phone numbers, Social Security Numbers, credit card numbers, or API tokens pasted from Slack/email threads.

### 3.2 Deterministic Pre-Transmission Scrubber (`guardrails.py`)

Before `llm_router.py` constructs the outbound payload to any LLM API, `sanitize_prompt_for_llm(raw_text: str)` executes a multi-stage redaction pipeline:

1. **Email Address Redaction:**
   - Pattern: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`
   - Replacement: `[REDACTED_EMAIL]`
2. **Phone Number Redaction:**
   - Pattern: North American and international phone formats (`(\+\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}`)
   - Replacement: `[REDACTED_PHONE]`
3. **Payment Card / PAN Redaction:**
   - Pattern: `\b(?:\d[ -]*?){13,19}\b`
   - Replacement: `[REDACTED_PAN]`
4. **SSN / Tax ID Redaction:**
   - Pattern: `\b\d{3}-\d{2}-\d{4}\b`
   - Replacement: `[REDACTED_SSN]`
5. **Bearer / Secret Token Redaction:**
   - Pattern: `(?:sk-[a-zA-Z0-9_-]{16,}|AIza[0-9A-Za-z-_]{35}|gsk_[a-zA-Z0-9]{20,}|Bearer\s+[a-zA-Z0-9\-._~+/]+=*)`
   - Replacement: `[REDACTED_CREDENTIAL]`

### 3.3 Context Minimization Contract

- **What IS sent to the LLM:**
  - The PII-redacted supply request string (e.g., *"Need 5 ergonomic chairs and 10 USB-C docks for the new hires starting Monday, contact [REDACTED_EMAIL]"*).
  - The static 15-item `Acme Workspace Supplies` catalog metadata (`sku`, `name`, `category`, `unit_price_cents`, `stock_status`).
  - The budget ceiling (`budget_limit_cents`, if specified).
- **What is NEVER sent to the LLM:**
  - Internal actor IDs (`usr_coord_01`), session tokens, `INTENTLOCK_SIGNING_SECRET`, `ApprovalLock` HMAC signatures, or `PAYPAL_CLIENT_SECRET`.
  - Historical PayPal order IDs or capture receipts.

---

## 4. Immutable Audit Trail & Non-Repudiation Compliance (SOX / SOC 2 Alignment)

### 4.1 Separation of Duties (SoD) Matrix

IntentLock enforces strict role-based separation at the service layer (`backend/app/services/auth_service.py` and `approval_service.py`):

| Lifecycle Action | Coordinator (`usr_coord_01`) | AI Agent (`sys_agent_01`) | Approver (`usr_appr_01`) | Buyer / Operator (`usr_buyer_01`) |
| :--- | :---: | :---: | :---: | :---: |
| Submit Natural-Language Need | **ALLOW** | DENY | DENY | DENY |
| Propose / Explain Cart Draft | DENY | **ALLOW** | DENY | DENY |
| Edit Cart Quantities ($v_{n+1}$) | **ALLOW** | DENY | DENY | DENY |
| Submit Cart Version for Approval | **ALLOW** | DENY | DENY | DENY |
| Approve / Reject Fixed Cart $v_n$ | **DENY (SoD Block)** | **DENY (Hard Block)** | **ALLOW** | **DENY (SoD Block)** |
| Create PayPal Order & Capture | **DENY** | **DENY (Hard Block)** | **DENY** | **ALLOW (Locked $v_n$ Only)** |
| Trigger Read-Only PayPal Reconcile | ALLOW (View) | DENY | ALLOW (View) | **ALLOW (Execute Sync)** |
| Manually Mark Order as "Paid" | **DENY (No Endpoint)** | **DENY (No Endpoint)** | **DENY (No Endpoint)** | **DENY (No Endpoint)** |

> [!CAUTION]
> **Self-Approval Prevention (`SOD_SELF_APPROVAL_FORBIDDEN`):** Even if a user attempts to forge headers where `approver_id == requester_id`, `approval_service.py` explicitly verifies `request.requester_id != actor.actor_id` and `actor.role == Role.APPROVER` before minting an `ApprovalLock`.

### 4.2 Cryptographic Hash Locking & Non-Repudiation (`RFC 8785`)

Every Cart Version $v_n$ computes a deterministic SHA-256 `intent_hash` over its canonical JSON representation (`sort_keys=True`, no whitespace, sorted line items by `sku`):

```json
{
  "currency": "USD",
  "items": [
    {"line_total_cents": 22500, "quantity": 5, "sku": "SKU-ACM-003", "unit_price_cents": 4500},
    {"line_total_cents": 8900, "quantity": 1, "sku": "SKU-ACM-007", "unit_price_cents": 8900}
  ],
  "merchant_id": "ACME_WORKSPACE_SUPPLIES",
  "request_id": "req_9f8a7b6c",
  "subtotal_cents": 31400,
  "tax_cents": 0,
  "total_cents": 31400,
  "version_number": 2
}
```

When the `Approver` approves Version $v_n$, IntentLock generates an `ApprovalLock` containing:
- `intent_hash`: `SHA-256(canonical_cart_json)`
- `signature`: `HMAC-SHA256(INTENTLOCK_SIGNING_SECRET, f"{request_id}:{version_number}:{intent_hash}:{approver_id}:{approved_at_iso}:{expires_at_iso}")`

During PayPal checkout:
1. `intent_hash` is injected into PayPal's `purchase_units[0].custom_id` and `invoice_id` fields.
2. Before capture and after capture, the Reconciliation Engine verifies both the local `HMAC-SHA256` signature and the remote PayPal `custom_id == intent_hash`.

### 4.3 Append-Only Audit Log (`audit_events` Table)

Every state change emits an immutable record in `audit_events` with:
- `event_id` (UUIDv4)
- `request_id`
- `actor_id` and `actor_role` (`COORDINATOR`, `AGENT`, `APPROVER`, `BUYER`, `SYSTEM`)
- `event_type` (`CART_VERSION_CREATED`, `APPROVAL_LOCKED`, `TAMPER_DRIFT_BLOCKED`, `PAYPAL_ORDER_CREATED`, `PAYPAL_CAPTURE_COMPLETED`, `RECONCILIATION_VERIFIED`, etc.)
- `version_number` and `intent_hash`
- `payload_json` (structured evidence snapshot)
- `prev_event_hash` and `event_hash` (cryptographic hash chaining per request so historical audit rows cannot be silently deleted or altered in SQLite).

---

## 5. Scope Compliance Enforcement (Hard Technical Boundaries)

To ensure IntentLock cannot be misused outside its approved operational envelope, the following technical controls are enforced in code:

| Scope Constraint | Enforcement Mechanism | Violation Response |
| :--- | :--- | :--- |
| **Sandbox-Only Execution** | `config.py` validates `PAYPAL_MODE == "sandbox"` and `api-m.sandbox.paypal.com`. Live PayPal endpoints are rejected at startup and runtime. | Startup `RuntimeError` or `HTTP 403 SANDBOX_ONLY_VIOLATION` |
| **Single Merchant (`Acme Workspace Supplies`)** | All line items must match a valid `sku` in the seeded 15-item `catalog_items` table (`merchant_id == "ACME_WORKSPACE_SUPPLIES"`). | `HTTP 422 OFF_CATALOG_SKU_REJECTED` |
| **Single Currency (`USD` Integer Cents)** | All monetary fields are stored as integer cents (`int`) with `currency == "USD"`. Floating-point prices and non-USD currencies (`EUR`, `GBP`, `JPY`, crypto) are rejected by Pydantic validators and pre-LLM guardrails. | `HTTP 422 NON_USD_CURRENCY_REJECTED` |
| **Single Purchase Unit / Full Capture Only** | PayPal order creation (`paypal_mcp_service.py`) constructs exactly 1 `purchase_unit` with `intent: "CAPTURE"`. Partial captures, multi-seller splits, and `AUTHORIZE` intents are prohibited. | `HTTP 422 UNSUPPORTED_PAYMENT_INTENT` |
| **No Recurring / Subscription Mandates** | Billing agreements, vaulting tokens, and recurring subscription webhooks are disabled; pre-LLM guardrails block subscription/recurring purchase instructions. | `HTTP 422 RECURRING_MANDATE_FORBIDDEN` |
| **Maximum Transaction Ceiling** | Single-order hard cap of `$5,000.00` (`500,000` cents) enforced in `approval_service.py` and `guardrails.py`. | `HTTP 422 ORDER_CEILING_EXCEEDED` |
