"""Regression: vnss.access logger must work independently of uvicorn's config.

uvicorn runs its dictConfig (disable_existing_loggers=True by default) AFTER
importing app.main, so any logger created at import time gets silently
disabled — our access-log middleware was a no-op in production (zero lines
over 40 min). The fix wires an explicit StreamHandler onto vnss.access so it
never depends on root/uvicorn configuration.
"""

from __future__ import annotations

import io
import logging

from app.main import _access_logger, create_app


def test_access_logger_has_own_handler_and_is_info():
    lg = _access_logger()
    assert lg.level <= logging.INFO
    assert lg.handlers, "vnss.access must own a handler (uvicorn disables import-time loggers)"
    assert lg.propagate is False


def test_access_middleware_logs_to_stream(capsys):
    """请求打进去后 vnss.access 必须真的产出 JSON 行（不依赖 root 配置）。"""
    # 把 vnss.access 的 handler 换成可捕获的流，模拟"root 被禁用"的最坏情况
    stream = io.StringIO()
    lg = _access_logger()
    old_handlers = list(lg.handlers)
    for h in old_handlers:
        lg.removeHandler(h)
    lg.addHandler(logging.StreamHandler(stream))
    try:
        import asyncio

        import db_gate

        app = create_app()
        async def _probe():
            async with db_gate.make_client(app) as client:
                r = await client.get("/health")
                assert r.status_code == 200, r.text
        asyncio.run(_probe())
    finally:
        for h in list(lg.handlers):
            lg.removeHandler(h)
        for h in old_handlers:
            lg.addHandler(h)

    lines = [ln for ln in stream.getvalue().splitlines() if ln.strip()]
    assert lines, "access log middleware produced no output"
    import json

    record = json.loads(lines[-1][lines[-1].index("{") :])
    assert record["method"] == "GET"
    assert record["path"] == "/health"
    assert record["status"] == 200
    assert "ms" in record
