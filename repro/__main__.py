"""Command line: python -m repro {run, estimate, build-synthetic, heldout}."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time


def _block_network() -> None:
    def blocked(*_a, **_k):
        raise OSError("network access is disabled during an offline run")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m repro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="replay recordings offline (default) or record live")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="replay recorded responses; never touches the network")
    mode.add_argument("--live", action="store_true", help="call the live providers (needs filled-in prices)")
    run.add_argument("--budget-usd", type=float, default=None)
    run.add_argument("--owner-approved-budget", action="store_true")
    run.add_argument("--yes", action="store_true", help="skip the confirmation question (live only)")
    run.add_argument("--rebuild-synthetic", action="store_true", help="rebuild the synthetic plumbing set first")
    run.add_argument("--seeds", type=str, default=None, help="comma-separated agent seeds (default: config)")
    run.add_argument("--provider", type=str, default=None,
                     help="run one other provider from prices.toml, with its own recordings/<name>/ and "
                          "results_by_model/<name>/ (default: the configured implementers)")
    est = sub.add_parser("estimate", help="print the live cost estimate without calling anything")
    est.add_argument("--provider", type=str, default=None)
    sub.add_parser("build-synthetic", help="rebuild the synthetic plumbing recording set")
    sub.add_parser("heldout", help="run the hidden suite against the hand reference")
    args = ap.parse_args(argv)

    if args.cmd == "estimate":
        from .estimate import estimate, format_estimate
        from .orchestrate import config
        cfg = config()
        providers = [args.provider] if args.provider else cfg["implementers"]
        print(format_estimate(estimate(seeds=cfg["agent_seeds"], providers=providers)))
        return 0
    if args.cmd == "heldout":
        from .oracle.runner import reference_files, run_heldout
        r = run_heldout(reference_files())
        print(f"held-out suite against reference_hand.py: {r['n_passed']}/{r['n_tests']} passed")
        return 0 if r["n_passed"] == r["n_tests"] else 1
    if args.cmd == "build-synthetic":
        _block_network()
        from .orchestrate import build_synthetic, config
        print(json.dumps({k: v for k, v in build_synthetic(config()["agent_seeds"]).items() if k != "entries"}))
        return 0
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else None
    if args.live:
        if args.budget_usd is None:
            ap.error("--live needs --budget-usd")
        from .orchestrate import run_live
        try:
            out = run_live(args.budget_usd, args.owner_approved_budget, args.yes, seeds, provider=args.provider)
        except PermissionError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    else:
        _block_network()
        from .orchestrate import run_offline
        t = time.monotonic()
        out = run_offline(seeds, rebuild_synthetic=args.rebuild_synthetic, provider=args.provider)
        out["wall_seconds"] = round(time.monotonic() - t, 1)
    print(json.dumps({k: v for k, v in out.items() if k != "verdicts"}, indent=1))
    print("verdicts:", json.dumps({k: (v.get("verdict") or "NOT RUN (synthetic only)") for k, v in out["verdicts"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
