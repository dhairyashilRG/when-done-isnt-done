"""Held-out tests for the money clauses. Each docstring's first line states the behaviour."""
import heldout_adapter as A
from heldout_adapter import advance, cash, expect_code, make


# ---------------------------------------------------------------- C05
def test_C05_receive_costs_unit_cost_times_qty(d):
    """Receiving costs unit_cost x qty."""
    c0 = cash(d)
    d.receive("BOLT", 10, "A")
    assert c0 - cash(d) == 120
    d.receive("GLUE", 3, "A")
    assert c0 - cash(d) == 120 + 720


def test_C05_insufficient_funds():
    """A receipt that would take cash below 0 gives INSUFFICIENT_FUNDS and changes nothing."""
    d = make(opening_cash=1000)
    expect_code("INSUFFICIENT_FUNDS", d.receive, "GLUE", 5, "A")
    assert (d.stock("GLUE"), cash(d)) == (0, 1000)


def test_C05_cash_may_reach_zero():
    """A receipt that takes cash exactly to 0 is accepted."""
    d = make(opening_cash=1200)
    d.receive("GLUE", 5, "A")
    assert cash(d) == 0


def test_C05_failed_receive_after_success():
    """After a successful receipt, an unaffordable one changes nothing."""
    d = make(opening_cash=500)
    d.receive("BOLT", 10, "A")
    expect_code("INSUFFICIENT_FUNDS", d.receive, "BOLT", 40, "A")
    assert (d.stock("BOLT"), cash(d)) == (10, 380)


# ---------------------------------------------------------------- C07
def test_C07_shipment_adds_price_times_qty(d):
    """A shipment adds price x qty to cash."""
    d.receive("BOLT", 10, "A")
    c0 = cash(d)
    d.ship("BOLT", 5, "A", 16)
    assert cash(d) - c0 == 80


def test_C07_two_shipments_add_up(d):
    """Each shipment adds its own price x qty."""
    d.receive("BOLT", 10, "A")
    c0 = cash(d)
    d.ship("BOLT", 3, "A", 20)
    d.ship("BOLT", 4, "A", 25)
    assert cash(d) - c0 == 160


def test_C07_largest_non_bulk_sale(d):
    """A sale just below the bulk threshold adds the full price x qty."""
    d.receive("BOLT", 30, "A")
    c0 = cash(d)
    d.ship("BOLT", 19, "A", 10)
    assert cash(d) - c0 == 190


# ---------------------------------------------------------------- C08
def test_C08_list_price_bolt(d):
    """list_price(BOLT) is 12 x 1.35 = 16.2, rounded to 16."""
    assert d.list_price("BOLT") == 16


def test_C08_list_price_glue(d):
    """list_price(GLUE) is 240 x 1.35 = 324."""
    assert d.list_price("GLUE") == 324


def test_C08_list_price_rounding_mode(rounding_mode):
    """list_price rounds half-cent prices by the depot's rounding mode."""
    d = make(rounding_mode=rounding_mode)
    d.add_item("PIN", 30, 1)   # 40.5
    d.add_item("TAPE", 70, 1)  # 94.5
    d.add_item("WIRE", 50, 1)  # 67.5
    expected = {"ROUND_HALF_UP": (41, 95, 68), "ROUND_HALF_EVEN": (40, 94, 68)}[rounding_mode]
    assert (d.list_price("PIN"), d.list_price("TAPE"), d.list_price("WIRE")) == expected


def test_C08_list_price_rounds_non_half(d):
    """list_price rounds non-half fractions to the nearest cent."""
    d.add_item("LENS", 95, 1)  # 128.25
    d.add_item("CLIP", 15, 1)  # 20.25
    d.add_item("RING", 17, 1)  # 22.95
    assert (d.list_price("LENS"), d.list_price("CLIP"), d.list_price("RING")) == (128, 20, 23)


# ---------------------------------------------------------------- C09
def test_C09_bulk_threshold_gets_discount(d):
    """A sale of exactly bulk_threshold units gets bulk_discount_pct off."""
    d.receive("BOLT", 50, "A")
    c0 = cash(d)
    d.ship("BOLT", 20, "A", 10)
    assert cash(d) - c0 == 180


def test_C09_below_threshold_no_discount(d):
    """A sale below bulk_threshold gets no discount."""
    d.receive("BOLT", 50, "A")
    c0 = cash(d)
    d.ship("BOLT", 19, "A", 10)
    assert cash(d) - c0 == 190


def test_C09_above_threshold_discount(d):
    """A sale above bulk_threshold gets bulk_discount_pct off."""
    d.receive("BOLT", 50, "A")
    c0 = cash(d)
    d.ship("BOLT", 30, "A", 15)
    assert cash(d) - c0 == 405


def test_C09_discount_does_not_change_units(d):
    """The bulk discount changes the money, not the units shipped."""
    d.receive("BOLT", 50, "A")
    d.ship("BOLT", 25, "A", 10)
    assert d.stock("BOLT", "A") == 25


