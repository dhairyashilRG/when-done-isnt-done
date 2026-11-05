"""Live cost estimate (brief 5): calls x (estimated input + max_tokens) x price. Calls nothing."""
from __future__ import annotations

from .agent.pipeline import MAX_TOKENS
from .providers.base import load_price_table, load_prices

# (experiment, stage, template, estimated new input tokens added by this stage's prompt,
#  typical answer length used to grow the conversation). The fix loop is counted at its maximum.
PLAN = [
    ("E1", "implement", "implement", 3700, 9000),
    ("E1", "test", "test", 100, 4000),
    ("E1", "fix1", "fix", 600, 6000),
    ("E1", "fix2", "fix", 600, 6000),
    ("E1", "demo", "demo", 50, 800),
    ("E1", "self_report", "self_report", 150, 1500),
    ("E1", "e1c_apply", "apply_review", 500, 6000),
    ("E3", "e3_rdep", "reference_dep", 60, 6000),
    ("E3", "e3_resolve1", "resolve_mismatch", 400, 4000),
    ("E3", "e3_resolve2", "resolve_mismatch", 400, 4000),
    ("E3", "e3_resolve3", "resolve_mismatch", 400, 4000),
]
FRESH = [  # calls in fresh conversations: (experiment, stage, template, input tokens)
    ("E3", "e3_rind", "reference_ind", 3700, 6000),
    ("E2", "base v1-6", "validators", 3600, 2500), ("E2", "base v7-9", "validators_later", 1600, 1500),
    ("E2", "checklist v1-6", "validators", 3600, 2500), ("E2", "checklist v7-9", "validators_later", 1600, 1500),
    ("E2", "guard v1-6", "validators", 4300, 2500), ("E2", "guard v7-9", "validators_later", 2300, 1500),
]
SYSTEM_TOKENS = 200


def per_run_calls() -> list[dict]:
    calls, context = [], SYSTEM_TOKENS
    e1c_context = None
    for exp, stage, tmpl, added, answer in PLAN:
        if stage == "e3_rdep":  # E1c ran in a fork; E3 continues from the self-report point
            context = e1c_context
        context += added
        calls.append({"experiment": exp, "stage": stage, "input": context, "max_tokens": MAX_TOKENS[tmpl],
                      "typical_output": answer})
        if stage == "self_report":
            e1c_context = context + answer
        context += answer
    for exp, stage, tmpl, inp, answer in FRESH:
        calls.append({"experiment": exp, "stage": stage, "input": SYSTEM_TOKENS + inp, "max_tokens": MAX_TOKENS[tmpl],
                      "typical_output": answer})
    return calls


def estimate(seeds=(0, 1, 2, 3, 4), providers=("anthropic",)) -> dict:
    prices = load_prices()
    per_exp: dict[str, dict] = {}
    for name in providers:
        p = prices[name]
        scale = int(load_price_table()[name].get("max_tokens_scale", 1))  # amendment A12
        for c in per_run_calls():
            cost = (c["input"] * p.input_usd_per_mtok + c["max_tokens"] * scale * p.output_usd_per_mtok) / 1e6
            typical = (c["input"] * p.input_usd_per_mtok + c["typical_output"] * p.output_usd_per_mtok) / 1e6
            e = per_exp.setdefault(c["experiment"], {"calls": 0, "usd": 0.0, "typical_usd": 0.0})
            e["calls"] += len(seeds)
            e["usd"] += cost * len(seeds)
            e["typical_usd"] += typical * len(seeds)
    per_exp.setdefault("E4", {"calls": 0, "usd": 0.0, "typical_usd": 0.0})
    return {"per_experiment": dict(sorted(per_exp.items())), "total_usd": sum(e["usd"] for e in per_exp.values()),
            "typical_total_usd": sum(e["typical_usd"] for e in per_exp.values()),
            "total_calls": sum(e["calls"] for e in per_exp.values()), "seeds": list(seeds),
            "providers": list(providers), "placeholder": any(prices[n].placeholder for n in providers)}


def format_estimate(est: dict) -> str:
    lines = ["Estimated cost of a live recording (nothing has been called)", ""]
    if est["placeholder"]:
        lines += ["WARNING: the prices in providers/prices.toml are PLACEHOLDERS. The operator must fill in real",
                  "prices and model ids before these numbers mean anything, and before a live run will start.", ""]
    lines += [f"Providers: {', '.join(est['providers'])}. Agent seeds: {est['seeds']}.",
              "Method: for every planned call, (estimated input tokens x input price) + (the call's maximum output",
              "tokens x output price). Using the maximum output makes this an upper-end estimate. The fix loop",
              "and the mismatch-resolving step are counted at their maximum number of calls.", "",
              "The 'typical' column instead assumes answers of a usual length, for comparison.", "",
              f"{'Experiment':<12}{'calls':>7}{'estimate (USD)':>18}{'typical (USD)':>16}"]
    for exp, e in est["per_experiment"].items():
        note = "  (reuses E1's runs; no extra calls)" if exp == "E4" else ""
        lines.append(f"{exp:<12}{e['calls']:>7}{e['usd']:>18.2f}{e['typical_usd']:>16.2f}{note}")
    lines += [f"{'Total':<12}{est['total_calls']:>7}{est['total_usd']:>18.2f}{est['typical_total_usd']:>16.2f}", "",
              "A live run enforces a hard cap: before each call it checks that the worst case for that call",
              "(input plus maximum output, all at the output price) still fits in the budget, and stops cleanly",
              "if not. Budgets above $5 also need --owner-approved-budget."]
    return "\n".join(lines)
