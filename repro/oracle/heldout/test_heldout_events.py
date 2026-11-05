"""Held-out tests for the event clauses. Each docstring's first line states the behaviour."""
from heldout_adapter import advance, cash, expect_code, make, notes, notes_of


# ---------------------------------------------------------------- C14
def test_C14_reorder_at_level(d):
    """A shipment leaving stock at reorder_level emits REORDER(sku, wh)."""
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 10, "A", 16)
    assert notes_of(d, "REORDER") == [("REORDER", "BOLT", "A")]


def test_C14_reorder_emitted_once(d):
    """A second shipment while still below the level does not emit REORDER again."""
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 15, "A", 16)
    d.ship("BOLT", 5, "A", 16)
    assert notes_of(d, "REORDER") == [("REORDER", "BOLT", "A")]


def test_C14_reorder_rearms_after_rising_above(d):
    """After stock rises above the level and falls again, REORDER is emitted again."""
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 15, "A", 16)
    d.receive("BOLT", 20, "A")
    d.ship("BOLT", 20, "A", 16)
    assert notes_of(d, "REORDER") == [("REORDER", "BOLT", "A")] * 2


def test_C14_no_rearm_without_rising_above(d):
    """A receipt that does not lift stock above the level does not re-arm REORDER."""
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 15, "A", 16)
    d.receive("BOLT", 3, "A")
    d.ship("BOLT", 1, "A", 16)
    assert notes_of(d, "REORDER") == [("REORDER", "BOLT", "A")]


def test_C14_no_reorder_above_level(d):
    """A shipment that leaves stock above the level emits no REORDER."""
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 9, "A", 16)
    assert notes_of(d, "REORDER") == []


# ---------------------------------------------------------------- C20
def _overdrawn_depot():
    d = make(opening_cash=120)
    d.receive("BOLT", 10, "A")
    d.advance_day()  # storage 20 -> cash -20
    return d


def test_C20_overdrawn_emitted():
    """When cash goes below 0, OVERDRAWN is emitted."""
    d = _overdrawn_depot()
    assert notes_of(d, "OVERDRAWN") == [("OVERDRAWN",)]


def test_C20_receive_blocked_while_overdrawn():
    """While cash is below 0, receive gives OVERDRAWN and receives nothing."""
    d = _overdrawn_depot()
    expect_code("OVERDRAWN", d.receive, "BOLT", 1, "A")
    assert d.stock("BOLT", "A") == 10


def test_C20_no_overdrawn_while_nonnegative(d):
    """No OVERDRAWN is emitted while cash stays at or above 0."""
    d.receive("BOLT", 10, "A")
    advance(d, 3)
    assert notes_of(d, "OVERDRAWN") == []


def test_C20_receive_allowed_after_recovery():
    """Once cash is back at or above 0, receive works again."""
    d = _overdrawn_depot()
    d.ship("BOLT", 5, "A", 20)  # +100 -> cash 80
    d.receive("BOLT", 1, "A")
    assert d.stock("BOLT", "A") == 6


# ---------------------------------------------------------------- C21
def test_C21_storage_charged_before_expiry(d):
    """Inside advance_day the storage charge comes before expiry, so expiring units are charged."""
    d.receive("GLUE", 10, "A")
    advance(d, 7)
    c0 = cash(d)
    d.advance_day()  # day 8: charge 10 units, then expire them
    assert d.stock("GLUE", "A") == 0
    assert c0 - cash(d) == 20


def test_C21_expiry_before_overdrawn_check():
    """Inside advance_day expiry comes before the overdrawn check: EXPIRY precedes OVERDRAWN."""
    d = make(opening_cash=2550)
    d.receive("GLUE", 10, "A")  # cash 150
    advance(d, 7)               # cash 10
    d.advance_day()             # charge 20 -> -10, expire 10, then overdrawn check
    kinds = [n[0] for n in notes(d)]
    assert "EXPIRY" in kinds and "OVERDRAWN" in kinds
    assert kinds.index("EXPIRY") < kinds.index("OVERDRAWN")


def test_C21_overdrawn_check_same_day_as_charge():
    """The overdrawn check runs in the same advance_day as the charge that caused it."""
    d = make(opening_cash=120)
    d.receive("BOLT", 10, "A")
    n0 = len(notes_of(d, "OVERDRAWN"))
    d.advance_day()
    assert len(notes_of(d, "OVERDRAWN")) == n0 + 1


# ---------------------------------------------------------------- C32
def _three_kinds(d):
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 15, "A", 16)                  # REORDER
    d.audit({("BOLT", "A"): 1})                  # AUDIT_MISMATCH
    for o in [d.place_order("S1", "BOLT", 1, 0) for _ in range(2)]:
        d.deliver(o, 3)                          # SUPPLIER_SUSPENDED on the second


def test_C32_log_in_operation_order(d):
    """notifications() lists every notification in the order of the operations that caused it."""
    _three_kinds(d)
    assert notes(d) == [("REORDER", "BOLT", "A"), ("AUDIT_MISMATCH", "BOLT", "A", 45, 1),
                        ("SUPPLIER_SUSPENDED", "S1")]


def test_C32_notifications_cumulative(d):
    """notifications() returns the whole log every time, not only new entries."""
    _three_kinds(d)
    assert notes(d) == notes(d)
    assert len(notes(d)) == 3


def test_C32_failed_operation_adds_none(d):
    """A failed operation adds no notification."""
    d.receive("BOLT", 60, "A")
    d.ship("BOLT", 15, "A", 16)
    before = notes(d)
    expect_code("INSUFFICIENT_STOCK", d.ship, "BOLT", 100, "A", 16)
    assert notes(d) == before


def test_C32_order_across_warehouses(d):
    """Notifications from different warehouses appear in operation order."""
    d.receive("BOLT", 60, "A")
    d.receive("BOLT", 60, "B")
    d.ship("BOLT", 15, "B", 16)
    d.ship("BOLT", 15, "A", 16)
    assert notes_of(d, "REORDER") == [("REORDER", "BOLT", "B"), ("REORDER", "BOLT", "A")]
