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


def test_international_and_domestic_vendors_present():
    """Keep the catalogue broad: 国外强模型 + 国内主力都要有预设入口。"""
    ids = {p["id"] for p in MODEL_PRESETS}
    for pid in (
        "claude-opus",
        "claude-sonnet",
        "gemini-flash",
        "gemini-pro",
        "doubao-seed-turbo",
        "glm-5-flash",
        "glm-5-turbo",
    ):
        assert pid in ids, f"missing preset: {pid}"


def test_glm_presets_use_live_verified_ids():
    """GLM 档位用线上实测到的模型名，避免写回已下线的老 ID。"""
    assert find_preset("glm-5")["model"] == "glm-5.3"
    assert find_preset("glm-5-flash")["model"] == "glm-5.3-flash"


def test_claude_and_gemini_use_openai_compatible_endpoints():
    """Claude / Gemini 走各自官方的 OpenAI 兼容端点，便于统一客户端调用。"""
    assert find_preset("claude-opus")["base_url"] == "https://api.anthropic.com/v1"
    g = find_preset("gemini-flash")
    assert g["base_url"].endswith("/v1beta/openai")


def test_find_unknown_returns_none():
    assert find_preset("no-such-model") is None


def test_list_returns_copies():
    a = list_model_presets()
    b = list_model_presets()
    assert a == b
    # mutating a returned dict must not corrupt the catalogue
    a[0]["model"] = "mutated"
    assert MODEL_PRESETS[0]["model"] != "mutated"
