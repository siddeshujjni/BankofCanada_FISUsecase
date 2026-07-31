"""Genie tool — conversational analytics over the governed regulatory-returns
metric view (Genie One).

Uses the Genie Conversation API. The Genie `conversation_id` is threaded back to
the caller so multi-turn analytics stay coherent within a chat session. Returns
the answer text, the generated SQL (surfaced as a reference), and rows.
"""
from __future__ import annotations

import mlflow

from ..config import get_settings

GENIE_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "query_returns_data",
        "description": (
            "Answer quantitative questions about the banks' regulatory-return "
            "balance sheets using the governed metric view: total assets, loans, "
            "cash and cash equivalents, deposits, loan-to-deposit and liquid-asset "
            "ratios, by bank and reporting date. Use for comparisons across the Big "
            "Six, trends over time, and rankings. Returns a natural-language answer "
            "plus the SQL and rows Genie used."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's data question."}
            },
            "required": ["question"],
        },
    },
}


def _extract(genie, space_id: str, msg) -> dict:
    """Pull answer text, SQL, and result rows out of a Genie message."""
    answer_parts: list[str] = []
    sql: str | None = None
    rows: list[dict] = []

    for att in msg.attachments or []:
        text = getattr(att, "text", None)
        if text and getattr(text, "content", None):
            answer_parts.append(text.content)
        query = getattr(att, "query", None)
        if query:
            sql = getattr(query, "query", None)
            if getattr(query, "description", None):
                answer_parts.append(query.description)
            try:
                result = genie.get_message_attachment_query_result(
                    space_id, msg.conversation_id, msg.id, att.attachment_id
                )
                sr = result.statement_response
                if sr and sr.result and sr.result.data_array and sr.manifest:
                    cols = [c.name for c in sr.manifest.schema.columns]
                    rows = [dict(zip(cols, r)) for r in sr.result.data_array]
            except Exception:  # noqa: BLE001
                pass

    return {"answer": "\n\n".join(answer_parts).strip(), "sql": sql, "rows": rows}


@mlflow.trace(span_type="TOOL")
def query_genie(question: str, conversation_id: str | None = None) -> dict:
    s = get_settings()
    if not s.genie_space_id:
        return {"answer": "", "sql": None, "rows": [], "error": "GENIE_SPACE_ID not configured"}
    genie = s.workspace_client.genie
    if conversation_id:
        msg = genie.create_message_and_wait(s.genie_space_id, conversation_id, question)
    else:
        msg = genie.start_conversation_and_wait(s.genie_space_id, question)

    out = _extract(genie, s.genie_space_id, msg)
    out["conversation_id"] = msg.conversation_id
    refs = []
    if out["sql"]:
        refs.append({"type": "sql", "label": "Genie SQL", "sql": out["sql"]})
    out["references"] = refs
    return out
