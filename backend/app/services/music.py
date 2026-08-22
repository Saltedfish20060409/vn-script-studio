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
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

# Hosts the /music/stream proxy may fetch (audio CDNs + share-link origins).
_STREAM_HOST_SUFFIXES = (
    "music.163.com",
    "music.126.net",
    "qqmusic.qq.com",
    "y.qq.com",
    "kugou.com",
)

# Public API origins the resolvers talk to (kept together for auditability).
_NETEASE_API = "https://music.163.com"
_QQ_API = "https://u.y.qq.com/cgi-bin/musicu.fcg"


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
    return headers


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
    song_id: str, api_url: str, cookie: str, transport: Optional[httpx.AsyncBaseTransport] = None
) -> ResolvedTrack:
    async with _client(transport) as client:
        # --- metadata ---
        if api_url:
            detail = await _json(client, f"{api_url}/song/detail", params={"ids": song_id})
        else:
            detail = await _json(
                client,
                f"{_NETEASE_API}/api/song/detail/",
                params={"id": song_id, "ids": f"[{song_id}]"},
            )
        song = None
        if detail:
            songs = detail.get("songs") or []
            song = songs[0] if songs else None
        title = (song or {}).get("name") or f"网易云歌曲 {song_id}"
        artists = song.get("artists") or song.get("ar") or []
        artist = " / ".join(a.get("name", "") for a in artists if a.get("name")) or "未知歌手"
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
            # Public enhance/player/url (free songs only), then outer-link trick.
            data = await _json(
                client,
                f"{_NETEASE_API}/api/song/enhance/player/url",
                params={"ids": f"[{song_id}]", "br": 3200000},
            )
            items = (data or {}).get("data") or []
            for item in items:
                if item.get("url"):
                    audio_url = item["url"]
                    break
            if not audio_url:
                audio_url = f"{_NETEASE_API}/song/media/outer/url?id={song_id}.mp3"
        if not audio_url:
            raise ResolveError("网易云：这首歌需要会员或已下架，换一首试试")

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
    mid: str, transport: Optional[httpx.AsyncBaseTransport] = None
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
        title = info.get("name") or f"QQ音乐 {mid}"
        singers = info.get("singer") or []
        artist = " / ".join(s.get("name", "") for s in singers if s.get("name")) or "未知歌手"
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
    if parsed.platform == "netease":
        return await _resolve_netease(
            parsed.id, netease_api_url.strip(), netease_cookie.strip(), transport
        )
    if parsed.platform == "qq":
        return await _resolve_qq(parsed.id, transport)
    return await _resolve_kugou(parsed.id, parsed.extra, transport)


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
    if platform == "netease":
        return await _search_netease(q, netease_cookie.strip(), transport)
    if platform == "qq":
        return await _search_qq(q, transport)
    if platform == "kugou":
        return await _search_kugou(q, transport)
    raise ResolveError("未知平台")


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
    async with _client(transport) as client:
        body = {
            "req_0": {
                "module": "music.search.SearchCgiService",
                "method": "DoSearchForQQMusicDesktop",
                "param": {"query": q, "num_per_page": 10, "page_num": 1, "search_type": 0},
            }
        }
        try:
            resp = await client.post(_QQ_API, json=body)
            data = ((resp.json().get("req_0") or {}).get("data") or {}).get("body") or {}
        except (httpx.HTTPError, ValueError):
            return []
        songs = ((data.get("song") or {}).get("list")) or []
        out: list[SearchResult] = []
        for s in songs:
            singers = s.get("singer") or []
            album = s.get("album") or {}
            pmid = album.get("pmid") or album.get("mid") or ""
            out.append(
                SearchResult(
                    # Search returns the song mid under `mid` (songmid is None).
                    id=str(s.get("mid") or s.get("songmid") or s.get("id") or ""),
                    title=s.get("name") or s.get("songname") or "",
                    artist=" / ".join(x.get("name", "") for x in singers if x.get("name")),
                    album=album.get("name") or "",
                    cover=f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{pmid}.jpg"
                    if pmid
                    else None,
                )
            )
        if not out:
            raise ResolveError("QQ音乐没搜到相关歌曲")
        return out


async def _search_kugou(
    q: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> list[SearchResult]:
    async with _client(transport) as client:
        try:
            resp = await client.get(
                "https://songsearch.kugou.com/song_search_v2",
                params={"keyword": q, "page": 1, "pagesize": 10},
                headers={"Referer": "https://www.kugou.com/"},
            )
            body = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return []
        songs = ((body.get("data") or {}).get("lists")) or []
        out: list[SearchResult] = []
        for s in songs:
            out.append(
                SearchResult(
                    id=str(s.get("FileHash") or s.get("hash") or ""),
                    title=s.get("SongName") or s.get("songname") or "",
                    artist=s.get("SingerName") or s.get("singername") or "",
                    album=s.get("AlbumName") or s.get("album_name") or "",
                    cover=s.get("ImgUrl") or s.get("img") or None,
                )
            )
        if not out:
            raise ResolveError("酷狗没搜到相关歌曲")
        return out


def proxy_url_for(real_url: str, api_prefix: str = "/api/v1") -> str:
    """Same-origin proxy URL the browser actually plays (keeps Referer correct)."""
    return f"{api_prefix}/music/stream?url={quote(real_url, safe='')}"
