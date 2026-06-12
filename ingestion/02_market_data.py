# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Market data + forecast (FX, commodities, indices)
# MAGIC Real FX from the Frankfurter API (ECB reference rates, free/no key) plus
# MAGIC realistic synthetic commodity/index series (no reliable key-free source).
# MAGIC Writes `market_prices`, computes a 5-day moving-average forecast into
# MAGIC `market_forecast`, and seeds one demonstrable >20% anomaly.

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("schema", "boc_demo")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

# COMMAND ----------
import datetime as dt

import numpy as np
import requests

START = (dt.date.today() - dt.timedelta(days=420)).isoformat()

# --- Real FX from Frankfurter (base USD) -------------------------------------
fx = requests.get(
    f"https://api.frankfurter.dev/v1/{START}..?base=USD&symbols=CAD,EUR,GBP,JPY",
    timeout=90,
).json()["rates"]
trading_days = sorted(fx.keys())  # ECB business days = our trading calendar

rows = []
for d in trading_days:
    for ccy, rate in fx[d].items():
        rows.append((f"USD{ccy}", "fx", d, float(rate)))
print(f"FX: {len([r for r in rows if r[1]=='fx'])} rows over {len(trading_days)} days")

# --- Synthetic commodities / indices (geometric brownian motion) -------------
np.random.seed(42)
SYNTH = {  # symbol -> (asset_class, start_level, annual_vol)
    "WTI": ("commodity", 78.0, 0.35),
    "GOLD": ("commodity", 2_320.0, 0.16),
    "SP500": ("index", 5_200.0, 0.18),
    "NASDAQ": ("index", 16_400.0, 0.22),
}
for symbol, (asset_class, level, vol) in SYNTH.items():
    daily_vol = vol / np.sqrt(252)
    price = level
    for d in trading_days:
        price *= float(np.exp(np.random.normal(-0.5 * daily_vol**2, daily_vol)))
        rows.append((symbol, asset_class, d, round(price, 2)))
print(f"total {len(rows)} price rows ({len(SYNTH)} synthetic symbols)")

# COMMAND ----------
from pyspark.sql import Window
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

price_schema = StructType([
    StructField("symbol", StringType()),
    StructField("asset_class", StringType()),
    StructField("obs_date", StringType()),
    StructField("close", DoubleType()),
])
prices = spark.createDataFrame(rows, price_schema).withColumn("obs_date", F.to_date("obs_date"))

# 5-day trailing moving-average forecast (uses the prior 5 closes).
w = Window.partitionBy("symbol").orderBy("obs_date").rowsBetween(-5, -1)
forecast = (
    prices.withColumn("forecast_value", F.avg("close").over(w))
    .where(F.col("forecast_value").isNotNull())
    .select("symbol", "obs_date", F.round("forecast_value", 4).alias("forecast_value"))
)

# COMMAND ----------
# Seed a demonstrable anomaly: override GOLD's latest close to 30% above forecast.
seed_symbol = "GOLD"
seed_date = prices.where(F.col("symbol") == seed_symbol).agg(F.max("obs_date")).first()[0]
seed_fc = forecast.where((F.col("symbol") == seed_symbol) & (F.col("obs_date") == seed_date)).first()
if seed_fc:
    seed_close = round(float(seed_fc["forecast_value"]) * 1.30, 4)
    prices = prices.withColumn(
        "close",
        F.when(
            (F.col("symbol") == seed_symbol) & (F.col("obs_date") == F.lit(seed_date)),
            F.lit(seed_close),
        ).otherwise(F.col("close")),
    )
    print(f"seeded anomaly: {seed_symbol} {seed_date} close={seed_close} (forecast {seed_fc['forecast_value']})")
else:
    print("WARNING: no forecast row to seed anomaly against")

# COMMAND ----------
prices.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.market_prices")
forecast.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.market_forecast")
print(f"wrote {prices.count()} prices, {forecast.count()} forecasts")
display(spark.sql(f"SELECT symbol, asset_class, count(*) n, max(obs_date) latest FROM {CATALOG}.{SCHEMA}.market_prices GROUP BY symbol, asset_class ORDER BY symbol"))
