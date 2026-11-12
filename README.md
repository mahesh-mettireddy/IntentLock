# IntentLock — Approval-Aware Agentic Purchasing with Cryptographic Intent Locking & PayPal Sandbox MCP

> **PayPal AI Hackathon 2026 ("Build What's Next with PayPal and AI") Submission**  
> **Live Cloud Deployment:** **[https://intentlock-unys.onrender.com/](https://intentlock-unys.onrender.com/)**  
> **License:** [MIT](file:///d:/Projects/IntentLock/LICENSE) | **Merchant Scope:** Single Verified Merchant (`Acme Workspace Supplies`, `USD` only, 15 Synthetic SKUs) | **Payment Rail:** PayPal Sandbox Orders v2 REST API + PayPal Agent Toolkit MCP (`@paypal/agent-toolkit`) + PayPal JS SDK

---

## 0. The Core Problem We Solve (And How to Try It Live in 60 Seconds)

### The Problem in Agentic Commerce
Businesses want AI agents to turn messy team supply requests into ready-to-buy carts, **but they cannot trust an AI agent with direct PayPal payment authority**:
1. **AI Hallucinations & Pack-Size Math Errors:** An AI might pick individual units instead of multi-packs, exceed stock, or hallucinate unit prices.
2. **No Separation of Duties:** A requester or AI agent should never be able to self-approve corporate spend.
3. **Post-Approval Cart Drift (`TOCTOU` — Time-of-Check to Time-of-Use):** Even if a manager reviews a cart, if a single item, quantity, or cent changes between manager approval and payment execution, unauthorized money leaves the account.

### How IntentLock Fixes It (Try Live at [https://intentlock-unys.onrender.com/](https://intentlock-unys.onrender.com/))
1. **Step 1 — Build Cart (`Alice Chen · Coordinator`):** Select a preset scenario or type a supply need and click **Build Cart Proposal with AI**. The unprivileged AI proposes SKUs from the 15-item `Acme Workspace Supplies` catalog with explicit pack-size math. Click **Submit Cart for Manager Approval** (automatically switches you to Step 2 as Manager Bob).
2. **Step 2 — Manager Approval Lock (`Bob Martinez · Approver`):** Review the cart and click **Approve & Lock Cart**. IntentLock serializes the cart via **RFC 8785 Canonical JSON**, computes a deterministic **`SHA-256 intent_hash`**, and signs an **`HMAC-SHA256 ApprovalLock`**. Click **Continue to Step 3: PayPal Checkout** (automatically switches you to Buyer Charlie).
3. **Step 3 — Verified PayPal Sandbox Checkout (`Charlie Kim · Buyer`):** Click **One-Click PayPal Sandbox Order + Capture** (or use the interactive **PayPal JS SDK** button). IntentLock recomputes the cart's `SHA-256` hash right before calling **PayPal Sandbox Orders v2** (`/v2/checkout/orders`), binding `purchase_units[0].custom_id = intent_hash` inside the live PayPal order.
   * *Bonus:* Open the **"Test Post-Approval Tamper & Guardrail Enforcement"** drawer at the bottom of Step 3 to see how any post-approval price hike or item drift is deterministically blocked (`409 STALE_APPROVAL_HASH_MISMATCH`) before PayPal is ever called.

---

## 1. What is IntentLock?

**IntentLock** is an interactive, approval-aware B2B purchasing application for small teams buying routine supplies from a single verified merchant (**Acme Workspace Supplies**).

Instead of giving an AI agent autonomous spending credentials—or letting a mutable shopping cart drift between managerial sign-off and checkout (**TOCTOU: Time-of-Check to Time-of-Use cart drift**)—IntentLock enforces a strict, cryptographically verifiable procurement pipeline:

1. **Translate & Explain (Unprivileged AI Agent):** Translates informal team supply needs (e.g., *"We have 4 new engineers starting Monday and the breakroom is out of dark roast coffee, oat milk, and dry-erase markers; keep it under \$450"*) into a complete, inventory-checked cart from the 15-item synthetic catalog, explaining every SKU selection and headcount/pack-size math calculation.
2. **Coordinate & Revise (`Coordinator` — Alice Chen):** Reviews the proposed cart, revises quantities or prompts the agent for adjustments (minting immutable Cart Versions $v_1 \rightarrow v_2$), and submits a fixed version for approval. **Blocked by Separation of Duties (`G-04`) from approving her own request.**
3. **Review & Cryptographically Lock (`Approver` — Bob Martinez):** Inspects the fixed Cart Version $v_n$, reviews the visual diff ($v_1 \rightarrow v_2$) and AI rationale, and clicks **Approve & Lock Intent**—sealing the cart's **RFC 8785 Canonical JSON SHA-256 `intent_hash`** with an **HMAC-SHA256 `approval_signature`** and a strict UTC expiry timestamp (`expires_at`).
4. **Execute Only the Approved Intent (`Buyer / Operator` — Charlie Davis):** Initiates checkout through **PayPal Sandbox Orders v2 REST API & PayPal MCP Server Toolkit**, binding `custom_id = intent_hash` and `invoice_id = IL-{cart_version_id}` into a single-purchase-unit, full-capture (`intent: "CAPTURE"`) USD order.
5. **6-Invariant Automated Cryptographic Reconciliation & Evidence Bundle:** Re-queries the authoritative PayPal Sandbox Order (`GET /v2/checkout/orders/{id}`) and verifies:
   - `Order Status == COMPLETED`
   - `Capture Status == COMPLETED`
   - `Currency == USD`
   - `Captured Cents == Approved Cents`
   - `PayPal custom_id == Approved SHA-256 intent_hash`
   - `Single Purchase Unit (len(purchase_units) == 1)`
   Operators can trigger a read-only PayPal reconciliation sync for uncertain transactions, but **cannot fabricate approval or manually mark payment provider success (`G-08`)**.

---

## 2. Problem Hypothesis & 3-Coordinator Discovery Benchmark

Before expanding scope, we evaluated recent supply purchases across **3 team coordinators** (`COORD-INT-01`..`03`, accessible interactively in the app's **Discovery Study & Eval Suite** tab and documented in [`docs/09-EVALUATION-STRATEGY.md`](file:///d:/Projects/IntentLock/docs/09-EVALUATION-STRATEGY.md)):

| Metric | Manual Baseline (3-Coordinator Avg) | IntentLock Workflow | Improvement |
| :--- | :--- | :--- | :--- |
| **Request-to-Cart Translation Time** | `14.2 minutes` | `38.4 seconds` | **95.5% faster** |
| **SKU / Pack-Size Math Corrections** | `2.33 corrections / order` (23.3% error rate) | `0.0 corrections` (deterministic rules) | **100% reduction** |
| **Post-Approval Cart Drift (TOCTOU)** | `33.3% of orders` diverged after manager review | `0.0%` (blocked by SHA-256 `intent_hash` lock) | **100% eliminated** |

---

## 3. Multi-LLM Automatic Failover Router (Free-Tier Resilient)

IntentLock features a provider-agnostic **Multi-LLM Automatic Failover Router** ([`backend/app/services/llm_router.py`](file:///d:/Projects/IntentLock/backend/app/services/llm_router.py)) that cascades across free-tier LLM APIs in priority order whenever a provider hits quota expiration, rate limits (`HTTP 429` / `RESOURCE_EXHAUSTED`), or timeouts:

1. **Tier 1 — Google Gemini Free Tier (`GEMINI_API_KEY`):** `gemini-2.5-flash` $\rightarrow$ `gemini-2.0-flash` ([Get free key at Google AI Studio](https://aistudio.google.com/apikey))
2. **Tier 2 — Groq Cloud Free Tier (`GROQ_API_KEY`):** `llama-3.3-70b-versatile` ([Get free key at Groq Console](https://console.groq.com/keys))
3. **Tier 3 — xAI Grok API (`XAI_API_KEY`):** `grok-2-latest` ([Get key at xAI Console](https://console.x.ai))
4. **Tier 4 — OpenRouter Free Models (`OPENROUTER_API_KEY`) / OpenAI (`OPENAI_API_KEY`):** `meta-llama/llama-3.3-70b-instruct:free` ([Get free key at OpenRouter](https://openrouter.ai/keys))

You can configure keys via `.env` **or paste them live at runtime** using the **"AI Router & PayPal Config"** button in the top navigation bar.

---

## 4. Complete Engineering & Security Specification Suite (`docs/`)

All 16 architectural, product, payment, security, and operational specifications are located in [`docs/`](file:///d:/Projects/IntentLock/docs):

1. [`docs/01-PRD.md`](file:///d:/Projects/IntentLock/docs/01-PRD.md) — Product Requirements Document, Personas, Authority Matrix & Non-Goals
2. [`docs/02-TRD.md`](file:///d:/Projects/IntentLock/docs/02-TRD.md) — Technical Requirements Document, Multi-LLM Failover Router & Precision Rules
3. [`docs/03-ARCHITECTURE.md`](file:///d:/Projects/IntentLock/docs/03-ARCHITECTURE.md) — System Architecture, Mermaid Sequence/Flow Diagrams & 10-Table ER Schema
4. [`docs/04-UI-UX-SPEC.md`](file:///d:/Projects/IntentLock/docs/04-UI-UX-SPEC.md) — Interactive Purchasing & Approval Application UI/UX Specification
5. [`docs/05-PAYMENT-LIFECYCLE.md`](file:///d:/Projects/IntentLock/docs/05-PAYMENT-LIFECYCLE.md) — PayPal Sandbox Orders v2 & PayPal MCP Server Payment Lifecycle Specification
6. [`docs/06-SECURITY-THREAT-MODEL.md`](file:///d:/Projects/IntentLock/docs/06-SECURITY-THREAT-MODEL.md) — STRIDE & OWASP Agentic LLM Threat Model & Red-Team Verification Suite
7. [`docs/07-AGENT-HARNESS.md`](file:///d:/Projects/IntentLock/docs/07-AGENT-HARNESS.md) — Unprivileged Agent Harness & Multi-LLM Failover Orchestration
8. [`docs/08-GUARDRAILS.md`](file:///d:/Projects/IntentLock/docs/08-GUARDRAILS.md) — 4-Layer Defense-in-Depth Guardrails (`G-01` through `G-08`)
9. [`docs/09-EVALUATION-STRATEGY.md`](file:///d:/Projects/IntentLock/docs/09-EVALUATION-STRATEGY.md) — 3-Coordinator Discovery Study & 12-Scenario Golden Evaluation Benchmark
10. [`docs/10-API-DATA-CONTRACTS.md`](file:///d:/Projects/IntentLock/docs/10-API-DATA-CONTRACTS.md) — REST API Endpoints & Strict Pydantic v2 Data Contracts
11. [`docs/11-OPERATIONS-RUNBOOK.md`](file:///d:/Projects/IntentLock/docs/11-OPERATIONS-RUNBOOK.md) — Operations & Incident Runbook (`SOP-01` through `SOP-04`)
12. [`docs/12-PRIVACY-COMPLIANCE.md`](file:///d:/Projects/IntentLock/docs/12-PRIVACY-COMPLIANCE.md) — Zero-PAN Privacy, Pre-LLM PII Redaction & SOX/SOC 2 Procurement Controls
13. [`docs/13-REVIEW-DECISION-SOURCES.md`](file:///d:/Projects/IntentLock/docs/13-REVIEW-DECISION-SOURCES.md) — Architecture Decision Records (`ADR-001` through `ADR-007`)
14. [`docs/14-STATE-MACHINE-AND-HASH-SPEC.md`](file:///d:/Projects/IntentLock/docs/14-STATE-MACHINE-AND-HASH-SPEC.md) — Formal State Machine & RFC 8785 Canonical JSON SHA-256 Hash Specification
15. [`docs/15-SYNTHETIC-MERCHANT-CATALOG.md`](file:///d:/Projects/IntentLock/docs/15-SYNTHETIC-MERCHANT-CATALOG.md) — Acme Workspace Supplies 15-Product Synthetic USD Catalog Specification
16. [`docs/16-IMPLEMENTATION-AND-MULTI-AGENT-PLAN.md`](file:///d:/Projects/IntentLock/docs/16-IMPLEMENTATION-AND-MULTI-AGENT-PLAN.md) — Module Segregation & Parallel Multi-Agent Implementation Blueprint

---

## 5. Quickstart Instructions

### Option A: One-Command Startup (Windows PowerShell)
```powershell
.\start-dev.ps1
```
This launches both the FastAPI backend (`http://127.0.0.1:8000`) and the React + Vite interactive web application (`http://localhost:5173`).

### Option B: Manual Startup

#### 1. Configure Environment (Optional — Keys can also be pasted live in the UI)
```powershell
Copy-Item .env.example .env
# Edit .env to add GEMINI_API_KEY, GROQ_API_KEY, XAI_API_KEY, and PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET
```

#### 2. Start Backend (FastAPI + SQLite WAL)
```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 3. Start Frontend (React 18 + Vite + TypeScript + Tailwind CSS)
```powershell
cd frontend
npm install
npm run dev
```
Open **`http://localhost:5173`** in your browser.

---

## 6. Running the Automated E2E & Red-Team Security Suite

```powershell
cd backend
python -m pytest tests/test_intentlock_e2e.py -v
```
This verifies:
- Health, Multi-LLM Failover Router status, and runtime API key updates
- 15-item USD synthetic catalog (`SKU-001`..`SKU-015`)
- Persona JWT RBAC switching (`COORDINATOR`, `APPROVER`, `BUYER`)
- Full end-to-end happy path: Proposal ($v_1$) $\rightarrow$ Quantity revision ($v_2$) $\rightarrow$ Submission $\rightarrow$ Self-Approval Block (`G-04` HTTP 403) $\rightarrow$ Manager Approval & SHA-256 Lock $\rightarrow$ PayPal Sandbox Order Creation (`custom_id == intent_hash`) $\rightarrow$ Full Capture $\rightarrow$ 6-Invariant Automated Reconciliation (`VERIFIED_MATCH`) $\rightarrow$ Signed Evidence Bundle & Hash-Chained Audit Timeline
- All 5 Live Security Tamper Simulations (`CART_DRIFT_TOCTOU`, `SELF_APPROVAL_SOD`, `EXPIRED_APPROVAL_REPLAY`, `MANUAL_PROVIDER_OVERRIDE`, `PROMPT_INJECTION_PRICE_OVERRIDE`)
- 3 Coordinator Discovery Interviews & 12-Scenario Golden Evaluation Suite (`100%` pass rate)
