"""Agent core — a fast router that escalates to a deep-investigation subagent.

The domain is the Bank of Canada FIS-DDS regulatory-returns analyst: it reasons
over the Z4 "Balance Sheet by Booking Location" return filed monthly by the
banks. Two agents share the same tools but run on different models / prompts:

  * Router (fast model): triages every turn — answers greetings/follow-ups
    directly, calls one tool for a simple lookup, or escalates.
  * Deep-investigation subagent (reasoning model): produces the flagship
    analytical output (e.g. a ~2-page comparison of the Big Six banks'
    liquidity and cash-management strategies), combining the tools.

Tools (all governed Unity Catalog objects or Genie):
  * query_returns_data            (Genie over the mv_balance_sheet metric view)
  * decode_time_series            (UC function — decode RZ4.OAB.V1045)
  * get_series_values             (UC function — value as-of + history)
  * validate_return               (UC function — evaluate the Z4 identities)
  * detect_outliers               (UC function — multi-sigma data-error check)
  * search_reporting_instructions (Vector Search over the Z4 instructions)

MLflow tracing: tool functions are decorated with @mlflow.trace and OpenAI calls
are auto-traced; the FastAPI route opens the per-turn root span.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from .llm import fast_model, get_client, reasoning_model
from .tools.genie_tool import GENIE_TOOL_SPEC, query_genie
from .tools.returns_tools import (
    DECODE_TOOL_SPEC,
    GET_VALUES_TOOL_SPEC,
    OUTLIERS_TOOL_SPEC,
    VALIDATE_TOOL_SPEC,
    decode_time_series,
    detect_outliers,
    get_series_values,
    validate_return,
)
from .tools.vector_search_tool import VECTOR_SEARCH_TOOL_SPEC, search_policy

DATA_TOOLS = [
    GENIE_TOOL_SPEC,
    DECODE_TOOL_SPEC,
    GET_VALUES_TOOL_SPEC,
    VALIDATE_TOOL_SPEC,
    OUTLIERS_TOOL_SPEC,
    VECTOR_SEARCH_TOOL_SPEC,
]

# General reporting/analyst instructions (Chapter 1 of the config file), fed to
# the agent as context — mirroring how the customer feeds a config file to GPT-5.
GENERAL_INSTRUCTIONS = (
    "GENERAL INSTRUCTIONS (from the return's configuration):\n"
    "- Users are particularly interested in loans to households and non-financial "
    "businesses located within Canada.\n"
    "- When users seek possible data errors, focus on recently occurring large "
    "changes with a growth rate several standard deviations from historical norms "
    "(use detect_outliers), and on validation-rule failures (use validate_return).\n"
    "- Common abbreviations: RBC=Royal Bank of Canada, TD=Toronto-Dominion Bank, "
    "BNS=Bank of Nova Scotia, BMO=Bank of Montreal, CIBC=Canadian Imperial Bank of "
    "Commerce, NBC=National Bank of Canada. The FI code segment of a time-series "
    "name maps to an institution (e.g. RZ4.OAB.V1045 -> OAB = RBC).\n"
    "- Regulatory time-series names are cryptic (R<return>.<FI>.<datapoint>, e.g. "
    "RZ4.OAB.V1045). ALWAYS decode a name with decode_time_series before relying "
    "on it, and explain the meaning to the user. All values are in thousands of CAD."
)

ESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": "escalate_to_deep_investigation",
        "description": (
            "Hand the question to the deep-investigation analyst — a slower, more "
            "thorough reasoning agent. Use this for complex, multi-step, "
            "analytical, or comparative questions (e.g. comparing the Big Six banks' "
            "liquidity and cash-management strategies, multi-bank reports, or "
            "anything combining data, validation, and instructions). Do NOT answer "
            "such questions yourself — escalate instead."
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
    "You are the router for the Bank of Canada FIS-DDS Regulatory Returns Analyst, "
    "which reasons over the Z4 'Balance Sheet by Booking Location' return filed "
    "monthly by the banks. Triage each turn and either answer it yourself (fast "
    "path) or escalate it.\n\n"
    + GENERAL_INSTRUCTIONS
    + "\n\nANSWER DIRECTLY, WITHOUT TOOLS, for greetings, thanks, chit-chat, meta "
    "questions, requests to rephrase/summarize something already in the "
    "conversation, or a follow-up whose answer is already in earlier messages.\n\n"
    "CALL ONE TOOL, then answer concisely, for a straightforward single request:\n"
    "- decode_time_series: 'what does RZ4.OAB.V1045 mean?'\n"
    "- get_series_values: one bank's reported value / trend for a datapoint.\n"
    "- query_returns_data: a single metric or simple comparison (total assets, "
    "loans, deposits, ratios) via Genie.\n"
    "- validate_return: 'are there data errors in RBC's latest Z4 filing?'\n"
    "- detect_outliers: unusual recent values for one series.\n"
    "- search_reporting_instructions: 'what is included in A1(a) Cash?'\n\n"
    "ESCALATE via escalate_to_deep_investigation (do NOT answer yourself) for "
    "complex, multi-step, analytical, or comparative questions — especially the "
    "flagship 'describe the liquidity and cash-management strategy of each of the "
    "Big Six banks' style request.\n\n"
    "Always read the full conversation history and resolve references. Be concise "
    "and precise with numbers (thousands of CAD) and dates."
)

DEEP_PROMPT = (
    "You are a senior Bank of Canada FIS-DDS analyst producing a rigorous, "
    "well-structured report from the Z4 regulatory return.\n\n"
    + GENERAL_INSTRUCTIONS
    + "\n\nWork methodically:\n"
    "1. Break the question into sub-questions.\n"
    "2. Gather evidence with the tools — call several, in sequence:\n"
    "   - query_returns_data (Genie): quantitative measures/comparisons over the "
    "governed metric view (total assets, loans, cash, deposits, loan-to-deposit "
    "and liquid-asset ratios) by bank and date.\n"
    "   - decode_time_series / get_series_values: decode and pull specific series.\n"
    "   - validate_return / detect_outliers: data-quality checks.\n"
    "   - search_reporting_instructions: ground definitions in the actual rules.\n"
    "3. Reason over the evidence, compare institutions, note data-quality caveats, "
    "and synthesize a clear report. For the flagship liquidity question, cover each "
    "of the Big Six with its cash/liquid-asset position, deposit mix, and "
    "loan-to-deposit ratio, then contrast their strategies and comment on prevailing "
    "conditions. Target roughly two pages.\n"
    "Always decode cryptic names, cite the metric/series and any instruction "
    "passages you used, and be precise with numbers (thousands of CAD) and dates."
)

_MAX_TOOL_ROUNDS = 6


def _fields(tc) -> tuple[str, str, str]:
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
        if name == "query_returns_data":
            out = query_genie(args["question"], state.get("genie_conversation_id"))
            if out.get("conversation_id"):
                state["genie_conversation_id"] = out["conversation_id"]
            return out
        if name == "decode_time_series":
            return decode_time_series(args["series_name"])
        if name == "get_series_values":
            return get_series_values(args["series_name"], args.get("as_of"),
                                     int(args.get("history_months", 12)))
        if name == "validate_return":
            return validate_return(args["bank_code"], args.get("as_of"),
                                   args.get("return_code", "Z4"))
        if name == "detect_outliers":
            return detect_outliers(args["series_name"], float(args.get("z_threshold", 3.0)))
        if name == "search_reporting_instructions":
            return search_policy(args["query"], int(args.get("k", 5)))
        return {"error": f"unknown tool {name}"}

    def _tool_rounds(self, model: str, convo: list[dict], tools: list[dict],
                     state: dict, all_refs: list[dict]) -> Iterator[dict]:
        for _ in range(_MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=model, messages=convo, tools=tools, tool_choice="auto"
            )
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                return None

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
                    "content": json.dumps(out, default=str)[:8000],
                })

            yield {"type": "tool", "status": "done"}
            if all_refs:
                yield {"type": "references", "references": all_refs}
        return None

    def _stream_final(self, model: str, convo: list[dict]) -> Iterator[dict]:
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

    @staticmethod
    def _should_force_deep(message: str) -> str | None:
        """Heuristic escalation for clearly multi-bank / comparative / report-style
        questions. Small router models sometimes *describe* escalating instead of
        calling the escalate tool, so we force it deterministically here — but only
        for phrasings that genuinely need the multi-step analyst, to avoid sending
        simple single-fact lookups down the slow reasoning path. Anything not caught
        here still gets the normal LLM router triage (which can escalate too)."""
        m = message.lower()
        # Multi-bank scope signals (a comparison/report spanning institutions).
        multi = ("big six" in m or "big 6" in m or "each of the" in m
                 or "all banks" in m or "each bank" in m or "the six" in m)
        # Explicit comparative/analytical intent.
        comparative = any(t in m for t in (
            "compare", "comparison", "versus", " vs ",
            "liquidity and cash", "cash-management strateg", "cash management strateg"))
        if (multi or comparative) and len(message.split()) >= 8:
            return "Multi-bank comparative/analytical question — routed to deep investigation."
        return None

    def stream(self, messages: list[dict], state: dict | None = None) -> Iterator[dict]:
        state = state or {}
        all_refs: list[dict] = []
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

        # --- Router (fast) --- with a deterministic heuristic escalation fallback.
        reason = self._should_force_deep(last_user)
        if reason is None:
            router_convo: list[dict] = [{"role": "system", "content": ROUTER_PROMPT}, *messages]
            reason = yield from self._tool_rounds(fast_model(), router_convo, ROUTER_TOOLS, state, all_refs)
            if reason is None:
                text = yield from self._stream_final(fast_model(), router_convo)
                yield {"type": "done", "text": text, "references": all_refs, "state": state}
                return

        # --- Deep-investigation subagent (reasoning) ---
        yield {"type": "mode", "mode": "deep", "reason": reason}
        deep_convo: list[dict] = [{"role": "system", "content": DEEP_PROMPT}, *messages]
        yield from self._tool_rounds(reasoning_model(), deep_convo, DATA_TOOLS, state, all_refs)
        text = yield from self._stream_final(reasoning_model(), deep_convo)
        yield {"type": "done", "text": text, "references": all_refs, "state": state}
