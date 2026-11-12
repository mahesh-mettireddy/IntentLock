# 04 — Interactive Application UI/UX Specification: IntentLock

| Document Metadata | Details |
| :--- | :--- |
| **Product Surface** | IntentLock Interactive Web Application (Desktop & Tablet Responsive) |
| **Design Paradigm** | High-Trust B2B Procurement & Cryptographic Checkout Application (Linear / Ramp / Stripe Checkout aesthetic) |
| **Anti-Pattern Explicitly Avoided** | Cluttered "AI Command Center" / Dark-Mode Hacker Telemetry Dashboard |
| **Tech Stack** | React 18 + Vite + TypeScript + Tailwind CSS + Lucide Icons + `@paypal/react-paypal-js` |

---

## 1. Design Philosophy: Purpose-Built Purchasing Application, Not a "Command Center"

IntentLock is designed for real small-team staff—**Operations Coordinators (Alice)**, **Department Managers / Approvers (Bob)**, and **Finance Buyers (Charlie)**—who need to turn a messy supply request into a verified, approved, and reconciled PayPal purchase in under two minutes.

### 1.1 Core UX Principles
1. **Workflow Clarity Over Telemetry Clutter:** Instead of overwhelming the screen with terminal logs or multi-agent graphs, the primary workspace follows a clean, linear 4-stage pipeline:
   $$\text{1. Request \& Propose } (v_n) \longrightarrow \text{2. Review \& Lock } (\text{SHA-256}) \longrightarrow \text{3. PayPal Checkout} \longrightarrow \text{4. Reconcile \& Evidence}$$
2. **Visible Cryptographic State Transitions:** The user can feel the difference between a **Mutable / Draft Proposal** (warm amber accents, interactive quantity steppers) and an **Immutable / Hash-Locked Approval** (emerald security banner, padlocked controls, monospace SHA-256 fingerprint pill, and live expiry countdown timer).
3. **Frictionless Multi-Persona Evaluation:** A persistent top **Persona & Role Switcher Bar** lets a single reviewer or evaluator seamlessly switch between **Alice (`Coordinator`)**, **Bob (`Approver`)**, and **Charlie (`Buyer / Auditor`)** with one click. Switching personas swaps the active backend-signed JWT token and immediately updates available actions and Separation-of-Duties guard banners.
4. **Interactive Adversarial Proof (Tamper Simulator):** Because security guarantees are invisible when everything goes right, Stage 3 (Buyer Checkout) includes an expandable **"Test Cryptographic Lock (Tamper Simulator)"** panel so evaluators can actively attempt to mutate quantities, alter prices, expire the lock, or replay a capture and watch the backend's cryptographic gate reject the attack in real time.

---

## 2. Visual System: Color Palette, Typography & Cryptographic Trust Badges

### 2.1 Color Tokens (Tailwind CSS Semantic Mapping)

| Semantic State | Surface / Background | Border | Text / Icon Accent | Usage Context |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Application Chrome** | `bg-slate-50` (`#F8FAFC`) / Cards `bg-white` (`#FFFFFF`) | `border-slate-200` (`#E2E8F0`) | `text-slate-900` (`#0F172A`) / Primary CTA `bg-indigo-600` (`#4F46E5`) | Clean, high-contrast light-mode B2B workspace with deep slate header (`bg-slate-900`). |
| **State 1: Draft / Versioning ($v_1, v_2$)** | `bg-amber-50/70` (`#FFFBEB`) | `border-amber-300` (`#FCD34D`) | `text-amber-800` (`#92400E`) | Indicates cart is still being prepared or revised; creates a new version $v_{n+1}$ on edit. |
| **State 2: Submitted for Approval** | `bg-blue-50/70` (`#EFF6FF`) | `border-blue-300` (`#93C5FD`) | `text-blue-800` (`#1E40AF`) | Indicates $v_n$ is frozen and awaiting managerial review by an `Approver`. |
| **State 3: Cryptographically Locked (`APPROVED_LOCKED`)** | `bg-emerald-50/80` (`#ECFDF5`) | `border-emerald-400` (`#34D399`) | `text-emerald-900` (`#064E3B`) | Indicates Bob has signed $v_n$; displays SHA-256 `intent_hash`, HMAC badge, and live TTL timer. |
| **State 4: Reconciled & Verified (`RECONCILED_VERIFIED`)** | `bg-teal-50/80` (`#F0FDFA`) | `border-teal-500` (`#14B8A6`) | `text-teal-900` (`#134E4A`) | Indicates PayPal Sandbox capture succeeded and passed all 5 cryptographic reconciliation invariants. |
| **State 5: Security Gate Blocked / Expired / Rejected** | `bg-rose-50` (`#FFF1F2`) | `border-rose-400` (`#FB7185`) | `text-rose-900` (`#881337`) | Displayed on SoD self-approval blocks, `ERR_INTENT_HASH_MISMATCH` tamper blocks, or expired locks. |

