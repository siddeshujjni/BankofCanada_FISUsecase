"""Per-user session history from MLflow traces."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..tracing import init_tracing, list_user_sessions, load_session
from .user import current_user_email

router = APIRouter()


@router.get("/sessions")
def list_sessions(request: Request) -> dict:
    init_tracing()
    user = current_user_email(request)
    return {"sessions": list_user_sessions(user)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    init_tracing()
    user = current_user_email(request)
    return {"session_id": session_id, "turns": load_session(session_id, user)}
