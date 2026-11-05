"""The harness's own checks: each fails on empty input (brief 3), and each works on real input."""
import ast

import pytest

from repro.checks import mutation
from repro.checks.empty_guard import Check, CheckResult, is_empty
from repro.checks.mutation import MutationCheck, apply, mutation_scores, points, sample_mutants
from repro.checks.parity import ParityCheck, compare, run_traces
from repro.checks.presence import PresenceCheck, defined_names
from repro.checks.reach import CLAUSE_OBSERVABLES, ReachCheck, reach_verdicts
from repro.oracle.runner import reference_files
from repro.spec import CLAUSE_IDS

EMPTIES = [None, [], {}, (), set(), [None], {"a": None}, [[], {}], iter(())]


class Always(Check):
    def check(self, items):
        return True, len(items)


@pytest.mark.parametrize("empty", EMPTIES, ids=repr)
def test_guard_fails_empty_before_calling_subclass(empty):
    called = []

    class Spy(Check):
        def check(self, items):
            called.append(items)
            return True, 1

    r = Spy().run(empty)
    assert r.passed is False and r.reason == "failed: empty input" and called == []


def test_guard_fails_when_nothing_measured_and_on_crash():
    class Nothing(Check):
        def check(self, items):
            return True, []

    class Crash(Check):
        def check(self, items):
            raise ZeroDivisionError

    assert Nothing().run([1]).reason == "failed: nothing measured"
    assert Crash().run([1]).passed is False
    assert Always().run([1, 2]).passed is True


def test_is_empty_and_result_unpacking():
    assert is_empty([None, {"x": None}]) and not is_empty([0]) and not is_empty({"a": 1})
    passed, measured = CheckResult(True, 3)
    assert (passed, measured) == (True, 3)


@pytest.mark.parametrize("check", [PresenceCheck(), ReachCheck(), ParityCheck(), MutationCheck()],
                         ids=lambda c: c.name)
@pytest.mark.parametrize("empty", [None, [], {}, ()], ids=repr)
def test_every_harness_check_fails_on_empty_input(check, empty):
    assert check.run(empty).passed is False


def test_presence_on_reference_and_missing_names():
    files = {"inventory.py": reference_files()["reference_hand.py"]}
    assert PresenceCheck().run({"files": files, "demo_ok": True}).passed
    assert not PresenceCheck().run({"files": files, "demo_ok": False}).passed
    r = PresenceCheck().run({"files": {"inventory.py": "def receive(): pass\n"}, "demo_ok": True})
    assert not r.passed and "ship" in r.measured["missing"]
    assert PresenceCheck().run({"files": {}, "demo_ok": True}).passed is False
    assert "Depot" in defined_names(files)


def test_reach_map_covers_every_clause_and_unreached_fails():
    assert set(CLAUSE_OBSERVABLES) == set(CLAUSE_IDS)
    everything = {o for obs in CLAUSE_OBSERVABLES.values() for o in obs}
    assert ReachCheck().run(everything).passed
    partial = everything - {"notif:EXPIRY"}
    r = ReachCheck().run(partial)
    assert not r.passed and r.measured["C13"] == "UNREACHED" and r.measured["C01"] == "reached"
    assert set(reach_verdicts([]).values()) == {"UNREACHED"}


def test_parity_check_on_pairs():
    assert ParityCheck().run([(1, 1), (2, 2)]).passed
    assert not ParityCheck().run([(1, 1), (2, 3)]).passed
    assert not ParityCheck().run([(None, None)]).passed


def test_differential_reference_agrees_with_itself_and_flags_d1():
    ref = reference_files()
    a = run_traces(ref, seeds=[100, 101], n_ops=60)
    assert compare(a, a, seeds=[100, 101])["seeds_agree"] == 2
    credit = dict(ref)
    credit["reference_hand.py"] = ref["reference_hand.py"].replace(
        'self._s["cash"] -= cost\n            self._rearm(sku, to_wh)',
        'self._s["cash"] += cost\n            self._rearm(sku, to_wh)')
    b = run_traces(credit, seeds=[100, 101], n_ops=60)
    c = compare(a, b, seeds=[100, 101])
    assert c["seeds_agree"] < 2 and c["first_divergence_clause"] == "C11"


SRC = '''
def f(a, b, items=[1, 2]):
    """doc"""
    if a < b and a > 0:
        x = 1
        return max(a, b)
    if not a:
        raise ValueError("no")
    flag = True
    return {"k": 1}
'''


def test_every_operator_applies_and_compiles():
    pts = points(SRC)
    ops = {p[0] for p in pts}
    assert ops == set(mutation.OPERATORS)
    for p in pts:
        out = apply(SRC, p)
        compile(out, "m.py", "exec")
        assert ast.dump(ast.parse(out)) != ast.dump(ast.parse(SRC))


