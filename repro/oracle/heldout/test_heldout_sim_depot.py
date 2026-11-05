"""Held-out tests for the sim and depot clauses. Each docstring's first line states the behaviour."""
import inspect
import random

import pytest

import heldout_adapter as A
from heldout_adapter import cash, expect_code, make, norm_sim

DEMAND = {"BOLT": (5, 40), "GLUE": (0, 6), "FILM": (1, 12)}


def sim(days, seed):
    return norm_sim(A.get("simulate")(days, seed))


# ---------------------------------------------------------------- C29
def test_C29_same_seed_same_orders():
    """simulate with the same seed gives the same orders."""
    assert sim(30, 7) == sim(30, 7)


def test_C29_different_seeds_differ():
    """simulate with different seeds gives different orders."""
    assert sim(30, 1) != sim(30, 2)


def test_C29_orders_follow_demand_ranges():
    """simulate gives one entry per day, with quantities inside each sku's demand range."""
    out = sim(30, 3)
    assert len(out) == 30
    seen = set()
    for day in out:
        for sku, qty in day:
            lo, hi = DEMAND[sku]
            assert lo <= qty <= hi
            seen.add(sku)
    assert seen == set(DEMAND)


def test_C29_uses_private_rng():
    """simulate uses only its own seeded RNG: the global random state neither matters nor changes."""
    random.seed(5)
    expected = random.random()
    random.seed(5)
    sim(10, 3)
    assert random.random() == expected
    random.seed(1)
    first = sim(10, 3)
    random.seed(2)
    assert sim(10, 3) == first


# ---------------------------------------------------------------- C31 (gate G1: rounding_mode injected)
def test_C31_rounding_mode_required_no_default():
    """The constructor's rounding_mode parameter exists and has no default."""
    params = inspect.signature(A.get("Depot").__init__).parameters
    assert "rounding_mode" in params
    assert params["rounding_mode"].default is inspect.Parameter.empty


def test_C31_missing_rounding_mode_is_type_error():
    """Constructing a depot without rounding_mode fails."""
    with pytest.raises((TypeError, A.Error())):
        A.construct(omit_rounding=True)


def test_C31_constructor_rounding_mode_controls_price(rounding_mode):
    """The rounding_mode given to the constructor decides how list prices round."""
    d = make(rounding_mode=rounding_mode)
    d.add_item("PIN", 30, 1)  # 40.5
    assert d.list_price("PIN") == {"ROUND_HALF_UP": 41, "ROUND_HALF_EVEN": 40}[rounding_mode]


def test_C31_constructor_takes_warehouses_and_cash():
    """The constructor fixes the warehouses, their capacities and the opening cash."""
    d = make(warehouses=("X", "Y"), capacities={"X": 5, "Y": 5}, opening_cash=777)
    assert cash(d) == 777
    expect_code("UNKNOWN_WAREHOUSE", d.receive, "BOLT", 1, "A")
    expect_code("CAPACITY", d.receive, "BOLT", 6, "Y")
    d.receive("BOLT", 5, "Y")
    assert d.stock("BOLT", "Y") == 5
