"""Runs the pipeline and the four experiments, offline (replay) or live (record), and writes results."""
from __future__ import annotations

import os
import shutil
import sys
import time
import tomllib
from pathlib import Path

from . import report
from .agent.pipeline import TEMPERATURE, Slot, run_standard
from .experiments import e1_done, e2_vacuous, e3_oracle, e4_gates
from .experiments.common import RunContext
from .providers.base import Budget, BudgetExceeded, ReplayMiss, chars_per_token_lower_bound, load_price_table, \
    load_prices, validate_budget
from .providers.mock import MockProvider, load_recordings, manifest
from .providers.record import RecordingProvider

PKG = Path(__file__).resolve().parent
LIVE_DIR = PKG / "recordings"
SYNTHETIC_DIR = PKG / "tests" / "fixtures" / "synthetic" / "recordings"
# Tables built from the hand-written plumbing responses never go to results/ (amendment A13).
SYNTHETIC_RESULTS_DIR = PKG / "tests" / "fixtures" / "synthetic" / "results"
SYNTHETIC_MODEL = "synthetic-plumbing"
EXPERIMENTS = [e1_done, e2_vacuous, e3_oracle, e4_gates]


def config() -> dict:
    with (PKG / "config.toml").open("rb") as fh:
        return tomllib.load(fh)["run"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _collect(slot: Slot, seed: int, r_ind_slot: Slot) -> RunContext:
    run_id = f"{slot.name}/s{seed}"
    art = run_standard(slot, seed, run_id)
    ctx = RunContext(run_id, slot, seed, r_ind_slot, art)
    e1_done.collect(ctx)
    e3_oracle.collect(ctx)
    e2_vacuous.collect(ctx)
    return ctx


def _measure(ctx: RunContext) -> None:
    for exp in (e1_done, e2_vacuous, e3_oracle, e4_gates):
        if hasattr(exp, "measure"):
            exp.measure(ctx)


def collect_all(slots: list[Slot], seeds: list[int], r_ind_for, measure: bool) -> tuple[list[RunContext], bool]:
    """Returns (contexts, incomplete). A budget stop ends collection cleanly."""
    ctxs, incomplete = [], False
    for slot in slots:
        for seed in seeds:
            t = time.monotonic()
            try:
                ctx = _collect(slot, seed, r_ind_for(slot))
            except BudgetExceeded as exc:
                log(f"budget cap reached, stopping cleanly: {exc}")
                return ctxs, True
            if measure:
                _measure(ctx)
            ctxs.append(ctx)
            log(f"  run {ctx.run_id}: {time.monotonic() - t:.1f}s")
    return ctxs, incomplete


# ------------------------------------------------------------------ synthetic plumbing set
def build_synthetic(seeds: list[int]) -> dict:
    from .tests.fixtures.synthetic.provider import SyntheticProvider
    if SYNTHETIC_DIR.exists():
        shutil.rmtree(SYNTHETIC_DIR)
    rec = RecordingProvider(SyntheticProvider(), SYNTHETIC_DIR, clock=lambda: "1970-01-01T00:00:00+00:00",
                            require_origin="synthetic")
    slot = Slot(rec, "synthetic", SYNTHETIC_MODEL)
    log(f"building the synthetic plumbing recording set ({len(seeds)} seeds) ...")
    collect_all([slot], seeds, lambda s: s, measure=False)
    return manifest(SYNTHETIC_DIR)


def _live_records_present(rec_dir: Path = LIVE_DIR) -> bool:
    return any(p.suffix == ".json" and p.name != "manifest.json" for p in rec_dir.glob("*.json"))


def model_set(provider: str | None) -> tuple[list[str], Path, Path]:
    """(implementers, recordings folder, results folder). The configured implementers use recordings/ and
    results/; any other provider (`--provider`) gets its own folders, so adding a model never changes the
    main result set (amendment A11)."""
    if provider is None or provider in config()["implementers"]:
        return config()["implementers"], LIVE_DIR, report.RESULTS_DIR
    return [provider], LIVE_DIR / provider, PKG / "results_by_model" / provider


def is_anthropic(table: dict, name: str) -> bool:
    return name == "anthropic" or table[name].get("kind") == "anthropic"


def _slots_from_config(provider_factory, implementers: list[str] | None = None) -> tuple[list[Slot], callable]:
    cfg = config()
    table = load_price_table()
    def temp(name):  # the Anthropic API rejects temperature; others get brief 5's 0.7
        return None if is_anthropic(table, name) else TEMPERATURE

    def slot(name):
        return Slot(provider_factory(name), name, table[name]["model"], temp(name),
                    int(table[name].get("max_tokens_scale", 1)))

    slots = [slot(name) for name in (implementers or cfg["implementers"])]
    by_name = {s.name: s for s in slots}
    choice = cfg.get("r_ind_provider", "same")

    def r_ind_for(slot):
        if choice == "same":
            return slot
        if choice not in by_name:
            by_name[choice] = slot(choice)
        return by_name[choice]
    return slots, r_ind_for


# ------------------------------------------------------------------ offline
def run_offline(seeds: list[int] | None = None, rebuild_synthetic: bool = False, out_dir: Path | None = None,
                provider: str | None = None) -> dict:
    started = time.monotonic()
    seeds = seeds if seeds is not None else config()["agent_seeds"]
    implementers, rec_dir, results_dir = model_set(provider)
    if provider is not None and not _live_records_present(rec_dir):
        raise SystemExit(f"no live recordings for provider '{provider}' in {rec_dir}")
    if _live_records_present(rec_dir) and not rebuild_synthetic:
        records = load_recordings(rec_dir)
        if any(r["provenance"]["origin"] != "live" for r in records.values()):
            raise SystemExit("recordings/ holds a non-live recording; the live set must be live only")
        replay = MockProvider(records=records)
        slots, r_ind_for = _slots_from_config(lambda name: replay, implementers)
        set_name, set_dir = "live", rec_dir
        out_dir = out_dir or results_dir
    else:
        if rebuild_synthetic or not any(SYNTHETIC_DIR.glob("*.json")):
            build_synthetic(seeds)
        set_name, set_dir = "synthetic", SYNTHETIC_DIR
        slots = [Slot(MockProvider(SYNTHETIC_DIR), "synthetic", SYNTHETIC_MODEL)]
        r_ind_for = lambda s: s  # noqa: E731
        out_dir = out_dir or SYNTHETIC_RESULTS_DIR
    log(f"replaying the {set_name} recording set ...")
    try:
        ctxs, incomplete = collect_all(slots, seeds, r_ind_for, measure=True)
    except ReplayMiss as exc:
        if set_name == "synthetic" and not rebuild_synthetic:
            log(f"{exc}\n-> the synthetic set is stale; rebuilding it")
            return run_offline(seeds, rebuild_synthetic=True, out_dir=out_dir)
        raise
    man = manifest(set_dir)
    return report.write_all(ctxs, EXPERIMENTS, recording_set=set_name, manifest=man, incomplete=incomplete,
                            seeds=seeds, runtime_s=time.monotonic() - started, out_dir=out_dir)


# ------------------------------------------------------------------ live (never run by this build)
def run_live(budget_usd: float, owner_approved: bool, assume_yes: bool, seeds: list[int] | None = None,
             provider: str | None = None) -> dict:
    from .estimate import estimate, format_estimate
    from .providers.anthropic import AnthropicProvider
    from .providers.openai_compat import OpenAICompatProvider

    validate_budget(budget_usd, owner_approved)
    cfg = config()
    seeds = seeds if seeds is not None else cfg["agent_seeds"]
    prices, table = load_prices(), load_price_table()
    implementers, rec_dir, results_dir = model_set(provider)
    used = set(implementers) | ({cfg["r_ind_provider"]} - {"same"})
    placeholders = [n for n in used if prices[n].placeholder]
    if placeholders:
        raise SystemExit(f"refusing to start: prices.toml still has placeholder prices for {placeholders} "
                         "(the operator must fill them and set placeholder = false)")
    est = estimate(seeds=seeds, providers=implementers)
    print(format_estimate(est))
    if est["total_usd"] > budget_usd:
        print(f"Note: the estimate is above the budget of ${budget_usd:.2f}; the run will stop when the cap is reached "
              "and mark its results INCOMPLETE.")
    if not assume_yes and input(f"Start live recording with a hard cap of ${budget_usd:.2f}? [y/N] ").strip().lower() != "y":
        raise SystemExit("not started")
    budget = Budget(budget_usd)
    divisor = chars_per_token_lower_bound()

    def factory(name):
        t = table[name]
        inner = (AnthropicProvider(prices[name], base_url=t.get("base_url") or None)
                 if is_anthropic(table, name) else
                 OpenAICompatProvider(prices[name], base_url=t["base_url"], api_key_env=t["api_key_env"]))
        return RecordingProvider(inner, rec_dir, budget=budget, price=prices[name], chars_per_token=divisor,
                                 require_origin="live")

    os.environ["REPRO_ALLOW_LIVE"] = "1"
    started = time.monotonic()
    try:
        slots, r_ind_for = _slots_from_config(factory, implementers)
        ctxs, incomplete = collect_all(slots, seeds, r_ind_for, measure=True)
    finally:
        os.environ.pop("REPRO_ALLOW_LIVE", None)
    log(f"spent ${budget.spent_usd:.4f} in {budget.calls} calls")
    return report.write_all(ctxs, EXPERIMENTS, recording_set="live", manifest=manifest(rec_dir), incomplete=incomplete,
                            seeds=seeds, runtime_s=time.monotonic() - started, out_dir=results_dir)
