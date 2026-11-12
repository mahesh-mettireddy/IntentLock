# IntentLock Cross-Module Integration & End-to-End Workflow Audit Report

**Audit Date:** 2026-11-12  
**Scope:** Cross-module wiring across `frontend/src/` and `backend/app/`, TypeScript vs. FastAPI/Pydantic schema alignment, PayPal Sandbox Orders v2 + MCP trace integration, and P1 extensibility (`intentlock_core` usable control library, `mcp_adapter.py`, and expanded evaluation suite).

---

## Executive Summary

### Wiring & Coverage Scorecard

| Category | Audited Items | Connected / Verified | Partial / Enhancement Needed | Broken / Orphaned |
| :--- | :---: | :---: | :---: | :---: |
| **API Client Endpoints (`client.ts` ↔ `main.py`)** | 17 | 17 (100%) | 3 minor UX/trace enrichments | 0 |
| **TypeScript Interfaces (`intentlock.ts` ↔ `schemas.py`)** | 18 | 17 | 1 (`PayPalOrder` missing `mcp_trace` / `order_payload` fields) | 0 |
| **E2E Multi-Persona Workflows (Steps 1 → 4)** | 7 | 7 | 3 workflow polish items | 0 |
| **P1 Extensibility Scope (`intentlock_core`, `mcp_adapter`, Larger Evals)** | 3 | 1 (12-scenario evals) | 2 (`intentlock_core/` & `mcp_adapter.py` not yet extracted) | 0 |

---

## 1. API Client & Component Consumption Audit (`frontend/src/api/client.ts`)

Every method in `frontend/src/api/client.ts` was traced from its HTTP call to `backend/app/main.py` and into the consuming React components:

### 1.1 `getHealth()` → `GET /api/v1/health`
- **Backend Handler:** `get_health` (`backend/app/main.py:466`) returns `SystemHealthOut`.
- **Consumer:** `App.tsx` (`bootstrap` line 171, `handleUpdateKeys` line 543).
- **Status:** **WIRED**.
- **Observation:** `App.tsx` fetches `health` and uses `health.active_llm_provider` as a fallback for the header badge, while `sqlite_wal_enabled` and `audit_chain_verified` are displayed as static text in the secondary header (`● SQLite WAL + Hash Chain Active`). Surfacing live `health.audit_events_count` and `health.paypal_credentials_configured` in the header bar will make telemetry even more responsive.

### 1.2 `getLLMStatus()` & `updateLLMAndPayPalKeys()` → `GET /api/v1/llm/status`, `POST /api/v1/llm/keys`
- **Backend Handlers:** `get_llm_status` (`main.py:537`) & `update_runtime_llm_and_paypal_keys` (`main.py:542`).
- **Consumers:** `App.tsx` (lines 172, 541, 1000), `LLMRouterConfigModal.tsx` (lines 90–125), `BuyerCheckoutWorkspace.tsx` (`paypalClientId={llmStatus?.paypal_sandbox?.client_id}` at `App.tsx:966`).
- **Status:** **WIRED** (with 2 minor state sync gaps identified below):
  1. **Gap 1 — `simulateFailover` initial state in `LLMRouterConfigModal.tsx`:** In `LLMRouterConfigModal.tsx:84`, `const [simulateFailover, setSimulateFailover] = useState(false)` is initialized to `false` and never synced with `llmStatus?.simulate_primary_failure` when the modal opens or refreshes. Furthermore, `LLMStatusResponse` in `frontend/src/types/intentlock.ts:310` does not declare `simulate_primary_failure?: boolean`, even though `_build_llm_and_paypal_status_response()` (`main.py:523`) returns `"simulate_primary_failure": _SIMULATE_PRIMARY_LLM_FAILURE`.
  2. **Gap 2 — Current PayPal Sandbox status badge inside `LLMRouterConfigModal.tsx`:** When a user configures `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` via `.env` or the modal, `llmStatus.paypal_sandbox` returns `credentials_configured: true`, `client_id_preview`, and `execution_mode_active: "PAYPAL_SANDBOX_API"`. Displaying a live status pill (`LIVE SANDBOX API CONNECTED` vs. `DETERMINISTIC MCP EMULATOR`) and pre-populating the masked preview in `LLMRouterConfigModal.tsx` will give immediate visual confirmation.

