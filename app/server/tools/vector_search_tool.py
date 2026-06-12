"""Vector Search tool — regulatory/policy documents (hybrid search).

Hybrid similarity search over the policy_docs index; returns chunk text plus
metadata (doc_title, source_url, page) so the UI can render source references.
"""
from __future__ import annotations

import functools

import mlflow
from databricks.vector_search.client import VectorSearchClient

from ..config import get_settings

VECTOR_SEARCH_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "search_policy_documents",
        "description": (
            "Search Bank of Canada regulatory and policy documents (monetary "
            "policy, inflation framework, financial-system resilience, currency, "
            "funds management) for relevant passages. Returns excerpts with their "
            "source document, URL, and page so answers can cite references."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in the policy corpus."},
                "k": {"type": "integer", "description": "Number of passages to return.", "default": 5},
            },
            "required": ["query"],
        },
    },
}

_COLUMNS = ["chunk_text", "doc_title", "source_url", "page"]


@functools.lru_cache(maxsize=1)
def _index():
    s = get_settings()
    vsc = VectorSearchClient(
        workspace_url=s.host, personal_access_token=s.token(), disable_notice=True
    )
    return vsc.get_index(endpoint_name=s.vs_endpoint, index_name=s.vs_index)


@mlflow.trace(span_type="RETRIEVER")
def search_policy(query: str, k: int = 5) -> dict:
    res = _index().similarity_search(
        query_text=query,
        columns=_COLUMNS,
        num_results=k,
        query_type="HYBRID",
    )
    data = res.get("result", {}).get("data_array", []) or []
    cols = [c["name"] for c in res.get("manifest", {}).get("columns", [])]
    passages = []
    for row in data:
        rec = dict(zip(cols, row))
        passages.append(rec)
    return {
        "query": query,
        "passages": passages,
        "references": [
            {
                "type": "document",
                "label": p.get("doc_title", "Policy document"),
                "url": p.get("source_url"),
                "page": p.get("page"),
                "snippet": (p.get("chunk_text") or "")[:240],
            }
            for p in passages
        ],
    }
