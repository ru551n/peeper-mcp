"""Vectorized signal analysis — the core of waver_analyze.

Pure function over a window of (times, values) change data plus the
value entering the window. No I/O, no file state: testable in isolation.

The fully-defined 1-bit path (the common case, and the 400k-change
benchmark case) is pure numpy. Mixed/real/string signals take a
Python-level path; those are rare and small in practice.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from decimal import Decimal

import numpy as np

from waver_mcp.formatting import format_value

#: Bit-pattern strings that carry X/Z (logic signals only).
_XZ_RE = re.compile(r"[01xz_]+", re.IGNORECASE)

_TOP_VALUES = 10


def _is_xz(value: object) -> bool:
    return isinstance(value, str) and _XZ_RE.fullmatch(value) is not None


def _freq(period_ticks: int, ticks_per_second: Decimal) -> str:
    hz = float(1 / (Decimal(period_ticks) * ticks_per_second))
    for unit, div in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if hz >= div:
            return f"{hz / div:.4g}{unit}"
    return f"{hz:.4g}Hz"


def _pct(fraction: float) -> str:
    return f"{fraction * 100:.4g}%"


def _pulse(durs: np.ndarray, fmt_t: Callable[[int], str]) -> str | None:
    durs = durs[durs > 0]
    if len(durs) == 0:
        return None
    med, lo, hi = int(np.median(durs)), int(durs.min()), int(durs.max())
    if lo == hi:
        return fmt_t(lo)
    return f"{fmt_t(med)} (min {fmt_t(lo)}, max {fmt_t(hi)})"


def _prepend_entering(times: np.ndarray, window_start: int) -> bool:
    """Whether the entering value forms its own run before the first change.

    A change exactly at ``window_start`` *is* the entering value, so it
    must not be duplicated as a zero-length run.
    """
    return len(times) == 0 or int(times[0]) > window_start


def _run_starts(
    times: np.ndarray, values: np.ndarray, entering: int, window_start: int
) -> tuple[np.ndarray, np.ndarray]:
    if _prepend_entering(times, window_start):
        run_times = np.concatenate((np.array([window_start], dtype=np.int64), times))
        run_values = np.concatenate((np.array([entering], dtype=np.int64), values))
    else:
        # First change is at window_start; it *is* the entering value.
        run_times = times
        run_values = values
    return run_times, run_values


def rising_edges(
    times: np.ndarray, values: np.ndarray, entering: int, window_start: int
) -> np.ndarray:
    """Times of 0→1 transitions within the window (binary signals)."""
    run_times, run_values = _run_starts(times, values, entering, window_start)
    if len(run_values) < 2:
        return np.array([], dtype=np.int64)
    mask = (run_values[1:] == 1) & (run_values[:-1] == 0)
    return np.asarray(run_times[1:][mask], dtype=np.int64)


def _runs(
    times: np.ndarray,
    values: np.ndarray,
    entering: int,
    window_start: int,
    window_end: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(run_start_times, run_values, run_durations) as int64 arrays."""
    run_times, run_values = _run_starts(times, values, entering, window_start)
    run_len = np.diff(run_times)
    # Tail: no changes -> entering held for the whole window; otherwise the
    # last value is held to the window end.
    tail = (
        np.array([window_end - window_start], dtype=np.int64)
        if len(times) == 0
        else np.array([window_end - int(times[-1])], dtype=np.int64)
    )
    run_len = np.concatenate((run_len, tail))
    return run_times, run_values, run_len


def value_runs(
    times: np.ndarray,
    values: np.ndarray,
    entering: object,
    window_start: int,
    window_end: int,
) -> tuple[list[int], list[object], list[int]]:
    """(run_start_times, run_values, run_durations) for mixed-type values."""
    vals: list[object] = values.tolist()
    if _prepend_entering(times, window_start):
        run_values: list[object] = [entering, *vals]
        run_times: list[int] = [window_start, *(int(t) for t in times)]
    else:
        run_values = list(vals)
        run_times = [int(t) for t in times]
    run_len: list[int] = [
        run_times[i + 1] - run_times[i] for i in range(len(run_times) - 1)
    ]
    run_len.append(window_end - run_times[-1])
    return run_times, run_values, run_len