### 1.3 `getPersonas()` & `switchPersona()` → `GET /api/v1/auth/personas`, `POST /api/v1/auth/switch`
- **Backend Handlers:** `list_personas` (`main.py:602`) & `switch_persona` (`main.py:608`).
- **Consumers:** `App.tsx` (`bootstrap` line 173, `handleSwitchPersona` line 218), and role-switch CTA buttons in `CoordinatorWorkspace.tsx:241`, `ApproverWorkspace.tsx:197`, and `BuyerCheckoutWorkspace.tsx:188`.
- **Status:** **WIRED**. Updates both JWT `Authorization: Bearer <token>` and `X-Persona-Id` / `X-Actor-Role` headers in `client.ts:26-30`.

### 1.4 `getCatalog()` → `GET /api/v1/catalog`
- **Backend Handler:** `list_catalog` (`main.py:635`) returns `list[ProductOut]` (15 USD SKUs).
- **Consumers:** `App.tsx` (line 174), `CoordinatorWorkspace.tsx` (stock bounds & manual SKU selector), `MerchantCatalogView.tsx` (15-SKU grid, search, category filter).
- **Status:** **WIRED** (with 2 integration gaps):
  1. **Gap 3 — Catalog Quick-Start SKU Prop Dropped in `App.tsx`:** `MerchantCatalogView.tsx:192` calls `onQuickStartWithSku(prod.sku, prod.name)` when the user clicks the **"Request"** button on any SKU card. However, `App.tsx:761` passes:
     ```tsx
     onQuickStartWithSku={() => {
       setActiveTab('WORKSPACE');
       setActiveStep(1);
     }}
     ```
     It ignores `(sku, productName)`, so clicking "Request" on a catalog item switches tabs without pre-populating or focusing the composer in `CoordinatorWorkspace.tsx`.
  2. **Gap 4 — Catalog Stock Refresh After Capture:** When an order is captured and reconciled in `reconciliation_service.py:197-201`, `prod.stock_available` is atomically decremented in SQLite. However, `App.tsx` does not re-fetch `apiClient.getCatalog()` after `handleCapturePayPalOrder` or `handleOneClickCreateAndCapture`, so `MerchantCatalogView` continues showing the initial stock count until page reload.

### 1.5 `getRequests()`, `getRequestDetail()`, `createRequest()`, `reviseCartVersion()`, `submitCartVersion()`
- **Backend Handlers:** `GET /api/v1/requests`, `GET /api/v1/requests/{id}`, `POST /api/v1/requests`, `POST /api/v1/requests/{id}/versions`, `POST /api/v1/requests/{id}/versions/{version_id}/submit`.
- **Consumer:** `CoordinatorWorkspace.tsx` via `App.tsx`.
- **Status:** **WIRED** (with 1 missing modal render in `CoordinatorWorkspace.tsx`):
  - **Gap 5 — `showCanonicalModal` state is set but never rendered in `CoordinatorWorkspace.tsx`:** At `CoordinatorWorkspace.tsx:94`, `const [showCanonicalModal, setShowCanonicalModal] = useState<boolean>(false)` is declared, and line 753 renders a button:
    ```tsx
    <button onClick={() => setShowCanonicalModal(true)}>Inspect Canonical JSON</button>
    ```
    However, `CoordinatorWorkspace.tsx` never renders a modal or drawer reading `showCanonicalModal`! Clicking **"Inspect Canonical JSON"** in Step 1 currently does nothing visible in the UI.

### 1.6 `approveCartVersion()` & `rejectCartVersion()`
- **Backend Handlers:** `POST /api/v1/requests/{id}/versions/{version_id}/approve` & `/reject` (`main.py:821`, `main.py:852`).
- **Consumer:** `ApproverWorkspace.tsx` via `App.tsx`.
- **Status:** **WIRED** (with 1 sub-minute TTL precision bug):
  - **Gap 6 — Sub-Minute Demo Expiry Test Mode (5-Second TTL) Rounded Up to 60 Seconds:** In `ApproverWorkspace.tsx:55`, the 4th TTL option is:
    ```ts
    { label: '5 Seconds (Demo Expiry Test Mode)', minutes: 1, seconds: 5 }
    ```
    When passed to `apiClient.approveCartVersion`, the payload sends both `ttl_minutes: 1` and `approval_ttl_seconds: 5`. In `backend/app/main.py:835-837`:
    ```python
    ttl_minutes = body.ttl_minutes
    if ttl_minutes is None and body.approval_ttl_seconds is not None:
        ttl_minutes = max(1, int(round(body.approval_ttl_seconds / 60)))
    ```
    Because `body.ttl_minutes` is `1` (not `None`), `approval_ttl_seconds=5` is ignored, and even if `ttl_minutes` were `None`, `max(1, ...)` forces a minimum of 1 full minute (60 seconds) instead of 5 seconds! Supporting `ttl_seconds` (`approval_ttl_seconds`) directly in `approval_service.approve_cart_version` when `approval_ttl_seconds` is provided (e.g., `< 60` seconds for Demo Expiry Test Mode) will make the 5-second live TTL countdown and G-06 expiry test work in 5 seconds as labeled.

