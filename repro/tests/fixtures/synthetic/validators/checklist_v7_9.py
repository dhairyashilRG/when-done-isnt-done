"""Synthetic validators, checklist condition, written later."""


def v7(entries):
    return all(e["max_units"] <= e["capacity"] for e in entries), len(entries)


def v8(entries):
    return all(sorted(e["expired"]) == sorted(e["notified"]) for e in entries), len(entries)


def v9(entries):
    if not entries:
        return False, 0
    return all(0 <= e["reliability"] <= 5 for e in entries), len(entries)
