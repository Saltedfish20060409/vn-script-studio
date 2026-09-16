"""Request-scoped LLM credentials supplied by the browser.

The frontend stores the user's API key / base URL / model locally and attaches
them as X-LLM-* headers on API calls. Resolution order is:

    request headers  >  per-user DB creds  >  server env

Security: base_url is ALWAYS bound to the SAME layer as the api_key that
resolved. A client-supplied base_url is only honored when the client also
supplied its own api_key — otherwise a logged-in user could point the server
at an attacker URL (or 169.254.169.254) and have the server's DEEPSEEK_API_KEY
sent there (credential-exfiltrating SSRF). Additionally, base_url is validated
to be https and non-private/metadata.
"""
from __future__ import annotations

import ipaddress
import logging
from contextvars import ContextVar
from typing import Mapping, Optional
from urllib.parse import urlparse

from app.llm_models import DEFAULT_LLM_MODEL

logger = logging.getLogger(__name__)

_client_llm: ContextVar[Optional[dict[str, str]]] = ContextVar(
    "client_llm_override", default=None
)

_HEADER_MAP = {
    "x-llm-api-key": "api_key",
    "x-llm-base-url": "base_url",
    "x-llm-model": "model",
    "x-llm-critic-api-key": "critic_api_key",
    "x-llm-critic-base-url": "critic_base_url",
    "x-llm-critic-model": "critic_model",
}

# Loopback / link-local / private / metadata ranges must never be LLM targets.
_BLOCKED_IPS = {
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",  # cloud metadata (169.254.169.254)
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
    # NAT64 well-known prefix: 64:ff9b::/96 maps IPv4 literals into IPv6 —
    # is_private() is False for these, so it could bypass the IPv4 blacklist.
    "64:ff9b::/96",
}


def _is_safe_base_url(url: str) -> bool:
    """https only + resolved host must not be private/loopback/metadata."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    # hostname without dots is a single-label intranet alias (e.g. http://redis)
    if "." not in host and host != "localhost":
        return False
    try:
        import socket

        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if ipaddress.ip_address(ip).is_private:
                return False
            for net in _BLOCKED_IPS:
                if ipaddress.ip_address(ip) in ipaddress.ip_network(net):
                    return False
    except OSError:
        # DNS failure — do not route credentials to an unresolvable host
        return False
    return True


def parse_llm_headers(headers: Mapping[str, str]) -> Optional[dict[str, str]]:
    """Extract non-empty X-LLM-* fields. Returns None when none are present."""
    out: dict[str, str] = {}
    getter = getattr(headers, "get", None)
    for header, key in _HEADER_MAP.items():
        raw = getter(header) if getter else headers.get(header)  # type: ignore[arg-type]
        value = str(raw or "").strip()
        if value:
            out[key] = value
    return out or None


def set_client_llm_override(creds: Optional[dict[str, str]]) -> None:
    _client_llm.set(creds)


def get_client_llm_override() -> Optional[dict[str, str]]:
    return _client_llm.get()


def _pick(*vals: object) -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _safe_or_blank(url: str) -> str:
    """Return url when it passes the SSRF guard, else blank (fall through)."""
    return url if _is_safe_base_url(url) else ""


def merge_llm_credentials(
    *,
    override: Optional[dict[str, str]],
    user_creds: Optional[dict[str, str]],
    server: dict[str, str],
) -> dict[str, str]:
    """Merge client / user / server layers. Missing fields fall through.

    整个凭据组（key + base_url + model）**绑定在同一层**上，先决定用谁的 key，
    就只用那一层的地址和模型名：

      - 浏览器带了 key → 用它自己的 url/model（缺了才回落）
      - 账号里有 key   → 用账号的 url/model
      - 都没有         → 服务端 key + **服务端** url/model

    为什么 model 也必须绑定（线上真实踩到过）：用户清掉自己的 Key、但浏览器
    localStorage 里还留着上次选预设时的模型名，于是站方的智谱 Key 配上
    "deepseek-v4-flash" 去请求智谱 → 模型不存在 → 免费档看起来"坏了"，
    用户会以为 Key 清了就回不去免费档。同时 source 也被标成 client，
    共享额度因此不被计入（配额绕过）。base_url 早就有这层绑定，
    model 当时漏了。

    所有候选 base_url 都要过 https/非内网 的 SSRF 守卫。
    """
    o = override or {}
    u = user_creds or {}

    server_key = _pick(server.get("api_key"))
    server_url = _pick(server.get("base_url")) or "https://api.deepseek.com"

    client_key = _pick(o.get("api_key"))
    client_url = _pick(o.get("base_url"))
    user_key = _pick(u.get("api_key"))
    user_url = _pick(u.get("base_url"))

    # 先定 key（client > user > server），后面一切都跟着这一层走
    if client_key:
        api_key, key_layer = client_key, "client"
    elif user_key:
        api_key, key_layer = user_key, "user"
    else:
        api_key, key_layer = server_key, "server"

    if key_layer == "client":
        base_url = _safe_or_blank(client_url)
        model = _pick(o.get("model"), u.get("model"), server.get("model"))
        critic_model = _pick(
            o.get("critic_model"), u.get("critic_model"), server.get("critic_model"), model
        )
    elif key_layer == "user":
        base_url = _safe_or_blank(user_url)
        model = _pick(u.get("model"), server.get("model"))
        critic_model = _pick(u.get("critic_model"), server.get("critic_model"), model)
    else:
        # 用站方的 key：模型名只能由站方决定，否则就是把站方额度花在别人的模型上
        base_url = ""
        model = _pick(server.get("model"))
        critic_model = _pick(server.get("critic_model"), model)
    # Fall through to server URL (server key's trusted endpoint)
    if not base_url:
        base_url = server_url

    critic_key = _pick(o.get("critic_api_key"), u.get("critic_api_key"), api_key)
    critic_url = _pick(o.get("critic_base_url"))
    if critic_url and not (
        _is_safe_base_url(critic_url)
        and (o.get("critic_api_key") or o.get("api_key"))
    ):
        critic_url = ""
    # 用户层 critic_base_url 同样过守卫 + 绑定本层 key（此前漏校验，
    # 会把用户/服务器凭据发往任意未校验地址）。
    user_critic_url = _pick(u.get("critic_base_url"))
    if user_critic_url and not (
        _is_safe_base_url(user_critic_url)
        and (u.get("critic_api_key") or u.get("api_key"))
    ):
        user_critic_url = ""
    critic_base_url = _pick(
        critic_url or "", user_critic_url, server.get("critic_base_url"), base_url
    )

    # source 表示"这通调用花的是谁的账户"——决定要不要计入共享额度，
    # 所以只看 key 来自哪一层，不能被"浏览器凑巧带了模型名"带偏。
    source = key_layer
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model or DEFAULT_LLM_MODEL,
        "provider": _pick(server.get("provider")) or "openai",
        "source": source,
        "critic_api_key": critic_key,
        "critic_base_url": critic_base_url or base_url,
        "critic_model": critic_model or model or DEFAULT_LLM_MODEL,
    }
