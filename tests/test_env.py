"""Tests for the WAVE_MCP_* env lookup (with the WAVE_* fallback)."""

from __future__ import annotations

import pytest

from waver_mcp.env import env_int


class TestEnvInt:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("WAVE_MCP_MAX_ROWS", raising=False)
        monkeypatch.delenv("WAVE_MAX_ROWS", raising=False)
        assert env_int("MAX_ROWS", "1000") == 1000

    def test_new_name(self, monkeypatch):
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "42")
        assert env_int("MAX_ROWS", "1000") == 42

    def test_deprecated_fallback(self, monkeypatch):
        monkeypatch.delenv("WAVE_MCP_MAX_ROWS", raising=False)
        monkeypatch.setenv("WAVE_MAX_ROWS", "7")
        assert env_int("MAX_ROWS", "1000") == 7

    def test_new_name_wins_over_fallback(self, monkeypatch):
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "42")
        monkeypatch.setenv("WAVE_MAX_ROWS", "7")
        assert env_int("MAX_ROWS", "1000") == 42

    def test_blank_new_name_falls_through_to_fallback(self, monkeypatch):
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "  ")
        monkeypatch.setenv("WAVE_MAX_ROWS", "7")
        assert env_int("MAX_ROWS", "1000") == 7

    def test_invalid_value_raises(self, monkeypatch):
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "abc")
        with pytest.raises(ValueError):
            env_int("MAX_ROWS", "1000")
