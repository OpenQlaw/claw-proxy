# claw-proxy

**Quota-aware OpenAI-compatible gateway.** Dispatches to GitHub Copilot API, Claude Code CLI, or local LM Studio based on live quota state and content security rules.

## What It Does

```
Any OpenAI-compatible client
         ↓  POST /v1/chat/completions
  localhost:8020
         ↓
  reads ~/.config/claw-proxy/quota-state.json
         ↓
  ┌────────────────────────────────────────┐
  │  Route decision:                        │
  │  1. secret content → local (forced)     │
  │  2. simple task    → local              │
  │  3. claude window > 20% → claude_cli    │
  │  4. copilot quota > 10% → copilot       │
  │  5. fallback        → local             │
  └────────────────────────────────────────┘
         ↓  sanitizer strips secret patterns
         ↓  SSE streaming response
```

## Security Properties

- **Secrets never leave LAN.** Any request containing `password`, `secret`, `vault`, `credential`, `token`, `ssh_key`, etc. is force-routed to local LM Studio.
- **No API key in any file.** Copilot backend reads OAuth token from the VS Code secret store or `~/.config/github-copilot/hosts.json`. Claude backend uses the `claude` CLI's stored auth — no key argument.
- **Output sanitizer** blocks chunks matching secret patterns (GitHub PATs, Anthropic keys, OpenAI keys, AWS keys, generic high-entropy strings). Detections are logged to stderr without the matched value.

## Installation (Linux / WSL2)

```bash
cd claw-proxy
chmod +x install.sh
./install.sh
```

Starts a `systemd --user` service on `localhost:8020`.

## Manual Start

```bash
cd claw-proxy
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8020
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/quota` | Current quota remaining % per backend |
| GET | `/v1/models` | Lists available virtual models |
| POST | `/v1/chat/completions` | Main inference endpoint |

## Model Names

Use these as the `model` field to express a preference (subject to security override):

| Model name | Routes to |
|---|---|
| `auto` | Router decides |
| `copilot` | GitHub Copilot API |
| `claude_cli` | Claude Code CLI subprocess |
| `local` | LM Studio (always available, always free) |

## Quota State

Quota is tracked at `~/.config/claw-proxy/quota-state.json`. Edit this file to set your actual monthly Copilot limit. The Claude window auto-resets every 5 hours.

## Extending

- Add a new backend in `backends/` implementing `async def stream(messages, model, **kwargs) -> AsyncGenerator[str, None]`
- Register it in `router.py` and `main.py`
- No other changes needed
