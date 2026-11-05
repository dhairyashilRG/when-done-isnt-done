"""Providers: replay, record/provenance, cost, hard cap, budget approval, live clients (fake transport)."""
import json

import pytest

from repro.providers import base
from repro.providers.anthropic import AnthropicProvider
from repro.providers.base import (Budget, BudgetExceeded, LiveCallRefused, Price, ReplayMiss, Response, Usage,
                                  call_upper_bound_usd, request_hash, validate_budget)
from repro.providers.http import urllib_transport
from repro.providers.mock import MockProvider, manifest
from repro.providers.openai_compat import OpenAICompatProvider
from repro.providers.record import RecordingProvider

MSGS = [{"role": "system", "content": "rules"}, {"role": "user", "content": "hello"}]
PRICE = Price("anthropic", "m", 3.0, 15.0, placeholder=True)


class Canned:
    name = "canned"

    def __init__(self, text="hi", origin="synthetic", usage=Usage(10, 5), cost=0.0):
        self.text, self.origin, self.usage, self.cost = text, origin, usage, cost
        self.calls = 0

    def complete(self, messages, *, model, max_tokens, temperature, seed=None, template_version="", label=""):
        self.calls += 1
        return Response(self.text, self.usage, self.cost, "canned", model, self.origin)


def call(p, **kw):
    args = dict(model="m", max_tokens=100, temperature=0.7, seed=1, template_version="t@v1#aa", label="x/implement")
    args.update(kw)
    return p.complete(MSGS, **args)


def test_request_hash_covers_every_field():
    h = request_hash(MSGS, model="m", max_tokens=100, temperature=0.7, seed=1, template_version="v1")
    variants = [dict(model="n"), dict(max_tokens=101), dict(temperature=0.5), dict(seed=2), dict(template_version="v2")]
    for v in variants:
        kw = dict(model="m", max_tokens=100, temperature=0.7, seed=1, template_version="v1")
        kw.update(v)
        assert request_hash(MSGS, **kw) != h
    assert request_hash(MSGS[:1], model="m", max_tokens=100, temperature=0.7, seed=1, template_version="v1") != h


def test_record_writes_provenance_and_replay_returns_it(tmp_path):
    rec = RecordingProvider(Canned(origin="synthetic"), tmp_path, clock=lambda: "1970-01-01T00:00:00+00:00")
    r1 = call(rec)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text())
    prov = doc["provenance"]
    for key in ("provider", "model", "timestamp", "request_hash", "usage", "cost_usd", "origin"):
        assert key in prov
    assert prov["origin"] == "synthetic" and prov["request_hash"] == r1.request_hash == files[0].stem
    replay = MockProvider(tmp_path)
    r2 = call(replay)
    assert (r2.text, r2.origin, r2.request_hash) == ("hi", "synthetic", r1.request_hash)


def test_replay_miss_raises_and_never_falls_back(tmp_path):
    RecordingProvider(Canned(), tmp_path)
    replay = MockProvider(tmp_path)
    assert not hasattr(replay, "inner") and replay.live is False
    with pytest.raises(ReplayMiss):
        call(replay)


def test_replay_miss_says_when_a_prompt_template_changed(tmp_path):
    call(RecordingProvider(Canned(), tmp_path))
    with pytest.raises(ReplayMiss, match="prompt template changed"):
        call(MockProvider(tmp_path), template_version="t@v1#bb")


def test_live_set_refuses_synthetic_records(tmp_path):
    with pytest.raises(ValueError):
        call(RecordingProvider(Canned(origin="synthetic"), tmp_path, require_origin="live"))
    assert list(tmp_path.glob("*.json")) == []


def test_manifest_hash_changes_with_content(tmp_path):
    call(RecordingProvider(Canned(), tmp_path))
    m1 = manifest(tmp_path)
    call(RecordingProvider(Canned(text="other"), tmp_path), label="y/test", seed=2)
    m2 = manifest(tmp_path)
    assert m1["manifest_sha256"] != m2["manifest_sha256"] and m2["n"] == 2 and m2["origins"]["synthetic"] == 2


def test_cost_from_usage():
    assert PRICE.cost(Usage(1_000_000, 0)) == pytest.approx(3.0)
    assert PRICE.cost(Usage(0, 1_000_000)) == pytest.approx(15.0)


def test_upper_bound_prices_everything_at_output_rate():
    ub = call_upper_bound_usd(MSGS, 1000, PRICE, divisor=2.0)
    tokens = base.token_upper_bound(MSGS, 2.0)
    assert ub == pytest.approx((tokens + 1000) * 15.0 / 1e6)
    assert tokens >= len("rules hello") / 2


