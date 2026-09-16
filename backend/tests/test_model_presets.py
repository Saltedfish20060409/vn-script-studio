"""Unit tests: curated model presets catalogue."""

from __future__ import annotations

from app.core.model_presets import (
    MODEL_PRESETS,
    find_preset,
    json_mode_warning,
    list_model_presets,
    supports_json_mode,
)


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
    """默认档：DeepSeek-V4.1 Flash 的官方名是 deepseek-flash（2026-09-10 起）。"""
    d = find_preset("deepseek-flash")
    assert d is not None
    assert d["base_url"] == "https://api.deepseek.com"
    assert d["model"] == "deepseek-flash"
    assert d["json_mode"] is True
    # 旧名保留为兼容项，但模型名也指向 V4.1（官方会路由）
    legacy = find_preset("deepseek-v4-flash")
    assert legacy is not None


def test_deepseek_v41_release_names_present():
    ids = {p["id"] for p in MODEL_PRESETS}
    for pid in ("deepseek-flash", "deepseek-flash-think", "deepseek-v4-pro"):
        assert pid in ids


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
        "deepseek-flash",
        "deepseek-v4-pro",
        "kimi-k3",
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


def test_supports_json_mode_reads_the_catalogue():
    """JSON 模式判断必须跟着预设里的 json_mode 走。"""
    assert supports_json_mode("deepseek-flash") is True
    assert supports_json_mode("glm-4-flash-250414") is True
    # 思考模式与 Anthropic 兼容层都不支持 response_format
    assert supports_json_mode("deepseek-flash-think") is False
    assert supports_json_mode("claude-opus-5") is False
    assert supports_json_mode("claude-sonnet-4-8") is False
    assert supports_json_mode("qwen3:8b") is False


def test_supports_json_mode_is_liberal_for_unknown_models():
    """预设只是帮忙填端点，用户可能手填没收录的模型名 —— 不能擅自把能力判小。"""
    assert supports_json_mode("some-vendor-model-9") is True
    assert supports_json_mode("") is True
    assert supports_json_mode("   ") is True


def test_supports_json_mode_tolerates_case_and_shorthand():
    assert supports_json_mode("Claude-Opus-5") is False
    assert supports_json_mode("  deepseek-flash  ") is True
    # 手填简写时按前缀兜底
    assert supports_json_mode("claude") is False


def test_json_mode_warning_only_for_unsupported():
    assert json_mode_warning("deepseek-flash") == ""
    warn = json_mode_warning("claude-opus-5")
    assert "不支持结构化输出" in warn and "建议换一档" in warn


def test_every_preset_without_json_mode_is_documented():
    """标了不支持就要在 note 里说清楚，别让用户在设置页猜。"""
    for p in MODEL_PRESETS:
        if p["json_mode"] is False:
            assert "JSON" in str(p["note"]), f"{p['id']} 标了不支持 JSON 却没写进 note"
