import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.llm_client_override import _is_safe_base_url
from app.core.llm_http import content_from_response
from app.core.llm_provider import provider_from_config
from app.core.rate_limit import require_rate
from app.db import get_db
from app.llm_models import DEFAULT_LLM_MODEL
from app.models import User
from app.schemas import SettingsOut, SettingsPutIn, TestLlmIn
from app.security import get_current_user
from app.services.projects import resolve_llm_credentials
from app.services.settings import get_or_create_settings, settings_to_out, update_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings_api(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_settings(db, user.id)
    return settings_to_out(row)


@router.put("", response_model=SettingsOut)
async def put_settings_api(
    body: SettingsPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_settings(db, user.id)
    row = await update_settings(db, row, body)
    return settings_to_out(row)


@router.get("/models")
async def model_catalogue(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Curated OpenAI-compatible model presets + the model currently in effect."""
    from app.core.model_presets import list_model_presets

    creds = await resolve_llm_credentials(db, user.id, settings)
    active = None
    if creds.get("api_key"):
        active = {
            "base_url": creds.get("base_url") or "",
            "model": creds.get("model") or "",
            "source": creds.get("source") or "server",
        }
    return {"presets": list_model_presets(), "active": active}


@router.post("/test-llm")
async def test_llm_api(
    body: TestLlmIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Fire a minimal chat request against the given (or saved) credentials.

    Returns 200 with ok=true/false so the UI can render the outcome inline;
    a non-200 only means the request itself was malformed.
    """
    # 与其他 LLM 端点一致：限流（防探测/滥用）
    require_rate(
        user.id,
        "test_llm",
        10,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="测试过于频繁，请稍后再试",
    )

    creds = await resolve_llm_credentials(db, user.id, settings)
    provided_key = (body.api_key or "").strip()
    provided_url = (body.base_url or "").strip()

    # SSRF 守卫：请求体自带的 base_url 必须过 https/公网校验，且必须自带 key。
    # 否则服务器会按解析结果把凭据（含服务器 DEEPSEEK_API_KEY）发往任意地址
    # （credential-exfiltrating SSRF，与 llm_client_override 的层绑定规则一致）。
    if provided_url:
        if not _is_safe_base_url(provided_url):
            raise HTTPException(
                status_code=400,
                detail="base_url 不安全：仅允许可解析的 https 公网地址",
            )
        if not provided_key:
            raise HTTPException(
                status_code=400,
                detail="自定义接口地址必须同时填写该服务自己的 API Key",
            )

    api_key = provided_key or creds.get("api_key") or ""
    if not api_key or "your-key" in api_key:
        raise HTTPException(status_code=400, detail="未配置 API Key：请先输入或保存 Key 再测试")

    base_url = (
        provided_url
        or creds.get("base_url")
        or "https://api.deepseek.com"
    )
    model = (body.model or "").strip() or creds.get("model") or DEFAULT_LLM_MODEL
    cfg = DeepSeekConfig(apiKey=api_key, baseUrl=base_url, model=model)
    provider = provider_from_config(cfg)

    t0 = time.monotonic()
    try:
        res = await provider.chat_completions(
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=8,
            timeout=30,
            max_retries=1,
        )
        _, echo = content_from_response(res)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms, "model": echo or model}
    except Exception as exc:  # noqa: BLE001 - surface upstream error to the user
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "model": model,
            "error": str(exc)[:400],
        }
