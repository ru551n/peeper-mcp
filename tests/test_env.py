"""Tests for the PEEPER_MCP_* env lookup (with WAVE_MCP_*/WAVE_* fallback)."""

from __future__ import annotations

import pytest

from peeper_mcp.env import env_int

_ALL_KEYS = ("PEEPER_MCP_MAX_ROWS", "WAVE_MCP_MAX_ROWS", "WAVE_MAX_ROWS")


class TestEnvInt:
    def test_default(self, monkeypatch):
        for key in _ALL_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert env_int("MAX_ROWS", "1000") == 1000

    def test_new_name(self, monkeypatch):
        monkeypatch.setenv("PEEPER_MCP_MAX_ROWS", "42")
        assert env_int("MAX_ROWS", "1000") == 42

    def test_deprecated_wave_mcp_fallback(self, monkeypatch):
        monkeypatch.delenv("PEEPER_MCP_MAX_ROWS", raising=False)
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "7")
        assert env_int("MAX_ROWS", "1000") == 7

    def test_deprecated_wave_fallback(self, monkeypatch):
        monkeypatch.delenv("PEEPER_MCP_MAX_ROWS", raising=False)
        monkeypatch.delenv("WAVE_MCP_MAX_ROWS", raising=False)
        monkeypatch.setenv("WAVE_MAX_ROWS", "3")
        assert env_int("MAX_ROWS", "1000") == 3

    def test_new_name_wins_over_both_fallbacks(self, monkeypatch):
        monkeypatch.setenv("PEEPER_MCP_MAX_ROWS", "42")
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "7")
        monkeypatch.setenv("WAVE_MAX_ROWS", "3")
        assert env_int("MAX_ROWS", "1000") == 42

    def test_wave_mcp_wins_over_wave(self, monkeypatch):
        monkeypatch.delenv("PEEPER_MCP_MAX_ROWS", raising=False)
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "7")
        monkeypatch.setenv("WAVE_MAX_ROWS", "3")
        assert env_int("MAX_ROWS", "1000") == 7

    def test_blank_new_name_falls_through_to_fallback(self, monkeypatch):
        monkeypatch.setenv("PEEPER_MCP_MAX_ROWS", "  ")
        monkeypatch.setenv("WAVE_MCP_MAX_ROWS", "7")
        assert env_int("MAX_ROWS", "1000") == 7

    def test_invalid_value_raises(self, monkeypatch):
        monkeypatch.setenv("PEEPER_MCP_MAX_ROWS", "abc")
        with pytest.raises(ValueError):
            env_int("MAX_ROWS", "1000")