### 1.7 `createPayPalOrder()`, `capturePayPalOrder()`, `reconcilePayPalOrder()`
- **Backend Handlers:** `POST /api/v1/checkout/{version_id}/create-paypal-order`, `/capture-paypal-order`, `/reconcile`.
- **Consumers:** `BuyerCheckoutWorkspace.tsx` and `ReconciliationAuditView.tsx` via `App.tsx`.
- **Status:** **WIRED** (see Section 3 for PayPal Sandbox & MCP trace findings).

### 1.8 `getEvidenceBundle()` & `getAuditTimeline()`
- **Backend Handlers:** `GET /api/v1/requests/{id}/evidence` & `GET /api/v1/requests/{id}/timeline`.
- **Consumer:** `ReconciliationAuditView.tsx` via `App.tsx`.
- **Status:** **WIRED**.

### 1.9 `simulateTamper()` → `POST /api/v1/security/simulate-tamper`
- **Backend Handler:** `simulate_security_tamper` (`main.py:1407`).
- **Consumer:** `TamperSimulatorPanel` (`TamperSimulatorModal.tsx`) embedded in `BuyerCheckoutWorkspace.tsx:522`.
- **Status:** **WIRED**. All 5 scenario IDs in `TAMPER_SCENARIOS` (`TAMPER_CART_POST_APPROVAL`, `COORDINATOR_SELF_APPROVAL`, `EXPIRED_APPROVAL_CAPTURE`, `OPERATOR_FAKE_PAYMENT_OVERRIDE`, `PROMPT_INJECTION_PRICE_OVERRIDE`) match the backend alias dispatcher in `main.py:1447-1676`.

### 1.10 `getDiscoveryInterviews()` & `runEvaluationSuite()`
- **Backend Handlers:** `GET /api/v1/discovery/interviews`, `POST /api/v1/evals/run`.
- **Consumer:** `DiscoveryEvalView.tsx` via `App.tsx`.
- **Status:** **WIRED**.

---

## 2. TypeScript Interface vs. Backend Pydantic Schema Comparison

Comparison of `frontend/src/types/intentlock.ts` against `backend/app/schemas.py` and `backend/app/main.py`:

