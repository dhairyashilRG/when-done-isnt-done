"""E3: an independent reference as oracle, and common-mode failure (brief 4, E3)."""
from __future__ import annotations

from ..agent.pipeline import IMPL_MODULES, base_repo_files, impl_only, resolve_mismatch, write_reference_dep, \
    write_reference_ind
from ..checks.parity import DRIVER_AS_RECORDED, E3_SEEDS, ParityCheck, compare, diff_text, run_traces
from ..checks.probe import ACCEPTABLE, probe
from ..oracle.runner import reference_files, run_heldout
from ..spec import CLAUSE_IDS
from .common import RunContext

MAX_RESOLVE = 3
PAIRS = [("impl", "R_dep"), ("impl", "R_ind"), ("impl", "R_hand"), ("R_dep", "R_hand"), ("R_ind", "R_hand")]


def _ref_dir(files: dict[str, str]) -> dict[str, str]:
    out = base_repo_files()
    out.update(files)
    return out


def collect(ctx: RunContext) -> None:
    art = ctx.art
    impl = impl_only(art.files)
    rdep_files, _ = write_reference_dep(art.conversation)
    rind_files, _ = write_reference_ind(ctx.r_ind_slot, ctx.seed, ctx.run_id, art.log)
    rdep, rind = _ref_dir(rdep_files), _ref_dir(rind_files)
    ctx.data["e3"] = {"impl": impl, "R_dep": rdep, "R_ind": rind, "r_ind_provider": ctx.r_ind_slot.name,
                      "r_ind_same_provider": ctx.r_ind_slot.name == ctx.slot.name, "edits": []}
    # Oracle editing: show the agent each impl/R_dep disagreement and record what it changes.
    # This stage uses the original comparison (DRIVER_AS_RECORDED): the live recording showed the agent
    # mismatches found by it, and replaying the recorded calls needs the same prompts (amendment A6).
    cur_impl, cur_rdep = dict(impl), dict(rdep)
    for k in range(1, MAX_RESOLVE + 1):
        cmp = compare(run_traces(cur_impl, driver=DRIVER_AS_RECORDED), run_traces(cur_rdep, driver=DRIVER_AS_RECORDED))
        if cmp["seeds_agree"] == cmp["n_seeds"]:
            break
        first = cmp["first_divergence_seed"]
        one = {"per_seed": {first: cmp["per_seed"][first]}} if first is not None else cmp
        text = diff_text(one, "impl", "reference.py", limit=1) or "(the traces differ before the first step)"
        changed, _ = resolve_mismatch(art.conversation, text, k)
        impl_changed = sorted(p for p in changed if p in IMPL_MODULES or (p.endswith(".py") and p != "reference.py"
                                                                           and not p.startswith("test_")
                                                                           and p != "demo.py"))
        rdep_changed = sorted(p for p in changed if p == "reference.py")
        kind = {(True, True): "both", (True, False): "impl", (False, True): "R_dep", (False, False): "neither"}[
            (bool(impl_changed), bool(rdep_changed))]
        ctx.data["e3"]["edits"].append({"k": k, "seed": first, "clause": cmp["first_divergence_clause"],
                                        "changed": kind, "files": sorted(changed)})
        for p in impl_changed:
            cur_impl[p] = changed[p]
        for p in rdep_changed:
            cur_rdep[p] = changed[p]


def measure(ctx: RunContext) -> None:
    e = ctx.data["e3"]
    impls = {"impl": e["impl"], "R_dep": e["R_dep"], "R_ind": e["R_ind"], "R_hand": reference_files()}
    traces = {k: run_traces(v) for k, v in impls.items()}
    e["parity"] = {f"{a}-{b}": compare(traces[a], traces[b]) for a, b in PAIRS}
    e["probe"] = {k: probe(v) for k, v in impls.items()}
    e["heldout"] = {k: run_heldout(v) for k, v in impls.items() if k != "R_hand"}


def _outcomes(held: dict, clause: str) -> tuple:
    return tuple(sorted((t["nodeid"], t["outcome"]) for t in held["tests"] if clause in t["clauses"]))


