"""Durable, queryable agent-turn logging to a Unity Catalog Delta table.

Why not rely solely on MLflow traces? The Databricks Apps runtime for this
workspace cannot reach the cloud object-storage host that MLflow 3's default
trace exporter uploads span artifacts to (connection refused), so traces created
in-app do not persist. The SQL warehouse and Unity Catalog, however, ARE
reachable from the app (the catalog endpoints prove it). So we additionally write
one governed, queryable row per turn — capturing the router/deep path, the tools
called, and timing — into ``{metadata_schema}.agent_turns``. This powers the
in-app session history and gives analysts a SQL/dashboards view of agent usage.

MLflow tracing (spans over the router + deep-analyst LLM calls) remains enabled;
where the runtime can reach trace storage (local dev, notebooks) it also persists.
"""
from __future__ import annotations

import json
import logging
import uuid

from .config import get_settings
from .sql import run_sql

logger = logging.getLogger("boc.turnlog")

_ensured = False


def _table() -> str:
    s = get_settings()
    return f"{s.catalog}.{s.metadata_schema}.agent_turns"


def _ensure_table() -> None:
    global _ensured
    if _ensured:
        return
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {_table()} (
            turn_id STRING, session_id STRING, user_email STRING,
            ts TIMESTAMP, message STRING, answer STRING,
            mode STRING, tools_used STRING, trace_id STRING, latency_ms BIGINT
        )
        COMMENT 'One row per agent turn: the user message, the answer, whether it was
        answered by the fast router or escalated to the deep analyst, the governed
        tools invoked, and latency. Queryable observability for the FIS returns agent.'
    """)
    _ensured = True


def new_turn_id() -> str:
    return uuid.uuid4().hex


def log_turn(*, turn_id: str, session_id: str, user: str, message: str, answer: str,
             mode: str, tools_used: list[str], trace_id: str | None,
             latency_ms: int) -> None:
    """Insert one turn row (values bound as parameters, never interpolated — safe
    against quotes/backslashes/injection). Best-effort: never breaks the response."""
    try:
        _ensure_table()
        run_sql(
            f"""
            INSERT INTO {_table()}
            (turn_id, session_id, user_email, ts, message, answer, mode, tools_used, trace_id, latency_ms)
            VALUES (:turn_id, :session_id, :user_email, current_timestamp(),
                    :message, :answer, :mode, :tools_used, :trace_id, :latency_ms)
            """,
            params={
                "turn_id": turn_id, "session_id": session_id, "user_email": user,
                "message": message[:4000], "answer": answer[:16000], "mode": mode,
                "tools_used": ",".join(dict.fromkeys(tools_used)),
                "trace_id": trace_id or "", "latency_ms": int(latency_ms),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("log_turn failed")


def list_sessions(user: str) -> list[dict]:
    """Sessions for a user (newest first), from the turn log."""
    try:
        rows = run_sql(
            f"""
            SELECT session_id, min_by(message, ts) AS title, max(ts) AS updated_at
            FROM {_table()}
            WHERE user_email = :user
            GROUP BY session_id
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            params={"user": user},
        )
        return [{"session_id": r["session_id"], "title": (r.get("title") or "Conversation")[:120]}
                for r in rows if r.get("session_id")]
    except Exception:  # noqa: BLE001
        logger.exception("list_sessions failed")
        return []


def load_session(session_id: str, user: str) -> list[dict]:
    """Ordered turns for a session, reconstructed from the turn log."""
    try:
        rows = run_sql(
            f"""
            SELECT message, answer, trace_id, ts
            FROM {_table()}
            WHERE session_id = :session_id AND user_email = :user
            ORDER BY ts
            """,
            params={"session_id": session_id, "user": user},
        )
    except Exception:  # noqa: BLE001
        logger.exception("load_session failed")
        return []
    turns: list[dict] = []
    for r in rows:
        if r.get("message"):
            turns.append({"role": "user", "content": r["message"]})
        if r.get("answer"):
            turns.append({"role": "assistant", "content": r["answer"],
                          "references": [], "trace_id": r.get("trace_id")})
    return turns
