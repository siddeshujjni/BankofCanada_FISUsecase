# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Regulatory-returns metadata (the Unity Catalog backbone)
# MAGIC Seeds the `metadata_db` schema that turns the cryptic Z4 datapoint codes
# MAGIC into governed, linkable, documented Unity Catalog objects:
# MAGIC
# MAGIC - `returns` — one row per regulatory return (Z4, M4, A2, LA).
# MAGIC - `financial_institutions` — the filers (RRS FI codes, the Big Six + others).
# MAGIC - `concepts` — the balance-sheet concept taxonomy (Total Assets, Cash, …).
# MAGIC - `datapoint_dictionary` — every Z4 datapoint address → concept + role.
# MAGIC - `validation_rules` — ALL parsed Z4 validation equations (simple + complex).
# MAGIC - `validation_rule_operands` — each rule's operands linked to datapoints.
# MAGIC
# MAGIC Every table and key column carries a business-meaningful `COMMENT`, and
# MAGIC tables are tagged, so Catalog Explorer / Genie / lineage surface human
# MAGIC meaning for the cryptic codes. This is the "data organization at scale" story.

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
from lib import data_loader, reference_data, z4_taxonomy

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("metadata_schema", "metadata_db")
CATALOG = dbutils.widgets.get("catalog")
META = dbutils.widgets.get("metadata_schema")
FQ = f"{CATALOG}.{META}"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ} COMMENT 'Regulatory-returns metadata: the decoder, concept taxonomy, and validation rules that organize the Z4 return at scale.'")
print(f"metadata schema: {FQ}")

# COMMAND ----------
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType, BooleanType, IntegerType, StringType, StructField, StructType,
)


def esc(s):
    """Escape single quotes for safe embedding in a SQL string literal."""
    return str(s).replace("'", "''")


def set_tag(fqt, k, v):
    """Best-effort tag: some workspaces enforce a tag policy (allowed keys/values)."""
    try:
        spark.sql(f"ALTER TABLE {fqt} SET TAGS ('{esc(k)}' = '{esc(v)}')")
    except Exception as e:  # noqa: BLE001
        print(f"    (tag {k}={v} skipped: {str(e)[:80]})")


def write(df, name, comment, tags=None):
    fqt = f"{FQ}.{name}"
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqt)
    spark.sql(f"COMMENT ON TABLE {fqt} IS '{esc(comment)}'")
    for k, v in (tags or {}).items():
        set_tag(fqt, k, v)
    print(f"  wrote {fqt} ({df.count()} rows)")
    return fqt


def comment_columns(name, cols):
    for col, cmt in cols.items():
        spark.sql(f"ALTER TABLE {FQ}.{name} ALTER COLUMN {col} COMMENT '{esc(cmt)}'")

# COMMAND ----------
# MAGIC %md ## returns — one row per regulatory return


# COMMAND ----------
returns_schema = StructType([
    StructField("return_code", StringType()),
    StructField("return_title", StringType()),
    StructField("agency", StringType()),
    StructField("frequency", StringType()),
    StructField("statutory_basis", StringType()),
    StructField("last_updated", StringType()),
    StructField("purpose", StringType()),
])
returns_df = spark.createDataFrame(
    [(r["return_code"], r["return_title"], r["agency"], r["frequency"],
      r["statutory_basis"], r["last_updated"], r["purpose"]) for r in reference_data.RETURNS],
    returns_schema,
).withColumn("last_updated", F.to_date("last_updated"))
write(returns_df, "returns",
      "Regulatory returns filed by deposit-taking institutions (OSFI / Bank of Canada). The demo builds the Z4 return in full.",
      {"domain": "finance"})
comment_columns("returns", {
    "return_code": "Return code, e.g. Z4 = Balance Sheet by Booking Location.",
    "return_title": "Human title of the return.",
    "agency": "Collecting agency (Bank of Canada or OSFI).",
    "frequency": "Filing frequency (Monthly / Quarterly).",
    "statutory_basis": "Legal authority under which the return is collected.",
    "purpose": "What the return captures and how it is used.",
})

# COMMAND ----------
# MAGIC %md ## financial_institutions — the filers


