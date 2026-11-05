"""Held-out acceptance suite fixtures. Hidden from the agent: never put into a prompt (brief 0)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import heldout_adapter as A  # noqa: E402


@pytest.fixture(params=A.GATE_ROUNDING)
def rounding_mode(request):
    """Gate G1 value, injected (the owner's choice; the suite tries each)."""
    return request.param


@pytest.fixture(params=A.GATE_PENALTY)
def late_penalty_pct(request):
    """Gate G2 value, injected (the owner's choice; the suite tries each)."""
    return request.param


@pytest.fixture
def d():
    """A two-warehouse depot (A, B; capacity 1000 each; 100000 cents) with BOLT and GLUE added."""
    return A.make()
