# IntentLock — AI Agent Harness & Evaluation Coverage Audit Report

**Audit Date:** 2026-11-12  
**Audited Subsystems:**
- [`backend/app/services/llm_router.py`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py)
- [`backend/app/services/agent_service.py`](file:///d:/Projects/IntentLock/backend/app/services/agent_service.py)
- [`backend/app/services/guardrails.py`](file:///d:/Projects/IntentLock/backend/app/services/guardrails.py)
- [`backend/app/services/eval_service.py`](file:///d:/Projects/IntentLock/backend/app/services/eval_service.py)
- [`backend/app/schemas.py`](file:///d:/Projects/IntentLock/backend/app/schemas.py) & [`backend/app/main.py`](file:///d:/Projects/IntentLock/backend/app/main.py)

**Normative Specifications Compared:**
- [`docs/07-AGENT-HARNESS.md`](file:///d:/Projects/IntentLock/docs/07-AGENT-HARNESS.md)
- [`docs/09-EVALUATION-STRATEGY.md`](file:///d:/Projects/IntentLock/docs/09-EVALUATION-STRATEGY.md)

**Overall Readiness Verdict:** **NEEDS TARGETED WAVE 2 ENHANCEMENTS (84/100)**

---

## 1. Executive Summary

The core **Unprivileged AI Proposer** boundary, **Multi-Provider LLM Failover Router**, **8 Deterministic Security Guardrails (`G-01`..`G-08`)**, and **12-Scenario Evaluation Suite** are implemented and functional. However, comparing the implementation line-by-line against `07-AGENT-HARNESS.md`, `09-EVALUATION-STRATEGY.md`, and the audit requirements surfaced **5 specific gaps** that should be closed in Wave 2 so judges and evaluators can test live multi-LLM failover and inspect all 6 canonical evaluation metrics.

---

## 2. Audit Area 1: Multi-LLM Automatic Failover Router (`llm_router.py` vs. `07-AGENT-HARNESS.md`)

### 2.1 Provider Cascade Order & Exception Handling
In [`MultiProviderLLMRouter._get_provider_definitions`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py#L136-L188) and [`generate_cart_proposal`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py#L266-L451):
- **Priority Chain Verified (`COVERED`):**
  1. **Tier 1 (`google_gemini`):** `gemini-2.5-flash` $\rightarrow$ intra-provider fallback to `gemini-2.0-flash` ([`_call_google_gemini`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py#L457-L514)).
  2. **Tier 2 (`groq_cloud`):** `llama-3.3-70b-versatile` (configured with `fallback_model="llama-3.1-8b-instant"`).
  3. **Tier 3 (`xai_grok`):** `grok-2-latest` (configured with `fallback_model="grok-2-latest"`).
  4. **Tier 4 (`openrouter_free`):** `meta-llama/llama-3.3-70b-instruct:free` $\rightarrow$ intra-provider fallback to `google/gemini-2.0-flash-exp:free` ([`_call_openrouter_with_fallback`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py#L516-L562)).
  5. **Tier 5 (`openai`):** `gpt-4o-mini`.
- **Exception Classification & Circuit Breaker Cooldowns (`COVERED`):**
  - [`_classify_exception`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py#L610-L631) accurately classifies `httpx.TimeoutException` (`>12.0s` $\rightarrow$ `30s` cooldown), `HTTP 429` rate limit (`60s` cooldown), `HTTP 429` quota/billing exhaustion (`900s` cooldown), `HTTP 402` credit exhaustion (`900s` cooldown), `HTTP 401/403` auth errors (`300s` cooldown), `HTTP 5xx` upstream outages (`30s` cooldown), and JSON/schema errors (`15s` cooldown).

### 2.2 Gaps Identified in `llm_router.py` & `main.py`

| Gap ID | Severity | Location | Finding |
| :--- | :---: | :--- | :--- |
| **`GAP-LLM-01`** | **HIGH (Wave 2 Action)** | [`backend/app/main.py`](file:///d:/Projects/IntentLock/backend/app/main.py#L537-L595) | **Missing `POST /api/v1/llm/test-failover` Endpoint:** While `main.py` has `/api/v1/llm/status` and `/api/v1/llm/keys`, there is **no dedicated `POST /api/v1/llm/test-failover` endpoint** (or UI trigger button in [`LLMRouterConfigModal.tsx`](file:///d:/Projects/IntentLock/frontend/src/components/LLMRouterConfigModal.tsx)) that simulates Provider 1 (`google_gemini`) hitting `HTTP 429 RESOURCE_EXHAUSTED` and returns a live multi-hop failover execution trace (`failover_trace`, `failover_hops`, `provider_used`, `model_used`, `latency_ms`, grounded cart preview, and recorded `AuditEvent`) for judges to verify on demand. |
| **`GAP-LLM-02`** | **MEDIUM (Wave 2 Action)** | [`backend/app/services/llm_router.py`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py#L324-L360) | **Groq Intra-Provider Fallback & Single-Key Failover Simulation:** In `_get_provider_definitions`, `groq_cloud` defines `"fallback_model": "llama-3.1-8b-instant"`, but `_call_openai_compatible` only calls `prov["primary_model"]` without trying `fallback_model` on 429/5xx. Furthermore, when `simulate_failover_providers=["google_gemini"]` is passed and **only** `GEMINI_API_KEY` (or 0 live keys) is configured in `.env`, the router should cleanly demonstrate hop 1 (`google_gemini` simulated `HTTP 429 RESOURCE_EXHAUSTED`) cascading to the next configured live provider (`groq_cloud` / `xai_grok` / `openrouter_free` / `openai`) OR to `google_gemini:gemini-2.0-flash` / `semantic_catalog_synthesizer` with `failover_hops >= 1` and explicit hop-by-hop telemetry. |
| **`GAP-LLM-03`** | **LOW (Wave 2 Action)** | [`backend/app/services/agent_service.py`](file:///d:/Projects/IntentLock/backend/app/services/agent_service.py#L292) | **Failover Hops Count on Intra-Provider Fallback:** In `llm_router.py:L384`, `failover_hops` is set to `idx` (the provider loop index) instead of counting failed attempts in `failover_trace` (`len(failover_trace) - 1`). If `gemini-2.5-flash` fails and `gemini-2.0-flash` succeeds via intra-provider fallback, `idx` is `0` even though 1 fallback hop occurred. Setting `failover_hops = len(failover_trace) - 1` fixes this. |

---

## 3. Audit Area 2: Evaluation Suite Coverage (`eval_service.py` vs. `09-EVALUATION-STRATEGY.md`)

### 3.1 Scenario Coverage (`EVAL-01` through `EVAL-12`)
- **All 12 Scenarios Present (`COVERED` with Doc/Order Alignment Note):**
  - Despite the stale docstring at [`eval_service.py:L83`](file:///d:/Projects/IntentLock/backend/app/services/eval_service.py#L83) saying *"Executes the 10-scenario Golden Benchmark"*, `run_golden_evaluation_suite` **does implement all 12 scenarios (`EVAL-01` through `EVAL-12`)**:
    - `EVAL-01`: 4-Engineer Onboarding Kit & Multi-Pack Ceiling Math (`SKU-005`x4, `SKU-006`x1, `SKU-009`x4, `SKU-012`x4 = `$302.50`)
    - `EVAL-02`: Weekly Breakroom Restock Under `$120` Strict Budget Ceiling (`$114.00 <= $120.00`)
    - `EVAL-03`: Workshop & Breakroom Provisioning for 20 Attendees (`$208.50`)
    - `EVAL-04`: Adversarial Prompt Injection (`$0.01` Price Override, Self-Approval & PII Scrubbing — `G-01` & `G-03`)
    - `EVAL-05`: Low-Stock Boundary Cap on `SKU-015` (Request 8, Cap at 5 in stock — `G-02`)
    - `EVAL-06`: Out-of-Catalog Item Rejection (`"27-inch 4K Dell Monitors"` / `SKU-999-MONITOR` — `G-01`)
    - `EVAL-07`: Coordinator Self-Approval Separation of Duties Block (`G-04` `HTTP 403`)
    - `EVAL-08`: TOCTOU Post-Approval Cart Drift Block (`G-05` `HTTP 409`)
    - `EVAL-09`: Expired Approval Lock Replay Block (`G-06` `HTTP 409`)
    - `EVAL-10`: Multi-LLM Automatic Failover (`HTTP 429` on `google_gemini`) + Payment Scope & Anti-Fabrication (`G-07` & `G-08`)
    - `EVAL-11`: Multi-Turn Conversational Cart Revision ($v_1 \rightarrow v_2$, `$136.50`)
    - `EVAL-12`: RFC 8785 Canonical Hash Order-Invariance & PayPal `custom_id` Cryptographic Binding
  - **Note on `EVAL-06` Ambiguous Request Clarification (`09-EVALUATION-STRATEGY.md`):** In `09-EVALUATION-STRATEGY.md`, `EVAL-06` tests ambiguous strategy-session clarification questions, whereas `eval_service.py` replaced it with `EVAL-12` (RFC 8785 Canonical Hash Determinism & PayPal Binding). Including clarification question verification or documenting all 12 scenarios cleanly in the docstring is recommended.

### 3.2 Evaluation Metrics Coverage (6 Required Metrics Audit)

We audited [`eval_service.py:L736-L794`](file:///d:/Projects/IntentLock/backend/app/services/eval_service.py#L736-L794) and [`EvalSuiteRunOut` in `schemas.py:L359-L370`](file:///d:/Projects/IntentLock/backend/app/schemas.py#L359-L370) against the **6 required evaluation metrics**:

| Metric ID | Metric Name | Status in `eval_service.py` & `EvalSuiteRunOut` | Audit Finding |
| :--- | :--- | :---: | :--- |
| **`M1_SKU_F1`** | SKU Selection F1 Score | **PARTIAL** | Computed as `sku_f1_score`, but canonical key `M1_SKU_F1` / `metrics.M1_SKU_F1` is not exposed in `EvalSuiteRunOut`. |
| **`M2_QUANTITY_PACK_ACCURACY`** | Quantity & Pack-Size Math Accuracy | **PARTIAL** | Computed as `pack_math_accuracy_pct`, but canonical key `M2_QUANTITY_PACK_ACCURACY` is not exposed in `EvalSuiteRunOut`. |
| **`M3_PRICE_GROUNDING_INTEGRITY`** | SQLite Catalog Price Grounding Integrity | **MISSING (BLOCKER)** | **Not computed or returned** as a top-level metric in `eval_service.py` or `EvalSuiteRunOut`. Must verify that 100% of line items across all cart scenarios have `unit_price_cents == catalog[sku].unit_price_cents` and `line_total_cents == unit_price_cents * quantity`. |
| **`M4_EXPLANATION_COMPLETENESS`** | Line-Item Rationale & Pack Math Completeness | **MISSING (BLOCKER)** | **Not computed or returned** in `eval_service.py` or `EvalSuiteRunOut`. Must verify that 100% of proposed line items have non-empty `selection_rationale` ($\ge 10$ chars) and `headcount_math` ($\ge 5$ chars). |
| **`M5_GUARDRAIL_ENFORCEMENT_RATE`** | Guardrail `G-01`–`G-08` & Failover Enforcement Rate | **PARTIAL** | Computed as `guardrail_enforcement_pct` and `failover_recovery_pct`, but canonical key `M5_GUARDRAIL_ENFORCEMENT_RATE` is not exposed in `EvalSuiteRunOut`. |
| **`M6_E2E_LATENCY_P95`** | 95th Percentile End-to-End Scenario Latency (ms) | **MISSING (BLOCKER)** | **Not computed or returned** in `eval_service.py` or `EvalSuiteRunOut`! Individual scenarios record `latency_ms`, but P95 latency (`e2e_latency_p95_ms` / `M6_E2E_LATENCY_P95`) is never aggregated or returned. |

---

## 4. Exact Actionable Remediation Plan for Wave 2

### Action Item 1: Add `POST /api/v1/llm/test-failover` Endpoint & Router Improvements (`llm_router.py`, `schemas.py`, `main.py`)
1. **In [`backend/app/services/llm_router.py`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py):**
   - Fix `failover_hops` calculation at line 384 to `len(failover_trace) - 1` so both intra-provider (`gemini-2.5-flash` $\rightarrow$ `gemini-2.0-flash`) and cross-provider (`google_gemini` $\rightarrow$ `groq_cloud` $\rightarrow$ `xai_grok` $\rightarrow$ `openrouter_free` $\rightarrow$ `openai`) hops are accurately counted.
   - Add intra-provider fallback support for `groq_cloud` (`llama-3.3-70b-versatile` $\rightarrow$ `llama-3.1-8b-instant`) and `xai_grok` (`grok-2-latest` $\rightarrow$ `grok-2-mini`) matching `_call_openrouter_with_fallback`.
   - Add a dedicated method `await llm_router.run_failover_drill(prompt, simulate_fail_providers, catalog_items)` that forces Provider 1 (`google_gemini`) to raise `HTTP 429 RESOURCE_EXHAUSTED`, cascades to the next available provider (e.g., `groq_cloud` / `xai_grok` / `openrouter_free` / `openai`, or fallback synthesizer if no secondary key is set), captures the full hop-by-hop `failover_trace`, and restores circuit breaker state (or optionally keeps it tripped if requested).
2. **In [`backend/app/main.py`](file:///d:/Projects/IntentLock/backend/app/main.py) & [`backend/app/schemas.py`](file:///d:/Projects/IntentLock/backend/app/schemas.py):**
   - Add `POST /api/v1/llm/test-failover` accepting optional `{"prompt": "...", "simulate_fail_providers": ["google_gemini"], "trip_circuit_breaker": false}`.
   - Execute a live cart proposal through the router with `simulate_failover_providers=["google_gemini"]`, ground the resulting items via `enforce_catalog_grounding_and_pricing`, record an `AuditEvent` (`event_type="LLM_FAILOVER_DRILL_EXECUTED"`), and return:
     - `simulated_failed_providers`: `["google_gemini"]`
     - `Simulated HTTP 429 RESOURCE_EXHAUSTED` hop telemetry in `failover_trace`
     - `fulfilled_by_provider`, `fulfilled_by_model`, `failover_hops`, `total_latency_ms`
     - `grounded_items`, `total_amount_cents`, `total_amount_usd`
     - `audit_event_uid` and updated `router_status`.
3. **In Frontend ([`frontend/src/api/client.ts`](file:///d:/Projects/IntentLock/frontend/src/api/client.ts) & [`frontend/src/components/LLMRouterConfigModal.tsx`](file:///d:/Projects/IntentLock/frontend/src/components/LLMRouterConfigModal.tsx)):**
   - Add a **"Run Live HTTP 429 Failover Drill"** button inside `LLMRouterConfigModal.tsx` that calls `POST /api/v1/llm/test-failover` and renders the hop-by-hop telemetry trace (`Hop 1: google_gemini [HTTP 429 RESOURCE_EXHAUSTED] -> Hop 2: groq_cloud / fallback [SUCCESS]`) right in the modal.

### Action Item 2: Compute & Return All 6 Evaluation Metrics in `eval_service.py`, `schemas.py`, and `DiscoveryEvalView.tsx`
1. **In [`backend/app/services/eval_service.py`](file:///d:/Projects/IntentLock/backend/app/services/eval_service.py):**
   - Update docstring to accurately reflect all **12 Golden Benchmark Scenarios (`EVAL-01` through `EVAL-12`)**.
   - Track `price_grounding_hits: list[bool]` across all cart-producing scenarios (`EVAL-01`..`EVAL-06`, `EVAL-10`, `EVAL-11`) verifying every item's `unit_price_cents == catalog_map[sku].unit_price_cents` and `line_total_cents == unit_price_cents * quantity`.
   - Track `explanation_completeness_hits: list[bool]` across all cart-producing scenarios verifying every item has `len(selection_rationale.strip()) >= 10` and `len(headcount_math.strip()) >= 5`.
   - Compute P95 latency (`e2e_latency_p95_ms`) across all 12 scenario latencies (`sorted_latencies[int(math.ceil(0.95 * len(sorted_latencies))) - 1]`).
   - Populate both backward-compatible fields (`sku_f1_score`, `pack_math_accuracy_pct`, `guardrail_enforcement_pct`, `failover_recovery_pct`) AND the new fields + a canonical `metrics` dict containing all 6 keys:
     - `M1_SKU_F1`: `float` (e.g. `1.0`)
     - `M2_QUANTITY_PACK_ACCURACY`: `float` (`100.0`)
     - `M3_PRICE_GROUNDING_INTEGRITY`: `float` (`100.0`)
     - `M4_EXPLANATION_COMPLETENESS`: `float` (`100.0`)
     - `M5_GUARDRAIL_ENFORCEMENT_RATE`: `float` (`100.0`)
     - `M6_E2E_LATENCY_P95`: `float` (e.g. `<= 8000.0` ms)
2. **In [`backend/app/schemas.py`](file:///d:/Projects/IntentLock/backend/app/schemas.py) (`EvalSuiteRunOut`):**
   - Add fields:
     - `price_grounding_integrity_pct: float = 100.0`
     - `explanation_completeness_pct: float = 100.0`
     - `e2e_latency_p95_ms: float = 0.0`
     - `metrics: dict[str, float] = Field(default_factory=dict)` (with `M1_SKU_F1` .. `M6_E2E_LATENCY_P95`)
3. **In [`frontend/src/types/intentlock.ts`](file:///d:/Projects/IntentLock/frontend/src/types/intentlock.ts) & [`frontend/src/components/DiscoveryEvalView.tsx`](file:///d:/Projects/IntentLock/frontend/src/components/DiscoveryEvalView.tsx):**
   - Update `EvalSuiteRun` TypeScript interface and `DiscoveryEvalView.tsx` scorecard grid to display all **6 canonical metrics (`M1` through `M6`)** alongside the overall pass rate (`12/12 — 100%`).
4. **In [`backend/tests/test_intentlock_e2e.py`](file:///d:/Projects/IntentLock/backend/tests/test_intentlock_e2e.py):**
   - Add assertions verifying `POST /api/v1/llm/test-failover` and asserting that `POST /api/v1/evals/run` returns all 12 scenarios (`EVAL-01`..`EVAL-12`) and all 6 metrics (`M1_SKU_F1`, `M2_QUANTITY_PACK_ACCURACY`, `M3_PRICE_GROUNDING_INTEGRITY`, `M4_EXPLANATION_COMPLETENESS`, `M5_GUARDRAIL_ENFORCEMENT_RATE`, `M6_E2E_LATENCY_P95`).
