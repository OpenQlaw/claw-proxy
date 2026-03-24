"""LM Studio passthrough backend."""
import json
import os
from typing import AsyncGenerator

import httpx

_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234").rstrip("/")
_DEFAULT_MODEL = os.environ.get("LMSTUDIO_MODEL", "local-model")


async def stream(
    messages: list[dict],
    model: str | None = None,
    **kwargs,
) -> AsyncGenerator[str, None]:
    payload = {
        "model": model or _DEFAULT_MODEL,
        "messages": messages,
        "stream": True,
        **{k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens", "top_p")},
    }
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{_BASE_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=180.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    return
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
