"""FastMCP server exposing the waver_* FST measurement tools.

The server is stateless from the caller's point of view: every tool takes
the waveform file path, and results never depend on a "current file".
The only server state is a small LRU of open files (see
:mod:`waver_mcp.store`) so repeated calls on the same file stay fast.
"""

from __future__ import annotations

import base64
import os
import re
import tempfile
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent, ToolAnnotations

from waver_mcp.analyze import analyze, is_xz, rising_edges, value_runs
from waver_mcp.formatting import format_value
from waver_mcp.store import (
    AmbiguousSignal,
    FileStore,
    Resolution,
    SignalInfo,
    SignalNotFound,
    WaveformFile,
)
from waver_mcp.timeutil import (
    TimeValueError,
    display_unit,
    format_ticks,
    parse_time,
)

#: Default cap on the signal list waver_search returns without a pattern.
MAX_SEARCH_RESULTS = int(os.environ.get("WAVE_MAX_SEARCH_RESULTS", "100"))

#: Default cap on changes waver_values returns.
MAX_ROWS = int(os.environ.get("WAVE_MAX_ROWS", "1000"))

#: Max plotted points per trace; denser change lists are decimated.
_MAX_PTS = 10_000

#: Max value labels drawn on a text lane (longest runs first).
_MAX_TEXT_LABELS = 24

#: Max run boundaries drawn on a text lane before striding.
_MAX_TEXT_RUNS_DRAWN = 2000

#: Per-lane geometry for waver_plot.
_LANE_HEIGHT = 1.0
_LANE_GAP = 0.4

_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

_STORE = FileStore()

mcp = FastMCP(
    "waver_mcp",
    instructions=(
        "Measure FST waveform files: signal values, period/duty, latency, "
        "event search, and PNG plots. Every tool takes the waveform file "
        "path; call waver_open first to learn a file's timescale and "
        "duration — they frame every window you pass elsewhere. Signal "
        "names accept case-insensitive full names or unique suffixes "
        "('clk' matches tb.dut.clk). Times are human-readable '10ns' / "
        "'1.5us' or integer file ticks."
    ),
)


def _open(file: str) -> str | None:
    """Return a self-describing error, or None if *file* opened."""
    try:
        _STORE.open(file)
    except FileNotFoundError as exc:
        return str(exc)
    return None


@mcp.tool(annotations=_RO)
def waver_open(file: str) -> str:
    """What is in this waveform file?

    Answers "what's in this FST? how long did the simulation run? what's
    the timescale?". Call it first for any file you have not inspected yet;
    the timescale and duration it reports frame every window you pass to
    the other waver_* tools. Use waver_search to list the individual
    signals.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    tps = f.ticks_per_second
    lines = [
        f"file:      {f.path}",
        f"format:    {f.wf.file_format}",
        f"writer:    {f.wf.version} ({f.wf.date})",
        f"timescale: {format_ticks(1, tps)} per tick",
        f"duration:  {format_ticks(f.duration(), tps)} (last change across "
        "sampled signals)",
        f"scopes:    {', '.join(f.scope_names)}",
        f"signals:   {len(f.signals)} (waver_search lists them)",
    ]
    return "\n".join(lines)


@mcp.tool(annotations=_RO)
def waver_search(file: str, pattern: str = "", limit: int = MAX_SEARCH_RESULTS) -> str:
    """Which signals are in this waveform file?

    Answers "what signals does this FST contain? is there a signal named
    X?". Pass a case-insensitive substring of `pattern` to narrow the list
    on large designs. The names shown are what you pass to waver_values,
    waver_analyze, waver_latency, waver_find and waver_plot — full names
    or unique suffixes. Header-only: nothing is decoded, so this is fast
    even on big files.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    pat = pattern.lower()
    matches = [s for s in f.signals if not pat or pat in s.full_name.lower()]
    total = len(matches)
    shown = matches[: max(limit, 1)]
    header = f"signals: {total}"
    if total > len(shown):
        header += f" (showing {len(shown)}; refine with pattern)"
    lines = [f"file: {f.path}", header]
    for s in shown:
        tags = []
        if s.is_real:
            tags.append("real")
        if s.is_string:
            tags.append("string")
        if s.bitwidth is not None and s.bitwidth > 1:
            tags.append(f"{s.bitwidth}b")
        tag = f"  [{', '.join(tags)}]" if tags else ""
        lines.append(f"  {s.full_name}  {s.var_type}{tag}")
    if total == 0:
        lines.append(f"no signal name contains {pattern!r}")
    return "\n".join(lines)


