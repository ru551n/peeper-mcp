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

from waver_mcp.store import FileStore
from waver_mcp.timeutil import format_ticks

#: Default cap on the signal list waver_search returns without a pattern.
MAX_SEARCH_RESULTS = int(os.environ.get("WAVE_MAX_SEARCH_RESULTS", "100"))

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
