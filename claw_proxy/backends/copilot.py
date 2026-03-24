"""GitHub Copilot API backend."""
import json
import os
import time
from pathlib import Path
from typing import AsyncGenerator

import httpx

_COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
_TOKEN_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"

_SESSION_TOKEN: str | None = None
_SESSION_EXPIRES_AT: float = 0.0


def _read_oauth_token() -> str:
    if token := os.environ.get("GITHUB_OAUTH_TOKEN"):
        return token
    hosts_paths = [
        Path.home() / ".config" / "github-copilot" / "hosts.json",
        Path("/mnt/c/Users") / os.environ.get("WINDOWS_USER", "") / "AppData/Roaming/GitHub Copilot/hosts.json",
    ]
    for p in hosts_paths:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                token = data.get("github.com", {}).get("oauth_token")
                if isinstance(token, str) and token:
                    return token
            except (json.JSONDecodeError, KeyError):
                continue
    raise RuntimeError(
        "No GitHub OAuth token found. Set GITHUB_OAUTH_TOKEN env var "
        "or run 'gh auth login' / 'github-copilot auth login'."
    )


async def _get_session_token() -> str:
    global _SESSION_TOKEN, _SESSION_EXPIRES_AT
    if _SESSION_TOKEN and time.time() < _SESSION_EXPIRES_AT - 60:
        return _SESSION_TOKEN
    oauth_token = _read_oauth_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _TOKEN_EXCHANGE_URL,
            headers={
                "Authorization": f"token {oauth_token}",
                "Accept": "application/json",
                "Editor-Version": "vscode/1.90.0",
                "Copilot-Integration-Id": "vscode-chat",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    _SESSION_TOKEN = data["token"]
    _SESSION_EXPIRES_AT = data.get("expires_at", time.time() + 1800)
    return _SESSION_TOKEN


async def stream(
    messages: list[dict],
    model: str = "gpt-4o",
    **kwargs,
) -> AsyncGenerator[str, None]:
    session_token = await _get_session_token()
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        **{k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens", "top_p")},
    }
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            _COPILOT_CHAT_URL,
            headers={
                "Authorization": f"Bearer {session_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Editor-Version": "vscode/1.90.0",
                "Copilot-Integration-Id": "vscode-chat",
            },
            json=payload,
            timeout=120.0,
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
