# IntentLock — Comprehensive Security Audit Report (Wave 1 Review)

| Audit Metadata | Details |
| :--- | :--- |
| **Document ID** | `AUDIT-SECURITY-REVIEW` |
| **Target System** | IntentLock — Approval-Aware Purchasing Agent & Cryptographic PayPal Checkout |
| **Codebase Inspected** | `backend/app/` (`main.py`, `database.py`, `models.py`, `schemas.py`, `config.py`, `seed.py`, and all 9 services) + `frontend/src/` |
| **Specifications Audited** | `06-SECURITY-THREAT-MODEL.md` (`LAW-01`..`LAW-07`, `T-01`..`T-06`), `08-GUARDRAILS.md` (`G-01`..`G-08`), `12-PRIVACY-COMPLIANCE.md`, `14-STATE-MACHINE-AND-HASH-SPEC.md` |
| **Audit Date** | 2026-11-11 |
| **Overall Verdict** | **`OPEN_THREATS` (Application-Layer Core Guardrails Verified; 4 Database/Data-Flow Hardening Gaps Identified for Wave 2)** |
| **`threats_open` (Blocking)** | **2** (`SEC-GAP-01`: Missing SQLite Immutability/SoD Triggers; `SEC-GAP-02`: Unredacted `raw_need_text` in Revision LLM Prompt & DB Persistence) |
| **`threats_open` (Non-Blocking)** | **4** (`SEC-GAP-03` through `SEC-GAP-06`: Sub-Minute TTL Rounding, Live Pre-Checkout Stock Re-Check, Evidence Bundle HMAC Signature, Audit Metadata Redaction Filter) |

---

## 1. Executive Summary & 6-Question Security Verification Matrix

We conducted a line-by-line adversarial code review across all backend services (`cart_hash_service.py`, `guardrails.py`, `approval_service.py`, `paypal_mcp_service.py`, `reconciliation_service.py`, `auth_service.py`, `audit_service.py`, `agent_service.py`, `llm_router.py`, `main.py`) and the React frontend (`frontend/src/`).

### 1.1 Direct Answers to the 6 Core Audit Questions

