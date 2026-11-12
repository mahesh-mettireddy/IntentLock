from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    role = Column(String, nullable=False)  # "COORDINATOR", "APPROVER", "BUYER"
    department = Column(String, nullable=False, default="Operations")
    avatar_badge = Column(String, nullable=False, default="AC")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Product(Base):
    __tablename__ = "products"

    sku = Column(String, primary_key=True, index=True)
    merchant_id = Column(String, nullable=False, default="MERCH-ACME-001")
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    pack_size_desc = Column(String, nullable=False)
    unit_price_cents = Column(Integer, nullable=False)
    stock_available = Column(Integer, nullable=False, default=20)
    recommended_rule = Column(String, nullable=False, default="")
    keywords_json = Column(Text, nullable=False, default="[]")
    is_active = Column(Boolean, nullable=False, default=True)


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    raw_need_text = Column(Text, nullable=False)
    coordinator_id = Column(String, ForeignKey("users.id"), nullable=False)
    budget_limit_cents = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="DRAFT")
    active_version_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    coordinator = relationship("User", foreign_keys=[coordinator_id], lazy="joined")
    cart_versions = relationship(
        "CartVersion",
        back_populates="purchase_request",
        order_by="CartVersion.version_number.asc()",
        cascade="all, delete-orphan",
    )
    approval_locks = relationship(
        "ApprovalLock",
        back_populates="purchase_request",
        order_by="ApprovalLock.issued_at.desc()",
        cascade="all, delete-orphan",
    )
    paypal_orders = relationship(
        "PayPalOrderRecord",
        back_populates="purchase_request",
        order_by="PayPalOrderRecord.created_at.desc()",
        cascade="all, delete-orphan",
    )
    reconciliations = relationship(
        "ReconciliationRecord",
        back_populates="purchase_request",
        order_by="ReconciliationRecord.checked_at.desc()",
        cascade="all, delete-orphan",
    )


class CartVersion(Base):
    __tablename__ = "cart_versions"

    id = Column(String, primary_key=True, index=True)
    request_id = Column(String, ForeignKey("purchase_requests.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="DRAFT")
    created_by_id = Column(String, ForeignKey("users.id"), nullable=False)
    source_prompt = Column(Text, nullable=False, default="")
    agent_summary = Column(Text, nullable=False, default="")
    agent_budget_notes = Column(Text, nullable=False, default="")
    agent_warnings_json = Column(Text, nullable=False, default="[]")
    llm_provider_used = Column(String, nullable=False, default="deterministic_fallback")
    llm_model_used = Column(String, nullable=False, default="intentlock-rule-synthesizer-v1")
    llm_failover_hops = Column(Integer, nullable=False, default=0)
    llm_latency_ms = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="USD")
    merchant_id = Column(String, nullable=False, default="MERCH-ACME-001")
    total_amount_cents = Column(Integer, nullable=False, default=0)
    canonical_payload_json = Column(Text, nullable=False, default="{}")
    intent_hash = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    purchase_request = relationship("PurchaseRequest", back_populates="cart_versions")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="joined")
    line_items = relationship(
        "CartLineItem",
        back_populates="cart_version",
        order_by="CartLineItem.sku.asc()",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    approval_lock = relationship(
        "ApprovalLock",
        back_populates="cart_version",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )
    paypal_orders = relationship(
        "PayPalOrderRecord",
        back_populates="cart_version",
        order_by="PayPalOrderRecord.created_at.desc()",
        cascade="all, delete-orphan",
    )
    reconciliations = relationship(
        "ReconciliationRecord",
        back_populates="cart_version",
        order_by="ReconciliationRecord.checked_at.desc()",
        cascade="all, delete-orphan",
    )


class CartLineItem(Base):
    __tablename__ = "cart_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cart_version_id = Column(String, ForeignKey("cart_versions.id"), nullable=False, index=True)
    sku = Column(String, ForeignKey("products.sku"), nullable=False)
    product_name = Column(String, nullable=False)
    pack_size_desc = Column(String, nullable=False, default="")
    unit_price_cents = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_total_cents = Column(Integer, nullable=False)
    selection_rationale = Column(Text, nullable=False, default="")
    headcount_math = Column(Text, nullable=False, default="")

    cart_version = relationship("CartVersion", back_populates="line_items")
    product = relationship("Product", foreign_keys=[sku], lazy="joined")


class ApprovalLock(Base):
    __tablename__ = "approval_locks"

    id = Column(String, primary_key=True, index=True)
    request_id = Column(String, ForeignKey("purchase_requests.id"), nullable=False, index=True)
    cart_version_id = Column(String, ForeignKey("cart_versions.id"), nullable=False, unique=True, index=True)
    approver_id = Column(String, ForeignKey("users.id"), nullable=False)
    decision = Column(String, nullable=False)  # "APPROVED", "REJECTED"
    comment = Column(Text, nullable=False, default="")
    intent_hash = Column(String, nullable=False)
    approval_signature = Column(String, nullable=False)
    issued_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)

    purchase_request = relationship("PurchaseRequest", back_populates="approval_locks")
    cart_version = relationship("CartVersion", back_populates="approval_lock")
    approver = relationship("User", foreign_keys=[approver_id], lazy="joined")


