"""Tests for the quota-aware router."""
import pytest
from unittest.mock import patch

from claw_proxy.router import select_backend, _force_local, _is_simple


class TestForceLocal:
    def test_password_keyword_forces_local(self):
        assert _force_local("please help me set a password") is True

    def test_secret_keyword_forces_local(self):
        assert _force_local("the secret is abc123") is True

    def test_vault_keyword_forces_local(self):
        assert _force_local("connect to vault at localhost") is True

    def test_credential_keyword_forces_local(self):
        assert _force_local("store the credential") is True

    def test_ssh_key_forces_local(self):
        assert _force_local("generate an ssh key for me") is True

    def test_normal_content_not_forced(self):
        assert _force_local("write a Python function to parse JSON") is False

    def test_case_insensitive(self):
        assert _force_local("What is my PASSWORD") is True


class TestIsSimple:
    def test_summarize_is_simple(self):
        assert _is_simple("summarize this file") is True

    def test_list_is_simple(self):
        assert _is_simple("list all the files") is True

    def test_what_is_is_simple(self):
        assert _is_simple("what is FastAPI?") is True

    def test_complex_task_not_simple(self):
        assert _is_simple("implement a distributed rate limiter with Redis") is False


class TestSelectBackend:
    def _make_messages(self, content: str) -> list[dict]:
        return [{"role": "user", "content": content}]

    def test_secret_content_always_local(self):
        msgs = self._make_messages("what is my vault password")
        with patch("claw_proxy.router.qs.get_remaining", return_value=1.0):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs)
        assert result == "local"

    def test_simple_task_routes_local(self):
        msgs = self._make_messages("summarize this document")
        with patch("claw_proxy.router.qs.get_remaining", return_value=1.0):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs)
        assert result == "local"

    def test_complex_task_routes_to_claude_when_healthy(self):
        msgs = self._make_messages("implement a distributed rate limiter with Redis")
        def mock_remaining(backend):
            return {"copilot": 0.8, "claude_cli": 0.5, "local": 1.0}[backend]
        with patch("claw_proxy.router.qs.get_remaining", side_effect=mock_remaining):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs)
        assert result == "claude_cli"

    def test_falls_back_to_copilot_when_claude_low(self):
        msgs = self._make_messages("implement a distributed rate limiter with Redis")
        def mock_remaining(backend):
            return {"copilot": 0.8, "claude_cli": 0.05, "local": 1.0}[backend]
        with patch("claw_proxy.router.qs.get_remaining", side_effect=mock_remaining):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs)
        assert result == "copilot"

    def test_falls_back_to_local_when_all_quotas_low(self):
        msgs = self._make_messages("implement a distributed rate limiter")
        def mock_remaining(backend):
            return {"copilot": 0.05, "claude_cli": 0.05, "local": 1.0}[backend]
        with patch("claw_proxy.router.qs.get_remaining", side_effect=mock_remaining):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs)
        assert result == "local"

    def test_preferred_copilot_respected_when_healthy(self):
        msgs = self._make_messages("implement something complex")
        def mock_remaining(backend):
            return {"copilot": 0.9, "claude_cli": 0.9, "local": 1.0}[backend]
        with patch("claw_proxy.router.qs.get_remaining", side_effect=mock_remaining):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs, preferred="copilot")
        assert result == "copilot"

    def test_preferred_overridden_by_security(self):
        msgs = self._make_messages("please help me with my password vault secret")
        with patch("claw_proxy.router.qs.get_remaining", return_value=1.0):
            with patch("claw_proxy.router.qs.force_local_patterns", return_value=[]):
                result = select_backend(msgs, preferred="copilot")
        # Security rule overrides, even when copilot is preferred
        assert result == "local"
