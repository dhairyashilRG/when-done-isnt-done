"""Find the implementation's modules, its Depot class and its DepotError (subprocess side only)."""
import importlib
import os
import sys
from pathlib import Path

SPEC_METHODS = ["add_item", "receive", "ship", "list_price", "transfer", "advance_day", "notifications",
                "place_order", "deliver", "reinstate", "audit", "return_goods", "receive_bulk", "stock",
                "report", "undo", "save", "load", "turnover"]
PREFERRED = ["inventory", "depot", "reference", "reference_hand", "money", "events", "suppliers", "sim"]


def impl_dir() -> Path:
    return Path(os.environ.get("DEPOT_IMPL_DIR") or os.getcwd())


def modules():
    d = impl_dir()
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    names = [n for n in PREFERRED if (d / f"{n}.py").exists()]
    names += sorted(p.stem for p in d.glob("*.py") if p.stem not in names
                    and not p.stem.startswith(("test_", "_")) and p.stem not in ("demo", "conftest", "sitecustomize"))
    out = []
    for n in names:
        try:
            out.append(importlib.import_module(n))
        except Exception:
            pass
    return out


def depot_classes(mods):
    seen = []
    for m in mods:
        for v in vars(m).values():
            if isinstance(v, type) and v not in seen and sum(hasattr(v, n) for n in SPEC_METHODS) >= 5:
                seen.append(v)
    return seen


def error_classes(mods):
    seen = []
    for m in mods:
        v = getattr(m, "DepotError", None)
        if isinstance(v, type) and issubclass(v, BaseException) and v not in seen:
            seen.append(v)
    return seen
