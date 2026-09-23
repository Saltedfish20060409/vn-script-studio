"""轻小说文体一致性：表记（确定性）与视角/称呼（启发式）。

测试只断言**语义**：该检出的检出、该放过的放过、coverage 如实。
不锁死具体条数或阈值常量——那些是调参的自由度，不是契约。
"""

from __future__ import annotations

from app.core.novel_consistency import analyze_novel_consistency
from app.core.project import normalize_project
from app.domain.types import VnProject

LINXIA = {
    "id": "c1",
    "defineName": "linxia",
    "displayName": "林夏",
    "aliases": ["小夏", "阿夏"],
}
LURAN = {"id": "c2", "defineName": "luran", "displayName": "陆然"}


def _proj(chapters, characters=None, lore=None):  # noqa: ANN001
    return normalize_project(
        {
            "id": "p1",
            "title": "测试作品",
            "characters": characters or [],
            "loreEntries": lore or [],
            "chapters": chapters,
        }
    )


def _prose(cid, title, prose, **extra):  # noqa: ANN001
    return {"id": cid, "title": title, "prose": prose, **extra}


def _codes(out):  # noqa: ANN001
    return [str(i["code"]) for i in out["issues"]]


def _of(out, code):  # noqa: ANN001
    return [i for i in out["issues"] if str(i["code"]) == code]


# --------------------------------------------------------------- A 组：表记


def test_detects_halfwidth_punctuation_inside_chinese():
    bad = analyze_novel_consistency(_proj([_prose("ch1", "第一章", "你好,世界。")]))
    assert "punct_halfwidth_near_cjk" in _codes(bad)
    issue = _of(bad, "punct_halfwidth_near_cjk")[0]
    assert issue["chapterId"] == "ch1"
    assert issue["chapterTitle"] == "第一章"
    assert issue["message"]
    # 原样引用片段：作者要能据此定位
    assert "你好,世界" in issue["quote"] or "你好,世界" in issue["message"]

    good = analyze_novel_consistency(_proj([_prose("ch1", "第一章", "你好，世界。")]))
    assert "punct_halfwidth_near_cjk" not in _codes(good)


def test_detects_half_and_full_width_punctuation_adjacent():
    out = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "真的吗,。他说：走！?")])
    )
    assert "punct_half_full_adjacent" in _codes(out)


def test_detects_digit_and_letter_width_mixing():
    mixed = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "第1章写到２０２４年。他说ＡI和AI不一样。")])
    )
    codes = _codes(mixed)
    assert "digit_width_mixed" in codes
    assert "letter_width_mixed" in codes

    uniform = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "第1章写到2024年。他说AI很厉害。")])
    )
    assert "digit_width_mixed" not in _codes(uniform)
    assert "letter_width_mixed" not in _codes(uniform)


def test_detects_space_inside_known_name():
    out = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "林 夏笑了笑，又把伞递过来。")], characters=[LINXIA])
    )
    assert "name_spaced_variant" in _codes(out)
    assert "林 夏" in _of(out, "name_spaced_variant")[0]["quote"]

    # 全角空格与间隔号同样算
    mid = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "林·夏笑了笑。")], characters=[LINXIA])
    )
    assert "name_spaced_variant" in _codes(mid)


def test_detects_unbalanced_quotes_and_accepts_balanced():
    bad = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "「你来了。他说完就走了。")])
    )
    issues = _of(bad, "quote_unbalanced")
    assert issues, "未闭合的开引号必须报出来"
    assert issues[0]["severity"] == "error"

    good = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "「你来了。」他说完就走了。")])
    )
    assert "quote_unbalanced" not in _codes(good)


def test_detects_dash_and_ellipsis_variants():
    bad = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "他走了--然后回头。他停了—很久。他说...算了。")])
    )
    codes = _codes(bad)
    assert "dash_ascii_double" in codes
    assert "dash_single_em" in codes
    assert "ellipsis_ascii_dots" in codes

    good = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "他走了——然后回头。他说……算了。")])
    )
    codes = _codes(good)
    for code in ("dash_ascii_double", "dash_single_em", "ellipsis_ascii_dots"):
        assert code not in codes


def test_detects_ellipsis_style_mixing():
    mixed = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "他说……算了。她又说...没事。")])
    )
    assert "ellipsis_style_mixed" in _codes(mixed)

    uniform = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "他说……算了。她又说……没事。")])
    )
    assert "ellipsis_style_mixed" not in _codes(uniform)


def test_block_project_does_not_report_renderer_markers():
    """脚本工程：`_blocks_to_plain` 渲染出的 `旁白: ` 与 `条件(...)` 不是作者的文字。

    这是本模块分两份文本视图的原因；若把渲染结果当成作者原文，
    `旁白: ` 的冒号与条件里的括号会被报成"半角标点混用"，那是纯粹的误报。
    """
    blocks = [
        {"type": "label", "id": "l1", "name": "start"},
        {"type": "narration", "text": "雨还在下。"},
        {"type": "dialogue", "characterId": "c1", "text": "「你来了。」"},
        {
            "type": "if",
            "branches": [
                {
                    "condition": "好感度 >= 3",
                    "blocks": [{"type": "narration", "text": "她笑了。"}],
                }
            ],
        },
    ]
    out = analyze_novel_consistency(
        _proj([{"id": "ch1", "title": "第一章", "blocks": blocks}], characters=[LINXIA])
    )
    assert [i for i in out["issues"] if i["category"] == "typography"] == []


