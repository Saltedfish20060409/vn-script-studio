"""Tests: music share-link parsing + resolve + stream proxy guardrails.

Pure parsing tests never touch the network. Resolve tests use httpx
MockTransport so the exact public-endpoint contract is exercised offline.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import music as svc
from app.services.music import ResolveError, parse_share_url

# ---------------------------------------------------------------- parsing ---

@pytest.mark.parametrize(
    "url,platform,expected",
    [
        ("https://music.163.com/#/song?id=1856244885", "netease", "1856244885"),
        ("https://music.163.com/song?id=1856244885", "netease", "1856244885"),
        ("https://y.music.163.com/m/song?id=1856244885", "netease", "1856244885"),
        (
            "https://music.163.com/#/song?id=1856244885&userid=123",
            "netease",
            "1856244885",
        ),
        (
            "https://y.qq.com/n/ryqq/songDetail/003a4Y8G0mQX6s",
            "qq",
            "003a4Y8G0mQX6s",
        ),
        (
            "https://y.qq.com/n/ryqq/songDetail/003a4Y8G0mQX6s?ADTAG=newwy",
            "qq",
            "003a4Y8G0mQX6s",
        ),
        (
            "https://i.y.qq.com/v8/playsong.html?songmid=003a4Y8G0mQX6s",
            "qq",
            "003a4Y8G0mQX6s",
        ),
        (
            "https://www.kugou.com/song/#hash=B7A1F2C3D4E5F6A7B8C9D0E1F2A3B4C5&album_id=123",
            "kugou",
            "b7a1f2c3d4e5f6a7b8c9d0e1f2a3b4c5",
        ),
        (
            "https://m.kugou.com/share/index.html?hash=B7A1F2C3D4E5F6A7B8C9D0E1F2A3B4C5&album_id=123",
            "kugou",
            "b7a1f2c3d4e5f6a7b8c9d0e1f2a3b4c5",
        ),
        ("https://music.163.com/#/playlist?id=123456", None, None),
    ],
)
def test_parse_share_url_recognizes(url, platform, expected):
    parsed = parse_share_url(url)
    if platform is None:
        assert parsed is None
        return
    assert parsed is not None
    assert parsed.platform == platform
    assert parsed.id == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://example.com/song?id=123",
        "not a url at all",
        "https://music.163.com/#/album?id=12345",
        "https://y.qq.com/n/ryqq/albumDetail/ABC123",
        "https://www.kugou.com/",
    ],
)
def test_parse_share_url_rejects(url):
    assert parse_share_url(url) is None


def test_kugou_album_id_captured():
    parsed = parse_share_url(
        "https://m.kugou.com/share/index.html?hash=B7A1F2C3D4E5F6A7B8C9D0E1F2A3B4C5&album_id=456"
    )
    assert parsed is not None
    assert parsed.extra.get("album_id") == "456"


# ------------------------------------------------------------ host allowlist ---

@pytest.mark.parametrize(
    "host,allowed",
    [
        ("music.163.com", True),
        ("m701.music.126.net", True),
        ("m7.music.126.net", True),
        ("isure.stream.qqmusic.qq.com", True),
        ("ws.stream.qqmusic.qq.com", True),
        ("y.qq.com", True),
        ("wwwapi.kugou.com", True),
        ("trackercdn.kugou.com", True),
        ("kugou.com", True),
        ("example.com", False),
        ("music.163.com.evil.com", False),
        ("evil163.com", False),
        ("", False),
        ("localhost", False),
        ("127.0.0.1", False),
    ],
)
def test_allowed_stream_host(host, allowed):
    assert svc.allowed_stream_host(host) is allowed


def test_stream_headers_referer():
    assert "music.163.com" in svc.stream_headers("m701.music.126.net")["Referer"]
    assert "y.qq.com" in svc.stream_headers("isure.stream.qqmusic.qq.com")["Referer"]
    assert "www.kugou.com" in svc.stream_headers("trackercdn.kugou.com")["Referer"]
    assert "User-Agent" in svc.stream_headers("y.qq.com")


# --------------------------------------------------------------- resolve -----

def _transport(handler) -> httpx.AsyncBaseTransport:
    return httpx.MockTransport(handler)


def test_resolve_netease_with_api_url():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/song/detail"):
            return httpx.Response(
                200,
                json={
                    "songs": [
                        {
                            "name": "测试歌曲",
                            "artists": [{"name": "歌手A"}, {"name": "歌手B"}],
                            "album": {"name": "专辑X", "picUrl": "https://p1.music.126.net/cov.jpg"},
                        }
                    ]
                },
            )
        if path.endswith("/song/url/v1"):
            return httpx.Response(
                200, json={"data": [{"url": "https://m701.music.126.net/abc.mp3", "br": 128000}]}
            )
        if path.endswith("/lyric"):
            return httpx.Response(200, json={"lrc": {"lyric": "[00:01.00]第一句\n[00:05.00]第二句"}})
        return httpx.Response(404)

    track = None
    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://music.163.com/#/song?id=1856244885",
            netease_api_url="https://api.example",
            netease_cookie="MUSIC_U=abc",
            transport=_transport(handler),
        )

    track = asyncio.run(run())
    assert track.id == "netease-1856244885"
    assert track.title == "测试歌曲"
    assert track.artist == "歌手A / 歌手B"
    assert track.audio_url == "https://m701.music.126.net/abc.mp3"
    assert track.cover == "https://p1.music.126.net/cov.jpg"
    assert "[00:01.00]" in (track.lrc or "")


def test_resolve_netease_no_api_url_falls_back_to_outer():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/song/detail/"):
            return httpx.Response(
                200,
                json={"songs": [{"name": "免费曲", "artists": [{"name": "某歌手"}], "album": {}}]},
            )
        if path.endswith("/api/song/enhance/player/url"):
            return httpx.Response(200, json={"data": [{"url": None}]})
        if path.endswith("/api/song/lyric"):
            return httpx.Response(200, json={"lrc": {"lyric": ""}})
        return httpx.Response(404)

    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://music.163.com/song?id=1856244885", transport=_transport(handler)
        )

    track = asyncio.run(run())
    assert track.audio_url == "https://music.163.com/song/media/outer/url?id=1856244885.mp3"
    assert track.lrc is None


def test_resolve_netease_unplayable_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/song/detail"):
            return httpx.Response(
                200,
                json={"songs": [{"name": "VIP曲", "artists": [], "album": {}}]},
            )
        if path.endswith("/song/url/v1"):
            return httpx.Response(200, json={"data": [{"url": None}]})
        return httpx.Response(404)

    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://music.163.com/song?id=999999",
            netease_api_url="https://api.example",
            netease_cookie="",
            transport=_transport(handler),
        )

    with pytest.raises(ResolveError):
        asyncio.run(run())


def test_resolve_qq():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8", "replace")
        if "get_song_detail_yqq" in body:
            return httpx.Response(
                200,
                json={
                    "req_0": {
                        "data": {
                            "track_info": {
                                "name": "QQ曲",
                                "singer": [{"name": "QQ歌手"}],
                                "album": {"pmid": "003RMaRI4iK2Tj"},
                            }
                        }
                    }
                },
            )
        if "CgiGetVkey" in body:
            return httpx.Response(
                200,
                json={
                    "req_0": {
                        "data": {
                            "sip": ["https://ws.stream.qqmusic.qq.com/"],
                            "midurlinfo": [{"purl": "C400003a4Y8G0mQX6s.m4a?x=1"}],
                        }
                    }
                },
            )
        if "PlayLyricInfo" in body:
            return httpx.Response(
                200,
                json={
                    "req_0": {
                        "data": {"lyric": "WzAwOjAwLjAwXea3u+WKnuiAgeivuuOAgg=="}
                    }
                },
            )
        return httpx.Response(404)

    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://y.qq.com/n/ryqq/songDetail/003a4Y8G0mQX6s",
            transport=_transport(handler),
        )

    track = asyncio.run(run())
    assert track.id == "qq-003a4Y8G0mQX6s"
    assert track.title == "QQ曲"
    assert track.artist == "QQ歌手"
    assert track.audio_url.startswith("https://ws.stream.qqmusic.qq.com/")
    assert "00:00" in (track.lrc or "")


def test_resolve_qq_vip_unplayable_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8", "replace")
        if "get_song_detail_yqq" in body:
            return httpx.Response(
                200,
                json={"req_0": {"data": {"track_info": {"name": "VIP", "singer": [], "album": {}}}}},
            )
        if "CgiGetVkey" in body:
            return httpx.Response(
                200,
                json={
                    "req_0": {
                        "data": {"sip": ["https://ws.stream.qqmusic.qq.com/"], "midurlinfo": [{"purl": ""}]}
                    }
                },
            )
        return httpx.Response(404)

    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://y.qq.com/n/ryqq/songDetail/003a4Y8G0mQX6s",
            transport=_transport(handler),
        )

    with pytest.raises(ResolveError):
        asyncio.run(run())


def test_resolve_kugou():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/yy/index.php")
        assert request.url.params.get("r") == "play/getdata"
        return httpx.Response(
            200,
            json={
                "data": {
                    "song_name": "酷狗曲",
                    "author_name": "酷狗歌手",
                    "play_url": "https://trackercdn.kugou.com/song.mp3",
                    "img": "https://imge.kugou.com/cov.jpg",
                    "lyrics": "[00:10.00]酷狗第一句\n",
                }
            },
        )

    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://www.kugou.com/song/#hash=B7A1F2C3D4E5F6A7B8C9D0E1F2A3B4C5&album_id=123",
            transport=_transport(handler),
        )

    track = asyncio.run(run())
    assert track.id == "kugou-b7a1f2c3d4e5f6a7b8c9d0e1f2a3b4c5"
    assert track.title == "酷狗曲"
    assert track.artist == "酷狗歌手"
    assert track.audio_url == "https://trackercdn.kugou.com/song.mp3"
    assert "[00:10.00]" in (track.lrc or "")


def test_resolve_unknown_link_raises():
    import asyncio

    async def run():
        return await svc.resolve_music_track(
            "https://example.com/whatever", transport=_transport(lambda r: httpx.Response(404))
        )

    with pytest.raises(ResolveError):
        asyncio.run(run())


def test_proxy_url_for():
    url = svc.proxy_url_for("https://m701.music.126.net/a b.mp3?x=1&y=2")
    assert url.startswith("/api/v1/music/stream?url=")
    assert "a%20b" in url
    assert "music.126.net" in url
