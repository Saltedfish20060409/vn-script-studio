"""测试 usage 批量写入（队列 + flush）。"""
from __future__ import annotations

import asyncio

from app.core import usage as usage_mod


def test_queue_and_flush_batch():
    """record_usage_later 入队，_flush_queue 批量写入并清空。"""
    usage_mod._usage_queue.clear()

    # 用假 DB session 替换，验证批量 INSERT 调用
    class _FakeRow:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    inserted = []

    class _FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            inserted.extend(self.added)

    import app.db as db_mod

    original = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = lambda: _FakeSession()
    try:
        for i in range(3):
            usage_mod.record_usage_later(
                user_id=f"u{i}",
                kind="llm",
                usage={"prompt": 10, "completion": 5, "total": 15},
            )
        written = asyncio.run(usage_mod._flush_queue())
        assert written == 3
        assert len(inserted) == 3
        assert inserted[0].total_tokens == 15
        assert usage_mod._usage_queue == []
    finally:
        db_mod.AsyncSessionLocal = original
        usage_mod._usage_queue.clear()


def test_queue_rejects_zero_total():
    """total<=0 不入队。"""
    usage_mod._usage_queue.clear()
    usage_mod.record_usage_later(
        user_id="u", usage={"prompt": 0, "completion": 0, "total": 0}
    )
    assert usage_mod._usage_queue == []
