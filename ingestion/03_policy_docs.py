# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Regulatory / policy documents -> chunks
# MAGIC Fetches stable Bank of Canada policy pages, strips to text, chunks with
# MAGIC overlap, and writes `policy_docs_chunks` (Change Data Feed enabled so the
# MAGIC Vector Search Delta-sync index can track it).

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("schema", "boc_demo")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

# COMMAND ----------
import hashlib
import re

import requests

# Stable Bank of Canada policy / core-function pages (public HTML).
PAGES = {
    "mp_overview": "https://www.bankofcanada.ca/core-functions/monetary-policy/",
    "mp_inflation": "https://www.bankofcanada.ca/core-functions/monetary-policy/inflation/",
    "mp_key_rate": "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
    "fin_system": "https://www.bankofcanada.ca/core-functions/financial-system/",
    "fin_resilience": "https://www.bankofcanada.ca/core-functions/financial-system/financial-system-resilience/",
    "currency": "https://www.bankofcanada.ca/core-functions/currency/",
    "funds_mgmt": "https://www.bankofcanada.ca/core-functions/funds-management/",
}

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_WS = re.compile(r"\s+")


def to_text(html: str) -> str:
    html = _SCRIPT.sub(" ", html)
    html = _TAG.sub(" ", html)
    html = re.sub(r"&[a-z]+;", " ", html)
    return _WS.sub(" ", html).strip()


def chunk(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    out, start = [], 0
    while start < len(text):
        out.append(text[start : start + size])
        start += size - overlap
    return out


rows = []
for doc_id, url in PAGES.items():
    try:
        html = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as e:  # noqa: BLE001
        print(f"{doc_id}: FAILED ({e})")
        continue
    m = _TITLE.search(html)
    title = (m.group(1).strip() if m else doc_id).replace(" - Bank of Canada", "")
    body = to_text(html)
    for i, ch in enumerate(chunk(body)):
        if len(ch.strip()) < 50:
            continue
        cid = hashlib.md5(f"{doc_id}-{i}".encode()).hexdigest()
        rows.append((cid, doc_id, title, url, 1, ch))
    print(f"{doc_id}: {len([r for r in rows if r[1] == doc_id])} chunks ({title})")

print(f"total {len(rows)} chunks")

# COMMAND ----------
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

schema = StructType([
    StructField("chunk_id", StringType()),
    StructField("doc_id", StringType()),
    StructField("doc_title", StringType()),
    StructField("source_url", StringType()),
    StructField("page", IntegerType()),
    StructField("chunk_text", StringType()),
])
table = f"{CATALOG}.{SCHEMA}.policy_docs_chunks"
spark.createDataFrame(rows, schema).write.mode("overwrite").option(
    "overwriteSchema", "true"
).saveAsTable(table)

# Change Data Feed is required for the Vector Search Delta-sync index.
spark.sql(f"ALTER TABLE {table} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print(f"wrote {spark.table(table).count()} chunks to {table} (CDF enabled)")
display(spark.sql(f"SELECT doc_id, doc_title, count(*) chunks FROM {table} GROUP BY doc_id, doc_title ORDER BY doc_id"))
