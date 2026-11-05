"""Run the hidden held-out suite against an implementation, in a subprocess; score it per clause.

The suite's files are copied to a temporary directory next to (not inside) the implementation's
directory, so agent code never sees them as part of its own tree. Nothing here reaches a prompt.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .. import sandbox
from ..spec import CLAUSE_IDS, agent_data_toml

HELDOUT_DIR = sandbox.HELDOUT_DIR
REFERENCE_PATH = Path(__file__).resolve().parent / "reference_hand.py"


def heldout_files() -> list[Path]:
    return sorted(p for p in HELDOUT_DIR.iterdir() if p.suffix == ".py" and p.is_file())


def heldout_sha256() -> str:
    """sha256 over the suite's files (name and content, sorted by name); recorded in PREREGISTRATION.md."""
    h = hashlib.sha256()
    for p in heldout_files():
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def reference_files() -> dict[str, str]:
    return {"reference_hand.py": REFERENCE_PATH.read_text(), "data.toml": agent_data_toml()}


def with_data(files: dict[str, str]) -> dict[str, str]:
    out = dict(files)
    out.setdefault("data.toml", agent_data_toml())
    return out


def clause_verdicts(tests: list[dict], clause_ids=CLAUSE_IDS) -> dict[str, str]:
    """pass when every test of the clause passes, fail when none does, partial otherwise."""
    out = {}
    for c in clause_ids:
        mine = [t for t in tests if c in t.get("clauses", [])]
        if not mine:
            out[c] = "fail"
            continue
        passed = sum(t["outcome"] == "passed" for t in mine)
        out[c] = "pass" if passed == len(mine) else ("fail" if passed == 0 else "partial")
    return out


def run_heldout(impl_files: dict[str, str], *, null_sink: bool = False, timeout: float = 120.0,
                select: list[str] | None = None) -> dict:
    """Run the suite against ``impl_files`` (relative path -> source). Cached by content."""
    files = with_data(impl_files)
    key = sandbox.cache_key("heldout", heldout_sha256(), files, null_sink, select)
    hit = sandbox.cache_get("heldout", key)
    if hit is not None:
        return hit
    impl_dir = sandbox.make_workdir(files, "impl")
    suite_dir = sandbox.make_workdir({}, "heldout")
    try:
        for p in heldout_files():
            shutil.copy(p, suite_dir / p.name)
        plugins = ("_nullsink",) if null_sink else ()
        targets = select or ["."]
        env_extra = {"DEPOT_IMPL_DIR": str(impl_dir)}
        res = sandbox.run_pytest(suite_dir, targets, timeout=timeout, plugins=plugins, env_extra=env_extra)
        tests = [t for t in res.get("tests", []) if not t["nodeid"].startswith("collect::")]
        out = {"tests": tests, "per_clause": clause_verdicts(tests), "timed_out": res.get("timed_out", False),
               "n_tests": len(tests), "n_passed": sum(t["outcome"] == "passed" for t in tests)}
    finally:
        sandbox.remove(impl_dir)
        sandbox.remove(suite_dir)
    if not out["timed_out"]:
        sandbox.cache_put("heldout", key, out)
    return out