| # | Audit Question | Status | Code Evidence & Findings |
| :---: | :--- | :---: | :--- |
| **1** | **Are there any bypass paths where a Coordinator can approve their own request (`G-04`)?** | **CLOSED (App Layer)** / **GAP (DB Constraint)** | **No application-layer bypass exists.** `approve_cart_version` (`approval_service.py:168`) and `reject_cart_version` (`approval_service.py:350`) unconditionally call `guardrails.enforce_separation_of_duties(coordinator_id=purchase_request.coordinator_id, approver_user_id=actor.id, approver_role=actor.role)` (`guardrails.py:317-358`), enforcing both `approver_role == "APPROVER"` and `coordinator_id != approver_user_id` before any lock is minted. However, the database-level `BEFORE INSERT` trigger / `CHECK` constraint required by `LAW-03` (`06-SECURITY-THREAT-MODEL.md:22,119`) is not yet registered in `database.py` (`SEC-GAP-01`). |
| **2** | **Are there any bypass paths where a Buyer can checkout an unapproved, mutated (`G-05`), or expired (`G-06`) cart version?** | **CLOSED (Core)** / **HARDEN (Sub-Minute TTL & Live Stock)** | **No checkout bypass exists for unapproved, superseded, mutated, or expired carts.** Both `POST /api/v1/checkout/{version_id}/create-paypal-order` (`main.py:993`) and `POST /api/v1/checkout/{version_id}/capture-paypal-order` (`main.py:1151`) invoke `_verify_checkout_gates` (`main.py:888-969`), which enforces: (a) `actor.role == "BUYER"`, (b) `enforce_intent_lock_integrity` (`guardrails.py:361-449`, checking `status != "SUPERSEDED"`, `approval_lock is not None`, `decision == "APPROVED"`, live SHA-256 recomputation from `CartLineItem` rows, and constant-time `hmac.compare_digest` over `approval_signature`), and (c) `enforce_approval_not_expired` (`guardrails.py:451-489`). **Minor Wave 2 Hardening (`SEC-GAP-03`):** `main.py:836-837` rounds `approval_ttl_seconds` up to `max(1, ...)` minutes, preventing the UI's `"5 Seconds (Demo Expiry Test Mode)"` option from expiring in 5 seconds. Also (`SEC-GAP-04`), `_verify_checkout_gates` should re-verify live `Product.stock_available` at checkout time (`G-02`) and explicitly assert `cart_version.status in ("APPROVED_LOCKED", "PAYPAL_ORDER_CREATED", "BUYER_APPROVED")`. |
| **3** | **Are LLM prices completely ignored in favor of SQLite catalog `unit_price_cents` (`G-01`)?** | **CLOSED (100% Enforced)** | **Verified.** In `llm_router.py:690-694`, any `unit_price_cents` or `price_cents` emitted by an LLM is forwarded only so `guardrails.enforce_catalog_grounding_and_pricing` (`guardrails.py:206-214`) can log a `[G-01 ENFORCED: Ignored non-authoritative price...]` warning. Line 279-280 then unconditionally overwrites `unit_price_cents = int(product.unit_price_cents)` and `line_total_cents = unit_price_cents * final_qty` from the SQLite `Product` row. Manual Coordinator edits (`agent_service.py:593`) also pass through `enforce_catalog_grounding_and_pricing`. |
| **4** | **Is PII scrubbed before any external LLM HTTP call (`llm_router.py` / `agent_service.py`)?** | **PARTIAL (`SEC-GAP-02` Open)** | **Initial requests (`propose_initial_cart_for_request`) scrub PII**, calling `sanitize_and_check_prompt_injection(raw_need_text)` (`agent_service.py:179`) before building `user_prompt` (`agent_service.py:217`). **However, 2 gaps exist (`SEC-GAP-02`):** (1) `purchase_request.raw_need_text` is persisted to SQLite *unredacted* (`agent_service.py:187`), and during cart revision (`revise_cart_with_agent`, `agent_service.py:413`), `f"Original Need: {purchase_request.raw_need_text}\n"` is interpolated directly into `user_prompt` without passing through `sanitize_and_check_prompt_injection`, leaking any PII from Turn 1 to external LLMs on Turn 2! (2) `llm_router.generate_cart_proposal` does not run a defense-in-depth `sanitize_prompt_for_llm` pass on `user_prompt` before outbound HTTP calls. |
| **5** | **Are runtime API keys redacted in `GET /api/v1/llm/status` and audit logs so secrets never leak (`T-06`)?** | **CLOSED (API & Logs)** / **HARDEN (Scrubber)** | **Verified in `GET /api/v1/llm/status` and `POST /api/v1/llm/keys`.** `llm_router.get_router_status()` (`llm_router.py:225-244`) exposes only `configured: bool(d["api_key"])` and never includes `api_key` in the returned dictionary. `paypal_mcp_service.get_paypal_status()` (`paypal_mcp_service.py:164-180`) never exposes `client_secret` and masks `client_id_preview`. `POST /api/v1/llm/keys` (`main.py:575-591`) logs only key names (`list(llm_keys_to_set.keys())`). **Wave 2 Hardening (`SEC-GAP-06`):** Add a recursive secret/token redaction filter inside `audit_service.record_audit_event` and `llm_router._classify_exception` so upstream error strings or metadata payloads can never inadvertently log an API key or bearer token. |
| **6** | **Are SQLite triggers or application guards protecting `audit_events` and locked `cart_versions` from mutation?** | **OPEN (`SEC-GAP-01` Missing SQLite Triggers)** | **Application-layer code follows append-only patterns, but zero SQLite triggers exist in `database.py` or `models.py`.** `06-SECURITY-THREAT-MODEL.md` (`LAW-02`, `LAW-03`, `LAW-07`, `T-01`, `T-02`) explicitly mandates SQLite `BEFORE UPDATE` and `BEFORE DELETE` immutability triggers on `audit_events`, `cart_line_items`, and locked `cart_versions`, as well as a `BEFORE INSERT` Separation-of-Duties trigger on `approval_locks`. Adding these DDL triggers in `database.py` is our top Wave 2 priority. |

