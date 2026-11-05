"""The Depot: warehouses, lots, cash, suppliers and notifications."""
import copy
import json
import tomllib
from pathlib import Path

import money
from events import EventLog
from suppliers import SupplierBook

DATA = tomllib.loads(Path(__file__).with_name("data.toml").read_text())


class DepotError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Depot:
    def __init__(self, warehouses, capacities, opening_cash, rounding_mode):
        self.warehouses = list(warehouses)
        self.capacities = dict(capacities)
        self.rounding_mode = rounding_mode
        self._cash = opening_cash
        self._day = 0
        self.items = {}
        self.lots = {}
        self.reordered = set()
        self.shipped = {}
        self.returned = {}
        self.shipments = []
        self.held = {}
        self.suppliers = SupplierBook()
        self.log = EventLog()
        self.overdrawn = False
        self._undo = None

    # ---- views
    @property
    def cash(self):
        return self._cash

    @property
    def day(self):
        return self._day

    def notifications(self):
        return self.log.all()

    def reliability(self, supplier):
        if supplier not in self.suppliers.reliability:
            raise DepotError("UNKNOWN_SUPPLIER")
        return self.suppliers.reliability[supplier]

    def stock(self, sku, wh=None):
        self._sku(sku)
        if wh is None:
            return sum(self._units(sku, w) for w in self.warehouses)
        self._wh(wh)
        return self._units(sku, wh)

    def list_price(self, sku):
        self._sku(sku)
        return money.list_price(self.items[sku]["unit_cost"], DATA["markup"], self.rounding_mode)

    def report(self):
        rows = []
        for sku in sorted(self.items):
            for wh in sorted(self.warehouses):
                units = self._units(sku, wh)
                if units:
                    rows.append((sku, wh, units, units * self.items[sku]["unit_cost"]))
        return rows

    def turnover(self, start_day, end_day):
        held = [self.held.get(d, self._total()) for d in range(start_day, end_day + 1)]
        shipped = sum(q for d, q in self.shipments if start_day <= d <= end_day)
        return money.turnover(shipped, held)

    # ---- operations
    def add_item(self, sku, unit_cost, reorder_level, shelf_life_days=None):
        if sku in self.items:
            raise DepotError("DUPLICATE_SKU")
        if not isinstance(unit_cost, int) or unit_cost <= 0:
            raise DepotError("INVALID_UNIT_COST")
        if not isinstance(reorder_level, int) or reorder_level < 0:
            raise DepotError("INVALID_REORDER_LEVEL")
        self._snapshot()
        self.items[sku] = {"unit_cost": unit_cost, "reorder_level": reorder_level, "shelf_life_days": shelf_life_days}
        self.lots[sku] = {wh: [] for wh in self.warehouses}

    def receive(self, sku, qty, wh):
        self._check_receive(sku, qty, wh, 0, 0)
        self._snapshot()
        self._do_receive(sku, qty, wh)

    def receive_bulk(self, receipts):
        extra_units, extra_cost = {}, 0
        for sku, qty, wh in receipts:
            self._check_receive(sku, qty, wh, extra_units.get(wh, 0), extra_cost)
            extra_units[wh] = extra_units.get(wh, 0) + qty
            extra_cost += self.items[sku]["unit_cost"] * qty
        self._snapshot()
        for sku, qty, wh in receipts:
            self._do_receive(sku, qty, wh)

    def ship(self, sku, qty, wh, price):
        self._sku(sku)
        self._wh(wh)
        self._qty(qty)
        if self._units(sku, wh) < qty:
            raise DepotError("INSUFFICIENT_STOCK")
        self._snapshot()
        self._take(sku, wh, qty)
        self._cash += money.sale_revenue(price, qty, DATA["bulk_threshold"], DATA["bulk_discount_pct"],
                                         self.rounding_mode)
        self.shipped[sku] = self.shipped.get(sku, 0) + qty
        self.shipments.append((self._day, qty))
        if self._units(sku, wh) <= self.items[sku]["reorder_level"] and (sku, wh) not in self.reordered:
            self.log.emit("REORDER", sku, wh)
            self.reordered.add((sku, wh))
        self._cash_check()

    def transfer(self, sku, qty, from_wh, to_wh):
        self._sku(sku)
        self._wh(from_wh)
        self._wh(to_wh)
        self._qty(qty)
        if self._units(sku, from_wh) < qty:
            raise DepotError("INSUFFICIENT_STOCK")
        if self._wh_total(to_wh) + qty > self.capacities[to_wh]:
            raise DepotError("CAPACITY")
        self._snapshot()
        moved = self._take(sku, from_wh, qty)
        self.lots[sku][to_wh] = sorted(self.lots[sku][to_wh] + moved)
        self._cash += DATA["transfer_credit_cents_per_unit"] * qty

    def return_goods(self, sku, qty, wh, price):
        self._sku(sku)
        self._wh(wh)
        self._qty(qty)
        if self.shipped.get(sku, 0) - self.returned.get(sku, 0) < qty:
            raise DepotError("RETURN_EXCEEDS")
        self._snapshot()
        self.lots[sku][wh].append([self._day, qty])
        self.returned[sku] = self.returned.get(sku, 0) + qty
        self._cash -= price * qty
        self._cash_check()

    def place_order(self, supplier, sku, qty, due_day):
        self._sku(sku)
        self._qty(qty)
        if self.suppliers.suspended(supplier):
            raise DepotError("SUPPLIER_SUSPENDED")
        self._snapshot()
        return self.suppliers.place(supplier, sku, qty, due_day)

    def deliver(self, order_id, day):
        order = self.suppliers.orders.get(order_id)
        if order is None:
            raise DepotError("UNKNOWN_ORDER")
        if order["done"]:
            raise DepotError("ALREADY_DELIVERED")
        self._snapshot()
        late = day > order["due_day"]
        self._cash -= money.delivery_payment(self.items[order["sku"]]["unit_cost"], order["qty"], late,
                                             self.rounding_mode)
        order["done"] = True
        if self.suppliers.record(order["supplier"], late):
            self.log.emit("SUPPLIER_SUSPENDED", order["supplier"])
        self._cash_check()

    def reinstate(self, supplier):
        if supplier not in self.suppliers.reliability:
            raise DepotError("UNKNOWN_SUPPLIER")
        self._snapshot()
        self.suppliers.reliability[supplier] = 2

    def audit(self, counts):
        found = []
        for (sku, wh), counted in sorted(counts.items()):
            self._sku(sku)
            self._wh(wh)
            ledger = self._units(sku, wh)
            if ledger != counted:
                found.append((sku, wh, ledger, counted))
        if found:
            self._snapshot()
        for sku, wh, ledger, counted in found:
            self.log.emit("AUDIT_MISMATCH", sku, wh, ledger, counted)
        return found

    def advance_day(self):
        self.held[self._day] = self._total()
        self._snapshot()
        self._day += 1
        for sku in sorted(self.items):
            life = self.items[sku]["shelf_life_days"]
            if life is None:
                continue
            for wh in sorted(self.warehouses):
                lots = self.lots[sku][wh]
                gone = sum(q for d, q in lots if self._day - d > life)
                if gone:
                    self.lots[sku][wh] = [[d, q] for d, q in lots if self._day - d <= life]
                    self.log.emit("EXPIRY", sku, wh, gone)
        self._cash -= money.storage_charge(self._total(), DATA["storage_cents_per_unit_day"])
        self._cash_check()

    def undo(self):
        if self._undo is None:
            raise DepotError("NOTHING_TO_UNDO")
        self.__dict__.update(self._undo)
        self._undo = None

    def save(self):
        state = {"day": self._day, "cash": self._cash, "items": self.items,
                 "lots": self.lots, "shipped": self.shipped, "returned": self.returned}
        return json.dumps({"version": 1, "state": state})

    def load(self, s):
        try:
            doc = json.loads(s)
            if not isinstance(doc, dict) or doc.get("version") != 1:
                raise ValueError
            state = doc["state"]
            day, cash, items, lots = state["day"], state["cash"], state["items"], state["lots"]
        except (ValueError, KeyError, TypeError):
            raise DepotError("BAD_SAVE") from None
        self._snapshot()
        self._day, self._cash, self.items, self.lots = day, cash, items, lots
        self.shipped, self.returned = state.get("shipped", {}), state.get("returned", {})

    # ---- helpers
    def _snapshot(self):
        saved = {k: copy.deepcopy(v) for k, v in self.__dict__.items() if k not in ("_undo", "log")}
        saved["log"] = copy.deepcopy(self.log)
        self._undo = saved

    def _check_receive(self, sku, qty, wh, extra_units, extra_cost):
        self._sku(sku)
        self._wh(wh)
        self._qty(qty)
        if self._cash < 0:
            raise DepotError("OVERDRAWN")
        if self._wh_total(wh) + extra_units + qty > self.capacities[wh]:
            raise DepotError("CAPACITY")
        if self._cash - extra_cost - self.items[sku]["unit_cost"] * qty < 0:
            raise DepotError("INSUFFICIENT_FUNDS")

    def _do_receive(self, sku, qty, wh):
        self.lots[sku][wh].append([self._day, qty])
        self._cash -= self.items[sku]["unit_cost"] * qty

    def _take(self, sku, wh, qty):
        lots, taken = self.lots[sku][wh], []
        while qty:
            d, q = lots[0]
            use = min(q, qty)
            taken.append([d, use])
            qty -= use
            if use == q:
                lots.pop(0)
            else:
                lots[0][1] = q - use
        return taken

    def _cash_check(self):
        if self._cash < 0 and not self.overdrawn:
            self.log.emit("OVERDRAWN")
            self.overdrawn = True
        elif self._cash >= 0:
            self.overdrawn = False

    def _units(self, sku, wh):
        return sum(q for _, q in self.lots[sku][wh])

    def _wh_total(self, wh):
        return sum(self._units(s, wh) for s in self.items)

    def _total(self):
        return sum(self._wh_total(w) for w in self.warehouses)

    def _sku(self, sku):
        if sku not in self.items:
            raise DepotError("UNKNOWN_SKU")

    def _wh(self, wh):
        if wh not in self.capacities:
            raise DepotError("UNKNOWN_WAREHOUSE")

    def _qty(self, qty):
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise DepotError("INVALID_QTY")