| TypeScript Interface (`intentlock.ts`) | Backend Schema / Dict (`schemas.py` / `main.py`) | Alignment Status | Notes / Discrepancies |
| :--- | :--- | :---: | :--- |
| `Persona` | `PersonaOut` | **MATCH** | All required fields (`id`, `name`, `email`, `role`, `department`, `avatar_badge`) match. |
| `SwitchPersonaResponse` | `SwitchPersonaResponse` | **MATCH** | Exact match (`access_token`, `token_type`, `expires_in_seconds`, `persona`). |
| `Product` | `ProductOut` | **MATCH** | Exact match on all 11 fields. |
| `CartLineItem` | `CartLineItemOut` | **MATCH** | Exact match (`sku`, `product_name`, `pack_size_desc`, `unit_price_cents`, `unit_price_usd`, `quantity`, `line_total_cents`, `line_total_usd`, `selection_rationale`, `headcount_math`). |
| `ApprovalLock` | `ApprovalLockOut` | **MATCH** | Exact match (`id`, `request_id`, `cart_version_id`, `approver_id`, `approver_name`, `decision`, `comment`, `intent_hash`, `approval_signature`, `issued_at`, `expires_at`, `is_expired`). |
| `PayPalOrder` | `PayPalOrderOut` + `create_paypal_order_endpoint` dict | **PARTIAL** | Backend `PayPalOrderRecord` stores `raw_create_response_json` and `raw_capture_response_json` (which contain `_mcp_trace`), but `_serialize_paypal_order()` (`main.py:231`) does **not** include `mcp_trace` or `order_payload` on `PayPalOrderOut`. Thus `requestDetail.paypal_orders` lacks `mcp_trace` when loaded via `GET /api/v1/requests/{id}`. |
| `ReconciliationRecord` | `ReconciliationOut` | **MATCH** | All 6 boolean invariant flags, cent amounts, hashes, `discrepancy_details`, `evidence_bundle_sha256`, and `evidence_bundle` match. |
| `CartVersion` | `CartVersionOut` | **MATCH** | All fields including `llm_provider_used`, `llm_model_used`, `llm_failover_hops`, `llm_latency_ms`, `canonical_payload_json`, `intent_hash`, `line_items`, `approval_lock` match. |
| `AuditEvent` | `AuditEventOut` | **MATCH** | Exact match (`id`, `event_uid`, `request_id`, `cart_version_id`, `actor_id`, `actor_role`, `event_type`, `summary`, `metadata`, `prev_event_hash`, `event_hash`, `created_at`). |
| `PurchaseRequestSummary` | `PurchaseRequestSummaryOut` | **MATCH** | Exact match. |
| `PurchaseRequestDetail` | `PurchaseRequestDetailOut` | **MATCH** | Exact match (`active_version`, `versions`, `approval_locks`, `paypal_orders`, `reconciliations`, `audit_events`). |
| `TamperSimulationResult` | `TamperSimulationOut` | **MATCH** | Exact match. |
| `CoordinatorInterview` | `CoordinatorInterviewOut` | **MATCH** | Exact match. |
| `EvalSuiteRun` & `EvalScenarioResult` | `EvalSuiteRunOut` & `EvalScenarioResultOut` | **MATCH** | Exact match. |
| `LLMStatusResponse` | `_build_llm_and_paypal_status_response()` | **PARTIAL** | Backend returns `simulate_primary_failure`, `any_live_api_key_configured`, and `paypal_sandbox.client_id_preview` / `execution_mode_active` / `mcp_tools`, which should be typed on `LLMStatusResponse`. |

---

## 3. PayPal Sandbox & MCP Trace Integration Audit

### 3.1 Dynamic `paypal_client_id` Propagation (`LLMRouterConfigModal` → `BuyerCheckoutWorkspace`)
- **How it works today:**
  1. When the user enters `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in `.env` or submits them in `LLMRouterConfigModal`, `POST /api/v1/llm/keys` calls `paypal_mcp_service.set_runtime_paypal_keys()` and returns `_build_llm_and_paypal_status_response()`.
  2. In `main.py:517-530`, `cid, _ = paypal_mcp_service.get_active_paypal_credentials()` is injected into `paypal_sandbox.client_id`.
  3. `App.tsx:541-542` updates `llmStatus` state (`setLlmStatus(updated)`), and passes `paypalClientId={llmStatus?.paypal_sandbox?.client_id}` to `BuyerCheckoutWorkspace` (`App.tsx:966`).
  4. `BuyerCheckoutWorkspace.tsx:486-512` conditionally renders `<PayPalScriptProvider options={{ clientId: paypalClientId, currency: 'USD', intent: 'capture' }}>` and `<PayPalButtons ... />` when `paypalClientId && paypalClientId !== 'sb'`.
- **Issue Found (Gap 7 — `PayPalScriptProvider` Remounting on Key Change):**
  - `@paypal/react-paypal-js` `PayPalScriptProvider` does not automatically reload the PayPal JS SDK script if `options.clientId` changes after initial mount unless a React `key={paypalClientId}` prop is placed on `<PayPalScriptProvider key={paypalClientId} ...>`. Adding `key={paypalClientId}` guarantees that updating the PayPal Client ID at runtime immediately re-initializes the PayPal JS SDK without a page refresh or rebuild.
  - Additionally, when no live `paypalClientId` is configured yet, `BuyerCheckoutWorkspace` Option B hides the PayPal SDK section silently. Showing a helpful note in Option B (with a 1-click button to open the PayPal Sandbox Credentials modal or use the built-in PayPal MCP Sandbox buttons) makes the experience crystal-clear for judges.

### 3.2 PayPal MCP Trace Visibility in Checkout & Reconciliation Views
- **Backend Generation (`paypal_mcp_service.py`):**
  - `create_paypal_sandbox_order` (`paypal_mcp_service.py:344, 405`) and `capture_paypal_sandbox_order` (`paypal_mcp_service.py:570, 654`) construct rich `_mcp_trace` objects containing:
    - `mcp_tool_name` (`paypal_create_order`, `paypal_capture_order`, `paypal_get_order_details`)
    - `transport` (`PAYPAL_SANDBOX_ORDERS_V2_LIVE`, `PAYPAL_MCP_SANDBOX_BRIDGE`, `PAYPAL_SANDBOX_LIVE_ORDER_VERIFIED_PLUS_MCP_CAPTURE`)
    - `endpoint` (`POST https://api-m.sandbox.paypal.com/v2/checkout/orders...`)
    - `paypal_request_id` (deterministic idempotency key)
    - `latency_ms`
    - `invoked_at_utc`
