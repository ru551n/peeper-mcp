"""Performance-gate tests (opt-in: `pytest -m perf`).

Budgets for the ~400k-change bench fixture, Linux CI runner:
cold open < 100 ms, warm waver_values < 20 ms, warm waver_analyze
< 50 ms. The budgets are 5-10x looser than measured so the gate only
fires on regressions, not machine-to-machine noise. Locally, run
`uv run python tools/bench.py tests/fixtures/bench.fst` for a
per-tool timing table on any platform.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from waver_mcp.server import waver_analyze, waver_open, waver_values
from waver_mcp.store import FileStore

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(
        sys.platform != "linux",
        reason="perf gate runs on Linux CI; tools/bench.py works anywhere",
    ),
]


def _best(fn: object, runs: int = 5) -> float:
    best = float("inf")
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - t0) * 1000)
    return best


def test_cold_open_budget(bench_path: Path) -> None:
    store = FileStore(max_files=1)
    t0 = time.perf_counter()
    store.open(str(bench_path))
    ms = (time.perf_counter() - t0) * 1000
    assert ms < 100, f"cold open took {ms:.1f} ms (budget 100 ms)"


def test_warm_values_budget(bench_path: Path) -> None:
    path = str(bench_path)
    waver_open(path)  # warmup: open file + decode clk once
    ms = _best(lambda: waver_values(path, "clk", start="1ms", end="1.001ms"))
    assert ms < 20, f"warm waver_values took {ms:.1f} ms (budget 20 ms)"


def test_warm_analyze_budget(bench_path: Path) -> None:
    path = str(bench_path)
    waver_open(path)
    ms = _best(lambda: waver_analyze(path, "clk"))
    assert ms < 50, f"warm waver_analyze took {ms:.1f} ms (budget 50 ms)"
