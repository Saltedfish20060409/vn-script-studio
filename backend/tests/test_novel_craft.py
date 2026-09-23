"""轻小说写作技艺度量（`core/novel_craft`）的测试。

重点验证三件容易写错的事：

1. **注音的两种写法都要认**，且"写坏了"要能定位到行/列（未闭合、分隔符数量不对、注音为空），
   同一汉字注音前后不一致要能抓出来——但两种读法**并列时不许瞎猜**谁对。
2. **拟声/感叹统计必须按章正确**（含"长词优先、不重复计数"），只报事实、不做好坏判断。
3. **章末钩子评分必须能区分"悬念式结尾"与"平淡结尾"**，同时暴露它是**启发式**：
   同输入同输出、逐项有依据字段、带声明。

另外：空工程 / 空章 / 只有演出指令的章都不能抛异常，`coverage` 必须如实（扫了几章、是否截断）。
"""

from __future__ import annotations

import json

import pytest

from app.core.novel_craft import (
    HOOK_WEIGHTS,
    ISSUE_RUBY_DENSITY_HIGH,
    ISSUE_RUBY_EMPTY_READING,
    ISSUE_RUBY_INCONSISTENT,
    ISSUE_RUBY_MISSING_SEPARATOR,
    ISSUE_RUBY_PIPE_MISMATCH,
    ISSUE_RUBY_READING_WITHOUT_BASE,
    ISSUE_RUBY_UNCLOSED_BRACE,
    ISSUE_RUBY_UNCLOSED_BRACKET,
    KIND_DIALOGUE,
    KIND_NARRATION,
    ProseUnit,
    analyze_novel_craft,
    chapter_readability,
    onomatopoeia_hits,
    parse_ruby_marks,
    scan_ruby_issues,
    score_chapter_hook,
)
from app.domain.types import VnProject
from app.services.writing_stats import count_words

# ------------------------------------------------------------------ 夹具工具


