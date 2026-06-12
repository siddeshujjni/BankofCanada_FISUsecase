"""Central configuration and dual-mode authentication.

Two runtime modes:
  * Databricks Apps  — identity comes from the app service principal; the SDK
    auto-discovers host/token from the injected DATABRICKS_* env vars. The
    end-user identity arrives per-request via X-Forwarded-* headers.
  * Local dev        — uses the `fe-vm-boc` CLI profile.
"""
from __future__ import annotations

import functools
import os

from databricks.sdk import WorkspaceClient


def _is_databricks_app() -> bool:
    # Databricks Apps set DATABRICKS_APP_NAME in the runtime environment.
    return bool(os.environ.get("DATABRICKS_APP_NAME"))


class Settings:
    """Resolved configuration, read once from the environment."""

    def __init__(self) -> None:
        self.is_app = _is_databricks_app()
        self.profile = os.environ.get("DATABRICKS_CONFIG_PROFILE", "fe-vm-boc")

        # Foundry serving endpoints (model= is the endpoint name).
        self.fast_endpoint = os.environ.get("FOUNDRY_FAST_ENDPOINT", "foundry-fast")
        self.reasoning_endpoint = os.environ.get("FOUNDRY_REASONING_ENDPOINT", "foundry-reasoning")
        self.embedding_endpoint = os.environ.get("FOUNDRY_EMBEDDING_ENDPOINT", "foundry-embedding")

        # Unity Catalog namespace.
        self.catalog = os.environ.get("UC_CATALOG", "shm_catalog")
        self.schema = os.environ.get("UC_SCHEMA", "boc_demo")

        # Tool backends.
        self.sql_warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "d94339f8fe9c593a")
        self.vs_endpoint = os.environ.get("VS_ENDPOINT", "boc-vs-endpoint")
        self.vs_index = os.environ.get("VS_INDEX", f"{self.catalog}.{self.schema}.policy_docs_index")
        self.anomaly_function = os.environ.get(
            "UC_ANOMALY_FUNCTION", f"{self.catalog}.{self.schema}.detect_market_anomaly"
        )
        self.genie_space_id = os.environ.get("GENIE_SPACE_ID", "01f166aad95716d1995c011a0473f1d7")

        # MLflow tracing target.
        self.mlflow_experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID", "574544292485229")

    @functools.cached_property
    def workspace_client(self) -> WorkspaceClient:
        if self.is_app:
            return WorkspaceClient()
        return WorkspaceClient(profile=self.profile)

    @property
    def host(self) -> str:
        host = self.workspace_client.config.host or ""
        if host and not host.startswith("http"):
            host = f"https://{host}"
        return host.rstrip("/")

    def token(self) -> str:
        """A bearer token for the current principal (app SP or local user)."""
        auth = self.workspace_client.config.authenticate()
        return auth.get("Authorization", "").replace("Bearer ", "")


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
