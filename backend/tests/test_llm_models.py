from app.llm_models import DEFAULT_LLM_MODEL, resolve_chat_model


def test_default_is_v41_flash():
    """2026-09-10 起 DeepSeek 正式名是 deepseek-flash（服务端 V4.1 Flash）。"""
    assert DEFAULT_LLM_MODEL == "deepseek-flash"
    assert resolve_chat_model(None) == ("deepseek-flash", "disabled")
    assert resolve_chat_model("  ") == ("deepseek-flash", "disabled")


def test_legacy_deepseek_aliases_route_to_v41():
    """已是历史名词的 chat / reasoner 也要落到 V4.1 Flash 上。"""
    assert resolve_chat_model("deepseek-chat") == ("deepseek-flash", "disabled")
    assert resolve_chat_model("deepseek-reasoner") == ("deepseek-flash", "enabled")


def test_official_compat_names_route_to_v41():
    """旧模型名（V4 Flash / vision-exp）官方保留兼容，实际由 V4.1 承接。"""
    assert resolve_chat_model("deepseek-v4-flash") == ("deepseek-flash", "disabled")
    assert resolve_chat_model("deepseek-v4-flash-think") == ("deepseek-flash", "enabled")
    assert resolve_chat_model("deepseek-v4-flash-vision-exp") == (
        "deepseek-flash",
        "disabled",
    )


def test_v41_official_and_think_suffix():
    assert resolve_chat_model("deepseek-flash") == ("deepseek-flash", "disabled")
    assert resolve_chat_model("deepseek-flash-think") == ("deepseek-flash", "enabled")


def test_pro_still_passes_through():
    """Pro 仍可用（V4.1 Pro 发布前），不做改写。"""
    assert resolve_chat_model("deepseek-v4-pro") == ("deepseek-v4-pro", "disabled")
    assert resolve_chat_model("deepseek-v4-pro-think") == ("deepseek-v4-pro", "enabled")


def test_other_vendors_omit_thinking():
    assert resolve_chat_model("kimi-k2.6") == ("kimi-k2.6", None)
    assert resolve_chat_model("kimi-k3") == ("kimi-k3", None)
    assert resolve_chat_model("gpt-5") == ("gpt-5", None)
    assert resolve_chat_model("glm-5.3") == ("glm-5.3", None)
