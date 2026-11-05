"""Minimal HTTP transport for the live providers (standard library only).

The default transport refuses to run unless the live run has opted in (REPRO_ALLOW_LIVE=1, set only
by ``python -m repro run --live`` after the cost estimate, the budget checks and the operator's
confirmation). Tests inject a fake transport instead.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .base import LiveCallRefused


def urllib_transport(url: str, headers: dict[str, str], body: dict, timeout: float = 600.0) -> tuple[int, dict]:
    if os.environ.get("REPRO_ALLOW_LIVE") != "1":
        raise LiveCallRefused("live HTTP call refused: the run did not opt in to live calls")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (operator-configured URL)
        return resp.status, json.loads(resp.read().decode())
