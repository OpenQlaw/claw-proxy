"""
Quota-aware backend router.
Pure function: given quota state + request metadata → backend name.

Routing priority:
1. If message content matches force_local_patterns → local (security invariant)
2. If estimated complexity == "simple" → local
3. If claude window > 20% remaining and complexity == "complex" → claude_cli
4. If copilot monthly > 10% remaining → copilot
5. Fallback → local (never block, never error)
"""
import re
from typing import Literal

import quota_state as qs

BackendName = Literal["copilot", "claude_cli", "local"]

# Patterns that force routing to local regardless of any other factor.
# Secrets must never leave the LAN.
_ALWAYS_LOCAL_RE = re.compile(
    r"(password|secret|vault|credential|token|ssh.?key|api.?key|passphrase)",
    re.IGNORECASE,
)

# Simple task indicators — not worth spending cloud quota on
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
    """Returns True if content matches any force-local pattern."""
    if _ALWAYS_LOCAL_RE.search(content):
        return True
    for pattern in qs.force_local_patterns():
        if pattern.lower() in content.lower():
            return True
    return False


def _is_simple(content: str) -> bool:
    return bool(_SIMPLE_TASK_RE.search(content))


def select_backend(messages: list[dict], preferred: BackendName | None = None) -> BackendName:
    """
    Choose the best backend for this request.
    preferred can be passed by the caller to express intent; security rules override it.
    """
    content = _content_from_messages(messages)

    # Rule 1: Security override — secrets stay local
    if _force_local(content):
        return "local"

    # Rule 2: Simple tasks go local — preserve quota
    if _is_simple(content):
        return "local"

    # Caller preference (if safe to respect)
    if preferred in ("copilot", "claude_cli"):
        remaining = qs.get_remaining(preferred)
        if remaining > 0.10:
            return preferred

    # Rule 3: Prefer claude_cli for complex tasks when window is healthy
    claude_remaining = qs.get_remaining("claude_cli")
    if claude_remaining > 0.20:
        return "claude_cli"

    # Rule 4: Fall back to copilot if monthly quota is healthy
    copilot_remaining = qs.get_remaining("copilot")
    if copilot_remaining > 0.10:
        return "copilot"

    # Rule 5: Always have a fallback — local never runs out
    return "local"
