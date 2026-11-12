export type RoleEnum = 'COORDINATOR' | 'APPROVER' | 'BUYER';

export interface Persona {
  id: string;
  user_id?: string;
  name: string;
  display_name?: string;
  email: string;
  role: RoleEnum | string;
  department: string;
  avatar_badge?: string;
  permissions?: string[];
}

export interface SwitchPersonaResponse {
  access_token: string;
  token_type: string;
  expires_in_seconds: number;
  persona: Persona;
}

export interface Product {
  sku: string;
  merchant_id: string;
  name: string;
  category: string;
  pack_size_desc: string;
  description?: string;
  unit_price_cents: number;
  unit_price_usd: string;
  unit_price_formatted?: string;
  stock_available: number;
  available_stock?: number;
  recommended_rule: string;
  recommended_per_person_rule?: string;
  keywords: string[];
  tags?: string[];
  is_active: boolean;
}

export interface CartLineItem {
  id?: number;
  cart_version_id?: string;
  sku: string;
  product_name: string;
  name?: string;
  pack_size_desc: string;
  unit_price_cents: number;
  unit_price_usd: string;
  unit_price_formatted?: string;
  quantity: number;
  line_total_cents: number;
  line_total_usd: string;
  line_total_formatted?: string;
  selection_rationale: string;
  item_rationale?: string;
  headcount_math: string;
}

export interface ApprovalLock {
  id: string;
  approval_lock_id?: string;
  request_id: string;
  cart_version_id: string;
  approver_id: string;
  approver_user_id?: string;
  approver_name?: string;
  decision: string;
  comment: string;
  approval_note?: string;
  intent_hash: string;
  approval_signature: string;
  issued_at: string;
  issued_at_utc?: string;
  expires_at: string;
  expires_at_utc?: string;
  is_expired?: boolean;
}

export interface PayPalOrder {
  id: string;
  payment_transaction_id?: string;
  request_id: string;
  cart_version_id: string;
  paypal_order_id: string;
  paypal_capture_id?: string | null;
  invoice_id: string;
  paypal_invoice_id?: string;
  custom_id_intent_hash: string;
  paypal_custom_id?: string;
  intent_hash_bound?: string;
  idempotency_key: string;
  amount_cents: number;
  amount_usd: string;
  amount_formatted?: string;
  currency: string;
  paypal_status: string;
  payment_state?: string;
  execution_mode: string;
  approval_url?: string | null;
  approve_link?: string | null;
  created_by_buyer_id?: string;
  created_at?: string;
  updated_at?: string | null;
  mcp_trace?: Record<string, any> | null;
  order_payload?: Record<string, any> | null;
}

export interface ReconciliationRecord {
  id: string;
  request_id: string;
  cart_version_id: string;
  paypal_order_id: string;
  verdict: string;
  outcome?: string;
  check_order_completed: boolean;
  check_capture_completed: boolean;
  check_currency_usd: boolean;
  check_amount_exact: boolean;
  check_intent_hash_match: boolean;
  check_single_purchase_unit: boolean;
  approved_amount_cents: number;
  captured_amount_cents: number;
  approved_intent_hash: string;
  paypal_custom_id_hash: string;
  discrepancy_details: string[];
  discrepancies?: string[];
  evidence_bundle_sha256: string;
  evidence_bundle: Record<string, unknown>;
  checked_at: string;
}

export interface CartVersion {
  id: string;
  cart_version_id?: string;
  request_id: string;
  version_number: number;
  status: string;
  created_by_id: string;
  source_prompt: string;
  agent_summary: string;
  agent_explanation?: string;
  agent_budget_notes: string;
  agent_warnings: string[];
  guardrail_warnings?: string[];
  llm_provider_used: string;
  llm_model_used: string;
  llm_failover_hops: number;
  llm_latency_ms: number;
  currency: string;
  merchant_id: string;
  merchant_name?: string;
  total_amount_cents: number;
  total_amount_usd: string;
  total_amount_formatted?: string;
  within_budget?: boolean;
  canonical_payload_json: string | Record<string, unknown>;
  intent_hash: string;
  candidate_intent_hash?: string;
  created_at: string;
  created_at_utc?: string;
  line_items: CartLineItem[];
  items?: CartLineItem[];
  approval_lock?: ApprovalLock | null;
}

export interface AuditEvent {
  id: number;
  event_uid: string;
  audit_event_id?: string;
  request_id?: string | null;
  cart_version_id?: string | null;
  actor_id: string;
  actor_user_id?: string;
  actor_role: string;
  event_type: string;
  summary: string;
  metadata: Record<string, unknown>;
  details?: Record<string, unknown>;
  prev_event_hash: string;
  event_hash: string;
  created_at: string;
  timestamp_utc?: string;
}

