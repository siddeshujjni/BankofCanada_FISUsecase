# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Unity Catalog functions + metric view
# MAGIC The governed "tools" the agent calls, all defined as first-class UC objects
# MAGIC (documented, permissioned, lineage-tracked):
# MAGIC
# MAGIC - `decode_time_series(name)` — decode a cryptic RRS name (RZ4.OAB.V1045) into
# MAGIC   its plain-English meaning (Huda's "pull metadata about a time series").
# MAGIC - `get_series_values(name, as_of)` — value as-of a date + trailing history
# MAGIC   (Huda's "parameterized query to pull any view").
# MAGIC - `validate_return(return_code, bank_code, as_of)` — evaluate ALL simple Z4
# MAGIC   validation identities against a filing; flag failures (the data-error story).
# MAGIC - `detect_outliers(name, z_threshold)` — values several std devs from the
# MAGIC   series' own history (the "recently occurring large changes" heuristic).
# MAGIC
# MAGIC Plus `metadata_db.mv_balance_sheet` — a UC **metric view** exposing curated,
# MAGIC governed measures (total assets, loans, cash, deposits, loan-to-deposit) over
# MAGIC the Z4 facts, so Genie speaks in business terms rather than cryptic codes.

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("views_schema", "views_db")
dbutils.widgets.text("metadata_schema", "metadata_db")
CATALOG = dbutils.widgets.get("catalog")
VIEWS = dbutils.widgets.get("views_schema")
META = dbutils.widgets.get("metadata_schema")
V = f"{CATALOG}.{VIEWS}"
M = f"{CATALOG}.{META}"

# COMMAND ----------
# MAGIC %md ## decode_time_series — turn a cryptic name into meaning

# COMMAND ----------
spark.sql(f"""
CREATE OR REPLACE FUNCTION {V}.decode_time_series(series_name STRING)
RETURNS TABLE (time_series_name STRING, return_code STRING, bank_code STRING,
               data_point_address STRING, bs_line STRING, concept_label STRING,
               role STRING, unit STRING, description STRING)
COMMENT 'Decode a cryptic RRS time-series name (e.g. RZ4.OAB.V1045) into its plain-English meaning: return, institution, datapoint concept, and balance-sheet line.'
RETURN
  SELECT ts.time_series_name, ts.return_code, ts.bank_code, ts.data_point_address,
         ts.bs_line, ts.label AS concept_label, ts.role, ts.unit, ts.description
  FROM {M}.time_series ts
  WHERE upper(ts.time_series_name) = upper(decode_time_series.series_name)
     OR lower(ts.time_series_key) = lower(decode_time_series.series_name)
""")
print("created decode_time_series")

# COMMAND ----------
# MAGIC %md ## get_series_values — value as-of a date + trailing history

# COMMAND ----------
spark.sql(f"""
CREATE OR REPLACE FUNCTION {V}.get_series_values(series_name STRING, as_of DATE,
                                                 history_months INT DEFAULT 12)
RETURNS TABLE (time_series_name STRING, bank_code STRING, data_point_address STRING,
               obs_date DATE, value DOUBLE, description STRING)
COMMENT 'Return a time series value as-of a date plus its trailing history (default 12 months). Parameterized to pull any series from any view.'
RETURN
  SELECT f.TIME_SERIES_NAME, f.BANK_CODE, f.DATA_POINT_ADDRESS, f.DATE AS obs_date,
         f.VALUE AS value, ts.description
  FROM {V}.vz4 f
  LEFT JOIN {M}.time_series ts ON ts.time_series_name = f.TIME_SERIES_NAME
  WHERE upper(f.TIME_SERIES_NAME) = upper(get_series_values.series_name)
    AND f.DATE <= get_series_values.as_of
    AND f.DATE > add_months(get_series_values.as_of, -get_series_values.history_months)
  ORDER BY f.DATE
""")
print("created get_series_values")

# COMMAND ----------
# MAGIC %md ## validate_return — evaluate ALL simple Z4 identities against a filing
# MAGIC For the given return/bank/date, join each rule's operands to the filed
# MAGIC values, sum the signed operands per (rule, side), and flag any rule whose
# MAGIC |LHS - RHS| exceeds its threshold. This runs every parsed simple identity.

