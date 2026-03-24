"""
Claude Code CLI subprocess backend.

Drives the `claude` CLI (Anthropic subscription) via stdin/stdout.
The CLI uses its own stored auth (~/.claude/credentials) — no API key
is passed as an argument or environment variable by this module.

Streams tokens as they arrive from the subprocess stdout.
"""
import asyncio
import json
import shutil
from typing import AsyncGenerator


def _find_claude_binary() -> str:
    binary = shutil.which("claude")
    if not binary:
        raise RuntimeError(
            "claude CLI not found in PATH. Install it via: "
            "npm install -g @anthropic-ai/claude-code  "
            "or the Anthropic installer."
        )
    return binary


def _messages_to_prompt(messages: list[dict]) -> str:
    """
    Flatten OpenAI-format messages into a single prompt string.
    The claude CLI's --print mode accepts a prompt on stdin.
    """
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
        if role == "system":
            parts.append(f"<system>\n{content}\n</system>")
        elif role == "assistant":
            parts.append(f"<assistant>\n{content}\n</assistant>")
        else:
            parts.append(content)
    return "\n\n".join(parts)


async def stream(
    messages: list[dict],
    model: str = "claude-sonnet-4-5",
    **kwargs,
) -> AsyncGenerator[str, None]:
    """
    Stream tokens from the claude CLI subprocess.
    Yields raw text chunks.
    """
    binary = _find_claude_binary()
    prompt = _messages_to_prompt(messages)

    # --print: non-interactive, output to stdout
    # --output-format stream-json: one JSON object per line, streaming
    # Model flag if supported by installed CLI version (may vary)
    cmd = [binary, "--print", "--output-format", "stream-json"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Write prompt to stdin and close
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    # Stream stdout line by line
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        line_str = line.decode(errors="replace").strip()
        if not line_str:
            continue
        try:
            obj = json.loads(line_str)
            # stream-json format: {"type": "content_block_delta", "delta": {"text": "..."}}
            if obj.get("type") == "content_block_delta":
                text = obj.get("delta", {}).get("text", "")
                if text:
                    yield text
            # Also handle plain text output mode (older CLI versions)
            elif "text" in obj and isinstance(obj["text"], str):
                yield obj["text"]
        except json.JSONDecodeError:
            # Fallback: treat non-JSON lines as raw text output
            if line_str and not line_str.startswith("{"):
                yield line_str + "\n"

    await proc.wait()
    if proc.returncode not in (0, None):
        stderr_output = await proc.stderr.read()
        # Log error to stderr but do not surface raw process output to client
        import sys
        print(
            f"[claw-proxy claude_cli] process exited with code {proc.returncode}. "
            f"Check claude CLI auth. stderr length={len(stderr_output)}",
            file=sys.stderr,
        )
