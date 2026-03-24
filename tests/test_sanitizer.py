"""Tests for the output sanitizer."""
import pytest
from claw_proxy.sanitizer import scan_chunk, sanitize_string, _REDACTION_MARKER


class TestScanChunk:
    def test_clean_chunk_passes(self):
        is_clean, pattern = scan_chunk("Hello, this is a normal response.")
        assert is_clean is True
        assert pattern is None

    def test_github_pat_blocked(self):
        chunk = "My token is ghp_" + "A" * 36
        is_clean, pattern = scan_chunk(chunk)
        assert is_clean is False
        assert pattern == "github_pat"

    def test_github_app_token_blocked(self):
        chunk = "Token: ghs_" + "B" * 36
        is_clean, pattern = scan_chunk(chunk)
        assert is_clean is False
        assert pattern == "github_app_token"

    def test_anthropic_key_blocked(self):
        chunk = "sk-ant-" + "C" * 93
        is_clean, pattern = scan_chunk(chunk)
        assert is_clean is False
        assert pattern == "anthropic_key"

    def test_openai_key_blocked(self):
        chunk = "sk-" + "D" * 48
        is_clean, pattern = scan_chunk(chunk)
        assert is_clean is False
        assert pattern == "openai_key"

    def test_aws_key_blocked(self):
        chunk = "AKIAIOSFODNN7EXAMPLE"
        is_clean, pattern = scan_chunk(chunk)
        assert is_clean is False
        assert pattern == "aws_access_key"

    def test_kv_secret_blocked(self):
        is_clean, pattern = scan_chunk("password=supersecret123")
        assert is_clean is False
        assert pattern == "kv_secret"

    def test_kv_secret_case_insensitive(self):
        is_clean, pattern = scan_chunk("PASSWORD: hunter2hunter")
        assert is_clean is False
        assert pattern == "kv_secret"

    def test_short_kv_not_blocked(self):
        # Values < 8 chars don't match the kv_secret pattern
        is_clean, _ = scan_chunk("x=abc")
        assert is_clean is True

    def test_empty_chunk_clean(self):
        is_clean, pattern = scan_chunk("")
        assert is_clean is True
        assert pattern is None


class TestSanitizeString:
    def test_clean_string_passes_through(self):
        result = sanitize_string("Normal text here.")
        assert result == "Normal text here."

    def test_dirty_string_returns_marker(self, capsys):
        token = "ghp_" + "X" * 36
        result = sanitize_string(token, backend="test_backend")
        assert result == _REDACTION_MARKER
        captured = capsys.readouterr()
        # Verify the secret value itself is NOT in stderr
        assert token not in captured.err
        assert "test_backend" in captured.err
        assert "github_pat" in captured.err
