"""公开站点元信息：ICP 备案号 / 公安备案号（网站底部展示）。

数字来自服务端环境变量 ICP_BEIAN_NUMBER / GONGAN_BEIAN_NUMBER（备案通过后填写），
未配置时返回空串，前端不渲染页脚。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["meta"])


@router.get("/meta")
async def site_meta(settings: Settings = Depends(get_settings)):
    return {
        "icpBeian": (settings.icp_beian_number or "").strip(),
        "gonganBeian": (settings.gongan_beian_number or "").strip(),
    }
