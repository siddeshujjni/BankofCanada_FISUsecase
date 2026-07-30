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
import os
import uuid

import mlflow
import mlflow.tracing  # noqa: F401 — ensures mlflow.tracing is importable at runtime

from .config import get_settings

logger = logging.getLogger("boc.tracing")


@functools.lru_cache(maxsize=1)
def init_tracing() -> str:
    """Point MLflow at the workspace experiment and enable OpenAI autolog.

    Uses an explicit tracing *destination* (not just the active experiment) so
    traces land reliably from the Databricks Apps runtime, and enables autolog so
    the router / deep-analyst LLM calls (via the SDK's OpenAI client) are captured
    as child spans under the turn. Async export is disabled so every trace is
    flushed synchronously before the request returns — the Apps worker would
    otherwise drop in-flight traces.
    """
    s = get_settings()
    # Disable async trace export: in the short-lived Apps request context the async
    # queue may not flush before the worker moves on, silently dropping traces.
    os.environ.setdefault("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
    mlflow.set_tracking_uri("databricks" if s.is_app else f"databricks://{s.profile}")
    if s.mlflow_experiment_id:
        mlflow.set_experiment(experiment_id=s.mlflow_experiment_id)
        # Re-assert the UC-backed trace location IN-PROCESS. The Apps runtime cannot
        # reach the default cloud trace-artifact storage, so traces must go to UC
        # tables (via the SQL warehouse). Setting this per-process configures the
        # exporter to route there; without it, writes silently target cloud storage
        # and are dropped. Idempotent when the experiment is already linked.
        try:
            from mlflow.entities.trace_location import UCSchemaLocation

            mlflow.tracing.set_experiment_trace_location(
                location=UCSchemaLocation(
                    catalog_name=s.catalog, schema_name=s.metadata_schema
                ),
                experiment_id=s.mlflow_experiment_id,
                sql_warehouse_id=s.sql_warehouse_id,
            )
        except Exception:  # noqa: BLE001 — older MLflow or already linked
            pass
    try:
        mlflow.openai.autolog()
    except Exception:  # noqa: BLE001
        pass
    return s.mlflow_experiment_id


def flush_traces() -> None:
    """Force any pending trace writes to complete (call at end of a turn)."""
    try:
        mlflow.flush_trace_async_logging()
    except Exception:  # noqa: BLE001
        pass


def new_session_id() -> str:
    return uuid.uuid4().hex


# NOTE: session history (list/load conversations) is served from the durable UC
# turn log in ``turn_log.py`` — NOT from MLflow trace tags — because the Apps
# runtime cannot reach the cloud storage MLflow's exporter uploads spans to, so
# in-app traces do not reliably persist. Feedback below still targets a trace_id
# where traces do persist (local dev / notebooks).


def log_turn_feedback(trace_id: str, value: bool, user: str, comment: str | None = None) -> None:
    from mlflow.entities import AssessmentSource

    mlflow.log_feedback(
        trace_id=trace_id,
        name="user_rating",
        value=value,
        rationale=comment,
        source=AssessmentSource(source_type="HUMAN", source_id=user),
    )
