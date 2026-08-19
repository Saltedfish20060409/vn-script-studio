from app.llm_models import DEFAULT_LLM_MODEL, resolve_chat_model


def test_default_is_v4_flash():
    assert DEFAULT_LLM_MODEL == "deepseek-v4-flash"
    assert resolve_chat_model(None) == ("deepseek-v4-flash", "disabled")
    assert resolve_chat_model("  ") == ("deepseek-v4-flash", "disabled")


def test_legacy_deepseek_aliases():
    assert resolve_chat_model("deepseek-chat") == ("deepseek-v4-flash", "disabled")
    assert resolve_chat_model("deepseek-reasoner") == ("deepseek-v4-flash", "enabled")


def test_v4_official_and_think_suffix():
    assert resolve_chat_model("deepseek-v4-flash") == ("deepseek-v4-flash", "disabled")
    assert resolve_chat_model("deepseek-v4-flash-think") == (
        "deepseek-v4-flash",
        "enabled",
    )
    assert resolve_chat_model("deepseek-v4-pro") == ("deepseek-v4-pro", "disabled")
    assert resolve_chat_model("deepseek-v4-pro-think") == ("deepseek-v4-pro", "enabled")


def test_other_vendors_omit_thinking():
    assert resolve_chat_model("kimi-k2.6") == ("kimi-k2.6", None)
    assert resolve_chat_model("gpt-5") == ("gpt-5", None)
