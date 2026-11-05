"""Amendment A11: a second model gets its own recordings and results, and never touches the main set."""
from repro import report
from repro.orchestrate import LIVE_DIR, PKG, config, is_anthropic, model_set
from repro.providers.base import load_price_table
from repro.providers.mock import load_recordings, manifest


def config_model(name):
    return load_price_table()[name]["model"]


def test_configured_implementers_use_the_main_folders():
    assert model_set(None) == (config()["implementers"], LIVE_DIR, report.RESULTS_DIR)
    assert model_set("anthropic")[1:] == (LIVE_DIR, report.RESULTS_DIR)


def test_another_provider_gets_its_own_folders():
    implementers, rec_dir, results_dir = model_set("anthropic_haiku")
    assert implementers == ["anthropic_haiku"]
    assert rec_dir == LIVE_DIR / "anthropic_haiku"
    assert results_dir == PKG / "results_by_model" / "anthropic_haiku"


def test_main_replay_ignores_other_providers_recordings():
    # The main set reads recordings/*.json only, so another model's recordings in a subfolder are not part of it.
    main = load_recordings(LIVE_DIR)
    assert main and all(r["provenance"]["model"] == config_model("anthropic") for r in main.values())
    other = load_recordings(LIVE_DIR / "anthropic_haiku_x4")
    assert other and not set(other) & set(main)


def test_synthetic_tables_never_go_to_results(monkeypatch, tmp_path):
    # Amendment A13: `make cold` (rebuild_synthetic) once overwrote results/ with the plumbing tables.
    from repro import orchestrate
    seen = {}
    monkeypatch.setattr(orchestrate, "SYNTHETIC_RESULTS_DIR", tmp_path / "synthetic_results")
    monkeypatch.setattr(orchestrate.report, "write_all", lambda *a, **k: seen.setdefault("out_dir", k["out_dir"]))
    monkeypatch.setattr(orchestrate, "collect_all", lambda *a, **k: ([], False))
    monkeypatch.setattr(orchestrate, "build_synthetic", lambda seeds: None)
    monkeypatch.setattr(orchestrate, "manifest", lambda d: {})
    orchestrate.run_offline([0], rebuild_synthetic=True)
    assert seen["out_dir"] == tmp_path / "synthetic_results" != report.RESULTS_DIR


def test_provider_kind():
    table = load_price_table()
    assert is_anthropic(table, "anthropic") and is_anthropic(table, "anthropic_haiku")
    assert not is_anthropic(table, "openai_compat")


def test_corrections_section_only_for_the_main_set():
    tables = {t: [] for names in report.TABLES_FOR.values() for t in names}
    args = dict(recording_set="live", manifest=manifest(LIVE_DIR), incomplete=False, seeds=[0], runtime_s=0.0)
    heading = "Corrections after the first live run"
    assert heading in report.render_summary(tables, tables, {}, corrections=True, **args)
    assert heading not in report.render_summary(tables, tables, {}, corrections=False, **args)


def test_output_limit_scale_only_for_the_x4_section():
    table = load_price_table()
    assert table["anthropic"].get("max_tokens_scale", 1) == 1
    assert table["anthropic_haiku"].get("max_tokens_scale", 1) == 1
    assert table["anthropic_haiku_x4"]["max_tokens_scale"] == 4


def test_slot_scales_every_output_limit():
    from repro.agent.pipeline import Conversation, RunLog, Slot
    seen = []

    class Fake:
        def complete(self, messages, *, model, max_tokens, **_):
            from repro.providers.base import Response, Usage
            seen.append(max_tokens)
            return Response(text="ok", usage=Usage(1, 1), cost_usd=0.0, provider="fake", model=model, origin="synthetic")

    conv = Conversation(Slot(Fake(), "x", "m", None, 4), "p", 0, RunLog(), [])
    conv._call("stage", "hi", "v1", 1000)
    assert seen == [4000]