# COMMAND ----------
fi_schema = StructType([
    StructField("bank_code", StringType()),
    StructField("short_name", StringType()),
    StructField("legal_name", StringType()),
    StructField("is_big6", BooleanType()),
    StructField("approx_total_assets_cad_000", IntegerType()),
])
fi_rows = [(b.bank_code, b.short_name, b.legal_name, b.is_big6, int(b.asset_scale))
           for b in reference_data.BANKS]
fi_df = spark.createDataFrame(fi_rows, fi_schema)
write(fi_df, "financial_institutions",
      "Deposit-taking institutions that file the returns. bank_code is the RRS FI code embedded in time-series names (RZ4.OAB.V1045 -> FI 'AB' = RBC). Big Six flagged; other Canadian and foreign-branch filers included at demo scale.",
      {"domain": "finance"})
comment_columns("financial_institutions", {
    "bank_code": "RRS financial-institution code (e.g. OAB). Appears in the middle segment of a time-series name.",
    "short_name": "Common abbreviation (RBC, TD, BNS, BMO, CIBC, NBC, …).",
    "legal_name": "Full legal name of the institution.",
    "is_big6": "True for the six largest Canadian banks.",
    "approx_total_assets_cad_000": "Approximate total assets in thousands of CAD (order-of-magnitude, for realistic demo filings).",
})

# COMMAND ----------
# MAGIC %md ## concepts — the balance-sheet concept taxonomy


# COMMAND ----------
concept_schema = StructType([
    StructField("concept_id", StringType()),
    StructField("bs_section", StringType()),
    StructField("bs_line", StringType()),
    StructField("label", StringType()),
    StructField("parent_id", StringType()),
    StructField("definition", StringType()),
])
concept_rows = [(c.concept_id, c.bs_section, c.bs_line, c.label, c.parent_id, c.definition)
                for c in z4_taxonomy.CONCEPTS]
concept_df = spark.createDataFrame(concept_rows, concept_schema)
write(concept_df, "concepts",
      "Balance-sheet concept taxonomy for the Z4 return (Section I Assets A1-A6, Section II Liabilities L1-L8, and roll-up totals), from the reporting instructions. Datapoints and validation rules link to these concepts so the cryptic codes become navigable meaning.",
      {"domain": "finance"})
comment_columns("concepts", {
    "concept_id": "Stable concept slug (e.g. A1, A3_a, TOTAL_ASSETS).",
    "bs_section": "Balance-sheet section (I - Assets / II - Liabilities).",
    "bs_line": "Balance-sheet line code (A1, A1(a), L1, …).",
    "label": "Human label of the concept.",
    "parent_id": "Parent concept_id in the hierarchy ('' for section totals).",
    "definition": "What the concept includes, from the Z4 reporting instructions.",
})

# COMMAND ----------
# MAGIC %md ## datapoint_dictionary — every Z4 datapoint address, decoded


# COMMAND ----------
rules_simple = data_loader.load_validation_rules_simple()
dictionary = z4_taxonomy.build_datapoint_dictionary(rules_simple)

dict_schema = StructType([
    StructField("data_point_address", StringType()),
    StructField("cell_code", StringType()),
    StructField("return_code", StringType()),
    StructField("bs_section", StringType()),
    StructField("bs_line", StringType()),
    StructField("concept_id", StringType()),
    StructField("label", StringType()),
    StructField("role", StringType()),
])
dict_df = spark.createDataFrame([tuple(d.values()) for d in dictionary], dict_schema)
write(dict_df, "datapoint_dictionary",
      "Every Z4 datapoint address (V-code) decoded: its balance-sheet line, concept, and role (total vs component). This is the key that turns V1045 into 'Total Assets'.",
      {"domain": "finance"})
comment_columns("datapoint_dictionary", {
    "data_point_address": "Datapoint address as it appears in the return (e.g. V1045).",
    "cell_code": "Numeric cell code used in the validation equations (e.g. 1045).",
    "return_code": "Return this datapoint belongs to (Z4).",
    "bs_line": "Balance-sheet line code (links to concepts.bs_line).",
    "concept_id": "Concept this datapoint measures (links to concepts.concept_id).",
    "label": "Human label of the datapoint.",
    "role": "'total' if the datapoint is a validation-rule subject, else 'component'.",
})

