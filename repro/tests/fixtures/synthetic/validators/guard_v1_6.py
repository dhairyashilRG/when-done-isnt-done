"""Synthetic validators, guard condition."""
from checks_base import Check


class V1(Check):
    def check(self, rows):
        return all(r["value_cents"] == r["units"] * r["unit_cost"] for r in rows), len(rows)


class V2(Check):
    def check(self, runs):
        seen = {n[0] for run in runs for n in run}
        return {"EXPIRY", "REORDER", "SUPPLIER_SUSPENDED", "OVERDRAWN", "AUDIT_MISMATCH"} <= seen, sorted(seen)


class V3(Check):
    def check(self, pairs):
        return all(p["a"] == p["b"] for p in pairs), len(pairs)


class V4(Check):
    def check(self, days):
        return all(d["storage_cost_cents"] <= d["budget_cents"] for d in days), len(days)


class V5(Check):
    def check(self, clauses):
        return all(c["tests"] for c in clauses), len(clauses)


class V6(Check):
    def check(self, pairs):
        return all(p["a"] == p["b"] for p in pairs), len(pairs)
