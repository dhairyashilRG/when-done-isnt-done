"""Held-out tests for the inventory clauses. Each docstring's first line states the behaviour."""
import json

import heldout_adapter as A
from heldout_adapter import advance, cash, expect_code, expect_error, make, notes, notes_of


# ---------------------------------------------------------------- C01
def test_C01_added_item_has_zero_stock():
    """add_item registers a sku with zero stock."""
    d = make(items=False)
    d.add_item("BOLT", 12, 50)
    assert d.stock("BOLT") == 0


def test_C01_duplicate_sku_rejected(d):
    """Adding a sku twice gives DUPLICATE_SKU."""
    expect_code("DUPLICATE_SKU", d.add_item, "BOLT", 12, 50)


def test_C01_unit_cost_must_be_positive(d):
    """unit_cost of 0 or below is rejected with a DepotError and the item is not added."""
    for bad in (0, -5):
        expect_error(d.add_item, "PIN", bad, 1)
    d.add_item("PIN", 7, 1)
    assert d.stock("PIN") == 0


def test_C01_reorder_level_must_be_nonnegative(d):
    """A negative reorder_level is rejected; a reorder_level of 0 is accepted."""
    expect_error(d.add_item, "PIN", 7, -1)
    d.add_item("PIN", 7, 0)
    assert d.stock("PIN") == 0


def test_C01_failed_duplicate_changes_nothing(d):
    """A rejected duplicate add_item leaves the original item's unit cost in place."""
    expect_error(d.add_item, "BOLT", 99, 1)
    assert d.list_price("BOLT") == 16


# ---------------------------------------------------------------- C02
def test_C02_receive_unknown_sku(d):
    """receive naming an unknown sku gives UNKNOWN_SKU."""
    expect_code("UNKNOWN_SKU", d.receive, "NOPE", 1, "A")


def test_C02_ship_unknown_sku(d):
    """ship naming an unknown sku gives UNKNOWN_SKU."""
    expect_code("UNKNOWN_SKU", d.ship, "NOPE", 1, "A", 10)


def test_C02_queries_unknown_sku(d):
    """stock and list_price naming an unknown sku give UNKNOWN_SKU."""
    expect_code("UNKNOWN_SKU", d.stock, "NOPE")
    expect_code("UNKNOWN_SKU", d.list_price, "NOPE")


def test_C02_other_operations_unknown_sku(d):
    """transfer, return_goods and place_order naming an unknown sku give UNKNOWN_SKU."""
    expect_code("UNKNOWN_SKU", d.transfer, "NOPE", 1, "A", "B")
    expect_code("UNKNOWN_SKU", d.return_goods, "NOPE", 1, "A", 10)
    expect_code("UNKNOWN_SKU", d.place_order, "S1", "NOPE", 1, 5)


# ---------------------------------------------------------------- C03
def test_C03_receive_unknown_warehouse(d):
    """receive into an unknown warehouse gives UNKNOWN_WAREHOUSE."""
    expect_code("UNKNOWN_WAREHOUSE", d.receive, "BOLT", 1, "Z")


def test_C03_ship_unknown_warehouse(d):
    """ship from an unknown warehouse gives UNKNOWN_WAREHOUSE."""
    d.receive("BOLT", 10, "A")
    expect_code("UNKNOWN_WAREHOUSE", d.ship, "BOLT", 1, "Z", 10)


def test_C03_stock_unknown_warehouse(d):
    """stock(sku, wh) for an unknown warehouse gives UNKNOWN_WAREHOUSE."""
    expect_code("UNKNOWN_WAREHOUSE", d.stock, "BOLT", "Z")


def test_C03_transfer_unknown_warehouse(d):
    """transfer to or from an unknown warehouse gives UNKNOWN_WAREHOUSE and moves nothing."""
    d.receive("BOLT", 10, "A")
    expect_code("UNKNOWN_WAREHOUSE", d.transfer, "BOLT", 1, "A", "Z")
    expect_code("UNKNOWN_WAREHOUSE", d.transfer, "BOLT", 1, "Z", "A")
    assert d.stock("BOLT", "A") == 10


# ---------------------------------------------------------------- C04
def test_C04_receive_adds_to_named_warehouse(d):
    """receive adds units to the named warehouse only."""
    d.receive("BOLT", 10, "A")
    assert d.stock("BOLT", "A") == 10
    assert d.stock("BOLT", "B") == 0


