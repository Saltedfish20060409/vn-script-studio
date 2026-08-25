"""Music endpoints: search + resolve + hotlink-safe proxy.

POST /api/v1/music/search — search songs on NetEase / QQ / Kugou via their
    public web endpoints (no login needed). Returns light hits for display.
POST /api/v1/music/resolve — resolve a share link OR a (platform, songId)
    search hit to a playable MusicTrack. Optional browser-held NetEase cookie
    (X-Netease-Cookie header) upgrades playback quality for VIP songs; it is
    used per-request and never stored.
GET /api/v1/music/stream?url=... — range-aware streaming proxy restricted to a
    whitelist of music CDN hosts (never an open proxy). Rate-limited per IP.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.core.llm_client_override import _BLOCKED_IPS
from app.core.rate_limit import require_rate
from app.security import get_current_user
from app.services import music as music_svc
from app.services.music import ResolveError

router = APIRouter(prefix="/music", tags=["music"])

_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

_PLATFORMS = {"netease", "qq", "kugou", "bili"}


class SearchIn(BaseModel):
    q: str = Field(min_length=1, max_length=128)
    platform: str = Field(pattern="^(netease|qq|kugou|bili)$")


class SearchItemOut(BaseModel):
    id: str
    title: str
    artist: str
    album: str = ""
    cover: str | None = None


class ResolveIn(BaseModel):
    url: str = Field(default="", max_length=2048)
    platform: str = Field(default="", pattern="^(netease|qq|kugou|bili|)$")
    songId: str = Field(default="", max_length=128)
    # 搜索结果点添加时回传的展示信息：数据中心 IP 上元数据接口可能不可用
    title: str = Field(default="", max_length=200)
    artist: str = Field(default="", max_length=200)


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


def _net_cookie(request: Request, settings: Settings) -> str:
    """Per-request browser cookie wins over the server-configured one."""
    return request.headers.get("x-netease-cookie") or settings.netease_cookie


async def _assert_public_host(url: str) -> None:
    """Reject URLs whose hostname resolves to a private/loopback/metadata IP.

    DNS 解析结果逐一过私网/回环/链路本地/保留段检查（与 llm_client_override
    的 _BLOCKED_IPS 一致），任一命中即拒绝——防止 /music/stream 被当跳板打内网。
    """
    try:
        host = (urlsplit(url).hostname or "").strip().lower()
    except ValueError:
        host = ""
    if not host:
        raise HTTPException(status_code=400, detail="无效的音源地址")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError:
        raise HTTPException(status_code=400, detail="音源域名无法解析")
    if not infos:
        raise HTTPException(status_code=400, detail="音源域名无法解析")
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if addr.version == 6 and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        ):
            raise HTTPException(status_code=400, detail="音源地址指向内网/保留地址")
        for net in _BLOCKED_IPS:
            if addr in ipaddress.ip_network(net):
                raise HTTPException(status_code=400, detail="音源地址指向内网/保留地址")


@router.post("/search", response_model=list[SearchItemOut])
async def search_songs(
    body: SearchIn,
    request: Request,
    settings: Settings = Depends(get_settings),
    _user=Depends(get_current_user),
):
    require_rate(
        request.client.host if request.client else None,
        "music_search",
        limit=30,
        enabled=settings.rate_limit_enabled,
        detail="搜索过于频繁，请稍后再试",
    )
    try:
        hits = await music_svc.search_tracks(
            body.q,
            body.platform,
            netease_cookie=_net_cookie(request, settings),
        )
    except ResolveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [SearchItemOut(**h.__dict__) for h in hits]


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
        limit=60,
        enabled=settings.rate_limit_enabled,
        detail="解析过于频繁，请稍后再试",
    )
    if not body.url and not (body.platform and body.songId):
        raise HTTPException(status_code=422, detail="请提供分享链接或搜索结果")
    if body.platform and body.platform not in _PLATFORMS:
        raise HTTPException(status_code=422, detail="未知平台")
    try:
        track = await music_svc.resolve_music_track(
            body.url,
            platform=body.platform,
            song_id=body.songId,
            fallback_title=body.title.strip() or None,
            fallback_artist=body.artist.strip() or None,
            netease_api_url=settings.netease_api_url,
            netease_cookie=_net_cookie(request, settings),
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
    # 初始 URL 先过 IP 级校验（仅主机名后缀白名单不够：白名单域名可被 DNS
    # 指向内网；也不允许先跟随重定向再校验——跳转目标一律逐跳重查）。
    await _assert_public_host(url)

    headers = music_svc.stream_headers(parts.hostname)
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=_STREAM_TIMEOUT, follow_redirects=False)
    try:
        current_url = url
        current_headers = dict(headers)
        upstream = None
        for _hop in range(4):  # 初始请求 + 最多 3 次跳转
            request_obj = client.build_request("GET", current_url, headers=current_headers)
            resp = await client.send(request_obj, stream=True)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                await resp.aclose()
                if not location:
                    raise HTTPException(status_code=502, detail="音源返回无效跳转")
                current_url = urljoin(current_url, location)
                hop = urlsplit(current_url)
                if hop.scheme not in ("http", "https") or not hop.hostname:
                    raise HTTPException(status_code=400, detail="跳转目标不是 http(s) 地址")
                if not music_svc.allowed_stream_host(hop.hostname):
                    raise HTTPException(status_code=400, detail="音源跳转到了白名单之外的地址")
                await _assert_public_host(current_url)
                current_headers = dict(headers)
                current_headers.update(music_svc.stream_headers(hop.hostname))
                if range_header:
                    current_headers["Range"] = range_header
                continue
            upstream = resp
            break
        if upstream is None:
            raise HTTPException(status_code=502, detail="音源跳转次数过多")
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"音源暂不可达（{type(exc).__name__}）") from exc
    except HTTPException:
        # 白名单/SSRF 校验失败：释放连接后原样抛出。
        await client.aclose()
        raise

    if upstream.status_code >= 400:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"音源返回 {upstream.status_code}")

    # Defense in depth: the final response host must also be inside the whitelist.
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
