"""One-time provisioning: UC catalog/schema/volume + MLflow experiment.

Run locally with the app venv:
    DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/provision.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import mlflow  # noqa: E402

from server.config import get_settings  # noqa: E402
from server.sql import run_sql  # noqa: E402

s = get_settings()
CATALOG, SCHEMA = s.catalog, s.schema

print(f"Provisioning {CATALOG}.{SCHEMA} on {s.host}")
run_sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
run_sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.raw")
print("  catalog / schema / volume ready")

# MLflow experiment for traces / sessions / feedback (under the current user).
mlflow.set_tracking_uri("databricks")
me = s.workspace_client.current_user.me().user_name
exp_name = f"/Users/{me}/boc-agent"
exp = mlflow.get_experiment_by_name(exp_name)
if exp is None:
    exp_id = mlflow.create_experiment(exp_name)
else:
    exp_id = exp.experiment_id
print(f"  MLflow experiment: {exp_name}  id={exp_id}")
print("\nSet these in .env and app/app.yaml:")
print(f"  MLFLOW_EXPERIMENT_ID={exp_id}")
