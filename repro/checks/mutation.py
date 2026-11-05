"""A small deterministic AST mutator written for this harness (brief 3), and the mutation runner.

Operators (11): comparison flip, ``and``/``or`` swap, integer constant +1, integer constant -1,
``return`` of a default value (``None``), dropped statement, swapped first two call arguments,
negated condition, emptied container literal (defaults and initialisers), removed ``raise``, and
inverted boolean constant.

Sampling: all mutation points of a module are enumerated in ``ast.walk`` order, then at most
``cap`` (60) are drawn with ``random.Random(seed)`` (seed 7). A passing baseline is required: the
suite is reduced to the tests that pass on the unmutated code, and the score is undefined when
that set is empty. Stillborn mutants (syntax or import errors) are excluded; a timeout is killed.
Score = killed / (total - stillborn), per module.
"""
from __future__ import annotations

import ast
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import sandbox
from .empty_guard import Check

OPERATORS = ["cmp_flip", "bool_op", "int_plus1", "int_minus1", "return_default", "drop_stmt", "swap_args",
             "negate_cond", "empty_container", "remove_raise", "bool_const"]
CMP_FLIP = {ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.Eq: ast.NotEq,
            ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
DEFAULT_CAP = 60
DEFAULT_SEED = 7
WORKER = sandbox.SUPPORT_DIR / "mutation_worker.py"


def _is_docstring(parent, field, idx, stmt) -> bool:
    return (field == "body" and idx == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
            and isinstance(parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))


def points(src: str) -> list[tuple]:
    """Every mutation point in ``src`` as (operator, node_index[, field, stmt_index])."""
    tree = ast.parse(src)
    pts: list[tuple] = []
    for i, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in CMP_FLIP:
            pts.append(("cmp_flip", i))
        elif isinstance(node, ast.BoolOp):
            pts.append(("bool_op", i))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            pts.append(("bool_const", i))
        elif isinstance(node, ast.Constant) and isinstance(node.value, int):
            pts += [("int_plus1", i), ("int_minus1", i)]
        elif isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            pts.append(("return_default", i))
        elif isinstance(node, ast.Call):
            pos = [a for a in node.args if not isinstance(a, ast.Starred)]
            if len(pos) >= 2 and len(pos) == len(node.args) and ast.dump(pos[0]) != ast.dump(pos[1]):
                pts.append(("swap_args", i))
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            pts.append(("negate_cond", i))
        elif (isinstance(node, ast.List) and isinstance(node.ctx, ast.Load) and node.elts) or (
                isinstance(node, ast.Dict) and node.keys) or (isinstance(node, ast.Set) and node.elts):
            pts.append(("empty_container", i))
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for j, stmt in enumerate(stmts):
                if isinstance(stmt, ast.Raise):
                    pts.append(("remove_raise", i, field, j))
                elif isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr)) and not _is_docstring(
                        node, field, j, stmt):
                    pts.append(("drop_stmt", i, field, j))
    return pts


def apply(src: str, point: tuple) -> str:
    tree = ast.parse(src)
    nodes = list(ast.walk(tree))
    op, idx = point[0], point[1]
    node = nodes[idx]
    if op == "cmp_flip":
        node.ops = [CMP_FLIP[type(node.ops[0])]()]
    elif op == "bool_op":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif op == "bool_const":
        node.value = not node.value
    elif op == "int_plus1":
        node.value = node.value + 1
    elif op == "int_minus1":
        node.value = node.value - 1
    elif op == "return_default":
        node.value = ast.Constant(None)
    elif op == "swap_args":
        node.args[0], node.args[1] = node.args[1], node.args[0]
    elif op == "negate_cond":
        node.test = ast.UnaryOp(ast.Not(), node.test)
    elif op == "empty_container":
        if isinstance(node, ast.Dict):
            node.keys, node.values = [], []
        elif isinstance(node, ast.Set):  # an empty set literal does not exist: use set()
            return _replace_node(tree, node, ast.Call(ast.Name("set", ast.Load()), [], []))
        else:
            node.elts = []
    elif op in ("drop_stmt", "remove_raise"):
        getattr(node, point[2])[point[3]] = ast.Pass()
    else:  # pragma: no cover
        raise ValueError(op)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _replace_node(tree, old, new) -> str:
    class R(ast.NodeTransformer):
        def generic_visit(self, n):
            super().generic_visit(n)
            return n

        def visit(self, n):
            if n is old:
                return new
            return super().visit(n)

    tree = R().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def sample_mutants(path: str, src: str, cap: int = DEFAULT_CAP, seed: int = DEFAULT_SEED) -> list[dict]:
    """At most ``cap`` mutants of one module, drawn deterministically with ``random.Random(seed)``."""
    try:
        pts = points(src)
    except SyntaxError:
        return []
    chosen = sorted(random.Random(seed).sample(range(len(pts)), min(cap, len(pts))))
    out = []
    for k in chosen:
        pt = pts[k]
        mid = f"{path}#{k}:{pt[0]}"
        try:
            mutated = apply(src, pt)
            compile(mutated, path, "exec")
            out.append({"id": mid, "path": path, "operator": pt[0], "source": mutated})
        except (SyntaxError, ValueError, TypeError) as exc:
            out.append({"id": mid, "path": path, "operator": pt[0], "stillborn": f"{type(exc).__name__}"})
    return out


def _pool_size() -> int:
    return max(1, min(12, (os.cpu_count() or 2) - 1))


