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
imperfect_filings = 0   # filings with any residual identity violation (should be ~0)

# A small growth trajectory per bank (annualized), plus mild monthly noise.
growth = {b.bank_code: rng.uniform(0.00, 0.08) for b in reference_data.BANKS}

# One Z4 filing per (bank, month-end) is the source of truth. Each return TABLE in
# views_db then projects a slice of these datapoints (per RETURN_TABLES) so the
# "one v* table per return" reality is visible and the tools work across tables.
# rows_by_table[table] = list of (name, bank, addr, date, value)
rows_by_table = {rt["table"]: [] for rt in reference_data.RETURN_TABLES}
# Precompute, per return, which datapoint dictionary rows it includes.
dict_by_table = {
    rt["table"]: [d for d in dictionary if rt["select"] is None or rt["select"](d)]
    for rt in reference_data.RETURN_TABLES
}
rc_by_table = {rt["table"]: rt["return_code"] for rt in reference_data.RETURN_TABLES}

for b in reference_data.BANKS:
    base = b.asset_scale
    for i, d in enumerate(DATES):
        # target assets drift up over time with a little noise
        months_frac = i / 12.0
        target = base * ((1 + growth[b.bank_code]) ** months_frac) * rng.uniform(0.98, 1.02)
        values = gen.generate_clean_filing(b, target_assets=target)
        if gen.check(values):
            imperfect_filings += 1
        for table, drows in dict_by_table.items():
            rc = rc_by_table[table]
            for d_addr_row in drows:
                addr = d_addr_row["cell_code"]
                if addr not in values:
                    continue
                name = z4_taxonomy.time_series_name(rc, b.bank_code, d_addr_row["data_point_address"])
                rows_by_table[table].append(
                    (name, b.bank_code, d_addr_row["data_point_address"], d, round(values[addr], 3))
                )

# The Z4 table is the flagship; keep a direct handle for error-seeding below.
fact_rows = rows_by_table["vz4"]
total_filings = len(reference_data.BANKS) * len(DATES)
print(f"generated {sum(len(v) for v in rows_by_table.values()):,} fact rows across "
      f"{len(rows_by_table)} return tables over {total_filings} filings; "
      f"{imperfect_filings} with residual identity violations")
for t, rws in rows_by_table.items():
    print(f"  {t}: {len(rws):,} rows ({len(dict_by_table[t])} datapoints/filing)")
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
rows_by_table["vz4"] = new_rows
fact_rows = new_rows
for n in err_notes:
    print("SEEDED ERROR:", n)

# COMMAND ----------
# MAGIC %md ## Write the views_db return tables (one v* table per return)

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

_COL_COMMENTS = {
    "TIME_SERIES_NAME": "Cryptic RRS series name, e.g. RZ4.OAB.V1045 (Return · FI · datapoint). Join to metadata_db.time_series to decode.",
    "BANK_CODE": "RRS financial-institution code (links to metadata_db.financial_institutions).",
    "DATA_POINT_ADDRESS": "Datapoint address within the return (links to metadata_db.datapoint_dictionary).",
    "DATE": "Reporting month-end date.",
    "VALUE": "Reported value in thousands of Canadian dollars.",
}
returns_of = {r["return_code"]: r["return_title"] for r in reference_data.RETURNS}

for rt in reference_data.RETURN_TABLES:
    table, rc = rt["table"], rt["return_code"]
    rows = rows_by_table[table]
    if not rows:
        print(f"  skip {table}: no rows")
        continue
    fq = f"{CATALOG}.{VIEWS}.{table}"
    spark.createDataFrame(rows, fact_schema).write.mode("overwrite").option(
        "overwriteSchema", "true").saveAsTable(fq)
    title = returns_of.get(rc, rc)
    cmt = (f"{rc} {title} — reported datapoint values, long format matching the "
           f"FIS-DDS views_db layout (one table per return). {rt['note']} "
           f"TIME_SERIES_NAME decodes via metadata_db.time_series.")
    spark.sql(f"COMMENT ON TABLE {fq} IS '{esc(cmt)}'")
    for col, ccmt in _COL_COMMENTS.items():
        spark.sql(f"ALTER TABLE {fq} ALTER COLUMN {col} COMMENT '{esc(ccmt)}'")
    try:
        spark.sql(f"ALTER TABLE {fq} SET TAGS ('domain' = 'finance')")
    except Exception as e:  # noqa: BLE001
        print(f"(tag skipped for {table}: {str(e)[:60]})")
    print(f"wrote {fq}: {len(rows):,} rows")

# A convenience union across all return tables (governed, for cross-return queries).
union_sql = " UNION ALL ".join(
    f"SELECT '{rt['return_code']}' AS RETURN_CODE, * FROM {CATALOG}.{VIEWS}.{rt['table']}"
    for rt in reference_data.RETURN_TABLES if rows_by_table[rt["table"]]
)
spark.sql(f"CREATE OR REPLACE VIEW {CATALOG}.{VIEWS}.all_returns AS {union_sql}")
spark.sql(f"COMMENT ON VIEW {CATALOG}.{VIEWS}.all_returns IS '{esc('All regulatory-return filings across the views_db tables, tagged with RETURN_CODE — a single place to query any return.')}'")
print(f"wrote {CATALOG}.{VIEWS}.all_returns (union view)")

# COMMAND ----------
# MAGIC %md ## Write metadata_db.time_series (the decoder)

# COMMAND ----------
# Decoder rows for EVERY return table, so RZ4.*, RM4.*, RA2.*, RLA.* all decode.
ts_rows = []
for rt in reference_data.RETURN_TABLES:
    if not rows_by_table[rt["table"]]:
        continue
    ts_rows += z4_taxonomy.build_time_series_rows(
        dict_by_table[rt["table"]], reference_data.BANKS, returns_of,
        return_code=rt["return_code"],
    )

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