### 2.2 Typography & Monospace Cryptographic Elements
* **UI & Prose Font:** `Inter` / system sans-serif (`font-sans`) for crisp legibility across tables, AI item rationales, and managerial comments.
* **Cryptographic & Financial Font:** `JetBrains Mono` / `Fira Code` (`font-mono`, `tabular-nums`) used strictly for:
  * SHA-256 `intent_hash` fingerprints (e.g., `sha256:e3b0c442...7852b855`)
  * HMAC-SHA256 `approval_signature` digests
  * Cart Version tags (`v1`, `v2`, `v3`) and SKU identifiers (`SKU-001` .. `SKU-015`)
  * Monetary columns (`$68.00`, `6800 cents`) and live countdown timers (`14:32 remaining`)

---

## 3. Global Application Layout & Navigation Chrome

```text
+------------------------------------------------------------------------------------------------------------------+
| [LockIcon] IntentLock   | Merchant: Acme Workspace Supplies (USD) | LLM Router: Gemini 2.5 [Auto-Failover Ready] |
|                         | Active Persona: [ (o) Alice: Coordinator | ( ) Bob: Approver | ( ) Charlie: Buyer ]    |
+------------------------------------------------------------------------------------------------------------------+
| [Purchasing Workspace]   [Merchant Catalog (15 SKUs)]   [Discovery & Evaluation Benchmark (3 Studies + 8 Evals)] |
+------------------------------------------------------------------------------------------------------------------+
|  SIDEBAR: PURCHASE REQUESTS     |  WORKFLOW STEPPER BAR:                                                         |
|  [+ New Supply Request]         |  (1) Propose & Version  --->  (2) Review & Lock  --->  (3) PayPal  ---> (4) Verify
|                                 |  ----------------------------------------------------------------------------- |
|  > PR-2026-0001 [RECONCILED]    |                                                                                |
|    3x New Hire Ergo Kit ($342)  |                        ACTIVE STAGE WORKSPACE PANEL                            |
|  > PR-2026-0002 [APPROVED v2]   |                   (Adapts to Selected Stage & Active Persona)                  |
|    Conf Room Whiteboards ($184) |                                                                                |
|  > PR-2026-0003 [DRAFT v1]      |                                                                                |
|    Standing Desk Mats ($210)    |                                                                                |
+---------------------------------+--------------------------------------------------------------------------------+
```

---

## 4. Screen-by-Screen Interactive Flows & Wireframe Specifications

### 4.1 Screen 1: Coordinator Workspace (`1. Request & Propose`)
**Target Persona:** `Coordinator` (Alice Chen)

#### Key UI Components & Interactive Behavior
1. **Natural Language Request Composer:**
   * Textarea for informal requests (e.g., *"We have 3 new backend engineers starting Monday. Need ergonomic vertical mice, USB-C multiport hubs, and braided 100W USB-C cables for each of them. Keep total under $400."*).
   * Quick-Load Scenario Chips (1-click presets for rapid testing: *New-Hire Ergonomic Bundle*, *Q4 Conference Room Restock*, *Tight-Budget Cable & Adapter Run*, *Over-Budget Constraint Stress Test*).
   * Optional structured inputs: **Budget Cap ($ USD)** and **Target Headcount**.
   * Primary CTA: **`Generate Inventory-Checked Cart Proposal`** (displays active LLM provider badge, latency in `ms`, and automatic failover indicator if primary LLM rate-limited).
