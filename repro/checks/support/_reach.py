"""Reach instrumentation (subprocess side): log every spec observable that actually occurs.

Wraps the implementation's Depot-like classes, its ``DepotError`` and ``simulate`` at run time and
logs, while ``demo.py`` and the agent's own tests run:

* ``ok:<method>`` / ``raise:<method>`` for each public spec call that returns / raises;
* ``err:<CODE>`` for each ``DepotError`` constructed;
* ``notif:<TYPE>`` for each notification that appears in the log during a public call;
* ``branch:<name>`` for named branches through the public API (see ``_post``).

Loaded as a pytest plugin (``-p _reach``) or via ``_reach.install()`` before running ``demo.py``.
The log is appended as JSON lines to ``REPRO_REACH_LOG`` at exit.
"""
import atexit
import enum
import functools
import inspect
import json
import os
import tomllib
from pathlib import Path

import _impl_lookup

LOG = set()
_depth = [0]
_installed = [False]
_shadow = {"skus": set(), "day": 0, "receipt_days": {}, "orders": {}, "reorders": {}, "seeds": set()}


def _norm(x):
    if isinstance(x, enum.Enum):
        return x.value if isinstance(x.value, str) else x.name
    return x


def _kind(n):
    if isinstance(n, str):
        return n
    if isinstance(n, dict):
        return str(_norm(n.get("type", n.get("kind", n.get("name")))))
    if isinstance(n, (list, tuple)) and n:
        return str(_norm(n[0]))
    return str(_norm(getattr(n, "kind", getattr(n, "type", "?"))))


def _bulk_threshold():
    try:
        with open(Path(_impl_lookup.impl_dir()) / "data.toml", "rb") as fh:
            return int(tomllib.load(fh)["bulk_threshold"])
    except Exception:
        return 20


SPEC_PARAMS = {"add_item": ["sku", "unit_cost", "reorder_level", "shelf_life_days"],
               "receive": ["sku", "qty", "wh"], "ship": ["sku", "qty", "wh", "price"],
               "stock": ["sku", "wh"], "place_order": ["supplier", "sku", "qty", "due_day"],
               "deliver": ["order_id", "day"], "receive_bulk": ["receipts"], "turnover": ["start_day", "end_day"]}


def _bind(fn, self, args, kwargs, name=""):
    """Arguments under the spec's parameter names, matched by position (robust to renamed parameters)."""
    try:
        b = inspect.signature(fn).bind(self, *args, **kwargs)
    except Exception:
        return {}
    values = list(b.arguments.values())[1:]
    names = SPEC_PARAMS.get(name)
    return dict(zip(names, values)) if names else dict(list(b.arguments.items())[1:])


def _notes(self):
    try:
        return list(self.notifications())
    except Exception:
        return []


def _units(self):
    total = 0
    for sku in list(_shadow["skus"]):
        try:
            total += int(self.stock(sku))
        except Exception:
            pass
    return total


