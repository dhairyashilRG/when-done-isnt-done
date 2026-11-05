"""Shared run context and helpers for the four experiments."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..agent.pipeline import RunArtifacts, Slot
from ..oracle.notes import SPEC_MODULES, module_of
from ..spec import CLAUSE_IDS, clauses

MODULE_CLAUSES = {m: [c for c, v in clauses().items() if module_of(v["module"]) == m] for m in SPEC_MODULES}
STANDARD_GROUPS = ("implement", "test", "fix1", "fix2", "demo", "self_report")


@dataclass
class RunContext:
    run_id: str
    slot: Slot
    seed: int
    r_ind_slot: Slot
    art: RunArtifacts
    data: dict = field(default_factory=dict)

    def deps(self, *groups: str) -> list[dict]:
        """Calls (hash, origin) in the given groups; a group is the label's first part after the run id."""
        out = []
        for c in self.art.log.calls:
            rest = c.label[len(self.run_id) + 1:]
            group = rest.split("/")[0].split(".")[0]
            if group in groups:
                out.append({"hash": c.request_hash, "origin": c.origin})
        return out

    def standard_deps(self) -> list[dict]:
        return self.deps(*STANDARD_GROUPS)


def agent_pass_by_clause(test_results: dict) -> dict[str, bool | None]:
    """Clause -> True (>= 1 agent test, all passing), False (some failing), None (no agent test)."""
    out = {}
    for c in CLAUSE_IDS:
        mine = [t for t in test_results.get("tests", []) if c in t.get("clauses", [])]
        out[c] = None if not mine else all(t["outcome"] == "passed" for t in mine)
    return out


def ticked(self_report: dict) -> list[str]:
    return [c for c, v in self_report["clauses"].items() if v["status"] == "done"]
