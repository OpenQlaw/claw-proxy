"""Tests for quota state management."""
import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import claw_proxy.quota_state as qs_module


@pytest.fixture(autouse=True)
def isolated_quota(tmp_path, monkeypatch):
    """Each test gets its own quota state file."""
    state_file = tmp_path / "quota-state.json"
    monkeypatch.setattr(qs_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(qs_module, "STATE_FILE", state_file)
    yield state_file


class TestLoad:
    def test_creates_default_state_when_missing(self, isolated_quota):
        assert not isolated_quota.exists()
        state = qs_module.load()
        assert isolated_quota.exists()
        assert "copilot" in state
        assert "claude_cli" in state

    def test_loads_existing_state(self, isolated_quota):
        data = {"copilot": {"monthly_limit": 500, "used_this_month": 100, "reset_date": "2026-05-01", "last_updated": ""}, "claude_cli": {"window_tokens": 100000, "used_this_window": 0, "window_start": datetime.now(timezone.utc).isoformat(), "window_hours": 5}, "default_backend": "copilot", "force_local_patterns": []}
        isolated_quota.write_text(json.dumps(data))
        state = qs_module.load()
        assert state["copilot"]["monthly_limit"] == 500


class TestGetRemaining:
    def test_local_always_full(self):
        assert qs_module.get_remaining("local") == 1.0

    def test_copilot_full_when_unused(self, isolated_quota):
        remaining = qs_module.get_remaining("copilot")
        assert remaining == 1.0

    def test_copilot_decreases_with_usage(self, isolated_quota):
        qs_module.record_usage("copilot", 500)
        state = qs_module.load()
        limit = state["copilot"]["monthly_limit"]
        remaining = qs_module.get_remaining("copilot")
        assert remaining == pytest.approx((limit - 500) / limit, rel=0.01)

    def test_claude_full_on_fresh_window(self, isolated_quota):
        remaining = qs_module.get_remaining("claude_cli")
        assert remaining == 1.0

    def test_claude_window_resets_after_expiry(self, isolated_quota):
        # Set up a state where the window started > 5 hours ago
        state = qs_module.load()
        old_start = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        state["claude_cli"]["window_start"] = old_start
        state["claude_cli"]["used_this_window"] = 150000
        qs_module.save(state)

        remaining = qs_module.get_remaining("claude_cli")
        assert remaining == 1.0

        # Verify counter was reset in the file
        reloaded = qs_module.load()
        assert reloaded["claude_cli"]["used_this_window"] == 0


class TestRecordUsage:
    def test_record_copilot_increments(self, isolated_quota):
        qs_module.record_usage("copilot", 100)
        qs_module.record_usage("copilot", 50)
        state = qs_module.load()
        assert state["copilot"]["used_this_month"] == 150

    def test_record_claude_increments(self, isolated_quota):
        qs_module.record_usage("claude_cli", 5000)
        state = qs_module.load()
        assert state["claude_cli"]["used_this_window"] == 5000

    def test_record_local_is_noop(self, isolated_quota):
        qs_module.record_usage("local", 999)
        state = qs_module.load()
        # local has no tracker
        assert "used" not in str(state.get("local", ""))
