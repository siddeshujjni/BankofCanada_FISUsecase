"""End-to-end smoke test of the agent's governed tools + a full agent turn.

    DATABRICKS_CONFIG_PROFILE=fe-vm-shm-skunkworks app/.venv/bin/python scripts/smoke_test.py

Exercises each UC-backed tool against the live workspace, then (optionally) runs a
full agent turn on the flagship prompt. Prints PASS/FAIL per check.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from server.tools.returns_tools import (  # noqa: E402
    decode_time_series, detect_outliers, get_series_values, validate_return,
)

results = []
def check(name, fn):
    try:
        d = fn()
        results.append((name, "PASS", d)); print(f"PASS  {name}: {d}")
    except Exception as e:  # noqa: BLE001
        results.append((name, "FAIL", str(e)[:200])); print(f"FAIL  {name}: {str(e)[:200]}")

check("decode_time_series", lambda: (decode_time_series("RZ4.OAB.V1045")["decoded"][:1] or "no rows"))
check("get_series_values", lambda: f"{len(get_series_values('RZ4.OAB.V1045')['values'])} rows")
check("validate_return (RBC, seeded error expected)",
      lambda: f"{len(validate_return('OAB')['failures'])} failing rules")
check("detect_outliers (RBC total assets)",
      lambda: f"{len(detect_outliers('RZ4.OAB.V1045')['outliers'])} outliers")

# Optional: a full agent turn (needs GENIE_SPACE_ID + endpoints).
if "--agent" in sys.argv:
    from server.agent import BankOfCanadaAgent
    agent = BankOfCanadaAgent()
    q = "What does RZ4.OAB.V1045 mean, and what is RBC's most recent value for it?"
    print(f"\n--- agent turn: {q}\n")
    text = ""
    for ev in agent.stream([{"role": "user", "content": q}]):
        if ev["type"] == "delta":
            text += ev["text"]
        elif ev["type"] == "done":
            text = ev["text"]
    print(text[:1200])

fails = [r for r in results if r[1] == "FAIL"]
print(f"\n{len(results) - len(fails)}/{len(results)} tool checks passed")
sys.exit(1 if fails else 0)