# COMMAND ----------
spark.sql(f"""
CREATE OR REPLACE FUNCTION {V}.validate_return(return_code STRING, bank_code STRING, as_of DATE)
RETURNS TABLE (rule_id STRING, description STRING, bs_line STRING,
               lhs_expression STRING, rhs_expression STRING,
               lhs_value DOUBLE, rhs_value DOUBLE, difference DOUBLE,
               threshold INT, passed BOOLEAN)
COMMENT 'Evaluate all intra-return validation identities (EqualWithinThreshold sum rules) for a bank filing as-of a date. Returns each rule with its computed LHS vs RHS and pass/fail — the automated monthly-validation story.'
RETURN
  WITH filing AS (
    SELECT DATA_POINT_ADDRESS AS addr, VALUE
    FROM {V}.vz4
    WHERE BANK_CODE = validate_return.bank_code AND DATE = validate_return.as_of
  ),
  sides AS (
    SELECT o.rule_id, o.side,
           sum(o.sign * coalesce(f.VALUE, 0)) AS side_value
    FROM {M}.validation_rule_operands o
    LEFT JOIN filing f ON f.addr = o.data_point_address
    GROUP BY o.rule_id, o.side
  ),
  pivoted AS (
    SELECT rule_id,
           max(CASE WHEN side = 'lhs' THEN side_value END) AS lhs_value,
           max(CASE WHEN side = 'rhs' THEN side_value END) AS rhs_value
    FROM sides GROUP BY rule_id
  )
  SELECT r.rule_id, r.description, r.bs_line, r.lhs_expression, r.rhs_expression,
         p.lhs_value, p.rhs_value, (p.lhs_value - p.rhs_value) AS difference,
         r.threshold, abs(p.lhs_value - p.rhs_value) <= r.threshold AS passed
  FROM {M}.validation_rules r
  JOIN pivoted p ON p.rule_id = r.rule_id
  WHERE r.return_code = validate_return.return_code AND r.rule_class = 'simple'
  ORDER BY passed, abs(p.lhs_value - p.rhs_value) DESC
""")
print("created validate_return")

# COMMAND ----------
# MAGIC %md ## detect_outliers — values several std devs from the series' history

# COMMAND ----------
spark.sql(f"""
CREATE OR REPLACE FUNCTION {V}.detect_outliers(series_name STRING, z_threshold DOUBLE DEFAULT 3.0)
RETURNS TABLE (time_series_name STRING, obs_date DATE, value DOUBLE,
               mean_value DOUBLE, stddev_value DOUBLE, z_score DOUBLE, is_outlier BOOLEAN)
COMMENT 'Flag reported values that are several standard deviations from the series own historical norm (the config file guidance for spotting data errors).'
RETURN
  WITH s AS (
    SELECT TIME_SERIES_NAME, DATE, VALUE FROM {V}.vz4
    WHERE upper(TIME_SERIES_NAME) = upper(detect_outliers.series_name)
  ),
  stats AS (SELECT avg(VALUE) mu, stddev_samp(VALUE) sd FROM s)
  SELECT s.TIME_SERIES_NAME, s.DATE AS obs_date, s.VALUE,
         stats.mu AS mean_value, stats.sd AS stddev_value,
         CASE WHEN stats.sd > 0 THEN (s.VALUE - stats.mu) / stats.sd END AS z_score,
         CASE WHEN stats.sd > 0 THEN abs((s.VALUE - stats.mu) / stats.sd) > detect_outliers.z_threshold ELSE false END AS is_outlier
  FROM s CROSS JOIN stats
  ORDER BY s.DATE
""")
print("created detect_outliers")

# COMMAND ----------
# MAGIC %md ## mv_balance_sheet — governed metric view (curated canonical measures)
# MAGIC A UC metric view over the Z4 facts giving Genie clean business measures.
# MAGIC Measures are built from the curated canonical datapoint cells so the numbers
# MAGIC are interpretable (no double-counting of the redundant re-partition cells).

# COMMAND ----------
import os
import sys

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
from lib import z4_taxonomy

