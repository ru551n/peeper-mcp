---
name: waver-mcp
description: Measure signal-level behavior in existing waveform files (VCD and FST) through the waver-mcp MCP server (waver_open, waver_search, waver_values, waver_value_at, waver_analyze, waver_latency, waver_find, waver_plot). Use when the user asks what a signal was doing at a time, a clock's period/duty/frequency, when a signal became a value, how long from one edge to another, the X/Z fraction, or "show me the waveform"; read-only — it never runs simulations, and it is the signal-level half of the vunit-mcp failure escalation (vunit_get_test_waveform returns the path).
---

# Waver MCP

## Overview
Use this skill whenever the user asks about **signal-level behavior in an
existing waveform file (VCD or FST)**: what a signal was doing at a time, a clock's
period/duty/frequency, when a signal became a value, how long from one
signal's edge to another's, or "show me the waveform". The `waver-mcp` MCP
server measures VCD and FST files through pywellen: values, statistics, latency,
event search, and PNG plots. It is read-only — it never runs simulations.

Triggers on: what were the signals doing, what's the period / frequency /
duty of, when did X become, how long is the bus in X, how long from A's edge
to B's edge, show me the waveform, plot these signals, what's in this waveform
file, is there a signal named, what was the value at <time>,
how much time in X / Z.

Every tool takes the waveform **file path** as its first argument — there is
no "current file" state. Call `waver_open` first for any file you have not
inspected yet: the timescale and duration it reports frame every window you
pass elsewhere. Signal names accept case-insensitive full names or unique
dot-separated suffixes (`clk` matches `tb.dut.clk`; the result notes the
match). Times are human-readable (`"10ns"`, `"1.5us"`) or integers of the
file's time ticks.

If output looks off or you don't know what a file contains, call
`waver_open` and `waver_search` before guessing.

## Tools

| Tool | What it answers |
| --- | --- |
| `waver_open` | **"What is in this waveform file?"** — format, writer, timescale, duration, scope + signal counts. Call it first for a new file. Header-only, so fast even on large files. |
| `waver_search` | **"Which signals are there?"** — full names with type and tags (`real`, `string`, `64b`); case-insensitive substring `pattern` to narrow. Header-only. |
| `waver_values` | **"What values did this signal have in this window?"** — change list in `[start, end)` plus the value entering the window. Hex for >= 32-bit values; X/Z and enum strings kept as-is. Truncation notices say how to narrow. |
| `waver_value_at` | **"What was X at time T?"** — batch point query (several signals in one call). Past the file end returns the last recorded value and says so. |
| `waver_analyze` | **"How fast / how long / how much?"** — period, frequency, duty, pulse widths for clocks; X/Z time and fraction of window; min/max/mean for reals; top-10 value distribution with held time. The statistics tool — it summarizes instead of listing. |
| `waver_latency` | **"How long from A's edge to B's edge?"** — pairs each edge of `a` with the first `b` edge at/after it; min/max/mean/p50/stddev plus the first and last pairs. `edge="rise"` (binary signals only) or `edge="any"`. |
| `waver_find` | **"When was the signal equal to this value?"** — each interval the value is held, with its duration. Decimal/hex for ints, case-insensitive strings/enums, `"x"`/`"z"` = full-width all-X/all-Z on logic vectors. A no-match lists the values the signal actually took. |
| `waver_plot` | **"Show me."** — PNG of several signals in stacked lanes: binary steps, numeric lines, string/enum/wide-bus value labels, X/Z spans shaded. Returned as an MCP image (vision models see it directly) next to a text summary and a temp-file path. Decimated to ~10000 points/trace. |

All tools are read-only. Windows are `[start, end)`; omit `end` to run to
the end of the file (`waver_plot`) or the signal's last change
(`waver_values`, `waver_analyze`).

## Workflows (user request -> tool calls)

**"What is in this waveform file / what's the timescale?"**
-> `waver_open(file)`. Then `waver_search` for signal names.

