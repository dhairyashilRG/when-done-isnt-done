"""Reach: a clause whose observable never occurred while demo.py and the agent's tests ran is UNREACHED.

The fixed clause -> observable map below is the harness's, written from the spec. A clause is
reached only when *every* observable listed for it occurred. An unreached clause fails.
"""
from __future__ import annotations

import json

from .. import sandbox
from ..spec import CLAUSE_IDS
from .empty_guard import Check

CLAUSE_OBSERVABLES: dict[str, list[str]] = {
    "C01": ["ok:add_item", "err:DUPLICATE_SKU"],
    "C02": ["err:UNKNOWN_SKU"],
    "C03": ["err:UNKNOWN_WAREHOUSE"],
    "C04": ["ok:receive", "err:CAPACITY"],
    "C05": ["ok:receive", "err:INSUFFICIENT_FUNDS"],
    "C06": ["ok:ship", "err:INSUFFICIENT_STOCK"],
    "C07": ["ok:ship"],
    "C08": ["ok:list_price"],
    "C09": ["branch:ship.bulk"],
    "C10": ["ok:transfer", "branch:transfer.rejected"],
    "C11": ["ok:transfer"],
    "C12": ["branch:ship.fifo"],
    "C13": ["notif:EXPIRY"],
    "C14": ["notif:REORDER", "branch:reorder.rearm"],
    "C15": ["branch:deliver.on_time", "branch:deliver.late"],
    "C16": ["ok:place_order", "ok:deliver"],
    "C17": ["notif:SUPPLIER_SUSPENDED", "err:SUPPLIER_SUSPENDED", "ok:reinstate"],
    "C18": ["branch:deliver.late"],
    "C19": ["branch:advance_day.storage"],
    "C20": ["notif:OVERDRAWN", "err:OVERDRAWN"],
    "C21": ["branch:advance_day.expiry_with_storage", "notif:OVERDRAWN"],
    "C22": ["notif:AUDIT_MISMATCH", "err:EMPTY_AUDIT"],
    "C23": ["ok:return_goods", "err:RETURN_EXCEEDS"],
    "C24": ["ok:receive_bulk", "branch:receive_bulk.rejected"],
    "C25": ["branch:stock.total", "branch:stock.wh"],
    "C26": ["ok:report"],
    "C27": ["ok:undo", "err:UNDO_BLOCKED"],
    "C28": ["ok:save", "ok:load", "err:BAD_SAVE"],
    "C29": ["branch:simulate.two_seeds"],
    "C30": ["ok:turnover", "branch:turnover.none"],
    "C31": ["ok:__init__"],
    "C32": ["ok:notifications"],
}
assert set(CLAUSE_OBSERVABLES) == set(CLAUSE_IDS)


class ReachCheck(Check):
    """Input: the set of observables that occurred. Measured: per-clause reached / UNREACHED."""

    name = "reach"

    def check(self, observed):
        observed = set(observed)
        per = {c: ("reached" if all(o in observed for o in obs) else "UNREACHED")
               for c, obs in CLAUSE_OBSERVABLES.items()}
        return all(v == "reached" for v in per.values()), per


def observe(files: dict[str, str], test_file: str = "test_depot.py", timeout: float = sandbox.DEFAULT_TIMEOUT) -> dict:
    """Run demo.py and the agent's tests under instrumentation; return the observables seen."""
    key = sandbox.cache_key("reach", files, test_file)
    hit = sandbox.cache_get("reach", key)
    if hit is not None:
        return hit
    d = sandbox.make_workdir(files, "reach")
    log = d / ".reach.jsonl"
    env = sandbox.env_for(d, {"REPRO_REACH_LOG": str(log)})
    timed_out = False
    try:
        if "demo.py" in files:
            p = sandbox.run(["-c", "import _reach; _reach.install(); import runpy; "
                                   "runpy.run_path('demo.py', run_name='__main__')"], d, timeout, env)
            timed_out |= p.timed_out
        if test_file in files:
            r = sandbox.run_pytest(d, [test_file], timeout=timeout, plugins=("_reach",),
                                   env_extra={"REPRO_REACH_LOG": str(log)})
            timed_out |= r.get("timed_out", False)
        seen: set[str] = set()
        if log.exists():
            for line in log.read_text().splitlines():
                seen.update(json.loads(line))
    finally:
        sandbox.remove(d)
    out = {"observed": sorted(seen), "timed_out": timed_out}
    if not timed_out:
        sandbox.cache_put("reach", key, out)
    return out


def reach_verdicts(observed: list[str]) -> dict[str, str]:
    res = ReachCheck().run(set(observed))
    if res.measured is None:  # nothing observed at all: every clause is unreached
        return {c: "UNREACHED" for c in CLAUSE_IDS}
    return res.measured