def _run_workers(base_files: dict, tests: list[str], modules: list[str], mutants: list[dict], timeout: float,
                 impl_dir_env: bool) -> dict:
    if not mutants:
        return {}
    tmp_root = sandbox.make_workdir({}, "mutation")
    n = min(_pool_size(), len(mutants))
    shards = [mutants[i::n] for i in range(n)]

    def go(i_shard):
        i, shard = i_shard
        job = {"base_files": base_files, "tests": tests, "modules": modules, "mutants": shard,
               "timeout": timeout, "tmp_root": str(tmp_root), "impl_dir_env": impl_dir_env}
        jp, rp = tmp_root / f"job{i}.json", tmp_root / f"res{i}.json"
        jp.write_text(json.dumps(job))
        env = sandbox.env_for(tmp_root)
        budget = 60 + len(shard) * (timeout + 2)
        subprocess.run([sys.executable, str(WORKER), str(jp), str(rp)], env=env, timeout=budget,
                       capture_output=True)
        return json.loads(rp.read_text()) if rp.exists() else {m["id"]: {"outcome": "error"} for m in shard}

    try:
        results = {}
        with ThreadPoolExecutor(max_workers=n) as ex:
            for part in ex.map(go, enumerate(shards)):
                results.update(part)
        return results
    finally:
        sandbox.remove(tmp_root)


class MutationCheck(Check):
    """Input: {module: [outcome, ...]}. Measured: per-module score. Passes when every score is defined."""

    name = "mutation"

    def check(self, outcomes):
        scores = {m: score(v) for m, v in outcomes.items()}
        return all(s is not None for s in scores.values()), {m: s for m, s in scores.items() if s is not None}


def score(outcomes: list[str]) -> float | None:
    counted = [o for o in outcomes if o != "stillborn"]
    if not counted:
        return None
    return sum(o in ("killed", "timeout") for o in counted) / len(counted)


def mutation_scores(files: dict[str, str], test_targets: list[str], modules: list[str], *, cap: int = DEFAULT_CAP,
                    seed: int = DEFAULT_SEED, impl_dir_env: bool = False, max_timeout: float = 20.0) -> dict:
    """Mutation score per module path in ``modules`` against the tests in ``test_targets``.

    Returns {"baseline": {...}, "modules": {path: {"score", "total", "stillborn", "killed", "survived",
    "timeout"}}}. Cached by content.
    """
    key = sandbox.cache_key("mutation", files, test_targets, modules, cap, seed, impl_dir_env, max_timeout,
                            WORKER.read_text(), Path(__file__).read_text())
    hit = sandbox.cache_get("mutation", key)
    if hit is not None:
        return hit
    # 1. baseline: which tests pass on the unmutated code?
    d = sandbox.make_workdir(files, "mutbaseline")
    try:
        t0 = time.monotonic()
        env_extra = {"DEPOT_IMPL_DIR": str(d)} if impl_dir_env else None
        base = sandbox.run_pytest(d, test_targets, timeout=max(60.0, max_timeout), env_extra=env_extra)
        base_seconds = time.monotonic() - t0
    finally:
        sandbox.remove(d)
    passing = [t["nodeid"] for t in base.get("tests", []) if t["outcome"] == "passed"]
    total_tests = len(base.get("tests", []))
    out = {"baseline": {"tests": total_tests, "passing": len(passing), "seconds": round(base_seconds, 3)},
           "modules": {}}
    present = [m for m in modules if m in files]
    if not passing:
        out["baseline"]["error"] = "no passing baseline"
        for m in present:
            out["modules"][m] = {"score": None, "reason": "no passing baseline"}
        sandbox.cache_put("mutation", key, out)
        return out
    timeout = min(max_timeout, max(5.0, 20 * base_seconds))
    out["baseline"]["mutant_timeout"] = round(timeout, 2)
    import_names = [Path(m).stem for m in present]
    mutants, pre_stillborn = [], {}
    for m in present:
        for mu in sample_mutants(m, files[m], cap, seed):
            if "stillborn" in mu:
                pre_stillborn[mu["id"]] = m
            else:
                mutants.append(mu)
    # baseline check through the worker itself (same mechanism as the mutants)
    check = _run_workers(files, passing, import_names, [{"id": "__baseline__", "path": None, "source": ""}],
                         max(timeout, 30.0), impl_dir_env)
    if check.get("__baseline__", {}).get("outcome") != "survived":
        out["baseline"]["error"] = f"baseline did not pass in the worker: {check.get('__baseline__')}"
        for m in present:
            out["modules"][m] = {"score": None, "reason": "baseline failed in worker"}
        sandbox.cache_put("mutation", key, out)
        return out
    res = _run_workers(files, passing, import_names, mutants, timeout, impl_dir_env)
    by_module: dict[str, list[str]] = {m: [] for m in present}
    for mu in mutants:
        by_module[mu["path"]].append(res.get(mu["id"], {}).get("outcome", "error"))
    for mid, m in pre_stillborn.items():
        by_module[m].append("stillborn")
    for m, outs in by_module.items():
        errors = sum(o in ("error", "no_tests") for o in outs)
        outs = ["stillborn" if o in ("error", "no_tests") else o for o in outs]  # unknown outcome: excluded
        out["modules"][m] = {"score": score(outs), "total": len(outs), "stillborn": outs.count("stillborn"),
                             "worker_errors": errors,
                             "killed": outs.count("killed"), "timeout": outs.count("timeout"),
                             "survived": outs.count("survived")}
    sandbox.cache_put("mutation", key, out)
    return out