2. **AI Explanation & Constraint Banner:**
   * Displays the AI Agent's executive summary explaining how headcount and pack sizes were mapped to exact Acme SKUs.
   * Renders amber **Constraint Warning Pills** if any requested item was clamped due to stock limits or if the request pushed near the budget cap.
3. **Interactive Line-Item Table & Automatic Immutable Versioning ($v_n \rightarrow v_{n+1}$):**
   * Columns: `SKU`, `Product Name & Pack Size`, `Live Stock`, `Unit Price (USD)`, `Quantity [- / +]`, `Line Total`, and `AI Selection Rationale`.
   * **Add Catalog Item Dropdown:** Allows Alice to add any of the 15 Acme SKUs manually.
   * **Crucial UX Behavior:** When Alice clicks `+` or `-` on a quantity or adds/removes an item and clicks **`Save Revision as New Immutable Version (v2)`**, the UI does **not** overwrite `v1`. Instead, the Version Selector tabs update (`[ v1 (Superseded) ]` $\rightarrow$ **`[ v2 (Current Draft) ]`**) and the Canonical SHA-256 `intent_hash` badge visibly updates to a new digest.
4. **Canonical Hash Preview & Submission Gate:**
   * Displays the computed `intent_hash` (`sha256:...`) with a **"View Canonical RFC 8785 JSON"** modal trigger.
   * Primary CTA: **`Submit Version v2 for Managerial Approval ->`**.

---

### 4.2 Screen 2: Approver Review View (`2. Review & Lock`)
**Target Persona:** `Approver` (Bob Martinez — Operations Manager)

#### Key UI Components & Interactive Behavior
1. **Separation of Duties (SoD) Guard Banner:**
   * **If viewed while logged in as Alice (`Coordinator`):** Displays a prominent rose security banner:
     > **Separation of Duties Enforced (`ERR_SOD_SELF_APPROVAL`):** As the requesting Coordinator (`USR-COORD-ALICE`), you cannot approve your own cart version. Switch persona to **Bob (`Approver`)** in the top bar—or click *"Test Self-Approval Block"* to verify backend HTTP 403 enforcement.
   * **If viewed while logged in as Bob (`Approver`):** Displays an indigo authority banner confirming Bob is authorized to review and cryptographically lock `CartVersion v2`.
2. **Version Diff Inspector ($v_1 \rightarrow v_2$):**
   * When $v_n > 1$, displays a clean delta card comparing $v_{n-1}$ against $v_n$:
     * Example: `SKU-003 (ThunderDock USB-C 8-in-1 Hub): Qty 3 -> 4 (+1 unit, +$46.00)` | `Net Total Delta: $342.00 -> $388.00 (+$46.00)`.
3. **Immutable Cart & AI Rationale Inspection Table:**
   * Read-only presentation of all line items, unit prices, quantities, AI item explanations, and constraint checks. Quantity steppers are absent—Bob reviews a fixed snapshot.
4. **Cryptographic Lock Minting Panel:**
   * Displays the exact `intent_hash` that will be bound into the HMAC-SHA256 `ApprovalLock` and sent to PayPal Sandbox as `purchase_units[0].custom_id`.
   * **Approval Expiry TTL Selector:** Radio pills allowing Bob to choose the lock window:
     * `15 Minutes (Standard P0 Default)`
     * `60 Minutes`
     * `24 Hours`
     * `5 Seconds (Demo Expiry Test Mode)` — included specifically so evaluators can watch a lock expire in 5 seconds and verify that checkout is blocked upon expiry.
   * **Managerial Comment / Rejection Reason Input:** Text field for approval notes or mandatory rejection rationale.
   * Action Buttons:
     * **`[Lock & Approve Version v2 (SHA-256)]`** (Emerald primary button)
     * **`[Reject Version v2 & Return to Coordinator]`** (Rose outline button)

---

### 4.3 Screen 3: Buyer Checkout View (`3. PayPal Sandbox Checkout`)
**Target Persona:** `Buyer / Operator` (Charlie Kim — Finance Buyer)

