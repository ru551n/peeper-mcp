"""Tests for waver_values and waver_value_at."""

from __future__ import annotations

from pathlib import Path

from waver_mcp.server import waver_value_at, waver_values


class TestWaverValues:
    def test_window(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "tb_wave.clk", start="5ns", end="25ns")
        lines = out.splitlines()
        assert "signal:   tb_wave.clk" in lines
        assert "window:   [5ns, 25ns)" in lines
        assert "entering: 1 (value at window start)" in lines
        assert "changes:  4" in lines
        rows = [line.split() for line in lines if line.startswith("  ")]
        assert rows == [
            ["5ns", "1"],
            ["10ns", "0"],
            ["15ns", "1"],
            ["20ns", "0"],
        ]

    def test_open_end(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "clk", start="990ns")
        assert "window:   [990ns, end of file)" in out
        assert "changes:  2" in out

    def test_suffix_match_note(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "CLK", start="0", end="20ns")
        assert "(matched 'CLK')" in out

    def test_hex_for_wide_vectors(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "data", start="0", end="10ns")
        assert "0x123456789abcdef" in out

    def test_xz_and_strings_preserved(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "data", start="0", end="0.5ns")
        assert (
            '"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"' in out
        )
        state = waver_values(str(all_types_path), "state", start="0", end="5ns")
        assert '"idle"' in state

    def test_empty_window_is_explanatory(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "clk", start="1us", end="2us")
        assert "no changes in this window" in out
        assert "held 1 throughout" in out

    def test_truncation_hint(self, bench_path: Path) -> None:
        out = waver_values(str(bench_path), "clk", start="0", max_changes=10)
        assert "changes:  10 of 400001 (truncated)" in out
        assert "narrow the window" in out
        assert "waver_analyze" in out

    def test_end_before_start(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "clk", start="20ns", end="10ns")
        assert "window is empty" in out

    def test_bad_time(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "clk", start="1.5fs")
        assert "not a whole number" in out

    def test_unknown_signal(self, all_types_path: Path) -> None:
        out = waver_values(str(all_types_path), "cntx")
        assert "no signal named 'cntx'" in out

    def test_missing_file(self) -> None:
        assert "not found" in waver_values("/nonexistent/x.fst", "clk")


class TestWaverValueAt:
    def test_single(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "7.5ns", ["tb_wave.clk"])
        lines = out.splitlines()
        assert "time: 7.5ns" in lines
        assert "  tb_wave.clk = 1" in lines

    def test_batch_multiple_signals(self, all_types_path: Path) -> None:
        out = waver_value_at(
            str(all_types_path), "15ns", ["tb_wave.clk", "tb_wave.cnt", "tb_wave.state"]
        )
        assert "  tb_wave.clk = 1" in out
        assert "  tb_wave.cnt = 2" in out
        assert "  tb_wave.state = " in out

    def test_suffix_match_note(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "7.5ns", ["CLK"])
        assert "(matched 'CLK')" in out

    def test_string_value(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "0", ["state"])
        assert '"idle"' in out

    def test_beyond_file_end_flagged(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "2us", ["clk"])
        assert "beyond file end at 995ns" in out

    def test_integer_ticks(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), 7_500_000, ["tb_wave.clk"])
        assert "time: 7.5ns" in out
        assert "  tb_wave.clk = 1" in out

    def test_empty_signals(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "0", [])
        assert "no signals given" in out

    def test_unknown_signal(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "0", ["nope"])
        assert "no signal named 'nope'" in out

    def test_negative_time(self, all_types_path: Path) -> None:
        out = waver_value_at(str(all_types_path), "-1", ["clk"])
        assert "negative time" in out

    def test_missing_file(self) -> None:
        assert "not found" in waver_value_at("/nonexistent/x.fst", "0", ["clk"])