- **Issue Found (Gap 8 — MCP Trace Not Surfaced in `PayPalOrderOut`, `BuyerCheckoutWorkspace.tsx`, or `ReconciliationAuditView.tsx`):**
  1. `_serialize_paypal_order` (`main.py:231`) does not extract `_mcp_trace` from `po.raw_create_response_json` / `po.raw_capture_response_json` into `PayPalOrderOut`.
  2. In `BuyerCheckoutWorkspace.tsx`, Option B shows `paypal_order_id` and `paypal_status`, but does **not** display the PayPal MCP Tool Trace (`mcp_tool_name`, `transport`, `paypal_request_id`, `custom_id = intent_hash`, `invoice_id`, `execution_mode`).
  3. In `ReconciliationAuditView.tsx`, `reconciliation.evidence_bundle.mcp_tool_trace` is buried inside the raw JSON collapse and is not surfaced as a dedicated **PayPal Orders v2 & MCP Protocol Trace Card**. Surfacing `mcp_tool_name`, `transport`, `paypal_request_id`, and `custom_id == intent_hash` in both `BuyerCheckoutWorkspace.tsx` and `ReconciliationAuditView.tsx` directly proves the PayPal MCP + Orders v2 integration to judges.

---

## 4. P1 Scope Audit (`usable control library`, `optional MCP adapter`, `larger evaluation suite`)

Inspecting `backend/app/` against the P1 scope items mentioned in the prompt:
1. **Usable Control Library (`backend/app/intentlock_core/`):**
   - Currently, the cryptographic canonicalization (`cart_hash_service.py`), 8 deterministic guardrails (`guardrails.py`), HMAC approval lock verification, and 6-point reconciliation verifier are coupled to `backend/app/services/` and SQLAlchemy ORM models.
   - **Recommendation:** Create a clean, standalone, zero-ORM-dependency control library package at `backend/app/intentlock_core/` (`__init__.py`, `controls.py`) that exposes a reusable `IntentLockControlPlane` / functional API (`canonicalize_cart`, `compute_intent_hash`, `mint_approval_lock`, `verify_checkout_gate`, `verify_reconciliation_invariants`, `enforce_catalog_grounding`, `scrub_prompt_injection`) so any external agent framework (LangChain, CrewAI, AutoGen, custom FastAPI services) can import `from app.intentlock_core import ...` directly.
2. **Optional MCP Adapter (`backend/app/mcp_adapter.py`):**
   - Currently, `paypal_mcp_service.py` defines `PAYPAL_MCP_TOOL_DEFINITIONS` (3 PayPal tools), and `main.py` has no `/api/v1/mcp/tools` or `/api/v1/mcp/invoke` JSON-RPC / REST adapter endpoint, nor a standalone `backend/app/mcp_adapter.py` module.
   - **Recommendation:** Create `backend/app/mcp_adapter.py` implementing an MCP-compliant tool server/adapter that exposes both IntentLock Control Tools (`intentlock_propose_cart`, `intentlock_verify_approval_lock`, `intentlock_reconcile_order`) and PayPal Sandbox MCP Tools (`paypal_create_order`, `paypal_get_order_details`, `paypal_capture_order`), and mount `GET /api/v1/mcp/tools` and `POST /api/v1/mcp/invoke` in `backend/app/main.py`.
3. **Larger Evaluation Suite (`backend/app/services/eval_service.py`):**
   - Currently, `eval_service.py` runs 12 scenarios (`EVAL-01` through `EVAL-12`). Note that the docstring at `eval_service.py:83` still says `"Executes the 10-scenario Golden Benchmark..."` even though there are 12 scenarios.
   - **Recommendation:** Expand the evaluation suite in `eval_service.py` to **15 comprehensive scenarios** (`EVAL-01` through `EVAL-15`), adding:
     - `EVAL-13`: **PayPal 6-Invariant Reconciliation Mismatch Detection** (simulating a tampered PayPal `custom_id` or under-captured cent amount and verifying `MISMATCH_BLOCKED` verdict).
     - `EVAL-14`: **PayPal MCP Adapter Tool Schema & Invocation Verification** (verifying `mcp_adapter` tool discovery and deterministic `paypal_create_order` custom_id binding).
     - `EVAL-15`: **Standalone `intentlock_core` Control Library Contract Test** (verifying zero-ORM canonical hash, HMAC lock, and gate verification).

