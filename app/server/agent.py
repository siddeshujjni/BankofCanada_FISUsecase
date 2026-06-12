"""Agent core — a fast router that escalates to a deep-investigation subagent.

Two agents share the same three tools but run on different models with
different prompts:

  * Router (foundry-fast): triages every turn. Answers greetings, follow-ups,
    and simple single-fact lookups directly (calling a data tool only when it
    needs new information). For complex, multi-step, analytical, or comparative
    questions it calls `escalate_to_deep_investigation` instead of answering.
  * Deep-investigation subagent (foundry-reasoning): a thorough analyst with its
    own prompt that runs a multi-tool reasoning pass and synthesizes the answer.

Tools:
  * query_bank_of_canada_data  (Genie)
  * detect_market_anomaly      (UC SQL function)
  * search_policy_documents    (Vector Search)

MLflow tracing: tool functions are decorated with @mlflow.trace and OpenAI calls
are auto-traced; the FastAPI route opens the per-turn root span.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from .llm import fast_model, get_client, reasoning_model
from .tools.anomaly_tool import ANOMALY_TOOL_SPEC, detect_anomaly
from .tools.genie_tool import GENIE_TOOL_SPEC, query_genie
from .tools.vector_search_tool import VECTOR_SEARCH_TOOL_SPEC, search_policy

DATA_TOOLS = [GENIE_TOOL_SPEC, ANOMALY_TOOL_SPEC, VECTOR_SEARCH_TOOL_SPEC]

ESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": "escalate_to_deep_investigation",
        "description": (
            "Hand the question to the deep-investigation analyst — a slower, more "
            "thorough reasoning agent. Use this for complex, multi-step, "
            "analytical, comparative, or open-ended questions, anything that needs "
            "combining multiple data sources, or that benefits from careful "
            "step-by-step reasoning. Do NOT answer such questions yourself — "
            "escalate instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why deep investigation is needed."}
            },
            "required": ["reason"],
        },
    },
}

ROUTER_TOOLS = [*DATA_TOOLS, ESCALATE_TOOL]

ROUTER_PROMPT = (
    "You are the router for the Bank of Canada Data Assistant. Triage each turn "
    "and either answer it yourself (fast path) or escalate it.\n\n"
    "ANSWER DIRECTLY, WITHOUT TOOLS, when the message is a greeting, thanks, "
    "chit-chat, a meta question ('what did I just ask?'), a request to rephrase / "
    "summarize / shorten / translate something already in the conversation, or a "
    "follow-up whose answer is already in earlier messages (reuse it; do not "
    "re-fetch unless the user explicitly asks for the latest/updated value).\n\n"
    "CALL ONE DATA TOOL, then answer concisely, for a straightforward single-fact "
    "lookup that needs new data:\n"
    "- query_bank_of_canada_data: policy/overnight rate, bond yields, "
    "CPI/inflation, USD/CAD.\n"
    "- detect_market_anomaly: a quick anomaly check for one market symbol.\n"
    "- search_policy_documents: a simple policy/mandate/framework definition.\n\n"
    "ESCALATE via escalate_to_deep_investigation (do NOT answer yourself) for "
    "complex, multi-step, analytical, or comparative questions, or anything that "
    "needs combining rates + markets + policy or careful reasoning.\n\n"
    "Always read the full conversation history and resolve references like 'that' "
    "or 'the same for X' against it. Be concise and precise with numbers and dates."
)

DEEP_PROMPT = (
    "You are a senior Bank of Canada research analyst handling a question that "
    "needs deep investigation. Work methodically:\n"
    "1. Break the question into the sub-questions you must answer.\n"
    "2. Gather evidence with the tools — you may call several, in sequence, and "
    "combine Bank of Canada data, market anomalies, and policy documents.\n"
    "   - query_bank_of_canada_data: rates, yields, CPI/inflation, USD/CAD.\n"
    "   - detect_market_anomaly: market deviations (FX, commodities, indices).\n"
    "   - search_policy_documents: policy, mandate, frameworks.\n"
    "3. Reason step by step over what you found, note caveats, and synthesize a "
    "clear, well-structured answer.\n"
    "Always cite the references the tools return and be precise with numbers and "
    "dates."
)

_MAX_TOOL_ROUNDS = 5


def _fields(tc) -> tuple[str, str, str]:
    """Normalize a tool call that may be an object or a raw dict."""
    if isinstance(tc, dict):
        fn = tc.get("function", {})
        return tc.get("id", ""), fn.get("name", ""), fn.get("arguments", "{}")
    return tc.id, tc.function.name, tc.function.arguments


def _loads(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


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

    def _tool_rounds(self, model: str, convo: list[dict], tools: list[dict],
                     state: dict, all_refs: list[dict]) -> Iterator[dict]:
        """Run tool-calling rounds on `model`. Yields events; returns the escalation
        reason (str) if the model escalated, else None."""
        for _ in range(_MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=model, messages=convo, tools=tools, tool_choice="auto"
            )
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                return None

            # Escalation short-circuits the round (router only).
            for tc in tool_calls:
                _, name, raw = _fields(tc)
                if name == "escalate_to_deep_investigation":
                    return _loads(raw).get("reason", "Complex question")

            convo.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": i, "type": "function", "function": {"name": n, "arguments": a}}
                    for (i, n, a) in (_fields(tc) for tc in tool_calls)
                ],
            })
            yield {"type": "tool", "names": [_fields(tc)[1] for tc in tool_calls], "status": "running"}

            for tc in tool_calls:
                tcid, name, raw = _fields(tc)
                out = self._run_tool(name, _loads(raw), state)
                all_refs.extend(out.get("references", []) or [])
                convo.append({
                    "role": "tool", "tool_call_id": tcid, "name": name,
                    "content": json.dumps(out, default=str)[:6000],
                })

            yield {"type": "tool", "status": "done"}
            if all_refs:
                yield {"type": "references", "references": all_refs}
        return None

    def _stream_final(self, model: str, convo: list[dict]) -> Iterator[dict]:
        """Stream the final answer from `model`. Yields delta events; returns text."""
        parts: list[str] = []
        stream = self.client.chat.completions.create(model=model, messages=convo, stream=True)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                yield {"type": "delta", "text": delta}
        return "".join(parts)

    def stream(self, messages: list[dict], state: dict | None = None) -> Iterator[dict]:
        """Route the turn (fast) and either answer directly or run the deep subagent."""
        state = state or {}
        all_refs: list[dict] = []

        # --- Router (foundry-fast) ---
        router_convo: list[dict] = [{"role": "system", "content": ROUTER_PROMPT}, *messages]
        reason = yield from self._tool_rounds(fast_model(), router_convo, ROUTER_TOOLS, state, all_refs)

        if reason is None:
            # Fast path: the router answers directly.
            text = yield from self._stream_final(fast_model(), router_convo)
            yield {"type": "done", "text": text, "references": all_refs, "state": state}
            return

        # --- Deep-investigation subagent (foundry-reasoning) ---
        yield {"type": "mode", "mode": "deep", "reason": reason}
        deep_convo: list[dict] = [{"role": "system", "content": DEEP_PROMPT}, *messages]
        yield from self._tool_rounds(reasoning_model(), deep_convo, DATA_TOOLS, state, all_refs)
        text = yield from self._stream_final(reasoning_model(), deep_convo)
        yield {"type": "done", "text": text, "references": all_refs, "state": state}