CM = z4_taxonomy.CANONICAL_METRICS
# Pivot the canonical datapoint cells (V-codes) into per-filing headline measures.
addr_case = ",\n           ".join(
    f"max(CASE WHEN DATA_POINT_ADDRESS = 'V{cell}' THEN VALUE END) AS {metric_key}"
    for metric_key, (cell, _label) in CM.items()
)

# Build a curated per-bank-per-date wide table, then the metric view over it.
spark.sql(f"""
CREATE OR REPLACE VIEW {M}.balance_sheet_headline AS
SELECT f.BANK_CODE AS bank_code, fi.short_name, fi.legal_name, fi.is_big6, f.DATE AS obs_date,
       {addr_case}
FROM {V}.vz4 f
JOIN {M}.financial_institutions fi ON fi.bank_code = f.BANK_CODE
GROUP BY f.BANK_CODE, fi.short_name, fi.legal_name, fi.is_big6, f.DATE
""")
spark.sql(f"COMMENT ON VIEW {M}.balance_sheet_headline IS 'Curated headline Z4 measures per bank per month-end (canonical cells only, no double-counting): total assets, loans, cash, deposits. Basis for the mv_balance_sheet metric view and Genie.'")
print("created balance_sheet_headline view")

# COMMAND ----------
# UC metric view (YAML spec) over the headline table.
metric_yaml = """version: 0.1
source: {M}.balance_sheet_headline
dimensions:
  - name: bank
    expr: short_name
  - name: legal_name
    expr: legal_name
  - name: is_big6
    expr: is_big6
  - name: obs_date
    expr: obs_date
measures:
  - name: total_assets
    expr: SUM(total_assets)
  - name: non_mortgage_loans
    expr: SUM(non_mortgage_loans)
  - name: cash_and_equivalents
    expr: SUM(cash_and_equivalents)
  - name: deposits_with_fis
    expr: SUM(deposits_with_fis)
  - name: demand_deposits
    expr: SUM(demand_deposits)
  - name: term_deposits
    expr: SUM(term_deposits)
  - name: total_deposits
    expr: SUM(demand_deposits) + SUM(term_deposits)
  - name: loan_to_deposit_ratio
    expr: SUM(non_mortgage_loans) / NULLIF(SUM(demand_deposits) + SUM(term_deposits), 0)
  - name: liquid_asset_ratio
    expr: (SUM(cash_and_equivalents) + SUM(deposits_with_fis)) / NULLIF(SUM(total_assets), 0)
""".replace("{M}", M)

try:
    spark.sql(f"""
    CREATE OR REPLACE VIEW {M}.mv_balance_sheet
    (bank COMMENT 'Bank short name', obs_date COMMENT 'Reporting month-end')
    WITH METRICS
    LANGUAGE YAML
    COMMENT 'Governed metric view over the Z4 balance sheet: total assets, loans, cash, deposits, loan-to-deposit and liquid-asset ratios. Lets Genie answer in business terms instead of cryptic datapoint codes.'
    AS $$
{metric_yaml}$$
    """)
    print("created metric view mv_balance_sheet")
except Exception as e:  # noqa: BLE001
    print(f"metric view creation note: {e}")
    print("Falling back to a plain aggregated view mv_balance_sheet.")
    spark.sql(f"""
    CREATE OR REPLACE VIEW {M}.mv_balance_sheet AS
    SELECT short_name AS bank, legal_name, is_big6, obs_date,
           total_assets, non_mortgage_loans, cash_and_equivalents,
           deposits_with_fis, demand_deposits, term_deposits,
           (demand_deposits + term_deposits) AS total_deposits,
           non_mortgage_loans / NULLIF(demand_deposits + term_deposits, 0) AS loan_to_deposit_ratio,
           (cash_and_equivalents + deposits_with_fis) / NULLIF(total_assets, 0) AS liquid_asset_ratio
    FROM {M}.balance_sheet_headline
    """)
    spark.sql(f"COMMENT ON VIEW {M}.mv_balance_sheet IS 'Governed balance-sheet measures over the Z4 return (total assets, loans, cash, deposits, loan-to-deposit and liquid-asset ratios) for Genie and the app.'")

# COMMAND ----------
print("05_create_uc_functions complete.")
display(spark.sql(f"SELECT * FROM {V}.decode_time_series('RZ4.OAB.V1045')"))
