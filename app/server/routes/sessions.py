"""Per-user session history from MLflow traces."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ..tracing import init_tracing, list_user_sessions, load_session
from .user import current_user_email

logger = logging.getLogger("boc.sessions")
router = APIRouter()


@router.get("/sessions")
def list_sessions(request: Request) -> dict:
    init_tracing()
    user = current_user_email(request)
    try:
        sessions = list_user_sessions(user)
        return {"user": user, "count": len(sessions), "sessions": sessions}
    except Exception as e:  # noqa: BLE001
        logger.exception("list_sessions failed")
        return {"user": user, "count": 0, "sessions": [], "error": str(e)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    init_tracing()
    user = current_user_email(request)
    return {"session_id": session_id, "turns": load_session(session_id, user)}
