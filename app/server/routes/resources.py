"""Workspace deep-links + Unity Catalog metadata for the governance-forward UI."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..sql import run_sql

router = APIRouter()


@router.get("/resources")
def resources() -> dict:
    s = get_settings()
    h = s.host
    exp = s.mlflow_experiment_id
    cat, views, meta = s.catalog, s.views_schema, s.metadata_schema
    return {
        "experiment_traces": f"{h}/ml/experiments/{exp}/traces" if exp else None,
        "experiment_base": f"{h}/ml/experiments/{exp}" if exp else None,
        "genie_space": f"{h}/genie/rooms/{s.genie_space_id}" if s.genie_space_id else None,
        "vector_index": f"{h}/explore/data/{cat}/{meta}/instruction_chunks_index",
        "metric_view": f"{h}/explore/data/{cat}/{meta}/mv_balance_sheet",
        "vz4_table": f"{h}/explore/data/{cat}/{views}/vz4",
        "time_series_decoder": f"{h}/explore/data/{cat}/{meta}/time_series",
        "validation_rules": f"{h}/explore/data/{cat}/{meta}/validation_rules",
        "views_schema": f"{h}/explore/data/{cat}/{views}",
        "metadata_schema": f"{h}/explore/data/{cat}/{meta}",
        "functions": {
            fn: f"{h}/explore/data/{fn.replace('.', '/')}"
            for fn in (s.fn_decode, s.fn_get_values, s.fn_validate, s.fn_outliers)
        },
    }


@router.get("/catalog/overview")
def catalog_overview() -> dict:
    """A snapshot of the Unity Catalog backbone for the data→insight story:
    counts and comments for the key governed objects. Surfaced in the UI so the
    governance / data-organization message is visible, not hidden."""
    s = get_settings()
    cat, views, meta = s.catalog, s.views_schema, s.metadata_schema
    try:
        counts = run_sql(f"""
            SELECT
              (SELECT count(*) FROM {cat}.{views}.vz4) AS filing_rows,
              (SELECT count(DISTINCT BANK_CODE) FROM {cat}.{views}.vz4) AS banks,
              (SELECT count(DISTINCT DATA_POINT_ADDRESS) FROM {cat}.{views}.vz4) AS datapoints,
              (SELECT count(DISTINCT DATE) FROM {cat}.{views}.vz4) AS reporting_dates,
              (SELECT count(*) FROM {cat}.{meta}.time_series) AS decoder_rows,
              (SELECT count(*) FROM {cat}.{meta}.validation_rules) AS validation_rules,
              (SELECT count(*) FROM {cat}.{meta}.concepts) AS concepts
        """)
        return {"ok": True, "counts": counts[0] if counts else {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@router.get("/catalog/decode")
def catalog_decode(series_name: str) -> dict:
    """Decode a cryptic time-series name via the UC function — powers the UI's
    'what does this code mean?' inline decoder."""
    s = get_settings()
    try:
        rows = run_sql(f"SELECT * FROM {s.fn_decode}(:series_name)",
                       params={"series_name": series_name.strip()})
        return {"ok": True, "decoded": rows[0] if rows else None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
