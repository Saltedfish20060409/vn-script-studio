"""写作通道默认**开思考**：与网页版对齐的那一层。

背景（2026-09-30 与网页版的正面对比）：同一份材料（第一章改写稿 + 设计稿），
网页版是**深度思考开着**写出来的——首轮思考 11.6k 字（先核对人设、找矛盾、排方向），
然后 3052 字成稿；而我们这边 `llm_models.resolve_chat_model` 给默认档下发的是
``thinking: disabled``，等于关着思考用同一个底座。"Agent 不如网页版"里有相当一部分
就是这个差，而不是模型能力差。

写作通道是自由文本、不需要 JSON，所以思考档在这里没有互斥问题
（`model_presets`：``*-think`` 的 ``json_mode`` 是 False，聊天那条路用不了它）。
本文件钉住两件事：

1. `resolve_write_model` 的边界：只换**我们自己**的档位；别的厂商/自建端点原样不动；
   ``write_thinking=off`` 时完全按作者选的走（可回退）。
2. 端到端：`POST /agent/write` 真的把思考档交给了写作条件（不是只在单元里算了一下）。
"""

from __future__ import annotations

import asyncio
import json

import db_gate
import pytest

from app.llm_models import resolve_chat_model, resolve_write_model

# ---- 1. 换档边界（纯单元，不需要数据库） ------------------------------------


def test_our_own_tiers_get_their_thinking_sibling():
    assert resolve_write_model("deepseek-flash") == "deepseek-flash-think"
    assert resolve_write_model("deepseek-v4-flash") == "deepseek-v4-flash-think"
    assert resolve_write_model("deepseek-v4-pro") == "deepseek-v4-pro-think"


def test_already_thinking_or_unknown_models_are_left_alone():
    # 已经是思考档：没有兄弟，原样返回
    assert resolve_write_model("deepseek-flash-think") == "deepseek-flash-think"
    # 别的厂商 / 自建端点：**不许替作者换模型**（我们也不知道那一档支不支持思考）
    for m in ("glm-5.3", "doubao-seed-2-1-turbo-260628", "qwen3.7-max", "my-local-llama"):
        assert resolve_write_model(m) == m
    # 空值回落到默认档，且默认档有兄弟
    assert resolve_write_model(None) == "deepseek-flash-think"


def test_off_mode_keeps_the_authors_choice():
    """`write_thinking=off` 是回退开关：关掉就完全按作者选的档位走。"""
    assert resolve_write_model("deepseek-flash", "off") == "deepseek-flash"
    assert resolve_write_model("deepseek-v4-pro", "off") == "deepseek-v4-pro"


# ---- 2. 端到端：端点真把思考档交出去了 ---------------------------------------

APP = db_gate.make_app()


async def _create_project(client, headers, title="思考档测试"):
    resp = await client.post(
        "/api/v1/projects", json={"title": title, "from_demo": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.db
@pytest.mark.skipif(
    not db_gate.DB_AVAILABLE,
    reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
)
def test_write_endpoint_sends_the_thinking_tier(monkeypatch):
    from app.core.pipeline import orchestrator as orch

    captured: dict = {}

    async def fake_stage_write(cfg, project, **kwargs):
        captured["model"] = cfg.model
        on_token = kwargs.get("on_token")
        if on_token is not None:
            on_token("（她偏过头。）\n")
        return {"stage": "write", "content": "（她偏过头。）", "model": cfg.model}

    monkeypatch.setattr(orch, "stage_write", fake_stage_write)
    # 必须用 db_gate 注入的测试设置：新用户无 Key 时走 server 凭据，
    # 裸 get_settings() 读进程默认会误期望 v4-flash-think，而 Depends 里是 deepseek-chat。
    settings = db_gate.test_settings()
    expected = resolve_write_model(settings.deepseek_model, settings.write_thinking)

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "write_think")
            pid = await _create_project(client, headers)
            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/write",
                json={"instruction": "帮我续写一段"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            events = [
                json.loads(line[len("data: ") :])
                for line in resp.text.splitlines()
                if line.startswith("data: ")
            ]
            done = events[-1]
            assert done["type"] == "done", events
            # 交到写作条件手里的是**思考档**（按上游口径判定，别只看名字后缀：
            # 兼容别名 deepseek-chat 的思考兄弟叫 deepseek-reasoner）
            assert captured["model"] == expected
            _, thinking = resolve_chat_model(captured["model"])
            assert thinking == "enabled", captured["model"]
            # 界面显示的那个模型名也要是同一个（作者要能看出"这次是思考档写的"）
            assert done["model"] == expected

    asyncio.run(_scenario())