#### Key UI Components & Interactive Behavior
1. **Cryptographic Approval Lock Header Card:**
   * Emerald verified banner showing:
     * **Locked Version:** `CartVersion v2` (Immutable)
     * **Approved By:** `Bob Martinez (USR-APPR-BOB)`
     * **Locked SHA-256 `intent_hash`:** `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
     * **HMAC-SHA256 Signature:** `verified (9f86d081...4a2b)`
     * **Live Expiry Countdown Pill:** Tick-by-second badge (e.g., `LOCK ACTIVE — Expires in 14m 42s`). Turns rose (`LOCK EXPIRED — Checkout Blocked`) the instant `now >= expires_at`.
2. **Interactive Tamper-Test Simulator Card ("Try Breaking the Lock"):**
   * A dedicated security demonstration panel with 4 adversarial test buttons that execute real requests against the backend checkout endpoint:
     1. **`Simulate Quantity Tamper (+1 SKU-001)`:** Sends checkout request with modified item quantity $\rightarrow$ Backend returns `HTTP 409 ERR_INTENT_HASH_MISMATCH` and logs `TAMPER_ATTEMPT_BLOCKED`.
     2. **`Simulate Price/Total Drift (+$10.00)`:** Sends checkout request with altered amount $\rightarrow$ Backend returns `HTTP 409 ERR_INTENT_HASH_MISMATCH`.
     3. **`Simulate Expired Approval Checkout`:** Forces TTL check against an expired lock $\rightarrow$ Backend returns `HTTP 409 ERR_APPROVAL_EXPIRED`.
     4. **`Simulate Replay Attack (Double Capture)`:** Attempts to re-use an already consumed `ApprovalLock` $\rightarrow$ Backend returns `HTTP 409 ERR_APPROVAL_ALREADY_CONSUMED`.
   * Displays the live structured JSON security rejection response from the backend without corrupting the valid locked cart state.
3. **PayPal Sandbox Checkout Execution Panel:**
   * Displays the exact PayPal Orders v2 payload preview (`intent: "CAPTURE"`, `currency_code: "USD"`, `purchase_units[0].custom_id = intent_hash`, `invoice_id`).
   * Provides dual execution controls for maximum reliability across interactive browser demos and headless evaluation environments:
     * **Official PayPal JS SDK Buttons (`@paypal/react-paypal-js`):** Renders the authentic PayPal Sandbox checkout button wired to `createOrder` and `onApprove`.
     * **PayPal Sandbox MCP / Orders v2 Direct Execution Flow:** Step 1 (`Create PayPal Sandbox Order via MCP/v2`) $\rightarrow$ Displays live PayPal Order ID & Sandbox `approve` link $\rightarrow$ Step 2 (`Complete Buyer Sandbox Approval & Capture Order`).
   * Includes a **`Sync / Investigate Uncertain PayPal Status`** button (FR-16) that queries `GET /v2/checkout/orders/{id}` directly from PayPal Sandbox if a capture is pending or interrupted.

---

### 4.4 Screen 4: Reconciliation, Evidence Bundle & Timeline View (`4. Reconcile & Verify`)
**Target Persona:** All Roles (`Buyer`, `Approver`, `Coordinator`, External Auditor)

#### Key UI Components & Interactive Behavior
1. **5-Point Cryptographic Reconciliation Scorecard:**
   * Displays a side-by-side comparison table between the **Internal Approved Lock (`ApprovalRecord`)** and the **Authoritative PayPal Sandbox Order (`GET /v2/checkout/orders/{id}`)**:

| Verification Invariant | Approved IntentLock Value | Authoritative PayPal Sandbox Value | Verification Status |
| :--- | :--- | :--- | :--- |
| **1. SHA-256 Intent Binding (`custom_id`)** | `e3b0c44298fc...7852b855` | `purchase_units[0].custom_id`: `e3b0c44298fc...7852b855` | `VERIFIED MATCH` |
| **2. Exact Capture Total (USD Cents)** | `38800 cents ($388.00)` | `captures[0].amount.value`: `"388.00"` (`38800 cents`) | `VERIFIED MATCH` |
| **3. Currency Code Invariance** | `"USD"` | `captures[0].amount.currency_code`: `"USD"` | `VERIFIED MATCH` |
| **4. PayPal Order & Capture Status** | Required: `COMPLETED` | Order: `COMPLETED` / Capture: `COMPLETED` | `VERIFIED MATCH` |
| **5. SKU Line-Item Breakdown** | `2 SKUs (7 total units)` | `purchase_units[0].items`: `2 SKUs (7 total units)` | `VERIFIED MATCH` |

2. **Tamper-Evident JSON Evidence Bundle Inspector & Export:**
   * Displays the sealed `evidence_bundle_hash` (`SHA-256`).
   * **`[Download Cryptographic Evidence Bundle (.json)]`** button: Downloads the complete JSON artifact containing the canonical cart, approval HMAC, PayPal Order/Capture metadata, reconciliation proof, and audit hash chain.
   * **`[Run In-App Cryptographic Re-Verification]`** button: Re-runs the RFC 8785 canonical hash check, HMAC verification, and audit chain integrity check live in the UI.
3. **Chronological Hash-Chained Audit Timeline:**
   * Vertical timeline showing every event for the purchase request from initial prompt $\rightarrow$ LLM provider selection/failover $\rightarrow$ version edits $\rightarrow$ managerial lock $\rightarrow$ tamper test blocks $\rightarrow$ PayPal order creation $\rightarrow$ capture $\rightarrow$ reconciliation.
   * Each event displays its monotonic sequence number (`#104`), actor badge (`Alice [COORDINATOR]`, `Bob [APPROVER]`, `Charlie [BUYER]`, `System [AGENT]`), timestamp, `prev_event_hash` snippet, and `event_hash` snippet, with a top **`Audit Chain Integrity: 100% Verified`** status pill.

