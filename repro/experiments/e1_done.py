"""E1: "done" against actually done, and what test metrics see (brief 4, E1, E1b, E1c)."""
from __future__ import annotations

from ..agent.pipeline import IMPL_MODULES, TEST_FILE, apply_review, impl_only, run_agent_tests
from ..checks.mutation import mutation_scores
from ..checks.presence import PresenceCheck, run_demo
from ..checks.reach import observe, reach_verdicts
from ..oracle.notes import NOTIFICATION_ONLY, SPEC_MODULES, STATE_DEPENDENT
from ..oracle.runner import heldout_files, run_heldout
from ..spec import CLAUSE_IDS
from ..stats import bootstrap_ci, median, spearman
from .common import MODULE_CLAUSES, RunContext, agent_pass_by_clause, ticked

N_REVIEW_COMMENTS = 8

CONTROL_TAUTOLOGY = '''"""Mutation control (i): tautologies that call nothing."""


def test_tautology_1():
    assert True


def test_tautology_2():
    assert True


def test_tautology_3():
    assert True
'''

CONTROL_GETTER = '''"""Mutation control (ii): construct the depot; assert stored fields and table values only."""
import importlib
import inspect
import tomllib
from pathlib import Path

DATA = tomllib.loads(Path(__file__).with_name("data.toml").read_text())


def _depot_class():
    for name in ("inventory", "depot", "reference"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        if hasattr(mod, "Depot"):
            return mod.Depot
    raise LookupError("Depot")


def _make():
    Depot = _depot_class()
    extra = {}
    for n in inspect.signature(Depot.__init__).parameters:
        if "penalty" in n.lower():
            extra[n] = 25
        elif "perishable" in n.lower() or "return_policy" in n.lower():
            extra[n] = "restock"
    return Depot(warehouses=["A", "B"], capacities={"A": 100, "B": 100}, opening_cash=1000,
                 rounding_mode="ROUND_HALF_EVEN", **extra)


def test_constructs():
    assert _make() is not None


def test_opening_cash_is_stored():
    c = _make().cash
    assert (c() if callable(c) else c) == 1000


def test_table_markup():
    assert DATA["markup"] == 0.35


def test_table_bolt_cost():
    assert DATA["items"]["BOLT"]["unit_cost"] == 12


def test_table_bulk_threshold():
    assert DATA["bulk_threshold"] == 20
'''


def _impl_with(files: dict, extra: dict) -> dict:
    out = impl_only(files)
    out.update(extra)
    return out


# ------------------------------------------------------------------ collect (agent calls: E1c)
def collect(ctx: RunContext) -> None:
    art = ctx.art
    held = run_heldout(impl_only(art.files))
    ctx.data["heldout"] = held
    failing = sorted((t for t in held["tests"] if t["outcome"] != "passed"), key=lambda t: t["nodeid"])
    chosen = failing[:N_REVIEW_COMMENTS]
    comments = [{"k": i + 1, "nodeid": t["nodeid"], "clauses": t["clauses"],
                 "text": f"({', '.join(t['clauses'])}) {t['doc']}"} for i, t in enumerate(chosen)]
    e1c = {"comments": comments, "claimed": {}, "landed": {}}
    if comments:
        conv = art.conversation.fork(ctx.run_id)
        new_files, report, _text = apply_review(conv, [c["text"] for c in comments])
        after = dict(art.files)
        after.update(new_files)
        held_after = run_heldout(impl_only(after))
        outcome = {t["nodeid"]: t["outcome"] for t in held_after["tests"]}
        for c in comments:
            e1c["claimed"][str(c["k"])] = bool(report.get(str(c["k"]), False))
            e1c["landed"][str(c["k"])] = outcome.get(c["nodeid"]) == "passed"
        e1c["changed_files"] = sorted(new_files)
    ctx.data["e1c"] = e1c


