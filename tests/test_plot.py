"""Tests for waver_plot."""

from __future__ import annotations

import base64
from pathlib import Path

from mcp.types import ImageContent, TextContent

from waver_mcp.server import mcp, waver_plot

PNG_MAGIC = b"\x89PNG"


def _text(res: object) -> str:
    text, _image = res
    assert isinstance(text, TextContent)
    return text.text


def _image(res: object) -> bytes:
    _text, image = res
    assert isinstance(image, ImageContent)
    return base64.b64decode(image.data)


class TestWaverPlot:
    def test_returns_text_and_image(self, all_types_path: Path) -> None:
        res = waver_plot(str(all_types_path), ["clk", "state", "real_sig"])
        assert isinstance(res, tuple) and len(res) == 2
        assert _image(res).startswith(PNG_MAGIC)
        lines = _text(res).splitlines()
        assert lines[0] == f"file:     {all_types_path}"
        assert "window:   [0ns, 995ns)" in lines
        assert "traces:   3" in lines
        for name in ("tb_wave.clk", "tb_wave.state", "tb_wave.real_sig"):
            assert any(line.startswith(f"  {name}") for line in lines)

    def test_png_file_written(self, all_types_path: Path) -> None:
        res = waver_plot(str(all_types_path), ["clk"])
        line = next(
            line for line in _text(res).splitlines() if line.startswith("image:")
        )
        path = Path(line.split("image:")[1].strip())
        assert path.exists()
        assert path.stat().st_size > 2000
        assert path.read_bytes().startswith(PNG_MAGIC)

    def test_lane_kinds(self, all_types_path: Path) -> None:
        text = _text(waver_plot(str(all_types_path), ["clk", "state", "real_sig"]))
        clk_line = next(line for line in text.splitlines() if "tb_wave.clk" in line)
        assert "binary (199 changes)" in clk_line
        state_line = next(line for line in text.splitlines() if "tb_wave.state" in line)
        assert "text (" in state_line
        assert "x/z interval" in text
        real_line = next(line for line in text.splitlines() if "real_sig" in line)
        assert "numeric (99 changes)" in real_line

    def test_decimated(self, bench_path: Path) -> None:
        text = _text(waver_plot(str(bench_path), ["clk"]))
        assert "window:   [0ns, 2ms)" in text
        dec = next(line for line in text.splitlines() if "decimated" in line)
        pts = int(dec.split("to ")[1].split(" points")[0])
        assert pts <= 10_001

    def test_window(self, all_types_path: Path) -> None:
        text = _text(waver_plot(str(all_types_path), ["clk"], start="10ns"))
        assert "window:   [10ns, 995ns)" in text

    def test_xz_shaded(self, all_types_path: Path) -> None:
        text = _text(waver_plot(str(all_types_path), ["data"]))
        data_line = next(line for line in text.splitlines() if "tb_wave.data" in line)
        # data has 14 changes -> 14 held runs; it opens with an all-X span.
        assert "text (14 runs, 1 x/z interval)" in data_line

    def test_duplicate_signals_deduped(self, all_types_path: Path) -> None:
        text = _text(waver_plot(str(all_types_path), ["clk", "tb_wave.clk"]))
        assert "traces:   1" in text
        assert text.count("tb_wave.clk") == 1

    def test_missing_file(self) -> None:
        assert "not found" in waver_plot("/nonexistent/x.fst", ["clk"])

    def test_unknown_signal(self, all_types_path: Path) -> None:
        assert "no signal named 'nope'" in waver_plot(str(all_types_path), ["nope"])

    def test_no_signals(self, all_types_path: Path) -> None:
        assert "no signals given" in waver_plot(str(all_types_path), [])

    def test_empty_window(self, all_types_path: Path) -> None:
        out = waver_plot(str(all_types_path), ["clk"], start="50ns", end="10ns")
        assert "window is empty" in out

    def test_start_beyond_file_end(self, all_types_path: Path) -> None:
        out = waver_plot(str(all_types_path), ["clk"], start="2us")
        assert "beyond the end of the file" in out

    async def test_unstructured_output(self, all_types_path: Path) -> None:
        # -> Any annotation: no outputSchema, text + image content only.
        tools = await mcp.list_tools()
        plot = next(t for t in tools if t.name == "waver_plot")
        assert plot.outputSchema is None
        res = await mcp.call_tool(
            "waver_plot", {"file": str(all_types_path), "signals": ["clk"]}
        )
        types = [c.type for c in res]
        assert types == ["text", "image"]
