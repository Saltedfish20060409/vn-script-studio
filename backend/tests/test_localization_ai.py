"""AI 代翻：批量挑选、提示词、响应解析、合并（不碰网络）。"""

from __future__ import annotations

import json

from app.core.localization_ai import (
    MAX_ENTRIES_PER_CALL,
    apply_translations,
    build_user_prompt,
    parse_translation_response,
    select_batch,
)


def _entries(n: int, *, translated: int = 0):
    out = []
    for i in range(n):
        out.append(
            {
                "key": f"ch1#{i}",
                "chapterId": "ch1",
                "kind": "dialogue",
                "source": f"第{i}句台词。",
                "sourceHash": f"h{i}",
                "targets": {"en": "done"} if i < translated else {},
                "status": {},
            }
        )
    return out


def test_select_batch_skips_translated_and_respects_budget():
    entries = _entries(10, translated=3)
    picked = select_batch(entries, locale="en")
    assert [e["key"] for e in picked] == [f"ch1#{i}" for i in range(3, 10)]
    assert len(select_batch(entries, locale="en", max_entries=2)) == 2
    # 字符预算：每条 6 个字左右，给 20 字 → 不会全选
    small = select_batch(entries, locale="en", max_chars=20)
    assert 0 < len(small) < 7


def test_select_batch_can_include_translated_for_overwrite():
    entries = _entries(4, translated=4)
    assert select_batch(entries, locale="en") == []
    assert len(select_batch(entries, locale="en", only_untranslated=False)) == 4


def test_default_batch_size_is_bounded():
    assert len(select_batch(_entries(200), locale="en")) <= MAX_ENTRIES_PER_CALL


def test_build_user_prompt_includes_glossary_and_json_payload():
    batch = _entries(2)
    prompt = build_user_prompt(
        batch,
        locale="en",
        locale_name="English",
        glossary=[{"term": "林夏", "targets": {"en": "Linxia"}}],
    )
    assert "English" in prompt
    assert "林夏 → Linxia" in prompt
    assert '"key": "ch1#0"' in prompt
    # 没给译名的术语不喂给模型（避免误导）
    assert "未给译名" not in prompt


def test_parse_handles_fences_extra_prose_and_wrong_shapes():
    allowed = ["a", "b"]
    assert parse_translation_response('{"译文":[{"key":"a","text":"A"}]}', allowed) == {"a": "A"}
    assert parse_translation_response(
        '好的，结果如下：\n```json\n{"译文":[{"key":"b","text":"B"}]}\n```\n以上。', allowed
    ) == {"b": "B"}
    # 扁平结构
    assert parse_translation_response('{"a": "A2"}', allowed) == {"a": "A2"}
    # 顶层数组
    assert parse_translation_response('[{"key":"a","text":"A3"}]', allowed) == {"a": "A3"}


def test_parse_drops_unknown_keys_and_empty_values():
    allowed = ["a"]
    out = parse_translation_response(
        '{"译文":[{"key":"a","text":"A"},{"key":"编造的","text":"X"},{"key":"a2","text":"  "}]}',
        allowed,
    )
    assert out == {"a": "A"}


def test_parse_drops_non_string_targets():
    """模型返回数字/布尔/嵌套结构时不能 str() 一兜就当译文写进剧本。"""
    allowed = ["a", "b", "c", "d"]
    raw = json.dumps(
        {
            "译文": [
                {"key": "a", "text": 66},
                {"key": "b", "text": True},
                {"key": "c", "text": ["x"]},
                {"key": "d", "text": None},
            ]
        },
        ensure_ascii=False,
    )
    assert parse_translation_response(raw, allowed) == {}
    # text 缺失/为空时仍可回落到 translation，但同样必须是字符串
    assert parse_translation_response('{"译文":[{"key":"a","translation":"A"}]}', allowed) == {"a": "A"}
    assert parse_translation_response('{"译文":[{"key":"a","text":"","translation":"A"}]}', allowed) == {"a": "A"}
    assert parse_translation_response('{"译文":[{"key":"a","text":0,"translation":"A"}]}', allowed) == {"a": "A"}
    assert parse_translation_response('{"译文":[{"key":"a","translation":7}]}', allowed) == {}


def test_parse_returns_empty_on_garbage():
    assert parse_translation_response("模型今天不想工作", ["a"]) == {}
    assert parse_translation_response("", ["a"]) == {}


def test_apply_translations_marks_ai_and_keeps_human_text():
    entries = _entries(3, translated=1)  # ch1#0 已有译文
    result = apply_translations(
        entries,
        locale="en",
        mapping={"ch1#0": "AI 想覆盖它", "ch1#1": "AI 译文"},
    )
    assert result["applied"] == 1
    assert result["skipped"] == 1
    by_key = {e["key"]: e for e in result["entries"]}
    # 已有译文不被覆盖，状态也不变
    assert by_key["ch1#0"]["targets"]["en"] == "done"
    assert by_key["ch1#0"]["status"] == {}
    # AI 译文标记为 ai（界面显示"AI 译·待校对"）
    assert by_key["ch1#1"]["targets"]["en"] == "AI 译文"
    assert by_key["ch1#1"]["status"]["en"] == "ai"


def test_apply_translations_can_overwrite_when_asked():
    entries = _entries(1, translated=1)
    result = apply_translations(
        entries, locale="en", mapping={"ch1#0": "重译"}, overwrite=True
    )
    assert result["applied"] == 1
    assert result["skipped"] == 0
    assert result["entries"][0]["targets"]["en"] == "重译"
    assert result["entries"][0]["status"]["en"] == "ai"


def test_apply_translations_does_not_mutate_input():
    entries = _entries(1)
    apply_translations(entries, locale="en", mapping={"ch1#0": "X"})
    assert entries[0]["targets"] == {}


def test_apply_translations_reports_unknown_keys():
    result = apply_translations(
        _entries(1), locale="en", mapping={"ch9#0": "谁？", "ch1#0": "好"}
    )
    assert result["applied"] == 1
    assert result["unknown"] == 1
