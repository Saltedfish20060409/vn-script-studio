"""AI 代翻端到端：假模型 → 批选 → 解析 → 合并 → 落库。

这里不连真模型（不花钱、结果可预期），验证的是"接口把模型输出正确地变成译文草稿"，
包括：只翻未翻的句子、状态标记 ai、人工译文不被覆盖、术语表进入提示词。
"""

from __future__ import annotations

import asyncio
import json

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


class _FakeResp:
    def __init__(self, content: str) -> None:
        self._content = content

    def json(self):  # noqa: ANN201
        return {"choices": [{"message": {"content": self._content}}]}


def _project_blocks():
    return [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "dialogue", "characterId": "c", "text": "你来了。"},
        {"type": "narration", "text": "雨还在下。"},
        {"type": "dialogue", "characterId": "c", "text": "路上小心。"},
    ]


def test_ai_translate_creates_reviewable_drafts():
    async def _scenario():
        from unittest.mock import AsyncMock, patch

        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "l10n_ai1")
            r = await client.post(
                "/api/v1/projects", json={"title": "翻译测试"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            # 写入三段正文（走真实保存路径）
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": {
                        **r.json(),
                        "chapters": [
                            {"id": "ch1", "title": "第一章", "blocks": _project_blocks()}
                        ],
                    }
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text

            # 先人工翻一句：AI 不应覆盖它
            r = await client.get(f"/api/v1/projects/{pid}/localization", headers=headers)
            assert r.status_code == 200, r.text
            entries = r.json()["entries"]
            assert len(entries) == 3
            first_key = entries[0]["key"]
            r = await client.put(
                f"/api/v1/projects/{pid}/localization",
                json={
                    "locales": [{"code": "en", "name": "English"}],
                    "glossary": [{"term": "你", "targets": {"en": "you"}}],
                    "entries": [
                        {
                            "key": first_key,
                            "sourceHash": entries[0]["sourceHash"],
                            "targets": {"en": "人工译文"},
                        }
                    ],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text

            seen_prompts: list[str] = []

            async def fake_chat(config, messages=None, **kwargs):  # noqa: ANN001, ANN003
                seen_prompts.append(messages[-1]["content"])
                # 只回一条：验证"模型少给几条"也不会出错
                payload = {
                    "译文": [
                        {"key": entries[1]["key"], "text": "The rain kept falling."},
                    ]
                }
                return _FakeResp(json.dumps(payload, ensure_ascii=False))

            with patch(
                "app.core.llm_http.chat_completions", side_effect=fake_chat
            ), patch(
                "app.api.v1.projects.resolve_llm_credentials",
                new_callable=AsyncMock,
                return_value={
                    "api_key": "sk-test",
                    "base_url": "https://example.com/v1",
                    "model": "test-model",
                },
            ):
                r = await client.post(
                    f"/api/v1/projects/{pid}/localization/translate",
                    json={"locale": "en", "locale_name": "English"},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["applied"] == 1
            assert body["remaining"] == 1  # 第三句还没翻
            assert "待校对" in body["message"]

            # 术语表必须进提示词
            assert "你 → you" in seen_prompts[0]

            # 落库结果：人工那句没被覆盖，AI 那句标记为 ai
            r = await client.get(f"/api/v1/projects/{pid}/localization", headers=headers)
            entries2 = {e["key"]: e for e in r.json()["entries"]}
            assert entries2[first_key]["targets"]["en"] == "人工译文"
            assert entries2[first_key]["status"] == {}
            ai_entry = entries2[entries[1]["key"]]
            assert ai_entry["targets"]["en"] == "The rain kept falling."
            assert ai_entry["status"]["en"] == "ai"
            # 源文本始终来自当前剧本
            assert ai_entry["source"] == "雨还在下。"

            # 提示词里只包含未翻的两句（不含已有人工译文的那句）
            assert "你来了。" not in seen_prompts[0]
            assert "路上小心。" in seen_prompts[0]

    _run(_scenario())


def test_ai_translate_reports_no_work_left():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "l10n_ai2")
            r = await client.post(
                "/api/v1/projects", json={"title": "空翻译"}, headers=headers
            )
            pid = r.json()["id"]
            r = await client.post(
                f"/api/v1/projects/{pid}/localization/translate",
                json={"locale": "en"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["applied"] == 0
            assert r.json()["remaining"] == 0

    _run(_scenario())
