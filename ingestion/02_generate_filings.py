# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Synthetic Z4 filings (`views_db`) + time-series decoder
# MAGIC Generates internally-consistent monthly Z4 filings for every financial
# MAGIC institution across a multi-year window, in the customer's real long-format
# MAGIC shape, and populates the `metadata_db.time_series` decoder.
# MAGIC
# MAGIC - `views_db.vz4` — the Z4 fact table: `TIME_SERIES_NAME, BANK_CODE,
# MAGIC   DATA_POINT_ADDRESS, DATE, VALUE`. One row per (series, month-end). Every
# MAGIC   filing satisfies the real Z4 validation identities (so `validate_return`
# MAGIC   passes) — except a small number of deliberately-seeded data errors.
# MAGIC - `metadata_db.time_series` — the decoder: `rz4.oab.v1045#rrs` -> the
# MAGIC   plain-English meaning of `RZ4.OAB.V1045`.
# MAGIC
# MAGIC In `DATA_MODE=existing` this notebook is skipped — the UC functions, metric
# MAGIC view, and app point at the customer's real `views_db` / `metadata_db` tables
# MAGIC instead (identical schema contract).

# COMMAND ----------
import os
import sys

# Make the ingestion helper library (this notebook's own folder) importable, both
# locally and when synced into a Databricks workspace by the bundle.
try:
    _here = os.path.dirname(
        dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    )
    _here = f"/Workspace{_here}"
except Exception:  # noqa: BLE001 — local execution
    _here = os.path.dirname(os.path.abspath("__file__" if "__file__" not in dir() else __file__))
for p in (_here, os.getcwd(), os.path.join(os.getcwd(), "ingestion")):
    if p not in sys.path:
        sys.path.insert(0, p)
from lib import data_loader, generate_filings, reference_data, z4_taxonomy

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("views_schema", "views_db")
dbutils.widgets.text("metadata_schema", "metadata_db")
dbutils.widgets.text("data_mode", "synthetic")   # 'synthetic' | 'existing'
dbutils.widgets.text("n_months", "30")
dbutils.widgets.text("seed", "42")
CATALOG = dbutils.widgets.get("catalog")
VIEWS = dbutils.widgets.get("views_schema")
META = dbutils.widgets.get("metadata_schema")
DATA_MODE = dbutils.widgets.get("data_mode")
N_MONTHS = int(dbutils.widgets.get("n_months"))
SEED = int(dbutils.widgets.get("seed"))

if DATA_MODE == "existing":
    dbutils.notebook.exit("DATA_MODE=existing: skipping synthetic generation; using the customer's real views_db / metadata_db.")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{VIEWS} COMMENT 'Regulatory-return fact tables (one table per return). Each row is a reported datapoint value for a bank at a month-end.'")

# COMMAND ----------
# MAGIC %md ## Generate the filings

# COMMAND ----------
import datetime as dt

rules_simple = data_loader.load_validation_rules_simple()
dictionary = z4_taxonomy.build_datapoint_dictionary(rules_simple)
gen = generate_filings.Z4Generator(rules_simple, dictionary=dictionary, seed=SEED)

# Month-end reporting dates (last N_MONTHS month-ends up to the prior month-end).
def month_ends(n):
    today = dt.date.today().replace(day=1)
    ends = []
    d = today
    for _ in range(n):
        last = d - dt.timedelta(days=1)   # last day of previous month
        ends.append(last)
        d = last.replace(day=1)
    return sorted(ends)

DATES = month_ends(N_MONTHS)
print(f"generating {len(reference_data.BANKS)} banks x {len(DATES)} month-ends "
      f"({DATES[0]} .. {DATES[-1]})")

# COMMAND ----------
# For each bank we draw one base filing, then apply a gentle month-over-month
# growth path so history looks like real balance-sheet evolution (and outliers
# stand out). Each month's filing is regenerated at that month's target assets so
# every monthly snapshot independently satisfies the identities.
import random

rng = random.Random(SEED)
fact_rows = []          # (time_series_name, bank_code, data_point_address, date, value)
imperfect_filings = 0   # filings with any residual identity violation (should be ~0)

# A small growth trajectory per bank (annualized), plus mild monthly noise.
growth = {b.bank_code: rng.uniform(0.00, 0.08) for b in reference_data.BANKS}

for b in reference_data.BANKS:
    base = b.asset_scale
    for i, d in enumerate(DATES):
        # target assets drift up over time with a little noise
        months_frac = i / 12.0
        target = base * ((1 + growth[b.bank_code]) ** months_frac) * rng.uniform(0.98, 1.02)
        values = gen.generate_clean_filing(b, target_assets=target)
        if gen.check(values):
            imperfect_filings += 1
        for d_addr_row in dictionary:
            addr = d_addr_row["cell_code"]
            if addr not in values:
                continue
            name = z4_taxonomy.time_series_name("Z4", b.bank_code, d_addr_row["data_point_address"])
            fact_rows.append((name, b.bank_code, d_addr_row["data_point_address"], d, round(values[addr], 3)))

total_filings = len(reference_data.BANKS) * len(DATES)
print(f"generated {len(fact_rows):,} fact rows over {total_filings} filings; "
      f"{imperfect_filings} with residual identity violations")
# Guard against a systemic break, but tolerate the rare non-converging filing
# (validate_return would just flag those alongside the seeded errors).
assert imperfect_filings <= total_filings * 0.02, (
    f"too many non-converging filings ({imperfect_filings}/{total_filings}) — "
    "generator regression"
)

