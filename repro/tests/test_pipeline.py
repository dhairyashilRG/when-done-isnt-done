"""Pipeline plumbing: parsers, prompt hygiene, the code gate, the sandbox, and the spec's agent copy."""
import pytest

from repro import sandbox
from repro.agent import pipeline
from repro.agent.pipeline import (Conversation, RunLog, Slot, g1_gate_problem, parse_ask_owner, parse_files,
                                  parse_fix_report, parse_self_report, render, template)
from repro.oracle.runner import heldout_files
from repro.providers.base import Response, Usage
from repro.spec import CLAUSE_IDS, agent_data_toml, agent_spec_text, clauses, data


def test_planted_comments_are_stripped_from_the_agent_copy():
    raw = (pipeline.REPO_DIR.parent.parent / "spec" / "data.toml").read_text()
    assert raw.count("planted") == 2
    agent = agent_data_toml()
    assert "planted" not in agent.lower()
    assert "transfer_credit_cents_per_unit = 25" in agent and "shelf_life_days = 0" in agent
    import tomllib
    assert tomllib.loads(agent) == data()


def test_spec_has_32_clauses_and_seed_permutes_rows():
    assert list(clauses()) == CLAUSE_IDS
    a, b = agent_spec_text(0), agent_spec_text(1)
    assert a != b and sorted(a.splitlines()) == sorted(b.splitlines()) and agent_spec_text(0) == a


def test_no_prompt_contains_harness_only_material():
    secrets = ["heldout", "held-out", "planted", "reference_hand", "D1", "D2", "G1:", "intent"]
    names = [p.read_text() for p in heldout_files()]
    test_names = {line.split("(")[0].split()[-1] for src in names for line in src.splitlines()
                  if line.startswith("def test_")}
    for p in sorted(pipeline.PROMPTS_DIR.glob("*.md")):
        text = p.read_text()
        for s in secrets:
            assert s not in text, (p.name, s)
        assert not any(t in text for t in test_names), p.name
    rendered, _ = render("implement", spec=agent_spec_text(0), data=agent_data_toml(),
                         interface=render("interface")[0], vendor=pipeline.vendor_source())
    assert "planted" not in rendered and "reference_hand" not in rendered


def test_template_version_tracks_content():
    text, version = template("implement")
    assert version.startswith("implement.v1#") and len(version.split("#")[1]) == 10


def test_ask_owner_tag_parser():
    text = "x <ask_owner>Which rounding mode?</ask_owner> y <ask_owner>\n What penalty? \n</ask_owner><ask_owner> </ask_owner>"
    assert parse_ask_owner(text) == ["Which rounding mode?", "What penalty?"]
    assert parse_ask_owner("no tags") == []


def test_file_parser_rejects_paths_outside_the_workdir():
    text = ('<file path="inventory.py">\nX = 1\n</file>\n<file path="../evil.py">bad</file>'
            '<file path="/etc/x.py">bad</file><file path="vendor/rounding.py">\n```python\nY = 2\n```\n</file>')
    assert parse_files(text) == {"inventory.py": "X = 1\n", "vendor/rounding.py": "Y = 2\n"}


def test_self_report_and_fix_report_parsers():
    sr = parse_self_report('<self_report>{"clauses": {"C01": {"status": "done", "evidence": "e"}, '
                           '"C02": "partial", "C03": {"status": "maybe"}}, "overall": "DONE"}</self_report>')
    assert sr["clauses"]["C01"] == {"status": "done", "evidence": "e"}
    assert sr["clauses"]["C02"]["status"] == "partial" and sr["clauses"]["C03"]["status"] == "not_done"
    assert sr["clauses"]["C32"]["status"] == "not_done" and sr["overall"] == "DONE"
    assert parse_self_report("nothing")["parsed"] is False
    assert parse_fix_report('<fix_report>{"1": "applied", "2": "not_applied"}</fix_report>') == {"1": True, "2": False}


def test_g1_code_gate_checks_the_signature():
    ok = "class Depot:\n    def __init__(self, warehouses, capacities, opening_cash, rounding_mode):\n        pass\n"
    bad = ok.replace("rounding_mode)", "rounding_mode='ROUND_HALF_UP')")
    kw = "class Depot:\n    def __init__(self, w, c, o, *, rounding_mode='x'):\n        pass\n"
    assert g1_gate_problem({"inventory.py": ok}) == ""
    assert "default" in g1_gate_problem({"inventory.py": bad})
    assert "default" in g1_gate_problem({"inventory.py": kw})
    assert "no `Depot`" in g1_gate_problem({"inventory.py": "X = 1\n"})


class Scripted:
    name = "scripted"

    def __init__(self, texts):
        self.texts = list(texts)
        self.seen = []

    def complete(self, messages, *, model, max_tokens, temperature, seed=None, template_version="", label=""):
        self.seen.append((label, [dict(m) for m in messages]))
        return Response(self.texts.pop(0), Usage(), 0.0, "scripted", model, "synthetic", request_hash=label)


def test_ask_owner_is_answered_logged_and_the_agent_continues():
    prov = Scripted(["<ask_owner>Which penalty?</ask_owner>", '<file path="a.py">\nA = 1\n</file>',
                     "<self_report>{}</self_report>"])
    log = RunLog()
    conv = Conversation(Slot(prov, "scripted", "m"), "r", 0, log)
    out = conv.ask("demo", "demo", need=pipeline.has_files)
    assert parse_files(out) == {"a.py": "A = 1\n"}
    assert log.ask_owner == [{"stage": "demo", "label": "r/demo", "question": "Which penalty?",
                              "reply": pipeline.OWNER_REPLY}]
    assert pipeline.OWNER_REPLY in prov.seen[1][1][-1]["content"]
    assert [c.label for c in log.calls] == ["r/demo", "r/demo.owner1"]
    assert all(c.origin == "synthetic" for c in log.calls)


def test_sandbox_runs_code_in_a_subprocess_with_timeout_and_no_network(tmp_path):
    d = sandbox.make_workdir({"spin.py": "while True:\n    pass\n",
                              "net.py": "import socket\nsocket.create_connection(('127.0.0.1', 9))\n"})
    try:
        p = sandbox.run(["spin.py"], d, timeout=1.0)
        assert p.timed_out and not p.ok
        n = sandbox.run(["net.py"], d, timeout=10.0)
        assert n.returncode != 0 and "network access is disabled" in n.stderr
    finally:
        sandbox.remove(d)


def test_impl_only_drops_tests_and_demo():
    files = {"inventory.py": "", "test_depot.py": "", "demo.py": "", "test_extra.py": "", "data.toml": ""}
    assert set(pipeline.impl_only(files)) == {"inventory.py", "data.toml"}


@pytest.mark.parametrize("name", ["implement", "test", "fix", "demo", "self_report", "apply_review",
                                  "reference_dep", "reference_ind", "resolve_mismatch", "validators",
                                  "validators_later", "owner_reply", "continue", "system", "interface"])
def test_every_template_exists_and_is_versioned(name):
    _text, version = template(name)
    assert ".v1#" in version


def test_failure_messages_are_stable_across_runs():
    a = "assert 1 == 2\n +  where 1 = <inventory.Depot object at 0x10860a9c0>.cash /private/var/folders/x/T/work-1/a.py"
    b = "assert 1 == 2\n +  where 1 = <inventory.Depot object at 0x10a39e9c0>.cash /var/folders/x/T/work-2/a.py"
    assert pipeline.stable_message(a) == pipeline.stable_message(b)
