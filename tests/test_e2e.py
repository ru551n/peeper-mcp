"""End-to-end tests: a real MCP client against peeper-mcp over stdio.

Spawns the actual server process (python -m peeper_mcp) and walks the
tools over the wire, exactly as an MCP client (Claude, IDE, ...) would.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "peeper_open",
    "peeper_search",
    "peeper_values",
    "peeper_value_at",
    "peeper_analyze",
    "peeper_latency",
    "peeper_find",
    "peeper_plot",
}


def _server() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "peeper_mcp"])


def _text(result: object) -> str:
    assert not result.is_error
    return result.content[0].text


class TestE2E:
    async def test_full_roundtrip(self, all_types_path: Path) -> None:
        file = str(all_types_path)
        async with (
            stdio_client(_server()) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == EXPECTED_TOOLS

            out = _text(await session.call_tool("peeper_open", {"file": file}))
            assert "duration:  995ns" in out
            assert "timescale: 1fs per tick" in out

            out = _text(
                await session.call_tool(
                    "peeper_search", {"file": file, "pattern": "clk"}
                )
            )
            assert "tb_wave.clk" in out

            out = _text(
                await session.call_tool(
                    "peeper_values",
                    {
                        "file": file,
                        "signal": "clk",
                        "start": "0ns",
                        "end": "20ns",
                        "max_changes": 10,
                    },
                )
            )
            assert "5ns   1" in out

            out = _text(
                await session.call_tool(
                    "peeper_value_at",
                    {"file": file, "time": "12ns", "signals": ["clk", "state"]},
                )
            )
            assert "= 0" in out  # clk is low at 12ns (high 5ns -> 10ns)
            assert '= "run"' in out

            out = _text(
                await session.call_tool(
                    "peeper_analyze", {"file": file, "signal": "clk"}
                )
            )
            assert "period:   10ns" in out
            assert "frequency: 100MHz" in out

            out = _text(
                await session.call_tool(
                    "peeper_find",
                    {"file": file, "signal": "state", "value": "run"},
                )
            )
            assert "matches:  33" in out

            out = _text(
                await session.call_tool(
                    "peeper_latency",
                    {
                        "file": file,
                        "a": "clk",
                        "b": "state",
                        "edge": "any",
                        "end": "100ns",
                    },
                )
            )
            assert "pairs:    20" in out

            res = await session.call_tool(
                "peeper_plot", {"file": file, "signals": ["clk", "state"]}
            )
            assert not res.is_error
            assert [c.type for c in res.content] == ["text", "image"]
            assert res.content[1].mime_type == "image/png"

    async def test_error_surfaces_as_text(self) -> None:
        async with (
            stdio_client(_server()) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            out = _text(
                await session.call_tool("peeper_open", {"file": "/nonexistent/x.fst"})
            )
            assert "not found" in out
