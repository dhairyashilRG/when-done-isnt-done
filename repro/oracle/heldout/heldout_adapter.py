"""Adapter between the held-out suite and any Depot implementation (agent-written or reference).

The implementation lives in the directory named by ``DEPOT_IMPL_DIR``; it is imported only inside
the subprocess that runs this suite, never in the harness process. Lookups are lazy, so a broken
implementation fails each test instead of breaking collection.

Gate values are injected here (brief 2.3): ``rounding_mode`` by keyword, and ``late_penalty_pct``
through any constructor or ``deliver`` parameter whose name contains "penalty". An implementation
that hard-codes a gate value instead fails that gate's tests for the other value.
"""
from __future__ import annotations

import enum
import functools
import importlib
import inspect
import os
import sys
from pathlib import Path

CANDIDATE_MODULES = ["inventory", "depot", "reference", "reference_hand", "money", "events", "suppliers", "sim"]
_cache: dict[str, object] = {}

DEFAULT_ROUNDING = "ROUND_HALF_EVEN"
DEFAULT_PENALTY = 25
GATE_ROUNDING = ["ROUND_HALF_UP", "ROUND_HALF_EVEN"]
GATE_PENALTY = [10, 25]


def _impl_dir() -> Path:
    d = os.environ.get("DEPOT_IMPL_DIR")
    if not d:
        raise RuntimeError("DEPOT_IMPL_DIR is not set")
    return Path(d)


def _modules():
    if "_modules" in _cache:
        return _cache["_modules"]
    impl = _impl_dir()
    if str(impl) not in sys.path:
        sys.path.insert(0, str(impl))
    names = [n for n in CANDIDATE_MODULES if (impl / f"{n}.py").exists()]
    names += sorted(p.stem for p in impl.glob("*.py")
                    if p.stem not in names and not p.stem.startswith(("test_", "_")) and p.stem not in ("demo", "conftest"))
    mods, errors = [], []
    for n in names:
        try:
            mods.append(importlib.import_module(n))
        except Exception as exc:  # recorded; the test that needs the module fails
            errors.append(f"{n}: {type(exc).__name__}: {exc}")
    _cache["_modules"] = mods
    _cache["_errors"] = errors
    return mods


def get(attr: str):
    if attr in _cache:
        return _cache[attr]
    for mod in _modules():
        if hasattr(mod, attr):
            _cache[attr] = getattr(mod, attr)
            return _cache[attr]
    raise LookupError(f"implementation exposes no {attr!r}; import errors: {_cache.get('_errors')}")


def Error():
    return get("DepotError")


def _norm_scalar(x):
    if isinstance(x, enum.Enum):
        return x.value if isinstance(x.value, str) else x.name
    return x


def code_of(exc) -> str:
    code = getattr(exc, "code", None)
    if code is None and exc.args:
        code = exc.args[0]
    code = _norm_scalar(code)
    return str(code)


def norm_note(n) -> tuple:
    if isinstance(n, str):
        return (n,)
    if isinstance(n, dict):
        kind = n.get("type", n.get("kind", n.get("name")))
        rest = [v for k, v in n.items() if k not in ("type", "kind", "name")]
        return (_norm_scalar(kind), *map(_norm_scalar, rest))
    if isinstance(n, (list, tuple)):
        return tuple(_norm_scalar(x) for x in n)
    kind = getattr(n, "kind", getattr(n, "type", None))
    args = getattr(n, "args", ())
    return (_norm_scalar(kind), *map(_norm_scalar, args))


def notes(d) -> list[tuple]:
    return [norm_note(n) for n in d.notifications()]


def notes_of(d, kind: str) -> list[tuple]:
    return [n for n in notes(d) if n and n[0] == kind]


def cash(d) -> int:
    for name in ("cash", "balance"):
        if hasattr(d, name):
            v = getattr(d, name)
            return v() if callable(v) else v
    if hasattr(d, "get_cash"):
        return d.get_cash()
    raise LookupError("no cash accessor")


def reliability(d, supplier) -> int:
    return d.reliability(supplier)


def norm_row(r) -> tuple:
    if isinstance(r, dict):
        return (r.get("sku"), r.get("wh", r.get("warehouse")), r.get("units"), r.get("value_cents", r.get("value")))
    return tuple(r)


def report(d) -> list[tuple]:
    return [row for row in (norm_row(r) for r in d.report()) if row[2]]


def norm_sim(out) -> list[list[tuple]]:
    days = []
    for entry in out:
        if isinstance(entry, dict):
            days.append(sorted((k, v) for k, v in entry.items()))
        else:
            orders = []
            for o in entry:
                if isinstance(o, dict):
                    orders.append((o.get("sku"), o.get("qty")))
                else:
                    orders.append(tuple(o))
            days.append(orders)
    return days


def _params(fn) -> dict:
    try:
        return dict(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return {}


def construct(warehouses=("A", "B"), capacities=None, opening_cash=100_000, *, rounding_mode=DEFAULT_ROUNDING,
              late_penalty_pct=DEFAULT_PENALTY, omit_rounding=False):
    Depot = get("Depot")
    warehouses = list(warehouses)
    capacities = dict(capacities) if capacities else {w: 1000 for w in warehouses}
    params = _params(Depot.__init__)
    core = {"warehouses": warehouses, "capacities": capacities, "opening_cash": opening_cash}
    if not omit_rounding:
        core["rounding_mode"] = rounding_mode
    extra = {}
    for name, p in params.items():
        low = name.lower()
        if "penalty" in low:
            extra[name] = late_penalty_pct
        elif "perishable" in low or "return_policy" in low:
            extra[name] = "restock"
    if all(k in params for k in ("warehouses", "capacities", "opening_cash")):
        d = Depot(**core, **extra)
    else:
        d = Depot(*core.values(), **extra)
    if not any("penalty" in n.lower() for n in params):
        deliver = getattr(d, "deliver", None)
        dparams = _params(deliver) if deliver else {}
        pname = next((n for n in dparams if "penalty" in n.lower()), None)
        if pname:
            d.deliver = functools.partial(deliver, **{pname: late_penalty_pct})
    return d


def make(warehouses=("A", "B"), capacities=None, opening_cash=100_000, *, rounding_mode=DEFAULT_ROUNDING,
         late_penalty_pct=DEFAULT_PENALTY, items=True):
    d = construct(warehouses, capacities, opening_cash, rounding_mode=rounding_mode, late_penalty_pct=late_penalty_pct)
    if items:
        d.add_item("BOLT", 12, 50)
        d.add_item("GLUE", 240, 5, shelf_life_days=7)
    return d


def expect_code(code: str, fn, *args, **kwargs):
    E = Error()
    try:
        fn(*args, **kwargs)
    except E as exc:
        got = code_of(exc)
        assert got == code, f"expected DepotError({code}), got DepotError({got})"
        return
    raise AssertionError(f"expected DepotError({code}); nothing was raised")


def expect_error(fn, *args, **kwargs):
    E = Error()
    try:
        fn(*args, **kwargs)
    except E:
        return
    raise AssertionError("expected a DepotError; nothing was raised")


def advance(d, n: int):
    for _ in range(n):
        d.advance_day()
