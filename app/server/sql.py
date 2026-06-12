"""Run SQL against the workspace SQL warehouse via the Statement Execution API."""
from __future__ import annotations

from databricks.sdk.service.sql import StatementState

from .config import get_settings


def run_sql(statement: str, *, warehouse_id: str | None = None) -> list[dict]:
    """Execute a SQL statement and return rows as a list of dicts.

    Returns [] for statements without a result set (DDL, etc.).
    """
    s = get_settings()
    w = s.workspace_client
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id or s.sql_warehouse_id,
        statement=statement,
        wait_timeout="50s",
    )
    status = resp.status
    if status and status.state not in (StatementState.SUCCEEDED, None):
        msg = status.error.message if status.error else status.state
        raise RuntimeError(f"SQL failed: {msg}")

    result = resp.result
    manifest = resp.manifest
    if not result or not result.data_array or not manifest or not manifest.schema:
        return []
    cols = [c.name for c in manifest.schema.columns]
    return [dict(zip(cols, row)) for row in result.data_array]
