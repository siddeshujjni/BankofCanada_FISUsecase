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

        # Serving endpoints (model= is the endpoint name). Defaults target the
        # native GPT-5 family on the skunkworks workspace, mirroring the customer's
        # GPT-5-in-Foundry setup.
        self.fast_endpoint = os.environ.get("FAST_ENDPOINT", "databricks-gpt-5-mini")
        self.reasoning_endpoint = os.environ.get("REASONING_ENDPOINT", "databricks-gpt-5")
        self.embedding_endpoint = os.environ.get("EMBEDDING_ENDPOINT", "databricks-gte-large-en")

        # Unity Catalog namespace: two schemas mirroring the customer's layout.
        self.catalog = os.environ.get("UC_CATALOG", "shm_catalog")
        self.views_schema = os.environ.get("VIEWS_SCHEMA", "views_db")
        self.metadata_schema = os.environ.get("METADATA_SCHEMA", "metadata_db")
        self.validation_schema = os.environ.get("VALIDATION_SCHEMA", "validation_db")

        # Tool backends.
        self.sql_warehouse_id = os.environ.get("SQL_WAREHOUSE_ID", "505ec857e6b4ea23")
        self.vs_endpoint = os.environ.get("VS_ENDPOINT", "boc-vs-endpoint")
        self.vs_index = os.environ.get(
            "VS_INDEX", f"{self.catalog}.{self.metadata_schema}.instruction_chunks_index"
        )
        # UC functions (governed tools).
        self.fn_decode = f"{self.catalog}.{self.views_schema}.decode_time_series"
        self.fn_get_values = f"{self.catalog}.{self.views_schema}.get_series_values"
        self.fn_validate = f"{self.catalog}.{self.views_schema}.validate_return"
        self.fn_outliers = f"{self.catalog}.{self.views_schema}.detect_outliers"
        self.metric_view = f"{self.catalog}.{self.metadata_schema}.mv_balance_sheet"
        self.genie_space_id = os.environ.get("GENIE_SPACE_ID", "")

        # MLflow tracing target.
        self.mlflow_experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID", "")

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
