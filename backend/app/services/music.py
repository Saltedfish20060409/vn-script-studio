"""Music share-link resolution + hotlink-bypass streaming (choice A+B).

Honest constraints (no official APIs for NetEase / QQ Music / Kugou):
- We use public, unofficial endpoints that may break anytime; every call is
  best-effort and time-boxed, and failures surface as clear Chinese messages.
- Option B: a self-hosted NeteaseCloudMusicApi (``NETEASE_API_URL``) plus an
  account cookie gives reliable NetEase playback. Without it we fall back to
  the public outer-link trick, which only plays free songs.
"""

from __future__ import annotations

import base64
import copy
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

# Public API origins the resolvers talk to (kept together for auditability).
_NETEASE_API = "https://music.163.com"
_QQ_API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_BILI_API = "https://api.bilibili.com"

# B 站音频 CDN 域名（DASH 音频流）；需加入 stream 白名单
_BILI_CDN_SUFFIXES = ("bilivideo.com", "akamaized.net")

# Hosts the /music/stream proxy may fetch (audio CDNs + share-link origins).
_STREAM_HOST_SUFFIXES = (
    "music.163.com",
    "music.126.net",
    "qqmusic.qq.com",
    "y.qq.com",
    "kugou.com",
) + _BILI_CDN_SUFFIXES

# Bilibili WBI 签名用的字符置换表（公开算法，非密钥）
_BILI_MIXIN = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
    49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
    40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
    62, 11, 36, 20, 34, 44, 52,
]

# --------------------------------------------------------------------------
# 进程内 TTL 缓存：resolve/search 结果。B站/QQ 返回的播放地址有时效性，
# TTL 必须短（120s）；容量超限直接整体清空（简单优先）。
# transport 注入（测试）时跳过缓存，避免 MockTransport 语义被缓存串扰。
# --------------------------------------------------------------------------
_CACHE_TTL_SECONDS = 120
_CACHE_MAX_ENTRIES = 500
_resolve_cache: dict[str, tuple[float, "ResolvedTrack"]] = {}
_search_cache: dict[str, tuple[float, list["SearchResult"]]] = {}


def _cache_get(cache: dict, key: str):
    hit = cache.get(key)
    if not hit:
        return None
    ts, payload = hit
    if time.time() - ts > _CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return copy.deepcopy(payload)


def _cache_put(cache: dict, key: str, payload) -> None:
    if len(cache) >= _CACHE_MAX_ENTRIES:
        cache.clear()
    cache[key] = (time.time(), copy.deepcopy(payload))


class ResolveError(Exception):
    """User-facing resolution failure (mapped to HTTP 422)."""


@dataclass
class ResolvedTrack:
    id: str
    title: str
    artist: str
    audio_url: str
    cover: Optional[str] = None
    lrc: Optional[str] = None


@dataclass
class ParsedShare:
    platform: str  # "netease" | "qq" | "kugou"
    id: str
    extra: dict = field(default_factory=dict)


def parse_share_url(raw: str) -> Optional[ParsedShare]:
    """Identify platform + song id from a share link.

    Supported forms:
      NetEase: music.163.com .../song?id=123  (incl. #/song?id=123, y.music.163.com)
      QQ:      y.qq.com/n/ryqq/songDetail/<songmid> | ...songmid=XXX
      Kugou:   kugou.com ... hash=HEX (optionally album_id=)
    Returns None when the link is not a recognizable song share link.
    """
    url = (raw or "").strip()
    if not url or len(url) > 2048:
        return None
    lowered = url.lower()

    # NetEase — song page with numeric id.
    if "music.163.com" in lowered and "song" in lowered:
        m = re.search(r"[?&#]id=(\d{4,})", url)
        if m:
            return ParsedShare("netease", m.group(1))

    # QQ Music — songmid (12-char alnum) from songDetail path or query.
    m = re.search(r"y\.qq\.com/n/ryqq/songDetail/([A-Za-z0-9]{8,})", url)
    if not m:
        m = re.search(r"[?&]songmid=([A-Za-z0-9]{8,})", url)
    if m and "qq.com" in lowered:
        return ParsedShare("qq", m.group(1))

    # Kugou — song hash (hex) in query/fragment, optionally album_id.
    if "kugou.com" in lowered:
        m = re.search(r"[?&#]hash=([0-9A-Fa-f]{8,})", url)
        if m:
            extra: dict = {}
            album = re.search(r"[?&#]album_id=(\d+)", url)
            if album:
                extra["album_id"] = album.group(1)
            return ParsedShare("kugou", m.group(1).lower(), extra)

    return None


