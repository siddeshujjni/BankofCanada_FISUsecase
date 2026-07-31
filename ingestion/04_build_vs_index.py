# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Vector Search index (hybrid, managed embeddings)
# MAGIC Idempotently creates the Vector Search endpoint and a Delta-sync index over
# MAGIC `metadata_db.instruction_chunks` (the Z4 reporting instructions), embedding
# MAGIC `chunk_text` with the configured embedding endpoint. Hybrid search is
# MAGIC selected at query time (query_type="HYBRID").

# COMMAND ----------
# MAGIC %pip install -q databricks-vectorsearch
# MAGIC %restart_python

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("metadata_schema", "metadata_db")
dbutils.widgets.text("vs_endpoint", "boc-vs-endpoint")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("metadata_schema")
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")
EMBEDDING_ENDPOINT = dbutils.widgets.get("embedding_endpoint")

SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.instruction_chunks"
INDEX_NAME = f"{CATALOG}.{SCHEMA}.instruction_chunks_index"

# COMMAND ----------
from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient(disable_notice=True)

# 1. Endpoint (create if missing).
existing = {e["name"] for e in vsc.list_endpoints().get("endpoints", [])}
if VS_ENDPOINT not in existing:
    print(f"creating endpoint {VS_ENDPOINT} ...")
    vsc.create_endpoint_and_wait(name=VS_ENDPOINT, endpoint_type="STANDARD")
print(f"endpoint ready: {VS_ENDPOINT}")

# COMMAND ----------
# 2. Delta-sync index (create if missing, else trigger a sync).
def index_exists(name: str) -> bool:
    try:
        vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=name).describe()
        return True
    except Exception:  # noqa: BLE001
        return False


if index_exists(INDEX_NAME):
    print(f"index exists, syncing: {INDEX_NAME}")
    vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX_NAME).sync()
else:
    print(f"creating index: {INDEX_NAME}")
    vsc.create_delta_sync_index_and_wait(
        endpoint_name=VS_ENDPOINT,
        index_name=INDEX_NAME,
        source_table_name=SOURCE_TABLE,
        primary_key="chunk_id",
        embedding_source_column="chunk_text",
        embedding_model_endpoint_name=EMBEDDING_ENDPOINT,
        pipeline_type="TRIGGERED",
    )
print(f"index ready: {INDEX_NAME}")
