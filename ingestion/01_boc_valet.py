# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bank of Canada public data (Valet API)
# MAGIC Downloads policy rate / bond yields / CPI / FX from the public Valet API
# MAGIC into `{catalog}.{schema}.boc_rates`. No authentication required.

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("schema", "boc_demo")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

# COMMAND ----------
import requests

# series_id -> (friendly label, unit)
SERIES = {
    "V39079": ("Target for the overnight rate", "percent"),
    "FXUSDCAD": ("USD/CAD noon exchange rate", "CAD per USD"),
    "BD.CDN.2YR.DQ.YLD": ("Government of Canada 2-year benchmark bond yield", "percent"),
    "BD.CDN.5YR.DQ.YLD": ("Government of Canada 5-year benchmark bond yield", "percent"),
    "BD.CDN.10YR.DQ.YLD": ("Government of Canada 10-year benchmark bond yield", "percent"),
    "V41690973": ("Consumer Price Index, all-items (2002=100)", "index"),
}

url = (
    "https://www.bankofcanada.ca/valet/observations/"
    + ",".join(SERIES.keys())
    + "/json?start_date=2015-01-01"
)
payload = requests.get(url, timeout=90).json()
detail = payload.get("seriesDetail", {})
observations = payload.get("observations", [])

rows = []
for obs in observations:
    obs_date = obs.get("d")
    for sid, (label, unit) in SERIES.items():
        cell = obs.get(sid)
        if not cell:
            continue
        v = cell.get("v")
        if v in (None, ""):
            continue
        rows.append((sid, detail.get(sid, {}).get("label", label), obs_date, float(v), unit))

print(f"parsed {len(rows)} observations across {len(SERIES)} series")

# COMMAND ----------
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

schema = StructType([
    StructField("series_id", StringType()),
    StructField("series_label", StringType()),
    StructField("obs_date", StringType()),
    StructField("value", DoubleType()),
    StructField("unit", StringType()),
])
df = spark.createDataFrame(rows, schema).withColumn("obs_date", F.to_date("obs_date"))
(
    df.write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.boc_rates")
)
print(f"wrote {df.count()} rows to {CATALOG}.{SCHEMA}.boc_rates")
display(spark.sql(f"SELECT series_id, count(*) n, max(obs_date) latest FROM {CATALOG}.{SCHEMA}.boc_rates GROUP BY series_id ORDER BY series_id"))
