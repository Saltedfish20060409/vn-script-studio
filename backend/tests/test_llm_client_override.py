"""Unit tests for browser-supplied LLM credential headers (no DB)."""

from app.core.llm_client_override import merge_llm_credentials, parse_llm_headers


def test_parse_llm_headers_empty():
    assert parse_llm_headers({}) is None
    assert parse_llm_headers({"authorization": "Bearer x"}) is None


def test_parse_llm_headers_picks_nonempty():
    got = parse_llm_headers(
        {
            "x-llm-api-key": " sk-browser ",
            "x-llm-base-url": "https://api.deepseek.com",
            "x-llm-model": "deepseek-chat",
            "x-llm-critic-api-key": "",
        }
    )
    assert got == {
        "api_key": "sk-browser",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    }


def test_merge_prefers_client_over_user_and_server():
    out = merge_llm_credentials(
        override={"api_key": "sk-c", "base_url": "https://c.example", "model": "c-model"},
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server={
            "api_key": "sk-s",
            "base_url": "https://s.example",
            "model": "s-model",
            "provider": "openai",
        },
    )
    assert out["api_key"] == "sk-c"
    assert out["base_url"] == "https://c.example"
    assert out["model"] == "c-model"
    assert out["source"] == "client"
    assert out["critic_api_key"] == "sk-c"


def test_merge_falls_back_user_then_server():
    user = merge_llm_credentials(
        override=None,
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server={"api_key": "sk-s", "base_url": "https://s.example", "model": "s-model"},
    )
    assert user["source"] == "user"
    assert user["api_key"] == "sk-u"

    server = merge_llm_credentials(
        override=None,
        user_creds=None,
        server={"api_key": "sk-s", "base_url": "https://s.example", "model": "s-model"},
    )
    assert server["source"] == "server"
    assert server["api_key"] == "sk-s"


def test_merge_client_url_keeps_user_key():
    out = merge_llm_credentials(
        override={"base_url": "https://api.moonshot.cn", "model": "moonshot-v1-32k"},
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server={"api_key": "sk-s", "base_url": "https://s.example", "model": "s-model"},
    )
    assert out["api_key"] == "sk-u"
    assert out["base_url"] == "https://api.moonshot.cn"
    assert out["model"] == "moonshot-v1-32k"
    assert out["source"] == "client"


def test_merge_independent_critic():
    out = merge_llm_credentials(
        override={
            "api_key": "sk-main",
            "critic_api_key": "sk-critic",
            "critic_base_url": "https://critic.example",
            "critic_model": "critic-model",
        },
        user_creds=None,
        server={"api_key": "sk-s", "base_url": "https://s.example", "model": "s-model"},
    )
    assert out["api_key"] == "sk-main"
    assert out["critic_api_key"] == "sk-critic"
    assert out["critic_base_url"] == "https://critic.example"
    assert out["critic_model"] == "critic-model"
