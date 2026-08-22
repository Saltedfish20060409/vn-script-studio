"""Music endpoints: resolve share links to playable tracks + hotlink-safe proxy.

POST /api/v1/music/resolve — parse a NetEase / QQ / Kugou share link and return
    a MusicTrack (id/title/artist/audioUrl/cover/lrc). The audioUrl always
    points at our own /music/stream proxy so the browser never hits the vendor
    CDN directly (Referer/UA set server-side, bypassing hotlink protection).

GET /api/v1/music/stream?url=... — range-aware streaming proxy restricted to a
    whitelist of music CDN hosts (never an open proxy). Rate-limited per IP.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.core.rate_limit import require_rate
from app.security import get_current_user
from app.services import music as music_svc
from app.services.music import ResolveError

router = APIRouter(prefix="/music", tags=["music"])

_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


class ResolveIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class MusicTrackOut(BaseModel):
    id: str
    title: str
    artist: str
    audioUrl: str
    cover: str | None = None
    lrc: str | None = None


def _to_out(t: music_svc.ResolvedTrack) -> MusicTrackOut:
    return MusicTrackOut(
        id=t.id,
        title=t.title,
        artist=t.artist,
        audioUrl=music_svc.proxy_url_for(t.audio_url),
        cover=t.cover,
        lrc=t.lrc,
    )


@router.post("/resolve", response_model=MusicTrackOut)
async def resolve_link(
    body: ResolveIn,
    request: Request,
    settings: Settings = Depends(get_settings),
    _user=Depends(get_current_user),
):
    require_rate(
        request.client.host if request.client else None,
        "music_resolve",
        limit=30,
        enabled=settings.rate_limit_enabled,
        detail="解析过于频繁，请稍后再试",
    )
    try:
        track = await music_svc.resolve_music_track(
            body.url,
            netease_api_url=settings.netease_api_url,
            netease_cookie=settings.netease_cookie,
        )
    except ResolveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(track)


@router.get("/stream")
async def stream_audio(
    url: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Proxy an audio URL with vendor-correct Referer/UA.

    Only http(s) URLs on the music CDN whitelist are proxied (never an open
    proxy). The browser's Range header is forwarded so seeking works.
    """
    require_rate(
        request.client.host if request.client else None,
        "music_stream",
        limit=120,
        enabled=settings.rate_limit_enabled,
        detail="播放请求过于频繁，请稍后再试",
    )
    if len(url) > 4096:
        raise HTTPException(status_code=400, detail="音源地址过长")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=400, detail="仅支持 http(s) 音源地址")
    if not music_svc.allowed_stream_host(parts.hostname):
        raise HTTPException(status_code=400, detail="该音源域名不在白名单内")

    headers = music_svc.stream_headers(parts.hostname)
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]

    client = httpx.AsyncClient(timeout=_STREAM_TIMEOUT, follow_redirects=True)
    try:
        request_obj = client.build_request("GET", url, headers=headers)
        upstream = await client.send(request_obj, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"音源暂不可达（{type(exc).__name__}）") from exc

    if upstream.status_code >= 400:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"音源返回 {upstream.status_code}")

    # Redirects must stay inside the whitelist too.
    final_host = upstream.url.host
    if not music_svc.allowed_stream_host(final_host):
        await client.aclose()
        raise HTTPException(status_code=400, detail="音源跳转到了白名单之外的地址")

    from fastapi.responses import StreamingResponse

    async def _gen():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp_headers = {}
    for key in (
        "content-type",
        "content-length",
        "accept-ranges",
        "content-range",
        "content-disposition",
    ):
        value = upstream.headers.get(key)
        if value:
            resp_headers[key] = value
    return StreamingResponse(
        _gen(),
        status_code=upstream.status_code,
        headers=resp_headers,
    )
