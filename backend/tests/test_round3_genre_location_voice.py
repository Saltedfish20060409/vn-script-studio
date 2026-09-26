"""第三轮：地点对账 / 体裁硬路径 / 尾部口吻对照。"""
from __future__ import annotations

from app.core.agent_context import build_agent_context, output_contract, task_key_rules
from app.core.character_voice.corpus import format_voice_contrast_tail, make_sample
from app.core.genre_write import resolve_writing_genre
from app.core.project import normalize_project
from app.core.write_precheck import precheck_before_continue


def test_resolve_writing_genre_explicit_and_markers():
    assert (
        resolve_writing_genre(
            normalize_project({"id": "a", "title": "t", "writingGenre": "novel", "chapters": []})
        )
        == "novel"
    )
    assert (
        resolve_writing_genre(
            normalize_project({"id": "b", "title": "t", "genre": "轻小说", "chapters": []})
        )
        == "novel"
    )
    assert (
        resolve_writing_genre(
            normalize_project({"id": "c", "title": "t", "genre": "视觉小说", "chapters": []})
        )
        == "vn"
    )
    # 「视觉小说」不得被「小说」误判
    assert (
        resolve_writing_genre(
            normalize_project({"id": "d", "title": "t", "genre": "视觉小说·恋爱", "chapters": []})
        )
        == "vn"
    )


def test_novel_continue_gets_genre_rules_and_contract():
    p = normalize_project(
        {
            "id": "p-novel",
            "title": "小说",
            "writingGenre": "novel",
            "characters": [{"id": "c1", "displayName": "林", "defineName": "lin"}],
            "chapters": [{"id": "ch1", "title": "一", "prose": "雨停了。"}],
        }
    )
    rules = task_key_rules("continue", p)
    assert any("小说" in r or "Ren'Py" in r for r in rules)
    contract = output_contract("continue", p)
    assert "叙述" in contract or "「」" in contract
    assert "Ren'Py" in contract or "不要 Ren'Py" in contract or "不要" in contract


def test_vn_branch_keeps_menu_contract():
    p = normalize_project(
        {
            "id": "p-vn",
            "title": "VN",
            "writingGenre": "vn",
            "chapters": [{"id": "ch1", "title": "一", "prose": "他推开门。"}],
        }
    )
    contract = output_contract("branch", p)
    assert "menu" in contract.lower() or "选项" in contract


def test_gone_location_precheck():
    p = normalize_project(
        {
            "id": "p-loc",
            "title": "地点",
            "locations": [
                {
                    "id": "l1",
                    "name": "旧钟楼",
                    "description": "三年前已毁，禁止进入。",
                }
            ],
            "chapters": [
                {"id": "ch1", "title": "一", "prose": "他再次走进旧钟楼。"},
            ],
        }
    )
    report = precheck_before_continue(p, chapter_id="ch1")
    assert any(i.code == "gone_location_present" for i in report.issues)
    ctx = build_agent_context(p, chapterId="ch1", userMessage="接着写", task="continue")
    assert "旧钟楼" in ctx.text
    assert "续写前对账" in ctx.text


def test_unknown_location_tag_surfaces_in_precheck():
    """VN 场景图无地点认领 → 续写前对账应能看见（continuity 子集）。"""
    p = normalize_project(
        {
            "id": "p-tag",
            "title": "图",
            "writingGenre": "vn",
            "locations": [{"id": "l1", "name": "车站", "imageTag": "bg station"}],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "一",
                    "blocks": [
                        {"type": "scene", "image": "bg mystery_void"},
                        {"type": "narration", "text": "雾很重。"},
                    ],
                }
            ],
        }
    )
    report = precheck_before_continue(p, chapter_id="ch1")
    assert any(i.code == "unknown_location_tag" for i in report.issues), report.issues


def test_voice_contrast_tail_in_continue_context():
    samples = [
        make_sample(
            scenario=f"sc{i}",
            scenario_label=f"场景{i}",
            axis=None,
            hypothesis=None,
            lines=[{"speaker": "self", "text": f"短句正例{i}。"}],
            source="preference",
        )
        for i in range(6)
    ]
    p = normalize_project(
        {
            "id": "p-voice-tail",
            "title": "声线尾",
            "characters": [
                {
                    "id": "c1",
                    "displayName": "澪",
                    "defineName": "mio",
                    "voice": "短句",
                    "voiceMind": "## 视角\n先顾眼前。",
                    "voiceCorpus": [s.model_dump() for s in samples],
                }
            ],
            "chapters": [{"id": "ch1", "title": "一", "prose": "澪站在月台上。"}],
        }
    )
    # 单测 format 本身
    chars = p.characters
    tail = format_voice_contrast_tail(chars)
    assert "口吻对照" in tail
    assert "澪" in tail
    ctx = build_agent_context(p, chapterId="ch1", userMessage="接着写澪", task="continue")
    # 尾部窗口应出现口吻对照（在硬规则附近）
    assert "口吻对照" in ctx.text
    assert any("口吻对照" in x for x in ctx.included)
