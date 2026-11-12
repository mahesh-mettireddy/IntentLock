from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User

DEFAULT_COORDINATOR_ID = "user-coord-alice"

PERSONA_ALIASES = {
    "user-coord-alice": "user-coord-alice",
    "USR-COORD-ALICE": "user-coord-alice",
    "usr_coord_01": "user-coord-alice",
    "alice": "user-coord-alice",
    "user-approver-bob": "user-approver-bob",
    "USR-APPR-BOB": "user-approver-bob",
    "usr_appr_01": "user-approver-bob",
    "bob": "user-approver-bob",
    "user-buyer-charlie": "user-buyer-charlie",
    "USR-BUYER-CHARLIE": "user-buyer-charlie",
    "usr_buyer_01": "user-buyer-charlie",
    "charlie": "user-buyer-charlie",
}


def resolve_persona_id(raw_id: str) -> str:
    cleaned = raw_id.strip()
    return PERSONA_ALIASES.get(cleaned, cleaned)


def create_access_token(user: User, expires_hours: int = 24) -> str:
    """Issues an HS256 JWT token signed with settings.INTENTLOCK_SIGNING_SECRET."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "name": user.name,
        "role": user.role,
        "email": user.email,
        "department": user.department,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.INTENTLOCK_SIGNING_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_access_token(token: str) -> dict:
    """Verifies HS256 JWT token and returns claims dict."""
    try:
        return jwt.decode(
            token,
            settings.INTENTLOCK_SIGNING_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token signature or claims.",
        ) from exc


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency resolving the authenticated Persona User.
    Supports:
    1. `Authorization: Bearer <token>` header
    2. `X-Persona-Id` (or `X-Actor-ID`) header validated against `users` table
    3. Defaults to Coordinator Alice (`user-coord-alice`) if neither is present.
    """
    auth_header = request.headers.get("Authorization")
    persona_header = (
        request.headers.get("X-Persona-Id")
        or request.headers.get("X-Actor-ID")
        or request.headers.get("x-persona-id")
    )

    user_id: Optional[str] = None

    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            claims = verify_access_token(token)
            user_id = resolve_persona_id(str(claims.get("sub", "")))

    if not user_id and persona_header:
        user_id = resolve_persona_id(persona_header)

    if not user_id:
        user_id = DEFAULT_COORDINATOR_ID

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Persona user '{user_id}' not found in registered users.",
        )
    return user


def require_role(*allowed_roles: str) -> Callable[[User], User]:
    """
    Strict RBAC dependency factory enforcing that `current_user.role` is in `allowed_roles`.
    """
    normalized_roles = {r.upper() for r in allowed_roles}

    def _role_guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.upper() not in normalized_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ERR_RBAC_ROLE_FORBIDDEN",
                    "message": (
                        f"Access denied: persona '{current_user.name}' ({current_user.role}) "
                        f"is not authorized. Required role(s): {', '.join(sorted(normalized_roles))}."
                    ),
                    "actor_id": current_user.id,
                    "actor_role": current_user.role,
                    "required_roles": sorted(normalized_roles),
                },
            )
        return current_user

    return _role_guard
