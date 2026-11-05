"""E2 vacuous seeds (subprocess side): do the agent's sim.simulate seed pairs give identical output?

Usage: python sim_probe.py OUT_JSON PAIRS_JSON
"""
import importlib
import json
import sys


def main():
    sys.path.insert(0, ".")
    pairs = json.loads(sys.argv[2])
    out = {}
    try:
        simulate = importlib.import_module("sim").simulate
    except Exception as exc:
        json.dump({"error": f"{type(exc).__name__}: {exc}"}, open(sys.argv[1], "w"))
        return
    for a, b in pairs:
        try:
            out[f"{a},{b}"] = repr(simulate(30, a)) == repr(simulate(30, b))
        except Exception as exc:
            out[f"{a},{b}"] = None
    json.dump(out, open(sys.argv[1], "w"))


if __name__ == "__main__":
    main()
