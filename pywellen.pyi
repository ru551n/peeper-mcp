"""Mypy stubs for the pywellen package (untyped Rust/pyo3 bindings).

pywellen ships no type information; these stubs cover the surface that
waver_mcp uses.
"""

Value = int | float | str

class TimescaleUnit:
    def to_exponent(self) -> int: ...

class Timescale:
    factor: int
    unit: TimescaleUnit

class Signal:
    """One signal's change history.

    Slicing is index-based (like a Python list of (time, value) tuples);
    use ``value_at`` for time-based point access.
    """

    def value_at(self, ticks: int) -> Value: ...
    def __getitem__(self, index: slice) -> list[tuple[int, Value]]: ...

class Var:
    name: str
    full_name: str
    var_type: str
    type: str
    vhdl_type_name: str
    enum_type: str | None
    direction: str
    bitwidth: int | None
    size: int
    is_1bit: bool
    is_bit_vector: bool
    is_real: bool
    is_string: bool
    tv: Signal
    signal: Signal
    signal_id: int
    signal_ref: int

class Scope:
    name: str
    full_name: str
    scope_type: str
    type: str

    def vars(self) -> list[Var]: ...
    def all_vars(self) -> list[Var]: ...
    def scopes(self) -> list[Scope]: ...
    def all_scopes(self) -> list[Scope]: ...

class Waveform:
    def __init__(self, path: str) -> None: ...

    timescale: Timescale
    date: str
    version: str
    file_format: str

    def vars(self) -> list[Var]: ...
    def all_vars(self) -> list[Var]: ...
    def scopes(self) -> list[Scope]: ...
    def all_scopes(self) -> list[Scope]: ...
    def __getitem__(self, name: str) -> Signal: ...
