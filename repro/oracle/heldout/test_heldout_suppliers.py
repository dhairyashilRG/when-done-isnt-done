"""Held-out tests for the supplier clauses. Each docstring's first line states the behaviour."""
from heldout_adapter import expect_code, notes_of, reliability


def _orders(d, n, due=5, supplier="S1"):
    return [d.place_order(supplier, "BOLT", 10, due) for _ in range(n)]


# ---------------------------------------------------------------- C15
def test_C15_new_supplier_starts_at_3(d):
    """A supplier starts with reliability 3."""
    _orders(d, 1)
    assert reliability(d, "S1") == 3


def test_C15_on_time_adds_one(d):
    """An on-time delivery adds 1 to reliability."""
    (o,) = _orders(d, 1)
    d.deliver(o, 5)
    assert reliability(d, "S1") == 4


def test_C15_late_subtracts_one(d):
    """A late delivery subtracts 1 from reliability."""
    (o,) = _orders(d, 1)
    d.deliver(o, 6)
    assert reliability(d, "S1") == 2


def test_C15_capped_at_5(d):
    """Reliability never rises above 5."""
    for o in _orders(d, 4):
        d.deliver(o, 5)
    assert reliability(d, "S1") == 5


def test_C15_floored_at_0(d):
    """Reliability never falls below 0."""
    for o in _orders(d, 4):
        d.deliver(o, 9)
    assert reliability(d, "S1") == 0


# ---------------------------------------------------------------- C16
def test_C16_place_order_returns_distinct_ids(d):
    """place_order returns a distinct order id for each order."""
    ids = _orders(d, 3)
    assert len(set(ids)) == 3


def test_C16_delivery_on_due_day_is_on_time(d):
    """A delivery on the due day is on time."""
    (o,) = _orders(d, 1, due=5)
    d.deliver(o, 5)
    assert reliability(d, "S1") == 4


def test_C16_delivery_after_due_day_is_late(d):
    """A delivery after the due day is late."""
    (o,) = _orders(d, 1, due=5)
    d.deliver(o, 6)
    assert reliability(d, "S1") == 2


def test_C16_delivery_before_due_day_is_on_time(d):
    """A delivery before the due day is on time."""
    (o,) = _orders(d, 1, due=5)
    d.deliver(o, 1)
    assert reliability(d, "S1") == 4


# ---------------------------------------------------------------- C17
def test_C17_two_late_deliveries_suspend(d):
    """Two late deliveries bring reliability to 1 and emit SUPPLIER_SUSPENDED(supplier)."""
    for o in _orders(d, 2):
        d.deliver(o, 9)
    assert reliability(d, "S1") == 1
    assert notes_of(d, "SUPPLIER_SUSPENDED") == [("SUPPLIER_SUSPENDED", "S1")]


def test_C17_suspended_supplier_rejects_orders(d):
    """A new order to a suspended supplier gives SUPPLIER_SUSPENDED."""
    for o in _orders(d, 2):
        d.deliver(o, 9)
    expect_code("SUPPLIER_SUSPENDED", d.place_order, "S1", "BOLT", 1, 20)


def test_C17_suspension_notified_once(d):
    """SUPPLIER_SUSPENDED is emitted once, when the supplier becomes suspended."""
    for o in _orders(d, 3):
        d.deliver(o, 9)
    assert notes_of(d, "SUPPLIER_SUSPENDED") == [("SUPPLIER_SUSPENDED", "S1")]


def test_C17_reinstate_sets_two(d):
    """reinstate sets reliability to 2 and the supplier takes orders again."""
    for o in _orders(d, 2):
        d.deliver(o, 9)
    d.reinstate("S1")
    assert reliability(d, "S1") == 2
    d.place_order("S1", "BOLT", 1, 20)


def test_C17_resuspension_notifies_again(d):
    """A reinstated supplier that becomes suspended again is notified again."""
    for o in _orders(d, 2):
        d.deliver(o, 9)
    d.reinstate("S1")
    (o,) = _orders(d, 1, due=10)
    d.deliver(o, 11)
    assert notes_of(d, "SUPPLIER_SUSPENDED") == [("SUPPLIER_SUSPENDED", "S1")] * 2
