"""Mock-LLM end-to-end pipeline: plan → write → check → apply."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

from app.core.ai import DeepSeekConfig
from app.core.pipeline.apply_draft import plain_text_to_script_blocks
from app.core.pipeline.orchestrator import run_pipeline
from app.domain.types import Character, SceneChapter, StoryBible, VnProject


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(
        apiKey="sk-test",
        baseUrl="https://api.example.com",
        model="test-model",
    )


def test_pipeline_resume_skips_done_stages():
    """断点续跑：resume 里已完成的阶段必须被跳过，状态从检查点恢复。"""
    proj = _project()
    resume = {
        "done": ["plan", "write", "check"],
        "result": {
            "stages": ["plan", "write", "check"],
            "plan": {"beatSheet": BEAT, "summary": "雨夜"},
            "draft": "草稿正文",
            "check": {
                "stage": "check",
                "pass": False,
                "errorCount": 1,
                "warnCount": 0,
                "infoCount": 0,
                "issues": [
                    {"severity": "error", "code": "mock", "message": "测试错误"}
                ],
                "notes": [],
                "gateReady": True,
            },
            "finalDraft": "草稿正文",
            "gate": {"pass": False, "errors": 1, "warnings": 0},
            "applied": False,
            "project": None,
            "reviseRounds": 0,
            "trace": [{"stage": "plan", "ms": 1, "ok": True}],
        },
        "vn": proj.model_dump(mode="json"),
        "draft": "草稿正文",
        "beatSheet": BEAT,
        "reviseRounds": 0,
    }

    out = asyncio.run(
        run_pipeline(
            _cfg(),
            proj,
            instruction="雨夜",
            stages=["plan", "write", "check"],
            persist_run=False,
            voice_check=False,
            resume=resume,
        )
    )
    # 三个阶段全部跳过，状态恢复而非重跑（语音终检已关，不再追加 check）
    assert out["stages"] == ["plan", "write", "check"]
    assert out["finalDraft"] == "草稿正文"
    assert out["check"]["errorCount"] == 1
    assert out["gate"]["pass"] is False
    # 恢复的 trace 保留
    assert out["trace"][0]["stage"] == "plan"


def _project() -> VnProject:
    return VnProject(
        id="p1",
        title="t",
        logline="",
        updatedAt="2026-01-01T00:00:00Z",
        bible=StoryBible(),
        characters=[
            Character(id="c1", defineName="aya", displayName="绫"),
            Character(id="c2", defineName="hero", displayName="主角"),
        ],
        chapters=[SceneChapter(id="ch1", title="第一章", blocks=[])],
        locations=[],
        locationLinks=[],
    )


BEAT = {
    "goal": "雨夜车站重逢",
    "beats": [
        {"name": "车站", "action": "雨夜车站重逢"},
        {"name": "红伞", "action": "红伞被风吹偏"},
    ],
    "triggers": ["红伞"],
}

SCRIPT = (
    "旁白: 雨夜的车站灯火摇曳。\n"
    "绫: 「你的红伞！」\n"
    "主角: 「小心。」\n"
    "旁白: 伞被风吹偏，两人同时伸手。\n"
)


async def _fake_llm(
    config: DeepSeekConfig,
    *,
    role: str,
    user_prompt: str,
    project: Optional[VnProject] = None,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    if role == "architect":
        return {
            "content": json.dumps(BEAT, ensure_ascii=False),
            "model": "mock",
            "role": role,
        }
    if role in ("writer", "editor"):
        return {"content": SCRIPT, "model": "mock", "role": role}
    return {"content": "", "model": "mock", "role": role}


def test_pipeline_e2e_apply_structured_blocks():
    cfg = DeepSeekConfig(apiKey="sk-test-not-real", model="mock")
    vn = _project()

    async def _run():
        with (
            patch(
                "app.core.pipeline.orchestrator.run_harness_llm",
                new=AsyncMock(side_effect=_fake_llm),
            ),
            patch(
                "app.core.pipeline.beat_check.lint_beat_sheet_semantic",
                new=AsyncMock(return_value=[]),
            ),
        ):
            return await run_pipeline(
                cfg,
                vn,
                instruction="写雨夜车站",
                chapter_id="ch1",
                stages=["plan", "write", "check"],
                apply_to_chapter=True,
                semantic_beats=True,
                voice_check=False,
                max_revise_rounds=0,
            )

    out = asyncio.run(_run())
    assert out["gate"]["pass"] is True
    assert out["applied"] is True
    assert out["project"] is not None
    ch = next(c for c in out["project"].chapters if c.id == "ch1")
    types = [b.get("type") for b in ch.blocks]
    assert "narration" in types
    assert "dialogue" in types
    assert any(
        b.get("type") == "dialogue" and b.get("characterId") == "c1" for b in ch.blocks
    )
    assert out.get("trace")
    assert {t["stage"] for t in out["trace"]} >= {"plan", "write", "check", "apply"}
    assert out.get("runId")
    assert out["project"].harnessRuns
    assert out["project"].harnessRuns[0]["kind"] == "pipeline"


def test_pipeline_multi_revise_until_pass():
    cfg = DeepSeekConfig(apiKey="sk-test-not-real", model="mock")
    vn = _project()

    async def _llm(config, *, role, user_prompt, project=None, temperature=0.7):
        if role == "architect":
            return {
                "content": json.dumps(BEAT, ensure_ascii=False),
                "model": "mock",
                "role": role,
            }
        if role == "writer":
            # First draft fails style
            return {
                "content": "绫: 「原来如此。」\n",
                "model": "mock",
                "role": role,
            }
        if role == "editor":
            return {"content": SCRIPT, "model": "mock", "role": role}
        return {"content": "", "model": "mock", "role": role}

    async def _sem(*_a, **_k):
        return []

    async def _run():
        with (
            patch(
                "app.core.pipeline.orchestrator.run_harness_llm",
                new=AsyncMock(side_effect=_llm),
            ),
            patch(
                "app.core.pipeline.beat_check.lint_beat_sheet_semantic",
                new=AsyncMock(side_effect=_sem),
            ),
        ):
            return await run_pipeline(
                cfg,
                vn,
                instruction="修",
                chapter_id="ch1",
                stages=["plan", "write", "check", "revise"],
                apply_to_chapter=True,
                semantic_beats=False,
                voice_check=False,
                max_revise_rounds=2,
            )

    out = asyncio.run(_run())
    assert out["reviseRounds"] >= 1
    assert out["gate"]["pass"] is True
    assert "原来如此" not in (out.get("finalDraft") or "")


def test_finalize_async_keyword_path():
    from app.core.pipeline.gate import finalize_chapter_async

    vn = _project()
    vn.chapters[0].blocks = plain_text_to_script_blocks(SCRIPT, vn.characters)

    async def _run():
        return await finalize_chapter_async(
            vn,
            "ch1",
            cfg=None,
            update_ledger=True,
            enrich_ledger=False,
            voice_check=False,
            semantic_beats=False,
            apply_draft=False,
        )

    out = asyncio.run(_run())
    assert out["gate"]["pass"] is True
    assert out["ledgerUpdated"] is True
    assert out["project"].harnessRuns[0]["kind"] == "finalize"


def test_plain_text_to_script_blocks_structured():
    chars = [Character(id="c1", defineName="aya", displayName="绫")]
    blocks = plain_text_to_script_blocks(
        "旁白: 风很大。\n绫: 「走吧。」\nscene bg_station\nunknown: hi\n",
        chars,
    )
    assert blocks[0]["type"] == "narration"
    assert blocks[1]["type"] == "dialogue" and blocks[1]["characterId"] == "c1"
    assert blocks[2]["type"] == "scene"
    assert blocks[3]["type"] == "raw"


def test_plain_text_to_script_blocks_menu_jump():
    blocks = plain_text_to_script_blocks(
        "绫: 「选哪边？」\n"
        "menu fork:\n"
        '    "去车站":\n'
        "        jump station\n"
        '    "回家":\n'
        "        jump home\n"
        "jump station\n"
        "return\n"
        "选项: 留下 / 离开\n",
        [Character(id="c1", defineName="aya", displayName="绫")],
    )
    types = [b["type"] for b in blocks]
    assert "dialogue" in types
    assert "menu" in types
    assert "jump" in types
    assert "return" in types
    menus = [b for b in blocks if b["type"] == "menu"]
    assert menus[0]["id"] == "fork"
    assert menus[0]["choices"][0]["jump"] == "station"
    assert menus[1]["choices"][0]["text"] == "留下"


def test_plain_text_menu_nested_dialogue_blocks():
    chars = [Character(id="c1", defineName="aya", displayName="绫")]
    blocks = plain_text_to_script_blocks(
        "menu stay:\n"
        '    "留下":\n'
        "        绫: 「那就……再坐一会儿。」\n"
        "        旁白: 雨声更密了。\n"
        "        jump stay_end\n"
        '    "离开":\n'
        "        jump leave\n",
        chars,
    )
    menu = blocks[0]
    assert menu["type"] == "menu"
    stay = menu["choices"][0]
    assert stay["text"] == "留下"
    assert "blocks" in stay
    nested_types = [b["type"] for b in stay["blocks"]]
    assert nested_types == ["dialogue", "narration", "jump"]
    assert stay["blocks"][0]["characterId"] == "c1"
    assert menu["choices"][1]["jump"] == "leave"
