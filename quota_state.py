"""
Quota state reader/writer for claw-proxy.
Tracks usage across Copilot (monthly) and Claude CLI (5-hour rolling window).
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal

CONFIG_DIR = Path.home() / ".config" / "claw-proxy"
STATE_FILE = CONFIG_DIR / "quota-state.json"

BackendName = Literal["copilot", "claude_cli", "local"]

DEFAULT_STATE = {
    "copilot": {
        "monthly_limit": 1000,
        "used_this_month": 0,
        "reset_date": "",
        "last_updated": ""
    },
    "claude_cli": {
        "window_tokens": 200000,
        "used_this_window": 0,
        "window_start": "",
        "window_hours": 5
    },
    "default_backend": "copilot",
    "force_local_patterns": [
        "password", "secret", "vault", "credential",
        "token", "ssh_key", "api_key", "passphrase"
    ]
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    if not STATE_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        state = DEFAULT_STATE.copy()
        state["copilot"] = state["copilot"].copy()
        state["claude_cli"] = state["claude_cli"].copy()

        now = datetime.now(timezone.utc)
        first_of_next = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        state["copilot"]["reset_date"] = first_of_next.strftime("%Y-%m-%d")
        state["copilot"]["last_updated"] = _now_iso()
        state["claude_cli"]["window_start"] = _now_iso()

        save(state)
        return state

    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_FILE)


def _copilot_remaining_pct(state: dict) -> float:
    c = state["copilot"]
    limit = c.get("monthly_limit", 1000)
    used = c.get("used_this_month", 0)
    # Check if reset_date has passed
    try:
        reset = datetime.fromisoformat(c["reset_date"])
        if datetime.now(timezone.utc) >= reset.replace(tzinfo=timezone.utc):
            # Auto-reset
            c["used_this_month"] = 0
            next_reset = (reset.replace(day=1) + timedelta(days=32)).replace(day=1)
            c["reset_date"] = next_reset.strftime("%Y-%m-%d")
            used = 0
    except (KeyError, ValueError):
        pass
    if limit == 0:
        return 0.0
    return max(0.0, (limit - used) / limit)


def _claude_remaining_pct(state: dict) -> float:
    cl = state["claude_cli"]
    try:
        window_start = datetime.fromisoformat(cl["window_start"])
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        window_hours = cl.get("window_hours", 5)
        elapsed = datetime.now(timezone.utc) - window_start
        if elapsed >= timedelta(hours=window_hours):
            # Window expired — reset
            cl["used_this_window"] = 0
            cl["window_start"] = _now_iso()
            save(state)
            return 1.0
    except (KeyError, ValueError):
        return 1.0

    limit = cl.get("window_tokens", 200000)
    used = cl.get("used_this_window", 0)
    if limit == 0:
        return 0.0
    return max(0.0, (limit - used) / limit)


def record_usage(backend: BackendName, tokens: int) -> None:
    state = load()
    if backend == "copilot":
        state["copilot"]["used_this_month"] = state["copilot"].get("used_this_month", 0) + tokens
        state["copilot"]["last_updated"] = _now_iso()
    elif backend == "claude_cli":
        state["claude_cli"]["used_this_window"] = state["claude_cli"].get("used_this_window", 0) + tokens
    save(state)


def get_remaining(backend: BackendName) -> float:
    """Returns fraction remaining (0.0–1.0)."""
    state = load()
    if backend == "copilot":
        return _copilot_remaining_pct(state)
    if backend == "claude_cli":
        return _claude_remaining_pct(state)
    return 1.0  # local is always available


def force_local_patterns() -> list[str]:
    return load().get("force_local_patterns", [])
