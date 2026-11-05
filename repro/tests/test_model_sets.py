"""Amendment A11: a second model gets its own recordings and results, and never touches the main set."""
from repro import report
from repro.orchestrate import LIVE_DIR, PKG, config, is_anthropic, model_set
from repro.providers.base import load_price_table
from repro.providers.mock import manifest


def test_configured_implementers_use_the_main_folders():
    assert model_set(None) == (config()["implementers"], LIVE_DIR, report.RESULTS_DIR)
    assert model_set("anthropic")[1:] == (LIVE_DIR, report.RESULTS_DIR)


def test_another_provider_gets_its_own_folders():
    implementers, rec_dir, results_dir = model_set("anthropic_haiku")
    assert implementers == ["anthropic_haiku"]
    assert rec_dir == LIVE_DIR / "anthropic_haiku"
    assert results_dir == PKG / "results_by_model" / "anthropic_haiku"


def test_main_replay_ignores_other_providers_recordings():
    # The main set reads recordings/*.json only, so a subfolder for another model is not part of it.
    assert LIVE_DIR / "anthropic_haiku" not in set(LIVE_DIR.glob("*.json"))


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
