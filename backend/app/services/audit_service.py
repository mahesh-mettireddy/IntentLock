import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy.orm import Session

from ..models import AuditEvent

GENESIS_HASH = "GENESIS_" + "0" * 56

# ---------------------------------------------------------------------------
# SEC-GAP-06: Secret & Token Redaction Filter (T-06)
# ---------------------------------------------------------------------------

_SECRET_TOKEN_PATTERNS: list[re.Pattern] = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"xai-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"sk-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"Bearer\s+[0-9A-Za-z\-._~+/]+=*", re.IGNORECASE),
]

_SENSITIVE_KEY_NAMES: set[str] = {
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "access_token",
    "authorization",
    "secret_key",
    "signing_secret",
}


def scrub_secrets_from_text(text: str) -> str:
    """
    Masks any string matching API key or Bearer token patterns (`AIza...`, `gsk_...`,
    `xai-...`, `sk-...`, `Bearer ...`) with `"[REDACTED_SECRET]"`.
    """
    if not text or not isinstance(text, str):
        return text
    scrubbed = text
    for pattern in _SECRET_TOKEN_PATTERNS:
        if pattern.search(scrubbed):
            scrubbed = pattern.sub("[REDACTED_SECRET]", scrubbed)
    return scrubbed


def scrub_secrets_from_obj(obj: Any) -> Any:
    """
    Recursively scrubs secrets and sensitive keys (`api_key`, `client_secret`, `password`,
    `access_token`, `authorization`) from dictionaries, lists, tuples, and strings.
    """
    if isinstance(obj, str):
        return scrub_secrets_from_text(obj)
    if isinstance(obj, dict):
        cleaned: dict[Any, Any] = {}
        for k, v in obj.items():
            key_str = str(k).strip().lower()
            if key_str in _SENSITIVE_KEY_NAMES and v is not None and v != "":
                cleaned[k] = "[REDACTED_SECRET]"
            else:
                cleaned[k] = scrub_secrets_from_obj(v)
        return cleaned
    if isinstance(obj, list):
        return [scrub_secrets_from_obj(item) for item in obj]
    if isinstance(obj, tuple):
        return [scrub_secrets_from_obj(item) for item in obj]
    return obj


def _format_timestamp_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _compute_audit_hash(
    prev_event_hash: str,
    event_uid: str,
    actor_id: str,
    actor_role: str,
    event_type: str,
    request_id: Optional[str],
    cart_version_id: Optional[str],
    canonical_metadata: str,
    timestamp_iso: str,
) -> str:
    payload = (
        f"{prev_event_hash}|{event_uid}|{actor_id}|{actor_role}|"
        f"{event_type}|{request_id}|{cart_version_id}|{canonical_metadata}|{timestamp_iso}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_audit_event(
    db: Session,
    actor_id: str,
    actor_role: str,
    event_type: str,
    summary: str,
    request_id: Optional[str] = None,
    cart_version_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    """
    Appends a cryptographically hash-chained audit event to the `audit_events` ledger.
    Computes `prev_event_hash` from the most recent `AuditEvent` row (or `"GENESIS_" + "0"*56`).
    Applies `SEC-GAP-06` secret and token redaction on both `summary` and `metadata`.
    """
    last_event = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
    prev_event_hash = last_event.event_hash if last_event else GENESIS_HASH

    event_uid = f"AUD-{uuid.uuid4().hex[:12].upper()}"
    created_at = datetime.now(timezone.utc)
    timestamp_iso = _format_timestamp_iso(created_at)

    clean_summary = scrub_secrets_from_text(summary)
    raw_meta_dict = dict(metadata) if metadata else {}
    meta_dict = scrub_secrets_from_obj(raw_meta_dict)
    if not isinstance(meta_dict, dict):
        meta_dict = {}
    meta_dict["_ts_iso"] = timestamp_iso
    canonical_metadata = json.dumps(meta_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    event_hash = _compute_audit_hash(
        prev_event_hash=prev_event_hash,
        event_uid=event_uid,
        actor_id=actor_id,
        actor_role=actor_role,
        event_type=event_type,
        request_id=request_id,
        cart_version_id=cart_version_id,
        canonical_metadata=canonical_metadata,
        timestamp_iso=timestamp_iso,
    )

    event = AuditEvent(
        event_uid=event_uid,
        request_id=request_id,
        cart_version_id=cart_version_id,
        actor_id=actor_id,
        actor_role=actor_role,
        event_type=event_type,
        summary=clean_summary,
        metadata_json=canonical_metadata,
        prev_event_hash=prev_event_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    return event


def verify_audit_chain(db: Session, request_id: Optional[str] = None) -> tuple[bool, int]:
    """
    Verifies the integrity of the global append-only audit hash chain.
    If `request_id` is passed, verifies the global chain and returns `(is_valid, count_for_request_or_total)`.
    """
    all_events = db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()
    if not all_events:
        return True, 0

    expected_prev = GENESIS_HASH
    matched_count = 0

    for ev in all_events:
        if ev.prev_event_hash != expected_prev:
            return False, matched_count

        try:
            meta = json.loads(ev.metadata_json) if ev.metadata_json else {}
        except Exception:
            meta = {}

        timestamp_iso = meta.get("_ts_iso") or _format_timestamp_iso(ev.created_at)
        canonical_metadata = ev.metadata_json or "{}"

        recomputed_hash = _compute_audit_hash(
            prev_event_hash=ev.prev_event_hash,
            event_uid=ev.event_uid,
            actor_id=ev.actor_id,
            actor_role=ev.actor_role,
            event_type=ev.event_type,
            request_id=ev.request_id,
            cart_version_id=ev.cart_version_id,
            canonical_metadata=canonical_metadata,
            timestamp_iso=timestamp_iso,
        )
        if recomputed_hash != ev.event_hash:
            return False, matched_count

        expected_prev = ev.event_hash
        if request_id is None or ev.request_id == request_id:
            matched_count += 1

    return True, matched_count
