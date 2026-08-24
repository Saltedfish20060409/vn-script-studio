"""Unit tests for browser-supplied LLM credential headers (no DB).

Covers the layer-bound base_url + SSRF guard (credential-exfiltrating SSRF fix).
"""
from app.core.llm_client_override import merge_llm_credentials, parse_llm_headers
from app.llm_models import DEFAULT_LLM_MODEL

SERVER = {
    "api_key": "sk-s",
    "base_url": "https://api.deepseek.com",
    "model": "s-model",
    "provider": "openai",
}


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
        override={
            "api_key": "sk-c",
            "base_url": "https://api.deepseek.com",
            "model": "c-model",
        },
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server=SERVER,
    )
    assert out["api_key"] == "sk-c"
    assert out["base_url"] == "https://api.deepseek.com"
    assert out["model"] == "c-model"
    assert out["source"] == "client"
    assert out["critic_api_key"] == "sk-c"


def test_merge_falls_back_user_then_server():
    user = merge_llm_credentials(
        override=None,
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server=SERVER,
    )
    assert user["source"] == "user"
    assert user["api_key"] == "sk-u"

    server = merge_llm_credentials(override=None, user_creds=None, server=SERVER)
    assert server["source"] == "server"
    assert server["api_key"] == "sk-s"
    assert server["base_url"] == "https://api.deepseek.com"


def test_client_url_without_client_key_is_rejected():
    """SSRF fix: client sending base_url but NO own key must NOT control the URL.

    Old behaviour routed server/user key to the client-supplied URL (credential
    exfiltration). Now the URL falls through to the user layer (their key's
    endpoint), never to a client URL the client has no key for.
    """
    out = merge_llm_credentials(
        override={"base_url": "https://attacker.example", "model": "moonshot-v1-32k"},
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server=SERVER,
    )
    assert out["api_key"] == "sk-u"
    # client URL rejected (no client key) → falls to user URL
    assert out["base_url"] != "https://attacker.example"
    assert out["model"] == "moonshot-v1-32k"
    assert out["source"] == "client"


def test_client_url_with_client_key_is_honored():
    out = merge_llm_credentials(
        override={
            "api_key": "sk-c",
            "base_url": "https://api.deepseek.com",
            "model": "c-model",
        },
        user_creds=None,
        server=SERVER,
    )
    assert out["api_key"] == "sk-c"
    assert out["base_url"] == "https://api.deepseek.com"


def test_server_key_forces_server_url_even_with_client_url():
    """Server key → server URL, even if client supplies a URL (SSRF guard)."""
    out = merge_llm_credentials(
        override={"base_url": "https://attacker.example"},
        user_creds=None,
        server=SERVER,
    )
    assert out["api_key"] == "sk-s"
    assert out["base_url"] == "https://api.deepseek.com"


def test_http_or_metadata_base_url_rejected():
    """http scheme / cloud metadata must never be a target."""
    for bad in ("http://attacker.example", "http://169.254.169.254", "http://127.0.0.1"):
        out = merge_llm_credentials(
            override={"api_key": "sk-c", "base_url": bad},
            user_creds=None,
            server=SERVER,
        )
        assert out["base_url"] != bad, f"{bad} should be rejected"


def test_merge_independent_critic():
    out = merge_llm_credentials(
        override={
            "api_key": "sk-main",
            "critic_api_key": "sk-critic",
            "critic_base_url": "https://api.deepseek.com",
            "critic_model": "critic-model",
        },
        user_creds=None,
        server=SERVER,
    )
    assert out["api_key"] == "sk-main"
    assert out["critic_api_key"] == "sk-critic"
    assert out["critic_base_url"] == "https://api.deepseek.com"
    assert out["critic_model"] == "critic-model"


def test_merge_empty_model_uses_v4_flash_default():
    out = merge_llm_credentials(override=None, user_creds=None, server={})
    assert out["model"] == DEFAULT_LLM_MODEL
    assert out["critic_model"] == DEFAULT_LLM_MODEL
