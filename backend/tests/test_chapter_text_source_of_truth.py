"""读"一章的正文"只走一个口径：`agent_context.chapter_plain`。

## 为什么单开一份守卫（2026-10-01 线上事故）

作者报的是：「我开了新对话、把之前不满意的原文删掉了，让它生成文字时用的**还是那段旧文**。」

根因是同一章有**两份存储**（正文档 `prose` / 脚本档 `blocks`），而读写两侧的口径不齐：

- 写：编辑器的正文档只写 `prose`、脚本档只写 `blocks`；Agent 的 `append_script` 只写 `blocks`。
- 读：`chapter_plain` 是 **prose 优先、prose 为空回落 blocks**——这个回落本身必要
  （纯脚本档工程的 `prose` 一直是空的），但它让"作者删掉的那一面"从另一面复活。

于是"文本存在 blocks、作者在正文档里删掉它"这条路上，模型读到的仍是那份旧文。
前端已经把"清空 = 两面都清"补上了（`frontend/src/lib/chapterSurfaces.ts`），
后端这边要做的是**把所有"读一章正文"的地方统一到唯一口径**——散着 15 处各读 blocks，
迟早会再冒出同一个现象（记忆存档、账本、文风记忆、事实扫描、分享页都会）。

本文件钉两层：

1. **行为**：正文优先——prose 与 blocks 同时有内容时，各处读到的必须是 prose；
2. **结构**：源代码里不许再出现"拿一手 chapter.blocks 当正文"的读法（只允许块级渲染的少数模块）。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.agent_context import chapter_plain
from app.core.consistency_audit import _chapter_texts as audit_chapter_texts
from app.core.fact_extract import chapter_fingerprint
from app.core.novel_memory import number_chapters
from app.core.project import normalize_project
from app.core.style_memory import _chapter_texts as style_chapter_texts

APP = Path(__file__).resolve().parent.parent / "app"

PROSE = "正文档里最新的一稿：她在沙发上坐直了。\n\n雪菜：「名字和代号，有什么不同？」"
STALE_BLOCKS = [{"type": "narration", "text": "脚本档里那份已经删掉的旧稿：雨还在下。"}]

#: 允许直接吃 `blocks` 的模块：它们做的是**块级渲染/转换**（导出、预览、结构化转换），
#: 不是"读这一章的正文"；而且各自都已在调用点先判过 prose（或只拿到 blocks 列表）。
BLOCK_LEVEL_ALLOWED = {
    "agent_context.py",  # chapter_plain 自身的回落实现 + 分支块渲染
    "consistency_scan.py",  # 自己实现了同一回落（prose 优先）
    "novel_consistency.py",  # 同上
    "export_submission.py",  # 投稿稿：章节级已先判 prose，这里只是"没有正文时"的渲染
    "novel_memory.py",  # 自己的 blocks→plain 渲染器（不含"读章正文"的语义）
}

CHAPTER_BLOCKS_READ = re.compile(r"_blocks_to_plain\(\s*(?:ch|c|chapter)\.blocks")


def _project(*, prose: str | None) -> object:
    return normalize_project(
        {
            "id": "p-truth",
            "title": "正文口径",
            "characters": [{"id": "c1", "displayName": "雪菜", "defineName": "yukina"}],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "prose": prose or "",
                    "blocks": list(STALE_BLOCKS),
                }
            ],
        }
    )


# ---- 1. 行为：prose 优先 ---------------------------------------------------


def test_chapter_plain_prefers_prose_over_stale_blocks():
    project = _project(prose=PROSE)
    assert chapter_plain(project.chapters[0], project.characters).startswith("正文档里最新的一稿")
    # 用户当前那一面是 prose，脚本档里那份旧稿不该再出现
    assert "已经删掉的旧稿" not in chapter_plain(project.chapters[0], project.characters)


def test_readers_that_feed_the_model_see_the_prose():
    """审计 / 文风记忆 / 记忆存档 / 分享预览：都必须是 prose，而不是脚本档的旧稿。"""
    project = _project(prose=PROSE)

    audit = audit_chapter_texts(project)
    assert audit and "正文档里最新的一稿" in audit[0]["text"]
    assert "已经删掉的旧稿" not in audit[0]["text"]

    style = style_chapter_texts(project)
    assert style and "正文档里最新的一稿" in style[0]["text"]

    numbered = number_chapters(project)
    assert "正文档里最新的一稿" in numbered[0].plain_text


def test_fingerprint_follows_the_prose():
    """指纹决定"这一章变了没有"：只看 blocks 的话，正文档里的改写永远不算变化。"""
    a = chapter_fingerprint(_project(prose=PROSE), "ch1")
    b = chapter_fingerprint(_project(prose="改过的另一稿。"), "ch1")
    assert a and b and a != b


def test_writer_and_preview_use_the_prose():
    """写作通道的"当前章末尾"与公开分享页的试读，都取自作者当下那一面。"""
    import asyncio

    from app.api.v1.shares import _build_preview
    from app.core.ai import DeepSeekConfig
    from app.core.pipeline import orchestrator as orch

    project = _project(prose=PROSE)
    preview = _build_preview(project)
    assert preview["chapterPreviews"], preview
    assert "正文档里最新的一稿" in preview["chapterPreviews"][0]["text"]
    assert "已经删掉的旧稿" not in preview["chapterPreviews"][0]["text"]
    # 字数也按 prose 算（否则分享页对正文档作品显示 0 字）
    assert preview["stats"]["words"] > 0

    captured: dict = {}

    async def fake_llm(cfg, *, role, user_prompt, project=None, temperature=0.0):
        captured["prompt"] = user_prompt
        return {"content": "（她偏头。）", "model": "test"}

    original = orch.run_harness_llm
    orch.run_harness_llm = fake_llm
    try:
        asyncio.run(
            orch.stage_write(
                DeepSeekConfig(apiKey="k", baseUrl="http://x", model="m"),
                project,
                instruction="接着写",
                chapter_id="ch1",
            )
        )
    finally:
        orch.run_harness_llm = original

    prompt = captured.get("prompt") or ""
    assert "正文档里最新的一稿" in prompt, "writer 拿到的不是作者当下那一面"
    assert "已经删掉的旧稿" not in prompt, "writer 还在拿脚本档里那份旧稿续写"


# ---- 2. 结构：不许再有"拿 chapter.blocks 当正文"的读法 ----------------------


def test_no_new_blocks_only_chapter_readers():
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name in BLOCK_LEVEL_ALLOWED:
            continue
        src = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]
            if CHAPTER_BLOCKS_READ.search(code):
                offenders.append(f"{path.relative_to(APP)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "这些地方又把 `ch.blocks` 当成「这一章的正文」读了——正文与脚本是两套存储，"
        "必须走 `chapter_plain`（正文优先、空才回落）：\n  " + "\n  ".join(offenders)
    )


def test_key_modules_actually_use_the_shared_reader():
    """正面断言：上面那几个"喂模型 / 喂记忆 / 喂审阅"的模块都引了唯一口径。"""
    for rel in (
        "core/pipeline/orchestrator.py",
        "core/chapter_revise.py",
        "core/consistency_audit.py",
        "core/fact_extract.py",
        "core/fact_llm.py",
        "core/style_memory.py",
        "core/pipeline/ledger.py",
        "core/pipeline/ledger_enrich.py",
        "core/pipeline/gate.py",
        "api/v1/shares.py",
        "api/v1/projects.py",
    ):
        src = (APP / rel).read_text(encoding="utf-8")
        assert "chapter_plain" in src, f"{rel} 没有走共享的读正文口径"