---

### 4.5 Screen 5: Coordinator Discovery & Evaluation Benchmark Tab
**Target Persona:** Product Evaluators, Engineers, and Auditors

#### Key UI Components & Interactive Behavior
1. **Section A — 3-Coordinator Discovery Study Findings (`COORD-INT-01` .. `03`):**
   * Displays the 3 structured Coordinator Discovery Cards detailing each coordinator's company profile, workflow pain points, real-world TOCTOU cart drift incident, and quantitative before/after metrics:
     * **Translation Time Reduction:** `11.4 min` manual baseline $\rightarrow$ `1.1 min` with IntentLock (**$-90.3\%$**).
     * **SKU / Pack-Size Error Rate:** `26.7%` manual baseline $\rightarrow$ `0.0%` with grounded catalog & AI explanation.
     * **TOCTOU Drift Rate:** `100%` blocked by SHA-256 `intent_hash` + PayPal `custom_id` reconciliation.
2. **Section B — Live Executable Evaluation Harness (`Run All 8 Golden & Adversarial Scenarios`):**
   * One-click **`[Execute Full Evaluation Suite]`** button that runs 8 deterministic end-to-end backend tests and renders live pass/fail badges, execution latency, and cryptographic assertions:
     1. `EVAL-01`: Multi-item New-Hire Ergonomic Kit translation & pack-size math accuracy
     2. `EVAL-02`: Strict budget ceiling enforcement & constraint warning generation
     3. `EVAL-03`: Multi-LLM Router automatic failover resilience under simulated `HTTP 429` rate limit
     4. `EVAL-04`: Immutable cart versioning ($v_1 \rightarrow v_2$) & RFC 8785 SHA-256 hash divergence
     5. `EVAL-05`: Separation-of-Duties hard block on Coordinator self-approval (`ERR_SOD_SELF_APPROVAL`)
     6. `EVAL-06`: Adversarial TOCTOU quantity/price tamper rejection before PayPal order creation (`ERR_INTENT_HASH_MISMATCH`)
     7. `EVAL-07`: Expired `ApprovalLock` rejection (`ERR_APPROVAL_EXPIRED`) & replay capture block (`ERR_APPROVAL_ALREADY_CONSUMED`)
     8. `EVAL-08`: PayPal Sandbox Orders v2 capture & 5-point `custom_id == intent_hash` reconciliation verification
