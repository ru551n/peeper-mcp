"""Tests for waver_mcp.store (file store, resolution, packed caches)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from waver_mcp.store import (
    AmbiguousSignal,
    FileStore,
    SignalInfo,
    SignalNotFound,
    WaveformFile,
    WaveformOpenError,
    resolve_signal,
)

CLK = "tb_wave.clk"


def make_info(full_name: str) -> SignalInfo:
    return SignalInfo(
        full_name=full_name,
        leaf=full_name.rsplit(".", 1)[-1],
        var_type="StdLogic",
        bitwidth=1,
        is_real=False,
        is_string=False,
        is_1bit=True,
        is_bit_vector=False,
        components=tuple(full_name.lower().split(".")),
    )


@pytest.fixture
def store() -> FileStore:
    return FileStore()


@pytest.fixture
def all_types(store: FileStore, all_types_path: Path) -> WaveformFile:
    return store.open(str(all_types_path))


class TestOpen:
    def test_timescale_and_format(self, all_types: WaveformFile) -> None:
        assert all_types.ticks_per_second == Decimal("1e-15")
        assert all_types.path.endswith("all_types.fst")
        assert all_types.wf.file_format == "FST"

    def test_signals(self, all_types: WaveformFile) -> None:
        assert [s.full_name for s in all_types.signals] == [
            "tb_wave.clk",
            "tb_wave.cnt",
            "tb_wave.state",
            "tb_wave.payload",
            "tb_wave.data",
            "tb_wave.real_sig",
            "tb_wave.lbl.[1:3]",
        ]
        assert all_types.signals[5].is_real
        assert all_types.signals[6].is_string
        assert all_types.signals[4].bitwidth == 64

    def test_scopes(self, all_types: WaveformFile) -> None:
        assert all_types.scope_names == ["tb_wave.lbl", "tb_wave"]

    def test_duration(self, all_types: WaveformFile) -> None:
        assert all_types.duration() == 995_000_000
        assert all_types.duration() == 995_000_000  # cached, same value

    def test_duration_bench(self, store: FileStore, bench_path: Path) -> None:
        file = store.open(str(bench_path))
        assert file.ticks_per_second == Decimal("1e-15")
        assert file.duration() == 2_000_000_000_000

    def test_missing_file(self, store: FileStore) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            store.open("/nonexistent/nope.fst")

    def test_unsupported_or_corrupt_file(
        self, store: FileStore, tmp_path: Path
    ) -> None:
        # A file that exists but isn't a VCD/FST/GHW — pywellen raises a
        # bare RuntimeError for this; FileStore.open should wrap it in a
        # clean, self-describing error instead of letting it propagate.
        bad = tmp_path / "not_a_waveform.fst"
        bad.write_text("this is definitely not a waveform file")
        with pytest.raises(WaveformOpenError, match="could not be opened"):
            store.open(str(bad))

    def test_open_returns_cached_instance(
        self, store: FileStore, all_types_path: Path
    ) -> None:
        first = store.open(str(all_types_path))
        assert first is store.open(str(all_types_path))

    def test_lru_eviction(self, all_types_path: Path, bench_path: Path) -> None:
        store = FileStore(max_files=1)
        small = store.open(str(all_types_path))
        big = store.open(str(bench_path))
        assert big.path in store._files
        assert small.path not in store._files
        assert store.open(str(all_types_path)) is not small


class TestResolve:
    def test_exact_full_name(self, all_types: WaveformFile) -> None:
        res = all_types.resolve(CLK)
        assert res.signal.full_name == CLK
        assert res.note is None

    def test_case_insensitive(self, all_types: WaveformFile) -> None:
        assert all_types.resolve("TB_WAVE.CNT").signal.full_name == "tb_wave.cnt"

    def test_leaf_suffix_match(self, all_types: WaveformFile) -> None:
        res = all_types.resolve("clk")
        assert res.signal.full_name == CLK
        assert res.note is not None

    def test_multicomponent_suffix(self, all_types: WaveformFile) -> None:
        res = all_types.resolve("lbl.[1:3]")
        assert res.signal.full_name == "tb_wave.lbl.[1:3]"
        assert res.note is not None

    def test_boundary_is_respected(self, all_types: WaveformFile) -> None:
        # "tbwave" is not the scope "tb_wave".
        with pytest.raises(SignalNotFound):
            all_types.resolve("tbwave.clk")

    def test_candidates_on_miss(self, all_types: WaveformFile) -> None:
        with pytest.raises(SignalNotFound) as exc:
            all_types.resolve("wave.cnt")
        assert exc.value.candidates == ["tb_wave.cnt"]

    def test_empty_name(self, all_types: WaveformFile) -> None:
        with pytest.raises(SignalNotFound):
            all_types.resolve("   ")

    def test_ambiguous(self) -> None:
        infos = [make_info("a.clk"), make_info("b.clk")]
        with pytest.raises(AmbiguousSignal) as exc:
            resolve_signal("clk", infos)
        assert exc.value.candidates == ["a.clk", "b.clk"]

    def test_ambiguous_prefers_exact(self) -> None:
        infos = [make_info("a.clk"), make_info("b.clk")]
        assert resolve_signal("b.clk", infos).signal.full_name == "b.clk"


class TestPacked:
    def test_clock(self, all_types: WaveformFile) -> None:
        packed = all_types.packed(CLK)
        assert packed.kind == "int"
        assert packed.is_int64
        assert len(packed.times) == 200
        assert packed.times[0] == 0
        assert packed.times[-1] == 995_000_000
        assert (packed.times[1:] - packed.times[:-1] > 0).all()
        assert set(packed.values.tolist()) == {0, 1}

    def test_cache_returns_same_object(self, all_types: WaveformFile) -> None:
        assert all_types.packed(CLK) is all_types.packed(CLK)

    def test_wide_vector_with_xz(self, all_types: WaveformFile) -> None:
        packed = all_types.packed("tb_wave.data")
        assert packed.kind == "str"
        assert len(packed.times) == 14
        assert packed.values[0] == "x" * 64
        assert packed.values[2] == 18446744073709551615

    def test_real_signal(self, all_types: WaveformFile) -> None:
        packed = all_types.packed("tb_wave.real_sig")
        assert packed.kind == "float"
        assert packed.values.min() == 0.0
        assert packed.values.max() == 7.5

    def test_bench_clock(self, store: FileStore, bench_path: Path) -> None:
        file = store.open(str(bench_path))
        packed = file.packed("tb_bench.clk")
        assert packed.kind == "int"
        assert len(packed.times) == 400_001

    def test_window_end_exclusive(self, all_types: WaveformFile) -> None:
        times, values = all_types.window(CLK, 0, 10_000_000)
        assert times.tolist() == [0, 5_000_000]
        assert values.tolist() == [0, 1]

    def test_window_open_end(self, all_types: WaveformFile) -> None:
        times, _ = all_types.window(CLK, 990_000_000, None)
        assert times.tolist() == [990_000_000, 995_000_000]

    def test_window_empty(self, all_types: WaveformFile) -> None:
        times, values = all_types.window(CLK, 123_456, 123_457)
        assert len(times) == 0 and len(values) == 0


class TestValueAt:
    def test_clock_edges(self, all_types: WaveformFile) -> None:
        # 20 ns period, rising at 5 ns: high 5-10 ns, low 10-15 ns.
        assert all_types.value_at("clk", 7_500_000) == 1
        assert all_types.value_at("clk", 12_500_000) == 0

    def test_resolves_name(self, all_types: WaveformFile) -> None:
        assert all_types.value_at("TB_WAVE.CLK", 7_500_000) == 1

    def test_missing(self, all_types: WaveformFile) -> None:
        with pytest.raises(SignalNotFound):
            all_types.value_at("nope", 0)