---

## 2. Detailed Threat Model & Guardrail Verification (`LAW-01`..`LAW-07`, `T-01`..`T-06`, `G-01`..`G-08`)

### 2.1 The 7 Unbreakable Laws (`06-SECURITY-THREAT-MODEL.md`)

| Law ID | Requirement | Verification Status | Implementation Evidence & Gap Analysis |
| :--- | :--- | :---: | :--- |
| **`LAW-01`** | **No Execution Without Valid Cryptographic Approval Lock** | **VERIFIED** | `main.py:888-969` (`_verify_checkout_gates`) and `guardrails.py:391-449` (`enforce_intent_lock_integrity`) verify `approval_lock is not None`, `approval_lock.decision == "APPROVED"`, and verify HMAC-SHA256 `approval_signature` using `hmac.compare_digest` (`cart_hash_service.py:166-176`). |
| **`LAW-02`** | **Zero Post-Approval Cart Drift (TOCTOU Immunity)** | **PARTIAL (`SEC-GAP-01`)** | App layer creates a new `CartVersion` $v_{n+1}$ on any edit (`agent_service.py:115-160`, `374`, `549`) and marks prior versions `SUPERSEDED`. Both `create-paypal-order` and `capture-paypal-order` recompute `intent_hash` from SQLite rows and compare to `ApprovalLock.intent_hash`. Missing SQLite `BEFORE UPDATE`/`BEFORE DELETE` triggers on `cart_line_items` and locked `cart_versions` (`SEC-GAP-01`). |
| **`LAW-03`** | **Strict Separation of Duties (SoD)** | **PARTIAL (`SEC-GAP-01`)** | FastAPI RBAC (`auth_service.py:114-137`) + `guardrails.enforce_separation_of_duties` (`guardrails.py:317-358`) + `_verify_checkout_gates` (`main.py:902`) strictly separate `COORDINATOR`, `APPROVER`, and `BUYER`. Missing SQLite `BEFORE INSERT` trigger on `approval_locks` verifying `approver_id != coordinator_id` (`SEC-GAP-01`). |
| **`LAW-04`** | **Server-Authoritative Catalog & Integer-Cent Math** | **VERIFIED** | `guardrails.enforce_catalog_grounding_and_pricing` (`guardrails.py:170-309`) looks up `Product` in SQLite (`catalog_map`), strips unknown/inactive SKUs, ignores external prices, and computes `unit_price_cents * final_qty` in integer cents. |
| **`LAW-05`** | **Dual-Gate UTC Expiration Enforcement** | **PARTIAL (`SEC-GAP-03`)** | `guardrails.enforce_approval_not_expired` (`guardrails.py:451-489`) checks `now_utc >= expires_at` at both `PRE_CREATE_ORDER` (`main.py:998`) and `PRE_CAPTURE_ORDER` (`main.py:1156`), transitioning expired versions to `EXPIRED`. Sub-minute `approval_ttl_seconds` is rounded to 1 minute in `main.py:837` (`SEC-GAP-03`). |
| **`LAW-06`** | **Authoritative Provider Reconciliation (No Manual Override)** | **VERIFIED** | Zero endpoints allow manual status overrides. `reconciliation_service.reconcile_order` (`reconciliation_service.py:30-361`) evaluates all 6 invariants (`check_order_completed`, `check_capture_completed`, `check_currency_usd`, `check_amount_exact`, `check_intent_hash_match`, `check_single_purchase_unit`) before transitioning to `CAPTURED_VERIFIED`. |
| **`LAW-07`** | **Append-Only Hash-Chained Audit Trail** | **PARTIAL (`SEC-GAP-01`)** | `audit_service.record_audit_event` (`audit_service.py:39-91`) chains every event via `prev_event_hash` and `SHA-256`, and `verify_audit_chain` (`audit_service.py:94-136`) verifies global chain integrity. Missing SQLite `BEFORE UPDATE`/`BEFORE DELETE` triggers on `audit_events` (`SEC-GAP-01`). |

