"""Tests for waver_analyze (pure core) and the waver_analyze tool."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np

from waver_mcp.analyze import analyze
from waver_mcp.server import waver_analyze

NS = Decimal("1e-9")  # 1 tick = 1 ns for the synthetic core tests


def _fmt(t: int) -> str:
    # Small helper mirroring the file's 1ns/tickscale for the core tests.
    return f"{t}ns"


class TestAnalyzeClock:
    def test_clean_clock(self) -> None:
        # 10 ns period, 5 ns high / 5 ns low, 3 full cycles in [0, 30 ns).
        times = np.array([0, 5, 10, 15, 20, 25, 30], dtype=np.int64)
        values = np.array([0, 1, 0, 1, 0, 1, 0], dtype=np.int64)
        out = analyze(times, values, "int", 0, 0, 30, 1, True, False, False, NS, _fmt)
        lines = out.splitlines()
        assert "changes:  7" in lines
        assert "clock:" in lines
        assert "  duty:     50% high, 50% low" in lines
        assert "  high pulse: 5ns" in lines
        assert "  low pulse:  5ns" in lines
        assert "  period:   10ns (median of 2 cycles, min 10ns, max 10ns)" in lines
        assert "  frequency: 100MHz" in lines

    def test_duty_skew(self) -> None:
        # 7 ns high / 3 ns low, period 10 ns.
        times = np.array([0, 3, 10, 13, 20], dtype=np.int64)
        values = np.array([0, 1, 0, 1, 0], dtype=np.int64)
        out = analyze(times, values, "int", 0, 0, 20, 1, True, False, False, NS, _fmt)
        # high = 7+7 = 14 of 20 -> 70%; low = 3+3 -> 30%.
        assert "  duty:     70% high, 30% low" in out
        assert "  high pulse: 7ns" in out
        assert "  low pulse:  3ns" in out
        # rising at 3 and 13 -> one measured period of 10 ns.
        assert "  period:   10ns (median of 1 cycles, min 10ns, max 10ns)" in out

    def test_no_period_single_edge(self) -> None:
        times = np.array([0, 5], dtype=np.int64)
        values = np.array([0, 1], dtype=np.int64)
        out = analyze(times, values, "int", 0, 0, 10, 1, True, False, False, NS, _fmt)
        assert "period:" not in out
        assert "frequency:" not in out


class TestAnalyzeXZ:
    def test_xz_intervals(self) -> None:
        x64 = "x" * 64
        times = np.array([0, 5, 10], dtype=np.int64)
        values = np.array([x64, 0x11, 0x22], dtype=object)
        out = analyze(
            times, values, "str", x64, 0, 20, 64, False, True, False, NS, _fmt
        )
        assert "x/z:      5ns (25% of window, 1 interval)" in out
        assert "defined:  min 0x11, max 0x22" in out

    def test_no_xz_on_strings(self) -> None:
        # Enum-as-string: 'x' inside a name is not X/Z.
        times = np.array([0, 5], dtype=np.int64)
        values = np.array(["tx_done", "rx_idle"], dtype=object)
        out = analyze(
            times, values, "str", "tx_done", 0, 10, 1, False, False, False, NS, _fmt
        )
        assert "x/z:" not in out
        assert '"tx_done"' in out


class TestAnalyzeReal:
    def test_real_stats(self) -> None:
        times = np.array([0, 10, 20], dtype=np.int64)
        values = np.array([1.5, 3.0, 2.0], dtype=np.float64)
        out = analyze(
            times, values, "float", 1.5, 0, 20, None, False, False, True, NS, _fmt
        )
        assert "changes:  3" in out
        assert "real:     min 1.5, max 3, mean 2.167" in out


class TestAnalyzeDegenerate:
    def test_zero_duration(self) -> None:
        out = analyze(
            np.array([], dtype=np.int64),
            np.array([], dtype=np.int64),
            "int",
            1,
            5,
            5,
            1,
            True,
            False,
            False,
            NS,
            _fmt,
        )
        assert "zero duration" in out

    def test_held_entire_window(self) -> None:
        # No changes in the window: entering value held throughout.
        out = analyze(
            np.array([], dtype=np.int64),
            np.array([], dtype=np.int64),
            "int",
            0,
            0,
            10,
            1,
            True,
            False,
            False,
            NS,
            _fmt,
        )
        assert "changes:  0" in out
        assert "clock:" in out
        assert "  duty:     0% high, 100% low" in out


class TestWaverAnalyzeTool:
    def test_clock_fixture(self, all_types_path: Path) -> None:
        out = waver_analyze(str(all_types_path), "clk")
        assert "signal:   tb_wave.clk" in out
        assert "changes:  200" in out
        assert "  duty:     49.75% high, 50.25% low" in out
        assert "  period:   10ns" in out
        assert "  frequency: 100MHz" in out

    def test_enum_fixture(self, all_types_path: Path) -> None:
        out = waver_analyze(str(all_types_path), "state")
        assert '"idle"' in out
        assert "x/z:" not in out

    def test_real_fixture(self, all_types_path: Path) -> None:
        out = waver_analyze(str(all_types_path), "real_sig")
        assert "real:     min 0, max 7.5" in out

    def test_wide_vector_fixture(self, all_types_path: Path) -> None:
        out = waver_analyze(str(all_types_path), "data")
        assert "x/z:" in out
        assert "defined:  min 0x123456789abcdef" in out

    def test_window(self, all_types_path: Path) -> None:
        out = waver_analyze(str(all_types_path), "clk", start="0", end="20ns")
        assert "window:   [0ns, 20ns)" in out

    def test_end_before_start(self, all_types_path: Path) -> None:
        out = waver_analyze(str(all_types_path), "clk", start="20ns", end="10ns")
        assert "window is empty" in out

    def test_unknown_signal(self, all_types_path: Path) -> None:
        assert "no signal named 'nope'" in waver_analyze(str(all_types_path), "nope")

    def test_missing_file(self) -> None:
        assert "not found" in waver_analyze("/nonexistent/x.fst", "clk")

    def test_held_rest_of_file(self, all_types_path: Path) -> None:
        # Start well past the signal's last change.
        out = waver_analyze(str(all_types_path), "state", start="2us")
        assert "no changes after" in out
        assert "held" in out