export interface PurchaseRequestSummary {
  id: string;
  request_id?: string;
  title: string;
  raw_need_text: string;
  natural_language_need?: string;
  coordinator_id: string;
  coordinator_user_id?: string;
  coordinator_name: string;
  budget_limit_cents?: number | null;
  budget_ceiling_cents?: number | null;
  budget_limit_usd?: string | null;
  status: string;
  active_version_id?: string | null;
  latest_version_number: number;
  current_version_number?: number;
  total_amount_cents: number;
  total_amount_usd: string;
  intent_hash?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PurchaseRequestDetail {
  id: string;
  request_id?: string;
  title: string;
  raw_need_text: string;
  natural_language_need?: string;
  coordinator_id: string;
  coordinator_user_id?: string;
  coordinator_name: string;
  budget_limit_cents?: number | null;
  budget_ceiling_cents?: number | null;
  budget_limit_usd?: string | null;
  status: string;
  active_version_id?: string | null;
  created_at: string;
  updated_at: string;
  active_version?: CartVersion | null;
  versions: CartVersion[];
  approval_locks: ApprovalLock[];
  paypal_orders: PayPalOrder[];
  reconciliations: ReconciliationRecord[];
  audit_events: AuditEvent[];
}

export interface TamperSimulationResult {
  scenario: string;
  blocked: boolean;
  http_status_code: number;
  http_status_simulated?: number;
  error_code: string;
  guardrail_triggered: string;
  explanation: string;
  expected_intent_hash?: string | null;
  tampered_intent_hash?: string | null;
  audit_event_uid: string;
  audit_event_id?: string;
  timestamp: string;
  timestamp_utc?: string;
}

export interface CoordinatorInterview {
  id: string;
  interview_id?: string;
  coordinator_name: string;
  role_title: string;
  team_size: number;
  company_profile?: string;
  recent_purchase_scenario: string;
  primary_workflows?: string;
  baseline_completion_minutes: number;
  baseline_translation_minutes?: number;
  baseline_corrections_count: number;
  baseline_drift_incident: string;
  real_world_drift_incident?: string;
  intentlock_completion_seconds: number;
  intentlock_translation_seconds?: number;
  intentlock_corrections_count: number;
  key_quote: string;
  pain_points: string[];
}

export interface EvalScenarioResult {
  scenario_id: string;
  category: string;
  title: string;
  passed: boolean;
  expected_behavior: string;
  expected_summary?: string;
  observed_behavior: string;
  observed_summary?: string;
  guardrail_verified: string;
  guardrail_tested?: string;
  latency_ms: number;
  details: Record<string, unknown>;
}

export interface EvalSuiteRun {
  run_id: string;
  executed_at: string;
  executed_at_utc?: string;
  total_scenarios: number;
  passed_scenarios: number;
  pass_rate_pct: number;
  sku_f1_score: number;
  pack_math_accuracy_pct: number;
  price_grounding_integrity_pct?: number;
  explanation_completeness_pct?: number;
  guardrail_enforcement_pct: number;
  failover_recovery_pct: number;
  e2e_latency_p95_ms?: number;
  total_duration_ms?: number;
  metrics?: Record<string, any>;
  results: EvalScenarioResult[];
  scenarios?: EvalScenarioResult[];
}

export type EvalSuiteRunResult = EvalSuiteRun;

export interface FailoverDrillHop {
  hop?: number;
  priority?: number;
  provider: string;
  model: string;
  status: string;
  reason?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  latency_ms?: number;
  circuit_action?: string | null;
}

export interface FailoverDrillResponse {
  drill_id?: string;
  drill_status?: string;
  simulated_primary_error?: string;
  simulated_failed_providers?: string[];
  primary_provider_simulated_error?: string;
  fulfilled_by_provider: string;
  fulfilled_by_model: string;
  failover_hops: number;
  latency_ms?: number;
  total_latency_ms?: number;
  failover_trace: FailoverDrillHop[];
  grounded_items?: CartLineItem[];
  total_amount_cents?: number;
  total_amount_usd?: string;
  audit_event_uid?: string;
  router_status?: LLMStatusResponse;
}

export interface LLMProviderStatus {
  priority: number;
  provider: string;
  model: string;
  configured: boolean;
  circuit_state: string;
  failover_ready?: boolean;
  total_calls?: number;
  error_count?: number;
  last_latency_ms: number | null;
}

export interface LLMStatusResponse {
  active_provider: string;
  simulate_primary_failure?: boolean;
  any_live_api_key_configured?: boolean;
  failover_chain?: LLMProviderStatus[];
  providers?: LLMProviderStatus[];
  llm_providers?: LLMProviderStatus[];
  paypal_sandbox?: {
    environment: string;
    api_base_url: string;
    mcp_toolkit_enabled: boolean;
    credentials_configured: boolean;
    client_id?: string;
    client_id_preview?: string | null;
    execution_mode_active?: string;
    mcp_tools?: string[];
    merchant_id: string;
    merchant_name: string;
    currency: string;
    mode?: string;
  };
  paypal_mode?: string;
  paypal_mcp_enabled?: boolean;
  paypal_credentials_configured?: boolean;
}

export interface SystemHealth {
  status: string;
  app_name: string;
  environment: string;
  sqlite_wal_enabled: boolean;
  catalog_sku_count: number;
  merchant_id: string;
  merchant_name: string;
  currency: string;
  audit_chain_verified: boolean;
  audit_events_count: number;
  active_llm_provider: string;
  llm_providers: LLMProviderStatus[];
  paypal_mode: string;
  paypal_mcp_enabled: boolean;
  paypal_credentials_configured: boolean;
}

export interface UpdateKeysPayload {
  gemini_api_key?: string;
  groq_api_key?: string;
  xai_api_key?: string;
  openrouter_api_key?: string;
  openai_api_key?: string;
  paypal_client_id?: string;
  paypal_client_secret?: string;
  simulate_primary_failure?: boolean;
}

export interface StructuredApiError {
  status: number;
  code: string;
  message: string;
  guardrail_violated?: string;
  audit_event_id?: string;
  details?: Record<string, unknown>;
}