**"What was <signal> doing around T?"**
-> `waver_values(file, signal, start, end)` with a window around T. For one
exact time point (or several signals at once): `waver_value_at`.

**"What's the period / frequency / duty cycle of <clock>?"**
-> `waver_analyze(file, signal)`.

**"How much time is <bus> in X/Z?" / "min/max/mean of this real?"**
-> `waver_analyze(file, signal, start?, end?)`.

**"When did <signal> become <value>?" / "when is the FSM in RUN?"**
-> `waver_find(file, signal, value)` — held intervals with durations.

**"How long from the clock edge to the output edge?"**
-> `waver_latency(file, a="clk", b=<out>, edge="rise"|"any", start?, end?)`.

**"Show me the waveform around T"**
-> `waver_plot(file, signals, start, end)` — the PNG *is* the answer; the
text summary gives per-trace change counts and a file path if the user
wants the image on disk.

**"Why did test X fail? (signal level)" — the VUnit escalation**
1. `vunit_get_report` (which test/check) + `vunit_get_test_log` (the
   message, the failing check's sim time when it has one).
2. If the log message already tells the whole story (e.g. a scalar
   check_equal diff), stop — no waveform needed.
3. Otherwise `vunit_get_test_waveform(test_name=...)` — returns the recorded
   waveform's **path** (VCD on GHDL, FST on NVC) and the failing check's sim
   time. If the run recorded no
   waveform, re-running with `waveform_format` is vunit-mcp's job, not
   waver's.
4. `waver_open(path)` -> `waver_values` / `waver_find` / `waver_analyze`
   around the failing check's time -> `waver_plot` for visual
   confirmation.

## Use / don't use
- USE for signal-level questions about an **existing** waveform file
  (VCD or FST): values, timing,
  statistics, "when did X happen", plots — especially as the signal-level
  half of the VUnit failure escalation above.
- DON'T USE when:
  - the question is answerable from the VUnit log/report alone (pass/fail,
    a check diff) — no waveform needed;
  - no waveform file exists. waver-mcp is read-only: it cannot run or
    re-run a simulation. Recording a waveform (or re-running a test) is
    vunit-mcp's job;
  - the user wants to change or re-run something — that is vunit-mcp;
  - "which tests failed" -> `vunit_get_report`;
  - the file is not a readable VCD/FST waveform (or is otherwise
    unreadable): `waver_open` fails clearly — say
    so and stop. Do not loop, and do not try to decode the file by hand.

## Rules of thumb
- `waver_open` first on any new file — timescale + duration frame every
  window you pass afterwards.
- Prefer `waver_analyze` over `waver_values` for statistical questions
  (period, X/Z fraction, distribution): analyze is vectorized and stays
  fast on hundreds of thousands of changes.
- Wide (>= 32-bit) values are hex everywhere; strings and enums are quoted
  and matched case-insensitively.
- X/Z on a logic vector: `waver_find` with `"x"` or `"z"` (full-width
  pattern); `waver_analyze` reports total X/Z time.
- Truncation is a feature: every capped output names the next step
  (narrow the window, raise the limit, use `waver_analyze`). Follow the
  hint instead of re-asking the same tool the same way.
- `waver_plot` is for *seeing*: plot the handful of signals the question
  is about, not fifty.
- Never dump a dense signal's raw change list into the conversation —
  windowed `waver_values` with a small `max_changes`, `waver_analyze`, or
  `waver_plot` instead.

## Configuration (env vars at server start)
- `WAVE_MCP_MAX_ROWS` — default change rows for `waver_values` (default 1000).
- `WAVE_MCP_MAX_FILES` — LRU of open files (default 4).
- `WAVE_MCP_MAX_SEARCH_RESULTS` — default signal-list size for `waver_search`
  (default 100).

The original `WAVE_*` names are a deprecated fallback; `WAVE_MCP_*` wins
when both are set.