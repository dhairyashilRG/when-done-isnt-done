"""Differential driver (subprocess side): run fixed random operation sequences against one implementation.

Usage: python diff_driver.py HELDOUT_DIR SEEDS_JSON N_OPS OUT_JSON   (DEPOT_IMPL_DIR names the implementation)

The sequence for a seed depends only on the seed (never on the implementation's answers), covers
every clause's operations, and injects the gate values (rounding ROUND_HALF_EVEN, late penalty 25).
After every operation it records the result and a state digest: cash, stock per (sku, wh),
supplier reliabilities, and the notifications that operation added. FILM (planted defect D2) and
perishable returns (owner gate G3) are left out so the sequences compare spec behaviour only.

Amendment A6 (2026-11-04): the trace records only what the spec pins down. Reliability is recorded
only for suppliers that exist (a supplier exists from its first successful order); `simulate` is
recorded as the properties C29 fixes (number of days, quantities inside the demand ranges, same
seed gives the same orders, a different seed gives different orders), not the exact orders; an
error code the spec does not name is recorded as "OTHER" (any DepotError); and a Decimal or
Fraction result is recorded by its value, not its type name. `diff_driver_v1.py` is the original
driver, kept unchanged because the E3 oracle-editing stage was recorded with it.
"""
import json
import random
import sys
import tomllib
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

# Error codes the spec names (brief 2.1). Any other DepotError code is not pinned by the spec.
SPEC_CODES = {"DUPLICATE_SKU", "UNKNOWN_SKU", "UNKNOWN_WAREHOUSE", "CAPACITY", "INSUFFICIENT_FUNDS",
              "INSUFFICIENT_STOCK", "SUPPLIER_SUSPENDED", "OVERDRAWN", "EMPTY_AUDIT", "RETURN_EXCEEDS",
              "UNDO_BLOCKED", "BAD_SAVE"}
SIM_OTHER_SEED_OFFSET = 1000
# Operations that change state under every reading of the spec. `undo` reverts the last operation;
# implementations differ on whether failed calls, queries, audits or save/load count as one, but the
# undone operation is never older than the last of these.
STATE_CHANGING = {"receive", "ship", "transfer", "advance_day", "return_goods", "receive_bulk", "place_order",
                  "deliver", "reinstate"}


def _demand():
    """The data table's demand ranges (C29), read from the harness's copy of the spec's data table."""
    path = Path(__file__).resolve().parents[2] / "spec" / "data.toml"
    with open(path, "rb") as fh:
        return {sku: (int(r["min"]), int(r["max"])) for sku, r in tomllib.load(fh)["demand"].items()}


def _sim_properties(A, days, seed):
    """What C29 pins down about simulate(days, seed), and nothing else."""
    sim = A.get("simulate")
    out = A.norm_sim(sim(days, seed))
    again = A.norm_sim(sim(days, seed))
    other = A.norm_sim(sim(days, seed + SIM_OTHER_SEED_OFFSET))
    demand = _demand()

    def in_range(order):
        if not isinstance(order, (list, tuple)) or len(order) != 2:
            return False
        sku, qty = order
        return (sku in demand and isinstance(qty, int) and not isinstance(qty, bool)
                and demand[sku][0] <= qty <= demand[sku][1])

    return {"days": len(out), "quantities_in_range": all(in_range(o) for day in out for o in day),
            "same_seed_same_orders": out == again, "other_seed_different_orders": out != other}


def _norm(x):
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _norm(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (float, Decimal, Fraction)):
        return round(float(x), 6)
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    return repr(type(x).__name__)


SKUS = ["BOLT", "GLUE"]
WHS = ["A", "B"]
WEIGHTS = {"receive": 14, "ship": 14, "transfer": 7, "advance_day": 10, "audit": 4, "return_goods": 4,
           "receive_bulk": 4, "place_order": 7, "deliver": 7, "reinstate": 2, "list_price": 3, "stock": 4,
           "report": 3, "undo": 4, "save_load": 3, "turnover": 3, "simulate": 2, "bad_sku": 2, "bad_wh": 2,
           "add_item_dup": 1}


