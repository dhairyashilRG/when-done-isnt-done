"""The ``Check`` base class: a check never passes on nothing (brief 3, and E2's guard condition).

``Check.run(items)`` returns ``failed: empty input`` for empty or all-unmeasured input *before*
calling the subclass, and ``failed: nothing measured`` when the subclass measured nothing. The
harness's own checks (presence, reach, parity, mutation) subclass it, and so do the agent's
validators in E2's guard condition (the agent gets this file as ``checks_base.py``).

This file is standard-library only so it can be copied verbatim into the agent's repo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CheckResult:
    passed: bool
    measured: Any
    reason: str = ""

    def __iter__(self):  # allows ``passed, measured = check.run(x)``
        yield self.passed
        yield self.measured

    def __bool__(self) -> bool:
        return bool(self.passed)


def is_empty(value: Any) -> bool:
    """True for None, empty containers, and containers whose every leaf is None or empty."""
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0 or all(is_empty(v) for v in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return len(value) == 0 or all(is_empty(v) for v in value)
    return False


class Check:
    """Subclasses implement ``check(items) -> (passed, measured)``; callers use ``run(items)``."""

    name = "check"

    def run(self, items: Any) -> CheckResult:
        if hasattr(items, "__next__"):  # a lazy source of runs: materialise before judging emptiness
            items = list(items)
        if is_empty(items):
            return CheckResult(False, None, "failed: empty input")
        try:
            passed, measured = self.check(items)
        except Exception as exc:  # a check that crashes has not passed
            return CheckResult(False, None, f"failed: {type(exc).__name__}: {exc}")
        if is_empty(measured):
            return CheckResult(False, measured, "failed: nothing measured")
        return CheckResult(bool(passed), measured, "" if passed else "failed")

    def check(self, items: Any) -> tuple[bool, Any]:  # pragma: no cover - abstract
        raise NotImplementedError
