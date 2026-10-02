"""ADR 0001 P2：写路径上下文拼装（无 DB）。"""

from __future__ import annotations

from app.core import normalize_project
from app.core.write_context import (
    assemble_write_context,
    format_bible_brief,
    format_chat_history,
)


def _demo_project(**kwargs):
    base = {
        "id": "p1",
        "title": "测试",
        "bible": {
            "world": "雨夜都市有一条只对失忆者开放的轨",
            "background": "主角失忆后在车站醒来",
            "outline": "第一卷：找回名字",
            "themes": "不要说明书旁白",
            "notes": "",
        },
        "chapters": [],
        "characters": [],
    }
    base.update(kwargs)
    return normalize_project(base)


def test_format_chat_history_includes_roles():
    block = format_chat_history(
        [
            {"role": "user", "content": "请续写，更压抑一点"},
            {"role": "assistant", "content": "草稿：雨还在下。"},
            {"role": "user", "content": "接着写车站那一段"},
        ]
    )
    assert "最近对话" in block
    assert "更压抑" in block
    assert "车站" in block


def test_format_bible_brief_keeps_five_fields():
    project = _demo_project()
    brief = format_bible_brief(project)
    assert "世界观" in brief
    assert "失忆者" in brief
    assert "大纲" in brief


def test_assemble_includes_history_bible_style():
    project = _demo_project()
    ctx = assemble_write_context(
        project,
        messages=[{"role": "user", "content": "续写并保持设定：只对失忆者开放"}],
        chat_memory="作者已确认基调压抑",
        long_memory="第1章：主角在车站醒来",
        global_memory="全书：寻找名字",
        include_lenses=True,
        include_style_skill=True,
        include_bible=True,
    )
    assert "chat_history" in ctx.included
    assert "bible" in ctx.included
    assert "style_skill" in ctx.included
    assert "long_memory" in ctx.included
    assert "global_memory" in ctx.included
    assert "失忆者" in ctx.bible_block or "失忆者" in ctx.system_extra
    assert "压抑" in ctx.chat_block
    assert "写作风格 Skill" in ctx.style_block or "style_skill" in ctx.included
    # system_extra 应带 bible（与 style）；对话在 user 侧 chat_block
    assert ctx.system_extra
    assert ctx.chat_block


def test_assemble_lens_when_project_has_active(monkeypatch):
    project = _demo_project(
        authorLenses={"activeIds": ["author-murakami"], "custom": []}
    )

    def fake_lens(project, *, override_ids=None, intent="review", total_budget=5200):
        return "## 作家透镜\n村上：疏离与节奏"

    monkeypatch.setattr(
        "app.core.lenses.build_lens_prompt_for_project", fake_lens
    )
    ctx = assemble_write_context(project, messages=[{"role": "user", "content": "写"}])
    assert "lens" in ctx.included
    assert "村上" in ctx.lens_block
    assert "村上" in ctx.system_extra


def test_stage_write_prompt_paths_include_enrichment(monkeypatch):
    """不调真实 LLM：截获 stream_chat_completions 的 messages，断言 enrichment。"""
    import asyncio

    from app.core.ai import DeepSeekConfig
    from app.core.pipeline import orchestrator as orch

    captured: dict = {}

    async def fake_stream(cfg, *, messages, **kwargs):
        captured["messages"] = messages
        yield "一段正文"

    monkeypatch.setattr(
        "app.core.llm_http.stream_chat_completions", fake_stream
    )

    project = _demo_project()
    tokens: list[str] = []

    async def _run():
        return await orch.stage_write(
            DeepSeekConfig(apiKey="sk-test", model="test"),
            project,
            instruction="续写车站",
            messages=[
                {"role": "user", "content": "记住：轨只对失忆者开放"},
                {"role": "assistant", "content": "好的。"},
            ],
            chat_memory="基调压抑",
            long_memory="章记忆：醒来",
            global_memory="全书骨架",
            on_token=tokens.append,
            enrich_context=True,
        )

    result = asyncio.run(_run())
    assert result["content"] == "一段正文"
    assert "bible" in result["contextIncluded"]
    assert "chat_history" in result["contextIncluded"]
    assert "style_skill" in result["contextIncluded"]
    assert "long_memory" in result["contextIncluded"]
    assert "global_memory" in result["contextIncluded"]
    system = captured["messages"][0]["content"]
    user = captured["messages"][1]["content"]
    assert "失忆者" in system or "失忆者" in user
    assert "最近对话" in user or "失忆者开放" in user
    assert "基调压抑" in user  # chat_memory
    assert "章记忆：醒来" in user or "醒来" in user  # long_memory
    assert "全书骨架" in user  # global_memory
    assert "写作风格 Skill" in system or "style_skill" in result["contextIncluded"]


def test_clip_keeps_head_and_marks_truncation():
    from app.core.write_context import _clip

    text = "关键事实：" + ("啊" * 200)
    out = _clip(text, 40)
    assert out.startswith("关键事实：")
    assert "截断" in out


def test_style_transfer_contract_mentions_preserve_plot():
    from app.core.pipeline.style_transfer_contract import style_transfer_prompt_block

    block = style_transfer_prompt_block(user_style_note="更冷、更短句")
    assert "风格迁移" in block
    assert "情节事实" in block
    assert "更冷" in block