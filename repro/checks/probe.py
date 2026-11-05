"""Behaviour probes for planted defects (E3) and owner gates (E4), run in a subprocess."""
from __future__ import annotations

import json

from .. import sandbox

DRIVER = sandbox.SUPPORT_DIR / "probe_driver.py"
ACCEPTABLE = {"D1": {"cost"}, "D2": {"reject", "treat_as_1"}}


def probe(files: dict[str, str], timeout: float = sandbox.DEFAULT_TIMEOUT) -> dict:
    key = sandbox.cache_key("probe", files, DRIVER.read_text())
    hit = sandbox.cache_get("probe", key)
    if hit is not None:
        return hit
    d = sandbox.make_workdir(files, "probe")
    try:
        out_path = d / ".probe.json"
        p = sandbox.run([str(DRIVER), str(sandbox.HELDOUT_DIR), str(out_path)], d, timeout,
                        sandbox.env_for(d, {"DEPOT_IMPL_DIR": str(d)}))
        out = json.loads(out_path.read_text()) if out_path.exists() else {
            "error": "probe failed", "timed_out": p.timed_out, "tail": p.stderr[-500:]}
    finally:
        sandbox.remove(d)
    if not out.get("timed_out"):
        sandbox.cache_put("probe", key, out)
    return out