def test_sampling_is_deterministic_and_capped():
    a = sample_mutants("m.py", SRC, cap=5, seed=7)
    b = sample_mutants("m.py", SRC, cap=5, seed=7)
    assert [m["id"] for m in a] == [m["id"] for m in b] and len(a) == 5
    assert [m["id"] for m in sample_mutants("m.py", SRC, cap=5, seed=8)] != [m["id"] for m in a]


def test_mutation_score_scenarios():
    mod = "def clamp(x):\n    if x > 5:\n        return 5\n    if x < 0:\n        return 0\n    return x\n"
    good = "from m import clamp\n\ndef test_c():\n    assert clamp(9) == 5\n    assert clamp(-1) == 0\n    assert clamp(3) == 3\n"
    taut = "def test_t():\n    assert True\n"
    r = mutation_scores({"m.py": mod, "test_m.py": good}, ["test_m.py"], ["m.py"], cap=60)
    assert r["modules"]["m.py"]["score"] >= 0.7
    t = mutation_scores({"m.py": mod, "test_m.py": taut}, ["test_m.py"], ["m.py"], cap=60)
    assert t["modules"]["m.py"]["score"] == 0.0
    bad = "def test_b():\n    assert False\n"
    nb = mutation_scores({"m.py": mod, "test_m.py": bad}, ["test_m.py"], ["m.py"], cap=60)
    assert nb["modules"]["m.py"]["score"] is None and "no passing baseline" in nb["baseline"]["error"]


def test_mutation_timeout_counts_as_killed_and_stillborn_excluded():
    mod = "def spin(n):\n    i = 0\n    while i < n:\n        i += 1\n    return i\n"
    test = "from m import spin\n\ndef test_s():\n    assert spin(3) == 3\n"
    r = mutation_scores({"m.py": mod, "test_m.py": test}, ["test_m.py"], ["m.py"], cap=60, max_timeout=5.0)
    m = r["modules"]["m.py"]
    assert m["timeout"] >= 1 and m["score"] == pytest.approx((m["killed"] + m["timeout"]) / (m["total"] - m["stillborn"]))
    boom = "X = 1\nif X == 1:\n    pass\nelse:\n    raise SystemExit\n"
    t2 = "import m\n\ndef test_x():\n    assert m.X == 1\n"
    r2 = mutation_scores({"m.py": boom, "test_m.py": t2}, ["test_m.py"], ["m.py"], cap=60)
    assert r2["modules"]["m.py"]["stillborn"] >= 1


# ------------------------------------------------------------------ amendment A6: compare only what the spec pins down
def _hand_variant(old: str, new: str) -> dict:
    ref = reference_files()
    assert ref["reference_hand.py"].count(old) == 1, old
    out = dict(ref)
    out["reference_hand.py"] = ref["reference_hand.py"].replace(old, new)
    return out


SEEDS = [100, 101, 102, 103]
UNKNOWN_SUPPLIER = '''        if supplier not in self._s["suppliers"]:
            raise DepotError("UNKNOWN_SUPPLIER")
        return self._s["suppliers"][supplier]'''


@pytest.mark.parametrize("old,new", [
    # reliability() of a supplier that has no order yet: the spec says nothing about it
    (UNKNOWN_SUPPLIER, UNKNOWN_SUPPLIER.replace('raise DepotError("UNKNOWN_SUPPLIER")', "return 3")),
    # simulate: other (still seeded, in-range) orders; C29 pins only determinism per seed
    ("    rng = random.Random(seed)\n", "    rng = random.Random(seed * 7919 + 17)\n"),
    # an error code the spec does not name
    ('raise DepotError("ALREADY_DELIVERED")', 'raise DepotError("ORDER_ALREADY_DONE")'),
], ids=["unknown-supplier", "other-sim-orders", "unnamed-error-code"])
def test_spec_only_comparison_ignores_what_the_spec_leaves_open(old, new):
    from repro.checks.parity import DRIVER_AS_RECORDED
    ref, variant = reference_files(), _hand_variant(old, new)
    a, b = run_traces(ref, seeds=SEEDS, n_ops=200), run_traces(variant, seeds=SEEDS, n_ops=200)
    assert compare(a, b, seeds=SEEDS)["seeds_agree"] == len(SEEDS)
    # the original driver counted these differences as disagreement
    a1 = run_traces(ref, seeds=SEEDS, n_ops=200, driver=DRIVER_AS_RECORDED)
    b1 = run_traces(variant, seeds=SEEDS, n_ops=200, driver=DRIVER_AS_RECORDED)
    assert compare(a1, b1, seeds=SEEDS)["seeds_agree"] < len(SEEDS)


