import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ApprovalLock, CartVersion, PurchaseRequest, User
from . import cart_hash_service, guardrails
from .audit_service import record_audit_event
from .guardrails import GuardrailViolationError


def _get_request_and_version(
    db: Session,
    request_id: str,
    version_id: str,
) -> tuple[PurchaseRequest, CartVersion]:
    purchase_request = (
        db.query(PurchaseRequest)
        .filter(PurchaseRequest.id == request_id)
        .first()
    )
    if not purchase_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PurchaseRequest '{request_id}' not found.",
        )

    cart_version = (
        db.query(CartVersion)
        .filter(
            CartVersion.id == version_id,
            CartVersion.request_id == request_id,
        )
        .first()
    )
    if not cart_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CartVersion '{version_id}' not found under PurchaseRequest '{request_id}'.",
        )

    return purchase_request, cart_version


def submit_version_for_approval(
    db: Session,
    request_id: str,
    version_id: str,
    actor: User,
) -> CartVersion:
    """
    Transitions a `DRAFT` or `REJECTED` CartVersion to `SUBMITTED_FOR_APPROVAL`.
    - Verifies `cart_version` belongs to `request_id` and is in `DRAFT` or `REJECTED` state.
    - Verifies `actor.role == "COORDINATOR"`.
    - Re-verifies canonical `intent_hash` integrity via `cart_hash_service`.
    - Transitions `cart_version.status = "SUBMITTED_FOR_APPROVAL"` and
      `purchase_request.status = "SUBMITTED"`, `purchase_request.active_version_id = version_id`.
    - Emits `CART_SUBMITTED_FOR_APPROVAL` audit event.
    """
    purchase_request, cart_version = _get_request_and_version(db, request_id, version_id)

    if (actor.role or "").upper() != "COORDINATOR":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only a COORDINATOR can submit a cart version for approval "
                f"(current actor '{actor.name}' has role '{actor.role}')."
            ),
        )

    if cart_version.status not in ("DRAFT", "REJECTED", "SUBMITTED_FOR_APPROVAL"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"CartVersion '{version_id}' is in status '{cart_version.status}' and cannot be "
                "submitted for approval (must be 'DRAFT' or 'REJECTED')."
            ),
        )

    is_valid, discrepancies = cart_hash_service.verify_cart_integrity(
        cart_version=cart_version,
        line_items=list(cart_version.line_items),
        approval_lock=None,
    )
    if not is_valid:
        audit_ev = record_audit_event(
            db=db,
            actor_id=actor.id,
            actor_role=actor.role,
            event_type="GUARDRAIL_BLOCKED_CART_DRIFT",
            summary=(
                f"Guardrail G-05 blocked submission of CartVersion {cart_version.id}: "
                f"{'; '.join(discrepancies)}"
            ),
            request_id=request_id,
            cart_version_id=version_id,
            metadata={"discrepancies": discrepancies, "guardrail_id": "G-05"},
        )
        db.commit()
        err = GuardrailViolationError(
            code="INTENT_HASH_DRIFT_DETECTED",
            message=f"Canonical cart hash verification failed on submission: {'; '.join(discrepancies)}",
            guardrail_id="G-05",
            metadata={"discrepancies": discrepancies, "audit_event_id": audit_ev.event_uid},
            http_status=409,
        )
        setattr(err, "audit_event_id", audit_ev.event_uid)
        raise err

    cart_version.status = "SUBMITTED_FOR_APPROVAL"
    purchase_request.status = "SUBMITTED"
    purchase_request.active_version_id = cart_version.id
    purchase_request.updated_at = datetime.now(timezone.utc)

    record_audit_event(
        db=db,
        actor_id=actor.id,
        actor_role=actor.role,
        event_type="CART_SUBMITTED_FOR_APPROVAL",
        summary=(
            f"Coordinator {actor.name} submitted CartVersion v{cart_version.version_number} "
            f"(${cart_version.total_amount_cents / 100:.2f} USD) for managerial approval."
        ),
        request_id=request_id,
        cart_version_id=version_id,
        metadata={
            "version_number": cart_version.version_number,
            "total_amount_cents": cart_version.total_amount_cents,
            "intent_hash": cart_version.intent_hash,
        },
    )
    db.commit()
    db.refresh(cart_version)
    return cart_version


