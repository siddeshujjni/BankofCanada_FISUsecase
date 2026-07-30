"""One-time provisioning: UC catalog/schemas + MLflow experiment.

Run locally with the app venv:
    DATABRICKS_CONFIG_PROFILE=fe-vm-shm-skunkworks app/.venv/bin/python scripts/provision.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import mlflow  # noqa: E402

from server.config import get_settings  # noqa: E402
from server.sql import run_sql  # noqa: E402

s = get_settings()
CATALOG = s.catalog

print(f"Provisioning {CATALOG}.{{{s.views_schema},{s.metadata_schema}}} on {s.host}")
run_sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{s.views_schema} "
        f"COMMENT 'Regulatory-return fact tables (one per return).'")
run_sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{s.metadata_schema} "
        f"COMMENT 'Regulatory-returns metadata: decoder, concepts, validation rules.'")
run_sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{s.metadata_schema}.raw")
print("  catalog / schemas / volume ready")

# MLflow experiment for traces / sessions / feedback (under the current user).
# Traces are stored in a Unity Catalog schema (not cloud storage) because the
# Databricks Apps runtime cannot reach the trace-artifact storage host — UC-backed
# trace tables are reachable and queryable. The UC link must be set on an
# experiment that has no traces yet, so we create a dedicated one.
mlflow.set_tracking_uri("databricks")
me = s.workspace_client.current_user.me().user_name
exp_name = f"/Users/{me}/boc-fis-returns-traces"
exp = mlflow.get_experiment_by_name(exp_name)
exp_id = exp.experiment_id if exp else mlflow.create_experiment(exp_name)
try:
    import mlflow.tracing
    from mlflow.entities.trace_location import UCSchemaLocation

    mlflow.tracing.set_experiment_trace_location(
        location=UCSchemaLocation(catalog_name=CATALOG, schema_name=s.metadata_schema),
        experiment_id=exp_id,
        sql_warehouse_id=s.sql_warehouse_id,
    )
    print(f"  UC trace storage linked: {CATALOG}.{s.metadata_schema}")
except Exception as e:  # noqa: BLE001 — already linked, or older MLflow
    print(f"  (UC trace link note: {str(e)[:120]})")
print(f"  MLflow experiment: {exp_name}  id={exp_id}")
print("\nSet these in .env and app/app.yaml:")
print(f"  MLFLOW_EXPERIMENT_ID={exp_id}")