def _d(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def _n(text: str) -> dict:
    return {"type": "narration", "text": text}


def _ch(cid: str, blocks: list, *, title: str | None = None, prose: str | None = None) -> dict:
    chapter = {"id": cid, "title": title or cid, "blocks": blocks}
    if prose is not None:
        chapter["prose"] = prose
    return chapter


def _project(
    chapters: list,
    *,
    chapter_index: list | None = None,
    characters: list | None = None,
) -> VnProject:
    data: dict = {
        "id": "p-craft",
        "title": "技艺度量",
        "updatedAt": "2026-01-01T00:00:00+00:00",
        "characters": characters
        if characters is not None
        else [
            {"id": "yukina", "defineName": "yukina", "displayName": "雪菜"},
            {"id": "shin", "defineName": "shin", "displayName": "真"},
        ],
        "chapters": chapters,
    }
    if chapter_index is not None:
        data["chapterIndex"] = chapter_index
    return VnProject.model_validate(data)


def _codes(issues: list) -> list:
    return [str(i["code"]) for i in issues]


# ------------------------------------------------------------------ 注音解析


def test_parse_ruby_marks_supports_bar_and_brace_forms():
    text = "她叫｜雪菜《ゆきな》，也写作{雪菜|ゆきな}。"
    marks = parse_ruby_marks(text)
    assert [m["form"] for m in marks] == ["bar", "brace"]
    assert marks[0]["base"] == "雪菜"
    assert marks[0]["reading"] == "ゆきな"
    assert marks[0]["column"] == text.index("｜") + 1
    assert marks[1]["base"] == "雪菜"
    assert marks[1]["reading"] == "ゆきな"
    assert marks[1]["column"] == text.index("{雪菜") + 1
    # 返回的行结构必须能直接被 JSON 序列化（不含内部 span 元组）
    assert json.dumps(marks, ensure_ascii=False)


def test_parse_ruby_marks_ignores_incomplete_or_unrelated_brackets():
    assert parse_ruby_marks("｜雪菜《ゆきな") == []  # 未闭合
    assert parse_ruby_marks("{雪菜|}") == []  # 注音为空
    assert parse_ruby_marks("{雪菜}") == []  # 缺分隔符
    assert parse_ruby_marks("《夜色》是她最爱的小说。") == []  # 书名号，不是注音


def test_unclosed_bracket_is_reported_with_line_and_column():
    text = "他说｜雪菜《ゆきな"
    issues = scan_ruby_issues(text, chapter_id="c1", chapter_title="第一章", line=3)
    assert _codes(issues) == [ISSUE_RUBY_UNCLOSED_BRACKET]
    issue = issues[0]
    assert issue["severity"] == "warn"
    assert issue["line"] == 3
    assert issue["column"] == text.index("《") + 1
    assert "没有闭合" in issue["message"]

    extra = scan_ruby_issues("她说》然后就走了。")
    assert _codes(extra) == [ISSUE_RUBY_UNCLOSED_BRACKET]
    assert "多出一个" in extra[0]["message"]


def test_unclosed_brace_is_reported():
    issues = scan_ruby_issues("{雪菜|ゆきな")
    assert _codes(issues) == [ISSUE_RUBY_UNCLOSED_BRACE]
    assert issues[0]["severity"] == "warn"


def test_empty_reading_is_reported_in_both_forms():
    text = "他喊｜雪菜《》又喊{雪菜|}。"
    issues = scan_ruby_issues(text, chapter_id="c9", chapter_title="第九章", line=2)
    assert _codes(issues) == [ISSUE_RUBY_EMPTY_READING, ISSUE_RUBY_EMPTY_READING]
    assert all(i["severity"] == "warn" for i in issues)
    assert {i["form"] for i in issues} == {"bar", "brace"}
    assert all(i["line"] == 2 for i in issues)
    assert [i["column"] for i in issues] == sorted(i["column"] for i in issues)


def test_pipe_mismatch_and_missing_separator_have_distinct_codes():
    mismatch = scan_ruby_issues("{雪菜|ゆきな|ゆきの}")
    assert _codes(mismatch) == [ISSUE_RUBY_PIPE_MISMATCH]
    assert mismatch[0]["severity"] == "warn"

    missing = scan_ruby_issues("{雪菜}")
    assert _codes(missing) == [ISSUE_RUBY_MISSING_SEPARATOR]
    # 花括号在正文里也可能是普通文本，因此只给 info，不吓人
    assert missing[0]["severity"] == "info"


def test_inconsistent_reading_flags_minority_with_expected_reading():
    project = _project(
        [
            _ch("c1", [_n("｜雪菜《ゆきな》笑了。｜雪菜《ゆきな》点头。")]),
            _ch("c2", [_n("｜雪菜《ゆきの》抬起头。")]),
        ]
    )
    out = analyze_novel_craft(project)
    inc = [i for i in out["rubyIssues"] if i["code"] == ISSUE_RUBY_INCONSISTENT]
    assert len(inc) == 1
    assert inc[0]["chapterId"] == "c2"
    assert inc[0]["reading"] == "ゆきの"
    assert inc[0]["expected"] == "ゆきな"  # 多数派 = 多数处写法
    assert inc[0]["severity"] == "warn"
    assert inc[0]["line"] == 1
    assert inc[0]["column"] == 1

    consistency = out["rubyConsistency"]
    assert len(consistency) == 1
    assert consistency[0]["base"] == "雪菜"
    assert consistency[0]["majority"] == "ゆきな"
    assert consistency[0]["tied"] is False
    assert consistency[0]["occurrences"] == 3


def test_inconsistent_reading_tie_does_not_guess():
    """两种读法各出现一次时，本模块**不许**挑一个宣布「你错了」。"""
    project = _project(
        [_ch("c1", [_n("｜雪菜《ゆきな》笑了。")]), _ch("c2", [_n("｜雪菜《ゆきの》抬头。")])]
    )
    out = analyze_novel_craft(project)
    inc = [i for i in out["rubyIssues"] if i["code"] == ISSUE_RUBY_INCONSISTENT]
    assert len(inc) == 2
    assert all(i["severity"] == "info" for i in inc)
    assert all(i["expected"] is None for i in inc)
    assert all("无法判断" in i["message"] for i in inc)
    assert out["rubyConsistency"][0]["tied"] is True
    assert out["rubyConsistency"][0]["majority"] is None


def test_bare_bracket_is_hinted_but_never_counted_as_ruby():
    project = _project(
        [_ch("c1", [_n("《夜色》是她最爱的小说，她念着｜雪菜《ゆきな》。")])]
    )
    out = analyze_novel_craft(project)
    row = out["perChapter"][0]
    assert row["ruby"]["count"] == 1  # 只算真正的注音标记
    assert row["ruby"]["titleLikeCount"] == 1
    hints = [i for i in out["rubyIssues"] if i["code"] == ISSUE_RUBY_READING_WITHOUT_BASE]
    assert len(hints) == 1
    assert hints[0]["severity"] == "info"
    assert "书名号" in hints[0]["message"]


def test_high_ruby_density_is_only_an_info():
    text = "｜雪菜《ゆきな》和｜真《しん》走在{雨|あめ}里，撑着{伞|かさ}。"
    project = _project([_ch("c1", [_n(text)])])
    out = analyze_novel_craft(project)
    row = out["perChapter"][0]
    assert row["ruby"]["count"] == 4
    assert row["ruby"]["per1000Chars"] == round(4 / row["words"]["total"] * 1000, 2)
    density = [i for i in out["rubyIssues"] if i["code"] == ISSUE_RUBY_DENSITY_HIGH]
    assert len(density) == 1
    assert density[0]["severity"] == "info"  # 只报事实，不要求改
    assert density[0]["chapterId"] == "c1"


# ------------------------------------------------------------- 拟声与感叹统计


def test_onomatopoeia_matching_prefers_longest_word_and_counts_once():
    hits = onomatopoeia_hits("心跳声很大")
    assert [h["word"] for h in hits] == ["心跳声"]
    assert hits[0]["group"] == "borrowed_heartbeat"
    # "咚咚" 是长词，不会被拆成两个"咚"
    assert [h["word"] for h in onomatopoeia_hits("咚咚")] == ["咚咚"]


def test_onomatopoeia_and_exclaim_density_per_chapter():
    project = _project(
        [
            _ch("c1", [_n("他听见ドキドキ的声音。哗啦一声，窗被吹开！"), _d("yukina", "别走！")]),
            _ch("c2", [_n("他安静地坐着。")]),
        ]
    )
    out = analyze_novel_craft(project)
    hot, calm = out["perChapter"]

    assert hot["onomatopoeia"]["count"] == 2
    assert hot["onomatopoeia"]["byCategory"] == {"ja_feeling": 1, "zh_sound": 1}
    assert hot["onomatopoeia"]["per1000Chars"] == round(
        2 / hot["words"]["total"] * 1000, 2
    )
    assert hot["punctuation"]["exclaim"] == 2
    assert hot["punctuation"]["question"] == 0
    assert hot["punctuation"]["exclaimPer1000"] == round(
        2 / hot["words"]["total"] * 1000, 2
    )

    assert calm["onomatopoeia"]["count"] == 0
    assert calm["onomatopoeia"]["per1000Chars"] == 0.0
    assert calm["punctuation"]["exclaim"] == 0
    assert calm["punctuation"]["exclaimPer1000"] == 0.0


def test_strict_count_excludes_borrowed_group():
    project = _project([_ch("c1", [_n("心跳声盖过了ドキドキ。")])])
    row = analyze_novel_craft(project)["perChapter"][0]
    assert row["onomatopoeia"]["count"] == 2
    assert row["onomatopoeia"]["strictCount"] == 1  # "心跳声"是意译借用词，不算严格拟声


def test_question_and_exclaim_are_counted_separately():
    project = _project([_ch("c1", [_d("shin", "真的吗？为什么？"), _d("yukina", "因为啊！")])])
    row = analyze_novel_craft(project)["perChapter"][0]
    assert row["punctuation"]["question"] == 2
    assert row["punctuation"]["exclaim"] == 1


# ------------------------------------------------------------- 可读性事实


def test_readability_reports_ratios_paragraphs_and_runs():
    blocks = [
        _n("雨很大。"),
        _d("yukina", "走吧。"),
        _d("shin", "别等了。"),
        _n("他抬起头。"),
        _d("yukina", "再等等。"),
        _d("shin", "……好。"),
        _d("yukina", "我陪你。"),
    ]
    project = _project([_ch("c1", blocks)])
    row = analyze_novel_craft(project)["perChapter"][0]

    dialogue_words = sum(count_words(b["text"]) for b in blocks if b["type"] == "dialogue")
    narration_words = sum(count_words(b["text"]) for b in blocks if b["type"] == "narration")
    assert row["words"]["dialogue"] == dialogue_words
    assert row["words"]["narration"] == narration_words
    assert row["ratio"]["dialogue"] == round(dialogue_words / (dialogue_words + narration_words), 3)
    assert row["ratio"]["narration"] == round(
        narration_words / (dialogue_words + narration_words), 3
    )
    assert row["paragraphs"]["count"] == 7
    assert row["paragraphs"]["avgChars"] == round(
        (dialogue_words + narration_words) / 7, 1
    )
    # 末三句是连续对白，前面被"他抬起头。"打断过
    assert row["paragraphs"]["maxConsecutiveDialogue"] == 3
    assert row["paragraphs"]["maxConsecutiveNarration"] == 1
    assert row["lines"]["dialogue"] == 5
    assert row["lines"]["narration"] == 2


def test_long_paragraph_ratio_uses_the_configured_threshold():
    units = [ProseUnit(KIND_NARRATION, "一二三四五六七八九十"), ProseUnit(KIND_DIALOGUE, "走。")]
    out = chapter_readability(units, long_paragraph_chars=6)
    assert out["paragraphs"]["longCount"] == 1
    assert out["paragraphs"]["longRatio"] == 0.5
    assert out["words"]["total"] == 11
    assert out["words"]["chars"] == len("一二三四五六七八九十") + len("走。")
    assert KIND_DIALOGUE == "dialogue" and KIND_NARRATION == "narration"


def test_choice_text_is_counted_but_kept_out_of_the_ratio():
    blocks = [
        _n("车站很空。"),
        {"type": "menu", "id": "m1", "prompt": "怎么做？", "choices": [{"text": "走过去。"}]},
    ]
    row = analyze_novel_craft(_project([_ch("c1", blocks)]))["perChapter"][0]
    assert row["words"]["choice"] == count_words("怎么做？") + count_words("走过去。")
    # 选项不参与占比：本章只有叙述，所以对白占比是 0（有叙述 ⇒ 这个 0 是有意义的）
    assert row["ratio"]["dialogue"] == 0.0
    assert row["ratio"]["narration"] == 1.0
    assert row["lines"]["choice"] == 2

    # 整章只有选项文本时，占比才"无从谈起"（None，而不是 0%）
    only_choice_blocks = [{"type": "menu", "id": "m1", "choices": [{"text": "走过去。"}]}]
    only_choice = _project([_ch("c1", only_choice_blocks)])
    row2 = analyze_novel_craft(only_choice)["perChapter"][0]
    assert row2["ratio"]["dialogue"] is None
    assert row2["ratio"]["narration"] is None
    assert row2["words"]["total"] == row2["words"]["choice"]


def test_prose_is_preferred_over_blocks_like_count_chapter_words():
    project = _project(
        [
            _ch(
                "c1",
                [_n("这段 blocks 正文不应被统计。")],
                prose="「走吧。」\n雨很大。",
            )
        ]
    )
    row = analyze_novel_craft(project)["perChapter"][0]
    assert row["source"] == "prose"
    assert row["words"]["total"] == count_words("走吧") + count_words("雨很大")
    assert row["lines"]["dialogue"] == 1  # 行首引号 ⇒ 对白
    assert row["lines"]["narration"] == 1
    assert row["source"] == "prose"  # blocks 里的那句没有被重复计数
    assert row["words"]["dialogue"] + row["words"]["narration"] == row["words"]["total"]


def test_prose_speaker_prefix_is_dialogue():
    project = _project(
        [_ch("c1", [], prose="雪菜：我们走吧。\n他点了点头，没有说话。")]
    )
    row = analyze_novel_craft(project)["perChapter"][0]
    assert row["lines"]["dialogue"] == 1
    assert row["lines"]["narration"] == 1


# ------------------------------------------------------------- 章末钩子评分


SUSPENSE_BLOCKS = [_n("雨声渐密。"), _d("yukina", "……难道，你一直都知道？")]
FLAT_BLOCKS = [
    _n(
        "他说明了车站的位置，解释了三趟列车的时刻，"
        "并确认了明天早上八点在东口集合的具体安排，然后就回家睡觉了。"
    )
]


def test_hook_score_separates_suspense_from_flat_ending():
    chapters = [_ch("s1", SUSPENSE_BLOCKS), _ch("f1", FLAT_BLOCKS)]
    with_hook = _project(
        chapters,
        chapter_index=[
            {"chapterId": "s1", "title": "s1", "hash": "h1", "closeHook": "她终于问出了那句话"}
        ],
    )
    out = analyze_novel_craft(with_hook)
    scores = {row["chapterId"]: row for row in out["hookScores"]}
    assert set(scores) == {"s1", "f1"}

    suspense, flat = scores["s1"], scores["f1"]
    assert suspense["score"] >= 0.7
    assert suspense["level"] == "strong"
    assert flat["score"] <= 0.35
    assert flat["level"] == "weak"
    assert suspense["score"] - flat["score"] >= 0.3  # 必须"可区分"
    assert suspense["endingKind"] == "dialogue"
    assert suspense["ledgerCloseHook"] == "她终于问出了那句话"
    assert suspense["hookSource"] == "chapterIndex"


def test_hook_score_is_a_heuristic_with_explicit_basis():
    out = analyze_novel_craft(_project([_ch("s1", SUSPENSE_BLOCKS)]))
    hook = out["hookScores"][0]
    assert hook["heuristic"] is True
    assert "启发式" in hook["disclaimer"]
    assert "不是文学判断" in hook["disclaimer"]
    keys = [c["key"] for c in hook["components"]]
    assert keys == ["endingKind", "endingLength", "endingPunctuation", "ledgerHook"]
    for comp in hook["components"]:
        assert comp["basis"]  # 每一项都要能说清依据
        assert 0.0 <= float(comp["value"]) <= 1.0
        assert float(comp["weight"]) > 0
        assert comp["weighted"] == round(float(comp["weight"]) * float(comp["value"]), 4)
    assert sum(HOOK_WEIGHTS.values()) == pytest.approx(1.0)
    assert hook["score"] == pytest.approx(
        sum(c["weighted"] for c in hook["components"]), abs=1e-4
    )


def test_suspense_narration_ending_beats_plain_narration_ending():
    """末段是叙述时也要区分"悬念句"与"平淡收束"：这是要求里的 (a) 项。"""
    suspense = score_chapter_hook([ProseUnit(KIND_NARRATION, "门开了，站在那里的竟然是——")])
    flat = score_chapter_hook([ProseUnit(KIND_NARRATION, "他关上门，然后去睡觉了。")])
    assert suspense["score"] > flat["score"]
    assert suspense["components"][0]["value"] == 0.7
    assert "悬念句" in suspense["components"][0]["basis"]
    assert flat["components"][0]["value"] == 0.4


def test_hook_score_is_deterministic_for_the_same_input():
    units = [ProseUnit(KIND_NARRATION, "雨声渐密。"), ProseUnit(KIND_DIALOGUE, "……难道是你？")]
    first = score_chapter_hook(
        units, close_hook="她问出了那句话", hook_source="chapterIndex", chapter_id="c1"
    )
    second = score_chapter_hook(
        units, close_hook="她问出了那句话", hook_source="chapterIndex", chapter_id="c1"
    )
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
    # 整个分析入口也必须纯确定性
    project = _project([_ch("c1", SUSPENSE_BLOCKS)])
    assert json.dumps(
        analyze_novel_craft(project), ensure_ascii=False, sort_keys=True
    ) == json.dumps(analyze_novel_craft(project), ensure_ascii=False, sort_keys=True)


def test_ledger_close_hook_component_changes_the_score():
    chapters = [_ch("s1", SUSPENSE_BLOCKS)]
    without = analyze_novel_craft(_project(chapters, chapter_index=[]))["hookScores"][0]
    with_hook = analyze_novel_craft(
        _project(
            chapters,
            chapter_index=[
                {"chapterId": "s1", "title": "s1", "hash": "h1", "closeHook": "她终于问出了那句话"}
            ],
        )
    )["hookScores"][0]
    assert without["hookSource"] == "none"
    assert without["ledgerCloseHook"] is None
    assert with_hook["score"] > without["score"]
    assert with_hook["score"] - without["score"] == pytest.approx(
        HOOK_WEIGHTS["ledgerHook"], abs=1e-3
    )
    # 这一项量的是"记账完整度"，依据里必须说清楚
    ledger_component = without["components"][3]
    assert "closeHook" in ledger_component["basis"]


def test_hook_score_reads_close_hook_from_writing_ledger_too():
    project = VnProject.model_validate(
        {
            "id": "p",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "chapters": [_ch("s1", SUSPENSE_BLOCKS)],
            "writingLedger": {
                "chapterFacts": [
                    {"chapterId": "s1", "title": "s1", "facts": ["收束钩：她终于问出了那句话"]}
                ]
            },
        }
    )
    hook = analyze_novel_craft(project)["hookScores"][0]
    assert hook["hookSource"] == "writingLedger"
    assert hook["ledgerCloseHook"] == "她终于问出了那句话"


# ------------------------------------------------------------- 空输入与覆盖率


def test_empty_project_does_not_raise():
    empty = VnProject.model_validate(
        {"id": "p", "title": "t", "updatedAt": "2026-01-01T00:00:00+00:00", "chapters": []}
    )
    out = analyze_novel_craft(empty)
    assert out["perChapter"] == []
    assert out["hookScores"] == []
    assert out["rubyIssues"] == []
    assert out["rubyConsistency"] == []
    assert out["summary"]
    assert out["notes"]
    assert out["coverage"]["chaptersTotal"] == 0
    assert out["coverage"]["chaptersAnalyzed"] == 0
    assert out["coverage"]["truncated"] is False


def test_empty_and_structure_only_chapters_do_not_raise():
    project = _project(
        [
            _ch("c1", [{"type": "label", "id": "start", "name": "start"}]),
            _ch("c2", []),
            _ch("c3", [_n("   "), {"type": "scene", "image": "bg room"}]),
        ]
    )
    out = analyze_novel_craft(project)
    assert len(out["perChapter"]) == 3
    for row in out["perChapter"]:
        assert row["source"] == "empty"
        assert row["words"]["total"] == 0
        assert row["words"]["chars"] == 0
        assert row["ratio"]["dialogue"] is None  # 没有正文 ≠ 占比 0%
        assert row["ratio"]["narration"] is None
        assert row["paragraphs"]["avgChars"] is None
        assert row["ruby"]["per1000Chars"] is None
        assert row["onomatopoeia"]["per1000Chars"] is None
        assert row["hook"]["level"] == "empty"
        assert row["hook"]["score"] == 0.0
        assert row["hook"]["heuristic"] is True
    assert out["coverage"]["emptyChapters"] == ["c1", "c2", "c3"]
    assert out["coverage"]["truncated"] is False


def test_unknown_chapter_filter_is_reported_not_raised():
    out = analyze_novel_craft(_project([_ch("c1", SUSPENSE_BLOCKS)]), chapter_id="nope")
    assert out["perChapter"] == []
    assert out["coverage"]["missingChapterId"] == "nope"
    assert out["coverage"]["chapterIdFilter"] == "nope"
    assert out["coverage"]["chaptersTotal"] == 1
    assert "未找到章节" in out["coverage"]["note"]


def test_coverage_reports_scope_filter_and_truncation_honestly():
    chapters = [
        _ch("c1", [_n("第一章的正文写了不少字，足够触发单章上限。")]),
        _ch("c2", [_n("第二章的正文也写了一些字。")]),
        _ch("c3", [_n("第三章正文。")]),
    ]
    project = _project(chapters)

    full = analyze_novel_craft(project)
    assert full["coverage"]["chaptersTotal"] == 3
    assert full["coverage"]["chaptersAnalyzed"] == 3
    assert full["coverage"]["truncated"] is False
    assert full["coverage"]["chaptersSkipped"] == []

    capped = analyze_novel_craft(project, max_chapters=2)
    assert capped["coverage"]["chaptersAnalyzed"] == 2
    assert capped["coverage"]["chaptersSkipped"] == ["c3"]
    assert capped["coverage"]["truncated"] is True
    assert [r["chapterId"] for r in capped["perChapter"]] == ["c1", "c2"]

    cut = analyze_novel_craft(project, max_chapter_chars=5)
    assert cut["coverage"]["truncated"] is True
    assert cut["coverage"]["truncatedChapters"] == ["c1", "c2"]
    assert cut["perChapter"][0]["truncated"] is True
    assert cut["perChapter"][0]["words"]["total"] <= 5
    assert cut["coverage"]["wordsScanned"] <= cut["coverage"]["perChapterWordCap"] * 3

    one = analyze_novel_craft(project, chapter_id="c2")
    assert [r["chapterId"] for r in one["perChapter"]] == ["c2"]
    assert one["perChapter"][0]["chapterIndex"] == 1  # 仍是全书里的第 2 章
    assert one["coverage"]["chaptersTotal"] == 3
    assert one["coverage"]["chaptersAnalyzed"] == 1
    assert one["coverage"]["chapterIdFilter"] == "c2"
    assert one["coverage"]["truncated"] is False
    assert "按 chapter_id 过滤" in one["coverage"]["note"]


# ------------------------------------------------------------- 相对比较与结论


def test_relative_hint_says_it_is_relative_and_needs_enough_chapters():
    calm = _n("他安静地坐着，看着窗外的雨。")
    hot = _n("ドキドキ哗啦咕噜砰咚咚啪嗒沙沙嗡嗡咔嚓")
    chapters = [_ch("c1", [calm]), _ch("c2", [calm]), _ch("c3", [calm]), _ch("c4", [hot])]
    out = analyze_novel_craft(_project(chapters))

    heavy = out["perChapter"][3]
    rel = heavy["relative"]["onomatopoeiaPer1000"]
    assert rel["level"] == "high"
    assert "相对" in rel["hint"]
    assert "不是好坏判断" in rel["hint"]

    # 其余章都是 0：低于绝对下限就不提示（"1 个感叹号 vs 0 个"不值得报警）
    assert "onomatopoeiaPer1000" not in out["perChapter"][0]["relative"]

    # 章数太少时不做相对比较
    pair = analyze_novel_craft(_project([_ch("c1", [calm]), _ch("c2", [hot])]))
    assert pair["perChapter"][0]["relative"] == {}
    assert pair["perChapter"][1]["relative"] == {}


def test_summary_and_notes_are_author_facing():
    out = analyze_novel_craft(_project([_ch("c1", SUSPENSE_BLOCKS)]))
    assert out["summary"].endswith("。")
    assert "启发式" in out["summary"]
    assert "非文学判断" in out["summary"]
    assert any("启发式" in n for n in out["notes"])
    assert any("相对" in n for n in out["notes"])
    assert any("不完整" in n for n in out["notes"])  # 词表不完整要写明
    assert out["coverage"]["note"] in out["notes"]