---

### 2.2 Defense-in-Depth Guardrails (`08-GUARDRAILS.md`: `G-01`..`G-08`)

| Guardrail | Layer | Status | Code Location & Audit Notes |
| :---: | :--- | :---: | :--- |
| **`G-01`** | Layer 2: Catalog Grounding & Price Integrity | **CLOSED** | `guardrails.py:170-295`. Rejects hallucinated SKUs (`SKU-999-MONITOR`), merges duplicate SKUs deterministically (`consolidated` dict), strips LLM-suggested prices, and binds `Product.unit_price_cents`. |
| **`G-02`** | Layer 2: Inventory & Quantity Bounds | **HARDEN (`SEC-GAP-04`)** | `guardrails.py:217-277`. Rejects `raw_qty < 1`, caps `requested_qty > stock_avail` with an explicit `[G-02 STOCK CAP: ...]` warning. **Gap:** Pre-checkout live stock re-verification (`08-GUARDRAILS.md` Section 2.2.2) is not called inside `_verify_checkout_gates` before creating/capturing a PayPal order (`SEC-GAP-04`). |
| **`G-03`** | Layer 1: Prompt Injection & Privilege Boundary | **CLOSED** | `guardrails.py:52-157`. Regex patterns detect and strip system instruction overrides, price manipulation directives, self-approval directives, payment fabrication directives, and non-USD currency overrides, emitting `[G-03 BLOCKED: ...]` warnings and `GUARDRAIL_G03_PRE_LLM_SCAN` audit events. |
| **`G-04`** | Layer 3: Separation of Duties (RBAC) | **CLOSED** | `guardrails.py:317-358`, `approval_service.py:168,350`, `main.py:704,736,902`. Enforces role boundaries across Coordinator, Approver, and Buyer. |
| **`G-05`** | Layer 3: Cryptographic Intent Lock (TOCTOU) | **CLOSED** | `cart_hash_service.py:23-178`, `guardrails.py:361-449`, `agent_service.py:115-160`. Enforces RFC 8785 canonical JSON SHA-256 `intent_hash` + HMAC-SHA256 `approval_signature` at approval time, supersedes prior locks on cart edit, and re-verifies at checkout/capture. |
| **`G-06`** | Layer 3: Expiry TTL Enforcement | **HARDEN (`SEC-GAP-03`)** | `guardrails.py:451-489`, `main.py:939,948-952`. Enforces UTC `expires_at` at Gate 1 and Gate 2. Needs exact `approval_ttl_seconds` support in `approval_service.py` so 5-second demo expiry locks work as intended (`SEC-GAP-03`). |
| **`G-07`** | Layer 4: Single Order / Single PU / Full Capture / USD | **CLOSED** | `guardrails.py:497-571`, `paypal_mcp_service.py:188-240`. Enforces `merchant_id == "MERCH-ACME-001"`, `currency == "USD"`, `0 < total_cents <= 500000` ($5,000 cap), `purchase_units_count == 1`, and `intent == "CAPTURE"`. |
| **`G-08`** | Layer 4: Anti-Fabrication Reconciliation | **CLOSED** | `guardrails.py:574-591`, `reconciliation_service.py:30-361`. Blocks manual payment status fabrication and verifies all 6 PayPal capture invariants before marking `CAPTURED_VERIFIED`. |

---

## 3. Detailed Security Findings & Wave 2 Hardening Plan

