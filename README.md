# waver-mcp

MCP server that **measures** FST waveform files: signal values,
period/duty cycle, X/Z durations, A→B latency, event search, and PNG
plots — with human-readable time addressing (`"10ns"`) instead of raw
time-table indices.

Read-only. Built on [pywellen](https://pypi.org/project/pywellen/) (the
Rust [wellen](https://github.com/ekiwi/wellen) reader), so only the
signals you actually query are decoded from the file.

> Status: under construction. Tool set (all `waver_*`):
>
> | Tool | Answers |
> | --- | --- |
> | `waver_open` | What is in this file? (format, timescale, counts, duration) |
> | `waver_search` | Which signals are there? |
> | `waver_values` | What values did this signal have in this window? |
> | `waver_value_at` | What was X at time T? (batch) |
> | `waver_analyze` | How fast / how long / how much? (period, duty, X/Z, real stats) |
> | `waver_latency` | How long from A's edge to B's edge? |
> | `waver_find` | When was the signal equal to V? |
> | `waver_plot` | Show me. (PNG, returned as an image) |

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
uv run pytest -q
```

## License

MIT — see [LICENSE](LICENSE).