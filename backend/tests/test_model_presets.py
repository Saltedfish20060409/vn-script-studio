"""Unit tests: curated model presets catalogue."""

from __future__ import annotations

from app.core.model_presets import MODEL_PRESETS, find_preset, list_model_presets


def test_presets_nonempty_and_unique_ids():
    ids = [p["id"] for p in MODEL_PRESETS]
    assert len(ids) >= 5
    assert len(set(ids)) == len(ids)


def test_preset_shape():
    for p in MODEL_PRESETS:
        assert p["label"]
        assert p["vendor"]
        assert p["base_url"].startswith("http")
        assert p["model"]
        assert isinstance(p["json_mode"], bool)
        assert isinstance(p["context_k"], int) and p["context_k"] > 0


def test_deepseek_default_present():
    d = find_preset("deepseek-v4-flash")
    assert d is not None
    assert d["base_url"] == "https://api.deepseek.com"
    assert d["model"] == "deepseek-v4-flash"
    assert d["json_mode"] is True


def test_ollama_local_present():
    o = find_preset("local-ollama")
    assert o is not None
    assert o["base_url"].startswith("http://localhost")


def test_old_models_removed_and_latest_present():
    """Presets track the current generation — retired names must not linger."""
    ids = {p["id"] for p in MODEL_PRESETS}
    for retired in (
        "deepseek-chat",
        "deepseek-reasoner",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
        "glm-4-plus",
        "gpt-4o",
        "gpt-4o-mini",
    ):
        assert retired not in ids, f"retired model still listed: {retired}"
    for latest in (
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "kimi-k2.6",
        "qwen-max",
        "glm-5",
        "gpt-5",
    ):
        assert latest in ids, f"missing latest model: {latest}"


def test_find_unknown_returns_none():
    assert find_preset("no-such-model") is None


def test_list_returns_copies():
    a = list_model_presets()
    b = list_model_presets()
    assert a == b
    # mutating a returned dict must not corrupt the catalogue
    a[0]["model"] = "mutated"
    assert MODEL_PRESETS[0]["model"] != "mutated"