### 3.1 Blocking Findings (`threats_open: 2`)

#### `SEC-GAP-01` (HIGH — Blocking): Missing SQLite Immutability & Separation-of-Duties Triggers (`LAW-02`, `LAW-03`, `LAW-07`, `T-01`, `T-02`)
- **Specification Reference:**
  - `06-SECURITY-THREAT-MODEL.md` (`LAW-03`, `T-01`, `T-02`): *"SQLite Immutability Triggers: Database-level `BEFORE UPDATE` and `BEFORE DELETE` triggers on `cart_line_items` and locked `cart_versions` raise `ABORT` if any code path attempts to alter items, quantities, or unit prices of a version once created."* and *"Enforced in FastAPI JWT RBAC AND SQLite `BEFORE INSERT` triggers."*
  - `12-PRIVACY-COMPLIANCE.md` Section 4.3: Append-only `audit_events` table.
- **Current Implementation:**
  - `backend/app/database.py` configures `PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;`, but defines **zero SQLite triggers**.
  - If any future service code or raw SQL query attempts to `UPDATE` or `DELETE` rows in `audit_events`, mutate `cart_line_items` after creation, or alter `intent_hash` / `total_amount_cents` / `canonical_payload_json` on a `CartVersion`, SQLite currently permits the mutation at the storage layer.
- **Wave 2 Remediation:**
  - Register a SQLite DDL initialization function in `backend/app/database.py` (invoked on engine connect / `seed_database`) that creates `CREATE TRIGGER IF NOT EXISTS` guards:
    1. `trg_audit_events_immutable_update` & `trg_audit_events_immutable_delete`: `BEFORE UPDATE` / `BEFORE DELETE` on `audit_events` $\rightarrow$ `SELECT RAISE(ABORT, 'LAW-07 Violation: audit_events ledger is append-only and immutable');`
    2. `trg_cart_line_items_immutable_update` & `trg_cart_line_items_immutable_delete`: `BEFORE UPDATE` / `BEFORE DELETE` on `cart_line_items` when the parent `cart_versions.status` is not `'DRAFT'` (or unconditionally once created, since edits always mint $v_{n+1}$) $\rightarrow$ `SELECT RAISE(ABORT, 'LAW-02 Violation: cart_line_items are immutable once created');`
    3. `trg_cart_versions_locked_immutable` & `trg_cart_versions_no_delete`: `BEFORE UPDATE` on `cart_versions` forbidding any change to `intent_hash`, `total_amount_cents`, `canonical_payload_json`, `merchant_id`, `currency`, or `version_number` once created, and `BEFORE DELETE` forbidding deletion of locked/captured versions.
    4. `trg_approval_locks_sod_insert` & `trg_approval_locks_sod_update`: `BEFORE INSERT` / `BEFORE UPDATE` on `approval_locks` verifying that `NEW.approver_id != (SELECT coordinator_id FROM purchase_requests WHERE id = NEW.request_id)` and `(SELECT role FROM users WHERE id = NEW.approver_id) = 'APPROVER'` $\rightarrow$ `SELECT RAISE(ABORT, 'LAW-03 / G-04 Violation: Database SoD trigger blocked self-approval or non-APPROVER lock');`

---

#### `SEC-GAP-02` (HIGH — Blocking): Unredacted PII in `PurchaseRequest.raw_need_text` & Turn-2 Revision Prompt Leak (`12-PRIVACY-COMPLIANCE.md` Section 3.2)
- **Specification Reference:**
  - `12-PRIVACY-COMPLIANCE.md` Section 2.2 (`PCI-04`) & Section 3.2: *"All natural-language coordinator inputs pass through a deterministic regex + structural PII scrubber (`backend/app/services/guardrails.py`) before leaving the application boundary to any external LLM API."*