# ------------------------------------------------------------------ measure (no agent calls)
def measure(ctx: RunContext) -> None:
    art = ctx.art
    files = art.files
    impl = impl_only(files)
    py_impl = {k: v for k, v in impl.items() if k.endswith(".py") and not k.startswith("vendor/")}
    demo = run_demo(files)
    presence = PresenceCheck().run({"files": py_impl, "demo_ok": demo["ok"]})
    observed = observe(files)
    m = {"demo": demo, "presence": presence.passed, "presence_measured": presence.measured,
         "reach": reach_verdicts(observed["observed"]), "agent_pass": agent_pass_by_clause(art.final_tests)}
    # E1b: the same checks with the notification log disabled
    m["null_tests"] = run_agent_tests(files, plugins=("_nullsink",))
    m["null_demo"] = run_demo(files, null_sink=True)
    m["null_presence"] = PresenceCheck().run({"files": py_impl, "demo_ok": m["null_demo"]["ok"]}).passed
    m["null_heldout"] = run_heldout(impl, null_sink=True)
    # Mutation: the agent's own tests, and the three controls
    modules = [p for p in IMPL_MODULES if p in files]
    with_tests = _impl_with(files, {TEST_FILE: files.get(TEST_FILE, "")})
    m["mut_agent"] = mutation_scores(with_tests, [TEST_FILE], modules)
    m["mut_tautology"] = mutation_scores(_impl_with(files, {"test_control_tautology.py": CONTROL_TAUTOLOGY}),
                                         ["test_control_tautology.py"], modules)
    m["mut_getter"] = mutation_scores(_impl_with(files, {"test_control_getter.py": CONTROL_GETTER}),
                                      ["test_control_getter.py"], modules)
    suite = {f"_heldout/{p.name}": p.read_text() for p in heldout_files()}
    m["mut_heldout"] = mutation_scores(_impl_with(files, suite), ["_heldout"], modules, impl_dir_env=True)
    ctx.data["e1"] = m


# ------------------------------------------------------------------ tables
def _verdicts(held: dict) -> dict[str, str]:
    return held["per_clause"]


def run_row(ctx: RunContext) -> dict:
    m, art = ctx.data["e1"], ctx.art
    held = _verdicts(ctx.data["heldout"])
    tick = ticked(art.self_report)
    not_pass = [c for c in CLAUSE_IDS if held[c] != "pass"]
    unreached = [c for c in CLAUSE_IDS if m["reach"][c] == "UNREACHED"]
    gap_set = [c for c in tick if held[c] != "pass"]
    return {
        "run": ctx.run_id, "provider": art.provider, "model": art.model, "seed": ctx.seed,
        "ticked": len(tick),
        "agent_pass": sum(v is True for v in m["agent_pass"].values()),
        "presence": m["presence"], "demo_ok": m["demo"]["ok"],
        "reach_reached": sum(v == "reached" for v in m["reach"].values()),
        "heldout_pass": sum(v == "pass" for v in held.values()),
        "heldout_partial": sum(v == "partial" for v in held.values()),
        "gap": len(tick) - sum(v == "pass" for v in held.values()),
        "gap_state_dependent": sum(c in STATE_DEPENDENT for c in gap_set),
        "gap_notification_only": sum(c in NOTIFICATION_ONLY for c in gap_set),
        "reach_flags_of_gap": (round(len(set(unreached) & set(not_pass)) / len(not_pass), 4) if not_pass else None),
        "fix_iterations": art.fix_iterations, "self_report_overall": art.self_report["overall"],
        "calls": len(art.log.calls), "refused_calls": sum(c.refused for c in art.log.calls),
        "truncated_calls": sum(c.truncated for c in art.log.calls),
        "_deps": ctx.standard_deps(),
    }


def clause_rows(ctx: RunContext) -> list[dict]:
    m, art = ctx.data["e1"], ctx.art
    held = _verdicts(ctx.data["heldout"])
    return [{"run": ctx.run_id, "seed": ctx.seed, "clause": c, "self_report": art.self_report["clauses"][c]["status"],
             "agent_pass": m["agent_pass"][c], "reach": m["reach"][c], "heldout": held[c],
             "state_dependent": c in STATE_DEPENDENT, "notification_only": c in NOTIFICATION_ONLY,
             "_deps": ctx.standard_deps()} for c in CLAUSE_IDS]


