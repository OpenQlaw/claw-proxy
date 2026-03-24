"""
claw-proxy main FastAPI app.

Exposes:  POST /v1/chat/completions  (streaming + non-streaming)
          GET  /v1/models
          GET  /health
          GET  /quota
"""
import json
import time
import uuid
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import quota_state as qs
from . import router as rt
from . import sanitizer
from .backends import claude_cli, copilot, lmstudio

app = FastAPI(title="claw-proxy", version="0.1.0")


class ChatMessage(BaseModel):
    role: str
    content: str | list


class ChatRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    claw_preferred_backend: str | None = None


def _messages_to_dicts(messages: list[ChatMessage]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _sse_chunk(content: str, model: str, req_id: str) -> str:
    payload = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse_done(model: str, req_id: str) -> str:
    payload = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    return f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n"


async def _backend_stream(
    backend_name: str,
    messages: list[dict],
    model: str,
    kwargs: dict,
) -> AsyncGenerator[str, None]:
    if backend_name == "copilot":
        gen = copilot.stream(messages, model=model, **kwargs)
    elif backend_name == "claude_cli":
        gen = claude_cli.stream(messages, model=model, **kwargs)
    else:
        gen = lmstudio.stream(messages, model=model, **kwargs)
    async for chunk in gen:
        yield chunk


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/quota")
async def quota_status():
    return {
        "copilot_remaining_pct": round(qs.get_remaining("copilot") * 100, 1),
        "claude_cli_remaining_pct": round(qs.get_remaining("claude_cli") * 100, 1),
        "local_remaining_pct": 100.0,
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "auto", "object": "model", "owned_by": "claw-proxy"},
            {"id": "copilot", "object": "model", "owned_by": "claw-proxy"},
            {"id": "claude_cli", "object": "model", "owned_by": "claw-proxy"},
            {"id": "local", "object": "model", "owned_by": "claw-proxy"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    messages = _messages_to_dicts(req.messages)
    preferred = req.claw_preferred_backend or (
        req.model if req.model in ("copilot", "claude_cli", "local") else None
    )
    backend_name = rt.select_backend(messages, preferred=preferred)

    extra = {}
    if req.temperature is not None:
        extra["temperature"] = req.temperature
    if req.max_tokens is not None:
        extra["max_tokens"] = req.max_tokens
    if req.top_p is not None:
        extra["top_p"] = req.top_p

    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    effective_model = f"{backend_name}-proxy"

    if req.stream:
        async def generate():
            raw_stream = _backend_stream(backend_name, messages, req.model, extra)
            clean_stream = sanitizer.sanitize_stream(raw_stream, backend=backend_name)
            token_count = 0
            async for chunk in clean_stream:
                token_count += len(chunk.split())
                yield _sse_chunk(chunk, effective_model, req_id)
            yield _sse_done(effective_model, req_id)
            try:
                qs.record_usage(backend_name, token_count)
            except Exception:
                pass

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Claw-Backend": backend_name},
        )

    parts = []
    raw_stream = _backend_stream(backend_name, messages, req.model, extra)
    clean_stream = sanitizer.sanitize_stream(raw_stream, backend=backend_name)
    async for chunk in clean_stream:
        parts.append(chunk)
    full_text = "".join(parts)
    token_estimate = len(full_text.split())

    try:
        qs.record_usage(backend_name, token_estimate)
    except Exception:
        pass

    return JSONResponse(
        content={
            "id": req_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": effective_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": token_estimate,
                "total_tokens": token_estimate,
            },
        },
        headers={"X-Claw-Backend": backend_name},
    )


def run():
    """Entry point for `claw-proxy` CLI command."""
    import uvicorn
    uvicorn.run("claw_proxy.main:app", host="127.0.0.1", port=8020, reload=False)
