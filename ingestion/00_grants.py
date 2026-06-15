# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Grant the app service principal access to every resource
# MAGIC Idempotent. Deployed and run by the DAB bundle so resource access is
# MAGIC reproducible: UC (catalog/schema/select/execute), serving endpoints
# MAGIC (CAN_QUERY), SQL warehouse (CAN_USE), Genie space (CAN_RUN), and the
# MAGIC Vector Search endpoint (CAN_USE).

# COMMAND ----------
dbutils.widgets.text("catalog", "shm_catalog")
dbutils.widgets.text("schema", "boc_demo")
dbutils.widgets.text("app_sp", "f9284cb5-df03-4b35-8d72-0e01f45fe00e")
dbutils.widgets.text("warehouse_id", "d94339f8fe9c593a")
dbutils.widgets.text("vs_endpoint", "boc-vs-endpoint")
dbutils.widgets.text("genie_space_id", "01f166aad95716d1995c011a0473f1d7")
dbutils.widgets.text("serving_endpoints", "foundry-fast,foundry-reasoning,foundry-embedding")

CAT = dbutils.widgets.get("catalog")
SCH = dbutils.widgets.get("schema")
SP = dbutils.widgets.get("app_sp")
WH = dbutils.widgets.get("warehouse_id")
VS = dbutils.widgets.get("vs_endpoint")
SPACE = dbutils.widgets.get("genie_space_id")
ENDPOINTS = [e.strip() for e in dbutils.widgets.get("serving_endpoints").split(",") if e.strip()]

# COMMAND ----------
# Unity Catalog grants.
spark.sql(f"GRANT USE CATALOG ON CATALOG {CAT} TO `{SP}`")
spark.sql(f"GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA {CAT}.{SCH} TO `{SP}`")
print(f"UC grants applied to {SP} on {CAT}.{SCH}")

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import serving
from databricks.sdk.service import sql as sqlsvc

w = WorkspaceClient()

# Serving endpoints: CAN_QUERY.
for name in ENDPOINTS:
    ep = w.serving_endpoints.get(name)
    w.serving_endpoints.update_permissions(
        serving_endpoint_id=ep.id,
        access_control_list=[serving.ServingEndpointAccessControlRequest(
            service_principal_name=SP, permission_level=serving.ServingEndpointPermissionLevel.CAN_QUERY)],
    )
    print(f"CAN_QUERY -> {name}")

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

vs_id = next((e["id"] for e in w.vector_search_endpoints.list_endpoints().as_dict().get("endpoints", [])
              if e.get("name") == VS), None)
if vs_id:
    w.api_client.do("PATCH", f"/api/2.0/permissions/vector-search-endpoints/{vs_id}",
                    body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_USE"}]})
    print(f"CAN_USE -> vector search endpoint {VS} ({vs_id})")
print("grants complete")
