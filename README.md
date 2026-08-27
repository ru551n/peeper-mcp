# waver-mcp

MCP server that **measures** FST waveform files: signal values,
period/duty cycle, X/Z durations, A→B latency, event search, and PNG
plots — with human-readable time addressing (`"10ns"`) instead of raw
time-table indices.

Read-only. Built on [pywellen](https://pypi.org/project/pywellen/) (the
Rust [wellen](https://github.com/ekiwi/wellen) reader), so only the
signals you actually query are decoded from the file.

Every tool takes the waveform file path and answers the question an LLM
would actually ask; output is self-describing (file/signal/window header,
truncation notices that say the next step, errors that steer to the right
sibling tool). `waver_plot` returns the PNG as MCP image content, so
vision models see the waveform directly.

## Tools

All `waver_*`, all read-only:

| Tool | Answers |
| --- | --- |
| `waver_open` | What is in this file? (format, timescale, counts, duration) |
| `waver_search` | Which signals are there? |
| `waver_values` | What values did this signal have in this window? |
| `waver_value_at` | What was X at time T? (batch) |
| `waver_analyze` | How fast / how long / how much? (period, duty, X/Z, real stats, value distribution) |
| `waver_latency` | How long from A's edge to B's edge? (min/max/mean/p50/stddev) |
| `waver_find` | When was the signal equal to V? (incl. strings/enums, X/Z buses) |
| `waver_plot` | Show me. (PNG, returned as an image) |

Signal names accept full names or unique dot-separated suffixes (`clk`
matches `tb.dut.clk`). Times are `"10ns"` / `"1.5us"` or integer ticks of
the file's timescale.

## Install & use

```bash
uv tool install waver-mcp        # or: pip install waver-mcp
```

MCP client configuration (stdio):

```json
{
  "mcpServers": {
    "waver": {
      "command": "waver-mcp"
    }
  }
}
```

For running from a checkout, use
`"command": "uv", "args": ["run", "--directory", "/path/to/waver-mcp", "waver-mcp"]`.

Environment (server start): `WAVE_MAX_ROWS` (default change rows, 1000),
`WAVE_MAX_FILES` (open-file LRU, 4), `WAVE_MAX_SEARCH_RESULTS` (100).

## Skill

[`skills/waver-mcp/SKILL.md`](skills/waver-mcp/SKILL.md) is written for
agent skills: tool table framed by the questions each tool answers,
workflows (including the VUnit failure escalation: `vunit_get_test_log`
→ `vunit_get_test_waveform` → `waver_open` → `waver_find` /
`waver_analyze` → `waver_plot`), and an explicit use / don't-use policy
(waver-mcp is read-only — it cannot run or re-run simulations).

## Requirements

- Python >= 3.10 (CPython; no Windows wheels for pywellen, so Windows is
  not supported)
- FST files (e.g. `nvc -r --wave=out.fst`)

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

## License

MIT — see [LICENSE](LICENSE).