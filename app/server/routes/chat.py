"""Chat endpoint — traces each turn, then streams the result over SSE.

The turn is computed inside a clean MLflow span (no network `yield`s inside the
span — doing so corrupts MLflow's thread-local trace context under FastAPI's
StreamingResponse and truncates the stream). The recorded events are then
streamed to the client, and the terminal `final` event carries the complete
answer so the UI never shows a partial response.
"""
from __future__ import annotations

import json
import logging
import traceback

import mlflow
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import time

from ..agent import BankOfCanadaAgent
from ..tracing import flush_traces, init_tracing, new_session_id
from ..turn_log import log_turn, new_turn_id
from .user import current_user_email

logger = logging.getLogger("boc.chat")
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    history: list[dict] = []
    genie_conversation_id: str | None = None


_agent: BankOfCanadaAgent | None = None


def _get_agent() -> BankOfCanadaAgent:
    global _agent
    if _agent is None:
        init_tracing()
        _agent = BankOfCanadaAgent()
    return _agent


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    user = current_user_email(request)
    session_id = req.session_id or new_session_id()
    messages = [*req.history, {"role": "user", "content": req.message}]
    state = {"genie_conversation_id": req.genie_conversation_id}
    agent = _get_agent()

    # Compute the full turn inside the span (synchronously, no yields).
    events: list[dict] = []
    final_text, refs = "", []
    gconv = req.genie_conversation_id
    trace_id = None
    mode = "fast"                 # 'fast' router path or 'deep' analyst path
    tools_used: list[str] = []
    t0 = time.time()
    with mlflow.start_span(name="chat_turn") as span:
        span.set_inputs({"message": req.message, "session_id": session_id})
        trace_id = getattr(span, "trace_id", None) or getattr(span, "request_id", None)
        try:
            for ev in agent.stream(messages, state):
                if ev["type"] == "done":
                    final_text = ev["text"]
                    refs = ev.get("references", [])
                    gconv = (ev.get("state") or {}).get("genie_conversation_id")
                else:
                    if ev.get("type") == "mode" and ev.get("mode") == "deep":
                        mode = "deep"
                    if ev.get("type") == "tool" and ev.get("names"):
                        tools_used.extend(ev["names"])
                    events.append(ev)
        except Exception as e:  # noqa: BLE001
            logger.exception("chat turn failed")
            try:
                span.set_attribute("error", str(e))
                span.set_attribute("error.stacktrace", traceback.format_exc())
                from mlflow.entities import SpanStatusCode

                span.set_status(SpanStatusCode.ERROR, str(e))
            except Exception:  # noqa: BLE001
                pass
            events.append({"type": "error", "message": str(e)})
            final_text = final_text or f"(error: {e})"
        span.set_outputs({"answer": final_text, "references": refs})
        span.set_attribute("mode", mode)
        # Session history lives in the UC turn log (below), not trace tags — but set
        # the native MLflow session/user so spans group by conversation where traces
        # do persist (local dev / notebooks).
        try:
            mlflow.update_current_trace(
                tags={"session_id": session_id, "mode": mode},
                metadata={"mlflow.trace.session": session_id, "mlflow.trace.user": user},
            )
        except Exception:  # noqa: BLE001
            pass

    # Flush the trace synchronously (best-effort MLflow tracing).
    flush_traces()

    # Durable, queryable turn record in Unity Catalog (reliable from the Apps
    # runtime, and powers session history). Best-effort — never breaks the reply.
    log_turn(
        turn_id=new_turn_id(), session_id=session_id, user=user,
        message=req.message, answer=final_text, mode=mode,
        tools_used=tools_used, trace_id=trace_id,
        latency_ms=int((time.time() - t0) * 1000),
    )

    def gen():
        yield _sse({"type": "meta", "session_id": session_id, "trace_id": trace_id})
        for ev in events:
            yield _sse(ev)
        yield _sse({
            "type": "final",
            "session_id": session_id,
            "trace_id": trace_id,
            "genie_conversation_id": gconv,
            "text": final_text,
            "references": refs,
        })

    return StreamingResponse(gen(), media_type="text/event-stream")
