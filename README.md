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
databricks.yml              DAB bundle (jobs + app, one deploy)
resources/ingestion_job.yml Ingestion job (serverless, daily schedule)
resources/validation_job.yml Resource validation job
resources/app.yml           Databricks App resource (source_code_path: ../app)
ingestion/                  Data download + prep notebooks (00-05)
genie/                      Genie space setup + semantic instructions
app/
  app.yaml                  Databricks App runtime config (env vars)
  app.py                    FastAPI entry (API + serves the static UI)
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
# 4. Backend (also serves the UI at http://localhost:8000)
uvicorn app:app --reload --port 8000
```

> There is no separate frontend build step — `app/static/index.html` is a
> no-build React UI (React + htm + Tailwind from a CDN) served directly by
> FastAPI. Just open the backend URL.

## Deploy

Everything — the ingestion/validation jobs **and** the app — ships from one
bundle. After a first-time provision, deploying (or redeploying) is two commands:

```bash
# Deploy all bundle resources (jobs + app source).
databricks bundle deploy -t dev -p fe-vm-boc
# Start / redeploy the app from the freshly-synced source.
databricks bundle run boc_agent -t dev -p fe-vm-boc
```

The app keeps a stable URL across redeploys. Env vars are defined in
`app/app.yaml` (not in the bundle), and `.venv/` + `__pycache__/` are ignored by
the bundle sync automatically.

### First-time provision (once per workspace)

```bash
# 1. UC schema + volume + MLflow experiment (experiment lands under the current user).
DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/provision.py
# 2. Genie space (prints space_id — put it in databricks.yml / app.yaml / .env).
DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/create_genie_space.py
# 3. Deploy the bundle, then build the data and start the app.
databricks bundle deploy -t dev -p fe-vm-boc
databricks bundle run boc_ingestion -t dev -p fe-vm-boc   # builds tables, VS index, grants
databricks bundle run boc_agent     -t dev -p fe-vm-boc   # starts the app
```

> The app was created by hand once and later adopted into the bundle via
> `databricks bundle deployment bind boc_agent boc-agent -t dev`. A clean
> workspace that has never had a `boc-agent` app skips the bind — `bundle deploy`
> creates it.

### Validate every resource
A bundle-deployed job tests tables, the anomaly function, the VS index, the
Genie space, the serving endpoints, and the app SP's UC grants — failing on any
error:
```bash
databricks bundle run boc_validation -t dev -p fe-vm-boc
```
(The `grants` task in the ingestion job applies the SP grants below idempotently.
To run validation *as* the app SP, an account admin grants the deployer the
`servicePrincipal.user` role, then set `run_as` in `resources/validation_job.yml`.)

> **Recovery:** if the `boc_demo` schema is ever dropped, recreate the schema +
> volume (only `provision.py` does this — the ingestion job does **not**), then
> re-run the ingestion job to rebuild everything (both are idempotent):
> ```bash
> DATABRICKS_CONFIG_PROFILE=fe-vm-boc app/.venv/bin/python scripts/provision.py
> databricks bundle run boc_ingestion -t dev -p fe-vm-boc
> ```
> The Genie space and Vector Search endpoint survive a schema drop; the job
> rebuilds the tables, the anomaly function, and the VS index, and re-applies the
> app SP grants.

### App service principal grants (applied by the `grants` job task)
- `CAN_QUERY` on `foundry-fast` / `foundry-reasoning` / `foundry-embedding`
- `CAN_USE` on the SQL warehouse and the Vector Search endpoint
- `USE CATALOG`/`USE SCHEMA`/`SELECT`/`EXECUTE` on `shm_catalog.boc_demo`
- `CAN_RUN` on the Genie space; `CAN_MANAGE` on the MLflow experiment
- `CAN_USE` on the Vector Search endpoint
