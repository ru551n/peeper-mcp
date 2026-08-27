"""FastMCP server exposing the waver_* FST measurement tools.

The server is stateless from the caller's point of view: every tool takes
the waveform file path, and results never depend on a "current file".
The only server state is a small LRU of open files (see
:mod:`waver_mcp.store`) so repeated calls on the same file stay fast.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from waver_mcp.analyze import analyze
from waver_mcp.formatting import format_value
from waver_mcp.store import (
    AmbiguousSignal,
    FileStore,
    SignalInfo,
    SignalNotFound,
    WaveformFile,
)
from waver_mcp.timeutil import TimeValueError, format_ticks, parse_time

#: Default cap on the signal list waver_search returns without a pattern.
MAX_SEARCH_RESULTS = int(os.environ.get("WAVE_MAX_SEARCH_RESULTS", "100"))

#: Default cap on changes waver_values returns.
MAX_ROWS = int(os.environ.get("WAVE_MAX_ROWS", "1000"))

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


def _fmt_value(info: SignalInfo, value: object) -> str:
    return format_value(value, info.bitwidth)


def _ticks(f: WaveformFile, value: str | int) -> int:
    return parse_time(value, f.ticks_per_second)


def _tm(f: WaveformFile, ticks: int) -> str:
    return format_ticks(ticks, f.ticks_per_second)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
