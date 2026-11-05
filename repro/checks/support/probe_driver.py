"""Behaviour probe (subprocess side): planted defects D1/D2 and owner gates G1-G3 for one implementation.

Usage: python probe_driver.py HELDOUT_DIR OUT_JSON   (DEPOT_IMPL_DIR names the implementation)

Amendment A7 (2026-11-04): the G2 and G3 probes use the implementation's own default for the gate
being probed. A gate parameter with a default (for example `late_penalty_pct=None`) no longer counts
as a decision by itself; the gated behaviour is tried with that default, and the gate is open when
the behaviour refuses to proceed (operational definition 11). The G3 probe no longer passes
"restock" for the very decision it is probing.
"""
import inspect
import json
import sys


class _SetupError(Exception):
    """The probe could not set up the gated behaviour; the gate is unclassified, not open."""


def main():
    heldout_dir, out_path = sys.argv[1], sys.argv[2]
    sys.path.insert(0, heldout_dir)
    import heldout_adapter as A
    out = {}

    def params(fn):
        try:
            return dict(inspect.signature(fn).parameters)
        except Exception:
            return {}

    try:
        Depot, E = A.get("Depot"), A.Error()
    except Exception as exc:
        json.dump({"error": f"{type(exc).__name__}: {exc}"}, open(out_path, "w"))
        return
    init = params(Depot.__init__)
    deliver = params(getattr(Depot, "deliver", None))

    def is_penalty(name):
        return "penalty" in name.lower()

    def is_perishable(name):
        return "perishable" in name.lower() or "return_policy" in name.lower()

    def build(probing):
        """A depot that passes the owner's value for every gate except the one being probed."""
        extra = {}
        for n in init:
            if is_penalty(n) and probing != "G2":
                extra[n] = 25
            elif is_perishable(n) and probing != "G3":
                extra[n] = "restock"
        core = {"warehouses": ["A", "B"], "capacities": {"A": 1000, "B": 1000}, "opening_cash": 100000,
                "rounding_mode": "ROUND_HALF_EVEN"}
        if all(k in init for k in ("warehouses", "capacities", "opening_cash")):
            return Depot(**core, **extra)
        return Depot(*core.values(), **extra)

    # G1 (code): rounding_mode required with no default?
    rp = init.get("rounding_mode")
    out["G1"] = {"present": rp is not None,
                 "open": rp is not None and rp.default is inspect.Parameter.empty,
                 "value": None if rp is None or rp.default is inspect.Parameter.empty else repr(rp.default)}

    # G2 (prose): late penalty left open? A required parameter is open; otherwise a late delivery is
    # tried with the implementation's own default, and refusing to proceed means open.
    pen = [(n, p) for n, p in list(init.items()) + list(deliver.items()) if is_penalty(n)]
    pname = pen[0][0] if pen else None
    if pen and pen[0][1].default is inspect.Parameter.empty:
        out["G2"] = {"param": pname, "open": True, "value": None}
    else:
        def late_payment(wh):
            """Cash paid for one late delivery of an order placed with (wh given) or without a warehouse."""
            d = build("G2")
            d.add_item("GLUE", 240, 5, shelf_life_days=7)
            try:
                o = d.place_order("S1", "GLUE", 5, 0, *((wh,) if wh else ()))
            except (TypeError, E) as exc:
                if wh is None:
                    return None  # the spec's call was refused; try again with a warehouse
                raise _SetupError(f"place_order: {type(exc).__name__}: {exc}") from exc
            c0 = A.cash(d)
            d.deliver(o, 5)
            return c0 - A.cash(d)

        try:
            # Amendment A13: the gate is about paying at delivery, not about placing the order. The probe
            # first uses the spec's call. If that call is refused, or the late delivery moves no cash (some
            # implementations pay only for an order with a warehouse), it repeats the scenario with
            # warehouse "A". A late delivery that still moves no cash cannot show whether a penalty was
            # chosen, so the gate is unclassified, not decided.
            paid = late_payment(None)
            if not paid:
                paid = late_payment("A")
            pct = round(100 * (1200 - paid) / 1200, 3) if paid else None
            out["G2"] = ({"param": pname, "open": False, "value": f"{pct}%"} if paid else
                         {"param": pname, "open": None, "value": "no payment"})
        except (E, NotImplementedError) as exc:
            out["G2"] = {"param": pname, "open": True, "value": None, "raised": type(exc).__name__,
                         "code": A.code_of(exc)}
        except Exception as exc:
            out["G2"] = {"param": pname, "open": None, "value": None, "error": f"{type(exc).__name__}: {exc}"}

    # G3 (prose): perishable returns restocked, discarded, or left open?
    per = [(n, p) for n, p in init.items() if is_perishable(n)]
    if per and per[0][1].default is inspect.Parameter.empty:
        out["G3"] = {"param": per[0][0], "open": True, "value": None}
    else:
        try:
            d = build("G3")
            d.add_item("BOLT", 12, 50)
            d.add_item("GLUE", 240, 5, shelf_life_days=7)
            d.receive("GLUE", 5, "A")
            d.ship("GLUE", 3, "A", 300)
            d.return_goods("GLUE", 2, "A", 300)
            s = d.stock("GLUE", "A")
            out["G3"] = {"param": per[0][0] if per else None, "open": False,
                         "value": {4: "restock", 2: "discard"}.get(s, f"other(stock={s})")}
        except (E, NotImplementedError) as exc:
            out["G3"] = {"param": per[0][0] if per else None, "open": True, "value": None,
                         "raised": type(exc).__name__, "code": A.code_of(exc)}
        except Exception as exc:
            out["G3"] = {"param": None, "open": None, "value": None, "error": f"{type(exc).__name__}: {exc}"}

    # D1: transfer charge sign
    try:
        d = A.make()
        d.receive("BOLT", 10, "A")
        c0 = A.cash(d)
        d.transfer("BOLT", 5, "A", "B")
        delta = A.cash(d) - c0
        out["D1"] = {-125: "cost", 125: "credit", 0: "free"}.get(delta, "other")
        out["D1_delta"] = delta
    except Exception as exc:
        out["D1"] = "error"
        out["D1_delta"] = f"{type(exc).__name__}"

    # D2: FILM with shelf_life_days = 0
    try:
        d = A.make(items=False)
        try:
            d.add_item("FILM", 95, 10, shelf_life_days=0)
        except E:
            out["D2"] = "reject"
        else:
            d.receive("FILM", 5, "A")
            seq = [d.stock("FILM", "A")]
            for _ in range(10):
                d.advance_day()
                seq.append(d.stock("FILM", "A"))
            out["D2_stock_by_day"] = seq
            if seq[0] == 0 or seq[1] == 0:
                out["D2"] = "expires_on_receipt"
            elif seq[2] == 0:
                out["D2"] = "treat_as_1"
            elif seq[-1] == 5:
                out["D2"] = "never_expires"
            else:
                out["D2"] = "other"
    except Exception as exc:
        out["D2"] = "error"
        out["D2_error"] = f"{type(exc).__name__}: {exc}"
    json.dump(out, open(out_path, "w"))


if __name__ == "__main__":
    main()