@mcp.tool(annotations=_RO)
def waver_values(
    file: str,
    signal: str,
    start: str | int = "0",
    end: str | int | None = None,
    max_changes: int = MAX_ROWS,
) -> str:
    """What values did this signal have in this time window?

    Answers "what did <signal> do between A and B?". Times are
    human-readable ('10ns', '1.5us') or integer file ticks; the window
    is [start, end) — omit end to run to the signal's last change.
    Wide (>= 32 bit) values are shown in hex; X/Z samples and enum/
    string values are kept as-is. For statistics instead of a change
    list, use waver_analyze; for one time point, waver_value_at.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    try:
        res = f.resolve(signal)
        start_t = _ticks(f, start)
        end_t = None if end is None else _ticks(f, end)
        if end_t is not None and end_t <= start_t:
            return (
                f"window is empty: end ({_tm(f, end_t)}) "
                f"must be after start ({_tm(f, start_t)})"
            )
        info = res.signal
        times, values = f.window(info.full_name, start_t, end_t)
    except (AmbiguousSignal, SignalNotFound, TimeValueError) as exc:
        return str(exc)

    if end_t is not None:
        window_text = f"[{_tm(f, start_t)}, {_tm(f, end_t)})"
    else:
        window_text = f"[{_tm(f, start_t)}, end of file)"
    entering_value = _fmt_value(info, f.value_at(info.full_name, start_t))
    header = [
        f"file:     {f.path}",
        f"signal:   {info.full_name}" + (f"  (matched {signal!r})" if res.note else ""),
        f"window:   {window_text}",
        f"entering: {entering_value} (value at window start)",
    ]
    if len(times) == 0:
        held = f.value_at(info.full_name, start_t)
        header.append(
            f"no changes in this window — {info.full_name} held "
            f"{_fmt_value(info, held)} throughout"
        )
        return "\n".join(header)

    shown = min(len(times), max(max_changes, 1))
    header.append(
        f"changes:  {shown}"
        + (f" of {len(times)} (truncated)" if shown < len(times) else "")
    )
    col = max(len(_tm(f, int(t))) for t in times[:shown])
    lines = header + [
        f"  {_tm(f, int(t)).ljust(col)}  {_fmt_value(info, v)}"
        for t, v in zip(times[:shown], values[:shown], strict=True)
    ]
    if shown < len(times):
        lines.append(
            f"truncated after {shown} changes — narrow the window "
            "(start='...' / end='...') or raise max_changes; "
            "for statistics use waver_analyze"
        )
    return "\n".join(lines)


@mcp.tool(annotations=_RO)
def waver_value_at(file: str, time: str | int, signals: list[str]) -> str:
    """What were these signals at this exact time?

    Answers "what was <signal> at 10ns?" (batch: pass several signals in
    one call). Returns the value held at that instant (the last change
    at or before the time). Time is human-readable ('10ns') or integer
    file ticks. If the time is past the end of the file, the last
    recorded value is returned and flagged. For a whole window of
    changes, use waver_values.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    if not signals:
        return "no signals given — pass at least one signal name"
    try:
        t = _ticks(f, time)
        duration = f.duration()
        rows = []
        for name in signals:
            res = f.resolve(name)
            val = f.value_at(res.signal.full_name, t)
            suffix = (
                f"  (beyond file end at {_tm(f, duration)} — last recorded value)"
                if t > duration
                else ""
            )
            note = f"  (matched {name!r})" if res.note else ""
            value_text = _fmt_value(res.signal, val)
            rows.append(f"  {res.signal.full_name}{note} = {value_text}{suffix}")
    except (AmbiguousSignal, SignalNotFound, TimeValueError) as exc:
        return str(exc)
    return "\n".join([f"file: {f.path}", f"time: {_tm(f, t)}", *rows])


