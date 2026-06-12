"""Anomaly tool — market data deviation detection.

Calls the UC SQL function `<catalog>.<schema>.detect_market_anomaly(symbol,
lookback_days)` via the SQL Statement Execution API and returns flagged rows
(>20% deviation from forecast) as references.
"""
from __future__ import annotations

import mlflow

from ..config import get_settings
from ..sql import run_sql

ANOMALY_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "detect_market_anomaly",
        "description": (
            "Detect anomalies in market data (FX, commodities, index funds) by "
            "flagging days where the close deviates more than 20% from a simple "
            "5-day moving-average forecast. Use for questions about unusual market "
            "moves, spikes, or risk. Known symbols: USDCAD, EURUSD, WTI, GOLD, "
            "SP500, NASDAQ."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Market symbol, e.g. WTI, GOLD, SP500, USDCAD."},
                "lookback_days": {"type": "integer", "description": "Days to look back.", "default": 30},
            },
            "required": ["symbol"],
        },
    },
}


@mlflow.trace(span_type="TOOL")
def detect_anomaly(symbol: str, lookback_days: int = 30) -> dict:
    s = get_settings()
    symbol = symbol.strip().upper()
    rows = run_sql(
        f"SELECT * FROM {s.anomaly_function}('{symbol}', {int(lookback_days)})"
    )
    anomalies = [r for r in rows if str(r.get("is_anomaly")).lower() == "true"]
    return {
        "symbol": symbol,
        "lookback_days": lookback_days,
        "rows_checked": len(rows),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "references": [
            {
                "type": "anomaly",
                "label": f"{a.get('symbol')} {a.get('obs_date')}",
                "close": a.get("close"),
                "forecast": a.get("forecast_value"),
                "pct_deviation": a.get("pct_deviation"),
            }
            for a in anomalies
        ],
    }
