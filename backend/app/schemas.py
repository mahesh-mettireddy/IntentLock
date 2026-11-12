from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


def cents_to_usd_str(cents: int) -> str:
    return f"{cents / 100:.2f}"


class PersonaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    role: str
    department: str
    avatar_badge: str
    created_at: Optional[datetime] = None


class SwitchPersonaRequest(BaseModel):
    persona_id: str = Field(..., description="Persona user ID to switch to, e.g., user-coord-alice")


class SwitchPersonaResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int = 86400
    persona: PersonaOut


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    merchant_id: str = "MERCH-ACME-001"
    name: str
    category: str
    pack_size_desc: str
    unit_price_cents: int
    unit_price_usd: str = ""
    stock_available: int
    recommended_rule: str
    keywords: list[str] = Field(default_factory=list)
    is_active: bool = True


class CreatePurchaseRequestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=2, max_length=200)
    raw_need_text: Optional[str] = Field(default=None, max_length=3000)
    natural_language_need: Optional[str] = Field(default=None, max_length=3000)
    budget_limit_cents: Optional[int] = Field(default=None, ge=0, le=5000000)
    budget_ceiling_cents: Optional[int] = Field(default=None, ge=0, le=5000000)


class LineItemEditIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: str
    quantity: int = Field(..., ge=1, le=200)
    selection_rationale: Optional[str] = None
    item_rationale: Optional[str] = None
    headcount_math: Optional[str] = None


class ReviseCartIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    revision_prompt: Optional[str] = None
    revision_instruction: Optional[str] = None
    budget_limit_cents: Optional[int] = Field(default=None, ge=0, le=5000000)
    updated_budget_ceiling_cents: Optional[int] = Field(default=None, ge=0, le=5000000)
    line_item_edits: Optional[list[LineItemEditIn]] = None
    explicit_items: Optional[list[LineItemEditIn]] = None


class CartLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    cart_version_id: Optional[str] = None
    sku: str
    product_name: str
    pack_size_desc: str = ""
    unit_price_cents: int
    unit_price_usd: str = ""
    quantity: int
    line_total_cents: int
    line_total_usd: str = ""
    selection_rationale: str = ""
    headcount_math: str = ""


class ApprovalLockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    cart_version_id: str
    approver_id: str
    approver_name: Optional[str] = None
    decision: str
    comment: str = ""
    intent_hash: str
    approval_signature: str
    issued_at: datetime
    expires_at: datetime
    is_expired: bool = False


class PayPalOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    cart_version_id: str
    paypal_order_id: str
    paypal_capture_id: Optional[str] = None
    invoice_id: str
    custom_id_intent_hash: str
    idempotency_key: str
    amount_cents: int
    amount_usd: str = ""
    currency: str = "USD"
    paypal_status: str
    execution_mode: str
    approval_url: Optional[str] = None
    mcp_trace: Optional[dict[str, Any]] = None
    order_payload: Optional[dict[str, Any]] = None
    created_by_buyer_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class ReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    cart_version_id: str
    paypal_order_id: str
    verdict: str
    check_order_completed: bool
    check_capture_completed: bool
    check_currency_usd: bool
    check_amount_exact: bool
    check_intent_hash_match: bool
    check_single_purchase_unit: bool
    approved_amount_cents: int
    captured_amount_cents: int
    approved_intent_hash: str
    paypal_custom_id_hash: str
    discrepancy_details: list[str] = Field(default_factory=list)
    evidence_bundle_sha256: str
    evidence_bundle: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime


class CartVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    version_number: int
    status: str
    created_by_id: str
    source_prompt: str = ""
    agent_summary: str = ""
    agent_budget_notes: str = ""
    agent_warnings: list[str] = Field(default_factory=list)
    llm_provider_used: str
    llm_model_used: str
    llm_failover_hops: int = 0
    llm_latency_ms: int = 0
    currency: str = "USD"
    merchant_id: str = "MERCH-ACME-001"
    total_amount_cents: int
    total_amount_usd: str = ""
    canonical_payload_json: str
    intent_hash: str
    created_at: datetime
    line_items: list[CartLineItemOut] = Field(default_factory=list)
    approval_lock: Optional[ApprovalLockOut] = None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_uid: str
    request_id: Optional[str] = None
    cart_version_id: Optional[str] = None
    actor_id: str
    actor_role: str
    event_type: str
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    prev_event_hash: str
    event_hash: str
    created_at: datetime


class PurchaseRequestSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    raw_need_text: str
    coordinator_id: str
    coordinator_name: str = ""
    budget_limit_cents: Optional[int] = None
    budget_limit_usd: Optional[str] = None
    status: str
    active_version_id: Optional[str] = None
    latest_version_number: int = 1
    total_amount_cents: int = 0
    total_amount_usd: str = "0.00"
    intent_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PurchaseRequestDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    raw_need_text: str
    coordinator_id: str
    coordinator_name: str = ""
    budget_limit_cents: Optional[int] = None
    budget_limit_usd: Optional[str] = None
    status: str
    active_version_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    active_version: Optional[CartVersionOut] = None
    versions: list[CartVersionOut] = Field(default_factory=list)
    approval_locks: list[ApprovalLockOut] = Field(default_factory=list)
    paypal_orders: list[PayPalOrderOut] = Field(default_factory=list)
    reconciliations: list[ReconciliationOut] = Field(default_factory=list)
    audit_events: list[AuditEventOut] = Field(default_factory=list)


class ApproveCartIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    comment: Optional[str] = Field(default="Approved after line-item and budget review.", max_length=1000)
    approval_note: Optional[str] = Field(default=None, max_length=1000)
    ttl_minutes: Optional[int] = Field(default=30, ge=1, le=1440)
    approval_ttl_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    expected_intent_hash: Optional[str] = None


class RejectCartIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    comment: Optional[str] = Field(default=None, max_length=1000)
    rejection_reason: Optional[str] = Field(default=None, max_length=1000)


class CreatePayPalOrderIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expected_intent_hash: Optional[str] = None
    idempotency_key: Optional[str] = None
    idempotency_hint: Optional[str] = None
    execution_mode: str = Field(default="PAYPAL_MCP_SANDBOX")


class CapturePayPalOrderIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paypal_order_id: Optional[str] = None
    expected_intent_hash: Optional[str] = None
    payer_id: Optional[str] = "SANDBOX-BUYER-001"


class UpdateKeysIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    paypal_client_id: Optional[str] = None
    paypal_client_secret: Optional[str] = None
    simulate_primary_failure: Optional[bool] = None
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    XAI_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None


class TamperSimulationIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: Optional[str] = None
    cart_version_id: Optional[str] = None
    scenario: str = Field(
        ...,
        description=(
            "Supports all tamper aliases: CART_DRIFT_TOCTOU / TAMPER_CART_POST_APPROVAL / TAMPER_QUANTITY_POST_APPROVAL, "
            "SELF_APPROVAL_SOD / COORDINATOR_SELF_APPROVAL, EXPIRED_APPROVAL_REPLAY / EXPIRED_APPROVAL_CAPTURE / EXPIRED_LOCK_CAPTURE, "
            "MANUAL_PROVIDER_OVERRIDE / OPERATOR_FAKE_PAYMENT_OVERRIDE / PAYPAL_CUSTOM_ID_MISMATCH, "
            "PROMPT_INJECTION_PRICE_OVERRIDE / TAMPER_PRICE_OVERRIDE"
        ),
    )


class TamperSimulationOut(BaseModel):
    scenario: str
    blocked: bool
    http_status_code: int
    http_status_simulated: Optional[int] = None
    error_code: str
    guardrail_triggered: str
    explanation: str
    expected_intent_hash: Optional[str] = None
    tampered_intent_hash: Optional[str] = None
    audit_event_uid: str
    audit_event_id: Optional[str] = None
    timestamp: datetime
    timestamp_utc: Optional[str] = None


class CoordinatorInterviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    coordinator_name: str
    role_title: str
    team_size: int
    recent_purchase_scenario: str
    baseline_completion_minutes: float
    baseline_corrections_count: int
    baseline_drift_incident: str
    intentlock_completion_seconds: float
    intentlock_corrections_count: int
    key_quote: str
    pain_points: list[str] = Field(default_factory=list)


class EvalScenarioResultOut(BaseModel):
    scenario_id: str
    category: str
    title: str
    passed: bool
    expected_behavior: str
    observed_behavior: str
    guardrail_verified: str
    latency_ms: float
    details: dict[str, Any] = Field(default_factory=dict)


class EvalSuiteRunOut(BaseModel):
    run_id: str
    executed_at: datetime
    total_scenarios: int
    passed_scenarios: int
    pass_rate_pct: float
    sku_f1_score: float
    pack_math_accuracy_pct: float
    price_grounding_integrity_pct: float = 100.0
    explanation_completeness_pct: float = 100.0
    guardrail_enforcement_pct: float
    failover_recovery_pct: float
    e2e_latency_p95_ms: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)
    results: list[EvalScenarioResultOut] = Field(default_factory=list)


class LLMProviderStatusOut(BaseModel):
    priority: int
    provider: str
    model: str
    configured: bool
    circuit_state: str = "CLOSED"
    failover_ready: bool = True
    total_calls: int = 0
    error_count: int = 0
    last_latency_ms: Optional[int] = None


class SystemHealthOut(BaseModel):
    status: str = "healthy"
    app_name: str = "IntentLock"
    environment: str = "development"
    sqlite_wal_enabled: bool = True
    catalog_sku_count: int = 15
    merchant_id: str = "MERCH-ACME-001"
    merchant_name: str = "Acme Workspace Supplies"
    currency: str = "USD"
    audit_chain_verified: bool = True
    audit_events_count: int = 0
    active_llm_provider: str = "gemini"
    llm_providers: list[LLMProviderStatusOut] = Field(default_factory=list)
    paypal_mode: str = "sandbox"
    paypal_mcp_enabled: bool = True
    paypal_credentials_configured: bool = False