def test_C04_qty_must_be_positive_int(d):
    """receive with qty 0, negative, or non-integer is rejected and changes nothing."""
    before = cash(d)
    for bad in (0, -3, 2.5):
        expect_error(d.receive, "BOLT", bad, "A")
    assert d.stock("BOLT") == 0
    assert cash(d) == before


def test_C04_capacity_exceeded(d):
    """A receipt that would push a warehouse's total units over capacity gives CAPACITY and receives nothing."""
    d = make(capacities={"A": 100, "B": 100})
    d.receive("BOLT", 60, "A")
    before = cash(d)
    expect_code("CAPACITY", d.receive, "GLUE", 41, "A")
    assert d.stock("GLUE", "A") == 0
    assert cash(d) == before


def test_C04_capacity_reached_exactly():
    """A receipt that fills a warehouse exactly to capacity is accepted."""
    d = make(capacities={"A": 100, "B": 100})
    d.receive("BOLT", 60, "A")
    d.receive("GLUE", 40, "A")
    assert d.stock("GLUE", "A") == 40


def test_C04_capacity_is_per_warehouse():
    """A full warehouse does not block receipts into another warehouse."""
    d = make(capacities={"A": 100, "B": 100})
    d.receive("BOLT", 100, "A")
    d.receive("BOLT", 50, "B")
    assert d.stock("BOLT", "B") == 50


# ---------------------------------------------------------------- C06
def test_C06_ship_reduces_stock(d):
    """ship removes the shipped units from the warehouse."""
    d.receive("BOLT", 30, "A")
    d.ship("BOLT", 12, "A", 16)
    assert d.stock("BOLT", "A") == 18


def test_C06_insufficient_stock_no_partial(d):
    """Shipping more than the stock gives INSUFFICIENT_STOCK and ships nothing."""
    d.receive("BOLT", 5, "A")
    before = cash(d)
    expect_code("INSUFFICIENT_STOCK", d.ship, "BOLT", 8, "A", 16)
    assert d.stock("BOLT", "A") == 5
    assert cash(d) == before


def test_C06_other_warehouse_stock_not_used(d):
    """Stock in another warehouse does not count towards a shipment."""
    d.receive("BOLT", 10, "A")
    d.receive("BOLT", 10, "B")
    expect_code("INSUFFICIENT_STOCK", d.ship, "BOLT", 15, "A", 16)


def test_C06_ship_all_stock(d):
    """Shipping exactly the stock leaves zero."""
    d.receive("BOLT", 7, "A")
    d.ship("BOLT", 7, "A", 16)
    assert d.stock("BOLT", "A") == 0


# ---------------------------------------------------------------- C10
def test_C10_transfer_moves_stock(d):
    """transfer moves units from one warehouse to the other."""
    d.receive("BOLT", 10, "A")
    d.transfer("BOLT", 4, "A", "B")
    assert d.stock("BOLT", "A") == 6
    assert d.stock("BOLT", "B") == 4


def test_C10_insufficient_source_stock():
    """A transfer larger than the source stock gives INSUFFICIENT_STOCK and changes nothing."""
    d = make()
    d.receive("BOLT", 3, "A")
    before = cash(d)
    expect_code("INSUFFICIENT_STOCK", d.transfer, "BOLT", 5, "A", "B")
    assert (d.stock("BOLT", "A"), d.stock("BOLT", "B"), cash(d)) == (3, 0, before)


def test_C10_destination_capacity():
    """A transfer that would overfill the destination gives CAPACITY and changes nothing."""
    d = make(capacities={"A": 100, "B": 5})
    d.receive("BOLT", 10, "A")
    before = cash(d)
    expect_code("CAPACITY", d.transfer, "BOLT", 6, "A", "B")
    assert (d.stock("BOLT", "A"), d.stock("BOLT", "B"), cash(d)) == (10, 0, before)


def test_C10_transfer_keeps_total(d):
    """A transfer leaves the sku's total across warehouses unchanged."""
    d.receive("BOLT", 10, "A")
    d.receive("BOLT", 3, "B")
    d.transfer("BOLT", 5, "A", "B")
    assert d.stock("BOLT") == 13


# ---------------------------------------------------------------- C12
def test_C12_oldest_lot_shipped_first(d):
    """Shipping consumes the oldest lot first, so the newer lot's remainder expires later."""
    d.receive("GLUE", 5, "A")
    advance(d, 1)
    d.receive("GLUE", 5, "A")
    d.ship("GLUE", 7, "A", 300)
    advance(d, 7)  # day 8: the day-0 lot would expire now, but it was shipped
    assert notes_of(d, "EXPIRY") == []
    assert d.stock("GLUE", "A") == 3
    advance(d, 1)  # day 9: the day-1 lot's remainder expires
    assert notes_of(d, "EXPIRY") == [("EXPIRY", "GLUE", "A", 3)]


