"""The harness author's own reference implementation of the Depot spec (all 32 clauses).

Written from the spec's prose intent (brief 2.1, with the 2.3 intents for the planted defects):

* D1: ``transfer_credit_cents_per_unit`` is applied as a *cost* to the sending side (C11 prose).
* D2: ``shelf_life_days = 0`` is rejected at ``add_item`` with ``DepotError("INVALID_SHELF_LIFE")``.

Owner-gate values are never chosen here; they are injected as required constructor arguments:
``rounding_mode`` (G1, C31), ``late_penalty_pct`` (G2, C18), ``perishable_return_policy``
(G3, C23: ``"restock"`` or ``"discard"``).

This file is self-contained (standard library only) so the harness can copy it into a temporary
directory and run it in a subprocess exactly like agent-written code.

Interpretations of points the spec leaves open (all recorded in DECISIONS.md):

* ``day`` starts at 0; ``advance_day()`` adds 1 and then charges storage, expires lots, and runs
  the overdrawn check (C21).
* A lot of age ``day - lot_day`` is discarded when the age is *greater than* the shelf life (C13).
* A supplier exists from its first ``place_order``. ``deliver`` pays the supplier
  ``unit_cost * qty`` (less the penalty when late); it names no warehouse, so it moves no stock.
* Voluntary payments out (receive, transfer cost, delivery payment, refund) may not take cash
  below 0 (``INSUFFICIENT_FUNDS``); only the storage charge may (C19).
* ``OVERDRAWN`` is emitted when cash goes from >= 0 to < 0.
* ``undo()`` restores the full state (including the notification log); it is single-level.
* ``turnover`` uses end-of-day units held for past days and the live value for today.
"""
from __future__ import annotations

import copy
import json
import random
import tomllib
from decimal import Decimal
from pathlib import Path

ROUNDING_MODES = {
    "ROUND_UP", "ROUND_DOWN", "ROUND_CEILING", "ROUND_FLOOR",
    "ROUND_HALF_UP", "ROUND_HALF_DOWN", "ROUND_HALF_EVEN", "ROUND_05UP",
}
PERISHABLE_RETURN_POLICIES = {"restock", "discard"}


class DepotError(Exception):
    def __init__(self, code: str, *details):
        super().__init__(code, *details)
        self.code = code


def _find_data_path() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "data.toml", Path.cwd() / "data.toml", here.parent / "spec" / "data.toml"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("data.toml not found next to the module or in the working directory")


def load_data(path: str | Path | None = None) -> dict:
    with open(path or _find_data_path(), "rb") as fh:
        return tomllib.load(fh)


