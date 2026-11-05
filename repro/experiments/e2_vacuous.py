"""E2: vacuous success of agent-written checks under base / checklist / guard (brief 4, E2)."""
from __future__ import annotations

import json

from .. import sandbox
from ..agent.pipeline import write_validators
from .common import RunContext

CONDITIONS = ["base", "checklist", "guard"]
SIM_SEED_PAIRS = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)]
PROBE = sandbox.SUPPORT_DIR / "validator_probe.py"
SIM_PROBE = sandbox.SUPPORT_DIR / "sim_probe.py"


def collect(ctx: RunContext) -> None:
    ctx.data["e2"] = {cond: write_validators(ctx.slot, ctx.seed, ctx.run_id, cond, ctx.art.log) for cond in CONDITIONS}


def _run(script, files: dict, args: list[str], kind: str) -> dict:
    key = sandbox.cache_key(kind, files, args, script.read_text())
    hit = sandbox.cache_get(kind, key)
    if hit is not None:
        return hit
    d = sandbox.make_workdir(files, kind)
    try:
        out_path = d / ".out.json"
        p = sandbox.run([str(script), str(out_path), *args], d)
        out = json.loads(out_path.read_text()) if out_path.exists() else {"error": "probe failed",
                                                                           "timed_out": p.timed_out}
    finally:
        sandbox.remove(d)
    if not out.get("timed_out"):
        sandbox.cache_put(kind, key, out)
    return out


def measure(ctx: RunContext) -> None:
    res = {cond: _run(PROBE, ctx.data["e2"][cond]["files"], [], "validators") for cond in CONDITIONS}
    sim_files = {k: v for k, v in ctx.art.files.items() if k.endswith(".py") or k == "data.toml"}
    sims = _run(SIM_PROBE, sim_files, [json.dumps(SIM_SEED_PAIRS)], "simseeds")
    ctx.data["e2_measure"] = {"validators": res, "sim": sims}


def tables(ctxs: list[RunContext]) -> dict[str, list[dict]]:
    rows, seeds = [], []
    for ctx in ctxs:
        meas = ctx.data["e2_measure"]
        for cond in CONDITIONS:
            deps = ctx.deps(f"e2_{cond}")
            per = meas["validators"][cond]
            for n in range(1, 10):
                v = per.get(f"V{n}", {"kind": "missing", "probes": {}})
                for probe in ("[]", "{}", "()", "all_none"):
                    p = v["probes"].get(probe, {"passed": False, "note": "missing"})
                    rows.append({"run": ctx.run_id, "seed": ctx.seed, "condition": cond,
                                 "set": "V1-V6" if n <= 6 else "V7-V9", "validator": f"V{n}", "kind": v["kind"],
                                 "probe": probe, "passed": bool(p["passed"]), "note": p.get("note", ""),
                                 "_deps": deps})
        sim = meas["sim"]
        for a, b in SIM_SEED_PAIRS:
            same = sim.get(f"{a},{b}") if "error" not in sim else None
            seeds.append({"run": ctx.run_id, "seed": ctx.seed, "pair": f"{a},{b}", "identical": same,
                          "error": sim.get("error", ""), "_deps": ctx.standard_deps()})
    return {"e2_vacuous": rows, "e2_sim_seeds": seeds}


def _rate(rows, cond, sets):
    sel = [r for r in rows if r["condition"] == cond and r["set"] in sets]
    return (round(sum(r["passed"] for r in sel) / len(sel), 4), len(sel)) if sel else (None, 0)


def verdicts(live: dict[str, list[dict]]) -> dict[str, dict]:
    rows = live["e2_vacuous"]
    if not rows:
        return {"E2": {"verdict": None, "n": 0}}
    rates = {f"{c}/{s}": _rate(rows, c, {s}) for c in CONDITIONS for s in ("V1-V6", "V7-V9")}
    base_all, n_base = _rate(rows, "base", {"V1-V6", "V7-V9"})
    c16, c79 = rates["checklist/V1-V6"][0], rates["checklist/V7-V9"][0]
    b16 = rates["base/V1-V6"][0]
    g16, g79 = rates["guard/V1-V6"][0], rates["guard/V7-V9"][0]
    ok = (base_all is not None and base_all >= 0.33 and c79 is not None and c79 >= 0.5 * base_all
          and c16 is not None and b16 is not None and c16 < b16 and g16 is not None and g16 < 0.05
          and g79 is not None and g79 < 0.05)
    seeds = live["e2_sim_seeds"]
    known = [r["identical"] for r in seeds if r["identical"] is not None]
    return {"E2": {"verdict": "reproduces" if ok else "does not reproduce", "n": len(rows), "base_V1_V9": base_all,
                   "rates": {k: v[0] for k, v in rates.items()}, "n_per_cell": {k: v[1] for k, v in rates.items()},
                   "vacuous_seed_fraction": round(sum(known) / len(known), 4) if known else None,
                   "n_seed_pairs": len(known)}}
