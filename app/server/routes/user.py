"""Logged-in user identity, derived from Databricks Apps headers."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def current_user_email(request: Request) -> str:
    """Resolve the end-user email.

    In Databricks Apps the platform injects the authenticated user via
    `X-Forwarded-Email`. Locally we fall back to a dev identity.
    """
    return (
        request.headers.get("X-Forwarded-Email")
        or request.headers.get("X-Forwarded-User")
        or "local-dev@databricks.com"
    )


@router.get("/user")
def get_user(request: Request) -> dict:
    email = current_user_email(request)
    return {
        "email": email,
        "name": request.headers.get("X-Forwarded-Preferred-Username") or email.split("@")[0],
    }
