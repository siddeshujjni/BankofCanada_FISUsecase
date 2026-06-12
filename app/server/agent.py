"""Agent core — a tool-calling loop over the Foundry endpoints.

Selects/executes tools with the fast model (`foundry-fast`), then streams the
final synthesized answer with the reasoning model (`foundry-reasoning`).
Tools:
  * query_bank_of_canada_data  (Genie)
  * detect_market_anomaly      (UC SQL function)
  * search_policy_documents    (Vector Search)

MLflow tracing: tool functions are decorated with @mlflow.trace and OpenAI calls
are auto-traced (mlflow.openai.autolog in tracing.init_tracing); the FastAPI
route opens the per-turn root span and tags it with session_id + user.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from .llm import fast_model, get_client, reasoning_model
from .tools.anomaly_tool import ANOMALY_TOOL_SPEC, detect_anomaly
from .tools.genie_tool import GENIE_TOOL_SPEC, query_genie
from .tools.vector_search_tool import VECTOR_SEARCH_TOOL_SPEC, search_policy

TOOL_SPECS = [GENIE_TOOL_SPEC, ANOMALY_TOOL_SPEC, VECTOR_SEARCH_TOOL_SPEC]

SYSTEM_PROMPT = (
    "You are the Bank of Canada Data Assistant. You help users with Canadian "
    "monetary data, market anomalies, and regulatory policy.\n"
    "- Use query_bank_of_canada_data for the policy/overnight rate, bond yields, "
    "CPI/inflation, and the USD/CAD exchange rate.\n"
    "- Use detect_market_anomaly for unusual moves in market data (FX, "
    "commodities, indices).\n"
    "- Use search_policy_documents for questions about Bank of Canada policy, "
    "mandate, or frameworks.\n"
    "Prefer tools over prior knowledge. Always cite the references the tools "
    "return, and be concise and precise with numbers and dates."
)

_MAX_TOOL_ROUNDS = 4


def _fields(tc) -> tuple[str, str, str]:
    """Normalize a tool call that may be an object or a raw dict."""
    if isinstance(tc, dict):
        fn = tc.get("function", {})
        return tc.get("id", ""), fn.get("name", ""), fn.get("arguments", "{}")
    return tc.id, tc.function.name, tc.function.arguments


class BankOfCanadaAgent:
    def __init__(self) -> None:
        self.client = get_client()

    def _run_tool(self, name: str, args: dict, state: dict) -> dict:
        if name == "query_bank_of_canada_data":
            out = query_genie(args["question"], state.get("genie_conversation_id"))
            if out.get("conversation_id"):
                state["genie_conversation_id"] = out["conversation_id"]
            return out
        if name == "detect_market_anomaly":
            return detect_anomaly(args["symbol"], int(args.get("lookback_days", 30)))
        if name == "search_policy_documents":
            return search_policy(args["query"], int(args.get("k", 5)))
        return {"error": f"unknown tool {name}"}

    def stream(self, messages: list[dict], state: dict | None = None) -> Iterator[dict]:
        """Yield event dicts: tool / references / delta / done."""
        state = state or {}
        convo: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
        all_refs: list[dict] = []

        for _ in range(_MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=fast_model(), messages=convo, tools=TOOL_SPECS, tool_choice="auto"
            )
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                break

            convo.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": i, "type": "function", "function": {"name": n, "arguments": a}}
                    for (i, n, a) in (_fields(tc) for tc in tool_calls)
                ],
            })
            names = [_fields(tc)[1] for tc in tool_calls]
            yield {"type": "tool", "names": names, "status": "running"}

            for tc in tool_calls:
                tcid, name, raw = _fields(tc)
                try:
                    args = json.loads(raw or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = self._run_tool(name, args, state)
                all_refs.extend(out.get("references", []) or [])
                convo.append({
                    "role": "tool",
                    "tool_call_id": tcid,
                    "name": name,
                    "content": json.dumps(out, default=str)[:6000],
                })

            yield {"type": "tool", "status": "done"}
            if all_refs:
                yield {"type": "references", "references": all_refs}

        # Final answer, streamed from the reasoning model.
        parts: list[str] = []
        stream = self.client.chat.completions.create(
            model=reasoning_model(), messages=convo, stream=True
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                yield {"type": "delta", "text": delta}

        yield {"type": "done", "text": "".join(parts), "references": all_refs, "state": state}
