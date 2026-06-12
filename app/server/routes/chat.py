"""Chat endpoint — streams agent responses over SSE and traces each turn."""
from __future__ import annotations

import json

import mlflow
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent import BankOfCanadaAgent
from ..tracing import init_tracing, new_session_id, tag_turn
from .user import current_user_email

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

    def gen():
        agent = _get_agent()
        with mlflow.start_span(name="chat_turn") as span:
            span.set_inputs({"message": req.message, "session_id": session_id})
            trace_id = getattr(span, "trace_id", None) or getattr(span, "request_id", None)
            yield _sse({"type": "meta", "session_id": session_id, "trace_id": trace_id})

            final_text, refs, gconv = "", [], req.genie_conversation_id
            try:
                for ev in agent.stream(messages, state):
                    if ev["type"] == "done":
                        final_text = ev["text"]
                        refs = ev.get("references", [])
                        gconv = (ev.get("state") or {}).get("genie_conversation_id")
                        continue
                    yield _sse(ev)
            except Exception as e:  # noqa: BLE001
                yield _sse({"type": "error", "message": str(e)})
                final_text = final_text or f"(error: {e})"

            span.set_outputs({"answer": final_text, "references": refs})
            tag_turn(session_id, user, req.message)
            yield _sse({
                "type": "final",
                "session_id": session_id,
                "trace_id": trace_id,
                "genie_conversation_id": gconv,
            })

    return StreamingResponse(gen(), media_type="text/event-stream")
