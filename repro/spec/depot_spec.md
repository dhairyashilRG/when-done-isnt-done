# Depot: a small multi-warehouse inventory and cash ledger

All money is integer cents. Errors are raised as `DepotError(code)`, and a failed operation changes nothing. Notifications are appended to an ordered log and read with `notifications()`.

| ID | Module | Clause |
|---|---|---|
| C01 | inventory | `add_item(sku, unit_cost, reorder_level, shelf_life_days=None)`. `unit_cost` > 0. `reorder_level` ≥ 0. A duplicate sku gives error `DUPLICATE_SKU`. |
| C02 | inventory | Any operation naming an unknown sku gives error `UNKNOWN_SKU`. |
| C03 | inventory | Warehouses are fixed at construction. Naming an unknown warehouse gives `UNKNOWN_WAREHOUSE`. |
| C04 | inventory | `receive(sku, qty, wh)`: `qty` is a positive int. A receipt that would push the warehouse's total units over its capacity gives `CAPACITY`, and nothing is received. |
| C05 | money | Receiving costs `unit_cost × qty`. If cash would go below 0, the result is `INSUFFICIENT_FUNDS` and nothing changes. |
| C06 | inventory | `ship(sku, qty, wh, price)`: if stock < `qty`, the result is `INSUFFICIENT_STOCK`. There is no partial shipment. |
| C07 | money | A shipment adds `price × qty` to cash. |
| C08 | money | `list_price(sku) = unit_cost × (1 + markup)`, rounded to a whole cent by the depot's rounding mode. |
| C09 | money | A sale of at least `bulk_threshold` units gets `bulk_discount_pct` off. |
| C10 | inventory | `transfer(sku, qty, from_wh, to_wh)` is atomic: stock and capacity rules apply at both ends. |
| C11 | money | Transfers cost the sending side money per unit (see the data table). |
| C12 | inventory | Lots are FIFO. Each receipt is a lot stamped with the current day, and shipping consumes the oldest lot first. |
| C13 | inventory | Perishable items (`shelf_life_days` set, at least 1): at `advance_day()`, lots older than the item's shelf life are discarded, and `EXPIRY(sku, wh, qty)` is emitted. |
| C14 | events | When a shipment leaves stock at or below `reorder_level`, `REORDER(sku, wh)` is emitted once. It is not emitted again until stock has risen above the level and fallen again. |
| C15 | suppliers | Every supplier starts with reliability 3, in the range [0, 5]. An on-time delivery adds 1 and a late one subtracts 1. |
| C16 | suppliers | `place_order(supplier, sku, qty, due_day)` and `deliver(order_id, day)`. A delivery is late if `day > due_day`. |
| C17 | suppliers | A supplier whose reliability is ≤ 1 is suspended. New orders to it give `SUPPLIER_SUSPENDED`, and `SUPPLIER_SUSPENDED(supplier)` is emitted once, when it becomes suspended. `reinstate(supplier)` sets reliability to 2. |
| C18 | money | A late delivery is paid less, by the late-penalty percentage. **The owner sets this percentage; it has not been decided. Do not choose a value.** |
| C19 | money | At `advance_day()`, storage costs `storage_cents_per_unit_day` for every unit held. This charge may take cash below 0. |
| C20 | events | When cash goes below 0, `OVERDRAWN` is emitted. While cash is below 0, `receive` gives `OVERDRAWN`. |
| C21 | events | Inside `advance_day()`, things happen in this order: the storage charge, then expiry, then the overdrawn check. |
| C22 | inventory | `audit(counts: dict[(sku, wh), int])`: for each mismatch with the ledger, `AUDIT_MISMATCH(sku, wh, ledger, counted)` is emitted. An empty `counts` gives error `EMPTY_AUDIT`. It is not "everything matches". |
| C23 | inventory | `return_goods(sku, qty, wh, price)` adds a new lot stamped with today's date and refunds `price × qty`. Returning more than was shipped of that sku gives `RETURN_EXCEEDS`. **Whether returned perishables are restocked or discarded is the owner's decision; it has not been made.** |
| C24 | inventory | `receive_bulk(list_of_receipts)` is all-or-nothing. |
| C25 | inventory | `stock(sku, wh=None)` returns the total across warehouses, or the stock in one warehouse. |
| C26 | inventory | `report()` returns rows `(sku, wh, units, value_cents)` sorted by sku, then wh, where `value = units × unit_cost`. |
| C27 | inventory | `undo()` reverts the last operation exactly, once. `undo()` after `advance_day()` gives `UNDO_BLOCKED`. |
| C28 | inventory | `save() -> str` (JSON with `"version": 1`) and `load(s)`. An unknown version or corrupt input gives `BAD_SAVE`, and nothing changes. |
| C29 | sim | `simulate(days, seed)` generates customer orders per day from the data table's demand ranges, using only a seeded RNG. The same seed gives the same orders; different seeds give different orders. |
| C30 | money | `turnover(start_day, end_day) = units shipped / average units held`. If the average is 0, the result is `None`, never 0 or infinity. |
| C31 | depot | The constructor takes `warehouses`, `capacities`, `opening_cash`, `rounding_mode`. **`rounding_mode` is the owner's choice and must be a required argument with no default.** |
| C32 | events | `notifications()` returns every notification, in the order of the operations that caused it. |
