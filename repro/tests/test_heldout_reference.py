"""The held-out suite passes 100% against the harness author's hand reference (task step 4)."""
from collections import Counter

from repro.oracle.runner import clause_verdicts, heldout_sha256, reference_files, run_heldout
from repro.spec import CLAUSE_IDS


def test_heldout_passes_100_percent_against_reference_hand():
    r = run_heldout(reference_files())
    failures = [(t["nodeid"], t["message"]) for t in r["tests"] if t["outcome"] != "passed"]
    assert failures == []
    assert r["n_tests"] == r["n_passed"] >= 128
    assert set(r["per_clause"].values()) == {"pass"}


def test_heldout_has_3_to_6_tests_per_clause():
    r = run_heldout(reference_files())
    base = {(t["nodeid"].split("[")[0], tuple(t["clauses"])) for t in r["tests"]}  # parameters folded
    per_clause = Counter(c for _, clauses in base for c in clauses)
    assert set(per_clause) == set(CLAUSE_IDS)
    assert all(3 <= n <= 6 for n in per_clause.values()), per_clause
    assert 120 <= sum(per_clause.values()) <= 140


def test_clause_verdicts_pass_partial_fail():
    tests = [{"clauses": ["C01"], "outcome": "passed"}, {"clauses": ["C01"], "outcome": "passed"},
             {"clauses": ["C02"], "outcome": "passed"}, {"clauses": ["C02"], "outcome": "failed"},
             {"clauses": ["C03"], "outcome": "failed"}]
    v = clause_verdicts(tests, ["C01", "C02", "C03", "C04"])
    assert v == {"C01": "pass", "C02": "partial", "C03": "fail", "C04": "fail"}


def test_heldout_hash_is_stable():
    assert heldout_sha256() == heldout_sha256()
    assert len(heldout_sha256()) == 64


def test_heldout_hash_matches_preregistration():
    from repro.report import RESULTS_DIR
    assert heldout_sha256() in (RESULTS_DIR / "PREREGISTRATION.md").read_text()
