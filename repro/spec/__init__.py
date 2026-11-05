"""The toy spec (brief section 2.1) and data table (2.2), and the agent-facing copies.

Only this package's *agent copies* (``agent_spec_text`` and ``agent_data_toml``) may go into a
prompt. Harness-only notes (brief 2.3) live in ``repro.oracle.notes`` and are never imported here.
"""
from __future__ import annotations

import random
import re
import tomllib
from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parent
SPEC_PATH = SPEC_DIR / "depot_spec.md"
DATA_PATH = SPEC_DIR / "data.toml"

_ROW = re.compile(r"^\| (C\d\d) \| (\w+) \| (.*) \|$")
_PLANTED = re.compile(r"[ \t]*#\s*planted\b.*$", re.IGNORECASE | re.MULTILINE)


def spec_text() -> str:
    return SPEC_PATH.read_text()


def clauses() -> dict[str, dict[str, str]]:
    """Clause id -> {"module": ..., "text": ...}, in spec order."""
    out: dict[str, dict[str, str]] = {}
    for line in spec_text().splitlines():
        m = _ROW.match(line)
        if m:
            out[m.group(1)] = {"module": m.group(2), "text": m.group(3)}
    return out


CLAUSE_IDS = [f"C{i:02d}" for i in range(1, 33)]


def data() -> dict:
    """The data table as the harness reads it (comments are irrelevant to TOML parsing)."""
    with DATA_PATH.open("rb") as fh:
        return tomllib.load(fh)


def strip_planted(text: str) -> str:
    """Remove the harness author's ``# planted`` comments (brief 2.2)."""
    return _PLANTED.sub("", text)


def agent_data_toml() -> str:
    """The copy of data.toml given to the agent: planted comments stripped at prompt time."""
    return strip_planted(DATA_PATH.read_text())


def agent_spec_text(seed: int) -> str:
    """Spec 2.1 for the agent, with the clause rows in a fixed per-seed permutation (brief 5)."""
    lines = spec_text().splitlines()
    rows = [i for i, line in enumerate(lines) if _ROW.match(line)]
    picked = [lines[i] for i in rows]
    random.Random(seed).shuffle(picked)
    for i, row in zip(rows, picked):
        lines[i] = row
    return "\n".join(lines) + "\n"
