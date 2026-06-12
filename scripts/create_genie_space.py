"""Create the Bank of Canada Genie space over boc_rates with semantic instructions.

    DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/create_genie_space.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from server.config import get_settings  # noqa: E402

s = get_settings()
TABLE = f"{s.catalog}.{s.schema}.boc_rates"


def qid() -> str:
    return uuid.uuid4().hex


serialized_space = {
    "version": 2,
    "data_sources": {
        "tables": [
            {
                "identifier": TABLE,
                "description": [
                    "Bank of Canada public time series. Columns: series_id, series_label, obs_date (date), value (double), unit.",
                    "V39079 = target for the overnight rate (percent); BD.CDN.2YR/5YR/10YR.DQ.YLD = Government of Canada benchmark bond yields (percent); V41690973 = CPI all-items (index, 2002=100); FXUSDCAD = USD/CAD noon rate (CAD per USD).",
                ],
            }
        ]
    },
    "instructions": {
        "text_instructions": [
            {
                "content": [
                    "MEASURES & UNITS: rate/yield values are in percent; CPI value is an index level (2002=100), not a percent; FXUSDCAD value is CAD per USD.",
                    "CENTRAL MEASURES: policy rate (series_id 'V39079'), benchmark bond yields ('BD.CDN.%.DQ.YLD'), CPI ('V41690973'), USD/CAD ('FXUSDCAD'). DIMENSIONS: series_id / series_label and obs_date.",
                    "AGGREGATIONS: for 'current' or 'latest', take the row with MAX(obs_date) for that series. Average rates/yields across dates - never SUM them. Report CPI as a level or as year-over-year percent change (value vs the value 12 months earlier), never summed. The 2s10s yield-curve slope is the 10-year yield minus the 2-year yield. The fiscal year runs Apr 1 to Mar 31.",
                ]
            }
        ],
    },
}
_ = qid  # sample-questions schema is nested/undocumented; instructions carry the semantics

out_path = "/tmp/genie_space.json"
with open(out_path, "w") as f:
    json.dump(serialized_space, f)
print(out_path)
print(f"WAREHOUSE_ID={s.sql_warehouse_id}")
