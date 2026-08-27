#!/usr/bin/env python3
"""Bench the waver tools on a waveform file.

Usage:
    uv run python tools/bench.py PATH [SIGNAL]

Times a cold open plus one warmed-up call of each measurement tool
(best of 5). Dense input recommended (e.g. tests/fixtures/bench.fst,
~400k changes) to exercise the decimation and vectorized paths.
"""

from __future__ import annotations

import statistics
import sys
import time

from waver_mcp.server import (
    waver_analyze,
    waver_find,
    waver_latency,
    waver_open,
    waver_plot,
    waver_values,
)
from waver_mcp.store import FileStore


def bench(name: str, fn: object, runs: int = 5) -> None:
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    print(
        f"{name:26s} best {min(times):8.1f} ms   "
        f"median {statistics.median(times):8.1f} ms"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    path = sys.argv[1]
    signal = sys.argv[2] if len(sys.argv) > 2 else "clk"
    print(f"file:   {path}")
    print(f"signal: {signal}")

    # Cold open on a fresh store: pywellen load + hierarchy decompress.
    fresh = FileStore(max_files=1)
    bench("open (cold)", lambda: fresh.open(path), runs=1)

    # Warm: the server-level LRU already holds the file + packed signal.
    bench("waver_open", lambda: waver_open(path))
    bench(
        "waver_values (window)",
        lambda: waver_values(path, signal, start="1ms", end="1.001ms"),
    )
    bench("waver_analyze (full)", lambda: waver_analyze(path, signal))
    bench(
        "waver_latency (self)",
        lambda: waver_latency(path, signal, signal, edge="rise"),
    )
    bench("waver_find", lambda: waver_find(path, signal, 1))
    bench("waver_plot (full)", lambda: waver_plot(path, [signal]))


if __name__ == "__main__":
    main()
