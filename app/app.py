"""FastAPI entry point for the Bank of Canada agent app.

Serves the JSON API under /api and the no-build static UI (static/index.html,
a single-file React app loaded from a CDN) for everything else.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from server.routes import chat, feedback, resources, sessions, user

app = FastAPI(title="Bank of Canada Agent")

app.include_router(user.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(resources.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve the no-build static frontend (single-file React app via CDN).
_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = _STATIC / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC / "index.html")
