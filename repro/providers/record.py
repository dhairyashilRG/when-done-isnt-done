"""Wraps a provider; checks the hard cap before each call; writes each response with provenance."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .base import Budget, Price, Response, call_upper_bound_usd, request_hash


class RecordingProvider:
    def __init__(self, inner, out_dir: Path, *, budget: Budget | None = None, price: Price | None = None,
                 chars_per_token: float = 2.0, clock=None, require_origin: str | None = None):
        self.inner = inner
        self.name = inner.name
        self.out_dir = Path(out_dir)
        self.budget = budget
        self.price = price
        self.chars_per_token = chars_per_token
        self.clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
        self.require_origin = require_origin
        self.written: list[str] = []

    def complete(self, messages, *, model, max_tokens, temperature, seed=None, template_version="", label=""):
        h = request_hash(messages, model=model, max_tokens=max_tokens, temperature=temperature, seed=seed,
                         template_version=template_version)
        if self.budget is not None:
            if self.price is None:
                raise ValueError("a budget needs a price")
            self.budget.check(call_upper_bound_usd(messages, max_tokens, self.price, self.chars_per_token))
        resp: Response = self.inner.complete(messages, model=model, max_tokens=max_tokens, temperature=temperature,
                                             seed=seed, template_version=template_version, label=label)
        if self.require_origin and resp.origin != self.require_origin:
            raise ValueError(f"refusing to record origin '{resp.origin}' into a '{self.require_origin}' set")
        if self.budget is not None:
            self.budget.charge(resp.cost_usd)
        resp.request_hash = h
        record = {
            "request_hash": h,
            "label": label,
            "template_version": template_version,
            "request": {"model": model, "max_tokens": max_tokens, "temperature": temperature, "seed": seed,
                        "messages": messages},
            "response": {"text": resp.text},
            "provenance": {"provider": resp.provider, "model": resp.model, "timestamp": self.clock(),
                           "request_hash": h,
                           "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
                           "cost_usd": resp.cost_usd, "origin": resp.origin,
                           "stop_reason": resp.extra.get("stop_reason"), "refused": bool(resp.extra.get("refused")),
                           "truncated": bool(resp.extra.get("truncated")),
                           "stop_details": resp.extra.get("stop_details")},
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"{h}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
        self.written.append(h)
        return resp