def module_rows(ctx: RunContext) -> list[dict]:
    m = ctx.data["e1"]
    held = _verdicts(ctx.data["heldout"])
    tests = ctx.art.final_tests.get("tests", [])
    rows = []
    for mod in SPEC_MODULES:
        cl = MODULE_CLAUSES[mod]
        mine = [t for t in tests if set(t["clauses"]) & set(cl)]
        mut = m["mut_agent"]["modules"].get(f"{mod}.py", {})
        rows.append({
            "run": ctx.run_id, "seed": ctx.seed, "module": mod, "agent_tests": len(mine),
            "agent_pass_rate": round(sum(t["outcome"] == "passed" for t in mine) / len(mine), 4) if mine else None,
            "mutation_score": None if mut.get("score") is None else round(mut["score"], 4),
            "mutants": mut.get("total"), "stillborn": mut.get("stillborn"),
            "heldout_fraction": round(sum(held[c] == "pass" for c in cl) / len(cl), 4),
            "clauses_missing": sum(held[c] == "fail" for c in cl),
            "_deps": ctx.standard_deps(),
        })
    return rows


def control_rows(ctx: RunContext) -> list[dict]:
    m = ctx.data["e1"]
    rows = []
    for control, key in (("tautology", "mut_tautology"), ("getter_only", "mut_getter"), ("heldout", "mut_heldout"),
                         ("agent_tests", "mut_agent")):
        res = m[key]
        base = res["baseline"]
        rate = round(base["passing"] / base["tests"], 4) if base.get("tests") else None
        for mod in SPEC_MODULES:
            mut = res["modules"].get(f"{mod}.py", {})
            rows.append({"run": ctx.run_id, "seed": ctx.seed, "control": control, "module": mod,
                         "suite_tests": base.get("tests"), "suite_pass_rate": rate,
                         "mutation_score": None if mut.get("score") is None else round(mut["score"], 4),
                         "_deps": ctx.standard_deps()})
    return rows


def nullsink_row(ctx: RunContext) -> dict:
    m = ctx.data["e1"]
    held_null = m["null_heldout"]["per_clause"]
    ap_null = agent_pass_by_clause(m["null_tests"])
    failing = [c for c in NOTIFICATION_ONLY if held_null[c] != "pass"]
    return {"run": ctx.run_id, "seed": ctx.seed, "presence_null": m["null_presence"],
            "demo_ok_null": m["null_demo"]["ok"],
            "agent_pass_null": sum(v is True for v in ap_null.values()),
            "notif_clauses_heldout_not_pass_null": len(failing),
            "notif_fail_while_presence_green": len(failing) if m["null_presence"] else 0,
            "notif_fail_while_presence_and_agent_pass_green": sum(1 for c in failing if m["null_presence"] and ap_null[c]),
            "_deps": ctx.standard_deps()}


def e1c_row(ctx: RunContext) -> dict:
    e = ctx.data["e1c"]
    claimed = [k for k, v in e["claimed"].items() if v]
    landed = [k for k, v in e["landed"].items() if v]
    return {"run": ctx.run_id, "seed": ctx.seed, "n_comments": len(e["comments"]),
            "claimed_applied": len(claimed), "verified_landed": len(landed),
            "claimed_but_not_landed": len([k for k in claimed if k not in landed]),
            "_deps": ctx.standard_deps() + ctx.deps("e1c_apply")}


def tables(ctxs: list[RunContext]) -> dict[str, list[dict]]:
    return {
        "e1_done": [run_row(c) for c in ctxs],
        "e1_clauses": [r for c in ctxs for r in clause_rows(c)],
        "e1_modules": [r for c in ctxs for r in module_rows(c)],
        "e1_controls": [r for c in ctxs for r in control_rows(c)],
        "e1b_nullsink": [nullsink_row(c) for c in ctxs],
        "e1c_fixes": [e1c_row(c) for c in ctxs],
    }


