# Databricks notebook source
# MAGIC %md
# MAGIC # 06 — Governance & discoverability (trusted assets, tags, function docs)
# MAGIC Makes every asset **discoverable and reusable in a democratized way**:
# MAGIC
# MAGIC - Rich `COMMENT`s on every table, view, and function (added in notebooks
# MAGIC   01-05); here we add **function parameter and return-column comments** so
# MAGIC   consumers see what each argument/output means straight from Catalog Explorer.
# MAGIC - **Trusted-asset** designation + discoverability **tags** (`certified`,
# MAGIC   `trusted`, `classification`, `domain`) on tables, the metric view, and
# MAGIC   functions, so others can find and reuse them with confidence.
# MAGIC
# MAGIC Idempotent and tolerant of workspace tag policies (unknown keys/values are
# MAGIC skipped, not fatal).

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("views_schema", "views_db")
dbutils.widgets.text("metadata_schema", "metadata_db")
CATALOG = dbutils.widgets.get("catalog")
VIEWS = dbutils.widgets.get("views_schema")
META = dbutils.widgets.get("metadata_schema")
V = f"{CATALOG}.{VIEWS}"
M = f"{CATALOG}.{META}"

def run(sql):
    try:
        spark.sql(sql)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  skip: {str(e)[:110]}")
        return False

# COMMAND ----------
# MAGIC %md ## Trusted-asset + discoverability tags
# MAGIC `certified`/`trusted` mark these as governed, reviewed assets; `classification`
# MAGIC and `domain` aid search. Free-form keys are used where the workspace tag
# MAGIC policy allows; the governed `domain` key uses its allowed value `finance`.

# COMMAND ----------
TABLES = [
    f"{V}.vz4",
    f"{M}.returns", f"{M}.financial_institutions", f"{M}.concepts",
    f"{M}.datapoint_dictionary", f"{M}.validation_rules",
    f"{M}.validation_rule_operands", f"{M}.time_series",
    f"{M}.instruction_chunks", f"{M}.general_instructions",
]
# agent_turns is created by the app at runtime; tag it if present.
try:
    spark.sql(f"DESCRIBE TABLE {M}.agent_turns")
    TABLES.append(f"{M}.agent_turns")
except Exception:  # noqa: BLE001
    pass
VIEWS_LIST = [f"{M}.mv_balance_sheet", f"{M}.balance_sheet_headline"]
FUNCTIONS = [f"{V}.decode_time_series", f"{V}.get_series_values",
             f"{V}.validate_return", f"{V}.detect_outliers"]

# Trusted-asset tag set (free-form keys verified against the workspace tag policy).
TRUSTED_TAGS = {"certified": "true", "trusted": "true",
                "classification": "internal", "domain": "finance"}

def tag_all(obj_type, names):
    for fq in names:
        applied = []
        for k, v in TRUSTED_TAGS.items():
            if run(f"ALTER {obj_type} {fq} SET TAGS ('{k}' = '{v}')"):
                applied.append(k)
        print(f"  {obj_type} {fq}: tags {applied}")

tag_all("TABLE", TABLES)
tag_all("VIEW", VIEWS_LIST)
# Functions support SET TAGS via ALTER FUNCTION on this platform; tolerate if not.
for fq in FUNCTIONS:
    applied = []
    for k, v in TRUSTED_TAGS.items():
        if run(f"ALTER FUNCTION {fq} SET TAGS ('{k}' = '{v}')"):
            applied.append(k)
    print(f"  FUNCTION {fq}: tags {applied}")

# COMMAND ----------
# MAGIC %md ## Function parameter & return-column documentation
# MAGIC Comments on each argument and output column so consumers understand how to
# MAGIC call the function and what it returns, from Catalog Explorer.

# COMMAND ----------
# decode_time_series
run(f"ALTER FUNCTION {V}.decode_time_series ALTER PARAMETER series_name COMMENT 'Cryptic RRS time-series name to decode, e.g. RZ4.OAB.V1045 (or its lowercase #rrs key).'")
# get_series_values
run(f"ALTER FUNCTION {V}.get_series_values ALTER PARAMETER series_name COMMENT 'Time-series name to pull, e.g. RZ4.OAB.V1045.'")
run(f"ALTER FUNCTION {V}.get_series_values ALTER PARAMETER as_of COMMENT 'As-of date; returns values on/before this date.'")
run(f"ALTER FUNCTION {V}.get_series_values ALTER PARAMETER history_months COMMENT 'Number of trailing months of history to include (default 12).'")
# validate_return
run(f"ALTER FUNCTION {V}.validate_return ALTER PARAMETER return_code COMMENT 'Return code to validate, e.g. Z4.'")
run(f"ALTER FUNCTION {V}.validate_return ALTER PARAMETER bank_code COMMENT 'RRS financial-institution code, e.g. OAB (RBC).'")
run(f"ALTER FUNCTION {V}.validate_return ALTER PARAMETER as_of COMMENT 'Reporting month-end date of the filing to validate.'")
# detect_outliers
run(f"ALTER FUNCTION {V}.detect_outliers ALTER PARAMETER series_name COMMENT 'Time-series name to scan for outliers, e.g. RZ4.OAB.V1045.'")
run(f"ALTER FUNCTION {V}.detect_outliers ALTER PARAMETER z_threshold COMMENT 'Z-score threshold; values beyond this many std devs from the series mean are flagged (default 3.0).'")
print("function parameter comments applied")

# COMMAND ----------
# MAGIC %md ## Verify
# MAGIC Show the governance metadata now attached (comments + tags) for a quick check.

# COMMAND ----------
print("=== table comments ===")
for fq in TABLES + VIEWS_LIST:
    try:
        c = spark.sql(f"DESCRIBE TABLE EXTENDED {fq}").where("col_name='Comment'").collect()
        print(f"  {fq}: {(c[0]['data_type'] if c else '')[:80]}")
    except Exception as e:  # noqa: BLE001
        print(f"  {fq}: {str(e)[:60]}")

print("\n=== information_schema tags (sample) ===")
try:
    display(spark.sql(f"""
      SELECT catalog_name, schema_name, table_name, tag_name, tag_value
      FROM {CATALOG}.information_schema.table_tags
      WHERE schema_name IN ('{VIEWS}', '{META}')
      ORDER BY table_name, tag_name LIMIT 60
    """))
except Exception as e:  # noqa: BLE001
    print(str(e)[:120])

# COMMAND ----------
print("06_governance complete.")
