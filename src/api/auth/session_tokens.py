from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from src.models.database import User
from src.services.auth.service import AuthService
from src.services.auth.session_service import SessionService
from src.utils.request_utils import get_client_ip, get_user_agent


def issue_session_bound_tokens(
    *,
    db: Session,
    user: User,
    request: Request,
) -> tuple[str, str]:
    session_id = str(uuid.uuid4())
    access_token = AuthService.create_access_token(
        data={
            "user_id": user.id,
            "role": user.role.value,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "session_id": session_id,
        }
    )
    refresh_token = AuthService.create_refresh_token(
        data={
            "user_id": user.id,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "session_id": session_id,
            "jti": str(uuid.uuid4()),
        }
    )

    client_device_id = SessionService.extract_client_device_id(request)
    client_context = SessionService.build_client_context(
        client_device_id=client_device_id,
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
        headers=dict(request.headers),
    )
    SessionService.create_session(
        db,
        user=user,
        session_id=session_id,
        refresh_token=refresh_token,
        expires_at=AuthService.get_refresh_token_expiry(),
        client=client_context,
    )
    return access_token, refresh_token
