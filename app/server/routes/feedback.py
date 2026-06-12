"""Thumbs up/down feedback -> MLflow assessment on the turn's trace."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..tracing import init_tracing, log_turn_feedback
from .user import current_user_email

router = APIRouter()


class FeedbackRequest(BaseModel):
    trace_id: str
    value: bool  # True = thumbs up, False = thumbs down
    comment: str | None = None


@router.post("/feedback")
def submit_feedback(req: FeedbackRequest, request: Request) -> dict:
    init_tracing()
    user = current_user_email(request)
    log_turn_feedback(req.trace_id, req.value, user, req.comment)
    return {"status": "ok"}