def allowed_stream_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in _STREAM_HOST_SUFFIXES)


def stream_headers(host: str) -> dict:
    """Referer/UA for a proxy target host (bypasses hotlink protection)."""
    host = (host or "").lower()
    headers = {"User-Agent": _UA}
    if host.endswith("music.163.com") or host.endswith("music.126.net"):
        headers["Referer"] = "https://music.163.com/"
    elif host.endswith("qqmusic.qq.com") or host.endswith("y.qq.com"):
        headers["Referer"] = "https://y.qq.com/"
    elif host.endswith("kugou.com"):
        headers["Referer"] = "https://www.kugou.com/"
    elif host.endswith("bilivideo.com") or host.endswith("akamaized.net"):
        headers["Referer"] = "https://www.bilibili.com/"
    return headers


def normalize_netease_cookie(raw: str) -> str:
    """容忍用户只粘贴 MUSIC_U 的值（不带前缀）。

    - 完整 Cookie 串（含 = 或 ;）→ 原样返回
    - 单个值 → 补成 MUSIC_U=值
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if "=" in value or ";" in value:
        return value
    return f"MUSIC_U={value}"


def _client(transport: Optional[httpx.AsyncBaseTransport] = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        transport=transport,
        headers={"User-Agent": _UA},
    )


async def _json(client: httpx.AsyncClient, url: str, **kw) -> Optional[dict]:
    try:
        resp = await client.get(url, **kw)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


async def _resolve_netease(
    song_id: str,
    api_url: str,
    cookie: str,
    fallback_title: Optional[str] = None,
    fallback_artist: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ResolvedTrack:
    cookie = normalize_netease_cookie(cookie)
    async with _client(transport) as client:
        # --- metadata ---
        headers = {"Referer": "https://music.163.com/"}
        if cookie:
            headers["Cookie"] = cookie
        if api_url:
            detail = await _json(client, f"{api_url}/song/detail", params={"ids": song_id})
        else:
            detail = await _json(
                client,
                f"{_NETEASE_API}/api/song/detail/",
                params={"id": song_id, "ids": f"[{song_id}]"},
                headers=headers,
            )
        song = None
        if detail:
            songs = detail.get("songs") or []
            song = songs[0] if songs else None
        song = song or {}
        # 数据中心 IP 上 detail 常返回空：用搜索结果回传的信息兜底
        title = song.get("name") or fallback_title or f"网易云歌曲 {song_id}"
        artists = song.get("artists") or song.get("ar") or []
        artist = (
            " / ".join(a.get("name", "") for a in artists if a.get("name"))
            or fallback_artist
            or "未知歌手"
        )
        album = song.get("album") or song.get("al") or {}
        cover = album.get("picUrl") or album.get("pic") or None

        # --- playable URL ---
        audio_url = ""
        if api_url:
            data = await _json(
                client,
                f"{api_url}/song/url/v1",
                params={"id": song_id, "level": "standard", "cookie": cookie},
            )
            if data:
                for item in data.get("data") or []:
                    if item.get("url"):
                        audio_url = item["url"]
                        break
        else:
            # Public enhance/player/url. From datacenter IPs it returns
            # url:null for everything unless the request carries a logged-in
            # cookie (server-side NETEASE_API_URL or per-request X-Netease-Cookie).
            headers = {"Referer": "https://music.163.com/"}
            if cookie:
                headers["Cookie"] = cookie
            data = await _json(
                client,
                f"{_NETEASE_API}/api/song/enhance/player/url",
                params={"ids": f"[{song_id}]", "br": 3200000},
                headers=headers,
            )
            items = (data or {}).get("data") or []
            for item in items:
                if item.get("url"):
                    audio_url = item["url"]
                    break
        if not audio_url:
            # No playable URL: be honest about the blocker instead of falling
            # back to a link that will 403/HTML from a datacenter IP.
            raise ResolveError(
                "网易云：需要登录才能播放这首歌（数据中心 IP 上免费直链不可用）。"
                "请在播放器面板填写网易云 Cookie，或让管理员配置 NETEASE_API_URL。"
            )

        # --- lyrics (best effort) ---
        lrc: Optional[str] = None
        if api_url:
            ly = await _json(client, f"{api_url}/lyric", params={"id": song_id, "cookie": cookie})
            if ly:
                lrc = (ly.get("lrc") or {}).get("lyric") or None
        else:
            ly = await _json(
                client,
                f"{_NETEASE_API}/api/song/lyric",
                params={"id": song_id, "lv": -1, "kv": -1, "tv": -1},
            )
            if ly:
                lrc = (ly.get("lrc") or {}).get("lyric") or None

    return ResolvedTrack(
        id=f"netease-{song_id}",
        title=title,
        artist=artist,
        audio_url=audio_url,
        cover=cover,
        lrc=lrc,
    )


async def _resolve_qq(
    mid: str,
    fallback_title: Optional[str] = None,
    fallback_artist: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ResolvedTrack:
    async with _client(transport) as client:
        def payload(module: str, method: str, param: dict) -> dict:
            return {"req_0": {"module": module, "method": method, "param": param}}

        # --- metadata ---
        detail_body = payload(
            "music.pf_song_detail_svr",
            "get_song_detail_yqq",
            {"song_mid_list": [mid]},
        )
        try:
            resp = await client.post(_QQ_API, json=detail_body)
            info = {}
            if resp.status_code == 200:
                data = (resp.json().get("req_0") or {}).get("data") or {}
                info = data.get("track_info") or {}
        except (httpx.HTTPError, ValueError):
            info = {}
        title = info.get("name") or fallback_title or f"QQ音乐 {mid}"
        singers = info.get("singer") or []
        artist = (
            " / ".join(s.get("name", "") for s in singers if s.get("name"))
            or fallback_artist
            or "未知歌手"
        )
        pmid = (info.get("album") or {}).get("pmid") or ""
        cover = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{pmid}.jpg" if pmid else None

        # --- playable URL (vkey endpoint; free songs usually work) ---
        import random

        guid = str(random.randrange(10**10, 10**11))
        vkey_body = payload(
            "vkey.GetVkeyServer",
            "CgiGetVkey",
            {
                "guid": guid,
                "songmid": [mid],
                "songtype": [0],
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
            },
        )
        audio_url = ""
        try:
            resp = await client.post(_QQ_API, json=vkey_body)
            if resp.status_code == 200:
                data = (resp.json().get("req_0") or {}).get("data") or {}
                sip = (data.get("sip") or [""])[0]
                infos = data.get("midurlinfo") or []
                purl = (infos[0] or {}).get("purl") or "" if infos else ""
                if purl:
                    audio_url = sip + purl if sip else purl
        except (httpx.HTTPError, ValueError):
            audio_url = ""
        if not audio_url:
            raise ResolveError("QQ音乐：这首歌需要会员或版权受限，暂时无法获取播放地址")

        # --- lyrics (base64 LRC, best effort) ---
        lrc: Optional[str] = None
        try:
            resp = await client.post(
                _QQ_API,
                json=payload(
                    "music.musichallSong.PlayLyricInfo",
                    "GetPlayLyricInfo",
                    {"songMID": mid},
                ),
            )
            if resp.status_code == 200:
                raw = ((resp.json().get("req_0") or {}).get("data") or {}).get("lyric") or ""
                if raw:
                    try:
                        decoded = base64.b64decode(raw).decode("utf-8", "replace")
                        if decoded.strip():
                            lrc = decoded
                    except Exception:  # noqa: BLE001
                        lrc = None
        except (httpx.HTTPError, ValueError):
            lrc = None

    return ResolvedTrack(
        id=f"qq-{mid}",
        title=title,
        artist=artist,
        audio_url=audio_url,
        cover=cover,
        lrc=lrc,
    )


async def _resolve_kugou(
    song_hash: str,
    extra: dict,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ResolvedTrack:
    async with _client(transport) as client:
        # Desktop play/getdata now demands SSA tokens (err 30020); the mobile
        # getSongInfo endpoint still serves a direct playable url.
        try:
            resp = await client.get(
                "https://m.kugou.com/app/i/getSongInfo.php",
                params={"cmd": "playInfo", "hash": song_hash},
                headers={"Referer": "https://m.kugou.com/"},
            )
            data = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            data = {}
        play_url = data.get("url") or data.get("backup_url") or ""
        if not play_url:
            raise ResolveError("酷狗：这首歌需要会员或已下架，暂时无法获取播放地址")
        title = data.get("songName") or data.get("fileName") or f"酷狗 {song_hash}"
        artist = data.get("author_name") or data.get("singerName") or "未知歌手"
        cover = data.get("imgUrl") or data.get("album_img") or None
        lrc = data.get("lyrics") or None
        if lrc and not lrc.strip():
            lrc = None

    return ResolvedTrack(
        id=f"kugou-{song_hash}",
        title=title,
        artist=artist,
        audio_url=play_url,
        cover=cover,
        lrc=lrc,
    )


@dataclass
class SearchResult:
    """One search hit — enough to display + resolve by platform/id."""

    id: str  # platform-native id (netease numeric / qq songmid / kugou hash)
    title: str
    artist: str
    album: str = ""
    cover: Optional[str] = None


async def resolve_music_track(
    raw_url: str,
    *,
    platform: str = "",
    song_id: str = "",
    fallback_title: Optional[str] = None,
    fallback_artist: Optional[str] = None,
    netease_api_url: str = "",
    netease_cookie: str = "",
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ResolvedTrack:
    """Resolve a share link — or a direct (platform, song_id) pair — to a
    playable track (audio_url is the real CDN URL).

    Raises ResolveError with a user-facing Chinese message when unparseable or
    unplayable. ``transport`` is test-only injection.
    """
    if platform and song_id:
        parsed = ParsedShare(platform=platform, id=song_id)
    else:
        parsed = parse_share_url(raw_url)
        if parsed is None:
            raise ResolveError("无法识别的链接：请粘贴网易云 / QQ音乐 / 酷狗的歌曲分享链接")
    cache_key = f"{parsed.platform}:{parsed.id}"
    if transport is None:
        cached = _cache_get(_resolve_cache, cache_key)
        if cached is not None:
            return cached
    if parsed.platform == "netease":
        track = await _resolve_netease(
            parsed.id,
            netease_api_url.strip(),
            netease_cookie.strip(),
            fallback_title,
            fallback_artist,
            transport,
        )
    elif parsed.platform == "qq":
        track = await _resolve_qq(parsed.id, fallback_title, fallback_artist, transport)
    elif parsed.platform == "bili":
        track = await _resolve_bili(parsed.id, transport)
    else:
        track = await _resolve_kugou(parsed.id, parsed.extra, transport)
    if transport is None:
        _cache_put(_resolve_cache, cache_key, track)
    return track


async def search_tracks(
    query: str,
    platform: str,
    *,
    netease_cookie: str = "",
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> list[SearchResult]:
    """Search songs on one platform via its public web endpoint.

    Returns up to ~10 hits with native ids ready for resolve_music_track.
    Raises ResolveError for unknown platforms or empty results.
    """
    q = (query or "").strip()
    if not q:
        raise ResolveError("请输入要搜索的歌名或歌手")
    cache_key = f"{platform}:{q}"
    if transport is None:
        cached = _cache_get(_search_cache, cache_key)
        if cached is not None:
            return cached
    if platform == "netease":
        hits = await _search_netease(q, netease_cookie.strip(), transport)
    elif platform == "qq":
        hits = await _search_qq(q, transport)
    elif platform == "kugou":
        hits = await _search_kugou(q, transport)
    elif platform == "bili":
        hits = await _search_bili(q, transport)
    else:
        raise ResolveError("未知平台")
    if transport is None:
        _cache_put(_search_cache, cache_key, hits)
    return hits


async def _search_netease(
    q: str,
    cookie: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> list[SearchResult]:
    async with _client(transport) as client:
        headers = {"Referer": "https://music.163.com/"}
        if cookie:
            headers["Cookie"] = cookie
        try:
            # cloudsearch/pc: the plain /api/search/pc now returns code -462
            # (verification wall) for anonymous clients; cloudsearch stays open.
            resp = await client.get(
                f"{_NETEASE_API}/api/cloudsearch/pc",
                params={"s": q, "type": 1, "limit": 10, "offset": 0, "total": "true"},
                headers=headers,
            )
            body = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return []
        songs = ((body.get("result") or {}).get("songs")) or []
        out: list[SearchResult] = []
        for s in songs:
            artists = s.get("artists") or s.get("ar") or []
            album = s.get("album") or s.get("al") or {}
            out.append(
                SearchResult(
                    id=str(s.get("id") or ""),
                    title=s.get("name") or "",
                    artist=" / ".join(a.get("name", "") for a in artists if a.get("name")),
                    album=album.get("name") or "",
                    cover=album.get("picUrl") or album.get("pic") or None,
                )
            )
        if not out:
            raise ResolveError("网易云没搜到相关歌曲")
        return out


async def _search_qq(
    q: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> list[SearchResult]:
    # client_search_cp（老接口）：musicu.fcg 的 SearchCgiService 在数据中心
    # IP（如腾讯云）会被风控返回空列表；client_search_cp 实测仍可用。
    async with _client(transport) as client:
        try:
            resp = await client.get(
                "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                params={"p": 1, "n": 10, "w": q, "format": "json", "cr": 1, "g_tk": 5381},
                headers={"Referer": "https://y.qq.com/"},
            )
            body = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return []
        songs = ((body.get("data") or {}).get("song") or {}).get("list") or []
        out: list[SearchResult] = []
        for s in songs:
            singers = s.get("singer") or []
            album_mid = s.get("albummid") or s.get("album_mid") or ""
            out.append(
                SearchResult(
                    id=str(s.get("songmid") or s.get("mid") or ""),
                    title=s.get("songname") or s.get("name") or "",
                    artist=" / ".join(x.get("name", "") for x in singers if x.get("name")),
                    album=s.get("albumname") or "",
                    cover=f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_mid}.jpg"
                    if album_mid
                    else None,
                )
            )
        if not out:
            raise ResolveError("QQ音乐没搜到相关歌曲")
        return out


def _bili_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in _BILI_MIXIN)[:32]


def _bili_sign(params: dict, img_key: str, sub_key: str) -> dict:
    """B 站 WBI 签名（公开算法）：加 wts 时间戳 → 排序 → md5 拼接签名。"""
    import hashlib
    from urllib.parse import urlencode

    signed = dict(params)
    signed["wts"] = int(time.time())
    ordered = dict(sorted(signed.items()))
    mixin = _bili_mixin_key(img_key + sub_key)
    signed["wtsign"] = hashlib.md5((urlencode(ordered) + mixin).encode()).hexdigest()
    return signed


async def _bili_wbi_keys(
    client: httpx.AsyncClient,
) -> tuple[str, str]:
    """从 /nav 拿 wbi_img 的 img_key/sub_key（失败返回空串，搜索仍可试）。"""
    try:
        resp = await client.get(
            f"{_BILI_API}/x/web-interface/nav",
            headers={"Referer": "https://www.bilibili.com/"},
        )
        wbi = ((resp.json().get("data") or {}).get("wbi_img")) or {}
        img_key = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
        sub_key = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
        return img_key, sub_key
    except (httpx.HTTPError, ValueError):
        return "", ""


async def _search_bili(
    q: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> list[SearchResult]:
    """B 站搜索含歌名的视频（后台听视频）：WBI 签名后查视频，返回 bvid。"""
    async with _client(transport) as client:
        img_key, sub_key = await _bili_wbi_keys(client)
        params = _bili_sign(
            {"search_type": "video", "keyword": q, "page": 1},
            img_key,
            sub_key,
        )
        try:
            resp = await client.get(
                f"{_BILI_API}/x/web-interface/wbi/search/type",
                params=params,
                headers={"Referer": "https://www.bilibili.com/"},
            )
            body = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return []
        if body.get("code") != 0:
            return []
        vlist = ((body.get("data") or {}).get("result")) or []
        import re as _re

        tag = _re.compile(r"</?em[^>]*>")
        out: list[SearchResult] = []
        for v in vlist[:10]:
            bvid = str(v.get("bvid") or "")
            title = tag.sub("", str(v.get("title") or ""))
            if not bvid or not title:
                continue
            out.append(
                SearchResult(
                    id=bvid,
                    title=title,
                    artist=str(v.get("author") or "B站UP主"),
                    album="",
                    cover=(v.get("pic") or "").startswith("http")
                    and v.get("pic")
                    or None,
                )
            )
        if not out:
            raise ResolveError("B站没搜到相关视频")
        return out


async def _resolve_bili(
    bvid: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ResolvedTrack:
    """B 站后台听视频：bvid → cid → DASH 音频流（只取音频轨，不播画面）。"""
    async with _client(transport) as client:
        headers = {"Referer": "https://www.bilibili.com/"}
        try:
            resp = await client.get(
                f"{_BILI_API}/x/web-interface/view",
                params={"bvid": bvid},
                headers=headers,
            )
            view = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            view = {}
        data = view.get("data") or {}
        cid = data.get("cid")
        title = data.get("title") or f"B站视频 {bvid}"
        cover = (data.get("pic") or "").startswith("http") and data.get("pic") or None
        if not cid:
            raise ResolveError("B站：该视频不存在或已删除")
        try:
            resp = await client.get(
                f"{_BILI_API}/x/player/playurl",
                params={"bvid": bvid, "cid": cid, "fnval": 16, "fnver": 0, "fourk": 0},
                headers=headers,
            )
            play = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            play = {}
        audio = ((play.get("data") or {}).get("dash") or {}).get("audio") or []
        # 选最高码率（bandwidth 最大）的音频轨
        audio_url = ""
        for item in sorted(audio, key=lambda a: a.get("bandwidth") or 0, reverse=True):
            base = item.get("baseUrl") or item.get("base_url") or ""
            if base:
                audio_url = base
                break
        if not audio_url:
            raise ResolveError("B站：该视频未提供可听的音频流")

    return ResolvedTrack(
        id=f"bili-{bvid}",
        title=title,
        artist="B站",
        audio_url=audio_url,
        cover=cover,
        lrc=None,
    )


# 版本/翻唱标记：搜索结果里这类条目排后面（优先原版）
_VERSION_MARKS = (
    "DJ", "dj", "Live", "live", "现场", "伴奏", "伴奏版", "翻唱", "翻唱版",
    "remix", "Remix", "remake", "女声版", "男声版", "合唱", "钢琴版", "吉他版",
    "片段", "纯音乐", "热歌", "慢摇", "说唱", "完整版",
)


def _title_version_penalty(title: str) -> int:
    """版本标记数：0 = 原版；越大越靠后。"""
    return sum(1 for m in _VERSION_MARKS if m in title)


async def _search_kugou(
    q: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> list[SearchResult]:
    # 酷狗 song_search_v2 对含空格的多词查询（"歌手 歌名"）直接返回空，
    # 且单关键词结果混入 DJ/Live/翻唱。策略：拆词分别搜 → 合并去重 →
    # 按「版本标记少 + 标题/歌手匹配度高」重排，优先原版原唱。
    async with _client(transport) as client:
        words = [w for w in q.split() if w.strip()]
        queries = [q] if q in words else [q]
        if len(words) > 1:
            queries = [q] + words  # 完整串 + 每个词单独搜

        merged: dict[str, SearchResult] = {}
        for query in queries:
            try:
                resp = await client.get(
                    "https://songsearch.kugou.com/song_search_v2",
                    params={"keyword": query, "page": 1, "pagesize": 20},
                    headers={"Referer": "https://www.kugou.com/"},
                )
                body = resp.json() if resp.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                continue
            songs = ((body.get("data") or {}).get("lists")) or []
            for s in songs:
                song_hash = str(s.get("FileHash") or s.get("hash") or "")
                title = s.get("SongName") or s.get("songname") or ""
                artist = s.get("SingerName") or s.get("singername") or ""
                if not song_hash or not title:
                    continue
                merged.setdefault(
                    song_hash,
                    SearchResult(
                        id=song_hash,
                        title=title,
                        artist=artist,
                        album=s.get("AlbumName") or s.get("album_name") or "",
                        cover=s.get("ImgUrl") or s.get("img") or None,
                    ),
                )

        def rank(item: SearchResult) -> tuple:
            title_pen = _title_version_penalty(item.title)
            # 歌手名包含查询词 → 匹配加分（负分排前）
            artist_match = -2 if any(w in item.artist for w in words if len(w) >= 2) else 0
            title_exact = -1 if any(w == item.title for w in words) else 0
            return (title_pen + artist_match + title_exact, item.title)

        out = sorted(merged.values(), key=rank)[:10]
        if not out:
            raise ResolveError("酷狗没搜到相关歌曲")
        return out


def proxy_url_for(real_url: str, api_prefix: str = "/api/v1") -> str:
    """Same-origin proxy URL the browser actually plays (keeps Referer correct)."""
    return f"{api_prefix}/music/stream?url={quote(real_url, safe='')}"
