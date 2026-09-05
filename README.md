# peeper-mcp

MCP server that **measures** waveform files (FST and VCD) — not just reads them.

Where other waveform MCPs hand the LLM raw change tables and leave it to
count cycles and do arithmetic, `peeper-mcp` answers the question directly:
clock period / duty / frequency, X/Z time, A→B latency statistics,
"when was the signal equal to V" (including strings, enums and X/Z buses),
and PNG plots the model can actually see. Times are addressed as `"10ns"`,
not as indices into a time table.

Read-only, headless, stateless: every tool takes the waveform file path,
there is no "current file". Built on
[pywellen](https://pypi.org/project/pywellen/) (the Rust
[wellen](https://github.com/ekiwi/wellen) reader), so only the signals you
actually query are decoded from the file.

## In action

`peeper_analyze` — "what's the frequency of this clock?":

```
file:     /path/to/all_types.fst
signal:   tb_wave.clk  (matched 'clk')
window:   [0ns, 995ns)
changes:  200
clock:
  duty:     49.75% high, 50.25% low
  high pulse: 5ns
  low pulse:  5ns
  period:   10ns (median of 99 cycles, min 10ns, max 10ns)
  frequency: 100MHz
```

`peeper_find` — "when is the FSM in RUN?":

```
file:     /path/to/all_types.fst
signal:   tb_wave.state  (matched 'state')
value:    "run"
matches:  33 (showing 5)
  5ns  held for 10ns
  35ns  held for 10ns
  65ns  held for 10ns
  95ns  held for 10ns
  125ns  held for 10ns
truncated after 5 — narrow with start='...' or raise limit
```

`peeper_latency` — "how long from the clock edge to the state change?":

```
file:     /path/to/all_types.fst
a:        tb_wave.clk (20 edges)
b:        tb_wave.state (11 edges)
window:   [0ns, 100ns)
pairs:    20 (each a edge -> first b edge at/after it)
min:      0ns
max:      5ns
mean:     2.25ns
p50:      0ns
stddev:   2.49ns
```

Output is deliberately self-describing for LLMs: file/signal/window
headers, truncation notices that say the next step, and errors that steer
to the right sibling tool. `peeper_plot` additionally returns the PNG as
MCP image content, so vision clients see the waveform inline.

## Tools

All `peeper_*`, all read-only:

| Tool | Answers |
| --- | --- |
| `peeper_open` | What is in this file? (format, writer, timescale, duration, signal counts). Optional — every tool opens the file itself, but this is a cheap way to learn a new file's metadata upfront. |
| `peeper_search` | Which signals are there? (full names with `real` / `string` / `64b` tags; substring `pattern`) |
| `peeper_values` | What values did this signal have in this window? (change list + entering value) |
| `peeper_value_at` | What was X at time T? (batch: several signals, one call) |
| `peeper_analyze` | How fast / how long / how much? (period, duty, pulse widths, X/Z time, real min/max/mean, top-10 value distribution) |
| `peeper_latency` | How long from A's edge to B's edge? (min/max/mean/p50/stddev + first/last pairs) |
| `peeper_find` | When was the signal equal to V? (held intervals with durations; strings/enums case-insensitive, `"x"`/`"z"` = full-width bus) |
| `peeper_plot` | Show me. (PNG, one lane per signal, X/Z spans shaded, decimated to ~10k points/trace) |

## Install

Zero-install via [uvx](https://docs.astral.sh/uv/guides/tools/) — builds an
isolated environment from git (no PyPI release yet; once published, plain
`uvx peeper-mcp` works):

```bash
uvx --from "git+https://github.com/ru551n/peeper-mcp.git" peeper-mcp
# shorthand (single entry point, so uvx infers the command):
uvx "git+https://github.com/ru551n/peeper-mcp.git"
```

MCP client configuration (stdio; works with any MCP client):

```json
{
  "mcpServers": {
    "peeper": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/ru551n/peeper-mcp.git", "peeper-mcp"]
    }
  }
}
```

To run from a checkout instead:

```json
{
  "mcpServers": {
    "peeper": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/peeper-mcp", "peeper-mcp"]
    }
  }
}
```

Or install the tool persistently instead:

```bash
uv tool install "peeper-mcp @ git+https://github.com/ru551n/peeper-mcp.git"
```

then use `"command": "peeper-mcp"` in the client config.

### Configuration (env vars at server start)

| Var | Meaning | Default |
| --- | --- | --- |
| `PEEPER_MCP_MAX_ROWS` | default `max_changes` for `peeper_values` | 1000 |
| `PEEPER_MCP_MAX_FILES` | LRU of open waveform files | 4 |
| `PEEPER_MCP_MAX_SEARCH_RESULTS` | default signal-list size for `peeper_search` | 100 |

The project's former name (`waver-mcp`) used `WAVE_MCP_*`, and before
that plain `WAVE_*` (e.g. `WAVE_MAX_ROWS`); both are still accepted as
deprecated fallbacks, in that priority order, when `PEEPER_MCP_*` isn't set.

## Times and signal names

- **Times** — `"10ns"`, `"1.5us"`, `"2ms"` (fs / ps / ns / us / µs / ms / s,
  case-insensitive), or a bare integer in the file's time ticks (see the
  timescale reported by `peeper_open`). Windows are `[start, end)`; omit
  `end` to run to the end of the file or the signal's last change.
- **Signal names** — case-insensitive full names, or unique dot-separated
  suffixes: `clk` matches `tb.dut.clk` (and the result says so). Matching
  is component-aligned, so `clk` does *not* match `tb.clk_buf`.
- **Values** — decimal or `0x…` for ints (≥ 32-bit signals are shown in
  hex), case-insensitive strings/enums, `"x"` / `"z"` for an all-X /
  all-Z logic vector.

## Performance

The measurement layer is vectorized (numpy over each signal's packed
change list); signals are decoded on first use and cached per open file.
On the repo's ~400k-change bench fixture (`tools/bench.py`):

| Operation | Time |
| --- | --- |
| Cold open | ~5 ms |
| Warm `peeper_values` (10 ns window) | ~0.5 ms |
| Warm `peeper_analyze` (whole file) | ~4 ms |
| `peeper_plot` (whole file, 1 trace) | ~140 ms |

CI enforces budgets on Linux (cold open < 100 ms, warm values < 20 ms,
warm analyze < 50 ms) via the opt-in perf-gate tests
(`pytest -m perf`).

Open files are cached in an LRU of size `PEEPER_MCP_MAX_FILES` (default 4).
Once more than that many distinct files have been opened in a session,
the least-recently-used one is evicted and closed; reopening it later
re-triggers a full cold open (parse + decode), i.e. the ~5 ms (or
longer, on bigger files) latency spike above. Raise `PEEPER_MCP_MAX_FILES`
if your workflow keeps more files open concurrently than that.

`peeper_plot` writes each PNG to a fresh file in the OS temp dir; the
previous call's PNG is removed on the next `peeper_plot` call
(best-effort), so at most one temp file lingers per process. Any file
left behind by an unclean shutdown is the OS temp dir's responsibility
to eventually clean up.

## Agent skill

[`skills/peeper-mcp/SKILL.md`](skills/peeper-mcp/SKILL.md) teaches an agent
when and how to use the server: the question-framed tool table, workflows
(including the VUnit failure escalation — `vunit_get_test_log` →
`vunit_get_test_waveform` → `peeper_open` → `peeper_find` /
`peeper_analyze` → `peeper_plot`), and an explicit use / don't-use policy
(peeper-mcp is read-only: it cannot run or re-run simulations).

## Requirements

- Python >= 3.10. `pywellen` is built from source on install (needs a
  Rust toolchain and the MSVC linker on Windows); alternatively, a
  prebuilt Windows wheel for `pywellen` (py3.12/3.13/3.14) is published
  as a [GitHub Release](https://github.com/ru551n/peeper-mcp/releases)
  by this repo, so Windows users can install it without a Rust
  toolchain by pointing pip at that wheel directly
- FST and VCD waveform files (FST e.g. from `nvc -r --wave=out.fst`, VCD e.g.
  from `ghdl -r --stop-on-failure --wave=wave.vcd` or recorded by
  [vunit-mcp](https://github.com/ru551n/vunit-mcp) with `waveform_format`;
  the reader auto-detects the format)

## Development

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pytest -q                 # perf-gate tests are opt-in
uv run pytest -q -m perf         # perf budgets on the ~400k-change fixture
uv run python tools/bench.py tests/fixtures/bench.fst clk
```

Test fixtures (FST files + VHDL sources) live in `tests/fixtures/`.

## License

MIT — see [LICENSE](LICENSE).