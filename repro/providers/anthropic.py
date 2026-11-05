"""Live provider for the Anthropic Messages API, through the official ``anthropic`` Python SDK.

Never invoked by the offline run or the tests (they pass a fake client). Choices, all recorded in
DECISIONS.md and as a dated amendment in PREREGISTRATION.md:

* No ``temperature``, ``top_p`` or ``top_k`` is sent (the API rejects them) and there is no ``seed``
  parameter; an agent "seed" acts only through the fixed clause-order permutation in the prompt.
* Thinking is left at its default (adaptive); ``output_config={"effort": "medium"}`` is set
  explicitly to keep costs down. Thinking tokens bill as output tokens.
* ``stop_reason == "refusal"`` is recorded as a refused call (with ``stop_details`` when present)
  and counted in the results. The server-side "fallbacks" option is never enabled: it would switch
  to another model and spoil the same-model comparison. ``"max_tokens"`` is recorded as truncated.
* Cost comes from the real token counts in ``response.usage``.
* Long outputs (``max_tokens`` >= 16000) use streaming with ``get_final_message()``.
* The API key is read from the environment by the SDK (``ANTHROPIC_API_KEY``).
"""
from __future__ import annotations

import os

from .base import LiveCallRefused, Price, Response, Usage

STREAM_FROM_MAX_TOKENS = 16000
EFFORT = "medium"


def _default_client(base_url: str | None):
    if os.environ.get("REPRO_ALLOW_LIVE") != "1":
        raise LiveCallRefused("live call refused: the run did not opt in to live calls")
    import anthropic as sdk  # the official SDK; only needed for a live run (pip install anthropic)
    return sdk.Anthropic(base_url=base_url) if base_url else sdk.Anthropic()


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class AnthropicProvider:
    name = "anthropic"
    live = True

    def __init__(self, price: Price, *, base_url: str | None = None, client=None, **_ignored):
        self.price = price
        self.base_url = base_url
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = _default_client(self.base_url)
        return self._client

    def request_body(self, messages, *, model, max_tokens) -> dict:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        body = {"model": model, "max_tokens": max_tokens, "messages": chat, "output_config": {"effort": EFFORT}}
        if system:
            body["system"] = system
        return body

    def complete(self, messages, *, model, max_tokens, temperature=None, seed=None, template_version="", label=""):
        # temperature and seed are deliberately not sent (see the module docstring).
        body = self.request_body(messages, model=model, max_tokens=max_tokens)
        if max_tokens >= STREAM_FROM_MAX_TOKENS:
            with self.client.messages.stream(**body) as stream:
                msg = stream.get_final_message()
        else:
            msg = self.client.messages.create(**body)
        text = "".join(_get(b, "text", "") for b in _get(msg, "content", []) if _get(b, "type") == "text")
        u = _get(msg, "usage", {})
        usage = Usage(int(_get(u, "input_tokens", 0) or 0), int(_get(u, "output_tokens", 0) or 0))
        stop_reason = _get(msg, "stop_reason")
        details = _get(msg, "stop_details")
        if details is not None and not isinstance(details, dict):
            details = {"category": _get(details, "category"), "explanation": _get(details, "explanation")}
        extra = {"stop_reason": stop_reason, "refused": stop_reason == "refusal",
                 "truncated": stop_reason == "max_tokens", "stop_details": details}
        return Response(text=text, usage=usage, cost_usd=self.price.cost(usage), provider=self.name,
                        model=_get(msg, "model", model), origin="live", extra=extra)
