"""Tests for the peeper_* MCP tools (called directly, no protocol)."""

from __future__ import annotations

from pathlib import Path

from peeper_mcp.server import mcp, peeper_open, peeper_search


class TestPeeperOpen:
    def test_output(self, all_types_path: Path) -> None:
        out = peeper_open(str(all_types_path))
        assert f"file:      {all_types_path}" in out
        assert "format:    FST" in out
        assert "nvc" in out
        assert "timescale: 1fs per tick" in out
        assert "duration:  995ns" in out
        assert "signals:   7" in out

    def test_bench_duration(self, bench_path: Path) -> None:
        out = peeper_open(str(bench_path))
        assert "duration:  2ms" in out

    def test_missing_file(self) -> None:
        assert "not found" in peeper_open("/nonexistent/x.fst")

    def test_unsupported_or_corrupt_file(self, tmp_path: Path) -> None:
        # Any tool opening a non-VCD/FST/GHW (or corrupt) file must return
        # a clean error string instead of an unhandled RuntimeError.
        bad = tmp_path / "not_a_waveform.fst"
        bad.write_text("this is definitely not a waveform file")
        out = peeper_open(str(bad))
        assert "could not be opened" in out


class TestPeeperSearch:
    def test_lists_all(self, all_types_path: Path) -> None:
        out = peeper_search(str(all_types_path))
        assert "signals: 7" in out
        assert "tb_wave.clk" in out
        real_line = next(line for line in out.splitlines() if "real_sig" in line)
        assert "real" in real_line

    def test_pattern_case_insensitive(self, all_types_path: Path) -> None:
        out = peeper_search(str(all_types_path), pattern="STATE")
        assert "signals: 1" in out
        assert "tb_wave.state" in out

    def test_pattern_no_match(self, all_types_path: Path) -> None:
        out = peeper_search(str(all_types_path), pattern="zzz")
        assert "signals: 0" in out
        assert "no signal name contains 'zzz'" in out

    def test_limit(self, all_types_path: Path) -> None:
        out = peeper_search(str(all_types_path), limit=2)
        assert "signals: 7" in out
        assert "showing 2" in out
        assert sum(line.startswith("  tb_") for line in out.splitlines()) == 2

    def test_missing_file(self) -> None:
        assert "not found" in peeper_search("/nonexistent/x.fst")

    def test_unsupported_or_corrupt_file(self, tmp_path: Path) -> None:
        # Every tool opens the file via the same _open() helper, so this
        # clean error isn't specific to peeper_open.
        bad = tmp_path / "not_a_waveform.vcd"
        bad.write_text("garbage")
        assert "could not be opened" in peeper_search(str(bad))


class TestServer:
    async def test_tools_registered_readonly(self) -> None:
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert {"peeper_open", "peeper_search"} <= names
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True

    def test_instructions_mention_open_first(self) -> None:
        assert mcp.instructions is not None
        assert "peeper_open" in mcp.instructions
