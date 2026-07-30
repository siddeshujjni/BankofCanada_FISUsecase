# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Reporting-instruction corpus (for Vector Search)
# MAGIC Loads the machine-readable Z4 reporting instructions (Chapter 2 of the
# MAGIC config file) into `metadata_db.instruction_chunks`, chunked and tagged with
# MAGIC the balance-sheet line each passage covers. The agent's
# MAGIC `search_reporting_instructions` tool retrieves from the Vector Search index
# MAGIC built over this table so answers cite the actual reporting rule (e.g. what
# MAGIC A1(a) "Cash and Cash Equivalents" includes / excludes).
# MAGIC
# MAGIC Chapter 1 (general instructions) is loaded into `metadata_db.general_instructions`
# MAGIC (one row) and is also embedded in the agent's system prompt.

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
from lib import data_loader

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("metadata_schema", "metadata_db")
CATALOG = dbutils.widgets.get("catalog")
META = dbutils.widgets.get("metadata_schema")
FQ = f"{CATALOG}.{META}"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ}")

# COMMAND ----------
from pyspark.sql.types import StringType, StructField, StructType

chunks = data_loader.load_instruction_chunks()
chunk_schema = StructType([
    StructField("chunk_id", StringType()),
    StructField("return_code", StringType()),
    StructField("bs_line", StringType()),
    StructField("section_title", StringType()),
    StructField("chunk_text", StringType()),
])
chunk_df = spark.createDataFrame([tuple(c.values()) for c in chunks], chunk_schema)
chunks_tbl = f"{FQ}.instruction_chunks"
chunk_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(chunks_tbl)
spark.sql(f"ALTER TABLE {chunks_tbl} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
spark.sql(f"COMMENT ON TABLE {chunks_tbl} IS 'Z4 reporting-instruction passages (Chapter 2), chunked and tagged with balance-sheet line. Source corpus for the Vector Search index the agent cites when explaining reporting rules.'")
for col, cmt in {
    "chunk_id": "Stable chunk identifier (primary key for the VS index).",
    "return_code": "Return the passage belongs to (Z4).",
    "bs_line": "Balance-sheet line the passage covers (A1, A3(a), L1, …).",
    "section_title": "Heading of the section the passage falls under.",
    "chunk_text": "The instruction text (embedded for retrieval).",
}.items():
    spark.sql(f"ALTER TABLE {chunks_tbl} ALTER COLUMN {col} COMMENT '{cmt}'")
try:
    spark.sql(f"ALTER TABLE {chunks_tbl} SET TAGS ('domain' = 'finance')")
except Exception as e:  # noqa: BLE001
    print(f"(tag skipped: {str(e)[:80]})")
print(f"wrote {chunks_tbl}: {chunk_df.count()} chunks")

# COMMAND ----------
# General instructions (Chapter 1) — one row, also used in the agent prompt.
ch1 = data_loader.load_chapter1_instructions()
gi_df = spark.createDataFrame([("Z4", "general", ch1)], StructType([
    StructField("return_code", StringType()),
    StructField("kind", StringType()),
    StructField("instructions", StringType()),
]))
gi_tbl = f"{FQ}.general_instructions"
gi_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(gi_tbl)
spark.sql(f"COMMENT ON TABLE {gi_tbl} IS 'General reporting/analyst instructions (Chapter 1): abbreviations, the households/non-financial-business focus, and the data-error heuristic. Fed to the agent as context, mirroring how the customer feeds a config file to GPT-5.'")
print(f"wrote {gi_tbl}")

# COMMAND ----------
print("03_instructions_corpus complete.")
display(spark.sql(f"SELECT bs_line, count(*) chunks FROM {chunks_tbl} GROUP BY bs_line ORDER BY bs_line"))