- **Current Implementation:**
  1. In `backend/app/services/agent_service.py:179-188` (`propose_initial_cart_for_request`), `sanitize_and_check_prompt_injection(raw_need_text)` produces `sanitized_prompt`, which is used for the Turn-1 LLM call. However, `PurchaseRequest.raw_need_text` and `CartVersion.source_prompt` store the **unredacted** `raw_need_text.strip()`. If a Coordinator accidentally pastes a 16-digit credit card PAN or SSN into the request box, the raw PAN/SSN is written to SQLite!
  2. Worse, in `backend/app/services/agent_service.py:412-415` (`revise_cart_with_agent`), the backend constructs the Turn-2 LLM prompt as:
     ```python
     user_prompt = (
         f"Original Need: {purchase_request.raw_need_text}\n"
         f"Coordinator Revision Instruction (for Version v{next_version_number}): {sanitized_revision}\n"
     )
     ```
     Because `purchase_request.raw_need_text` was stored unredacted, **any PII or prompt injection payload from Turn 1 bypasses the scrubber on Turn 2 and is transmitted directly to external LLM APIs!**
  3. Furthermore, `llm_router.generate_cart_proposal` (`llm_router.py:266`) trusts callers to have scrubbed `user_prompt` rather than enforcing a mandatory pre-flight `sanitize_prompt_for_llm` check at the router boundary.
- **Wave 2 Remediation:**
  1. In `agent_service.py` (`propose_initial_cart_for_request` and `revise_cart_with_agent`), persist `sanitized_prompt` (or PII-redacted text) into `purchase_request.raw_need_text` and `cart_version.source_prompt` so PANs/SSNs/tokens are never stored in SQLite (satisfying `PCI-01` & `PCI-04`).
  2. In `revise_cart_with_agent`, pass `purchase_request.raw_need_text` through `sanitize_and_check_prompt_injection` before interpolating it into `user_prompt`.
  3. In `llm_router.generate_cart_proposal`, apply `guardrails.sanitize_prompt_for_llm(user_prompt)` right before dispatching to any external LLM provider as a defense-in-depth guarantee.

---

### 3.2 Non-Blocking Hardening Improvements (`threats_open` below threshold: 4)

#### `SEC-GAP-03` (MEDIUM): Sub-Minute `approval_ttl_seconds` Rounding Breaks 5-Second Demo Expiry Mode (`G-06`)
- **Observation:**
  - In `frontend/src/components/ApproverWorkspace.tsx:55`, the UI provides a 4th TTL option: `{ label: '5 Seconds (Demo Expiry Test Mode)', minutes: 1, seconds: 5 }`, sending `ttl_minutes: 1, approval_ttl_seconds: 5` to `POST /api/v1/requests/{request_id}/versions/{version_id}/approve`.
  - In `backend/app/main.py:835-837`:
    ```python
    ttl_minutes = body.ttl_minutes
    if ttl_minutes is None and body.approval_ttl_seconds is not None:
        ttl_minutes = max(1, int(round(body.approval_ttl_seconds / 60)))
    ```
    Because `body.ttl_minutes` is `1` (not `None`), `approval_ttl_seconds=5` is ignored; and even if `ttl_minutes` were `None`, `max(1, ...)` forces a minimum of 60 seconds.
- **Wave 2 Remediation:**
  - Update `approval_service.approve_cart_version` to accept `ttl_seconds: Optional[int] = None` (taking precedence when `approval_ttl_seconds` is provided and `< 60` or explicitly set) so that 5-second demo expiry locks expire in exactly 5 seconds for live judge testing.