def test_C12_lot_stamped_with_receipt_day(d):
    """A receipt's lot is stamped with the day it was received."""
    advance(d, 2)
    d.receive("GLUE", 5, "A")
    advance(d, 7)  # day 9: age 7
    assert d.stock("GLUE", "A") == 5
    advance(d, 1)  # day 10: age 8 > 7
    assert d.stock("GLUE", "A") == 0


def test_C12_partial_lot_consumption(d):
    """A shipment smaller than the oldest lot leaves the remainder in that oldest lot."""
    d.receive("GLUE", 4, "A")
    advance(d, 1)
    d.receive("GLUE", 4, "A")
    d.ship("GLUE", 2, "A", 300)
    advance(d, 7)  # day 8
    assert notes_of(d, "EXPIRY") == [("EXPIRY", "GLUE", "A", 2)]
    assert d.stock("GLUE", "A") == 4


def test_C12_fifo_is_per_warehouse(d):
    """Shipping from one warehouse does not consume lots in another warehouse."""
    d.receive("GLUE", 5, "B")
    advance(d, 1)
    d.receive("GLUE", 5, "A")
    d.ship("GLUE", 3, "A", 300)
    advance(d, 7)  # day 8: only B's day-0 lot is old enough
    assert notes_of(d, "EXPIRY") == [("EXPIRY", "GLUE", "B", 5)]
    assert d.stock("GLUE", "A") == 2


# ---------------------------------------------------------------- C13
def test_C13_perishable_expires_after_shelf_life(d):
    """A perishable lot is kept while its age is at most the shelf life and discarded when older."""
    d.receive("GLUE", 5, "A")
    advance(d, 7)
    assert d.stock("GLUE", "A") == 5
    advance(d, 1)
    assert d.stock("GLUE", "A") == 0


def test_C13_expiry_notification(d):
    """An expiry emits EXPIRY(sku, wh, qty) exactly once."""
    d.receive("GLUE", 5, "A")
    advance(d, 10)
    assert notes_of(d, "EXPIRY") == [("EXPIRY", "GLUE", "A", 5)]


def test_C13_non_perishable_never_expires(d):
    """Items without a shelf life never expire."""
    d.receive("BOLT", 10, "A")
    advance(d, 30)
    assert d.stock("BOLT", "A") == 10
    assert notes_of(d, "EXPIRY") == []


def test_C13_shelf_life_zero_rejected_or_treated_as_one():
    """A shelf life of 0 is either rejected at add_item or treated as 1; it never expires on receipt."""
    d = make(items=False)
    try:
        d.add_item("FILM", 95, 10, shelf_life_days=0)
    except A.Error():
        return  # rejected at load with an error: accepted
    d.receive("FILM", 5, "A")
    assert d.stock("FILM", "A") == 5
    advance(d, 1)
    assert d.stock("FILM", "A") == 5
    advance(d, 1)
    assert d.stock("FILM", "A") == 0


def test_C13_expiry_per_warehouse(d):
    """Only the lots old enough expire; a younger lot in another warehouse stays."""
    d.receive("GLUE", 3, "A")
    advance(d, 2)
    d.receive("GLUE", 4, "B")
    advance(d, 6)  # day 8
    assert notes_of(d, "EXPIRY") == [("EXPIRY", "GLUE", "A", 3)]
    assert d.stock("GLUE", "B") == 4


# ---------------------------------------------------------------- C22
def test_C22_mismatch_notified(d):
    """An audit count that differs from the ledger emits AUDIT_MISMATCH(sku, wh, ledger, counted)."""
    d.receive("BOLT", 10, "A")
    d.audit({("BOLT", "A"): 8})
    assert notes_of(d, "AUDIT_MISMATCH") == [("AUDIT_MISMATCH", "BOLT", "A", 10, 8)]


def test_C22_matching_counts_silent(d):
    """An audit whose counts match the ledger emits nothing."""
    d.receive("BOLT", 10, "A")
    d.audit({("BOLT", "A"): 10})
    assert notes_of(d, "AUDIT_MISMATCH") == []


def test_C22_empty_audit_is_error(d):
    """An empty audit gives EMPTY_AUDIT; it is not 'everything matches'."""
    expect_code("EMPTY_AUDIT", d.audit, {})


