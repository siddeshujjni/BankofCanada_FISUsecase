"""MLflow tracing, sessions, per-user history, and feedback.

Conventions:
  * Each chat turn is one trace. We tag it with custom tags `session_id`,
    `user_email`, and `title` (reliable to filter/group on) and also set the
    standard MLflow session/user so the MLflow UI groups conversations.
  * Per-user history filters on `tags.user_email`; conversations are grouped by
    `tags.session_id`.
  * Feedback is logged as an MLflow assessment on the turn's trace.

Security: callers must pass the server-derived user email; never trust the
browser.
"""
from __future__ import annotations

import functools
import logging
import uuid
from datetime import datetime, timezone

import mlflow

from .config import get_settings

logger = logging.getLogger("boc.tracing")


@functools.lru_cache(maxsize=1)
def init_tracing() -> str:
    """Point MLflow at the workspace experiment and enable OpenAI autolog."""
    s = get_settings()
    mlflow.set_tracking_uri("databricks" if s.is_app else f"databricks://{s.profile}")
    if s.mlflow_experiment_id:
        mlflow.set_experiment(experiment_id=s.mlflow_experiment_id)
    try:
        mlflow.openai.autolog()
    except Exception:  # noqa: BLE001
        pass
    return s.mlflow_experiment_id


def new_session_id() -> str:
    return uuid.uuid4().hex


def tag_turn(session_id: str, user: str, title: str) -> None:
    """Tag the active trace with session/user/title/timestamp."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tags = {"session_id": session_id, "user_email": user, "title": title[:200], "timestamp": ts}
    try:
        mlflow.update_current_trace(tags=tags, session_id=session_id, user=user)
    except TypeError:
        # Older MLflow without session_id/user kwargs.
        mlflow.update_current_trace(
            tags={**tags, "mlflow.trace.session": session_id, "mlflow.trace.user": user}
        )


_META_KEY = {"session_id": "mlflow.trace.session", "user_email": "mlflow.trace.user"}


def _tag(row, key: str) -> str:
    """Read a value from the trace's custom tags, falling back to MLflow's native
    session/user metadata (set via update_current_trace's session_id/user)."""
    tags = row.get("tags") or {}
    if tags.get(key):
        return tags[key]
    md = row.get("trace_metadata") or {}
    alt = _META_KEY.get(key)
    if alt and md.get(alt):
        return md[alt]
    return ""


def _row_time(row) -> int:
    for col in ("request_time", "timestamp_ms", "timestamp"):
        if col in row and row[col] is not None:
            try:
                return int(row[col])
            except (TypeError, ValueError):
                return 0
    return 0


def _search_user_traces(experiment_id: str, user: str):
    """Find the user's traces, tolerant of whether identity lives in a custom tag
    or MLflow's native user metadata."""
    for filt in (f"tags.user_email = '{user}'", f"metadata.`mlflow.trace.user` = '{user}'"):
        try:
            df = mlflow.search_traces(
                experiment_ids=[experiment_id], filter_string=filt,
                max_results=500, return_type="pandas",
            )
        except Exception:  # noqa: BLE001
            logger.exception("search_traces failed for filter %s", filt)
            continue
        if len(df) > 0:
            return df
    return df  # last (possibly empty) frame


def list_user_sessions(user: str) -> list[dict]:
    """Return the user's conversations (one row per session_id), newest first."""
    s = get_settings()
    df = _search_user_traces(s.mlflow_experiment_id, user)
    logger.info("list_user_sessions user=%s rows=%d", user, len(df))
    sessions: dict[str, dict] = {}
    for _, row in df.iterrows():
        sid = _tag(row, "session_id")
        if not sid:
            continue
        ts = _row_time(row)
        cur = sessions.get(sid)
        if cur is None:
            sessions[sid] = {"session_id": sid, "title": _tag(row, "title") or "Conversation", "updated_at": ts, "first_at": ts}
        else:
            cur["updated_at"] = max(cur["updated_at"], ts)
            if ts < cur["first_at"]:
                cur["first_at"] = ts
                cur["title"] = _tag(row, "title") or cur["title"]
    out = sorted(sessions.values(), key=lambda x: x["updated_at"], reverse=True)
    for o in out:
        o.pop("first_at", None)
    return out


def _as_dict(value) -> dict:
    """search_traces returns request/response as a dict in some versions and a
    JSON string in others — handle both."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        import json

        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def load_session(session_id: str, user: str) -> list[dict]:
    """Return ordered turns {role, content, references, trace_id} for a session."""
    s = get_settings()
    df = None
    for filt in (
        f"tags.session_id = '{session_id}' AND tags.user_email = '{user}'",
        f"metadata.`mlflow.trace.session` = '{session_id}' AND metadata.`mlflow.trace.user` = '{user}'",
    ):
        try:
            df = mlflow.search_traces(
                experiment_ids=[s.mlflow_experiment_id], filter_string=filt,
                max_results=200, return_type="pandas",
            )
        except Exception:  # noqa: BLE001
            logger.exception("load_session search failed for %s", filt)
            continue
        if len(df) > 0:
            break
    turns: list[dict] = []
    if df is None:
        return turns
    rows = sorted((r for _, r in df.iterrows()), key=_row_time)
    for row in rows:
        tid = row.get("trace_id") or row.get("request_id")
        req = _as_dict(row.get("request"))
        resp = _as_dict(row.get("response"))
        user_msg = req.get("message")
        answer = resp.get("answer")
        if user_msg:
            turns.append({"role": "user", "content": user_msg})
        if answer is not None:
            turns.append({"role": "assistant", "content": answer,
                          "references": resp.get("references", []), "trace_id": tid})
    return turns


def log_turn_feedback(trace_id: str, value: bool, user: str, comment: str | None = None) -> None:
    from mlflow.entities import AssessmentSource

    mlflow.log_feedback(
        trace_id=trace_id,
        name="user_rating",
        value=value,
        rationale=comment,
        source=AssessmentSource(source_type="HUMAN", source_id=user),
    )
