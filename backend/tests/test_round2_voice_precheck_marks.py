"""第二轮：声线策略 / 写后闸 markHints / 续写前对账。"""
from __future__ import annotations

import asyncio

from app.core.ai import DeepSeekConfig
from app.core.agent_context import build_agent_context
from app.core.character_voice.corpus import dialogue_write_policy, make_sample
from app.core.character_voice.generate import generate_long_scene
from app.core.demo import create_demo_project
from app.core.project import normalize_project
from app.core.write_gate import gate_continue_draft
from app.core.write_precheck import precheck_before_continue


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test-not-real", model="mock")


def test_dialogue_write_policy_advise_only_without_corpus():
    p = create_demo_project()
    char = p.characters[0]
    char.voiceCorpus = []
    char.voiceMind = ""
    char.voice = ""
    policy = dialogue_write_policy(char)
    assert policy["mode"] == "advise_only"


def test_dialogue_write_policy_anchored_with_mind():
    p = create_demo_project()
    char = p.characters[0]
    char.voiceMind = "## 视角\n短句。"
    policy = dialogue_write_policy(char)
    assert policy["mode"] == "anchored"
    assert policy["mustSample"] is True


def test_generate_long_scene_advise_only_skips_llm():
    p = create_demo_project()
    char = p.characters[0]
    char.voiceCorpus = []
    char.voiceMind = ""
    char.voice = ""

    async def _run():
        return await generate_long_scene(_cfg(), p, character_id=char.id)

    out = asyncio.run(_run())
    assert out.get("adviceOnly") is True
    assert out.get("kind") == "advice"
    assert out.get("lines") == []
    assert "不足" in (out.get("advice") or "") or "建议" in (out.get("advice") or "")


def test_char_card_injects_voice_downgrade_for_advise_only():
    p = normalize_project(
        {
            "id": "p-voice",
            "title": "声线",
            "characters": [
                {
                    "id": "c1",
                    "displayName": "空壳",
                    "defineName": "empty",
                    "voice": "",
                    "bio": "",
                }
            ],
            "chapters": [{"id": "ch1", "title": "一", "prose": "空壳站在门口。"}],
        }
    )
    ctx = build_agent_context(p, chapterId="ch1", userMessage="接着写", task="continue")
    assert "声线降级" in ctx.text or "勿写成长篇对白" in ctx.text


def test_write_gate_mark_hints_for_apartment_tour():
    draft = "林夏点头。\n这里是厨房，带你熟悉一下这个空间。\n他没说话。"
    result = gate_continue_draft(draft)
    assert result.passed is False
    assert result.markHints
    assert any("厨房" in h.get("quote", "") or "熟悉" in h.get("quote", "") for h in result.markHints)
    assert result.as_meta().get("markHints")


def test_precheck_flags_dead_character_in_draft():
    p = normalize_project(
        {
            "id": "p-dead",
            "title": "对账",
            "characters": [
                {"id": "c1", "displayName": "顾沉", "defineName": "gu"},
            ],
            "chapters": [
                {"id": "ch1", "title": "一", "prose": "雨停了。"},
                {"id": "ch2", "title": "二", "prose": "顾沉推门进来。"},
            ],
            "writingLedger": {
                "characterStates": [
                    {
                        "characterName": "顾沉",
                        "characterId": "c1",
                        "chapterId": "ch1",
                        "chapterTitle": "一",
                        "body": "已故",
                        "emotion": "—",
                        "relations": "—",
                    }
                ],
                "foreshadows": [],
                "chapterFacts": [],
            },
        }
    )
    report = precheck_before_continue(p, chapter_id="ch2", draft="顾沉推门进来。")
    assert any(i.code == "dead_character_present" for i in report.issues)
    assert report.ok is False


def test_precheck_warns_stale_foreshadow():
    chapters = [
        {"id": f"ch{i}", "title": f"第{i}章", "prose": f"第{i}章正文。"}
        for i in range(1, 6)
    ]
    p = normalize_project(
        {
            "id": "p-fo",
            "title": "伏笔",
            "characters": [],
            "chapters": chapters,
            "writingLedger": {
                "characterStates": [],
                "chapterFacts": [],
                "foreshadows": [
                    {
                        "id": "f1",
                        "hook": "抽屉里有第二把钥匙",
                        "status": "open",
                        "plantedChapter": "ch1",
                    }
                ],
            },
        }
    )
    report = precheck_before_continue(p, chapter_id="ch5")
    assert any(i.code == "foreshadow_stale" for i in report.issues)
    ctx = build_agent_context(p, chapterId="ch5", userMessage="接着写", task="continue")
    assert "续写前对账" in ctx.text
    assert "钥匙" in ctx.text


def test_write_gate_dead_character_with_project():
    p = normalize_project(
        {
            "id": "p-gate-dead",
            "title": "闸",
            "characters": [{"id": "c1", "displayName": "顾沉", "defineName": "gu"}],
            "chapters": [{"id": "ch1", "title": "一", "prose": "雨。"}],
            "writingLedger": {
                "characterStates": [
                    {
                        "characterName": "顾沉",
                        "body": "阵亡",
                        "emotion": "",
                        "relations": "",
                        "chapterId": "ch1",
                    }
                ],
                "foreshadows": [],
                "chapterFacts": [],
            },
        }
    )
    result = gate_continue_draft("顾沉忽然开口。", project=p, chapter_id="ch1")
    assert result.passed is False
    assert any(i.get("code") == "dead_character_present" for i in result.issues)
