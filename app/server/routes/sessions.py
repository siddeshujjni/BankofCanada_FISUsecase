"""Per-user session history from MLflow traces."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ..turn_log import list_sessions as tl_list_sessions
from ..turn_log import load_session as tl_load_session
from .user import current_user_email

logger = logging.getLogger("boc.sessions")
router = APIRouter()


@router.get("/sessions")
def list_sessions(request: Request) -> dict:
    """Per-user conversations from the durable UC turn log."""
    user = current_user_email(request)
    sessions = tl_list_sessions(user)
    return {"user": user, "count": len(sessions), "sessions": sessions}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    user = current_user_email(request)
    return {"session_id": session_id, "turns": tl_load_session(session_id, user)}
