"""文风记忆自动学习：保存时按需触发（模型与"作者自己的 Key"都被 mock）。

为什么要集成测一次：这条是"默认开"的承诺——挂在保存路径上、且只在作者**自己有 Key** 时才跑
（站内免费档是共享额度，不该代作者花）。纯函数测试只能证明"该不该学"，
这里证明"真的学到了、真的写进工程了、没自己 Key 时不学"。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import db_gate
import pytest

from app.core.style_memory import StyleMemoryResult

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()
LEARN_TARGET = "app.core.style_memory.learn_style_memory"
CREDS_TARGET = "app.services.settings.user_llm_credentials"

LONG_PROSE = "雨落在站台上。他把手举到眼前，那双手不是他的。" * 40


def _run(coro):
    return asyncio.run(coro)


async def _project_with_long_prose(client, headers) -> str:
    r = await client.post("/api/v1/projects", json={"from_demo": True}, headers=headers)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
    project = r.json()
    # 凑够 4 章、每章都够长（触发门槛：≥3 章且 ≥3000 字）
    project["chapters"] = [
        {"id": f"c{i}", "title": f"第{i}章", "prose": LONG_PROSE, "blocks": []}
        for i in range(1, 5)
    ]
    r = await client.put(
        f"/api/v1/projects/{pid}",
        json={"data": project, "force": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return pid


def test_auto_learn_runs_on_save_and_stores_memory():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "style_auto")
            pid = await _project_with_long_prose(client, headers)

            calls = {"n": 0}

            async def fake_learn(config, project):
                calls["n"] += 1
                return StyleMemoryResult(guide="你习惯短句，少用形容词。", samples=["雨落在站台上。"])

            async def fake_creds(db, user_id, settings):
                return {"api_key": "own-key", "base_url": "", "model": "own-model"}

            with patch(LEARN_TARGET, new=fake_learn), patch(CREDS_TARGET, new=fake_creds):
                # 再存一次：这次内容已经够多 → 应触发自动学习
                r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
                project = r.json()
                r = await client.put(
                    f"/api/v1/projects/{pid}",
                    json={"data": project, "force": True},
                    headers=headers,
                )
                assert r.status_code == 200, r.text

            assert calls["n"] >= 1, "内容够了却没自动学习"
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            memory = r.json().get("styleMemory") or {}
            assert memory.get("guide") == "你习惯短句，少用形容词。"
            assert memory.get("samples") == ["雨落在站台上。"]
            # 记下章节数：下一次靠"又写了若干章"触发，避免每章都跑模型
            assert memory.get("learnedChapterCount") == 4
            assert memory.get("auto") is True

    _run(_scenario())


def test_auto_learn_is_skipped_without_the_authors_own_key():
    """没有自己的 Key 时不自动学：不能替作者花站内共享额度。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "style_auto_nokey")
            pid = await _project_with_long_prose(client, headers)

            calls = {"n": 0}

            async def fake_learn(config, project):  # pragma: no cover - 不该被调用
                calls["n"] += 1
                return StyleMemoryResult(guide="不该发生")

            async def no_creds(db, user_id, settings):
                return {}

            with patch(LEARN_TARGET, new=fake_learn), patch(CREDS_TARGET, new=no_creds):
                r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
                project = r.json()
                r = await client.put(
                    f"/api/v1/projects/{pid}",
                    json={"data": project, "force": True},
                    headers=headers,
                )
                assert r.status_code == 200, r.text

            assert calls["n"] == 0
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert not (r.json().get("styleMemory") or {}).get("guide")

    _run(_scenario())
