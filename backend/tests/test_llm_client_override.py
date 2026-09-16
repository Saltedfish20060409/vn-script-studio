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

    同理，客户端带的**模型名**也必须被忽略：这一层的 key 是账号的，
    模型名就该听账号的（否则就是把账号/站方的 key 配上别人的模型名）。
    """
    out = merge_llm_credentials(
        override={"base_url": "https://attacker.example", "model": "moonshot-v1-32k"},
        user_creds={"api_key": "sk-u", "base_url": "https://u.example", "model": "u-model"},
        server=SERVER,
    )
    assert out["api_key"] == "sk-u"
    # client URL rejected (no client key) → never the client's URL
    # （u.example 解析不出来，SSRF 守卫会把它清空再回落服务端 URL —— 两种结果都算通过）
    assert out["base_url"] != "https://attacker.example"
    assert out["model"] == "u-model", "key 是账号的，模型名不能被浏览器带偏"
    assert out["source"] == "user"


def test_cleared_key_with_leftover_model_still_uses_free_tier():
    """线上真实故障：清掉自带 Key 后，浏览器里还留着上次选的模型名。

    旧行为：站方的智谱 Key 配上 "deepseek-v4-flash" 去请求智谱 → 模型不存在 →
    免费档看起来"坏了"；而且 source 被标成 client，共享额度不计入（配额绕过）。
    现在：用站方的 key 就用站方的模型名，source 也如实是 server。
    """
    out = merge_llm_credentials(
        override={"model": "deepseek-v4-flash"}, user_creds=None, server=SERVER
    )
    assert out["api_key"] == "sk-s"
    assert out["model"] == "s-model", "站方的 key 必须配站方的模型名"
    assert out["base_url"] == "https://api.deepseek.com"
    assert out["source"] == "server", "source 决定是否计入共享额度，不能被残留模型名带偏"

    # 只残留 Base URL 也一样
    out2 = merge_llm_credentials(
        override={"base_url": "https://api.deepseek.com"}, user_creds=None, server=SERVER
    )
    assert out2["source"] == "server"
    assert out2["model"] == "s-model"


def test_client_key_still_controls_its_own_model():
    """自带 Key 时，浏览器选的模型名照旧生效（这层 key 是用户自己的）。"""
    out = merge_llm_credentials(
        override={
            "api_key": "sk-c",
            "base_url": "https://api.deepseek.com",
            "model": "c-model",
        },
        user_creds={"api_key": "sk-u", "model": "u-model"},
        server=SERVER,
    )
    assert out["api_key"] == "sk-c"
    assert out["model"] == "c-model"
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


def test_user_layer_critic_base_url_unsafe_ignored():
    """用户层 critic_base_url 必须过 SSRF 守卫（此前漏校验）。"""
    out = merge_llm_credentials(
        override=None,
        user_creds={
            "api_key": "sk-u",
            "base_url": "https://api.deepseek.com",
            "critic_api_key": "sk-cu",
            "critic_base_url": "http://169.254.169.254",
        },
        server=SERVER,
    )
    assert out["critic_base_url"] != "http://169.254.169.254"
    assert out["critic_base_url"] == "https://api.deepseek.com"


def test_user_layer_critic_base_url_safe_with_own_key_honored():
    out = merge_llm_credentials(
        override=None,
        user_creds={
            "api_key": "sk-u",
            "base_url": "https://api.deepseek.com",
            "critic_api_key": "sk-cu",
            "critic_base_url": "https://api.moonshot.cn",
        },
        server=SERVER,
    )
    assert out["critic_base_url"] == "https://api.moonshot.cn"


def test_user_layer_critic_base_url_without_keys_falls_through():
    """安全 URL 但用户层没有任何自己的 key → 不采用，回退主 base_url。"""
    out = merge_llm_credentials(
        override=None,
        user_creds={"critic_base_url": "https://api.moonshot.cn"},
        server=SERVER,
    )
    assert out["critic_base_url"] == "https://api.deepseek.com"
