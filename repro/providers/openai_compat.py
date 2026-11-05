"""Optional second live provider: any OpenAI-compatible chat-completions endpoint. Never invoked here."""
from __future__ import annotations

import os

from .base import Price, Response, Usage
from .http import urllib_transport


class OpenAICompatProvider:
    name = "openai_compat"
    live = True

    def __init__(self, price: Price, *, base_url: str, api_key_env: str = "OPENAI_COMPAT_API_KEY", transport=None):
        self.price = price
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.transport = transport or urllib_transport

    def complete(self, messages, *, model, max_tokens, temperature, seed=None, template_version="", label=""):
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages]}
        if temperature is not None:
            body["temperature"] = temperature
        if seed is not None:
            body["seed"] = seed
        headers = {"content-type": "application/json",
                   "authorization": f"Bearer {os.environ.get(self.api_key_env, '')}"}
        status, data = self.transport(f"{self.base_url}/chat/completions", headers, body)
        if status != 200:
            raise RuntimeError(f"openai_compat: HTTP {status}: {str(data)[:300]}")
        text = data["choices"][0]["message"].get("content") or ""
        u = data.get("usage", {})
        usage = Usage(int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
        return Response(text=text, usage=usage, cost_usd=self.price.cost(usage), provider=self.name,
                        model=data.get("model", model), origin="live")