# ---------------------------------------------------------------- C11
def test_C11_transfer_costs_per_unit(d):
    """A transfer costs the sending side 25 cents per unit."""
    d.receive("BOLT", 20, "A")
    c0 = cash(d)
    d.transfer("BOLT", 10, "A", "B")
    assert c0 - cash(d) == 250


def test_C11_transfer_cost_scales(d):
    """The transfer cost is per unit transferred."""
    d.receive("BOLT", 20, "A")
    c0 = cash(d)
    d.transfer("BOLT", 4, "A", "B")
    assert c0 - cash(d) == 100
    d.transfer("BOLT", 1, "B", "A")
    assert c0 - cash(d) == 125


def test_C11_failed_transfer_costs_nothing(d):
    """A rejected transfer costs nothing."""
    d.receive("BOLT", 3, "A")
    c0 = cash(d)
    expect_code("INSUFFICIENT_STOCK", d.transfer, "BOLT", 5, "A", "B")
    assert cash(d) == c0


# ---------------------------------------------------------------- C18 (gate G2: late_penalty_pct injected)
def _order(d, sku, qty, due):
    return d.place_order("S1", sku, qty, due)


def test_C18_on_time_delivery_pays_full(late_penalty_pct):
    """An on-time delivery is paid in full (unit_cost x qty)."""
    d = make(late_penalty_pct=late_penalty_pct)
    o = _order(d, "GLUE", 5, 5)
    c0 = cash(d)
    d.deliver(o, 5)
    assert c0 - cash(d) == 1200


def test_C18_late_delivery_pays_less(late_penalty_pct):
    """A late delivery is paid less by the owner's late-penalty percentage."""
    d = make(late_penalty_pct=late_penalty_pct)
    o = _order(d, "GLUE", 5, 5)
    c0 = cash(d)
    d.deliver(o, 6)
    assert c0 - cash(d) == 1200 * (100 - late_penalty_pct) // 100


def test_C18_late_penalty_small_order(late_penalty_pct):
    """The late penalty applies to any order size."""
    d = make(late_penalty_pct=late_penalty_pct)
    o = _order(d, "BOLT", 10, 2)
    c0 = cash(d)
    d.deliver(o, 3)
    assert c0 - cash(d) == 120 * (100 - late_penalty_pct) // 100


def test_C18_penalty_follows_owner_value():
    """The penalty follows the owner's value: two depots with different values pay differently."""
    paid = []
    for pct in A.GATE_PENALTY:
        d = make(late_penalty_pct=pct)
        o = _order(d, "GLUE", 5, 1)
        c0 = cash(d)
        d.deliver(o, 4)
        paid.append(c0 - cash(d))
    assert paid == [1200 * (100 - p) // 100 for p in A.GATE_PENALTY]


# ---------------------------------------------------------------- C19
def test_C19_storage_charge_per_unit_day(d):
    """advance_day charges storage_cents_per_unit_day for every unit held."""
    d.receive("BOLT", 100, "A")
    c0 = cash(d)
    d.advance_day()
    assert c0 - cash(d) == 200


def test_C19_storage_counts_all_units(d):
    """The storage charge counts units of every sku in every warehouse."""
    d.receive("BOLT", 10, "A")
    d.receive("GLUE", 5, "B")
    c0 = cash(d)
    d.advance_day()
    assert c0 - cash(d) == 30


def test_C19_no_units_no_charge(d):
    """With no units held there is no storage charge."""
    c0 = cash(d)
    d.advance_day()
    assert cash(d) == c0


def test_C19_storage_may_go_negative():
    """The storage charge may take cash below 0."""
    d = make(opening_cash=120)
    d.receive("BOLT", 10, "A")
    d.advance_day()
    assert cash(d) == -20


# ---------------------------------------------------------------- C30
def test_C30_none_when_nothing_held(d):
    """turnover is None when the average units held is 0."""
    advance(d, 3)
    assert d.turnover(0, 2) is None


def test_C30_zero_when_held_but_not_shipped(d):
    """turnover is 0 (not None) when units were held but none shipped."""
    d.receive("BOLT", 100, "A")
    advance(d, 3)
    t = d.turnover(1, 2)
    assert t is not None and t == 0


def test_C30_units_shipped_over_average_held(d):
    """turnover is units shipped divided by average units held over the days."""
    d.receive("BOLT", 100, "A")
    advance(d, 1)
    d.ship("BOLT", 50, "A", 10)
    d.receive("BOLT", 50, "A")
    advance(d, 2)
    assert abs(d.turnover(1, 2) - 0.5) < 1e-9


def test_C30_none_before_any_stock(d):
    """turnover over a period before any stock existed is None, never 0 or infinity."""
    advance(d, 2)
    d.receive("BOLT", 10, "A")
    advance(d, 1)
    assert d.turnover(0, 1) is None