# ------------------------------------------------------------------ pre-registered verdicts (live rows only)
def verdicts(live: dict[str, list[dict]]) -> dict[str, dict]:
    runs = live["e1_done"]
    out = {}
    if not runs:
        for part in ("H1a+b", "H1c", "H1d", "E1b", "E1c"):
            out[part] = {"verdict": None, "n": 0}
        return out
    g = median([r["gap"] for r in runs])
    rf = median([r["reach_flags_of_gap"] for r in runs])
    green = sum(bool(r["presence"]) for r in runs) / len(runs)
    if g is not None and g >= 4 and green >= 0.8 and rf is not None and rf >= 0.5:
        v = "reproduces"
    elif g is not None and g <= 1:
        v = "does not reproduce"
    else:
        v = "partial"
    out["H1a+b"] = {"verdict": v, "n": len(runs), "median_gap": g, "median_reach_flags_of_gap": rf,
                    "presence_green_share": round(green, 4),
                    "median_gap_state_dependent": median([r["gap_state_dependent"] for r in runs]),
                    "median_gap_notification_only": median([r["gap_notification_only"] for r in runs])}

    mods = live["e1_modules"]
    xs_pass = [r["agent_pass_rate"] for r in mods]
    xs_mut = [r["mutation_score"] for r in mods]
    ys = [r["heldout_fraction"] for r in mods]
    rho_pass, rho_mut = spearman(xs_pass, ys), spearman(xs_mut, ys)
    getter = [r for r in live["e1_controls"] if r["control"] == "getter_only"]
    getter_med = median([r["mutation_score"] for r in getter])
    getter_full = bool(getter) and all(r["suite_pass_rate"] == 1.0 for r in getter)
    cond_rho = rho_pass is not None and rho_mut is not None and rho_mut - rho_pass >= 0.2
    cond_getter = getter_med is not None and getter_med < 0.3 and getter_full
    # Pre-registration item 5: "reproduces if both conditions hold, does not reproduce otherwise".
    # An undefined rho (e.g. every pass rate identical) means the condition does not hold (A9).
    out["H1c"] = {"verdict": ("reproduces" if cond_rho and cond_getter else "does not reproduce")
                  if mods else "not determinable",
                  "n": sum(1 for a, b in zip(xs_pass, ys) if a is not None and b is not None),
                  "n_mut": sum(1 for a, b in zip(xs_mut, ys) if a is not None and b is not None),
                  "rho_pass": rho_pass, "rho_pass_ci": bootstrap_ci(xs_pass, ys),
                  "rho_mutation": rho_mut, "rho_mutation_ci": bootstrap_ci(xs_mut, ys),
                  "getter_only_median_mutation": getter_med, "getter_only_pass_100": getter_full,
                  "control_medians": {c: median([r["mutation_score"] for r in live["e1_controls"] if r["control"] == c])
                                      for c in ("tautology", "getter_only", "heldout")}}
    missing = [r["mutation_score"] for r in mods if r["clauses_missing"] >= 1 and r["mutation_score"] is not None]
    mm = median(missing)
    out["H1d"] = {"verdict": ("not determinable" if mm is None else ("reproduces" if mm >= 0.6 else "does not reproduce")),
                  "n": len(missing), "median_mutation_missing": mm, "scores": missing}
    nb = live["e1b_nullsink"]
    out["E1b"] = {"verdict": "descriptive", "n": len(nb),
                  "notif_fail_while_presence_green": [r["notif_fail_while_presence_green"] for r in nb],
                  "notif_fail_while_presence_and_agent_pass_green":
                      [r["notif_fail_while_presence_and_agent_pass_green"] for r in nb]}
    fx = live["e1c_fixes"]
    out["E1c"] = {"verdict": "descriptive", "n": len(fx),
                  "claimed_applied": sum(r["claimed_applied"] for r in fx),
                  "verified_landed": sum(r["verified_landed"] for r in fx),
                  "claimed_but_not_landed": sum(r["claimed_but_not_landed"] for r in fx),
                  "comments": sum(r["n_comments"] for r in fx)}
    return out
