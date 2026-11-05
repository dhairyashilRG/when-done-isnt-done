"""Parity: differential runs between two implementations (E3), and the ``ParityCheck``.

Each implementation runs the same seeded operation sequences in its own subprocess (brief 4, E3:
20 seeds x 200 operations); the traces are compared after every operation.

Two drivers exist (amendment A6). ``DRIVER`` records only what the spec pins down and is used for
every measurement. ``DRIVER_AS_RECORDED`` is the original driver, unchanged; the oracle-editing
stage of E3 uses it because the mismatches shown to the agent during the live recording came from
it, and replaying those recorded calls needs the same prompts.
"""
from __future__ import annotations

import json

from .. import sandbox
from .empty_guard import Check

DRIVER = sandbox.SUPPORT_DIR / "diff_driver.py"
DRIVER_AS_RECORDED = sandbox.SUPPORT_DIR / "diff_driver_v1.py"
E3_SEEDS = list(range(100, 120))
N_OPS = 200

OP_CLAUSE = {"receive": "C04", "ship": "C06", "transfer": "C10", "advance_day": "C19", "audit": "C22",
             "return_goods": "C23", "receive_bulk": "C24", "place_order": "C16", "deliver": "C16",
             "reinstate": "C17", "list_price": "C08", "stock": "C25", "report": "C26", "undo": "C27",
             "save_load": "C28", "turnover": "C30", "simulate": "C29", "bad_sku": "C02", "bad_wh": "C03",
             "add_item_dup": "C01"}
CODE_CLAUSE = {"CAPACITY": "C04", "INSUFFICIENT_FUNDS": "C05", "INSUFFICIENT_STOCK": "C06", "UNKNOWN_SKU": "C02",
               "UNKNOWN_WAREHOUSE": "C03", "OVERDRAWN": "C20", "EMPTY_AUDIT": "C22", "RETURN_EXCEEDS": "C23",
               "SUPPLIER_SUSPENDED": "C17", "UNDO_BLOCKED": "C27", "BAD_SAVE": "C28", "DUPLICATE_SKU": "C01"}
NOTE_CLAUSE = {"EXPIRY": "C13", "REORDER": "C14", "SUPPLIER_SUSPENDED": "C17", "OVERDRAWN": "C20",
               "AUDIT_MISMATCH": "C22"}
CASH_CLAUSE = {"transfer": "C11", "receive": "C05", "receive_bulk": "C05", "advance_day": "C19", "deliver": "C18",
               "return_goods": "C23"}


def run_traces(files: dict[str, str], seeds=E3_SEEDS, n_ops: int = N_OPS, timeout: float = 120.0,
               driver=DRIVER) -> dict:
    """Trace of every seed for one implementation (relative path -> source). Cached by content."""
    key = sandbox.cache_key("diff", files, seeds, n_ops, driver.read_text())
    hit = sandbox.cache_get("diff", key)
    if hit is not None:
        return hit
    d = sandbox.make_workdir(files, "diff")
    out_path = d / ".traces.json"
    try:
        env = sandbox.env_for(d, {"DEPOT_IMPL_DIR": str(d)})
        p = sandbox.run([str(driver), str(sandbox.HELDOUT_DIR), json.dumps(list(seeds)), str(n_ops), str(out_path)],
                        d, timeout, env)
        traces = json.loads(out_path.read_text()) if out_path.exists() else {}
        out = {"traces": traces, "timed_out": p.timed_out, "returncode": p.returncode,
               "stderr_tail": p.stderr[-600:] if not traces else ""}
    finally:
        sandbox.remove(d)
    if not out["timed_out"]:
        sandbox.cache_put("diff", key, out)
    return out


def _step_clause(a: dict, b: dict) -> str:
    op = a["op"]
    if a["result"] != b["result"]:
        for r in (a["result"], b["result"]):
            if r[0] == "err" and r[1] in CODE_CLAUSE:
                return CODE_CLAUSE[r[1]]
        return OP_CLAUSE.get(op, "?")
    if a["new_notes"] != b["new_notes"]:
        for n in a["new_notes"] + b["new_notes"]:
            if n and (n not in a["new_notes"] or n not in b["new_notes"]) and n[0] in NOTE_CLAUSE:
                return NOTE_CLAUSE[n[0]]
        return "C32"
    if a["cash"] != b["cash"]:
        if op == "ship":
            return "C09" if a["args"][1] >= 20 else "C07"
        return CASH_CLAUSE.get(op, OP_CLAUSE.get(op, "?"))
    if a["stock"] != b["stock"]:
        return "C13" if op == "advance_day" else OP_CLAUSE.get(op, "?")
    if a["rel"] != b["rel"]:
        return "C15"
    return OP_CLAUSE.get(op, "?")


def compare(ta: dict, tb: dict, seeds=E3_SEEDS) -> dict:
    """seeds_agree and the clause of the first divergence (over all seeds, earliest step)."""
    agree, first = 0, None
    per_seed = {}
    for s in seeds:
        a, b = ta.get("traces", {}).get(str(s)), tb.get("traces", {}).get(str(s))
        if a is None or b is None or "setup_error" in a or "setup_error" in b:
            per_seed[s] = {"agree": False, "step": 0, "clause": "C31" if (a or b) else "timeout"}
            first = first or (0, per_seed[s]["clause"], s)
            continue
        div = next((i for i, (x, y) in enumerate(zip(a["steps"], b["steps"])) if x != y), None)
        if div is None and len(a["steps"]) != len(b["steps"]):
            div = min(len(a["steps"]), len(b["steps"]))
        if div is None:
            agree += 1
            per_seed[s] = {"agree": True}
            continue
        x, y = (a["steps"][div], b["steps"][div]) if div < min(len(a["steps"]), len(b["steps"])) else (None, None)
        clause = _step_clause(x, y) if x else "?"
        per_seed[s] = {"agree": False, "step": div, "clause": clause, "op": x["op"] if x else None,
                       "a": x, "b": y}
        if first is None or div < first[0]:
            first = (div, clause, s)
    return {"seeds_agree": agree, "n_seeds": len(seeds), "first_divergence_clause": first[1] if first else "",
            "first_divergence_seed": first[2] if first else None, "per_seed": per_seed}


class ParityCheck(Check):
    """Input: a list of (trace_a, trace_b) step pairs. Passes when every compared pair agrees."""

    name = "parity"

    def check(self, pairs):
        compared = [(a, b) for a, b in pairs if a is not None and b is not None]
        if not compared:
            return False, None
        disagree = sum(a != b for a, b in compared)
        return disagree == 0, {"compared": len(compared), "disagree": disagree}


def diff_text(cmp: dict, name_a: str, name_b: str, limit: int = 3) -> str:
    """A short, deterministic description of the first divergences (shown to the agent in E3)."""
    lines = []
    for s, info in sorted(cmp["per_seed"].items()):
        if info.get("agree") or "a" not in info:
            continue
        a, b = info["a"], info["b"]
        lines.append(f"- sequence {s}, step {info['step']}: `{a['op']}({', '.join(map(str, a['args']))})`\n"
                     f"  {name_a}: result={a['result']} cash={a['cash']} stock={a['stock']} "
                     f"reliability={a['rel']} notifications={a['new_notes']}\n"
                     f"  {name_b}: result={b['result']} cash={b['cash']} stock={b['stock']} "
                     f"reliability={b['rel']} notifications={b['new_notes']}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)
