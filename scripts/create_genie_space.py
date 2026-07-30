"""Create the Genie space over the regulatory-returns metric view + metadata.

    DATABRICKS_CONFIG_PROFILE=fe-vm-shm-skunkworks app/.venv/bin/python scripts/create_genie_space.py

Prints a serialized-space JSON payload and the warehouse id. Genie spaces are
created in the workspace UI (Genie > New) or via the SDK/REST; paste/import this
config, then record the resulting space_id in app/app.yaml and databricks.yml.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from server.config import get_settings  # noqa: E402

s = get_settings()
METRIC_VIEW = s.metric_view
TIME_SERIES = f"{s.catalog}.{s.metadata_schema}.time_series"
DATAPOINTS = f"{s.catalog}.{s.metadata_schema}.datapoint_dictionary"
FIS = f"{s.catalog}.{s.metadata_schema}.financial_institutions"

serialized_space = {
    "version": 2,
    "data_sources": {
        "tables": sorted([
            {"identifier": METRIC_VIEW, "description": [
                "Governed balance-sheet measures from the Z4 return: total_assets, "
                "non_mortgage_loans, cash_and_equivalents, deposits, total_deposits, "
                "loan_to_deposit_ratio, liquid_asset_ratio. Dimensions: bank, legal_name, "
                "is_big6, obs_date. All amounts in thousands of CAD."]},
            {"identifier": TIME_SERIES, "description": [
                "Decoder for cryptic RRS time-series names (RZ4.OAB.V1045): return, "
                "institution, datapoint concept, balance-sheet line, description."]},
            {"identifier": FIS, "description": [
                "Financial institutions: bank_code (RRS FI code), short_name (RBC, TD, ...), "
                "legal_name, is_big6."]},
        ], key=lambda t: t["identifier"])
    },
    "instructions": {
        "text_instructions": [
            {"content": [
                "DOMAIN: the Z4 'Balance Sheet by Booking Location' regulatory return filed "
                "monthly by Canadian banks. Prefer the mv_balance_sheet metric view for "
                "quantitative questions; it exposes clean measures so you never sum the raw "
                "cryptic datapoint codes.",
                "UNITS: all monetary values are in thousands of Canadian dollars.",
                "THE BIG SIX: RBC, TD, BNS, BMO, CIBC, NBC (is_big6 = true). For 'the Big Six' "
                "filter is_big6 = true. Bank codes: OAB=RBC, OCB=TD, ODB=BNS, OEB=BMO, OFB=CIBC, OGB=NBC.",
                "LATEST: for 'current'/'latest', use the row with MAX(obs_date). Reporting dates "
                "are month-ends.",
                "RATIOS: loan_to_deposit_ratio = non_mortgage_loans / total_deposits; "
                "liquid_asset_ratio = (cash_and_equivalents + deposits_with_fis) / total_assets. "
                "Never sum ratios across banks — average them or compute from summed components.",
                "NAMING: a time-series name looks like RZ4.OAB.V1045 = Return Z4 · FI OAB (RBC) · "
                "datapoint V1045 (Total Assets); its lowercase metadata key adds a '#rrs' suffix.",
            ]}
        ],
    },
}

out_path = "/tmp/genie_space.json"
with open(out_path, "w") as f:
    json.dump(serialized_space, f, indent=2)
print(out_path)
print(f"WAREHOUSE_ID={s.sql_warehouse_id}")
print(f"METRIC_VIEW={METRIC_VIEW}")

# Create the space via the SDK if requested (pass --create).
if "--create" in sys.argv:
    w = s.workspace_client
    space = w.genie.create_space(
        warehouse_id=s.sql_warehouse_id,
        serialized_space=json.dumps(serialized_space),
        title="Bank of Canada — Z4 Regulatory Returns",
        description="Balance Sheet by Booking Location (Z4): governed balance-sheet "
                    "measures, the time-series decoder, and the filers.",
    )
    space_id = getattr(space, "space_id", None) or getattr(space, "id", None)
    print(f"\nCREATED Genie space: {space_id}")
    print(f"  set GENIE_SPACE_ID={space_id} in app/app.yaml and databricks.yml")
