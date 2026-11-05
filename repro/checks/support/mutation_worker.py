"""Mutation worker (subprocess): run a test selection against each mutant in a forked child.

Usage: python mutation_worker.py job.json result.json

The worker imports pytest once; each mutant gets a fresh copy of the base directory with one
file replaced, and a forked child that imports the implementation modules (an import error makes
the mutant stillborn) and runs the selected tests with ``-x``. A child that outlives the timeout is
killed and the mutant counts as killed.
"""
import importlib
import json
import os
import shutil
import signal
import sys
import tempfile
import time

import pytest  # noqa: F401  (imported once in the parent so children start fast)

sys.dont_write_bytecode = True


def _write(d, files):
    for rel, text in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)


def _child(mdir, job):
    os.chdir(mdir)
    sys.path.insert(0, mdir)
    if job.get("impl_dir_env"):
        os.environ["DEPOT_IMPL_DIR"] = mdir
    fd = os.open(os.environ.get("REPRO_MUT_DEBUG_LOG", os.devnull), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    for name in job["modules"]:
        try:
            importlib.import_module(name)
        except BaseException:
            os._exit(3)
    rc = pytest.main(["-q", "-x", "-p", "no:cacheprovider", "--rootdir", mdir, *job["tests"]])
    os._exit(0 if rc == 0 else (4 if rc == 5 else 1))


def run_one(base_dir, job, mutant):
    mdir = tempfile.mkdtemp(prefix="mut-", dir=os.path.dirname(base_dir))
    shutil.copytree(base_dir, mdir, dirs_exist_ok=True)
    if mutant.get("path"):
        _write(mdir, {mutant["path"]: mutant["source"]})
    start = time.monotonic()
    pid = os.fork()
    if pid == 0:
        try:
            _child(mdir, job)
        finally:
            os._exit(2)
    status = None
    deadline = start + job["timeout"]
    while True:
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
            break
        if time.monotonic() > deadline:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            break
        time.sleep(0.002)
    elapsed = time.monotonic() - start
    shutil.rmtree(mdir, ignore_errors=True)
    if status is None:
        return "timeout", elapsed
    code = os.waitstatus_to_exitcode(status)
    return {0: "survived", 3: "stillborn", 4: "no_tests"}.get(code, "killed"), elapsed


def main():
    job = json.load(open(sys.argv[1]))
    base_dir = tempfile.mkdtemp(prefix="mutbase-", dir=job["tmp_root"])
    _write(base_dir, job["base_files"])
    out = {}
    try:
        for m in job["mutants"]:
            outcome, elapsed = run_one(base_dir, job, m)
            out[m["id"]] = {"outcome": outcome, "seconds": round(elapsed, 3)}
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
    json.dump(out, open(sys.argv[2], "w"))


if __name__ == "__main__":
    main()
