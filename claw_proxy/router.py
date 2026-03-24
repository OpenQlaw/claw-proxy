"""
Quota-aware backend router.
Pure function: given quota state + request metadata → backend name.
"""
import re
from typing import Literal

from . import quota_state as qs

BackendName = Literal["copilot", "claude_cli", "local"]

_ALWAYS_LOCAL_RE = re.compile(
    r"(password|secret|vault|credential|token|ssh.?key|api.?key|passphrase)",
    re.IGNORECASE,
)

_SIMPLE_TASK_RE = re.compile(
    r"(summarize|list|enumerate|what is|define|explain briefly|rename|format|lint)",
    re.IGNORECASE,
)


def _content_from_messages(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return " ".join(parts)


def _force_local(content: str) -> bool:
    if _ALWAYS_LOCAL_RE.search(content):
        return True
    for pattern in qs.force_local_patterns():
        if pattern.lower() in content.lower():
            return True
    return False


def _is_simple(content: str) -> bool:
    return bool(_SIMPLE_TASK_RE.search(content))


def select_backend(
    messages: list[dict],
    preferred: BackendName | None = None,
) -> BackendName:
    content = _content_from_messages(messages)

    # Security override — secrets stay local, always
    if _force_local(content):
        return "local"

    # Simple tasks don't burn cloud quota
    if _is_simple(content):
        return "local"

    # Respect caller preference if quota is healthy
    if preferred in ("copilot", "claude_cli"):
        if qs.get_remaining(preferred) > 0.10:
            return preferred

    # Prefer claude_cli for complex work when window is healthy
    if qs.get_remaining("claude_cli") > 0.20:
        return "claude_cli"

    # Fall back to copilot
    if qs.get_remaining("copilot") > 0.10:
        return "copilot"

    # Always have a fallback
    return "local"