def _post(self, name, a, result, pre):
    """Named branches, judged from arguments, results and the notification log."""
    new = _notes(self)[pre["n_notes"]:] if pre.get("n_notes") is not None else []
    kinds = [_kind(n) for n in new]
    for k in kinds:
        LOG.add(f"notif:{k}")
    for n in new:
        if _kind(n) == "REORDER" and isinstance(n, (list, tuple)) and len(n) >= 3:
            key = (n[1], n[2])
            _shadow["reorders"][key] = _shadow["reorders"].get(key, 0) + 1
            if _shadow["reorders"][key] >= 2:
                LOG.add("branch:reorder.rearm")
    if name == "add_item" and "sku" in a:
        _shadow["skus"].add(a["sku"])
    elif name == "advance_day":
        _shadow["day"] += 1
        if pre.get("units", 0) > 0:
            LOG.add("branch:advance_day.storage")
            if "EXPIRY" in kinds:
                LOG.add("branch:advance_day.expiry_with_storage")
    elif name == "receive":
        key = (a.get("sku"), a.get("wh"))
        _shadow["receipt_days"].setdefault(key, set()).add(_shadow["day"])
    elif name == "receive_bulk":
        for r in a.get("receipts", a.get("list_of_receipts", [])) or []:
            try:
                sku, _qty, wh = r
                _shadow["receipt_days"].setdefault((sku, wh), set()).add(_shadow["day"])
            except Exception:
                pass
    elif name == "ship":
        qty = a.get("qty")
        if isinstance(qty, int) and qty >= _bulk_threshold():
            LOG.add("branch:ship.bulk")
        if len(_shadow["receipt_days"].get((a.get("sku"), a.get("wh")), ())) >= 2:
            LOG.add("branch:ship.fifo")
    elif name == "stock":
        LOG.add("branch:stock.total" if a.get("wh") is None else "branch:stock.wh")
    elif name == "place_order":
        _shadow["orders"][repr(result)] = a.get("due_day")
    elif name == "deliver":
        due = _shadow["orders"].get(repr(a.get("order_id")))
        day = a.get("day")
        if isinstance(due, int) and isinstance(day, int):
            LOG.add("branch:deliver.late" if day > due else "branch:deliver.on_time")
    elif name == "turnover" and result is None:
        LOG.add("branch:turnover.none")


def _wrap_method(cls, name, fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if _depth[0] > 0:
            return fn(self, *args, **kwargs)
        _depth[0] += 1
        try:
            a = _bind(fn, self, args, kwargs, name)
            pre = {"n_notes": len(_notes(self)) if name != "__init__" else None}
            if name == "advance_day":
                pre["units"] = _units(self)
            try:
                result = fn(self, *args, **kwargs)
            except Exception:
                LOG.add(f"raise:{name}")
                if name == "transfer":
                    LOG.add("branch:transfer.rejected")
                elif name == "receive_bulk":
                    LOG.add("branch:receive_bulk.rejected")
                raise
            LOG.add(f"ok:{name}")
            if name != "__init__":
                _post(self, name, a, result, pre)
            return result
        finally:
            _depth[0] -= 1
    return wrapper


def _wrap_error(cls):
    orig = cls.__init__

    @functools.wraps(orig)
    def init(self, *args, **kwargs):
        code = kwargs.get("code", args[0] if args else None)
        LOG.add(f"err:{_norm(code)}")
        orig(self, *args, **kwargs)
    cls.__init__ = init


def _wrap_simulate(mods):
    for m in mods:
        fn = getattr(m, "simulate", None)
        if callable(fn) and not getattr(fn, "_reach_wrapped", False):
            @functools.wraps(fn)
            def sim(*args, _fn=fn, **kwargs):
                a = {}
                try:
                    sig = inspect.signature(_fn).bind(*args, **kwargs)
                    a = dict(sig.arguments)
                except Exception:
                    pass
                result = _fn(*args, **kwargs)
                LOG.add("ok:simulate")
                _shadow["seeds"].add(repr(a.get("seed")))
                if len(_shadow["seeds"]) >= 2:
                    LOG.add("branch:simulate.two_seeds")
                return result
            sim._reach_wrapped = True
            for other in mods:  # rebind everywhere the same function object is visible
                for k, v in list(vars(other).items()):
                    if v is fn:
                        setattr(other, k, sim)


def install():
    if _installed[0]:
        return
    _installed[0] = True
    mods = _impl_lookup.modules()
    for cls in _impl_lookup.error_classes(mods):
        _wrap_error(cls)
    for cls in _impl_lookup.depot_classes(mods):
        for name in _impl_lookup.SPEC_METHODS + ["__init__"]:
            fn = cls.__dict__.get(name)
            if callable(fn):
                setattr(cls, name, _wrap_method(cls, name, fn))
    _wrap_simulate(mods)
    atexit.register(dump)


def dump():
    path = os.environ.get("REPRO_REACH_LOG")
    if path and LOG:
        with open(path, "a") as fh:
            fh.write(json.dumps(sorted(LOG)) + "\n")


def pytest_configure(config):
    install()


def pytest_unconfigure(config):
    dump()
    LOG.clear()