def test_C22_each_mismatch_notified(d):
    """Every mismatching count gets its own AUDIT_MISMATCH."""
    d.receive("BOLT", 10, "A")
    d.receive("GLUE", 2, "B")
    d.audit({("BOLT", "A"): 9, ("GLUE", "B"): 3, ("BOLT", "B"): 0})
    assert set(notes_of(d, "AUDIT_MISMATCH")) == {("AUDIT_MISMATCH", "BOLT", "A", 10, 9),
                                                  ("AUDIT_MISMATCH", "GLUE", "B", 2, 3)}


def test_C22_audit_does_not_change_ledger(d):
    """An audit reports mismatches but does not change the ledger."""
    d.receive("BOLT", 10, "A")
    d.audit({("BOLT", "A"): 8})
    assert d.stock("BOLT", "A") == 10


# ---------------------------------------------------------------- C23
def test_C23_return_restocks_and_refunds(d):
    """return_goods adds the units back and refunds price x qty."""
    d.receive("BOLT", 20, "A")
    d.ship("BOLT", 10, "A", 20)
    before = cash(d)
    d.return_goods("BOLT", 4, "A", 20)
    assert d.stock("BOLT", "A") == 14
    assert before - cash(d) == 80


def test_C23_return_exceeds_shipped(d):
    """Returning more than was shipped gives RETURN_EXCEEDS and changes nothing."""
    d.receive("BOLT", 20, "A")
    d.ship("BOLT", 5, "A", 20)
    before = cash(d)
    expect_code("RETURN_EXCEEDS", d.return_goods, "BOLT", 6, "A", 20)
    assert (d.stock("BOLT", "A"), cash(d)) == (15, before)


def test_C23_returns_are_cumulative(d):
    """Earlier returns count against the shipped total."""
    d.receive("BOLT", 20, "A")
    d.ship("BOLT", 5, "A", 20)
    d.return_goods("BOLT", 3, "A", 20)
    expect_code("RETURN_EXCEEDS", d.return_goods, "BOLT", 3, "A", 20)


def test_C23_never_shipped(d):
    """Returning a sku that was never shipped gives RETURN_EXCEEDS."""
    expect_code("RETURN_EXCEEDS", d.return_goods, "BOLT", 1, "A", 20)


def test_C23_return_to_other_warehouse(d):
    """Returns are limited per sku, not per warehouse."""
    d.receive("BOLT", 20, "A")
    d.ship("BOLT", 5, "A", 20)
    d.return_goods("BOLT", 5, "B", 20)
    assert d.stock("BOLT", "B") == 5


# ---------------------------------------------------------------- C24
def test_C24_bulk_applies_all(d):
    """receive_bulk applies every receipt and charges for all of them."""
    before = cash(d)
    d.receive_bulk([("BOLT", 10, "A"), ("GLUE", 2, "B")])
    assert (d.stock("BOLT", "A"), d.stock("GLUE", "B")) == (10, 2)
    assert before - cash(d) == 600


def test_C24_bulk_unknown_sku_applies_none(d):
    """A receive_bulk with one bad receipt applies none of them."""
    before = cash(d)
    expect_error(d.receive_bulk, [("BOLT", 10, "A"), ("NOPE", 1, "A")])
    assert d.stock("BOLT", "A") == 0
    assert cash(d) == before


def test_C24_bulk_capacity_combined():
    """Receipts in one receive_bulk count together against capacity."""
    d = make(capacities={"A": 50, "B": 50})
    expect_code("CAPACITY", d.receive_bulk, [("BOLT", 30, "A"), ("BOLT", 30, "A")])
    assert d.stock("BOLT", "A") == 0


def test_C24_bulk_funds_combined():
    """Receipts in one receive_bulk count together against cash."""
    d = make(opening_cash=1000)
    expect_code("INSUFFICIENT_FUNDS", d.receive_bulk, [("GLUE", 3, "A"), ("GLUE", 3, "B")])
    assert d.stock("GLUE") == 0
    assert cash(d) == 1000


# ---------------------------------------------------------------- C25
def test_C25_total_across_warehouses(d):
    """stock(sku) returns the total across warehouses."""
    d.receive("BOLT", 10, "A")
    d.receive("BOLT", 5, "B")
    assert d.stock("BOLT") == 15


def test_C25_per_warehouse(d):
    """stock(sku, wh) returns one warehouse's stock."""
    d.receive("BOLT", 10, "A")
    d.receive("BOLT", 5, "B")
    assert (d.stock("BOLT", "A"), d.stock("BOLT", "B")) == (10, 5)


def test_C25_zero_without_stock(d):
    """stock of an item with no receipts is 0, in total and per warehouse."""
    assert d.stock("GLUE") == 0
    assert d.stock("GLUE", "B") == 0


