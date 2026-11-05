"""Presence: every public function named in the spec exists, and demo.py exits 0 (the green dashboard)."""
from __future__ import annotations

import ast

from .. import sandbox
from .empty_guard import Check

SPEC_FUNCTIONS = ["add_item", "receive", "ship", "list_price", "transfer", "advance_day", "notifications",
                  "place_order", "deliver", "reinstate", "audit", "return_goods", "receive_bulk", "stock",
                  "report", "undo", "save", "load", "turnover", "simulate"]
IMPL_MODULES = ["inventory.py", "money.py", "suppliers.py", "events.py", "sim.py"]


def defined_names(files: dict[str, str]) -> set[str]:
    """Function and method names defined anywhere in the given sources (static; nothing is imported)."""
    names: set[str] = set()
    for path, src in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
    return names


class PresenceCheck(Check):
    """Input: {"files": {path: source}, "demo_ok": bool}."""

    name = "presence"

    def check(self, items):
        files = {p: s for p, s in items.get("files", {}).items()
                 if p.endswith(".py") and not p.split("/")[-1].startswith("test_") and p != "demo.py"}
        if not files:
            return False, None
        missing = [f for f in SPEC_FUNCTIONS if f not in defined_names(files)]
        demo_ok = bool(items.get("demo_ok"))
        return (not missing and demo_ok), {"missing": missing, "n_found": len(SPEC_FUNCTIONS) - len(missing),
                                           "demo_ok": demo_ok}


def run_demo(files: dict[str, str], *, null_sink: bool = False, timeout: float = sandbox.DEFAULT_TIMEOUT) -> dict:
    """Run demo.py in a subprocess. Cached by content."""
    if "demo.py" not in files:
        return {"ok": False, "returncode": None, "timed_out": False, "tail": "no demo.py"}
    key = sandbox.cache_key("demo", files, null_sink)
    hit = sandbox.cache_get("demo", key)
    if hit is not None:
        return hit
    d = sandbox.make_workdir(files, "demo")
    try:
        boot = "import _nullsink; _nullsink.install(); " if null_sink else ""
        code = boot + "import runpy; runpy.run_path('demo.py', run_name='__main__')"
        p = sandbox.run(["-c", code], d, timeout)
        out = {"ok": p.ok, "returncode": p.returncode, "timed_out": p.timed_out, "tail": (p.stdout + p.stderr)[-800:]}
    finally:
        sandbox.remove(d)
    if not out["timed_out"]:
        sandbox.cache_put("demo", key, out)
    return out
