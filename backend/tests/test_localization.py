"""本地化：文本提取 / 术语表 / 进度 / Ren'Py 导出。

覆盖的是"提高本地化效率"这条核心目标里唯一完全缺失的一块。
关键行为：键要稳（插入段落不该丢译文）、只收该翻的文本、术语表能预填、导出用官方字符串翻译。
"""

from __future__ import annotations

from app.core.localization import (
    apply_glossary,
    export_localization_renpy,
    extract_entries,
    localization_stats,
    merge_save,
    source_hash,
    valid_locale,
)
from app.core.project import normalize_project


def _project(blocks, variables=None):  # noqa: ANN001
    return normalize_project(
        {
            "id": "p1",
            "title": "T",
            "variables": variables or [],
            "chapters": [{"id": "ch1", "title": "第一章", "blocks": blocks}],
        }
    )


BLOCKS = [
    {"type": "label", "id": "start", "name": "start"},
    {"type": "music", "action": "play", "file": "bgm/rain.ogg"},
    {"type": "dialogue", "characterId": "c", "text": "你来了。"},
    {"type": "narration", "text": "雨还在下。"},
    {
        "type": "menu",
        "id": "m",
        "prompt": "要接受吗？",
        "choices": [
            {"text": "接受", "blocks": [{"type": "narration", "text": "她笑了。"}]},
            {"text": "谢绝", "blocks": [{"type": "narration", "text": "她别过头。"}]},
        ],
    },
    {
        "type": "if",
        "branches": [
            {
                "condition": "affection >= 1",
                "blocks": [{"type": "dialogue", "characterId": "c", "text": "隐藏台词。"}],
            }
        ],
    },
    {"type": "wait", "seconds": 1},
]


def test_extract_collects_only_translatable_text():
    entries = extract_entries(_project(BLOCKS))
    texts = [e["source"] for e in entries]
    assert texts == [
        "你来了。",
        "雨还在下。",
        "要接受吗？",
        "接受",
        "她笑了。",
        "谢绝",
        "她别过头。",
        "隐藏台词。",
    ]
    kinds = {e["kind"] for e in entries}
    assert kinds == {"dialogue", "narration", "prompt", "choice"}
    # 指令不进翻译表
    assert all("bgm/rain.ogg" not in t for t in texts)


def test_keys_are_stable_and_unique():
    entries = extract_entries(_project(BLOCKS))
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys))
    assert keys[0] == "ch1#2"
    # 嵌套键不能把 chapterId 叠两次
    assert not any(k.count("ch1#") > 1 for k in keys)


def test_translations_survive_inserting_a_block_above():
    """在段落前面插入内容后，译文要能自动接回去（按内容指纹匹配）。

    注意：客户端从 GET 拿到的条目会带 sourceHash，保存时原样回传——测试按这个真实契约走。
    """
    first = extract_entries(_project(BLOCKS))
    saved = merge_save(
        _project(BLOCKS),
        {
            "locales": [{"code": "en", "name": "English"}],
            "entries": [
                {
                    "key": first[0]["key"],
                    "sourceHash": first[0]["sourceHash"],
                    "targets": {"en": "You came."},
                },
                {
                    "key": first[1]["key"],
                    "sourceHash": first[1]["sourceHash"],
                    "targets": {"en": "The rain kept falling."},
                },
            ],
        },
    )

    shifted = [{"type": "label", "id": "start", "name": "start"}] + list(BLOCKS)[1:]
    shifted.insert(2, {"type": "narration", "text": "新插入的一句。"})
    re_extracted = extract_entries(_project(shifted), saved.localization)
    by_source = {e["source"]: e.get("targets", {}).get("en") for e in re_extracted}
    assert by_source["你来了。"] == "You came."
    assert by_source["雨还在下。"] == "The rain kept falling."
    # 新插入的句子不该继承任何旧译文
    assert by_source["新插入的一句。"] in (None, "")


def test_changed_text_at_same_position_drops_stale_translation():
    """同一位置的文本被改写时，旧译文必须丢掉——贴错句子比丢译文严重得多。"""
    first = extract_entries(_project(BLOCKS))
    saved = merge_save(
        _project(BLOCKS),
        {
            "locales": [{"code": "en", "name": "English"}],
            "entries": [
                {
                    "key": first[0]["key"],
                    "sourceHash": first[0]["sourceHash"],
                    "targets": {"en": "You came."},
                }
            ],
        },
    )
    edited = list(BLOCKS)
    edited[2] = {"type": "dialogue", "characterId": "c", "text": "你终于来了。"}
    re_extracted = extract_entries(_project(edited), saved.localization)
    entry = next(e for e in re_extracted if e["source"] == "你终于来了。")
    assert entry["targets"].get("en") in (None, "")


