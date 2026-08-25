"""Agent loop tools — project-scoped only."""

from __future__ import annotations

from app.core.agent import _parse_agent_json
from app.core.agent_loop import (
    _is_echo_of_tool_result,
    _normalize_tool_calls,
    _parse_loop_json,
)
from app.core.agent_tools import run_agent_tool, tool_catalog_for_prompt
from app.domain.types import VnProject


def test_parse_agent_json_prose_fallback():
    """模型忽略 response_format 返回纯文本：不得抛 JSONDecodeError，原文当回复。"""
    msg, actions = _parse_agent_json(
        "好的，我来帮你审查并续写这个剧本。首先我需要通读第一章……"
    )
    assert "审查" in msg
    assert actions == []


def test_parse_agent_json_empty_fallback():
    msg, actions = _parse_agent_json("")
    assert "无法解析" in msg or "没产出" in msg
    assert actions == []


def test_parse_agent_json_fenced_json_still_parses():
    msg, actions = _parse_agent_json(
        '```json\n{"message": "已按意见修改", "actions": [{"op": "rewrite_chapter", "chapterId": "ch1"}]}\n```'
    )
    assert "已按意见修改" in msg
    assert actions and actions[0]["op"] == "rewrite_chapter"


def test_parse_loop_json_prose_no_crash():
    """_parse_loop_json 对纯文本回复走兜底，不抛异常。"""
    parsed = _parse_loop_json("模型直接说了句话，没给 JSON。")
    assert isinstance(parsed.get("message"), str)
    assert parsed.get("actions") == []


def test_echo_detection_catches_full_echo():
    chapter = "#第一章\n[label start]\n（她静静地坐起身……）\n" * 20
    reply = chapter[:1500]  # 模型把工具读到的正文开头当回复
    assert _is_echo_of_tool_result(reply, chapter) is True


def test_echo_detection_ignores_short_quotes_and_reviews():
    chapter = "#第一章\n[label start]\n（她静静地坐起身……）\n" * 20
    # 正常引用一小段 + 自己的意见 → 不误杀
    review = "（她静静地坐起身）这段的镜头感不错，但男主反应可以更有层次。"
    assert _is_echo_of_tool_result(review, chapter) is False
    # 空/过短回复不误杀
    assert _is_echo_of_tool_result("好的", chapter) is False
    assert _is_echo_of_tool_result("", chapter) is False


def _demo() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {
                    "id": "c1",
                    "defineName": "linxia",
                    "displayName": "霖夏",
                    "voice": "克制",
                    "bio": "雨夜车站的人",
                }
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "车站",
                    "blocks": [
                        {"type": "narration", "text": "雨很大。"},
                        {
                            "type": "dialogue",
                            "characterId": "c1",
                            "text": "伞借你。",
                        },
                    ],
                }
            ],
            "bible": {"world": "近未来雨城", "outline": "车站邂逅"},
            "locations": [{"id": "l1", "name": "车站", "description": "夜雨"}],
        }
    )


def test_tool_catalog_mentions_no_shell():
    cat = tool_catalog_for_prompt()
    assert "get_chapter" in cat
    assert "shell" not in cat.lower() or "禁止" in cat


def test_get_chapter_and_search():
    p = _demo()
    ok, text = run_agent_tool("get_chapter", {}, project=p, chapter_id="ch1")
    assert ok
    assert "伞借你" in text or "雨" in text
    ok2, hits = run_agent_tool(
        "search_script", {"query": "伞"}, project=p, chapter_id="ch1"
    )
    assert ok2
    assert "伞" in hits


def test_get_chapter_multi():
    """get_chapter 支持 chapterRefs 一次读多章（跨章对照）。"""
    p = _demo()
    # demo 只有一章，复制一个第二章节做多章测试
    import copy

    ch2 = copy.deepcopy(p.chapters[0])
    ch2.id = "ch2"
    ch2.title = "第二章"
    p.chapters.append(ch2)

    ok, text = run_agent_tool(
        "get_chapter", {"chapterRefs": "ch1, 第二章"}, project=p, chapter_id="ch1"
    )
    assert ok
    assert "车站" in text  # 第一章标题
    assert "第二章" in text
    # 单章模式仍可用（不传 refs）
    ok2, single = run_agent_tool("get_chapter", {}, project=p, chapter_id="ch1")
    assert ok2 and "伞借你" in single or "雨" in single
    # 缺省章容错
    ok3, text3 = run_agent_tool(
        "get_chapter", {"chapterRefs": "ch1, 不存在的章"}, project=p, chapter_id="ch1"
    )
    assert ok3
    assert "未找到章节" in text3


def test_get_character_and_bible():
    p = _demo()
    ok, text = run_agent_tool("get_character", {"ref": "霖夏"}, project=p)
    assert ok and "霖夏" in text
    ok2, bible = run_agent_tool("get_bible", {}, project=p)
    assert ok2 and "雨城" in bible
    ok3, sb = run_agent_tool("search_bible", {"query": "车站"}, project=p)
    assert ok3 and "车站" in sb


def test_lint_draft_runs():
    p = _demo()
    ok, out = run_agent_tool(
        "lint_draft",
        {"text": '旁白 "你好。"\n霖夏 "嗯。"'},
        project=p,
    )
    assert ok
    assert "体检" in out or "问题" in out or "通过" in out


def test_parse_loop_json_tool_calls():
    raw = '{"message":"先查","tool_calls":[{"id":"t1","name":"get_chapter","arguments":{}}],"done":false}'
    parsed = _parse_loop_json(raw)
    calls = _normalize_tool_calls(parsed.get("tool_calls"))
    assert len(calls) == 1
    assert calls[0]["name"] == "get_chapter"


def test_legacy_actions_only_means_done_path():
    raw = '{"message":"这是意见","actions":[]}'
    parsed = _parse_loop_json(raw)
    calls = _normalize_tool_calls(parsed.get("tool_calls"))
    assert calls == []
