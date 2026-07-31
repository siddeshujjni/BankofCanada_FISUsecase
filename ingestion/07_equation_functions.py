# Databricks notebook source
# MAGIC %md
# MAGIC # 07 — Equations → a whole schema of UC functions (`validation_db`)
# MAGIC Materializes each Z4 validation identity as its own **governed Unity Catalog
# MAGIC function** in `{catalog}.validation_db` (the schema the FIS team's real
# MAGIC catalog uses for validation). Every rule becomes discoverable, runnable from
# MAGIC SQL/Genie, lineage-tracked to `views_db.vz4`, and reusable — turning the
# MAGIC equation table into a first-class, queryable governance surface.
# MAGIC
# MAGIC Produces:
# MAGIC - `validation_db.z4_s0000 … z4_sNNNN(bank_code, as_of)` — one function per
# MAGIC   simple identity, returning lhs/rhs/difference/threshold/passed.
# MAGIC - `validation_db.run_all(bank_code, as_of)` — evaluates every rule at once.
# MAGIC - `validation_db.rule_catalog` — a browsable index of the rules.

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
from lib import data_loader, equation_functions as eqf

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("views_schema", "views_db")
dbutils.widgets.text("metadata_schema", "metadata_db")
dbutils.widgets.text("validation_schema", "validation_db")
dbutils.widgets.text("limit", "0")   # 0 = all rules; set small for a quick test
CATALOG = dbutils.widgets.get("catalog")
VIEWS = dbutils.widgets.get("views_schema")
META = dbutils.widgets.get("metadata_schema")
VAL = dbutils.widgets.get("validation_schema")
LIMIT = int(dbutils.widgets.get("limit"))

spark.sql(
    f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{VAL} "
    f"COMMENT 'Validation functions for the regulatory returns — one governed UC "
    f"function per Z4 identity, plus run_all and a rule_catalog. Turns the equation "
    f"set into a discoverable, runnable, lineage-tracked governance surface.'"
)
print(f"validation schema: {CATALOG}.{VAL}")

# COMMAND ----------
# MAGIC %md ## Emit one UC function per simple identity

# COMMAND ----------
rules = data_loader.load_validation_rules_simple()
# The single-address-LHS identities are the cleanly evaluable ones (component sums
# tie to a total). Multi-address-LHS rules are alternate partitions kept in metadata.
simple = [r for r in rules if len(r["lhs_addresses"]) == 1]
if LIMIT:
    simple = simple[:LIMIT]

created, failed = 0, []
for r in simple:
    ddl = eqf.build_function_ddl(CATALOG, VIEWS, VAL, r)
    try:
        spark.sql(ddl)
        created += 1
    except Exception as e:  # noqa: BLE001
        failed.append((eqf.rule_id(r), str(e)[:120]))
print(f"created {created} validation functions in {CATALOG}.{VAL}")
if failed:
    print(f"{len(failed)} failed:")
    for rid, err in failed[:10]:
        print(f"  {rid}: {err}")

# COMMAND ----------
# MAGIC %md ## run_all — evaluate every rule for a bank/date in one call

# COMMAND ----------
# Build a single function that UNION-ALLs every per-rule function, so a consumer
# can validate an entire filing with one call and filter to failures.
union = "\n  UNION ALL\n  ".join(
    f"SELECT * FROM {eqf.function_name(CATALOG, VAL, r)}(run_all.bank_code, run_all.as_of)"
    for r in simple
)
run_all_ddl = f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{VAL}.run_all(bank_code STRING, as_of DATE)
RETURNS TABLE (rule_id STRING, description STRING, bs_line STRING,
               lhs_value DOUBLE, rhs_value DOUBLE, difference DOUBLE,
               threshold INT, passed BOOLEAN)
COMMENT 'Run every Z4 validation rule for a bank filing as-of a date; UNION of all per-rule functions. Filter WHERE NOT passed to see data errors.'
RETURN
  {union}
"""
try:
    spark.sql(run_all_ddl)
    print(f"created {CATALOG}.{VAL}.run_all (unions {len(simple)} rules)")
except Exception as e:  # noqa: BLE001
    print(f"run_all creation note: {str(e)[:160]}")

# COMMAND ----------
# MAGIC %md ## rule_catalog — browsable index of the generated functions

# COMMAND ----------
spark.sql(eqf.build_catalog_view_ddl(CATALOG, VAL, META))
spark.sql(
    f"COMMENT ON VIEW {CATALOG}.{VAL}.rule_catalog IS "
    f"'Browsable catalog of the Z4 validation rules that back the {VAL} functions "
    f"(rule id, balance-sheet line, description, formula, threshold).'"
)
print(f"created {CATALOG}.{VAL}.rule_catalog")

# COMMAND ----------
# MAGIC %md ## Verify — run a couple of functions + run_all on RBC's seeded-error filing

# COMMAND ----------
latest = spark.sql(
    f"SELECT max(DATE) d FROM {CATALOG}.{VIEWS}.vz4 WHERE BANK_CODE='OAB'"
).first()["d"]
print("latest OAB filing:", latest)
sample_fn = eqf.function_name(CATALOG, VAL, simple[0])
display(spark.sql(f"SELECT * FROM {sample_fn}('OAB', DATE'{latest}')"))
fails = spark.sql(
    f"SELECT count(*) n, sum(CASE WHEN NOT passed THEN 1 ELSE 0 END) failing "
    f"FROM {CATALOG}.{VAL}.run_all('OAB', DATE'{latest}')"
).first()
print(f"run_all: {fails['n']} rules, {fails['failing']} failing (expect >=1 seeded)")

# COMMAND ----------
print("07_equation_functions complete.")
# List the generated functions via information_schema (SHOW ... IN cat.schema
# rejects a cross-catalog reference, so query the catalog instead).
display(spark.sql(f"""
    SELECT routine_name, left(comment, 80) AS comment
    FROM {CATALOG}.information_schema.routines
    WHERE routine_schema = '{VAL}'
    ORDER BY routine_name
    LIMIT 15
"""))
