"""Claude Code CLI subprocess backend."""
import asyncio
import json
import shutil
import sys
from typing import AsyncGenerator


def _find_claude_binary() -> str:
    binary = shutil.which("claude")
    if not binary:
        raise RuntimeError(
            "claude CLI not found in PATH. "
            "Install: npm install -g @anthropic-ai/claude-code"
        )
    return binary


def _messages_to_prompt(messages: list[dict]) -> str:
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
    binary = _find_claude_binary()
    prompt = _messages_to_prompt(messages)
    cmd = [binary, "--print", "--output-format", "stream-json"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        line_str = line.decode(errors="replace").strip()
        if not line_str:
            continue
        try:
            obj = json.loads(line_str)
            if obj.get("type") == "content_block_delta":
                text = obj.get("delta", {}).get("text", "")
                if text:
                    yield text
            elif "text" in obj and isinstance(obj["text"], str):
                yield obj["text"]
        except json.JSONDecodeError:
            if line_str and not line_str.startswith("{"):
                yield line_str + "\n"

    await proc.wait()
    if proc.returncode not in (0, None):
        stderr_output = await proc.stderr.read()
        print(
            f"[claw-proxy claude_cli] process exited {proc.returncode}. "
            f"stderr len={len(stderr_output)}",
            file=sys.stderr,
        )
