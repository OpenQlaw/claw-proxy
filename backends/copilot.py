"""
GitHub Copilot API backend.

Authentication flow:
1. Read OAuth token from VS Code Insiders secret store OR github-copilot CLI config.
2. Exchange for a short-lived session token (30 min TTL) via GitHub internal API.
3. Use session token against the Copilot chat completions endpoint.

The OAuth token is read fresh on each session-token exchange. It is never written to
disk by this module and never appears in log output.
"""
import json
import os
import platform
import time
from pathlib import Path
from typing import AsyncGenerator

import httpx

_COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
_TOKEN_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"

# Cached session token state (in-process only, not persisted)
_SESSION_TOKEN: str | None = None
_SESSION_EXPIRES_AT: float = 0.0


def _read_oauth_token() -> str:
    """
    Read the GitHub OAuth token from the first available source.
    Priority:
      1. GITHUB_OAUTH_TOKEN env var (for testing; must be set explicitly by operator)
      2. github-copilot CLI hosts.json (Linux / WSL path)
      3. VS Code Insiders globalStorage (Windows path via /mnt/c in WSL)
    Never falls through silently — raises if no token found.
    """
    # 1. Explicit env override (operator sets this via a secure mechanism, not hardcoded)
    if token := os.environ.get("GITHUB_OAUTH_TOKEN"):
        return token

    # 2. github-copilot CLI config (works in WSL and native Linux)
    hosts_paths = [
        Path.home() / ".config" / "github-copilot" / "hosts.json",
        Path("/mnt/c/Users") / os.environ.get("WINDOWS_USER", "") / "AppData/Roaming/GitHub Copilot/hosts.json",
    ]
    for p in hosts_paths:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                token = (
                    data.get("github.com", {}).get("oauth_token") or
                    data.get("github.com", {}).get("user", {})  # older format
                )
                if isinstance(token, str) and token:
                    return token
            except (json.JSONDecodeError, KeyError):
                continue

    raise RuntimeError(
        "No GitHub OAuth token found. Set GITHUB_OAUTH_TOKEN env var, "
        "or run 'gh auth login' / 'github-copilot auth login' first."
    )


async def _get_session_token() -> str:
    global _SESSION_TOKEN, _SESSION_EXPIRES_AT

    # Refresh if within 60 seconds of expiry
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
    # expires_at is a Unix timestamp in the response
    _SESSION_EXPIRES_AT = data.get("expires_at", time.time() + 1800)
    return _SESSION_TOKEN


async def stream(
    messages: list[dict],
    model: str = "gpt-4o",
    **kwargs,
) -> AsyncGenerator[str, None]:
    """
    Stream chat completions from Copilot API.
    Yields raw text chunks (not SSE-wrapped; main.py wraps them).
    """
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