#### `SEC-GAP-04` (MEDIUM): Pre-Checkout Live Warehouse Stock Re-Verification & Explicit Cart Status Gate (`G-02` & `14-STATE-MACHINE-AND-HASH-SPEC.md`)
- **Observation:**
  - `08-GUARDRAILS.md` Section 2.2.2 specifies: *"Immediately before invoking PayPal `create_order` and `capture_order`, `G-02` re-queries `products.available_stock`... If any item in the approved cart now exceeds `available_stock`, execution halts with `HTTP 409 Conflict`."*
  - Currently, `_verify_checkout_gates` (`main.py:888-969`) checks `G-04`, `G-05`, `G-06`, and `G-07`, but does not re-verify that `li.quantity <= prod.stock_available` against live SQLite `Product` rows, nor does it explicitly assert that `cart_version.status` is in `("APPROVED_LOCKED", "PAYPAL_ORDER_CREATED", "BUYER_APPROVED")` (e.g., if a version was `EXPIRED` or `REJECTED`).
- **Wave 2 Remediation:**
  - Add `guardrails.enforce_live_stock_availability(db, cart_version.line_items)` inside `_verify_checkout_gates` and assert valid checkout statuses on `cart_version`.

#### `SEC-GAP-05` (LOW): Add Server HMAC-SHA256 Signature (`evidence_signature`) & `consumed_at` Tracking to Sealed Evidence Bundle (`T-04`, `T-05`)
- **Observation:**
  - `reconciliation_service.py:293-294` computes `evidence_bundle_sha256 = hashlib.sha256(evidence_bundle_json.encode("utf-8")).hexdigest()`.
  - `06-SECURITY-THREAT-MODEL.md` (`T-05` item 4) specifies signing the `EvidenceBundle` with `HMAC_SHA256(SERVER_SECRET, canonical_evidence_json)`. Including `evidence_signature: hmac-sha256:...` inside the evidence bundle and response strengthens non-repudiation.
  - Additionally, in `_supersede_prior_versions` (`agent_service.py:137`), prevent revising a request if a PayPal order is already in `CAPTURE_PENDING` or `UNCERTAIN_NEEDS_SYNC` (`14-STATE-MACHINE-AND-HASH-SPEC.md` Table 1.2 Event `E02`).

#### `SEC-GAP-06` (LOW): Secret Redaction Scrubber on Audit Event Metadata & Upstream Error Previews (`T-06`)
- **Observation:**
  - `06-SECURITY-THREAT-MODEL.md` (`T-06` item 2) specifies: *"All logger formatters and audit payload serializers pass through a regex secret scrubber that masks Bearer tokens and API keys."*
  - In `llm_router.py:616`, `body_preview = (exc.response.text or "")[:180]` is inspected, and in `audit_service.py:62`, `metadata` is serialized directly to `metadata_json`. Adding a lightweight secret-redaction pass over `metadata_json` and `summary` in `audit_service.record_audit_event` guarantees that no API key (`AIza...`, `gsk_...`, `sk-...`, `Bearer ...`) can ever be written to `audit_events`.

---

## 4. Summary Verdict & Next Steps for Wave 2

- **Verdict:** **`OPEN_THREATS`** (`2` blocking architecture alignment gaps: `SEC-GAP-01` SQLite immutability/SoD triggers and `SEC-GAP-02` Turn-2 PII scrubbing + redacted storage; `4` non-blocking defense-in-depth hardening items).
- **Action Plan for Wave 2:**
  1. Implement SQLite `BEFORE UPDATE` / `BEFORE DELETE` / `BEFORE INSERT` triggers in `backend/app/database.py` (`SEC-GAP-01`).
  2. Scrub PII before persisting `raw_need_text` / `source_prompt`, scrub `Original Need` in `revise_cart_with_agent`, and add defense-in-depth scrubbing in `llm_router.generate_cart_proposal` (`SEC-GAP-02`).
  3. Support sub-minute `approval_ttl_seconds` in `approval_service.approve_cart_version` and `main.py` (`SEC-GAP-03`).
  4. Add live warehouse stock verification (`G-02`) in `_verify_checkout_gates` (`SEC-GAP-04`).
  5. Add `evidence_signature` (`HMAC-SHA256`) to `reconciliation_service.py` (`SEC-GAP-05`) and regex secret scrubbing to `audit_service.py` (`SEC-GAP-06`).
