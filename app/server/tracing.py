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
import uuid

import mlflow

from .config import get_settings


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
    """Tag the active trace with session/user/title."""
    tags = {"session_id": session_id, "user_email": user, "title": title[:200]}
    try:
        mlflow.update_current_trace(tags=tags, session_id=session_id, user=user)
    except TypeError:
        # Older MLflow without session_id/user kwargs.
        mlflow.update_current_trace(
            tags={**tags, "mlflow.trace.session": session_id, "mlflow.trace.user": user}
        )


def _tag(row, key: str) -> str:
    tags = row.get("tags") or {}
    return tags.get(key, "")


def _row_time(row) -> int:
    for col in ("request_time", "timestamp_ms", "timestamp"):
        if col in row and row[col] is not None:
            try:
                return int(row[col])
            except (TypeError, ValueError):
                return 0
    return 0


def list_user_sessions(user: str) -> list[dict]:
    """Return the user's conversations (one row per session_id), newest first."""
    s = get_settings()
    df = mlflow.search_traces(
        experiment_ids=[s.mlflow_experiment_id],
        filter_string=f"tags.user_email = '{user}'",
        max_results=500,
        return_type="pandas",
    )
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


def load_session(session_id: str, user: str) -> list[dict]:
    """Return ordered turns {role, content, references, trace_id} for a session."""
    import json

    s = get_settings()
    df = mlflow.search_traces(
        experiment_ids=[s.mlflow_experiment_id],
        filter_string=f"tags.session_id = '{session_id}' AND tags.user_email = '{user}'",
        max_results=200,
        return_type="pandas",
    )
    rows = sorted((r for _, r in df.iterrows()), key=_row_time)
    turns: list[dict] = []
    for row in rows:
        tid = row.get("trace_id") or row.get("request_id")
        try:
            req = json.loads(row.get("request") or "{}")
            resp = json.loads(row.get("response") or "{}")
        except (TypeError, ValueError):
            req, resp = {}, {}
        user_msg = req.get("message") if isinstance(req, dict) else None
        answer = resp.get("answer") if isinstance(resp, dict) else None
        refs = resp.get("references", []) if isinstance(resp, dict) else []
        if user_msg:
            turns.append({"role": "user", "content": user_msg})
        if answer is not None:
            turns.append({"role": "assistant", "content": answer, "references": refs, "trace_id": tid})
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