def test_spec_only_comparison_still_flags_what_the_spec_pins_down():
    ref = reference_files()
    same_every_seed = _hand_variant("    rng = random.Random(seed)\n", "    rng = random.Random(0)\n")
    c = compare(run_traces(ref, seeds=SEEDS), run_traces(same_every_seed, seeds=SEEDS), seeds=SEEDS)
    assert c["seeds_agree"] < len(SEEDS) and c["first_divergence_clause"] == "C29"
    out_of_range = _hand_variant('rng.randint(demand[sku]["min"], demand[sku]["max"])',
                                 'rng.randint(demand[sku]["min"], demand[sku]["max"] + 50)')
    c = compare(run_traces(ref, seeds=SEEDS), run_traces(out_of_range, seeds=SEEDS), seeds=SEEDS)
    assert c["seeds_agree"] < len(SEEDS)
    named = _hand_variant('raise DepotError("UNDO_BLOCKED")', 'raise DepotError("BLOCKED")')
    c = compare(run_traces(ref, seeds=SEEDS), run_traces(named, seeds=SEEDS), seeds=SEEDS)
    assert c["seeds_agree"] < len(SEEDS)


def test_driver_records_decimal_results_by_value():
    import importlib.util
    from decimal import Decimal
    from fractions import Fraction
    from repro.checks.parity import DRIVER
    spec = importlib.util.spec_from_file_location("diff_driver_under_test", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._norm(Decimal("0")) == mod._norm(0.0) == 0.0
    assert mod._norm([Decimal("1.5"), Fraction(1, 4)]) == [1.5, 0.25]


# ------------------------------------------------------------------ amendment A7: gate probes use the implementation's defaults
def _probe_variant(old: str, new: str) -> dict:
    from repro.checks.probe import probe
    files = _hand_variant(old, new) if old else reference_files()
    return probe(files)


HAND_INIT = "late_penalty_pct, perishable_return_policy, data: dict | None = None):"


UNDECIDED_DEFAULTS = '''
class DepotError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Depot:
    def __init__(self, warehouses, capacities, opening_cash, rounding_mode, *, late_penalty_pct=None,
                 returned_perishables=None):
        self.cash, self.pct, self.policy = opening_cash, late_penalty_pct, returned_perishables
        self.items, self.units, self.orders = {}, {}, {}

    def add_item(self, sku, unit_cost, reorder_level, shelf_life_days=None):
        self.items[sku] = (unit_cost, shelf_life_days)

    def receive(self, sku, qty, wh):
        self.units[sku, wh] = self.units.get((sku, wh), 0) + qty

    def ship(self, sku, qty, wh, price):
        self.units[sku, wh] -= qty

    def return_goods(self, sku, qty, wh, price):
        if self.items[sku][1] is not None and self.policy is None:
            raise DepotError("RETURN_POLICY_UNSET")
        self.units[sku, wh] += qty if self.policy == "restock" else 0

    def stock(self, sku, wh=None):
        return self.units.get((sku, wh), 0)

    def place_order(self, supplier, sku, qty, due_day):
        self.orders[len(self.orders)] = (sku, qty, due_day)
        return len(self.orders) - 1

    def deliver(self, order_id, day):
        sku, qty, due = self.orders[order_id]
        if day > due and self.pct is None:
            raise DepotError("LATE_PENALTY_UNSET")
        self.cash -= self.items[sku][0] * qty * (100 - (self.pct if day > due else 0)) // 100

    def notifications(self):
        return []
'''


def test_gate_probe_counts_an_undecided_default_that_refuses_as_open():
    from repro.checks.probe import probe
    r = probe({"inventory.py": UNDECIDED_DEFAULTS})
    assert r["G2"] == {"param": "late_penalty_pct", "open": True, "value": None, "raised": "DepotError",
                       "code": "LATE_PENALTY_UNSET"}
    assert r["G3"] == {"param": "returned_perishables", "open": True, "value": None, "raised": "DepotError",
                       "code": "RETURN_POLICY_UNSET"}


def test_gate_probe_reads_a_decided_default_and_never_injects_the_probed_value():
    r = _probe_variant(HAND_INIT, 'late_penalty_pct=10, perishable_return_policy="discard", '
                                  "data: dict | None = None):")
    assert r["G2"] == {"param": "late_penalty_pct", "open": False, "value": "10.0%"}
    assert r["G3"]["open"] is False and r["G3"]["value"] == "discard"
    assert _probe_variant("", "")["G2"]["open"] is True  # required parameters stay open
