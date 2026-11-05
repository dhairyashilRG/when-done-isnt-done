"""SyntheticProvider: returns the hand-written plumbing responses in this folder, by pipeline stage.

Every response it returns has ``origin: synthetic``, zero tokens and zero cost. It ignores the
request's content: the responses exist only to exercise the harness's code paths.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from repro.providers.base import Response, Usage

HERE = Path(__file__).resolve().parent
IMPL = {p.name: p.read_text() for p in sorted((HERE / "impl").glob("*.py"))}


def _files(files: dict[str, str]) -> str:
    return "\n".join(f'<file path="{k}">\n{v}</file>' for k, v in files.items())


def _read(name: str) -> str:
    return (HERE / name).read_text()


def _impl_variant(**subs) -> dict[str, str]:
    out = dict(IMPL)
    for (path, old), new in subs.items():
        assert old in out[path], (path, old)
        out[path] = out[path].replace(old, new)
    return out


def _as_reference(files: dict[str, str]) -> dict[str, str]:
    out = {k: v for k, v in files.items() if k != "inventory.py"}
    out["reference.py"] = files["inventory.py"] + "\nfrom sim import simulate  # noqa: E402,F401\n"
    return out


def responses() -> dict[str, str]:
    r_dep = _as_reference({**IMPL, "money.py": IMPL["money.py"].replace(
        "    if average == 0:\n        return 0.0", "    if average == 0:\n        return None")})
    r_ind = _as_reference({**IMPL, "inventory.py": IMPL["inventory.py"].replace(
        'self._cash += DATA["transfer_credit_cents_per_unit"] * qty',
        'self._cash -= DATA["transfer_credit_cents_per_unit"] * qty')})
    applied = dict(IMPL)
    applied["inventory.py"] = IMPL["inventory.py"].replace(
        "    def audit(self, counts):\n        found = []",
        '    def audit(self, counts):\n        if not counts:\n            raise DepotError("EMPTY_AUDIT")\n        found = []')
    report = json.dumps({str(k): "applied" for k in range(1, 9)})
    out = {
        "implement": "Here is the implementation.\n" + _files(IMPL) + "\n" + _read("notes_implement.txt"),
        "test": _files({"test_depot.py": _read("agent_tests_v1.py.txt")}),
        "fix1": "The bulk-discount expectation was wrong.\n" + _files({"test_depot.py": _read("agent_tests_v2.py.txt")}),
        "fix2": _files({"test_depot.py": _read("agent_tests_v2.py.txt")}),
        "demo": _files({"demo.py": _read("demo.py")}),
        "self_report": "<self_report>" + _read("self_report.json") + "</self_report>",
        "e1c_apply": "Applied the comments.\n" + _files({"inventory.py": applied["inventory.py"]})
                     + f"\n<fix_report>{report}</fix_report>",
        "e3_rdep": _files(r_dep),
        "e3_rind": _files(r_ind),
    }
    for k in range(1, 4):
        out[f"e3_resolve{k}"] = "Updated the reference.\n" + _files({"reference.py": r_dep["reference.py"]})
    for cond in ("base", "checklist", "guard"):
        out[f"e2_{cond}/v1_6"] = _files({"validators.py": _read(f"validators/{cond}_v1_6.py")})
        out[f"e2_{cond}/v7_9"] = _files({"validators_later.py": _read(f"validators/{cond}_v7_9.py")})
    return out


class SyntheticProvider:
    name = "synthetic"
    live = False

    def __init__(self):
        self.table = responses()

    def complete(self, messages, *, model, max_tokens, temperature, seed=None, template_version="", label=""):
        stage = label.split("/", 2)[2] if label.count("/") >= 2 else label
        stage = re.sub(r"\.owner\d+$", "", stage)
        if stage not in self.table:
            raise KeyError(f"no synthetic response for stage '{stage}' (label {label})")
        return Response(text=self.table[stage], usage=Usage(0, 0), cost_usd=0.0, provider="synthetic",
                        model=model, origin="synthetic")
