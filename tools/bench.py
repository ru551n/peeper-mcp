#!/usr/bin/env python3
"""Bench the peeper tools on a waveform file.

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

from peeper_mcp.server import (
    peeper_analyze,
    peeper_find,
    peeper_latency,
    peeper_open,
    peeper_plot,
    peeper_values,
)
from peeper_mcp.store import FileStore


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
    bench("peeper_open", lambda: peeper_open(path))
    bench(
        "peeper_values (window)",
        lambda: peeper_values(path, signal, start="1ms", end="1.001ms"),
    )
    bench("peeper_analyze (full)", lambda: peeper_analyze(path, signal))
    bench(
        "peeper_latency (self)",
        lambda: peeper_latency(path, signal, signal, edge="rise"),
    )
    bench("peeper_find", lambda: peeper_find(path, signal, 1))
    bench("peeper_plot (full)", lambda: peeper_plot(path, [signal]))


if __name__ == "__main__":
    main()