class PayPalOrderRecord(Base):
    __tablename__ = "paypal_order_records"

    id = Column(String, primary_key=True, index=True)
    request_id = Column(String, ForeignKey("purchase_requests.id"), nullable=False, index=True)
    cart_version_id = Column(String, ForeignKey("cart_versions.id"), nullable=False, index=True)
    paypal_order_id = Column(String, nullable=False, unique=True, index=True)
    paypal_capture_id = Column(String, nullable=True)
    invoice_id = Column(String, nullable=False, unique=True)
    custom_id_intent_hash = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="USD")
    paypal_status = Column(String, nullable=False, default="CREATED")  # "CREATED", "APPROVED", "COMPLETED", "PENDING", "FAILED"
    execution_mode = Column(String, nullable=False, default="PAYPAL_MCP_SANDBOX")  # "PAYPAL_SANDBOX_API" or "PAYPAL_MCP_SANDBOX"
    approval_url = Column(String, nullable=True)
    raw_create_response_json = Column(Text, nullable=False, default="{}")
    raw_capture_response_json = Column(Text, nullable=True)
    created_by_buyer_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    purchase_request = relationship("PurchaseRequest", back_populates="paypal_orders")
    cart_version = relationship("CartVersion", back_populates="paypal_orders")
    buyer = relationship("User", foreign_keys=[created_by_buyer_id], lazy="joined")


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_records"

    id = Column(String, primary_key=True, index=True)
    request_id = Column(String, ForeignKey("purchase_requests.id"), nullable=False, index=True)
    cart_version_id = Column(String, ForeignKey("cart_versions.id"), nullable=False, index=True)
    paypal_order_id = Column(String, nullable=False, index=True)
    verdict = Column(String, nullable=False)  # "VERIFIED_MATCH", "MISMATCH_BLOCKED", "UNCERTAIN_PENDING"
    check_order_completed = Column(Boolean, nullable=False, default=False)
    check_capture_completed = Column(Boolean, nullable=False, default=False)
    check_currency_usd = Column(Boolean, nullable=False, default=False)
    check_amount_exact = Column(Boolean, nullable=False, default=False)
    check_intent_hash_match = Column(Boolean, nullable=False, default=False)
    check_single_purchase_unit = Column(Boolean, nullable=False, default=False)
    approved_amount_cents = Column(Integer, nullable=False)
    captured_amount_cents = Column(Integer, nullable=False)
    approved_intent_hash = Column(String, nullable=False)
    paypal_custom_id_hash = Column(String, nullable=False)
    discrepancy_details_json = Column(Text, nullable=False, default="[]")
    evidence_bundle_sha256 = Column(String, nullable=False)
    evidence_bundle_json = Column(Text, nullable=False, default="{}")
    checked_at = Column(DateTime, nullable=False, default=utcnow)

    purchase_request = relationship("PurchaseRequest", back_populates="reconciliations")
    cart_version = relationship("CartVersion", back_populates="reconciliations")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_uid = Column(String, nullable=False, unique=True, index=True)
    request_id = Column(String, nullable=True, index=True)
    cart_version_id = Column(String, nullable=True, index=True)
    actor_id = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    summary = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    prev_event_hash = Column(String, nullable=False)
    event_hash = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CoordinatorInterview(Base):
    __tablename__ = "coordinator_interviews"

    id = Column(String, primary_key=True, index=True)  # "COORD-INT-01".."03"
    coordinator_name = Column(String, nullable=False)
    role_title = Column(String, nullable=False)
    team_size = Column(Integer, nullable=False)
    recent_purchase_scenario = Column(Text, nullable=False)
    baseline_completion_minutes = Column(Float, nullable=False)
    baseline_corrections_count = Column(Integer, nullable=False)
    baseline_drift_incident = Column(Text, nullable=False)
    intentlock_completion_seconds = Column(Float, nullable=False)
    intentlock_corrections_count = Column(Integer, nullable=False)
    key_quote = Column(Text, nullable=False)
    pain_points_json = Column(Text, nullable=False, default="[]")