def test_source_hash_ignores_whitespace():
    assert source_hash("你来了。") == source_hash("  你来了。 ")
    assert source_hash("你来了。") != source_hash("你走了。")


def test_stats_count_translated_per_locale():
    entries = extract_entries(_project(BLOCKS))
    saved = merge_save(
        _project(BLOCKS),
        {
            "locales": [
                {"code": "en", "name": "English"},
                {"code": "ja", "name": "日本語"},
            ],
            "entries": [
                {
                    "key": entries[0]["key"],
                    "sourceHash": entries[0]["sourceHash"],
                    "targets": {"en": "You came.", "ja": "来たね。"},
                },
                {
                    "key": entries[1]["key"],
                    "sourceHash": entries[1]["sourceHash"],
                    "targets": {"en": "The rain kept falling."},
                },
            ],
        },
    )
    stats = localization_stats(saved)
    by_code = {s["code"]: s for s in stats["locales"]}
    assert by_code["en"]["translated"] == 2
    assert by_code["ja"]["translated"] == 1
    assert by_code["en"]["total"] == len(entries)
    assert by_code["en"]["ratio"] == round(2 / len(entries), 3)


def test_merge_save_always_takes_source_from_current_script():
    """源文本永远以当前剧本为准（客户端就算传了旧稿的 source 也不采信）。"""
    entries = extract_entries(_project(BLOCKS))
    saved = merge_save(
        _project(BLOCKS),
        {
            "locales": [{"code": "en", "name": "English"}],
            "entries": [
                {
                    "key": entries[0]["key"],
                    "sourceHash": entries[0]["sourceHash"],
                    "source": "旧稿里的句子",
                    "targets": {"en": "You came."},
                }
            ],
        },
    )
    entry = next(e for e in saved.localization["entries"] if e["key"] == entries[0]["key"])
    assert entry["source"] == "你来了。"
    assert entry["targets"]["en"] == "You came."


def test_glossary_prefill_replaces_terms_longest_first():
    glossary = [
        {"term": "林", "targets": {"en": "Lin"}},
        {"term": "林夏", "targets": {"en": "Linxia"}},
    ]
    assert apply_glossary("林夏笑了。", glossary, "en") == "Linxia笑了。"
    assert apply_glossary("林夏和林都笑了。", glossary, "en") == "Linxia和Lin都笑了。"


def test_export_generates_renpy_string_translation():
    entries = extract_entries(_project(BLOCKS))
    saved = merge_save(
        _project(BLOCKS),
        {
            "locales": [{"code": "en", "name": "English"}],
            "entries": [
                {
                    "key": entries[0]["key"],
                    "sourceHash": entries[0]["sourceHash"],
                    "targets": {"en": 'You came "here".'},
                },
                {
                    "key": entries[1]["key"],
                    "sourceHash": entries[1]["sourceHash"],
                    "targets": {"en": "雨还在下。"},  # 与原文相同 → 跳过
                },
            ],
        },
    )
    files = export_localization_renpy(saved)
    assert list(files) == ["tl/en/strings.rpy"]
    content = files["tl/en/strings.rpy"]
    assert "translate en strings:" in content
    assert 'old "你来了。"' in content
    assert 'new "You came \\"here\\"."' in content
    # 与原文一致的条目不该出现在导出里
    assert 'new "雨还在下。"' not in content


def test_export_skips_locales_without_translations_and_bad_codes():
    saved = merge_save(
        _project(BLOCKS),
        {
            "locales": [
                {"code": "en", "name": "English"},
                {"code": "bad code!", "name": "非法代码"},
                {"code": "ja", "name": "日本語"},
            ],
            "entries": [],
        },
    )
    assert export_localization_renpy(saved) == {}
    assert [l["code"] for l in saved.localization["locales"]] == ["en", "ja"]


def test_valid_locale_whitelist():
    assert valid_locale("en")
    assert valid_locale("zh-Hans")
    assert valid_locale("pt_BR")
    assert not valid_locale("x")
    assert not valid_locale("en us")
    assert not valid_locale('en"; import os')
