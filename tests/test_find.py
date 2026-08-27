"""Tests for waver_find."""

from __future__ import annotations

from pathlib import Path

from waver_mcp.server import waver_find


class TestWaverFind:
    def test_enum_case_insensitive(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "state", "RUN")
        lines = out.splitlines()
        assert 'value:    "RUN"' in lines
        assert "matches:  " in out
        assert "held for 10ns" in out
        # first run interval starts at 5ns
        first_match = next(line for line in lines if "held for" in line)
        assert "5ns" in first_match

    def test_enum_exact(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "state", "done")
        assert "matches:  " in out
        assert "held for 10ns" in out

    def test_int_value(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "clk", 1)
        assert "matches:  " in out
        assert "held for 5ns" in out

    def test_int_as_string(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "clk", "1")
        assert "held for 5ns" in out

    def test_hex_value(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "data", "0x123456789abcdef")
        assert "matches:  7" in out

    def test_xz_expansion(self, all_types_path: Path) -> None:
        # 'x' on a 64-bit vector -> all-X pattern.
        out = waver_find(str(all_types_path), "data", "x")
        lines = out.splitlines()
        assert "matches:  1" in lines
        assert "held for 5ns" in out

    def test_no_match_lists_actual_values(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "state", "NOPE")
        assert "matches:  0" in out
        assert '"idle"' in out  # hint of actual values

    def test_start_skips_earlier(self, all_types_path: Path) -> None:
        before = waver_find(str(all_types_path), "state", "run")
        after = waver_find(str(all_types_path), "state", "run", start="30ns")
        n_before = int(before.split("matches:")[1].split()[0].rstrip(")"))
        n_after = int(after.split("matches:")[1].split()[0].rstrip(")"))
        assert n_after < n_before

    def test_held_rest_of_file(self, all_types_path: Path) -> None:
        # data's last value is 0x1234... after its final change at 965ns;
        # start between that and the file end (995ns).
        out = waver_find(
            str(all_types_path), "data", "0x123456789abcdef", start="970ns"
        )
        lines = out.splitlines()
        assert "matches:  1 —" in out
        assert "held from 970ns" in out
        assert "held for 25ns" in out
        assert "end of file" in out
        assert any(line.startswith("matches:  1") for line in lines)

    def test_start_beyond_file_end(self, all_types_path: Path) -> None:
        # File ends at 995ns; 2us is past it.
        out = waver_find(str(all_types_path), "data", "0x123456789abcdef", start="2us")
        assert "matches:  0" in out
        assert "beyond the end of the file" in out

    def test_truncation(self, all_types_path: Path) -> None:
        out = waver_find(str(all_types_path), "clk", 1, limit=3)
        assert "(showing 3)" in out
        assert "truncated after 3" in out

    def test_unknown_signal(self, all_types_path: Path) -> None:
        assert "no signal named 'nope'" in waver_find(str(all_types_path), "nope", 1)

    def test_missing_file(self) -> None:
        assert "not found" in waver_find("/nonexistent/x.fst", "clk", 1)