def _is_count(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def simulate(days: int, seed: int, data: dict | None = None) -> list[list[tuple[str, int]]]:
    """C29: customer orders per day from the demand ranges, using only a private seeded RNG."""
    if not _is_count(days) or days < 0:
        raise DepotError("INVALID_ARGUMENT")
    demand = (data or load_data())["demand"]
    rng = random.Random(seed)
    out = []
    for _ in range(days):
        out.append([(sku, rng.randint(demand[sku]["min"], demand[sku]["max"])) for sku in sorted(demand)])
    return out


class Depot:
    def __init__(self, warehouses, capacities, opening_cash, rounding_mode, *,
                 late_penalty_pct, perishable_return_policy, data: dict | None = None):
        warehouses = list(warehouses)
        if not warehouses or len(set(warehouses)) != len(warehouses) or not all(isinstance(w, str) for w in warehouses):
            raise DepotError("INVALID_ARGUMENT")
        if not isinstance(capacities, dict) or set(capacities) != set(warehouses):
            raise DepotError("INVALID_ARGUMENT")
        if not all(_is_count(c) and c >= 0 for c in capacities.values()):
            raise DepotError("INVALID_ARGUMENT")
        if not _is_count(opening_cash):
            raise DepotError("INVALID_ARGUMENT")
        if rounding_mode not in ROUNDING_MODES:
            raise DepotError("INVALID_ROUNDING_MODE")
        if not isinstance(late_penalty_pct, (int, float)) or isinstance(late_penalty_pct, bool) or not 0 <= late_penalty_pct <= 100:
            raise DepotError("INVALID_ARGUMENT")
        if perishable_return_policy not in PERISHABLE_RETURN_POLICIES:
            raise DepotError("INVALID_ARGUMENT")
        self._warehouses = sorted(warehouses)
        self._capacities = dict(capacities)
        self._rounding_mode = rounding_mode
        self._late_penalty_pct = Decimal(str(late_penalty_pct))
        self._perishable_policy = perishable_return_policy
        d = data or load_data()
        self._markup = Decimal(str(d["markup"]))
        self._bulk_threshold = int(d["bulk_threshold"])
        self._bulk_discount_pct = Decimal(str(d["bulk_discount_pct"]))
        self._storage = int(d["storage_cents_per_unit_day"])
        self._transfer_cost = int(d["transfer_credit_cents_per_unit"])  # D1: applied as a cost
        self._s = {
            "day": 0,
            "cash": opening_cash,
            "items": {},
            "lots": {},            # sku -> wh -> [[day, qty], ...] oldest first
            "armed": {},           # "sku|wh" -> bool (REORDER re-arm state)
            "shipped": {},         # sku -> units shipped (all time)
            "returned": {},        # sku -> units returned (all time)
            "shipments": [],       # [[day, qty], ...]
            "held": {},            # str(day) -> end-of-day units held
            "suppliers": {},       # name -> reliability
            "orders": {},          # str(id) -> order
            "next_order": 1,
            "overdrawn": opening_cash < 0,
            "notifications": [],
        }
        self._undo: dict | None = None
        self._undo_blocked = False

    # ------------------------------------------------------------------ read-only views
    @property
    def cash(self) -> int:
        return self._s["cash"]

    @property
    def day(self) -> int:
        return self._s["day"]

    def notifications(self) -> list[tuple]:
        """C32: every notification, in the order of the operations that caused it."""
        return [tuple(n) for n in self._s["notifications"]]

    def reliability(self, supplier: str) -> int:
        if supplier not in self._s["suppliers"]:
            raise DepotError("UNKNOWN_SUPPLIER")
        return self._s["suppliers"][supplier]

    def stock(self, sku, wh=None) -> int:
        """C25."""
        self._need_sku(sku)
        if wh is None:
            return sum(self._units(sku, w) for w in self._warehouses)
        self._need_wh(wh)
        return self._units(sku, wh)

    def list_price(self, sku) -> int:
        """C08: unit_cost * (1 + markup), rounded to a whole cent by the depot's rounding mode."""
        self._need_sku(sku)
        return self._round(Decimal(self._s["items"][sku]["unit_cost"]) * (1 + self._markup))

    def report(self) -> list[tuple]:
        """C26: rows (sku, wh, units, value_cents) sorted by sku then wh; rows with units > 0."""
        rows = []
        for sku in sorted(self._s["items"]):
            for wh in self._warehouses:
                units = self._units(sku, wh)
                if units > 0:
                    rows.append((sku, wh, units, units * self._s["items"][sku]["unit_cost"]))
        return rows

    def turnover(self, start_day, end_day):
        """C30: units shipped / average units held over [start_day, end_day]; None if the average is 0."""
        if not (_is_count(start_day) and _is_count(end_day)) or start_day < 0 or end_day < start_day or end_day > self.day:
            raise DepotError("INVALID_RANGE")
        held = [self._held_on(d) for d in range(start_day, end_day + 1)]
        average = sum(held) / len(held)
        if average == 0:
            return None
        shipped = sum(q for d, q in self._s["shipments"] if start_day <= d <= end_day)
        return shipped / average

    # ------------------------------------------------------------------ operations
    def add_item(self, sku, unit_cost, reorder_level, shelf_life_days=None):
        """C01 (and D2: a shelf life below 1 is rejected)."""
        def op():
            if not isinstance(sku, str) or not sku:
                raise DepotError("INVALID_ARGUMENT")
            if sku in self._s["items"]:
                raise DepotError("DUPLICATE_SKU")
            if not _is_count(unit_cost) or unit_cost <= 0:
                raise DepotError("INVALID_UNIT_COST")
            if not _is_count(reorder_level) or reorder_level < 0:
                raise DepotError("INVALID_REORDER_LEVEL")
            if shelf_life_days is not None and (not _is_count(shelf_life_days) or shelf_life_days < 1):
                raise DepotError("INVALID_SHELF_LIFE")
            self._s["items"][sku] = {"unit_cost": unit_cost, "reorder_level": reorder_level,
                                     "shelf_life_days": shelf_life_days}
            self._s["lots"][sku] = {wh: [] for wh in self._warehouses}
        self._mutate(op)

    def receive(self, sku, qty, wh):
        """C04, C05, C12 (new lot stamped today), C20 (blocked while overdrawn)."""
        self._mutate(lambda: self._receive(sku, qty, wh))

    def receive_bulk(self, receipts):
        """C24: all-or-nothing."""
        def op():
            for receipt in receipts:
                sku, qty, wh = receipt
                self._receive(sku, qty, wh)
        self._mutate(op)

    def ship(self, sku, qty, wh, price):
        """C06, C07, C09, C12 (FIFO), C14 (REORDER)."""
        def op():
            self._need_sku(sku)
            self._need_wh(wh)
            self._need_qty(qty)
            if not _is_count(price) or price < 0:
                raise DepotError("INVALID_PRICE")
            if self._units(sku, wh) < qty:
                raise DepotError("INSUFFICIENT_STOCK")
            self._take_fifo(sku, wh, qty)
            revenue = Decimal(price) * qty
            if qty >= self._bulk_threshold:
                revenue = revenue * (100 - self._bulk_discount_pct) / 100
            self._s["cash"] += self._round(revenue)
            self._s["shipped"][sku] = self._s["shipped"].get(sku, 0) + qty
            self._s["shipments"].append([self.day, qty])
            key = f"{sku}|{wh}"
            if self._units(sku, wh) <= self._s["items"][sku]["reorder_level"] and self._s["armed"].get(key, True):
                self._emit("REORDER", sku, wh)
                self._s["armed"][key] = False
            self._cash_check()
        self._mutate(op)

    def transfer(self, sku, qty, from_wh, to_wh):
        """C10 (atomic, both ends' rules) and C11 (a cost per unit to the sending side; D1)."""
        def op():
            self._need_sku(sku)
            self._need_wh(from_wh)
            self._need_wh(to_wh)
            self._need_qty(qty)
            if from_wh == to_wh:
                raise DepotError("SAME_WAREHOUSE")
            if self._units(sku, from_wh) < qty:
                raise DepotError("INSUFFICIENT_STOCK")
            if self._wh_total(to_wh) + qty > self._capacities[to_wh]:
                raise DepotError("CAPACITY")
            cost = self._transfer_cost * qty
            if self.cash - cost < 0:
                raise DepotError("INSUFFICIENT_FUNDS")
            moved = self._take_fifo(sku, from_wh, qty)
            lots = self._s["lots"][sku][to_wh]
            lots.extend(moved)
            lots.sort(key=lambda lot: lot[0])
            self._s["cash"] -= cost
            self._rearm(sku, to_wh)
            self._cash_check()
        self._mutate(op)

    def return_goods(self, sku, qty, wh, price):
        """C23: a new lot stamped today, refund price * qty; RETURN_EXCEEDS; G3 policy injected."""
        def op():
            self._need_sku(sku)
            self._need_wh(wh)
            self._need_qty(qty)
            if not _is_count(price) or price < 0:
                raise DepotError("INVALID_PRICE")
            if self._s["shipped"].get(sku, 0) - self._s["returned"].get(sku, 0) < qty:
                raise DepotError("RETURN_EXCEEDS")
            refund = price * qty
            if self.cash - refund < 0:
                raise DepotError("INSUFFICIENT_FUNDS")
            perishable = self._s["items"][sku]["shelf_life_days"] is not None
            if not perishable or self._perishable_policy == "restock":
                if self._wh_total(wh) + qty > self._capacities[wh]:
                    raise DepotError("CAPACITY")
                self._s["lots"][sku][wh].append([self.day, qty])
            self._s["returned"][sku] = self._s["returned"].get(sku, 0) + qty
            self._s["cash"] -= refund
            self._rearm(sku, wh)
            self._cash_check()
        self._mutate(op)

    def place_order(self, supplier, sku, qty, due_day):
        """C16, C17 (suspended suppliers take no new orders)."""
        result = {}

        def op():
            self._need_sku(sku)
            self._need_qty(qty)
            if not isinstance(supplier, str) or not supplier or not _is_count(due_day):
                raise DepotError("INVALID_ARGUMENT")
            reliability = self._s["suppliers"].setdefault(supplier, 3)
            if reliability <= 1:
                raise DepotError("SUPPLIER_SUSPENDED")
            order_id = self._s["next_order"]
            self._s["next_order"] += 1
            self._s["orders"][str(order_id)] = {"supplier": supplier, "sku": sku, "qty": qty,
                                                 "due_day": due_day, "delivered": False}
            result["id"] = order_id
        self._mutate(op)
        return result["id"]

    def deliver(self, order_id, day):
        """C15, C16 (late if day > due_day), C17 (suspension), C18 (late penalty, injected)."""
        def op():
            order = self._s["orders"].get(str(order_id))
            if order is None:
                raise DepotError("UNKNOWN_ORDER")
            if order["delivered"]:
                raise DepotError("ALREADY_DELIVERED")
            if not _is_count(day):
                raise DepotError("INVALID_ARGUMENT")
            late = day > order["due_day"]
            amount = Decimal(self._s["items"][order["sku"]]["unit_cost"]) * order["qty"]
            if late:
                amount = amount * (100 - self._late_penalty_pct) / 100
            payment = self._round(amount)
            if self.cash - payment < 0:
                raise DepotError("INSUFFICIENT_FUNDS")
            self._s["cash"] -= payment
            order["delivered"] = True
            name = order["supplier"]
            before = self._s["suppliers"][name]
            after = max(0, before - 1) if late else min(5, before + 1)
            self._s["suppliers"][name] = after
            if before > 1 and after <= 1:
                self._emit("SUPPLIER_SUSPENDED", name)
            self._cash_check()
        self._mutate(op)

    def reinstate(self, supplier):
        """C17: reliability set to 2."""
        def op():
            if supplier not in self._s["suppliers"]:
                raise DepotError("UNKNOWN_SUPPLIER")
            self._s["suppliers"][supplier] = 2
        self._mutate(op)

    def audit(self, counts):
        """C22: AUDIT_MISMATCH per mismatch; an empty count is an error, never 'all match'."""
        found = []

        def op():
            if not counts:
                raise DepotError("EMPTY_AUDIT")
            checked = []
            for key, counted in counts.items():
                sku, wh = key
                self._need_sku(sku)
                self._need_wh(wh)
                if not _is_count(counted):
                    raise DepotError("INVALID_ARGUMENT")
                checked.append((sku, wh, counted))
            for sku, wh, counted in sorted(checked):
                ledger = self._units(sku, wh)
                if ledger != counted:
                    self._emit("AUDIT_MISMATCH", sku, wh, ledger, counted)
                    found.append((sku, wh, ledger, counted))
        self._mutate(op)
        return found

    def advance_day(self):
        """C19, C13, C20 in the C21 order: storage charge, then expiry, then the overdrawn check."""
        self._s["held"][str(self.day)] = self._total_units()
        self._s["day"] += 1
        self._s["cash"] -= self._storage * self._total_units()
        for sku in sorted(self._s["items"]):
            life = self._s["items"][sku]["shelf_life_days"]
            if life is None:
                continue
            for wh in self._warehouses:
                lots = self._s["lots"][sku][wh]
                expired = sum(q for d, q in lots if self.day - d > life)
                if expired:
                    self._s["lots"][sku][wh] = [[d, q] for d, q in lots if self.day - d <= life]
                    self._emit("EXPIRY", sku, wh, expired)
        self._cash_check()
        self._undo = None
        self._undo_blocked = True

    def undo(self):
        """C27: revert the last operation exactly, once; blocked right after advance_day()."""
        if self._undo_blocked:
            raise DepotError("UNDO_BLOCKED")
        if self._undo is None:
            raise DepotError("NOTHING_TO_UNDO")
        self._s = self._undo
        self._undo = None

    def save(self) -> str:
        """C28."""
        return json.dumps({"version": 1, "warehouses": self._warehouses, "state": self._s}, sort_keys=True)

    def load(self, s):
        """C28: unknown version or corrupt input gives BAD_SAVE and changes nothing."""
        try:
            doc = json.loads(s)
            if not isinstance(doc, dict) or doc.get("version") != 1:
                raise ValueError("version")
            if doc.get("warehouses") != self._warehouses:
                raise ValueError("warehouses")
            state = doc["state"]
            if not isinstance(state, dict) or set(state) != set(self._s):
                raise ValueError("keys")
            if not _is_count(state["day"]) or not _is_count(state["cash"]):
                raise ValueError("types")
            for sku, by_wh in state["lots"].items():
                if sku not in state["items"] or set(by_wh) != set(self._warehouses):
                    raise ValueError("lots")
                for lots in by_wh.values():
                    for d, q in lots:
                        if not (_is_count(d) and _is_count(q) and q > 0):
                            raise ValueError("lot")
        except DepotError:
            raise
        except Exception:
            raise DepotError("BAD_SAVE") from None

        def op():
            self._s = copy.deepcopy(state)
        self._mutate(op)

    # ------------------------------------------------------------------ internals
    def _mutate(self, fn):
        before = copy.deepcopy(self._s)
        try:
            fn()
        except DepotError:
            self._s = before
            raise
        except Exception:
            self._s = before
            raise
        self._undo = before
        self._undo_blocked = False

    def _receive(self, sku, qty, wh):
        self._need_sku(sku)
        self._need_wh(wh)
        self._need_qty(qty)
        if self.cash < 0:
            raise DepotError("OVERDRAWN")
        if self._wh_total(wh) + qty > self._capacities[wh]:
            raise DepotError("CAPACITY")
        cost = self._s["items"][sku]["unit_cost"] * qty
        if self.cash - cost < 0:
            raise DepotError("INSUFFICIENT_FUNDS")
        self._s["lots"][sku][wh].append([self.day, qty])
        self._s["cash"] -= cost
        self._rearm(sku, wh)

    def _take_fifo(self, sku, wh, qty) -> list[list[int]]:
        lots = self._s["lots"][sku][wh]
        taken = []
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

    def _rearm(self, sku, wh):
        if self._units(sku, wh) > self._s["items"][sku]["reorder_level"]:
            self._s["armed"][f"{sku}|{wh}"] = True

    def _cash_check(self):
        if self.cash < 0 and not self._s["overdrawn"]:
            self._emit("OVERDRAWN")
            self._s["overdrawn"] = True
        elif self.cash >= 0:
            self._s["overdrawn"] = False

    def _emit(self, kind, *args):
        self._s["notifications"].append([kind, *args])

    def _units(self, sku, wh) -> int:
        return sum(q for _, q in self._s["lots"][sku][wh])

    def _wh_total(self, wh) -> int:
        return sum(self._units(sku, wh) for sku in self._s["items"])

    def _total_units(self) -> int:
        return sum(self._wh_total(wh) for wh in self._warehouses)

    def _held_on(self, day) -> int:
        if day == self.day:
            return self._total_units()
        return self._s["held"].get(str(day), 0)

    def _round(self, amount: Decimal) -> int:
        return int(Decimal(amount).quantize(Decimal(1), rounding=self._rounding_mode))

    def _need_sku(self, sku):
        if sku not in self._s["items"]:
            raise DepotError("UNKNOWN_SKU")

    def _need_wh(self, wh):
        if wh not in self._capacities:
            raise DepotError("UNKNOWN_WAREHOUSE")

    def _need_qty(self, qty):
        if not _is_count(qty) or qty <= 0:
            raise DepotError("INVALID_QTY")
