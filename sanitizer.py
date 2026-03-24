"""
Output sanitizer — runs on every streamed chunk before yielding to client.
Blocks responses containing secret patterns.
Logs detections to stderr only. Never logs the matched secret value.
"""
import re
import sys
from typing import Generator

# Patterns that must never appear in outbound chunks.
# Order: most specific first to minimize false positives.
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("github_pat",        re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_app_token",  re.compile(r"ghs_[A-Za-z0-9]{36}")),
    ("github_oauth",      re.compile(r"gho_[A-Za-z0-9]{36}")),
    ("anthropic_key",     re.compile(r"sk-ant-[A-Za-z0-9\-_]{93}")),
    ("openai_key",        re.compile(r"sk-[A-Za-z0-9]{48}")),
    ("aws_access_key",    re.compile(r"AKIA[A-Z0-9]{16}")),
    ("generic_b64_secret",re.compile(r'"[A-Za-z0-9+/=]{40,}"')),
    # Key=value patterns for common secret names
    ("kv_secret",         re.compile(
        r'(?i)(password|secret|api.?key|token|credential|passphrase)\s*[=:]\s*["\']?[^\s"\']{8,}',
    )),
]

_REDACTION_MARKER = "[REDACTED — secret pattern detected by claw-proxy sanitizer]"


def _scan_chunk(chunk: str) -> tuple[bool, str | None]:
    """
    Returns (is_clean, pattern_name_if_dirty).
    Does NOT return the matched secret value.
    """
    for pattern_name, pattern in _SECRET_PATTERNS:
        if pattern.search(chunk):
            return False, pattern_name
    return True, None


def sanitize_stream(
    chunks: Generator[str, None, None],
    backend: str = "unknown",
) -> Generator[str, None, None]:
    """
    Wraps a chunk generator. Yields clean chunks, replaces dirty ones.
    """
    for chunk in chunks:
        is_clean, pattern_name = _scan_chunk(chunk)
        if is_clean:
            yield chunk
        else:
            print(
                f"[claw-proxy sanitizer] BLOCKED chunk from backend={backend}, "
                f"pattern={pattern_name}. Chunk NOT logged.",
                file=sys.stderr,
            )
            yield _REDACTION_MARKER


def sanitize_string(text: str, backend: str = "unknown") -> str:
    """Synchronous version for non-streaming responses."""
    is_clean, pattern_name = _scan_chunk(text)
    if is_clean:
        return text
    print(
        f"[claw-proxy sanitizer] BLOCKED response from backend={backend}, "
        f"pattern={pattern_name}. Response NOT logged.",
        file=sys.stderr,
    )
    return _REDACTION_MARKER
