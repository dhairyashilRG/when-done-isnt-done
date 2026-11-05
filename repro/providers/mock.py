"""Replay provider keyed by request hash. A miss raises; it never falls back to a live call."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import ORIGINS, ReplayMiss, Response, Usage, request_hash


def load_recordings(directory: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(Path(directory).glob("*.json")):
        if p.name == "manifest.json":
            continue
        rec = json.loads(p.read_text())
        if rec.get("provenance", {}).get("origin") not in ORIGINS:
            raise ValueError(f"{p.name}: recording without a valid origin")
        out[rec["request_hash"]] = rec
    return out


def manifest(directory: Path) -> dict:
    """Recording-set manifest: request hash -> sha256 of the recording file, plus the set's hash."""
    entries = {}
    origins = {"live": 0, "synthetic": 0}
    for p in sorted(Path(directory).glob("*.json")):
        if p.name == "manifest.json":
            continue
        entries[p.stem] = hashlib.sha256(p.read_bytes()).hexdigest()
        origins[json.loads(p.read_text())["provenance"]["origin"]] += 1
    body = json.dumps(entries, sort_keys=True).encode()
    return {"manifest_sha256": hashlib.sha256(body).hexdigest(), "n": len(entries), "origins": origins,
            "entries": entries}


class MockProvider:
    """Replays recorded responses. It holds no live provider, so it cannot fall back to one."""

    live = False

    def __init__(self, directory: Path | None = None, records: dict[str, dict] | None = None, name: str = "replay"):
        self.name = name
        self.records = records if records is not None else load_recordings(directory)
        self.by_label: dict[str, list[dict]] = {}
        for rec in self.records.values():
            self.by_label.setdefault(rec.get("label", ""), []).append(rec)
        self.hits: list[str] = []

    def _diagnose(self, label: str, template_version: str) -> str:
        recs = self.by_label.get(label)
        if not recs:
            return f"no recording exists for call '{label}'"
        versions = sorted({r.get("template_version", "") for r in recs})
        if template_version not in versions:
            return (f"prompt template changed for '{label}': recorded {versions}, requested '{template_version}'. "
                    "Changing a prompt invalidates its recordings; re-record (live, with approval) "
                    "or rebuild the synthetic set")
        return f"the request for '{label}' differs from its recording (messages, model or parameters changed)"

    def complete(self, messages, *, model, max_tokens, temperature, seed=None, template_version="", label=""):
        h = request_hash(messages, model=model, max_tokens=max_tokens, temperature=temperature, seed=seed,
                         template_version=template_version)
        rec = self.records.get(h)
        if rec is None:
            raise ReplayMiss(f"replay miss {h[:12]}: {self._diagnose(label, template_version)}")
        self.hits.append(h)
        prov = rec["provenance"]
        return Response(text=rec["response"]["text"], usage=Usage(**prov["usage"]), cost_usd=prov["cost_usd"],
                        provider=prov["provider"], model=prov["model"], origin=prov["origin"], request_hash=h,
                        extra={k: prov.get(k) for k in ("stop_reason", "refused", "truncated", "stop_details")})