# COMMAND ----------
# MAGIC %md ## Seed deliberate data errors (for the validation / anomaly demo)

# COMMAND ----------
# One broken component-sum (fails a validate_return rule) and one multi-sigma
# outlier (caught by detect_outliers), on RBC's latest filing.
seed_bank = "OAB"
seed_date = DATES[-1]
# find RBC's Total-Assets series latest row and inflate it 40% (breaks its sum rule
# and stands out vs history)
err_notes = []
new_rows = []
for (name, bank, addr, d, val) in fact_rows:
    if bank == seed_bank and d == seed_date and addr == "V1045":
        val_bad = round(val * 1.40, 3)
        err_notes.append(f"{name} @ {d}: {val:,.0f} -> {val_bad:,.0f} (inflated 40%: breaks Total-Assets identity & is a multi-sigma outlier)")
        new_rows.append((name, bank, addr, d, val_bad))
    else:
        new_rows.append((name, bank, addr, d, val))
fact_rows = new_rows
for n in err_notes:
    print("SEEDED ERROR:", n)

# COMMAND ----------
# MAGIC %md ## Write views_db.vz4

# COMMAND ----------
from pyspark.sql.types import DateType, DoubleType, StringType, StructField, StructType

fact_schema = StructType([
    StructField("TIME_SERIES_NAME", StringType()),
    StructField("BANK_CODE", StringType()),
    StructField("DATA_POINT_ADDRESS", StringType()),
    StructField("DATE", DateType()),
    StructField("VALUE", DoubleType()),
])
def esc(s):
    """Escape single quotes for safe embedding in a SQL string literal."""
    return str(s).replace("'", "''")

fact_df = spark.createDataFrame(fact_rows, fact_schema)
vz4 = f"{CATALOG}.{VIEWS}.vz4"
fact_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(vz4)
spark.sql(f"COMMENT ON TABLE {vz4} IS '{esc('Z4 Balance Sheet by Booking Location — reported datapoint values. Long format, matching the FIS-DDS views_db layout. TIME_SERIES_NAME decodes via metadata_db.time_series; component values add to their totals per the Z4 validation identities (except deliberately seeded data errors).')}'")
for col, cmt in {
    "TIME_SERIES_NAME": "Cryptic RRS series name, e.g. RZ4.OAB.V1045 (Return Z4 · FI OAB=RBC · datapoint V1045=Total Assets). Join to metadata_db.time_series to decode.",
    "BANK_CODE": "RRS financial-institution code (links to metadata_db.financial_institutions).",
    "DATA_POINT_ADDRESS": "Datapoint address within the return (links to metadata_db.datapoint_dictionary).",
    "DATE": "Reporting month-end date.",
    "VALUE": "Reported value in thousands of Canadian dollars.",
}.items():
    spark.sql(f"ALTER TABLE {vz4} ALTER COLUMN {col} COMMENT '{esc(cmt)}'")
try:
    spark.sql(f"ALTER TABLE {vz4} SET TAGS ('domain' = 'finance')")
except Exception as e:  # noqa: BLE001
    print(f"(tag skipped: {str(e)[:80]})")
print(f"wrote {vz4}: {fact_df.count():,} rows")

# COMMAND ----------
# MAGIC %md ## Write metadata_db.time_series (the decoder)

# COMMAND ----------
returns_of = {r["return_code"]: r["return_title"] for r in reference_data.RETURNS}
ts_rows = z4_taxonomy.build_time_series_rows(dictionary, reference_data.BANKS, returns_of)

ts_schema = StructType([StructField(k, StringType()) for k in ts_rows[0].keys()])
ts_df = spark.createDataFrame([tuple(r.values()) for r in ts_rows], ts_schema)
ts_tbl = f"{CATALOG}.{META}.time_series"
ts_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(ts_tbl)
spark.sql(f"ALTER TABLE {ts_tbl} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
spark.sql(f"COMMENT ON TABLE {ts_tbl} IS '{esc('The decoder ring: one row per time series (bank x datapoint). Maps the cryptic name (RZ4.OAB.V1045) and its lowercase #rrs key (rz4.oab.v1045#rrs) to a plain-English description. This is how you understand what an RBC Z4 time series means.')}'")
for col, cmt in {
    "time_series_key": "Lowercase metadata key with the #rrs suffix, e.g. rz4.oab.v1045#rrs.",
    "time_series_name": "The series name as it appears in views_db, e.g. RZ4.OAB.V1045.",
    "description": "Plain-English meaning: return · institution · datapoint concept · line · address.",
    "concept_id": "Balance-sheet concept (links to metadata_db.concepts).",
    "role": "'total' or 'component'.",
    "unit": "Reporting unit (thousands CAD).",
}.items():
    spark.sql(f"ALTER TABLE {ts_tbl} ALTER COLUMN {col} COMMENT '{esc(cmt)}'")
try:
    spark.sql(f"ALTER TABLE {ts_tbl} SET TAGS ('domain' = 'finance')")
except Exception as e:  # noqa: BLE001
    print(f"(tag skipped: {str(e)[:80]})")
print(f"wrote {ts_tbl}: {ts_df.count():,} decoder rows")

# COMMAND ----------
print("02_generate_filings complete.")
display(spark.sql(f"SELECT * FROM {ts_tbl} WHERE time_series_name = 'RZ4.OAB.V1045' LIMIT 5"))
