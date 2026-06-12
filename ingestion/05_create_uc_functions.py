# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Anomaly-detection UC SQL function
# MAGIC Registers `detect_market_anomaly(symbol, lookback_days)` -> TABLE, flagging
# MAGIC days where the market close deviates more than 20% from the forecast.

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("schema", "boc_demo")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

# COMMAND ----------
spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.detect_market_anomaly(
  in_symbol STRING, lookback_days INT DEFAULT 30)
RETURNS TABLE (obs_date DATE, symbol STRING, close DOUBLE,
               forecast_value DOUBLE, pct_deviation DOUBLE, is_anomaly BOOLEAN)
COMMENT 'Flags days where market close deviates >20% from forecast for a symbol.'
RETURN
  SELECT p.obs_date, p.symbol, p.close, f.forecast_value,
         (p.close - f.forecast_value) / NULLIF(f.forecast_value, 0) AS pct_deviation,
         ABS((p.close - f.forecast_value) / NULLIF(f.forecast_value, 0)) > 0.20 AS is_anomaly
  FROM {CATALOG}.{SCHEMA}.market_prices p
  JOIN {CATALOG}.{SCHEMA}.market_forecast f
    ON p.symbol = f.symbol AND p.obs_date = f.obs_date
  WHERE p.symbol = detect_market_anomaly.in_symbol
    AND p.obs_date >= current_date() - make_interval(0, 0, 0, detect_market_anomaly.lookback_days)
  ORDER BY p.obs_date
""")
print(f"created {CATALOG}.{SCHEMA}.detect_market_anomaly")
