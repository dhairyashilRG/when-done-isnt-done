"""Results plumbing: provenance labels, exclusion of synthetic rows, verdict code paths, live-run refusals."""
import csv

import pytest

from repro import orchestrate, report
from repro.estimate import estimate, format_estimate
from repro.experiments import e1_done, e2_vacuous, e3_oracle, e4_gates
from repro.stats import bootstrap_ci, median, spearman


def test_rows_with_any_synthetic_dependency_are_labelled_synthetic():
    rows = [{"a": 1, "_deps": [{"hash": "h1", "origin": "live"}]},
            {"a": 2, "_deps": [{"hash": "h1", "origin": "live"}, {"hash": "h2", "origin": "synthetic"}]},
            {"a": 3, "_deps": []}]
    out = report.label(rows)
    assert [r["provenance"] for r in out] == ["LIVE", "SYNTHETIC", "SYNTHETIC"]
    assert all("_deps" not in r for r in out)


def test_every_verdict_is_not_run_without_live_rows():
    empty = {k: [] for k in ("e1_done", "e1_clauses", "e1_modules", "e1_controls", "e1b_nullsink", "e1c_fixes",
                             "e2_vacuous", "e2_sim_seeds", "e3_parity", "e3_common_mode", "e3_oracle_edits",
                             "e4_gates")}
    for exp in (e1_done, e2_vacuous, e3_oracle, e4_gates):
        for v in exp.verdicts(empty).values():
            assert v["verdict"] is None and v["n"] == 0


def test_stats_helpers():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None and spearman([1, 2], [1, 2]) is None
    lo, hi = bootstrap_ci([1, 2, 3, 4, 5, 6], [1, 3, 2, 5, 4, 6])
    assert -1 <= lo <= hi <= 1
    assert median([3, None, 1, 2]) == 2


def _offline(tmp_path):
    # Plumbing tests use the synthetic set only (brief 1), even when live recordings exist.
    out = orchestrate.run_offline([0], rebuild_synthetic=True, out_dir=tmp_path)
    tables = {}
    for p in tmp_path.glob("*.csv"):
        with p.open() as fh:
            tables[p.stem] = list(csv.DictReader(fh))
    return out, tables


def test_offline_end_to_end_one_seed(tmp_path):
    out, tables = _offline(tmp_path)
    assert set(out["tables"]) >= {"e1_done", "e1_modules", "e1_controls", "e1b_nullsink", "e1c_fixes", "e2_vacuous",
                                  "e2_sim_seeds", "e3_parity", "e3_common_mode", "e3_oracle_edits", "e4_gates"}
    for name, rows in tables.items():
        assert rows and all(r["provenance"] == "SYNTHETIC" for r in rows), name
        assert all(r["recording_set_manifest"] for r in rows)
    summary = (tmp_path / "summary.md").read_text()
    assert "No live recording exists yet" in summary
    assert summary.count("NOT RUN (synthetic only)") >= 8
    assert all(v["verdict"] is None for v in out["verdicts"].values())


def _as_live(rows):
    return [{**r, "_deps": [{"hash": "x", "origin": "live"}]} for r in rows]


def test_verdict_code_paths_run_on_rows_relabelled_live_in_memory_only(tmp_path):
    """Exercises the statistics on plumbing rows relabelled in memory. Nothing here is written as a result."""
    out = orchestrate.run_offline([0, 1, 2], rebuild_synthetic=True, out_dir=tmp_path)
    assert out["tables"]["e1_done"] == 3
    live = {}
    for p in tmp_path.glob("*.csv"):
        with p.open() as fh:
            live[p.stem] = _as_live([_coerce(r) for r in csv.DictReader(fh)])
    v = {}
    for exp in (e1_done, e2_vacuous, e3_oracle, e4_gates):
        v.update(exp.verdicts(live))
    allowed = {"reproduces", "partial", "does not reproduce", "not determinable", "descriptive"}
    assert set(v) == {"H1a+b", "H1c", "H1d", "E1b", "E1c", "E2", "E3", "E4"}
    assert all(x["verdict"] in allowed and (x["n"] > 0 or x["verdict"] == "not determinable") for x in v.values()), v


def _coerce(r):
    out = {}
    for k, v in r.items():
        if v in ("true", "false"):
            out[k] = v == "true"
        elif v == "":
            out[k] = None
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def test_live_run_refusals_never_reach_a_provider(monkeypatch):
    answers = []
    monkeypatch.setattr("builtins.input", lambda *_: answers.append(1) or "n")
    with pytest.raises(PermissionError):
        orchestrate.run_live(6, owner_approved=False, assume_yes=True)
    assert answers == []
    # Declining the confirmation question stops before any provider is built.
    with pytest.raises(SystemExit, match="not started"):
        orchestrate.run_live(5, owner_approved=False, assume_yes=False)
    assert answers == [1]
    # Placeholder prices for a provider in use also refuse.
    from repro.providers import base
    real = base.load_prices()
    fake = {k: base.Price(v.provider, v.model, v.input_usd_per_mtok, v.output_usd_per_mtok, True) for k, v in real.items()}
    monkeypatch.setattr(orchestrate, "load_prices", lambda: fake)
    with pytest.raises(SystemExit, match="placeholder"):
        orchestrate.run_live(5, owner_approved=False, assume_yes=True)


def test_estimate_prints_per_experiment_and_total_without_calling():
    est = estimate()
    assert set(est["per_experiment"]) == {"E1", "E2", "E3", "E4"} and est["total_usd"] > 0
    text = format_estimate(est)
    assert "Total" in text and "nothing has been called" in text


def test_config_default_r_ind_is_same_provider_fresh_conversation():
    assert orchestrate.config()["r_ind_provider"] == "same"