def approve_cart_version(
    db: Session,
    request_id: str,
    version_id: str,
    actor: User,
    comment: str = "",
    ttl_minutes: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
    expected_intent_hash: Optional[str] = None,
) -> ApprovalLock:
    """
    Approves and cryptographically locks a submitted CartVersion:
    - Enforces Guardrail G-04 (Separation of Duties) via `guardrails.enforce_separation_of_duties`.
      If `actor.id == purchase_request.coordinator_id` or `actor.role != "APPROVER"`, logs a
      `GUARDRAIL_BLOCKED_SELF_APPROVAL` audit event and raises `GuardrailViolationError` (HTTP 403).
    - Verifies `cart_version.status == "SUBMITTED_FOR_APPROVAL"`.
    - Enforces Guardrail G-05 (Canonical Hash Verification): recomputes canonical JSON and `intent_hash`
      from `CartLineItem` rows and verifies exact match with `cart_version.intent_hash`.
    - Computes `issued_at = datetime.now(timezone.utc)` and
      `expires_at = issued_at + timedelta(minutes=ttl_minutes or settings.DEFAULT_APPROVAL_TTL_MINUTES)`.
    - Computes `approval_signature = cart_hash_service.compute_approval_signature(...)`.
    - Creates/updates `ApprovalLock` with `decision="APPROVED"`, transitions
      `cart_version.status = "APPROVED_LOCKED"`, `purchase_request.status = "APPROVED_LOCKED"`.
    - Emits `CART_VERSION_APPROVED_LOCKED` audit event containing `intent_hash`, `approval_signature`, and `expires_at`.
    """
    purchase_request, cart_version = _get_request_and_version(db, request_id, version_id)

    # 1. Guardrail G-04: Separation of Duties
    try:
        guardrails.enforce_separation_of_duties(
            coordinator_id=purchase_request.coordinator_id,
            approver_user_id=actor.id,
            approver_role=actor.role,
        )
    except GuardrailViolationError as exc:
        audit_ev = record_audit_event(
            db=db,
            actor_id=actor.id,
            actor_role=actor.role,
            event_type="GUARDRAIL_BLOCKED_SELF_APPROVAL",
            summary=(
                f"Guardrail G-04 blocked self-approval / unauthorized role approval on "
                f"{request_id} ({version_id}) by {actor.name} ({actor.role})."
            ),
            request_id=request_id,
            cart_version_id=version_id,
            metadata={
                "guardrail_id": "G-04",
                "coordinator_id": purchase_request.coordinator_id,
                "attempted_approver_id": actor.id,
                "attempted_approver_role": actor.role,
            },
        )
        db.commit()
        exc.metadata["audit_event_id"] = audit_ev.event_uid
        setattr(exc, "audit_event_id", audit_ev.event_uid)
        raise exc

    # 2. Verify CartVersion status
    if cart_version.status != "SUBMITTED_FOR_APPROVAL":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"CartVersion '{version_id}' must be in 'SUBMITTED_FOR_APPROVAL' state to be approved "
                f"(current status: '{cart_version.status}')."
            ),
        )

    # 3. Guardrail G-05: Canonical Hash Verification
    is_valid, discrepancies = cart_hash_service.verify_cart_integrity(
        cart_version=cart_version,
        line_items=list(cart_version.line_items),
        approval_lock=None,
    )
    if expected_intent_hash and expected_intent_hash.strip() != cart_version.intent_hash:
        is_valid = False
        discrepancies.append(
            f"Approver expected_intent_hash '{expected_intent_hash}' does not match "
            f"cart_version.intent_hash '{cart_version.intent_hash}'."
        )

    if not is_valid:
        audit_ev = record_audit_event(
            db=db,
            actor_id=actor.id,
            actor_role=actor.role,
            event_type="GUARDRAIL_BLOCKED_CART_DRIFT",
            summary=(
                f"Guardrail G-05 blocked approval of CartVersion {version_id} due to canonical hash drift: "
                f"{'; '.join(discrepancies)}"
            ),
            request_id=request_id,
            cart_version_id=version_id,
            metadata={
                "guardrail_id": "G-05",
                "discrepancies": discrepancies,
                "cart_intent_hash": cart_version.intent_hash,
                "expected_intent_hash": expected_intent_hash,
            },
        )
        db.commit()
        err = GuardrailViolationError(
            code="INTENT_HASH_DRIFT_DETECTED",
            message=(
                "Guardrail G-05 Violation: Canonical cart hash verification failed prior to approval lock "
                f"({'; '.join(discrepancies)})."
            ),
            guardrail_id="G-05",
            metadata={
                "cart_version_id": cart_version.id,
                "discrepancies": discrepancies,
                "audit_event_id": audit_ev.event_uid,
            },
            http_status=409,
        )
        setattr(err, "audit_event_id", audit_ev.event_uid)
        raise err

    # 4. Mint HMAC-SHA256 ApprovalLock with TTL
    effective_ttl = int(ttl_minutes if ttl_minutes is not None else settings.DEFAULT_APPROVAL_TTL_MINUTES)
    issued_at = datetime.now(timezone.utc)
    if ttl_seconds is not None and int(ttl_seconds) > 0:
        expires_at = issued_at + timedelta(seconds=int(ttl_seconds))
    else:
        expires_at = issued_at + timedelta(minutes=effective_ttl)

    approval_signature = cart_hash_service.compute_approval_signature(
        cart_version_id=cart_version.id,
        intent_hash=cart_version.intent_hash,
        approver_id=actor.id,
        issued_at_iso=cart_hash_service.format_utc_iso(issued_at),
        expires_at_iso=cart_hash_service.format_utc_iso(expires_at),
    )

    existing_lock = (
        db.query(ApprovalLock)
        .filter(ApprovalLock.cart_version_id == cart_version.id)
        .first()
    )
    clean_comment = (comment or "Approved after line-item and budget review.").strip()

    if existing_lock:
        existing_lock.approver_id = actor.id
        existing_lock.decision = "APPROVED"
        existing_lock.comment = clean_comment
        existing_lock.intent_hash = cart_version.intent_hash
        existing_lock.approval_signature = approval_signature
        existing_lock.issued_at = issued_at
        existing_lock.expires_at = expires_at
        approval_lock = existing_lock
    else:
        approval_lock = ApprovalLock(
            id=f"APR-{uuid.uuid4().hex[:10].upper()}",
            request_id=request_id,
            cart_version_id=cart_version.id,
            approver_id=actor.id,
            decision="APPROVED",
            comment=clean_comment,
            intent_hash=cart_version.intent_hash,
            approval_signature=approval_signature,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        db.add(approval_lock)

    cart_version.status = "APPROVED_LOCKED"
    purchase_request.status = "APPROVED_LOCKED"
    purchase_request.active_version_id = cart_version.id
    purchase_request.updated_at = issued_at
    db.flush()

    record_audit_event(
        db=db,
        actor_id=actor.id,
        actor_role=actor.role,
        event_type="CART_VERSION_APPROVED_LOCKED",
        summary=(
            f"Approver {actor.name} approved & locked CartVersion v{cart_version.version_number} "
            f"(${cart_version.total_amount_cents / 100:.2f} USD). Minted ApprovalLock {approval_lock.id}."
        ),
        request_id=request_id,
        cart_version_id=version_id,
        metadata={
            "approval_lock_id": approval_lock.id,
            "intent_hash": cart_version.intent_hash,
            "approval_signature": approval_signature,
            "issued_at": cart_hash_service.format_utc_iso(issued_at),
            "expires_at": cart_hash_service.format_utc_iso(expires_at),
            "ttl_minutes": effective_ttl,
            "comment": clean_comment,
        },
    )
    db.commit()
    db.refresh(approval_lock)
    return approval_lock


def reject_cart_version(
    db: Session,
    request_id: str,
    version_id: str,
    actor: User,
    reason: str,
) -> ApprovalLock:
    """
    Rejects a submitted CartVersion:
    - Enforces `actor.role == "APPROVER"` and `actor.id != purchase_request.coordinator_id`.
    - Creates/updates `ApprovalLock` with `decision="REJECTED"`, transitions
      `cart_version.status = "REJECTED"`, `purchase_request.status = "REJECTED"`.
    - Emits `CART_VERSION_REJECTED` audit event.
    """
    purchase_request, cart_version = _get_request_and_version(db, request_id, version_id)

    try:
        guardrails.enforce_separation_of_duties(
            coordinator_id=purchase_request.coordinator_id,
            approver_user_id=actor.id,
            approver_role=actor.role,
        )
    except GuardrailViolationError as exc:
        audit_ev = record_audit_event(
            db=db,
            actor_id=actor.id,
            actor_role=actor.role,
            event_type="GUARDRAIL_BLOCKED_SELF_APPROVAL",
            summary=(
                f"Guardrail G-04 blocked unauthorized rejection attempt on {request_id} ({version_id}) "
                f"by {actor.name} ({actor.role})."
            ),
            request_id=request_id,
            cart_version_id=version_id,
            metadata={
                "guardrail_id": "G-04",
                "coordinator_id": purchase_request.coordinator_id,
                "actor_id": actor.id,
                "actor_role": actor.role,
            },
        )
        db.commit()
        exc.metadata["audit_event_id"] = audit_ev.event_uid
        setattr(exc, "audit_event_id", audit_ev.event_uid)
        raise exc

    if cart_version.status not in ("SUBMITTED_FOR_APPROVAL", "APPROVED_LOCKED", "DRAFT"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"CartVersion '{version_id}' in status '{cart_version.status}' cannot be rejected."
            ),
        )

    now = datetime.now(timezone.utc)
    clean_reason = (reason or "Rejected by approver.").strip()
    sig = cart_hash_service.compute_approval_signature(
        cart_version_id=cart_version.id,
        intent_hash=cart_version.intent_hash,
        approver_id=actor.id,
        issued_at_iso=cart_hash_service.format_utc_iso(now),
        expires_at_iso=cart_hash_service.format_utc_iso(now),
    )

    existing_lock = (
        db.query(ApprovalLock)
        .filter(ApprovalLock.cart_version_id == cart_version.id)
        .first()
    )
    if existing_lock:
        existing_lock.approver_id = actor.id
        existing_lock.decision = "REJECTED"
        existing_lock.comment = clean_reason
        existing_lock.intent_hash = cart_version.intent_hash
        existing_lock.approval_signature = sig
        existing_lock.issued_at = now
        existing_lock.expires_at = now
        approval_lock = existing_lock
    else:
        approval_lock = ApprovalLock(
            id=f"APR-{uuid.uuid4().hex[:10].upper()}",
            request_id=request_id,
            cart_version_id=cart_version.id,
            approver_id=actor.id,
            decision="REJECTED",
            comment=clean_reason,
            intent_hash=cart_version.intent_hash,
            approval_signature=sig,
            issued_at=now,
            expires_at=now,
        )
        db.add(approval_lock)

    cart_version.status = "REJECTED"
    purchase_request.status = "REJECTED"
    purchase_request.updated_at = now
    db.flush()

    record_audit_event(
        db=db,
        actor_id=actor.id,
        actor_role=actor.role,
        event_type="CART_VERSION_REJECTED",
        summary=(
            f"Approver {actor.name} rejected CartVersion v{cart_version.version_number}: {clean_reason}"
        ),
        request_id=request_id,
        cart_version_id=version_id,
        metadata={
            "approval_lock_id": approval_lock.id,
            "decision": "REJECTED",
            "reason": clean_reason,
            "intent_hash": cart_version.intent_hash,
        },
    )
    db.commit()
    db.refresh(approval_lock)
    return approval_lock