def _analyze_clock(
    times: np.ndarray,
    values: np.ndarray,
    entering: int,
    window_start: int,
    window_end: int,
    total: int,
    ticks_per_second: Decimal,
    fmt_t: Callable[[int], str],
) -> list[str]:
    run_times, run_values, run_len = _runs(
        times, values, entering, window_start, window_end
    )
    high = run_len[run_values == 1]
    high_total = int(high.sum())
    lines = [
        "clock:",
        f"  duty:     {_pct(high_total / total)} high,"
        f" {_pct(1 - high_total / total)} low",
    ]
    high_pulse = _pulse(high, fmt_t)
    if high_pulse is not None:
        lines.append(f"  high pulse: {high_pulse}")
    low = run_len[run_values == 0]
    low_pulse = _pulse(low, fmt_t)
    if low_pulse is not None:
        lines.append(f"  low pulse:  {low_pulse}")
    # Period is measured on same-polarity edges (rising preferred); an
    # edge-to-edge span would halve it on a symmetric clock.
    if len(run_values) >= 2:
        rising = run_times[1:][(run_values[1:] == 1) & (run_values[:-1] == 0)]
        if len(rising) < 2:
            rising = run_times[1:][(run_values[1:] == 0) & (run_values[:-1] == 1)]
        if len(rising) >= 2:
            periods = np.diff(rising)
            med = int(np.median(periods))
            lines.append(
                f"  period:   {fmt_t(med)} (median of {len(periods)} cycles,"
                f" min {fmt_t(int(periods.min()))}, max {fmt_t(int(periods.max()))})"
            )
            lines.append(f"  frequency: {_freq(med, ticks_per_second)}")
    return lines


def analyze(
    times: np.ndarray,
    values: np.ndarray,
    kind: str,
    entering: object,
    window_start: int,
    window_end: int,
    bitwidth: int | None,
    is_1bit: bool,
    is_bit_vector: bool,
    is_real: bool,
    ticks_per_second: Decimal,
    fmt_t: Callable[[int], str],
) -> str:
    """Analyze one window of a signal; returns the report body.

    The caller has already sliced ``times``/``values`` to
    ``[window_start, window_end)``. ``entering`` is the value held at
    ``window_start`` (it may have changed long before), so the first run
    starts at ``window_start``. ``window_end`` is the effective end:
    the requested end, or the signal's last change time for an open end.
    """
    total = window_end - window_start
    if total <= 0:
        return (
            f"window has zero duration — {format_value(entering, bitwidth)}"
            " held throughout"
        )

    lines: list[str] = [f"changes:  {len(times)}"]

    # Fast path: fully-defined 1-bit logic (numpy).
    if (
        kind == "int"
        and is_1bit
        and entering in (0, 1)
        and bool(np.all((values >= 0) & (values <= 1)))
    ):
        lines.extend(
            _analyze_clock(
                times,
                values,
                int(entering),
                window_start,
                window_end,
                total,
                ticks_per_second,
                fmt_t,
            )
        )
        return "\n".join(lines)

    # General path: wide vectors (incl. X/Z), reals, enums-as-strings,
    # character strings.
    _, run_values, run_len = value_runs(
        times, values, entering, window_start, window_end
    )

    is_logic = (is_1bit or is_bit_vector) and not is_real and kind != "float"
    if is_logic and kind == "str":  # X/Z only possible in pattern strings
        xz_total = sum(run_len[i] for i, v in enumerate(run_values) if _is_xz(v))
        xz_count = sum(1 for v in run_values if _is_xz(v))
        if xz_total > 0:
            unit = " interval" if xz_count == 1 else " intervals"
            lines.append(
                f"x/z:      {fmt_t(xz_total)} ({_pct(xz_total / total)}"
                f" of window, {xz_count}{unit})"
            )

    if kind == "float" or is_real:
        real_vals = [v for v in run_values if isinstance(v, float)]
        if real_vals:
            lines.append(
                "real:     min "
                f"{min(real_vals):g}, max {max(real_vals):g},"
                f" mean {sum(real_vals) / len(real_vals):.4g}"
            )

    ints = [v for v in run_values if isinstance(v, int)]
    if ints:
        lines.append(
            "defined:  min "
            f"{format_value(min(ints), bitwidth)},"
            f" max {format_value(max(ints), bitwidth)}"
        )

    if kind != "float":
        durations: dict[object, int] = {}
        for i, v in enumerate(run_values):
            durations[v] = durations.get(v, 0) + run_len[i]
        top = Counter(run_values).most_common(_TOP_VALUES)
        lines.append(f"values:   top {len(top)} by count (count, held time)")
        for v, n in top:
            lines.append(
                f"  {format_value(v, bitwidth):<24} {n:>5}x  {fmt_t(durations[v])}"
            )

    return "\n".join(lines)