# ---------------------------------------------------------------- C26
def test_C26_report_rows_sorted(d):
    """report rows are (sku, wh, units, value_cents) sorted by sku then wh."""
    d.receive("GLUE", 2, "B")
    d.receive("BOLT", 3, "B")
    d.receive("BOLT", 10, "A")
    assert A.report(d) == [("BOLT", "A", 10, 120), ("BOLT", "B", 3, 36), ("GLUE", "B", 2, 480)]


def test_C26_value_uses_unit_cost(d):
    """report values use unit_cost, not the list price."""
    d.receive("GLUE", 3, "A")
    assert A.report(d) == [("GLUE", "A", 3, 720)]


def test_C26_report_reflects_shipments(d):
    """report reflects shipped units."""
    d.receive("BOLT", 10, "A")
    d.ship("BOLT", 4, "A", 16)
    assert A.report(d) == [("BOLT", "A", 6, 72)]


# ---------------------------------------------------------------- C27
def test_C27_undo_reverts_receive(d):
    """undo reverts a receive: stock and cash return to their earlier values."""
    before = cash(d)
    d.receive("BOLT", 10, "A")
    d.undo()
    assert (d.stock("BOLT"), cash(d)) == (0, before)


def test_C27_undo_reverts_ship(d):
    """undo reverts a shipment: stock and cash return to their earlier values."""
    d.receive("BOLT", 10, "A")
    before = cash(d)
    d.ship("BOLT", 4, "A", 20)
    d.undo()
    assert (d.stock("BOLT", "A"), cash(d)) == (10, before)


def test_C27_undo_only_once(d):
    """undo reverts only the last operation; a second undo does not revert the one before."""
    d.receive("BOLT", 10, "A")
    d.receive("BOLT", 5, "A")
    d.undo()
    assert d.stock("BOLT", "A") == 10
    try:
        d.undo()
    except A.Error():
        pass
    assert d.stock("BOLT", "A") == 10


def test_C27_undo_after_advance_blocked(d):
    """undo right after advance_day gives UNDO_BLOCKED."""
    d.receive("BOLT", 10, "A")
    d.advance_day()
    expect_code("UNDO_BLOCKED", d.undo)
    assert d.stock("BOLT", "A") == 10


def test_C27_undo_reverts_transfer(d):
    """undo reverts a transfer at both ends and its cost."""
    d.receive("BOLT", 10, "A")
    before = cash(d)
    d.transfer("BOLT", 4, "A", "B")
    d.undo()
    assert (d.stock("BOLT", "A"), d.stock("BOLT", "B"), cash(d)) == (10, 0, before)


# ---------------------------------------------------------------- C28
def test_C28_save_is_versioned_json(d):
    """save returns JSON with "version": 1."""
    d.receive("BOLT", 10, "A")
    assert json.loads(d.save())["version"] == 1


def test_C28_round_trip_restores_state(d):
    """load(save()) restores the saved stock and cash."""
    d.receive("BOLT", 10, "A")
    s, saved_cash = d.save(), cash(d)
    d.receive("BOLT", 5, "A")
    d.ship("BOLT", 3, "A", 20)
    d.load(s)
    assert (d.stock("BOLT", "A"), cash(d)) == (10, saved_cash)


def test_C28_load_into_fresh_depot(d):
    """A save loads into a freshly constructed depot with the same stock and cash."""
    d.receive("BOLT", 10, "A")
    d.receive("GLUE", 2, "B")
    advance(d, 2)
    s = d.save()
    fresh = make()
    fresh.load(s)
    assert (fresh.stock("BOLT", "A"), fresh.stock("GLUE", "B"), cash(fresh)) == (10, 2, cash(d))


def test_C28_unknown_version_rejected(d):
    """A save with an unknown version gives BAD_SAVE and changes nothing."""
    d.receive("BOLT", 10, "A")
    doc = json.loads(d.save())
    doc["version"] = 2
    d.receive("BOLT", 5, "A")
    before = cash(d)
    expect_code("BAD_SAVE", d.load, json.dumps(doc))
    assert (d.stock("BOLT", "A"), cash(d)) == (15, before)


def test_C28_corrupt_input_rejected(d):
    """Corrupt save input gives BAD_SAVE and changes nothing."""
    d.receive("BOLT", 10, "A")
    before = cash(d)
    expect_code("BAD_SAVE", d.load, "{not json")
    expect_code("BAD_SAVE", d.load, "[]")
    assert (d.stock("BOLT", "A"), cash(d)) == (10, before)
