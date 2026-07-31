# Databricks notebook source
# MAGIC %md
# MAGIC # Resource validation
# MAGIC Tests every resource the agent depends on: the two schemas' tables, the
# MAGIC four UC functions, the metric view, the Vector Search index, the serving
# MAGIC endpoints, the Genie space, and (if set) the app SP's UC grants. Prints a
# MAGIC PASS/FAIL table and raises if any check fails.

# COMMAND ----------
# MAGIC %pip install -q databricks-vectorsearch
# MAGIC %restart_python

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("views_schema", "views_db")
dbutils.widgets.text("metadata_schema", "metadata_db")
dbutils.widgets.text("vs_endpoint", "boc-vs-endpoint")
dbutils.widgets.text("genie_space_id", "")
dbutils.widgets.text("app_sp", "")
dbutils.widgets.text("fast_endpoint", "databricks-gpt-5-mini")
dbutils.widgets.text("reasoning_endpoint", "databricks-gpt-5")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
CAT = dbutils.widgets.get("catalog")
V = f"{CAT}.{dbutils.widgets.get('views_schema')}"
M = f"{CAT}.{dbutils.widgets.get('metadata_schema')}"
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")
SPACE = dbutils.widgets.get("genie_space_id")
APP_SP = dbutils.widgets.get("app_sp")
FAST = dbutils.widgets.get("fast_endpoint")
REASON = dbutils.widgets.get("reasoning_endpoint")
EMBED = dbutils.widgets.get("embedding_endpoint")

from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
print(f"Running validation as: {w.current_user.me().user_name}")

results = []
def check(name, fn):
    try:
        detail = fn()
        results.append((name, "PASS", detail)); print(f"PASS  {name}: {detail}")
    except Exception as e:  # noqa: BLE001
        results.append((name, "FAIL", str(e)[:300])); print(f"FAIL  {name}: {str(e)[:300]}")

# COMMAND ----------
# 1. Tables.
for t in ["vz4"]:
    check(f"table {V.split('.')[-1]}.{t}", lambda t=t: f"{spark.table(f'{V}.{t}').count()} rows")
for t in ["returns", "financial_institutions", "concepts", "datapoint_dictionary",
          "validation_rules", "validation_rule_operands", "time_series", "instruction_chunks"]:
    check(f"table metadata_db.{t}", lambda t=t: f"{spark.table(f'{M}.{t}').count()} rows")

# 2. UC functions.
def _get_values():
    q = "SELECT * FROM " + V + ".get_series_values('RZ4.OAB.V1045', current_date(), 24)"
    return f"{spark.sql(q).count()} rows"
def _decode2():
    q = "SELECT * FROM " + V + ".decode_time_series('RZ4.OAB.V1045')"
    return f"{spark.sql(q).count()} rows"
check("fn decode_time_series", _decode2)
check("fn get_series_values", _get_values)
def _validate():
    q = ("SELECT * FROM " + V + ".validate_return('Z4','OAB',"
         "(SELECT max(DATE) FROM " + V + ".vz4 WHERE BANK_CODE='OAB'))")
    df = spark.sql(q)
    return f"{df.count()} rules, {df.filter('NOT passed').count()} failing (expect >=1 seeded)"
check("fn validate_return", _validate)
def _outliers():
    df = spark.sql(f"SELECT * FROM {V}.detect_outliers('RZ4.OAB.V1045', 3.0)")
    return f"{df.count()} rows, {df.filter('is_outlier').count()} outliers (expect >=1 seeded)"
check("fn detect_outliers", _outliers)

# 3. Metric view.
check("metric view mv_balance_sheet", lambda: f"{spark.table(f'{M}.mv_balance_sheet').count()} rows")

# 4. Serving endpoints.
def _chat(model):
    c = w.serving_endpoints.get_open_ai_client()
    # GPT-5 endpoints reject max_tokens (use max_completion_tokens) — omit for portability.
    r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": "ping"}])
    return (r.choices[0].message.content or "")[:20]
check(f"serving {FAST}", lambda: _chat(FAST))
check(f"serving {REASON}", lambda: _chat(REASON))
def _embed():
    r = w.serving_endpoints.get_open_ai_client().embeddings.create(model=EMBED, input=["hello"])
    return f"dim={len(r.data[0].embedding)}"
check(f"serving {EMBED}", _embed)

# 5. Vector Search index.
def _vs():
    from databricks.vector_search.client import VectorSearchClient
    idx = VectorSearchClient(disable_notice=True).get_index(
        endpoint_name=VS_ENDPOINT, index_name=f"{M}.instruction_chunks_index")
    res = idx.similarity_search(query_text="cash and cash equivalents", columns=["bs_line"], num_results=3, query_type="HYBRID")
    return f"{len(res.get('result', {}).get('data_array', []))} hits"
check("vector search instruction_chunks_index", _vs)

# 6. App SP UC grants (only if app_sp provided).
if APP_SP:
    def _sp_grants():
        have = set()
        for scope in (f"SCHEMA {V}", f"SCHEMA {M}", f"CATALOG {CAT}"):
            for r in spark.sql(f"SHOW GRANTS ON {scope}").collect():
                if r["Principal"] == APP_SP:
                    have.add(r["ActionType"])
        need = {"USE CATALOG", "USE SCHEMA", "SELECT", "EXECUTE"}
        missing = need - have
        if missing:
            raise RuntimeError(f"app SP missing: {missing}")
        return f"app SP has {sorted(need)}"
    check("app SP UC grants", _sp_grants)

# 7. Genie space (only if set).
if SPACE:
    def _genie():
        msg = w.genie.start_conversation_and_wait(SPACE, "What are the total assets of RBC in the latest Z4 filing?")
        txt = ""
        for att in msg.attachments or []:
            if getattr(att, "text", None) and getattr(att.text, "content", None):
                txt = att.text.content
        return (txt or "answered")[:60]
    check("genie space", _genie)

# COMMAND ----------
fails = [r for r in results if r[1] == "FAIL"]
lines = ["==== VALIDATION SUMMARY ===="]
lines += [f"{status:4}  {name:42} {detail}" for name, status, detail in results]
lines.append(f"{len(results) - len(fails)}/{len(results)} passed")
summary = "\n".join(lines)
print("\n" + summary)
if fails:
    raise RuntimeError(f"{len(fails)} check(s) FAILED: " + ", ".join(f[0] for f in fails) + "\n" + summary)
dbutils.notebook.exit(summary)
