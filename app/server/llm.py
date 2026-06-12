"""OpenAI client pointed at Databricks Foundry serving endpoints.

The Databricks serving layer exposes an OpenAI-compatible surface at
`{host}/serving-endpoints`, where the `model` argument is the serving-endpoint
name (e.g. "foundry-fast").
"""
from __future__ import annotations

import functools

from openai import OpenAI

from .config import get_settings


@functools.lru_cache(maxsize=1)
def get_client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.token(), base_url=f"{s.host}/serving-endpoints")


def fast_model() -> str:
    return get_settings().fast_endpoint


def reasoning_model() -> str:
    return get_settings().reasoning_endpoint


def embedding_model() -> str:
    return get_settings().embedding_endpoint


def embed(texts: list[str]) -> list[list[float]]:
    """Embed text via the Foundry embedding endpoint (query-side use)."""
    resp = get_client().embeddings.create(model=embedding_model(), input=texts)
    return [d.embedding for d in resp.data]
