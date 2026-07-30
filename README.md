# Bank of Canada — Regulatory Returns Analyst

A Databricks App + data platform that turns the Bank of Canada FIS-DDS team's
**regulatory returns** into a governed, conversational analytics experience. It
models the **Z4 "Balance Sheet by Booking Location"** return (filed monthly by
the banks), decodes its cryptic time-series codes, evaluates the return's own
validation equations, and produces analyst-grade reports — all grounded in Unity
Catalog.

The centerpiece is **data organization at scale on Unity Catalog**: the cryptic
`RZ4.OAB.V1045` codes become documented, linkable, governed objects (comments,
concepts, common columns, lineage, functions, a metric view), so an analyst can
go from a filing to an insight and see the governance the whole way.

## What it does

1. **Decode cryptic codes.** `decode_time_series('RZ4.OAB.V1045')` → *Return Z4 ·
   Royal Bank of Canada · Total Assets*. The decoder ring is `metadata_db.time_series`.
2. **Query the balance sheets.** A Genie space over the **`mv_balance_sheet` metric
   view** answers business questions (total assets, loans, deposits, loan-to-deposit
   and liquid-asset ratios) across the Big Six and over time.
3. **Validate filings.** `validate_return('Z4','OAB', <date>)` evaluates **all ~330
   intra-Z4 `EqualWithinThreshold` identities** parsed from the reporting
   instructions and flags component sums that don't tie to their totals. All ~740
   equations (incl. cross-return checks to M4/J2/GQ/GR) are catalogued.
4. **Spot data errors.** `detect_outliers(series, z)` flags values several standard
   deviations from a series' own history (the config file's data-error heuristic).
5. **Cite the rules.** Vector Search over the Z4 reporting instructions lets the
   agent explain what each line (e.g. A1(a) Cash) includes/excludes.

The agent is a **fast router → deep-analyst** pair on native **GPT-5** endpoints
(mirroring the customer's GPT-5-in-Foundry setup), instrumented with **MLflow 3
tracing**, and served behind a React UI that surfaces Unity Catalog metadata,
lineage, and a live code decoder.

## Workspace

| Resource | Value |
| --- | --- |
| Workspace | `fevm-shm-skunkworks.cloud.databricks.com` (FEVM) |
| CLI profile | `fe-vm-shm-skunkworks` |
| Fast model (router) | `databricks-gpt-5-mini` |
| Reasoning model | `databricks-gpt-5` |
| Embeddings | `databricks-gte-large-en` (1024-dim) |
| SQL warehouse | `505ec857e6b4ea23` (Serverless Starter) |
| Views schema | `shm_catalog.views_db` (`vz4`, …) |
| Metadata schema | `shm_catalog.metadata_db` (decoder, concepts, rules, metric view) |
| Vector Search | endpoint `boc-vs-endpoint`, index `shm_catalog.metadata_db.instruction_chunks_index` |

## Data model (mirrors the customer's real layout)

```
views_db.vz4                         Z4 fact table: TIME_SERIES_NAME, BANK_CODE,
                                     DATA_POINT_ADDRESS, DATE, VALUE (long format)
metadata_db.returns                  one row per return (Z4, M4, A2, LA)
metadata_db.financial_institutions   the filers (RRS FI codes; the Big Six + others)
metadata_db.concepts                 balance-sheet concept taxonomy (A1..L8, totals)
metadata_db.datapoint_dictionary     every datapoint address -> concept + role
metadata_db.time_series              the decoder ring (rz4.oab.v1045#rrs -> meaning)
metadata_db.validation_rules         ALL Z4 equations (simple + complex)
metadata_db.validation_rule_operands each rule's operands, linked to datapoints
metadata_db.instruction_chunks       Z4 reporting instructions (Vector Search source)
metadata_db.mv_balance_sheet         governed metric view (curated headline measures)
```

Every table and key column carries a business-meaningful `COMMENT`; all return
tables share the identical column contract. The synthetic filings are
**internally consistent** — component values add to their totals so the real Z4
identities pass — with a couple of deliberately-seeded data errors for the
validation/anomaly demo.

### Configurable: synthetic vs. real data

Everything is parameterized by bundle variables (`catalog`, `views_schema`,
`metadata_schema`, endpoints, warehouse). A `data_mode` switch controls the
source:

- `synthetic` (default) — the ingestion job generates the demo filings.
- `existing` — skip generation and point the UC functions / metric view / Genie /
  app at the customer's **real** `views_db` / `metadata_db` tables. The schema
  contract is identical, so swapping in real RRS data is a config change.

## Repo layout

```
databricks.yml                 DAB bundle (jobs + app, one deploy)
resources/ingestion_job.yml    Ingestion job (metadata -> filings -> instructions -> VS -> functions -> grants)
resources/validation_job.yml   Resource validation job
resources/app.yml              Databricks App resource
ingestion/
  lib/                         parse_config_pdf, extract_instructions, z4_taxonomy,
                               generate_filings, reference_data, data_loader
  data/                        checked-in artifacts parsed from the config PDF
  01_returns_metadata.py       metadata_db (returns, FIs, concepts, dictionary, rules)
  02_generate_filings.py       views_db.vz4 + time_series decoder (+ seeded errors)
  03_instructions_corpus.py    instruction_chunks + general_instructions
  04_build_vs_index.py         Vector Search index over the instructions
  05_create_uc_functions.py    4 UC functions + mv_balance_sheet metric view
  00_grants.py                 app SP grants (both schemas)
app/                           FastAPI + no-build React UI (server/ tools, agent, routes)
scripts/                       provision.py, create_genie_space.py
validation/validate.py         end-to-end resource validation
info/                          the source config PDFs (Z4 instructions + equations)
```

### Regenerating the parsed artifacts

The `ingestion/data/*.json` artifacts are parsed once from the config PDF (so the
job needs neither the 4.9 MB PDF nor `pdftotext` at runtime):

```bash
python ingestion/lib/parse_config_pdf.py  --pdf "info/LLM_config_file_V1 ProtectedA Copy.pdf" --out ingestion/data
python ingestion/lib/extract_instructions.py --pdf "info/LLM_config_file_V1 ProtectedA Copy.pdf" --out ingestion/data
```

## Deploy

```bash
# 1. Provision schemas + MLflow experiment (once per workspace).
DATABRICKS_CONFIG_PROFILE=fe-vm-shm-skunkworks app/.venv/bin/python scripts/provision.py
# 2. Create the Genie space (prints config + space_id -> put in app.yaml / databricks.yml).
DATABRICKS_CONFIG_PROFILE=fe-vm-shm-skunkworks app/.venv/bin/python scripts/create_genie_space.py
# 3. Deploy the bundle, build the data, start the app.
databricks bundle deploy -t dev -p fe-vm-shm-skunkworks
databricks bundle run boc_ingestion -t dev -p fe-vm-shm-skunkworks
databricks bundle run boc_agent     -t dev -p fe-vm-shm-skunkworks
```

Validate every resource:

```bash
databricks bundle run boc_validation -t dev -p fe-vm-shm-skunkworks
```

## Local development

```bash
cd app && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp ../.env.example ../.env   # set GENIE_SPACE_ID / MLFLOW_EXPERIMENT_ID once created
set -a; . ../.env; set +a
uvicorn app:app --reload --port 8000   # serves the UI at http://localhost:8000
```