def gen_ops(seed, n):
    rng = random.Random(seed)
    names, weights = zip(*WEIGHTS.items())
    ops, day = [], 0
    for _ in range(n):
        op = rng.choices(names, weights)[0]
        sku, wh = rng.choice(SKUS), rng.choice(WHS)
        other = "B" if wh == "A" else "A"
        if op == "receive":
            args = [sku, rng.randint(1, 60), wh]
        elif op == "ship":
            args = [sku, rng.randint(1, 45), wh, rng.randint(5, 40)]
        elif op == "transfer":
            args = [sku, rng.randint(1, 30), wh, other]
        elif op == "advance_day":
            args = []
            day += 1
        elif op == "audit":
            args = [[] if rng.random() < 0.15 else
                    [[rng.choice(SKUS), rng.choice(WHS), rng.randint(0, 60)] for _ in range(rng.randint(1, 2))]]
        elif op == "return_goods":
            args = ["BOLT", rng.randint(1, 15), wh, rng.randint(5, 30)]
        elif op == "receive_bulk":
            args = [[[rng.choice(SKUS), rng.randint(1, 40), rng.choice(WHS)] for _ in range(rng.randint(1, 3))]]
        elif op == "place_order":
            args = [rng.choice(["S1", "S2"]), sku, rng.randint(1, 10), day + rng.randint(0, 3)]
        elif op == "deliver":
            args = [rng.randint(0, 99), day + rng.randint(0, 4)]
        elif op == "reinstate":
            args = [rng.choice(["S1", "S2"])]
        elif op == "stock":
            args = [sku, rng.choice([None, wh])]
        elif op in ("list_price",):
            args = [sku]
        elif op == "turnover":
            args = [0, day]
        elif op == "simulate":
            args = [5, rng.randint(0, 9)]
        else:
            args = []
        ops.append([op, args])
    return ops


def main():
    heldout_dir, seeds, n_ops, out_path = sys.argv[1], json.loads(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    sys.path.insert(0, heldout_dir)
    import heldout_adapter as A

    def snapshot(d, n_before, known):
        try:
            cash = A.cash(d)
        except Exception as exc:
            cash = f"exc:{type(exc).__name__}"
        stock = []
        for s in SKUS:
            for w in WHS:
                try:
                    stock.append(d.stock(s, w))
                except Exception as exc:
                    stock.append(f"exc:{type(exc).__name__}")
        rel = {}
        for sup in sorted(known):  # only suppliers that exist; the spec says nothing about others
            try:
                rel[sup] = d.reliability(sup)
            except Exception:
                rel[sup] = None
        try:
            notes = A.notes(d)
        except Exception:
            notes = []
        return {"cash": cash, "stock": stock, "rel": rel, "new_notes": _norm(notes[n_before:])}, len(notes)

    traces = {}
    for seed in seeds:
        steps = []
        try:
            d = A.make(warehouses=("A", "B"), capacities={"A": 400, "B": 300}, opening_cash=20_000,
                       rounding_mode="ROUND_HALF_EVEN", late_penalty_pct=25)
        except Exception as exc:
            traces[str(seed)] = {"setup_error": f"{type(exc).__name__}: {exc}", "steps": []}
            continue
        E = A.Error()
        orders = []
        n_notes = 0
        known = set()           # suppliers that exist: at least one successful order
        undo_may_remove = None  # a supplier whose first order was the last state-changing operation
        for op, args in gen_ops(seed, n_ops):
            new_supplier = None
            try:
                if op == "audit":
                    res = d.audit({(s, w): c for s, w, c in args[0]})
                    res = None
                elif op == "receive_bulk":
                    res = d.receive_bulk([tuple(r) for r in args[0]])
                    res = None
                elif op == "place_order":
                    oid = d.place_order(*args)
                    orders.append(oid)
                    if args[0] not in known:
                        new_supplier = args[0]
                        known.add(args[0])
                    res = None
                elif op == "deliver":
                    if not orders:
                        res = "no-orders"
                    else:
                        d.deliver(orders[args[0] % len(orders)], args[1])
                        res = None
                elif op == "stock":
                    res = d.stock(args[0]) if args[1] is None else d.stock(args[0], args[1])
                elif op == "report":
                    res = [list(r) for r in A.report(d)]
                elif op == "save_load":
                    d.load(d.save())
                    res = None
                elif op == "simulate":
                    res = _sim_properties(A, *args)
                elif op == "bad_sku":
                    d.receive("NOPE", 1, "A")
                    res = None
                elif op == "bad_wh":
                    d.ship("BOLT", 1, "Z", 10)
                    res = None
                elif op == "add_item_dup":
                    d.add_item("BOLT", 12, 50)
                    res = None
                elif op in ("list_price", "turnover"):
                    res = getattr(d, op)(*args)
                else:
                    getattr(d, op)(*args)
                    res = None
                    if op == "undo" and undo_may_remove is not None:
                        known.discard(undo_may_remove)  # the undone call may be that supplier's first order
                        undo_may_remove = None
                result = ["ok", _norm(res)]
            except E as exc:
                code = A.code_of(exc)
                result = ["err", code if code in SPEC_CODES else "OTHER"]
            except Exception as exc:
                result = ["exc", type(exc).__name__]
            if op in STATE_CHANGING and result[0] == "ok":
                undo_may_remove = new_supplier
            snap, n_notes = snapshot(d, n_notes, known)
            steps.append({"op": op, "args": _norm(args), "result": result, **snap})
        traces[str(seed)] = {"steps": steps}
    with open(out_path, "w") as fh:
        json.dump(traces, fh)


if __name__ == "__main__":
    main()
