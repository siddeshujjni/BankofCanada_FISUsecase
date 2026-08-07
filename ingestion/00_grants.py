# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Grant the app service principal access to every resource
# MAGIC Idempotent. Grants the app SP what it needs: UC on both schemas
# MAGIC (`views_db` + `metadata_db`), serving endpoints (CAN_QUERY), the SQL
# MAGIC warehouse (CAN_USE), the Genie space (CAN_RUN), and the Vector Search
# MAGIC endpoint (CAN_USE). Skips gracefully if `app_sp` is not yet set (first
# MAGIC data build, before the app exists).

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("views_schema", "views_db")
dbutils.widgets.text("metadata_schema", "metadata_db")
dbutils.widgets.text("validation_schema", "validation_db")
dbutils.widgets.text("app_sp", "")
dbutils.widgets.text("warehouse_id", "505ec857e6b4ea23")
dbutils.widgets.text("vs_endpoint", "boc-vs-endpoint")
dbutils.widgets.text("genie_space_id", "")
dbutils.widgets.text("mlflow_experiment_id", "")
dbutils.widgets.text("serving_endpoints", "databricks-gpt-5,databricks-gpt-5-mini,databricks-gpt-5-nano,databricks-gte-large-en")

CAT = dbutils.widgets.get("catalog")
VIEWS = dbutils.widgets.get("views_schema")
META = dbutils.widgets.get("metadata_schema")
VAL = dbutils.widgets.get("validation_schema")
SP = dbutils.widgets.get("app_sp").strip()
WH = dbutils.widgets.get("warehouse_id")
VS = dbutils.widgets.get("vs_endpoint")
SPACE = dbutils.widgets.get("genie_space_id").strip()
EXP = dbutils.widgets.get("mlflow_experiment_id").strip()
ENDPOINTS = [e.strip() for e in dbutils.widgets.get("serving_endpoints").split(",") if e.strip()]

if not SP:
    dbutils.notebook.exit("app_sp not set — skipping grants (run again after the app exists).")

# COMMAND ----------
# Unity Catalog grants on both schemas.
spark.sql(f"GRANT USE CATALOG ON CATALOG {CAT} TO `{SP}`")
for sch in (VIEWS, META, VAL):
    try:
        spark.sql(f"GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA {CAT}.{sch} TO `{SP}`")
        print(f"UC grants applied to {SP} on {CAT}.{sch}")
    except Exception as e:  # noqa: BLE001 — validation_db may not exist on first run
        print(f"skip grants on {CAT}.{sch}: {str(e)[:80]}")
# The app writes MLflow traces to UC tables in the metadata schema — needs write.
spark.sql(f"GRANT MODIFY, CREATE TABLE ON SCHEMA {CAT}.{META} TO `{SP}`")
print(f"MODIFY, CREATE TABLE granted on {CAT}.{META} (for UC-backed MLflow traces)")

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import serving
from databricks.sdk.service import sql as sqlsvc

w = WorkspaceClient()

# Serving endpoints: CAN_QUERY.
for name in ENDPOINTS:
    try:
        ep = w.serving_endpoints.get(name)
        w.serving_endpoints.update_permissions(
            serving_endpoint_id=ep.id,
            access_control_list=[serving.ServingEndpointAccessControlRequest(
                service_principal_name=SP, permission_level=serving.ServingEndpointPermissionLevel.CAN_QUERY)],
        )
        print(f"CAN_QUERY -> {name}")
    except Exception as e:  # noqa: BLE001
        print(f"skip endpoint {name}: {e}")

# SQL warehouse: CAN_USE.
w.warehouses.update_permissions(
    warehouse_id=WH,
    access_control_list=[sqlsvc.WarehouseAccessControlRequest(
        service_principal_name=SP, permission_level=sqlsvc.WarehousePermissionLevel.CAN_USE)],
)
print(f"CAN_USE -> warehouse {WH}")

# COMMAND ----------
# Genie space (CAN_RUN) and Vector Search endpoint (CAN_USE) via the permissions API.
if SPACE:
    w.api_client.do("PATCH", f"/api/2.0/permissions/genie/{SPACE}",
                    body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_RUN"}]})
    print(f"CAN_RUN -> genie space {SPACE}")

vs_id = next((e.id for e in w.vector_search_endpoints.list_endpoints() if e.name == VS), None)
if vs_id:
    w.api_client.do("PATCH", f"/api/2.0/permissions/vector-search-endpoints/{vs_id}",
                    body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_USE"}]})
    print(f"CAN_USE -> vector search endpoint {VS} ({vs_id})")

# MLflow experiment (CAN_MANAGE) so the app can set the experiment and log traces.
if EXP:
    try:
        w.api_client.do("PATCH", f"/api/2.0/permissions/experiments/{EXP}",
                        body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_MANAGE"}]})
        print(f"CAN_MANAGE -> mlflow experiment {EXP}")
    except Exception as e:  # noqa: BLE001
        print(f"skip experiment grant: {e}")
print("grants complete")