def test_hard_cap_stops_before_the_call(tmp_path):
    inner = Canned(origin="live", cost=0.01)
    budget = Budget(cap_usd=0.02)
    rec = RecordingProvider(inner, tmp_path, budget=budget, price=PRICE)
    call(rec, max_tokens=100)  # bound ~ 0.0018: allowed
    with pytest.raises(BudgetExceeded):
        call(rec, max_tokens=10_000, label="x/test")  # bound 0.15 > remaining
    assert inner.calls == 1 and budget.spent_usd == pytest.approx(0.01)


def test_budget_above_5_needs_owner_approval():
    validate_budget(5, owner_approved=False)
    with pytest.raises(PermissionError):
        validate_budget(5.01, owner_approved=False)
    validate_budget(50, owner_approved=True)
    with pytest.raises(ValueError):
        validate_budget(0, owner_approved=True)


def test_prices_file_ships_placeholders_marked_operator_must_fill():
    text = base.PRICES_PATH.read_text()
    assert "OPERATOR MUST FILL" in text
    prices = base.load_prices()
    assert prices["openai_compat"].placeholder
    assert not prices["anthropic"].placeholder and "checked 2026-11-04" in text


def test_default_transport_refuses_without_live_opt_in(monkeypatch):
    monkeypatch.delenv("REPRO_ALLOW_LIVE", raising=False)
    with pytest.raises(LiveCallRefused):
        urllib_transport("http://127.0.0.1:9/never", {}, {})
    with pytest.raises(LiveCallRefused):
        AnthropicProvider(PRICE).client  # the SDK client is never even built without the opt-in


class FakeMessages:
    def __init__(self, msg):
        self.msg, self.created, self.streamed = msg, [], []

    def create(self, **body):
        self.created.append(body)
        return self.msg

    def stream(self, **body):
        self.streamed.append(body)
        msg = self.msg

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return msg
        return S()


class FakeClient:
    def __init__(self, msg):
        self.messages = FakeMessages(msg)


def _msg(stop="end_turn", details=None):
    return {"model": "m-1", "stop_reason": stop, "stop_details": details,
            "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}


def test_anthropic_provider_sends_no_temperature_or_seed_and_sets_effort():
    client = FakeClient(_msg())
    p = AnthropicProvider(PRICE, client=client)
    r = call(p)
    body = client.messages.created[0]
    assert body["system"] == "rules" and body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["output_config"] == {"effort": "medium"} and body["max_tokens"] == 100
    for banned in ("temperature", "top_p", "top_k", "seed", "fallbacks", "thinking"):
        assert banned not in body
    assert (r.text, r.origin, r.usage) == ("ok", "live", Usage(100, 20))
    assert r.cost_usd == pytest.approx(PRICE.cost(Usage(100, 20)))
    assert r.extra["refused"] is False and r.extra["truncated"] is False


def test_anthropic_provider_streams_long_outputs():
    client = FakeClient(_msg())
    call(AnthropicProvider(PRICE, client=client), max_tokens=16000)
    assert client.messages.streamed and not client.messages.created


def test_anthropic_refusal_and_truncation_are_recorded(tmp_path):
    details = {"category": "other", "explanation": "declined"}
    rec = RecordingProvider(AnthropicProvider(PRICE, client=FakeClient(_msg("refusal", details))), tmp_path)
    r = call(rec)
    assert r.extra["refused"] and r.extra["stop_details"] == details
    prov = json.loads(next(tmp_path.glob("*.json")).read_text())["provenance"]
    assert prov["refused"] is True and prov["stop_reason"] == "refusal" and prov["stop_details"] == details
    replay = call(MockProvider(tmp_path))
    assert replay.extra["refused"] is True
    t = call(AnthropicProvider(PRICE, client=FakeClient(_msg("max_tokens"))))
    assert t.extra["truncated"] is True


def test_openai_compat_provider_with_fake_transport():
    seen = {}

    def fake(url, headers, body):
        seen.update(url=url, body=body)
        return 200, {"model": "m-2", "choices": [{"message": {"content": "fine"}}],
                     "usage": {"prompt_tokens": 7, "completion_tokens": 3}}

    p = OpenAICompatProvider(PRICE, base_url="http://endpoint.test/v1", transport=fake)
    r = call(p)
    assert seen["url"] == "http://endpoint.test/v1/chat/completions"
    assert seen["body"]["seed"] == 1 and seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["temperature"] == 0.7
    assert (r.text, r.origin, r.usage) == ("fine", "live", Usage(7, 3))
