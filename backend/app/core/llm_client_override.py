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

    base_url is layer-bound to the api_key:
      - client base_url honored ONLY if client also sent its own api_key
      - user base_url honored ONLY if user DB creds have their own api_key
      - otherwise server base_url (server key → server URL)
    All candidate base_urls pass the https/non-private SSRF guard.
    """
    o = override or {}
    u = user_creds or {}

    server_key = _pick(server.get("api_key"))
    server_url = _pick(server.get("base_url")) or "https://api.deepseek.com"

    client_key = _pick(o.get("api_key"))
    client_url = _pick(o.get("base_url"))
    user_key = _pick(u.get("api_key"))
    user_url = _pick(u.get("base_url"))

    # Pick api_key first (client > user > server)
    api_key = _pick(client_key, user_key, server_key)
    # Layer-bind base_url: only the layer that supplied the key may set the URL
    if api_key == client_key and client_key:
        base_url = _safe_or_blank(client_url)
    elif api_key == user_key and user_key:
        base_url = _safe_or_blank(user_url)
    else:
        base_url = ""
    # Fall through to server URL (server key's trusted endpoint)
    if not base_url:
        base_url = server_url

    model = _pick(o.get("model"), u.get("model"), server.get("model"))

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
    critic_model = _pick(
        o.get("critic_model"), u.get("critic_model"), server.get("critic_model"), model
    )

    if client_key or client_url or o.get("model"):
        source = "client"
    elif user_key:
        source = "user"
    else:
        source = "server"
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