@mcp.tool(annotations=_RO)
def waver_analyze(
    file: str, signal: str, start: str | int = "0", end: str | int | None = None
) -> str:
    """How fast, how long, how much is this signal?

    Answers "what's the period / frequency / duty cycle of <signal>?",
    "how much time is <signal> in X/Z?", "what's the min/max/mean of this
    real?", "which values does <signal> take and how often?". This is the
    statistics tool: it summarizes a window instead of listing changes.
    Times are human-readable ('10ns') or integer ticks; the window is
    [start, end) — omit end to run to the signal's last change. For a raw
    change list use waver_values; for edge-to-edge timing between two
    signals use waver_latency.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    try:
        res = f.resolve(signal)
        info = res.signal
        start_t = _ticks(f, start)
        end_t = None if end is None else _ticks(f, end)
        if end_t is not None and end_t <= start_t:
            return (
                f"window is empty: end ({_tm(f, end_t)}) "
                f"must be after start ({_tm(f, start_t)})"
            )
        packed = f.packed(info.full_name)
        times, values = f.window(info.full_name, start_t, end_t)
        # Effective end: explicit end, or the signal's last change.
        win_end = (
            end_t if end_t is not None else int(times[-1]) if len(times) else start_t
        )
        # Degenerate: with an open end and nothing (or only the value at
        # start_t) to measure, say so plainly.
        if end_t is None and win_end <= start_t:
            held = f.value_at(info.full_name, start_t)
            return (
                f"file:     {f.path}\n"
                f"signal:   {info.full_name}\n"
                f"window:   [{_tm(f, start_t)}, end of file)\n"
                f"no changes after {_tm(f, start_t)} — {info.full_name}"
                f" held {_fmt_value(info, held)} for the rest of the file"
            )
        entering = f.value_at(info.full_name, start_t)
        body = analyze(
            times,
            values,
            packed.kind,
            entering,
            start_t,
            win_end,
            info.bitwidth,
            info.is_1bit,
            info.is_bit_vector,
            info.is_real,
            f.ticks_per_second,
            lambda t: _tm(f, t),
        )
    except (AmbiguousSignal, SignalNotFound, TimeValueError) as exc:
        return str(exc)
    header = [
        f"file:     {f.path}",
        f"signal:   {info.full_name}" + (f"  (matched {signal!r})" if res.note else ""),
        f"window:   [{_tm(f, start_t)}, {_tm(f, win_end)})",
    ]
    return "\n".join([*header, body])


@mcp.tool(annotations=_RO)
def waver_latency(
    file: str,
    a: str,
    b: str,
    edge: Literal["rise", "any"] = "rise",
    start: str | int = "0",
    end: str | int | None = None,
) -> str:
    """How long from A's edge to B's edge?

    Answers "what's the propagation delay from <a> to <b>?", "how long
    after <a>'s rising edge does <b> rise?". For every edge of A in
    [start, end) it finds the first edge of B at or after that moment and
    reports min/max/mean/p50/stddev over all such pairs, plus the first
    and last pairs. edge='rise' needs both signals to be binary (0/1);
    use edge='any' for any change. Times are human-readable or ticks.
    For one signal's own timing use waver_analyze.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    try:
        ra, rb = f.resolve(a), f.resolve(b)
        ia, ib = ra.signal, rb.signal
        start_t = _ticks(f, start)
        end_t = None if end is None else _ticks(f, end)
        if end_t is not None and end_t <= start_t:
            return (
                f"window is empty: end ({_tm(f, end_t)}) "
                f"must be after start ({_tm(f, start_t)})"
            )
        end_label = _tm(f, end_t) if end_t is not None else "end of file"
        pa, pb = f.packed(ia.full_name), f.packed(ib.full_name)
        ta, va = f.window(ia.full_name, start_t, end_t)
        tb, vb = f.window(ib.full_name, start_t, end_t)
        ea_name = "rising edges"
        if edge == "rise":
            for name, kind, values, full in (
                (a, pa.kind, va, ia.full_name),
                (b, pb.kind, vb, ib.full_name),
            ):
                if kind != "int" or not bool(
                    (len(values) == 0) or np.all((values >= 0) & (values <= 1))
                ):
                    return (
                        f"edge='rise' needs binary (0/1) signals; {full}"
                        f" (from {name!r}) is not — use edge='any'"
                    )
            ea = rising_edges(ta, va, int(f.value_at(ia.full_name, start_t)), start_t)
            eb = rising_edges(tb, vb, int(f.value_at(ib.full_name, start_t)), start_t)
        else:
            ea, eb, ea_name = ta, tb, "edges"
        if len(ea) == 0:
            return (
                f"file:     {f.path}\n"
                f"window:   [{_tm(f, start_t)}, {end_label})\n"
                f"no {ea_name} on {ia.full_name} in this window"
            )
        if len(eb) == 0:
            return (
                f"file:     {f.path}\n"
                f"window:   [{_tm(f, start_t)}, {end_label})\n"
                f"no {ea_name} on {ib.full_name} in this window"
            )
        idx = np.searchsorted(eb, ea, side="left")
        matched = idx < len(eb)
        if not matched.any():
            return (
                f"file:     {f.path}\n"
                f"window:   [{_tm(f, start_t)}, {end_label})\n"
                f"no matched pairs — {ib.full_name} has no {ea_name}"
                f" at or after {ia.full_name}'s edges in this window"
            )
        ae, be = ea[matched], eb[idx[matched]]
        deltas = be - ae
        unmatched = int((~matched).sum())

        def fmt(t: np.number | float) -> str:
            return _tm(f, _round_sig3(round(float(t))))

        lines = [
            f"file:     {f.path}",
            f"a:        {ia.full_name} ({len(ea)} {ea_name})",
            f"b:        {ib.full_name} ({len(eb)} {ea_name})",
            f"window:   [{_tm(f, start_t)}, {end_label})",
            f"pairs:    {len(deltas)} (each a edge -> first b edge at/after it)"
            + (f"; {unmatched} a edges unmatched (b quiet)" if unmatched else ""),
            f"min:      {fmt(deltas.min())}",
            f"max:      {fmt(deltas.max())}",
            f"mean:     {fmt(deltas.mean())}",
            f"p50:      {fmt(np.percentile(deltas, 50))}",
            f"stddev:   {fmt(deltas.std())}",
        ]
        if len(deltas) > 5:
            lines.append("first:")
            lines += [
                f"  a@{_tm(f, int(x))} -> b@{_tm(f, int(y))} ({fmt(d)})"
                for x, y, d in zip(ae[:3], be[:3], deltas[:3], strict=True)
            ]
            lines.append("last:")
            lines += [
                f"  a@{_tm(f, int(x))} -> b@{_tm(f, int(y))} ({fmt(d)})"
                for x, y, d in zip(ae[-2:], be[-2:], deltas[-2:], strict=True)
            ]
        else:
            lines.append("pairs:")
            lines += [
                f"  a@{_tm(f, int(x))} -> b@{_tm(f, int(y))} ({fmt(d)})"
                for x, y, d in zip(ae, be, deltas, strict=True)
            ]
    except (AmbiguousSignal, SignalNotFound, TimeValueError) as exc:
        return str(exc)
    return "\n".join(lines)


