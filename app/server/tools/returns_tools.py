"""Regulatory-returns tools backed by governed Unity Catalog functions.

Each tool calls a UC function via the SQL Statement Execution API and returns
structured rows plus UI `references` (including the Unity Catalog object touched,
so the app can surface governance/lineage). These mirror the customer's agreed
query steps: decode a series' metadata, pull its values as-of a date, validate a
return, and flag outliers.
"""
from __future__ import annotations

import mlflow

from ..config import get_settings
from ..sql import run_sql


def _catalog_link(fq_name: str) -> str:
    s = get_settings()
    return f"{s.host}/explore/data/{fq_name.replace('.', '/')}"


# --- decode_time_series ---------------------------------------------------------
DECODE_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "decode_time_series",
        "description": (
            "Decode a cryptic RRS regulatory time-series name (e.g. RZ4.OAB.V1045) "
            "into its plain-English meaning: the return, the financial institution, "
            "the datapoint concept, and the balance-sheet line. Use this whenever a "
            "user references a time-series name or asks what a code means."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_name": {"type": "string", "description": "The time-series name, e.g. RZ4.OAB.V1045."}
            },
            "required": ["series_name"],
        },
    },
}


@mlflow.trace(span_type="TOOL")
def decode_time_series(series_name: str) -> dict:
    s = get_settings()
    rows = run_sql(f"SELECT * FROM {s.fn_decode}(:series_name)",
                   params={"series_name": series_name.strip()})
    refs = [{"type": "uc_function", "label": "decode_time_series", "url": _catalog_link(s.fn_decode)}]
    if rows:
        refs.append({"type": "uc_table", "label": "metadata_db.time_series",
                     "url": _catalog_link(f"{s.catalog}.{s.metadata_schema}.time_series")})
    return {"series_name": series_name, "decoded": rows, "references": refs}


# --- get_series_values ----------------------------------------------------------
GET_VALUES_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "get_series_values",
        "description": (
            "Get the reported values for a regulatory time series: the value as-of a "
            "date plus its trailing history. Use for questions about what a bank "
            "reported for a given datapoint, or its trend."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_name": {"type": "string", "description": "Time-series name, e.g. RZ4.OAB.V1045."},
                "as_of": {"type": "string", "description": "Date YYYY-MM-DD (defaults to latest)."},
                "history_months": {"type": "integer", "description": "Trailing months of history.", "default": 12},
            },
            "required": ["series_name"],
        },
    },
}


@mlflow.trace(span_type="TOOL")
def get_series_values(series_name: str, as_of: str | None = None, history_months: int = 12) -> dict:
    s = get_settings()
    vz4 = f"{s.catalog}.{s.views_schema}.vz4"
    as_of_sql = "cast(:as_of AS DATE)" if as_of else f"(SELECT max(DATE) FROM {vz4})"
    params = {"series_name": series_name.strip(), "history_months": int(history_months)}
    if as_of:
        params["as_of"] = as_of
    rows = run_sql(
        f"SELECT * FROM {s.fn_get_values}(:series_name, {as_of_sql}, :history_months)",
        params=params,
    )
    return {
        "series_name": series_name,
        "as_of": as_of or "latest",
        "values": rows,
        "references": [{"type": "uc_function", "label": "get_series_values", "url": _catalog_link(s.fn_get_values)}],
    }


# --- validate_return ------------------------------------------------------------
VALIDATE_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "validate_return",
        "description": (
            "Run the official Z4 validation equations against a bank's filing for a "
            "reporting date and report any rules that FAIL (component sums that do "
            "not tie to their totals). Use for data-quality / data-error questions "
            "about a filing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bank_code": {"type": "string", "description": "FI code, e.g. OAB (RBC)."},
                "as_of": {"type": "string", "description": "Reporting month-end YYYY-MM-DD (defaults to latest)."},
                "return_code": {"type": "string", "description": "Return code.", "default": "Z4"},
            },
            "required": ["bank_code"],
        },
    },
}


@mlflow.trace(span_type="TOOL")
def validate_return(bank_code: str, as_of: str | None = None, return_code: str = "Z4") -> dict:
    s = get_settings()
    vz4 = f"{s.catalog}.{s.views_schema}.vz4"
    as_of_sql = ("cast(:as_of AS DATE)" if as_of
                 else f"(SELECT max(DATE) FROM {vz4} WHERE BANK_CODE = :bank_code)")
    params = {"return_code": return_code.strip(), "bank_code": bank_code.strip()}
    if as_of:
        params["as_of"] = as_of
    rows = run_sql(
        f"SELECT * FROM {s.fn_validate}(:return_code, :bank_code, {as_of_sql})",
        params=params,
    )
    # A rule passes only when `passed` is explicitly true; NULL (one-sided rules
    # where lhs or rhs is missing) is treated as a failure, not silently passed.
    failures = [r for r in rows if str(r.get("passed")).lower() != "true"]
    return {
        "return_code": return_code,
        "bank_code": bank_code,
        "as_of": as_of or "latest",
        "rules_evaluated": len(rows),
        "failures": failures,
        "passed_count": len(rows) - len(failures),
        "references": [
            {"type": "uc_function", "label": "validate_return", "url": _catalog_link(s.fn_validate)},
            *[
                {"type": "validation_failure",
                 "label": f.get("rule_id"),
                 "detail": f"{f.get('description')}: {f.get('lhs_value')} vs {f.get('rhs_value')} (Δ {f.get('difference')})"}
                for f in failures[:10]
            ],
        ],
    }


# --- detect_outliers ------------------------------------------------------------
OUTLIERS_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "detect_outliers",
        "description": (
            "Flag reported values for a time series that are several standard "
            "deviations from that series' own historical norm — the recommended way "
            "to spot possible data errors (recent large changes)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_name": {"type": "string", "description": "Time-series name, e.g. RZ4.OAB.V1045."},
                "z_threshold": {"type": "number", "description": "Std-dev threshold.", "default": 3.0},
            },
            "required": ["series_name"],
        },
    },
}


@mlflow.trace(span_type="TOOL")
def detect_outliers(series_name: str, z_threshold: float = 3.0) -> dict:
    s = get_settings()
    rows = run_sql(
        f"SELECT * FROM {s.fn_outliers}(:series_name, :z_threshold)",
        params={"series_name": series_name.strip(), "z_threshold": float(z_threshold)},
    )
    outliers = [r for r in rows if str(r.get("is_outlier")).lower() == "true"]
    return {
        "series_name": series_name,
        "z_threshold": z_threshold,
        "rows_checked": len(rows),
        "outliers": outliers,
        "references": [
            {"type": "uc_function", "label": "detect_outliers", "url": _catalog_link(s.fn_outliers)},
            *[{"type": "outlier", "label": f"{o.get('obs_date')}",
               "detail": f"value {o.get('value')} (z={o.get('z_score')})"} for o in outliers[:10]],
        ],
    }