# ----------------------------------------------------------- A 组：人名变体


def test_detects_name_char_variant():
    prose = "林夏走进教室。林霞坐在窗边。林霞抬起头看了看她。"
    out = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", prose)], characters=[LINXIA])
    )
    issues = _of(out, "name_char_variant")
    assert issues, "与角色名只差一个字、且同章并存的写法应被检出"
    assert issues[0]["evidence"]["candidate"] == "林霞"
    assert issues[0]["evidence"]["knownName"] == "林夏"


def test_known_aliases_are_never_flagged_as_variants():
    prose = "小夏走进教室。小夏抬起头。阿夏在窗边等着。林夏笑了。"
    out = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", prose)], characters=[LINXIA])
    )
    assert _of(out, "name_char_variant") == []
    assert _of(out, "name_char_variant_suspect") == []


def test_lore_entry_titles_count_as_known_names():
    prose = "圣痕学院的门开了。圣痕学园的学生们涌了出来。圣痕学园很旧。圣痕学院也是。"
    out = analyze_novel_consistency(
        _proj(
            [_prose("ch1", "第一章", prose)],
            lore=[{"id": "e1", "title": "圣痕学院", "keywords": ["学院"]}],
        )
    )
    issues = _of(out, "name_char_variant")
    assert issues, "世界观条目名也应作为已知写法参与比对"
    assert issues[0]["evidence"]["knownName"] == "圣痕学院"


# ---------------------------------------------------------------- B 组：视角


def test_detects_pov_shift_and_gives_counts():
    first_a = (
        "我推开教室的门。我看见林夏坐在窗边。我走过去，问那个人为什么一个人在这里。"
        "没有回答。我又问了一次，还是没有回应。我只好在旁边坐下。我等着。"
    )
    first_b = (
        "我看着窗外的雨。我想起昨天说过的话。我知道没有人会回答我。我把书包放在桌上。"
        "我等了很久。我又看了一眼窗外。我决定再等一会儿。"
    )
    third = (
        "林夏推开教室的门。她看见窗边坐着一个人。他抬起头，朝林夏笑了笑。"
        "林夏没有回答。她把书包放在桌上。他站起来，走到林夏面前。"
    )
    out = analyze_novel_consistency(
        _proj(
            [
                _prose("ch1", "第一章", first_a),
                _prose("ch2", "第二章", first_b),
                _prose("ch3", "第三章", third),
            ],
            characters=[LINXIA, LURAN],
        )
    )
    issues = _of(out, "pov_shift")
    assert issues, "全书主导第一人称里混进第三人称章节应被检出"
    issue = issues[0]
    assert issue["chapterId"] == "ch3"
    evidence = issue["evidence"]
    assert evidence["heuristic"] is True
    # 计数依据：本章第三人称多于第一人称，且全书第一人称占优
    assert evidence["chapterThirdPerson"] > evidence["chapterFirstPerson"]
    assert evidence["bookFirstPerson"] > evidence["bookThirdPerson"]
    assert out["pov"]["dominant"] == "first"
    assert out["pov"]["chapters"][2]["pov"] == "third"


def test_single_chapter_project_has_no_pov_verdict():
    out = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", "我推开门。我看见她在窗边。我走过去，问她为什么。")])
    )
    assert _of(out, "pov_shift") == []


# -------------------------------------------------------------- B 组：称呼


def _dialogue_chapter(cid, title, lines):  # noqa: ANN001
    return {
        "id": cid,
        "title": title,
        "blocks": [
            {"type": "dialogue", "characterId": who, "text": text} for who, text in lines
        ],
    }


def test_detects_address_level_drift_as_heuristic():
    chapters = [
        _dialogue_chapter("ch1", "第一章", [("c2", "您今天来得真早。"), ("c1", "嗯。")]),
        _dialogue_chapter("ch2", "第二章", [("c2", "你今天来得真早。"), ("c1", "嗯。")]),
        _dialogue_chapter("ch3", "第三章", [("c2", "您今天来得真早。"), ("c1", "嗯。")]),
    ]
    out = analyze_novel_consistency(_proj(chapters, characters=[LINXIA, LURAN]))
    issues = _of(out, "address_level_drift")
    assert issues, "先「您」后「你」再回「您」应被检出"
    issue = issues[0]
    evidence = issue["evidence"]
    assert evidence["heuristic"] is True
    assert "启发式" in issue["message"]
    assert evidence["levelRepeats"] is True
    # 按章序给出演变（这就是作者据以判断的"依据"）
    assert [t["level"] for t in evidence["timeline"]] == ["polite", "plain", "polite"]
    assert [t["chapterId"] for t in evidence["timeline"]] == ["ch1", "ch2", "ch3"]