# COMMAND ----------
# MAGIC %md ## validation_rules — ALL parsed Z4 equations (simple + complex)


# COMMAND ----------
rules_complex = data_loader.load_validation_rules_complex()

rule_schema = StructType([
    StructField("rule_id", StringType()),
    StructField("return_code", StringType()),
    StructField("rule_class", StringType()),      # 'simple' | 'complex'
    StructField("description", StringType()),
    StructField("bs_line", StringType()),
    StructField("lhs_expression", StringType()),
    StructField("rhs_expression", StringType()),
    StructField("tolerance", IntegerType()),
    StructField("threshold", IntegerType()),
    StructField("references_returns", ArrayType(StringType())),
    StructField("formula", StringType()),
])
rule_rows = []
for r in rules_simple:
    rid = f"Z4-S{r['rule_index']:04d}"
    rule_rows.append((rid, "Z4", "simple", r.get("description", ""), r.get("bs_line", ""),
                      r["lhs_expression"], r["rhs_expression"], int(r["tolerance"]),
                      int(r["threshold"]), ["Z4"], r["raw"]))
for r in rules_complex:
    rid = f"Z4-C{r['rule_index']:04d}"
    rule_rows.append((rid, "Z4", "complex", r.get("description", ""), r.get("bs_line", ""),
                      None, None, None, None,
                      r.get("references_returns", []) or ["Z4"], r["raw"]))
rule_df = spark.createDataFrame(rule_rows, rule_schema)
write(rule_df, "validation_rules",
      "ALL Z4 validation equations parsed from the reporting instructions. 'simple' rules are intra-Z4 sum identities (evaluated by validate_return); 'complex' rules are conditional / cross-return checks (reconciling Z4 to M4, J2, GQ, GR) kept for completeness.",
      {"domain": "finance"})
comment_columns("validation_rules", {
    "rule_id": "Stable rule identifier.",
    "rule_class": "'simple' (intra-Z4 sum identity) or 'complex' (conditional/cross-return).",
    "description": "The rule's human description from the instructions (e.g. 'Components add to total A1(a)').",
    "bs_line": "Balance-sheet line the rule's total belongs to.",
    "lhs_expression": "Left-hand side (the total) for simple rules, e.g. [0100].",
    "rhs_expression": "Right-hand side (the component sum) for simple rules.",
    "tolerance": "Allowed signed tolerance (0 for exact sum rules).",
    "threshold": "Absolute threshold in $thousands within which the identity must hold.",
    "references_returns": "Returns referenced by the rule (Z4 alone, or M4/J2/GQ/GR for cross-return checks).",
    "formula": "The full original formula text as parsed from the instructions.",
})

# COMMAND ----------
# MAGIC %md ## validation_rule_operands — link each simple rule's operands to datapoints


# COMMAND ----------
op_schema = StructType([
    StructField("rule_id", StringType()),
    StructField("side", StringType()),           # 'lhs' | 'rhs'
    StructField("data_point_address", StringType()),
    StructField("cell_code", StringType()),
    StructField("sign", IntegerType()),
])
op_rows = []
for r in rules_simple:
    rid = f"Z4-S{r['rule_index']:04d}"
    for a in r["lhs_addresses"]:
        op_rows.append((rid, "lhs", f"V{a}", a, 1))
    # parse rhs signs
    import re as _re
    for sign, a in _re.findall(r"([+\-]?)\[(\d+)\]", r["rhs_expression"]):
        op_rows.append((rid, "rhs", f"V{a}", a, -1 if sign == "-" else 1))
op_df = spark.createDataFrame(op_rows, op_schema)
write(op_df, "validation_rule_operands",
      "Operands of each simple Z4 validation rule, linked to datapoint addresses so equations are joinable to datapoints and concepts (organization at scale, not opaque strings).",
      {"domain": "finance"})
comment_columns("validation_rule_operands", {
    "rule_id": "Rule this operand belongs to (links to validation_rules.rule_id).",
    "side": "'lhs' (the total) or 'rhs' (a component).",
    "data_point_address": "Operand datapoint address (links to datapoint_dictionary).",
    "sign": "+1 or -1, the operand's sign in the equation.",
})

# COMMAND ----------
print("01_returns_metadata complete.")
display(spark.sql(f"SHOW TABLES IN {FQ}"))
