"""Run agent-written (or reference) code in a temporary directory, in a subprocess, with a timeout.

Agent code is never imported into the harness process (brief 1). Every subprocess gets
``checks/support`` first on PYTHONPATH, whose ``sitecustomize`` disables network access.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent
SUPPORT_DIR = PKG_DIR / "checks" / "support"
HELDOUT_DIR = PKG_DIR / "oracle" / "heldout"
CACHE_DIR = ROOT_DIR / ".cache"
DEFAULT_TIMEOUT = 20.0
_TMP_ROOT = Path(tempfile.gettempdir()).resolve() / "repro-harness"


@dataclass
class Proc:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def safe_relpath(path: str) -> str | None:
    """Accept only plain relative paths inside the work directory."""
    p = Path(path)
    if p.is_absolute() or not path or any(part in ("..", "") for part in p.parts) or path.startswith("~"):
        return None
    return p.as_posix()


def make_workdir(files: dict[str, str], prefix: str = "work") -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix=prefix + "-", dir=_TMP_ROOT))
    write_files(d, files)
    return d


def write_files(d: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        rel = safe_relpath(rel)
        if rel is None:
            continue
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def remove(d: Path) -> None:
    shutil.rmtree(d, ignore_errors=True)


def env_for(workdir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "REPRO_MUT_DEBUG_LOG")}
    env["PYTHONPATH"] = os.pathsep.join([str(SUPPORT_DIR), str(workdir)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env.update(extra or {})
    return env


def run(args: list[str], cwd: Path, timeout: float = DEFAULT_TIMEOUT, env: dict[str, str] | None = None) -> Proc:
    try:
        cp = subprocess.run([sys.executable, *args], cwd=cwd, env=env or env_for(cwd), capture_output=True,
                            text=True, timeout=timeout)
        return Proc(cp.returncode, cp.stdout, cp.stderr, False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return Proc(None, out, err, True)


def run_pytest(workdir: Path, targets: list[str], timeout: float = DEFAULT_TIMEOUT, plugins: tuple[str, ...] = (),
               env_extra: dict[str, str] | None = None) -> dict:
    """Run pytest in a subprocess; return the ``_pytest_results`` JSON plus process info."""
    out_json = workdir / ".repro_results.json"
    if out_json.exists():
        out_json.unlink()
    extra = {"REPRO_RESULTS_JSON": str(out_json), **(env_extra or {})}
    args = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "_pytest_results"]
    for p in plugins:
        args += ["-p", p]
    args += ["--rootdir", str(workdir), *targets]
    proc = run(args, workdir, timeout, env_for(workdir, extra))
    result = {"tests": [], "exitstatus": None}
    if out_json.exists():
        try:
            result = json.loads(out_json.read_text())
        except json.JSONDecodeError:
            pass
    result["timed_out"] = proc.timed_out
    result["returncode"] = proc.returncode
    if not result["tests"] and not proc.timed_out:
        result["stderr_tail"] = (proc.stdout + proc.stderr)[-1500:]
    return result


# ------------------------------------------------------------------ content-addressed cache
def cache_key(*parts) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(parts, sort_keys=True, default=str).encode())
    return h.hexdigest()


def cache_get(kind: str, key: str):
    if os.environ.get("REPRO_NO_CACHE"):
        return None
    p = CACHE_DIR / kind / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


def cache_put(kind: str, key: str, value) -> None:
    p = CACHE_DIR / kind / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(p)
