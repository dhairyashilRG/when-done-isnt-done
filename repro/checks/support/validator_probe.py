"""E2 probe (subprocess side): run each agent-written validator on empty and all-unmeasured input.

Usage: python validator_probe.py OUT_JSON   (cwd holds validators.py, validators_later.py, checks_base.py)
"""
import importlib
import json
import sys

NONE_INPUTS = {
    1: [{"sku": None, "wh": None, "units": None, "value_cents": None, "unit_cost": None}],
    2: [None, None],
    3: [{"seed": None, "a": None, "b": None}],
    4: [{"day": None, "storage_cost_cents": None, "budget_cents": None}],
    5: [{"clause_id": None, "tests": None}],
    6: [{"key": None, "a": None, "b": None}],
    7: [{"wh": None, "capacity": None, "max_units": None}],
    8: [{"expired": None, "notified": None}],
    9: [{"supplier": None, "reliability": None}],
}
PROBES = {"[]": lambda n: [], "{}": lambda n: {}, "()": lambda n: (), "all_none": lambda n: NONE_INPUTS[n]}


def _passed(result):
    if hasattr(result, "passed"):
        return bool(result.passed)
    if isinstance(result, tuple) and result:
        return bool(result[0])
    return bool(result)


def main():
    sys.path.insert(0, ".")
    mods = []
    for name in ("validators", "validators_later"):
        try:
            mods.append(importlib.import_module(name))
        except Exception as exc:
            mods.append(None)
    out = {}
    for n in range(1, 10):
        entry = None
        for m in mods:
            if m is None:
                continue
            cls, fn = getattr(m, f"V{n}", None), getattr(m, f"v{n}", None)
            if isinstance(cls, type):
                entry = ("class", cls)
                break
            if callable(fn):
                entry = ("function", fn)
                break
            if callable(cls):
                entry = ("function", cls)
                break
        res = {}
        for probe, make in PROBES.items():
            if entry is None:
                res[probe] = {"passed": False, "note": "missing"}
                continue
            try:
                if entry[0] == "class":
                    obj = entry[1]()
                    r = obj.run(make(n)) if hasattr(obj, "run") else obj.check(make(n))
                else:
                    r = entry[1](make(n))
                res[probe] = {"passed": _passed(r), "note": ""}
            except Exception as exc:
                res[probe] = {"passed": False, "note": f"raised {type(exc).__name__}"}
        out[f"V{n}"] = {"kind": entry[0] if entry else "missing", "probes": res}
    json.dump(out, open(sys.argv[1], "w"))


if __name__ == "__main__":
    main()
