"""API tests: /music resolve + stream endpoints (auth, whitelist, wiring)."""

from __future__ import annotations

import asyncio

import db_gate
import pytest

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()


def _run(coro):
    return asyncio.run(coro)


def test_resolve_requires_auth():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.post(
                "/api/v1/music/resolve",
                json={"url": "https://music.163.com/#/song?id=1856244885"},
            )
            assert r.status_code in (401, 403)

    _run(_scenario())


def test_resolve_unknown_link_422():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "music_user")
            r = await client.post(
                "/api/v1/music/resolve",
                json={"url": "https://example.com/not-a-song"},
                headers=headers,
            )
            assert r.status_code == 422, r.text
            assert "无法识别" in r.json()["detail"]

    _run(_scenario())


def test_resolve_requires_url_or_song():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "music_user2")
            r = await client.post(
                "/api/v1/music/resolve", json={}, headers=headers
            )
            assert r.status_code == 422, r.text

    _run(_scenario())


def test_search_requires_auth():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.post(
                "/api/v1/music/search",
                json={"q": "夜曲", "platform": "netease"},
            )
            assert r.status_code in (401, 403)

    _run(_scenario())


def test_search_bad_platform_422():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "music_user3")
            r = await client.post(
                "/api/v1/music/search",
                json={"q": "x", "platform": "spotify"},
                headers=headers,
            )
            assert r.status_code == 422, r.text

    _run(_scenario())


def test_stream_rejects_non_whitelisted_host():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.get(
                "/api/v1/music/stream",
                params={"url": "https://evil.example.com/song.mp3"},
            )
            assert r.status_code == 400, r.text
            r2 = await client.get(
                "/api/v1/music/stream",
                params={"url": "file:///etc/passwd"},
            )
            assert r2.status_code == 400, r2.text

    _run(_scenario())


def test_stream_proxies_whitelisted_audio():
    """A whitelisted host is proxied; upstream headers flow through."""

    async def _scenario():
        # Override httpx client inside the endpoint with a MockTransport.
        from unittest.mock import patch

        import httpx

        class FakeResp:
            status_code = 200
            url = httpx.URL("https://m701.music.126.net/song.mp3")

            def __init__(self):
                self.headers = httpx.Headers(
                    {"content-type": "audio/mpeg", "content-length": "42"}
                )

            async def aiter_raw(self):
                yield b"\xff\xfb"
                yield b"\x00\x01"

            async def aclose(self):
                return None

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            def build_request(self, method, url, headers=None):
                return ("GET", url, headers)

            async def send(self, request, stream=False):
                return FakeResp()

            async def aclose(self):
                return None

        with patch(
            "app.api.v1.music.httpx.AsyncClient", side_effect=lambda *a, **k: FakeClient()
        ):
            async with db_gate.make_client(APP) as client:
                r = await client.get(
                    "/api/v1/music/stream",
                    params={"url": "https://m701.music.126.net/song.mp3"},
                )
                assert r.status_code == 200, r.text
                assert r.headers["content-type"] == "audio/mpeg"
                assert r.content == b"\xff\xfb\x00\x01"

    _run(_scenario())
