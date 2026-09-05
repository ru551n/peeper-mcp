"""Open waveform files and per-signal packed change arrays.

A :class:`WaveformFile` wraps one pywellen ``Waveform`` and exposes:

- human-friendly signal-name resolution (case-insensitive, suffix match),
- a numpy-packed (time, value) change list per signal, decoded once and
  cached so repeated measurements are pure numpy,
- cheap time-based point reads (``value_at``) that skip full decoding.

A :class:`FileStore` keeps an LRU of open files (bounded by
``WAVE_MCP_MAX_FILES``).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pywellen

from waver_mcp.env import env_int
from waver_mcp.timeutil import TimeValueError, ticks_per_second

#: Seconds-per-unit exponents pywellen may report (10**exponent seconds).
_EXONENT_TO_UNIT: dict[int, str] = {
    -15: "fs",
    -12: "ps",
    -9: "ns",
    -6: "us",
    -3: "ms",
    0: "s",
}

#: How many signals to probe when estimating file duration.
_DURATION_PROBES = 16


class SignalNotFound(LookupError):
    """No signal matches the given name."""

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        hint = f"; similar names: {', '.join(candidates)}" if candidates else ""
        super().__init__(f"no signal named {name!r}{hint}")


class AmbiguousSignal(LookupError):
    """Several signals match the given name."""

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        super().__init__(f"signal name {name!r} is ambiguous: {', '.join(candidates)}")


class WaveformOpenError(RuntimeError):
    """Raised when pywellen cannot parse a file as VCD/FST/GHW."""

    def __init__(self, path: str, cause: BaseException) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"waveform file could not be opened: {path} ({cause})")


@dataclass(frozen=True)
class SignalInfo:
    """Header-only description of one signal."""

    full_name: str
    leaf: str
    var_type: str
    bitwidth: int | None
    is_real: bool
    is_string: bool
    is_1bit: bool
    is_bit_vector: bool
    components: tuple[str, ...]


@dataclass
class Resolution:
    """Result of name resolution, with a note when matching was fuzzy."""

    signal: SignalInfo
    note: str | None = None


@dataclass
class Packed:
    """A signal's change list as numpy arrays (times strictly increasing).

    ``kind`` is ``"int"``, ``"float"`` or ``"str"``. Int-kind values are
    stored as int64 when they all fit, else as Python ints in an object
    array (``is_int64`` says which).
    """

    times: np.ndarray
    values: np.ndarray
    kind: str
    is_int64: bool


def _unit_from_exponent(exponent: int) -> str:
    unit = _EXONENT_TO_UNIT.get(exponent)
    if unit is None:
        raise TimeValueError(f"unsupported file timescale: 10^{exponent} s per tick")
    return unit


def resolve_signal(name: str, signals: list[SignalInfo]) -> Resolution:
    """Resolve *name* to one of *signals*.

    Order: case-insensitive exact full name; then a unique suffix match
    on dot-separated name components (e.g. ``"state"`` or
    ``"tb.state"`` for ``tb.dut.state``); otherwise an error listing
    candidates (ambiguity, or substring hints).
    """
    q = name.strip()
    if not q:
        raise SignalNotFound(name, [])
    key = q.lower()

    for info in signals:
        if info.full_name.lower() == key:
            return Resolution(info)

    qparts = key.split(".")
    matches = [
        info
        for info in signals
        if len(info.components) >= len(qparts)
        and info.components[-len(qparts) :] == tuple(qparts)
    ]
    if len(matches) == 1:
        return Resolution(matches[0], note=f"matched {matches[0].full_name!r}")

    if matches:
        raise AmbiguousSignal(name, [m.full_name for m in matches])

    candidates = sorted({i.full_name for i in signals if key in i.full_name.lower()})
    raise SignalNotFound(name, candidates[:10])


class WaveformFile:
    """One open waveform file plus its decoded-signal cache."""

    def __init__(self, path: str, wf: pywellen.Waveform) -> None:
        self.path = path
        self.wf = wf
        exponent = wf.timescale.unit.to_exponent()
        self.ticks_per_second: Decimal = ticks_per_second(
            wf.timescale.factor, _unit_from_exponent(exponent)
        )
        self.signals: list[SignalInfo] = []
        self.scope_names: list[str] = []
        self._vars: dict[str, pywellen.Var] = {}
        self._packed: dict[str, Packed] = {}
        self._duration: int | None = None
        for var in wf.all_vars():
            self.signals.append(
                SignalInfo(
                    full_name=var.full_name,
                    leaf=var.full_name.rsplit(".", 1)[-1],
                    var_type=var.var_type,
                    bitwidth=var.bitwidth,
                    is_real=var.is_real,
                    is_string=var.is_string,
                    is_1bit=var.is_1bit,
                    is_bit_vector=var.is_bit_vector,
                    components=tuple(var.full_name.lower().split(".")),
                )
            )
            self._vars[var.full_name] = var
        for scope in wf.all_scopes():
            self.scope_names.append(scope.full_name)

    def resolve(self, name: str) -> Resolution:
        return resolve_signal(name, self.signals)

    def packed(self, full_name: str) -> Packed:
        """Packed change list for *full_name*, decoded on first use."""
        packed = self._packed.get(full_name)
        if packed is None:
            packed = self._decode(full_name)
            self._packed[full_name] = packed
        return packed

    def _decode(self, full_name: str) -> Packed:
        changes = self._vars[full_name].tv[:]
        times = np.fromiter((t for t, _ in changes), dtype=np.int64, count=len(changes))
        values: list[pywellen.Value] = [v for _, v in changes]
        if any(isinstance(v, str) for v in values):
            return Packed(times, np.array(values, dtype=object), "str", False)
        if any(isinstance(v, float) for v in values):
            return Packed(times, np.array(values, dtype=np.float64), "float", False)
        ints = [int(v) for v in values]
        lo = np.iinfo(np.int64).min
        hi = np.iinfo(np.int64).max
        fits = (not ints) or (min(ints) >= lo and max(ints) <= hi)
        dtype = np.int64 if fits else object
        return Packed(times, np.array(ints, dtype=dtype), "int", fits)

    def window(
        self, full_name: str, start: int, end: int | None
    ) -> tuple[np.ndarray, np.ndarray]:
        """Changes with ``start <= t < end`` (``end=None`` means until last)."""
        packed = self.packed(full_name)
        i = np.searchsorted(packed.times, start, side="left")
        if end is None:
            return packed.times[i:], packed.values[i:]
        j = np.searchsorted(packed.times, end, side="left")
        return packed.times[i:j], packed.values[i:j]

    def value_at(self, name: str, ticks: int) -> pywellen.Value:
        """Value of *name* at (or most recently before) *ticks*."""
        full_name = self.resolve(name).signal.full_name
        return self._vars[full_name].tv.value_at(ticks)

    def duration(self) -> int:
        """Latest change time seen across a sample of signals (cached)."""
        if self._duration is None:
            self._duration = self._probe_duration()
        return self._duration

    def _probe_duration(self) -> int:
        vars_list = list(self._vars.values())
        n = len(vars_list)
        if n == 0:
            return 0
        if n <= _DURATION_PROBES:
            indices = list(range(n))
        else:
            indices = sorted({int(x) for x in np.linspace(0, n - 1, _DURATION_PROBES)})
        end = 0
        for i in indices:
            tail = vars_list[i].tv[-1:]
            if tail:
                end = max(end, tail[0][0])
        return end


class FileStore:
    """LRU cache of open :class:`WaveformFile` objects by resolved path."""

    def __init__(self, max_files: int | None = None) -> None:
        self.max_files = max_files or env_int("MAX_FILES", "4")
        self._files: OrderedDict[str, WaveformFile] = OrderedDict()

    def open(self, path: str) -> WaveformFile:
        resolved = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"waveform file not found: {resolved}")
        existing = self._files.get(resolved)
        if existing is not None:
            self._files.move_to_end(resolved)
            return existing
        try:
            wf = pywellen.Waveform(resolved)
        except Exception as exc:
            # pywellen raises a bare RuntimeError (or similar) for
            # unsupported/corrupt files — surface it as a clean,
            # self-describing error instead of an unhandled traceback.
            raise WaveformOpenError(resolved, exc) from exc
        file = WaveformFile(resolved, wf)
        self._files[resolved] = file
        while len(self._files) > self.max_files:
            # Dropping the last reference closes the Rust file handle.
            self._files.popitem(last=False)
        return file

    def close_all(self) -> None:
        self._files.clear()
