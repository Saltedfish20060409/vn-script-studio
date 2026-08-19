"""Request-scoped LLM credentials supplied by the browser.

The frontend stores the user's API key / base URL / model locally and attaches
them as X-LLM-* headers on API calls. Resolution order is:

    request headers  >  per-user DB creds  >  server env
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Mapping, Optional

from app.llm_models import DEFAULT_LLM_MODEL

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


def merge_llm_credentials(
    *,
    override: Optional[dict[str, str]],
    user_creds: Optional[dict[str, str]],
    server: dict[str, str],
) -> dict[str, str]:
    """Merge client / user / server layers. Missing fields fall through."""
    o = override or {}
    u = user_creds or {}
    api_key = _pick(o.get("api_key"), u.get("api_key"), server.get("api_key"))
    base_url = _pick(o.get("base_url"), u.get("base_url"), server.get("base_url"))
    model = _pick(o.get("model"), u.get("model"), server.get("model"))
    critic_api_key = _pick(
        o.get("critic_api_key"),
        u.get("critic_api_key"),
        server.get("critic_api_key"),
        api_key,
    )
    critic_base_url = _pick(
        o.get("critic_base_url"),
        u.get("critic_base_url"),
        server.get("critic_base_url"),
        base_url,
    )
    critic_model = _pick(
        o.get("critic_model"),
        u.get("critic_model"),
        server.get("critic_model"),
        model,
    )
    if o.get("api_key") or o.get("base_url") or o.get("model"):
        source = "client"
    elif u.get("api_key"):
        source = "user"
    else:
        source = "server"
    return {
        "api_key": api_key,
        "base_url": base_url or "https://api.deepseek.com",
        "model": model or DEFAULT_LLM_MODEL,
        "provider": _pick(server.get("provider")) or "openai",
        "source": source,
        "critic_api_key": critic_api_key,
        "critic_base_url": critic_base_url or base_url or "https://api.deepseek.com",
        "critic_model": critic_model or model or DEFAULT_LLM_MODEL,
    }
