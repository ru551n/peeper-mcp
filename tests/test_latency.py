"""Tests for waver_latency."""

from __future__ import annotations

from pathlib import Path

from waver_mcp.server import waver_latency


class TestWaverLatency:
    def test_any_edges(self, all_types_path: Path) -> None:
        out = waver_latency(str(all_types_path), "clk", "state", edge="any", end="50ns")
        lines = out.splitlines()
        assert "a:        tb_wave.clk (10 edges)" in lines
        assert "b:        tb_wave.state (6 edges)" in lines
        assert "pairs:    10 (each a edge" in out
        assert "min:      0ns" in lines
        assert "max:      5ns" in lines
        assert "p50:      0ns" in lines
        # 9 > 5 pairs -> first/last sections.
        assert "first:" in lines
        assert "last:" in lines

    def test_rise_to_rise_same_signal(self, all_types_path: Path) -> None:
        # A rising edge matches itself on the same signal -> 0 delay.
        out = waver_latency(str(all_types_path), "clk", "clk", edge="rise", end="50ns")
        lines = out.splitlines()
        assert "a:        tb_wave.clk (5 rising edges)" in lines
        assert "pairs:    5 (each a edge" in out
        assert "max:      0ns" in lines
        assert "min:      0ns" in lines

    def test_rise_needs_binary(self, all_types_path: Path) -> None:
        # state is a string signal -> rise is rejected.
        out = waver_latency(str(all_types_path), "state", "clk", edge="rise")
        assert "edge='rise' needs binary" in out
        assert "use edge='any'" in out

    def test_window_label_open_end(self, all_types_path: Path) -> None:
        out = waver_latency(str(all_types_path), "clk", "state", edge="any")
        assert "end of file" in out.splitlines()[3]

    def test_end_before_start(self, all_types_path: Path) -> None:
        out = waver_latency(
            str(all_types_path), "clk", "state", start="20ns", end="10ns"
        )
        assert "window is empty" in out

    def test_no_a_edges_in_window(self, all_types_path: Path) -> None:
        # state's last change is ~995ns; start past it -> no edges.
        out = waver_latency(
            str(all_types_path), "state", "clk", start="2us", edge="any"
        )
        assert "no edges on tb_wave.state" in out

    def test_unknown_signal(self, all_types_path: Path) -> None:
        assert "no signal named 'nope'" in waver_latency(
            str(all_types_path), "nope", "clk"
        )

    def test_missing_file(self) -> None:
        assert "not found" in waver_latency("/nonexistent/x.fst", "clk", "state")

    def test_bench(self, bench_path: Path) -> None:
        out = waver_latency(str(bench_path), "clk", "clk", edge="rise")
        # Same signal, rise->rise: each edge matches itself -> 0.
        assert "max:      0ns" in out
        assert "pairs:" in out
