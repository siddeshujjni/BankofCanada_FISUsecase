# Databricks notebook source
# MAGIC %md
# MAGIC # Resource validation
# MAGIC Runs (ideally **as the app service principal** — see validation_job.yml
# MAGIC `run_as`) and tests every resource the agent depends on: tables, the
# MAGIC anomaly UC function, the Vector Search index, the Genie space, and the
# MAGIC three Foundry serving endpoints. Prints a PASS/FAIL table and raises if any
# MAGIC check fails, so the job surfaces the exact error.

# COMMAND ----------
# MAGIC %pip install -q databricks-vectorsearch
# MAGIC %restart_python

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("schema", "boc_demo")
dbutils.widgets.text("vs_endpoint", "boc-vs-endpoint")
dbutils.widgets.text("genie_space_id", "01f166aad95716d1995c011a0473f1d7")
dbutils.widgets.text("app_sp", "f9284cb5-df03-4b35-8d72-0e01f45fe00e")
CAT = dbutils.widgets.get("catalog")
SCH = dbutils.widgets.get("schema")
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")
SPACE = dbutils.widgets.get("genie_space_id")
APP_SP = dbutils.widgets.get("app_sp")
NS = f"{CAT}.{SCH}"

from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
me = w.current_user.me()
print(f"Running validation as: {me.user_name} (id {me.id})")

results = []
def check(name, fn):
    try:
        detail = fn()
        results.append((name, "PASS", detail))
        print(f"PASS  {name}: {detail}")
    except Exception as e:  # noqa: BLE001
        results.append((name, "FAIL", str(e)[:300]))
        print(f"FAIL  {name}: {str(e)[:300]}")

# COMMAND ----------
# 1. Tables.
for t in ["boc_rates", "market_prices", "market_forecast", "policy_docs_chunks"]:
    check(f"table {t}", lambda t=t: f"{spark.table(f'{NS}.{t}').count()} rows")

# 2. Anomaly UC function.
def _anomaly():
    q = f"SELECT * FROM {NS}.detect_market_anomaly('GOLD', 60)"
    df = spark.sql(q)
    total = df.count()
    anomalies = df.filter("is_anomaly").count()
    return f"{total} rows, {anomalies} anomalies"
check("function detect_market_anomaly", _anomaly)

# 3. Serving endpoints.
def _chat(model):
    c = w.serving_endpoints.get_open_ai_client()
    r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=5)
    return r.choices[0].message.content[:20]
check("serving foundry-fast", lambda: _chat("foundry-fast"))
check("serving foundry-reasoning", lambda: _chat("foundry-reasoning"))

def _embed():
    c = w.serving_endpoints.get_open_ai_client()
    r = c.embeddings.create(model="foundry-embedding", input=["hello"])
    return f"dim={len(r.data[0].embedding)}"
check("serving foundry-embedding", _embed)

# 4. Vector Search index.
def _vs():
    from databricks.vector_search.client import VectorSearchClient
    idx = VectorSearchClient(disable_notice=True).get_index(
        endpoint_name=VS_ENDPOINT, index_name=f"{NS}.policy_docs_index")
    res = idx.similarity_search(query_text="inflation target", columns=["doc_title"], num_results=3, query_type="HYBRID")
    return f"{len(res.get('result', {}).get('data_array', []))} hits"
check("vector search policy_docs_index", _vs)

# 5. App service-principal UC grants (proves the deployed app can access UC).
def _sp_grants():
    have = set()
    for r in spark.sql(f"SHOW GRANTS ON SCHEMA {NS}").collect():
        if r["Principal"] == APP_SP:
            have.add(r["ActionType"])
    for r in spark.sql(f"SHOW GRANTS ON CATALOG {CAT}").collect():
        if r["Principal"] == APP_SP:
            have.add(r["ActionType"])
    need = {"USE CATALOG", "USE SCHEMA", "SELECT", "EXECUTE"}
    missing = need - have
    if missing:
        raise RuntimeError(f"app SP missing UC privileges: {missing}")
    return f"app SP has {sorted(need)}"
check("app SP UC grants", _sp_grants)

# 6. Genie space.
def _genie():
    msg = w.genie.start_conversation_and_wait(SPACE, "What is the latest overnight target rate?")
    txt = ""
    for att in msg.attachments or []:
        if getattr(att, "text", None) and getattr(att.text, "content", None):
            txt = att.text.content
    return (txt or "answered")[:60]
check("genie space", _genie)

# COMMAND ----------
fails = [r for r in results if r[1] == "FAIL"]
lines = ["==== VALIDATION SUMMARY ===="]
lines += [f"{status:4}  {name:38} {detail}" for name, status, detail in results]
lines.append(f"{len(results) - len(fails)}/{len(results)} passed")
summary = "\n".join(lines)
print("\n" + summary)
if fails:
    # RuntimeError (not SystemExit) guarantees the job task is marked FAILED.
    raise RuntimeError(f"{len(fails)} check(s) FAILED: " + ", ".join(f[0] for f in fails) + "\n" + summary)
dbutils.notebook.exit(summary)