---

## 5. Prioritized Wave 2 Integration Enhancement Checklist

1. **Backend — `PayPalOrderOut` & MCP Trace Serialization (`backend/app/schemas.py`, `backend/app/main.py`):**
   - Add `mcp_trace: Optional[dict[str, Any]] = None` and `order_payload: Optional[dict[str, Any]] = None` to `PayPalOrderOut` in `schemas.py` and populate them in `_serialize_paypal_order()` (`main.py`) from `raw_capture_response_json` / `raw_create_response_json`.
2. **Backend — Sub-Minute TTL Support for Demo Expiry Test Mode (`backend/app/main.py`, `backend/app/services/approval_service.py`):**
   - Honor `approval_ttl_seconds` in `approve_cart_version_endpoint` and `approval_service.approve_cart_version` so selecting `"5 Seconds (Demo Expiry Test Mode)"` sets `expires_at = issued_at + timedelta(seconds=5)` instead of rounding up to 60 seconds.
3. **Backend — P1 Usable Control Library (`backend/app/intentlock_core/`):**
   - Create `backend/app/intentlock_core/__init__.py` and `backend/app/intentlock_core/controls.py` providing a clean, framework-agnostic Python control library for RFC 8785 cart hashing, HMAC lock signing/verification, G-01–G-08 guardrail checks, and 6-point PayPal reconciliation.
4. **Backend — P1 MCP Adapter (`backend/app/mcp_adapter.py` & `backend/app/main.py`):**
   - Create `backend/app/mcp_adapter.py` exposing MCP tool definitions and JSON-RPC / REST tool dispatch (`list_mcp_tools()`, `call_mcp_tool()`), and wire `GET /api/v1/mcp/tools` and `POST /api/v1/mcp/invoke` in `main.py`.
5. **Backend — Expanded 15-Scenario Evaluation Suite (`backend/app/services/eval_service.py`):**
   - Add `EVAL-13` (6-Invariant Reconciliation Mismatch Detection), `EVAL-14` (MCP Adapter Tool Invocation & `custom_id` Binding), and `EVAL-15` (`intentlock_core` Control Library Verification), bringing the benchmark suite to 15 scenarios.
6. **Frontend — TypeScript Interfaces (`frontend/src/types/intentlock.ts`):**
   - Add `mcp_trace` and `order_payload` to `PayPalOrder`, and add `simulate_primary_failure`, `client_id_preview`, `execution_mode_active`, and `mcp_tools` to `LLMStatusResponse`.
7. **Frontend — `CoordinatorWorkspace.tsx` & `App.tsx` Enhancements:**
   - Render the **Canonical JSON Inspector Modal** when `showCanonicalModal` is true in `CoordinatorWorkspace.tsx`.
   - Wire `onQuickStartWithSku(sku, productName)` in `App.tsx` → `CoordinatorWorkspace.tsx` so clicking **"Request"** on any SKU in `MerchantCatalogView` switches to Step 1 and pre-fills a request for that SKU.
   - Refresh `apiClient.getCatalog()` in `App.tsx` after PayPal order capture so decremented stock counts reflect immediately in `MerchantCatalogView`.
8. **Frontend — `BuyerCheckoutWorkspace.tsx`, `ReconciliationAuditView.tsx`, & `LLMRouterConfigModal.tsx`:**
   - Add `key={paypalClientId}` to `<PayPalScriptProvider>` in `BuyerCheckoutWorkspace.tsx` so runtime PayPal Client ID updates re-render the live PayPal JS SDK buttons immediately without a rebuild.
   - Render a clear **PayPal MCP & Orders v2 Trace Card** (`mcp_tool_name`, `transport`, `paypal_request_id`, `custom_id = intent_hash`, `execution_mode`) in both `BuyerCheckoutWorkspace.tsx` and `ReconciliationAuditView.tsx`.
   - Sync `simulateFailover` state with `llmStatus?.simulate_primary_failure` and display live PayPal Sandbox connection status (`client_id_preview`, `execution_mode_active`) in `LLMRouterConfigModal.tsx`.
