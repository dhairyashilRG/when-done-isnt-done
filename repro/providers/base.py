"""The Provider protocol (brief 1), the request hash, prices, cost and the hard budget cap."""
from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

PRICES_PATH = Path(__file__).resolve().parent / "prices.toml"
ORIGINS = ("live", "synthetic")


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Response:
    text: str
    usage: Usage
    cost_usd: float
    provider: str
    model: str
    origin: str                      # "live" or "synthetic"
    request_hash: str = ""
    extra: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def complete(self, messages: list[dict], *, model: str, max_tokens: int, temperature: float,
                 seed: int | None = None, template_version: str = "", label: str = "") -> Response: ...


class ReplayMiss(RuntimeError):
    """A replayed request has no recording. Never answered by falling back to a live call."""


class BudgetExceeded(RuntimeError):
    """The next call's upper-bound cost would take spend past the cap."""


class LiveCallRefused(RuntimeError):
    """A live transport was used without the live run's explicit opt-in."""


def request_hash(messages: list[dict], *, model: str, max_tokens: int, temperature: float,
                 seed: int | None, template_version: str) -> str:
    """Covers everything in the call: messages, model, max_tokens, temperature, seed, template version."""
    payload = {"messages": messages, "model": model, "max_tokens": max_tokens,
               "temperature": temperature, "seed": seed, "template_version": template_version}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ------------------------------------------------------------------ prices and cost
@dataclass(frozen=True)
class Price:
    provider: str
    model: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    placeholder: bool

    def cost(self, usage: Usage) -> float:
        return (usage.input_tokens * self.input_usd_per_mtok + usage.output_tokens * self.output_usd_per_mtok) / 1e6


def load_price_table(path: Path = PRICES_PATH) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_prices(path: Path = PRICES_PATH) -> dict[str, Price]:
    table = load_price_table(path)
    out = {}
    for name, v in table.items():
        if isinstance(v, dict):
            out[name] = Price(name, v.get("model", ""), float(v["input_usd_per_mtok"]),
                              float(v["output_usd_per_mtok"]), bool(v.get("placeholder", True)))
    return out


def chars_per_token_lower_bound(path: Path = PRICES_PATH) -> float:
    return float(load_price_table(path).get("chars_per_token_lower_bound", 2.0))


def token_upper_bound(messages: list[dict], divisor: float = 2.0) -> int:
    n = 0
    for m in messages:
        n += math.ceil(len(str(m.get("content", "")).encode()) / divisor) + 8
    return n


def call_upper_bound_usd(messages: list[dict], max_tokens: int, price: Price, divisor: float = 2.0) -> float:
    """Brief 0: input tokens + max_tokens, all at the output price."""
    return (token_upper_bound(messages, divisor) + max_tokens) * price.output_usd_per_mtok / 1e6


class Budget:
    """A hard cap. ``check`` runs before every call with that call's upper bound."""

    def __init__(self, cap_usd: float):
        self.cap_usd = float(cap_usd)
        self.spent_usd = 0.0
        self.calls = 0

    def check(self, upper_bound_usd: float) -> None:
        if self.spent_usd + upper_bound_usd > self.cap_usd:
            raise BudgetExceeded(f"next call's upper bound ${upper_bound_usd:.4f} would take spend "
                                 f"${self.spent_usd:.4f} past the cap ${self.cap_usd:.2f}")

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd
        self.calls += 1


MAX_UNAPPROVED_BUDGET_USD = 5.0


def validate_budget(budget_usd: float, owner_approved: bool) -> None:
    """Brief 0: refuse --budget-usd above 5 unless --owner-approved-budget is also passed."""
    if budget_usd <= 0:
        raise ValueError("--budget-usd must be positive")
    if budget_usd > MAX_UNAPPROVED_BUDGET_USD and not owner_approved:
        raise PermissionError(f"--budget-usd {budget_usd} exceeds ${MAX_UNAPPROVED_BUDGET_USD:.0f}; spend above "
                              "$5 needs the owner's explicit approval (--owner-approved-budget)")


def response_to_dict(r: Response) -> dict:
    d = asdict(r)
    d["usage"] = asdict(r.usage)
    return d
