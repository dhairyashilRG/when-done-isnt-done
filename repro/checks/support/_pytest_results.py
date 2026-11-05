"""pytest plugin: write one JSON record per test (outcome, clause tags, short failure message).

Used for the agent's own tests and for the held-out suite. Loaded with ``-p _pytest_results``;
the output path comes from ``REPRO_RESULTS_JSON``. Clause tags come from the test name and its
docstring (``C04`` / ``[C04]``), as the test-writing prompt asks.
"""
import json
import os
import re

_TAG = re.compile(r"(?<![A-Za-z0-9])C(\d{2})(?![0-9])")
_records = {}
_order = []


def _tags(name, doc):
    found = []
    for text in (name or "", doc or ""):
        for m in _TAG.finditer(text):
            tag = "C" + m.group(1)
            if tag not in found and 1 <= int(m.group(1)) <= 32:
                found.append(tag)
    return found


def _first_line(doc):
    for line in (doc or "").strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        fn = getattr(item, "function", None)
        doc = getattr(fn, "__doc__", None)
        base = getattr(item, "originalname", None) or item.name
        _records[item.nodeid] = {"nodeid": item.nodeid, "name": item.name, "outcome": "not_run",
                                 "clauses": _tags(base, doc), "doc": _first_line(doc), "message": ""}
        _order.append(item.nodeid)


def pytest_runtest_logreport(report):
    rec = _records.setdefault(report.nodeid, {"nodeid": report.nodeid, "name": report.nodeid, "outcome": "not_run",
                                              "clauses": [], "doc": "", "message": ""})
    if report.failed:
        rec["outcome"] = "failed"
        crash = getattr(report.longrepr, "reprcrash", None)
        msg = getattr(crash, "message", None) or str(report.longrepr).splitlines()[-1:]
        rec["message"] = (msg if isinstance(msg, str) else " ".join(msg))[:500]
    elif report.when == "call" and report.passed and rec["outcome"] != "failed":
        rec["outcome"] = "passed"
    elif report.skipped and rec["outcome"] == "not_run":
        rec["outcome"] = "skipped"


def pytest_collectreport(report):
    if report.failed:
        key = "collect::" + report.nodeid
        _records[key] = {"nodeid": key, "name": key, "outcome": "error", "clauses": [], "doc": "",
                         "message": str(report.longrepr).splitlines()[-1][:500] if report.longrepr else ""}
        _order.append(key)


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("REPRO_RESULTS_JSON")
    if not path:
        return
    out = [_records[k] for k in _order if k in _records]
    with open(path, "w") as fh:
        json.dump({"exitstatus": int(exitstatus), "tests": out}, fh)
