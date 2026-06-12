"""Workspace deep-links for the resources behind the agent (traces, Genie, VS)."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings

router = APIRouter()


@router.get("/resources")
def resources() -> dict:
    s = get_settings()
    h = s.host
    exp = s.mlflow_experiment_id
    return {
        "experiment_traces": f"{h}/ml/experiments/{exp}/traces" if exp else None,
        "experiment_base": f"{h}/ml/experiments/{exp}" if exp else None,
        "genie_space": f"{h}/genie/rooms/{s.genie_space_id}" if s.genie_space_id else None,
        "vector_index": f"{h}/explore/data/{s.catalog}/{s.schema}/policy_docs_index",
        "anomaly_function": f"{h}/explore/data/{s.catalog}/{s.schema}/detect_market_anomaly",
        "schema": f"{h}/explore/data/{s.catalog}/{s.schema}",
    }