def tables(ctxs: list[RunContext]) -> dict[str, list[dict]]:
    parity, common, edits = [], [], []
    for ctx in ctxs:
        e = ctx.data["e3"]
        deps = ctx.standard_deps() + ctx.deps("e3_rdep", "e3_rind")
        for a, b in PAIRS:
            cmp = e["parity"][f"{a}-{b}"]
            parity.append({"run": ctx.run_id, "seed": ctx.seed, "pair": f"{a}-{b}", "seeds_agree": cmp["seeds_agree"],
                           "n_seeds": cmp["n_seeds"], "first_divergence_clause": cmp["first_divergence_clause"],
                           "parity_check": ParityCheck().run(
                               [(cmp["per_seed"][s].get("agree"), True) for s in E3_SEEDS]).passed,
                           "r_ind_provider": e["r_ind_provider"], "_deps": deps})
        pr = e["probe"]
        for d in ("D1", "D2"):
            ci, cd, cn, ch = pr["impl"].get(d), pr["R_dep"].get(d), pr["R_ind"].get(d), pr["R_hand"].get(d)
            common.append({"run": ctx.run_id, "seed": ctx.seed, "item": d, "impl": ci, "R_dep": cd, "R_ind": cn,
                           "R_hand": ch, "impl_matches_R_dep": ci == cd,
                           "impl_matches_R_hand": ci in ACCEPTABLE[d],
                           "R_ind_matches_R_hand": cn in ACCEPTABLE[d],
                           "common_mode_R_dep": ci == cd and ci not in ACCEPTABLE[d],
                           "common_mode_R_ind": ci == cn and ci not in ACCEPTABLE[d], "_deps": deps})
        held = e["heldout"]
        for c in CLAUSE_IDS:
            oi, od, on = (_outcomes(held[k], c) for k in ("impl", "R_dep", "R_ind"))
            all_pass_i = all(o == "passed" for _, o in oi)
            common.append({"run": ctx.run_id, "seed": ctx.seed, "item": c, "impl": held["impl"]["per_clause"][c],
                           "R_dep": held["R_dep"]["per_clause"][c], "R_ind": held["R_ind"]["per_clause"][c],
                           "R_hand": "pass", "impl_matches_R_dep": oi == od, "impl_matches_R_hand": all_pass_i,
                           "R_ind_matches_R_hand": all(o == "passed" for _, o in on),
                           "common_mode_R_dep": oi == od and not all_pass_i,
                           "common_mode_R_ind": oi == on and not all_pass_i, "_deps": deps})
        for ed in e["edits"]:
            # Does the spec-only comparison (A6) still see the mismatch the agent was shown?
            still = e["parity"]["impl-R_dep"]["per_seed"].get(ed["seed"], {}).get("agree") is False
            edits.append({"run": ctx.run_id, "seed": ctx.seed, "k": ed["k"], "sequence_seed": ed["seed"],
                          "clause": ed["clause"], "changed": ed["changed"], "files": " ".join(ed["files"]),
                          "mismatch_seen_by_spec_only_comparison": still,
                          "_deps": deps + ctx.deps(f"e3_resolve{ed['k']}")})
    return {"e3_parity": parity, "e3_common_mode": common, "e3_oracle_edits": edits}


def verdicts(live: dict[str, list[dict]]) -> dict[str, dict]:
    par = live["e3_parity"]
    if not par:
        return {"E3": {"verdict": None, "n": 0}}

    def disagreement(pair):
        rows = [r for r in par if r["pair"] == pair]
        return round(1 - sum(r["seeds_agree"] / r["n_seeds"] for r in rows) / len(rows), 4) if rows else None

    cm = [r for r in live["e3_common_mode"] if r["item"] in ("D1", "D2")]
    runs = sorted({r["run"] for r in cm})
    cm_dep = sum(any(r["common_mode_R_dep"] for r in cm if r["run"] == run) for run in runs) / len(runs) if runs else None
    cm_ind = sum(any(r["common_mode_R_ind"] for r in cm if r["run"] == run) for run in runs) / len(runs) if runs else None
    d_dep, d_ind = disagreement("impl-R_dep"), disagreement("impl-R_ind")
    if cm_dep is None:
        v = "not determinable"
    elif cm_dep <= cm_ind:
        v = "does not reproduce"
    elif d_dep < d_ind and cm_dep >= 0.5 and cm_ind < cm_dep:
        v = "reproduces"
    else:
        v = "partial"
    edits = live["e3_oracle_edits"]
    return {"E3": {"verdict": v, "n": len(runs), "disagreement_impl_R_dep": d_dep, "disagreement_impl_R_ind": d_ind,
                   "disagreement_all": {p: disagreement(p) for p in sorted({r["pair"] for r in par})},
                   "common_mode_rate_R_dep": cm_dep, "common_mode_rate_R_ind": cm_ind,
                   "oracle_edits": {k: sum(e["changed"] == k for e in edits) for k in ("impl", "R_dep", "both", "neither")},
                   "oracle_edits_on_mismatch_not_seen_by_spec_only_comparison":
                       sum(e.get("mismatch_seen_by_spec_only_comparison") is False for e in edits)}}
