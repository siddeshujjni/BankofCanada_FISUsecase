# Bank of Canada Conversational Agent

A Databricks App that lets users converse with Bank of Canada data through three tools:

1. **Genie Space** — Bank of Canada **public data** (policy rate, yields, CPI, FX).
2. **Anomaly detection** — a Unity Catalog SQL function over **market data** (FX, commodities, indices) that flags >20% deviation from a simple forecast.
3. **Vector Search** — **regulatory/policy documents** (hybrid search) with source references in the UI.

The agent calls **Foundry serving endpoints** through the OpenAI client, is instrumented with **MLflow 3 tracing to Unity Catalog** (session_id = conversation history), and ships with a **React + FastAPI** frontend carrying Bank of Canada branding.

## Workspace

| Resource | Value |
| --- | --- |
| Workspace | `fevm-serverless-stable-qr9if1.cloud.databricks.com` (FEVM) |
| CLI profile | `fe-vm-boc` |
| Fast model | `foundry-fast` → gpt-5.4-nano |
| Reasoning model | `foundry-reasoning` → gpt-5.4 |
| Embeddings | `foundry-embedding` → text-embedding-3-small (1536-dim) |
| SQL warehouse | `d94339f8fe9c593a` (Serverless Starter) |
| UC namespace | `shm_catalog.boc_demo` |
| Genie space | `01f166aad95716d1995c011a0473f1d7` |
| Vector Search | endpoint `boc-vs-endpoint`, index `shm_catalog.boc_demo.policy_docs_index` |
| MLflow experiment | `574544292485229` |
| Deployed app | https://boc-agent-7474643830998004.aws.databricksapps.com |
| App service principal | `f9284cb5-df03-4b35-8d72-0e01f45fe00e` (`app-16b4vw boc-agent`) |

## Repo layout

```
databricks.yml              DAB bundle (ingestion job + schedule)
resources/ingestion_job.yml Job definition (serverless, daily)
ingestion/                  Data download + prep notebooks (01-05)
genie/                      Genie space setup + semantic instructions
app/
  app.yaml                  Databricks App runtime config
  app.py                    FastAPI entry (API + serves React build)
  requirements.txt
  server/
    config.py               Settings + dual-mode auth (Apps vs local)
    llm.py                  OpenAI client -> Foundry endpoints
    agent.py                Router (foundry-fast) + deep-investigation subagent (foundry-reasoning)
    tracing.py              Session/user tagging, per-user history, feedback
    sql.py                  SQL Statement Execution helper
    tools/                  genie_tool, anomaly_tool, vector_search_tool
    routes/                 chat, sessions, feedback, user
  static/index.html         No-build React UI (CDN React + htm + Tailwind)
scripts/                    provision.py, create_genie_space.py
```

> The frontend is a single static `index.html` that loads React from a CDN at
> runtime — no npm/build step. FastAPI serves it.

## Local development

```bash
# 1. Auth (already done): profile fe-vm-boc
# 2. Python deps
cd app && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
# 3. Env
cp ../.env.example ../.env   # edit GENIE_SPACE_ID / MLFLOW_EXPERIMENT_ID once created
set -a; . ../.env; set +a
# 4. Backend
uvicorn app:app --reload --port 8000
# 5. Frontend (separate shell)
cd app/frontend && npm install && npm run dev   # Vite proxies /api -> :8000
```

## Provision & deploy (one-time)

```bash
# 1. UC schema + volume + MLflow experiment
DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/provision.py
# 2. Genie space (prints space_id; written into config)
DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/create_genie_space.py
# 3. Data plane: ingestion job (5 tasks) + daily schedule
databricks bundle deploy -t dev -p fe-vm-boc
databricks bundle run boc_ingestion -t dev -p fe-vm-boc
# 4. App (no build step — static UI loads React from CDN)
databricks apps create boc-agent -p fe-vm-boc        # once
databricks sync app/ /Workspace/Users/<you>/boc-agent-src -p fe-vm-boc \
  --exclude ".venv/**" --exclude "__pycache__/**"
databricks apps deploy boc-agent \
  --source-code-path /Workspace/Users/<you>/boc-agent-src -p fe-vm-boc
```

### App service principal grants (already applied)
- `CAN_QUERY` on `foundry-fast` / `foundry-reasoning` / `foundry-embedding`
- `CAN_USE` on the SQL warehouse and the Vector Search endpoint
- `USE CATALOG`/`USE SCHEMA`/`SELECT`/`EXECUTE` on `shm_catalog.boc_demo`
- `CAN_RUN` on the Genie space; `CAN_MANAGE` on the MLflow experiment

See `/Users/scott.mckean/.claude/plans/cozy-discovering-lampson.md` for the full build plan.
