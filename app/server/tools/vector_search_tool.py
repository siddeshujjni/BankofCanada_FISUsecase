"""Vector Search tool — Z4 reporting instructions (hybrid search).

Hybrid similarity search over the reporting-instruction index; returns the
instruction passage plus metadata (balance-sheet line, section title) so the
agent can cite the actual reporting rule for a line item.
"""
from __future__ import annotations

import functools

import mlflow
from databricks.vector_search.client import VectorSearchClient

from ..config import get_settings

VECTOR_SEARCH_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "search_reporting_instructions",
        "description": (
            "Search the official Z4 reporting instructions (what each balance-sheet "
            "line includes and excludes — e.g. A1(a) Cash and Cash Equivalents, A3 "
            "Loans, L1 Demand and Notice Deposits). Use to explain how a line is "
            "defined or what belongs in it, and to ground answers in the rules. "
            "Returns passages with their balance-sheet line and section."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in the instructions."},
                "k": {"type": "integer", "description": "Number of passages to return.", "default": 5},
            },
            "required": ["query"],
        },
    },
}

_COLUMNS = ["chunk_text", "bs_line", "section_title", "return_code"]


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
        query_text=query, columns=_COLUMNS, num_results=k, query_type="HYBRID"
    )
    data = res.get("result", {}).get("data_array", []) or []
    cols = [c["name"] for c in res.get("manifest", {}).get("columns", [])]
    passages = [dict(zip(cols, row)) for row in data]
    return {
        "query": query,
        "passages": passages,
        "references": [
            {
                "type": "instruction",
                "label": (p.get("section_title") or f"Z4 {p.get('bs_line', '')}").strip(),
                "bs_line": p.get("bs_line"),
                "snippet": (p.get("chunk_text") or "")[:240],
            }
            for p in passages
        ],
    }