def test_consistent_address_usage_is_not_flagged():
    chapters = [
        _dialogue_chapter(cid, f"第{n}章", [("c2", "您今天来得真早。"), ("c1", "嗯。")])
        for n, cid in enumerate(["ch1", "ch2", "ch3"], start=1)
    ]
    out = analyze_novel_consistency(_proj(chapters, characters=[LINXIA, LURAN]))
    assert _of(out, "address_level_drift") == []


# ------------------------------------------------------------------ 边界与口径


def test_empty_project_reports_honestly_without_raising():
    empty = VnProject(id="p0", title="空作品", updatedAt="2024-01-01T00:00:00Z")
    out = analyze_novel_consistency(empty)
    assert out["issues"] == []
    assert out["coverage"]["chaptersTotal"] == 0
    assert out["coverage"]["truncated"] is False
    assert "没有章节" in out["summary"]
    assert out["notes"], "启发式与已知边界必须写在 notes 里"


def test_chapters_without_author_text_are_not_counted_as_scanned():
    chapters = [
        {"id": "ch1", "title": "第一章", "blocks": [{"type": "label", "id": "l", "name": "start"}]}
    ]
    out = analyze_novel_consistency(_proj(chapters))
    assert out["issues"] == []
    assert out["coverage"]["chaptersScanned"] == 0
    assert out["coverage"]["chaptersWithoutText"] == ["ch1"]
    assert "没有可检查" in out["summary"]


def test_coverage_reports_issue_truncation():
    chapters = [
        _prose(f"ch{n}", f"第{n}章", f"「未闭合的第{n}章。你好,世界。")
        for n in range(1, 5)
    ]
    full = analyze_novel_consistency(_proj(chapters))
    assert full["coverage"]["issuesFound"] > 1

    capped = analyze_novel_consistency(_proj(chapters), max_issues=1)
    coverage = capped["coverage"]
    assert len(capped["issues"]) == 1
    assert coverage["issuesReported"] == 1
    assert coverage["issuesTruncated"] == coverage["issuesFound"] - 1
    assert coverage["truncated"] is True
    # counts 统计的是**全部检出**（截断前），否则作者看不到真实规模
    assert capped["counts"]["total"] == coverage["issuesFound"]
    assert "max_issues" in capped["summary"]


def test_coverage_reports_chapter_text_truncation():
    long_prose = "我走了一步。" * 2000
    out = analyze_novel_consistency(
        _proj([_prose("ch1", "第一章", long_prose)]), chapter_char_cap=200
    )
    coverage = out["coverage"]
    assert "ch1" in coverage["textTruncatedChapters"]
    assert coverage["truncated"] is True
    assert any("上限" in note for note in out["notes"])


def test_focus_limits_scope_and_reports_dropped_chapters():
    chapters = [
        _prose("ch1", "第一章", "你好,世界。"),
        _prose("ch2", "第二章", "你好,世界。"),
    ]
    out = analyze_novel_consistency(_proj(chapters), focus="第二章")
    assert out["coverage"]["focusApplied"] is True
    assert out["coverage"]["focusDroppedChapters"] == ["ch1"]
    assert out["issues"]
    assert all(i["chapterId"] == "ch2" for i in out["issues"])

    none = analyze_novel_consistency(_proj(chapters), focus="不存在的标题")
    assert none["coverage"]["chaptersScanned"] == 0
    assert none["issues"] == []
    assert none["coverage"]["focusDroppedChapters"] == ["ch1", "ch2"]


def test_issue_shape_is_complete():
    out = analyze_novel_consistency(
        _proj(
            [_prose("ch1", "第一章", "「未闭合。你好,世界。他走了--然后回头。")],
            characters=[LINXIA],
        )
    )
    assert out["issues"]
    for issue in out["issues"]:
        assert issue["severity"] in ("error", "warn", "info")
        assert issue["code"]
        assert issue["message"]
        assert issue["chapterId"] == "ch1"
        assert issue["chapterTitle"] == "第一章"
    assert set(out["counts"]["bySeverity"]) == {"error", "warn", "info"}
    assert out["counts"]["total"] == len(out["issues"])
    assert "byCode" in out["counts"]


def test_result_is_deterministic():
    chapters = [
        _prose("ch1", "第一章", "「未闭合。你好,世界。他走了--然后回头。"),
        _prose("ch2", "第二章", "我推开门。我看见她在窗边。我走过去。"),
    ]
    first = analyze_novel_consistency(_proj(chapters, characters=[LINXIA]))
    second = analyze_novel_consistency(_proj(chapters, characters=[LINXIA]))
    assert first["issues"] == second["issues"]
    assert first["counts"] == second["counts"]
    assert first["coverage"] == second["coverage"]
