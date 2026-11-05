"""Synthetic validators, checklist condition."""


def v1(rows):
    if not rows:
        return False, 0
    bad = [r for r in rows if r["value_cents"] != r["units"] * r["unit_cost"]]
    return not bad, len(rows)


def v2(runs):
    seen = {n[0] for run in runs for n in run}
    need = {"EXPIRY", "REORDER", "SUPPLIER_SUSPENDED", "OVERDRAWN", "AUDIT_MISMATCH"}
    return need <= seen, sorted(seen)


def v3(pairs):
    if not pairs:
        return False, 0
    return all(p["a"] == p["b"] for p in pairs), len(pairs)


def v4(days):
    return all(d["storage_cost_cents"] <= d["budget_cents"] for d in days), len(days)


def v5(clauses):
    return all(len(c["tests"]) > 0 for c in clauses), len(clauses)


def v6(pairs):
    if not pairs:
        return False, 0
    return all(p["a"] == p["b"] for p in pairs), len(pairs)