@mcp.tool(annotations=_RO)
def waver_find(
    file: str, signal: str, value: str | int, start: str | int = "0", limit: int = 100
) -> str:
    """When was the signal equal to this value?

    Answers "when did <signal> become <value>?", "when is the bus in X?",
    "when does the FSM enter <state>?". Int signals take decimal or hex
    ('0x1f'); string/enum signals match case-insensitively; on logic
    vectors 'x' or 'z' matches an all-X/all-Z bus. Returns each interval
    the value is held, with its duration, from `start` onwards. For a
    single time point use waver_value_at; for statistics use
    waver_analyze.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    try:
        res = f.resolve(signal)
        info = res.signal
        start_t = _ticks(f, start)
        target = _parse_target(value, info)
        target_text = _fmt_value(info, target)
        duration = f.duration()
        if start_t >= duration:
            return (
                f"file:     {f.path}\n"
                f"signal:   {info.full_name}\n"
                f"value:    {target_text}\n"
                f"matches:  0 — start ({_tm(f, start_t)}) is beyond the"
                f" end of the file (at {_tm(f, duration)})"
            )
        packed = f.packed(info.full_name)
        i = int(np.searchsorted(packed.times, start_t, side="left"))
        times_win = packed.times[i:]
        entering = f.value_at(info.full_name, start_t)
        if len(times_win) == 0:
            held_text = _fmt_value(info, entering)
            if _value_eq(entering, target):
                return (
                    f"file:     {f.path}\n"
                    f"signal:   {info.full_name}\n"
                    f"value:    {target_text}\n"
                    f"matches:  1 — held from {_tm(f, start_t)} to end of"
                    f" file (held for {_tm(f, duration - start_t)})"
                )
            return (
                f"file:     {f.path}\n"
                f"signal:   {info.full_name}\n"
                f"value:    {target_text}\n"
                f"matches:  0 — the signal held {held_text} throughout"
                f" (no changes after {_tm(f, start_t)})"
            )
        run_times, run_values, run_len = value_runs(
            times_win, packed.values[i:], entering, start_t, duration
        )
        matches = [
            (rt, rl)
            for rt, rv, rl in zip(run_times, run_values, run_len, strict=True)
            if rl > 0 and _value_eq(rv, target)
        ]
    except (AmbiguousSignal, SignalNotFound, TimeValueError) as exc:
        return str(exc)
    header = [
        f"file:     {f.path}",
        f"signal:   {info.full_name}" + (f"  (matched {signal!r})" if res.note else ""),
        f"value:    {target_text}",
    ]
    if not matches:
        distinct: dict[object, int] = {}
        for rv in run_values:
            distinct[rv] = distinct.get(rv, 0) + 1
        top = sorted(distinct.items(), key=lambda kv: -kv[1])[:5]
        hint = ", ".join(f"{_fmt_value(info, v)} ({n}x)" for v, n in top)
        return "\n".join(
            [
                *header,
                "matches:  0",
                f"the signal took these values after {_tm(f, start_t)}: {hint}",
            ]
        )
    shown = min(len(matches), max(limit, 1))
    lines = [
        *header,
        f"matches:  {len(matches)}"
        + (f" (showing {shown})" if shown < len(matches) else ""),
    ]
    lines += [f"  {_tm(f, rt)}  held for {_tm(f, rl)}" for rt, rl in matches[:shown]]
    if shown < len(matches):
        lines.append(
            f"truncated after {shown} — narrow with start='...' or raise limit"
        )
    return "\n".join(lines)


def _decimate_idx(n: int) -> np.ndarray:
    """Indices into an n-point series, keeping ~_MAX_PTS points.

    Always includes the last point so the trace reaches the window end.
    """
    if n <= _MAX_PTS:
        return np.arange(n)
    stride = int(np.ceil(n / _MAX_PTS))
    idx = np.arange(0, n, stride)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return idx


def _draw_plot_lane(
    ax: Axes,
    f: WaveformFile,
    info: SignalInfo,
    lane_base: float,
    start_t: int,
    win_end: int,
    scale: float,
    color: tuple[float, ...],
) -> str:
    """Draw one signal's window in its lane; return a one-line summary."""
    packed = f.packed(info.full_name)
    times, values = f.window(info.full_name, start_t, win_end)
    entering = f.value_at(info.full_name, start_t)
    n_changes = len(times)
    kind = packed.kind
    wide_int = kind == "int" and (info.bitwidth or 0) > 32
    if kind == "str" or wide_int:
        # Text lane: held values as labels, X/Z spans shaded. String/enum
        # signals (kind "str", possibly mixing ints with X/Z strings) and
        # wide int buses (> 32 bit, which don't plot meaningfully as
        # numbers) both render here.
        run_times, run_values, run_len = value_runs(
            times, values, entering, start_t, win_end
        )
        runs = [
            (rt, rv, rl)
            for rt, rv, rl in zip(run_times, run_values, run_len, strict=True)
            if rl > 0
        ]
        stride = max(1, (len(runs) - 1) // _MAX_TEXT_RUNS_DRAWN)
        if len(runs) > 1:
            x_lines = (
                np.asarray([rt for rt, _rv, _rl in runs[1::stride]], dtype=np.float64)
                * scale
            )
            ax.vlines(
                x_lines,
                lane_base,
                lane_base + _LANE_HEIGHT,
                color="0.8",
                lw=0.5,
            )
        xz_runs = [(rt, rv, rl) for rt, rv, rl in runs if is_xz(rv)]
        for rt, _rv, rl in xz_runs:
            ax.add_patch(
                Rectangle(
                    (rt * scale, lane_base),
                    rl * scale,
                    _LANE_HEIGHT,
                    facecolor="0.9",
                    edgecolor="none",
                    alpha=0.9,
                    lw=0,
                )
            )
        labels = [(rt, rv, rl) for rt, rv, rl in runs if not is_xz(rv)]
        shown = (
            labels
            if len(labels) <= _MAX_TEXT_LABELS
            else sorted(labels, key=lambda r: -r[2])[:_MAX_TEXT_LABELS]
        )
        for rt, rv, rl in shown:
            ax.annotate(
                _fmt_value(info, rv),
                xy=((rt + rl / 2) * scale, lane_base + 0.5),
                ha="center",
                va="center",
                fontsize=7,
                color="0.1",
            )
        note = ""
        if len(shown) < len(labels):
            note = f", showing {len(shown)} of {len(labels)} labels"
        plural = "" if len(xz_runs) == 1 else "s"
        return f"text ({len(runs)} runs, {len(xz_runs)} x/z interval{plural}{note})"
    x = np.concatenate((np.array([start_t], dtype=np.int64), times))
    if kind == "int" and (info.is_1bit or (info.bitwidth or 0) <= 1):
        y = np.concatenate((np.array([int(entering)], dtype=np.int64), values))
        idx = _decimate_idx(len(x))
        ax.step(
            x[idx] * scale,
            lane_base + y[idx],
            where="post",
            color=color,
            lw=1,
        )
    else:
        allv = np.concatenate((np.array([entering], dtype=values.dtype), values))
        vmin, vmax = float(allv.min()), float(allv.max())
        idx = _decimate_idx(len(x))
        if vmax == vmin:
            yplot = np.full(len(idx), lane_base + 0.5)
        else:
            yplot = lane_base + (allv[idx] - vmin) / (vmax - vmin)
        ax.plot(x[idx] * scale, yplot, color=color, lw=0.8)
    dec = f", decimated to {len(idx)} points" if len(idx) < n_changes else ""
    lane = (
        "binary"
        if kind == "int" and (info.is_1bit or (info.bitwidth or 0) <= 1)
        else "numeric"
    )
    return f"{lane} ({n_changes} changes{dec})"


@mcp.tool(annotations=_RO)
def waver_plot(
    file: str,
    signals: list[str],
    start: str | int = "0",
    end: str | int | None = None,
) -> Any:
    """Show me the waveforms: a PNG plot of these signals in this window.

    Answers "show me <signal(s)> around time A" / "what does the bus look
    like here?". One lane per signal: binary signals step between 0 and 1,
    small numeric signals draw as a line, and wide buses plus string/enum
    signals show their held values as text labels with X/Z spans shaded.
    Times are human-readable ('10ns', '1.5us') or integer file ticks; the
    window is [start, end) — omit end to run to the end of the file.
    Dense signals are decimated to ~10000 points so large files stay fast.
    Returns the plot as an image plus a text summary; the PNG is also
    written to a temp file whose path is in the summary. For statistics
    use waver_analyze; for exact values use waver_values.
    """
    error = _open(file)
    if error is not None:
        return error
    f = _STORE.open(file)
    if not signals:
        return "no signals given — pass at least one signal name"
    fig: Figure | None = None
    try:
        start_t = _ticks(f, start)
        end_t = None if end is None else _ticks(f, end)
        duration = f.duration()
        if end_t is not None and end_t <= start_t:
            return (
                f"window is empty: end ({_tm(f, end_t)}) "
                f"must be after start ({_tm(f, start_t)})"
            )
        if end_t is None and start_t >= duration:
            return (
                f"window is empty: start ({_tm(f, start_t)}) is beyond the"
                f" end of the file (at {_tm(f, duration)})"
            )
        win_end = end_t if end_t is not None else duration
        resolved: list[Resolution] = []
        seen: set[str] = set()
        for name in signals:
            res = f.resolve(name)
            if res.signal.full_name not in seen:
                seen.add(res.signal.full_name)
                resolved.append(res)
        unit, per_unit = display_unit(duration, f.ticks_per_second)
        scale = float(f.ticks_per_second / per_unit)
        n = len(resolved)
        fig, ax = plt.subplots(figsize=(10, 0.9 * n + 1.4))
        ax.set_xlim(start_t * scale, win_end * scale)
        summaries: list[str] = []
        for i, res in enumerate(resolved):
            color = plt.cm.tab10(i % 10)
            summaries.append(
                _draw_plot_lane(
                    ax,
                    f,
                    res.signal,
                    i * (_LANE_HEIGHT + _LANE_GAP),
                    start_t,
                    win_end,
                    scale,
                    color,
                )
            )
        ax.set_yticks([i * (_LANE_HEIGHT + _LANE_GAP) + 0.5 for i in range(n)])
        ax.set_yticklabels([res.signal.leaf for res in resolved])
        ax.set_ylim(-0.2, (n - 1) * (_LANE_HEIGHT + _LANE_GAP) + _LANE_HEIGHT + 0.2)
        ax.set_xlabel(f"time ({unit})")
        ax.set_title(
            f"{os.path.basename(f.path)}   [{_tm(f, start_t)}, {_tm(f, win_end)})"
        )
        ax.grid(axis="x", linewidth=0.3, alpha=0.4)
        fd, png_path = tempfile.mkstemp(prefix="waver-plot-", suffix=".png")
        os.close(fd)
        fig.savefig(png_path, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        fig = None
        with open(png_path, "rb") as fh:
            png_bytes = fh.read()
        lines = [
            f"file:     {f.path}",
            f"window:   [{_tm(f, start_t)}, {_tm(f, win_end)})",
            f"image:    {png_path}",
            f"traces:   {n}",
        ]
        for res, summary in zip(resolved, summaries, strict=True):
            note = f"  (matched {res.signal.leaf!r})" if res.note else ""
            lines.append(f"  {res.signal.full_name}{note}  {summary}")
        lines.append(
            "stats: waver_analyze; exact values: waver_values; narrow the"
            " window to read dense labels"
        )
        return (
            TextContent(type="text", text="\n".join(lines)),
            ImageContent(
                type="image",
                data=base64.b64encode(png_bytes).decode(),
                mimeType="image/png",
            ),
        )
    except (AmbiguousSignal, SignalNotFound, TimeValueError) as exc:
        if fig is not None:
            plt.close(fig)
        return str(exc)


def _fmt_value(info: SignalInfo, value: object) -> str:
    return format_value(value, info.bitwidth)


_INT_RE = re.compile(r"-?\d+")


def _parse_target(value: str | int, info: SignalInfo) -> int | str:
    """Parse a waver_find target: int stays int, hex/decimal strings
    become ints, everything else stays a string. 'x'/'z' on a logic
    vector expands to the full-width all-X/all-Z pattern."""
    if isinstance(value, int):
        return value
    s = value.strip()
    if s.lower().startswith("0x"):
        try:
            return int(s, 16)
        except ValueError:
            return s
    if _INT_RE.fullmatch(s):
        return int(s)
    if s.lower() in ("x", "z") and info.is_bit_vector and info.bitwidth:
        return s * info.bitwidth
    return s


def _value_eq(actual: object, target: object) -> bool:
    if isinstance(target, int):
        return isinstance(actual, int) and actual == target
    return isinstance(actual, str) and actual.lower() == str(target).lower()


def _ticks(f: WaveformFile, value: str | int) -> int:
    return parse_time(value, f.ticks_per_second)


def _tm(f: WaveformFile, ticks: int) -> str:
    return format_ticks(ticks, f.ticks_per_second)


def _round_sig3(ticks: int) -> int:
    """Round ticks to 3 significant figures for statistics display.

    A min/mean/stddev of deltas can carry as many digits as the file's
    timescale; rounding keeps statistics readable. Exact tick values
    (timestamps, individual intervals) are left untouched.
    """
    if ticks <= 0:
        return 0
    magnitude: int = 10 ** max(len(str(ticks)) - 3, 0)  # mypy 2 types ** as Any
    # Integer round-half-up to the nearest multiple of `magnitude`.
    return ((ticks + magnitude // 2) // magnitude) * magnitude


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
