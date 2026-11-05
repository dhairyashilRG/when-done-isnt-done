"""Synthetic validators, guard condition, written later."""
from checks_base import Check


class V7(Check):
    def check(self, entries):
        return all(e["max_units"] <= e["capacity"] for e in entries), len(entries)


class V8(Check):
    def check(self, entries):
        return all(sorted(e["expired"]) == sorted(e["notified"]) for e in entries), len(entries)


class V9(Check):
    def check(self, entries):
        return all(0 <= e["reliability"] <= 5 for e in entries), len(entries)
