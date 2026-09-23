"""故事层指标测试：伏笔回收率 与 情感弧线。

重点验证两件容易写错的事：
1. **没有伏笔时不能报"回收率 0%"**——那是把"无从谈起"说成了"做得很差"；
2. 情感推断**真的在推断**，而不是恒返回默认值。后者尤其危险：一个恒返回「平静」的
   量具会让作者以为"全篇情绪平稳"，比没有量具更糟（写实现时确实踩到过这个坑）。
"""

from __future__ import annotations

from app.core.project import normalize_project
from app.core.story_metrics import (
    analyze_story_metrics,
    declared_arc_mismatches,
    emotion_arcs,
    foreshadow_resolution,
)


def _d(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def _ch(cid: str, blocks: list) -> dict:
    return {"id": cid, "title": cid, "blocks": blocks}


def _project(chapters: list, *, characters: list | None = None, ledger: dict | None = None):
    data = {
        "id": "p1",
        "title": "故事指标",
        "characters": characters
        or [
            {"id": "lin", "defineName": "lin", "displayName": "林夏"},
            {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
        ],
        "chapters": chapters,
    }
    if ledger is not None:
        data["writingLedger"] = ledger
    return normalize_project(data)


# ------------------------------------------------------------------ 伏笔回收


def test_no_foreshadows_means_no_rate_not_zero_percent():
    """分母为 0 时必须返回 None：没有伏笔 ≠ 回收率 0%。"""
    out = foreshadow_resolution(_project([_ch("c1", [{"type": "return"}])]))
    assert out["total"] == 0
    assert out["resolutionRate"] is None
    assert "还没有记录任何伏笔" in out["note"]


def test_resolution_rate_counts_paid_over_total():
    ledger = {
        "foreshadows": [
            {"id": "f1", "hook": "伞", "status": "paid", "plantedChapter": "c1", "paidInChapter": "c3"},
            {"id": "f2", "hook": "车票", "status": "open", "plantedChapter": "c2"},
            {"id": "f3", "hook": "照片", "status": "open", "plantedChapter": "c1"},
            {"id": "f4", "hook": "信", "status": "paid", "plantedChapter": "c2", "paidInChapter": "c4"},
        ]
    }
    project = _project(
        [_ch(f"c{i}", [{"type": "return"}]) for i in range(1, 5)], ledger=ledger
    )
    out = foreshadow_resolution(project)
    assert out["total"] == 4
    assert out["paid"] == 2
    assert out["open"] == 2
    assert out["resolutionRate"] == 0.5


def test_open_hooks_are_sorted_by_age_and_use_the_ledger_age():
    """"挂了多久"必须直接用账本的 ageChapters，不能自己重算。"""
    ledger = {
        "foreshadows": [
            {"id": "new", "hook": "刚埋的", "status": "open", "plantedChapter": "c3"},
            {"id": "old", "hook": "埋很久的", "status": "open", "plantedChapter": "c1"},
        ]
    }
    project = _project(
        [_ch(f"c{i}", [{"type": "return"}]) for i in range(1, 5)], ledger=ledger
    )
    out = foreshadow_resolution(project)
    assert [h["hook"] for h in out["openHooks"]] == ["埋很久的", "刚埋的"]
    assert out["openHooks"][0]["chaptersOpen"] == 3
    assert out["oldestOpenChapters"] == 3
    assert out["openHooks"][0]["plantedChapterTitle"] == "c1"


def test_low_resolution_is_reported_as_warning():
    ledger = {
        "foreshadows": [
            {"id": "f1", "hook": "伞", "status": "open", "plantedChapter": "c1"},
            {"id": "f2", "hook": "票", "status": "open", "plantedChapter": "c1"},
            {"id": "f3", "hook": "信", "status": "open", "plantedChapter": "c1"},
            {"id": "f4", "hook": "光", "status": "paid", "plantedChapter": "c1", "paidInChapter": "c2"},
        ]
    }
    project = _project(
        [_ch(f"c{i}", [{"type": "return"}]) for i in range(1, 4)], ledger=ledger
    )
    out = analyze_story_metrics(project)
    codes = [f["code"] for f in out["findings"]]
    assert "foreshadow_low_resolution" in codes


def test_high_resolution_is_not_reported():
    ledger = {
        "foreshadows": [
            {"id": "f1", "hook": "a", "status": "paid", "plantedChapter": "c1", "paidInChapter": "c2"},
            {"id": "f2", "hook": "b", "status": "paid", "plantedChapter": "c1", "paidInChapter": "c2"},
        ]
    }
    project = _project([_ch("c1", [{"type": "return"}] * 1)], ledger=ledger)
    out = analyze_story_metrics(project)
    assert "foreshadow_low_resolution" not in [f["code"] for f in out["findings"]]


# ------------------------------------------------------------------ 情感弧线


def test_emotion_inference_actually_reacts_to_words():
    """回归闸：情绪推断不能恒返回默认值。"""
    raging = _project(
        [
            _ch(
                "c1",
                [_d("lin", t) for t in ("混蛋！", "该死！", "你怎么能这样！")],
            )
        ]
    )
    calm = _project([_ch("c1", [_d("lin", t) for t in ("嗯。", "好。", "知道了。")])])
    hot = emotion_arcs(raging)["characters"]
    cool = emotion_arcs(calm)["characters"]
    assert hot and cool
    assert hot[0]["end"] == "激动", hot
    assert cool[0]["end"] == "平静", cool


def test_rising_arc_is_detected():
    texts = ["嗯。", "好。", "我知道了。", "随便你。", "混蛋！", "你给我站住！"]
    project = _project([_ch("c1", [_d("lin", t) for t in texts])])
    row = emotion_arcs(project)["characters"][0]
    assert row["start"] == "平静"
    assert row["end"] == "激动"
    assert row["delta"] > 0


def test_single_line_character_is_skipped():
    """一句话推不出弧线——宁可不报，也不要编一个。"""
    project = _project([_ch("c1", [_d("lin", "嗯。")])])
    assert emotion_arcs(project)["characters"] == []


def test_flat_arc_is_listed_as_info_not_error():
    project = _project([_ch("c1", [_d("lin", t) for t in ("嗯。", "好。", "知道了。", "行。")])])
    out = analyze_story_metrics(project)
    flat_codes = [f["code"] for f in out["findings"] if f["code"] == "emotion_arc_flat"]
    assert flat_codes
    assert all(f["severity"] == "info" for f in out["findings"] if f["code"] == "emotion_arc_flat")


# ------------------------------------------------------ 与节拍表声明对账


def test_declared_arc_that_never_happens_is_reported():
    """节拍表说"从平静走到愤怒"，实际全篇平静 → 必须报出来。"""
    project = _project([_ch("c1", [_d("lin", t) for t in ("嗯。", "好。", "知道了。", "行。")])])
    sheet = {"emotionStart": {"林夏": "平静"}, "emotionEnd": {"林夏": "愤怒"}}
    out = declared_arc_mismatches(project, [sheet])
    assert out and out[0]["issue"] == "arc_flat"
    assert "林夏" in out[0]["message"]


def test_reversed_arc_is_reported():
    """实际情绪是**往下走**（激动→平静），而节拍表声明往上走 → 方向相反。"""
    lines = ["混蛋！", "你给我站住！", "算了。", "嗯。", "好。", "知道了。"]
    project = _project([_ch("c1", [_d("lin", t) for t in lines])])
    sheet = {"emotionStart": {"林夏": "平静"}, "emotionEnd": {"林夏": "愤怒"}}
    out = declared_arc_mismatches(project, [sheet])
    assert out and out[0]["issue"] == "arc_reversed", out


def test_flat_actual_arc_is_reported_as_flat_not_reversed():
    """声明有变化、实际一点没变 → 是"没写出来"（arc_flat），不是"写反了"。"""
    project = _project(
        [_ch("c1", [_d("lin", t) for t in ("混蛋！", "该死！", "你给我站住！")])]
    )
    sheet = {"emotionStart": {"林夏": "激动"}, "emotionEnd": {"林夏": "冷静"}}
    out = declared_arc_mismatches(project, [sheet])
    assert out and out[0]["issue"] == "arc_flat", out


def test_unrecognised_emotion_words_are_not_guessed():
    """节拍表里的词对不上就**不猜**：硬映射只会造假警报。"""
    project = _project([_ch("c1", [_d("lin", t) for t in ("嗯。", "好。", "知道了。")])])
    sheet = {"emotionStart": {"林夏": "微妙"}, "emotionEnd": {"林夏": "说不清"}}
    assert declared_arc_mismatches(project, [sheet]) == []


def test_mismatch_skips_characters_absent_from_the_draft():
    project = _project([_ch("c1", [_d("lin", t) for t in ("嗯。", "好。", "知道了。")])])
    sheet = {"emotionStart": {"周屿": "平静"}, "emotionEnd": {"周屿": "愤怒"}}
    assert declared_arc_mismatches(project, [sheet]) == []


def test_empty_project_is_safe():
    project = normalize_project({"id": "p", "title": "空"})
    out = analyze_story_metrics(project)
    assert out["foreshadow"]["resolutionRate"] is None
    assert out["emotionArcs"]["characters"] == []
    assert out["counts"]["warn"] == 0


# -------------------------------------------------------------- 逐章情绪走向
# 整部作品级的弧线答不出"哪一章把他写反了"，而后者才是作者能直接改的东西。
# 这一节的夹具刻意构造成：全篇往上走，但中间有一章掉下来。


def _arc_break_project():
    """林夏：ch1 平静 → ch2 从激动掉到平静（写反）→ ch3 激动。
    全篇 平静 → 激动（+4，往上走），ch2 局部是 -4（往下）→ 应被报为弧线断裂。
    """
    return _project(
        [
            _ch("ch1", [_d("lin", "嗯。"), _d("lin", "好。")]),
            _ch("ch2", [_d("lin", "混蛋！"), _d("lin", "该死！"), _d("lin", "算了。"), _d("lin", "嗯。")]),
            _ch("ch3", [_d("lin", "你给我站住！"), _d("lin", "别走！")]),
        ]
    )


def test_chapter_emotion_rows_are_per_character_and_chapter():
    from app.core.story_metrics import chapter_emotion_rows

    rows = chapter_emotion_rows(_arc_break_project())
    assert [r["chapterId"] for r in rows] == ["ch1", "ch2", "ch3"]
    assert all(r["character"] == "林夏" for r in rows)
    assert rows[0]["start"] == "平静" and rows[0]["end"] == "平静"
    assert rows[1]["start"] == "激动" and rows[1]["end"] == "平静"
    assert rows[1]["delta"] == -4
    assert rows[2]["delta"] == 0


def test_chapter_with_a_single_line_is_not_judged():
    """一章只说一句推不出走向；拿单句判"写反了"只会造假警报。"""
    from app.core.story_metrics import chapter_emotion_rows

    project = _project(
        [
            _ch("ch1", [_d("lin", "嗯。"), _d("lin", "好。")]),
            _ch("ch2", [_d("lin", "混蛋！")]),
        ]
    )
    assert [r["chapterId"] for r in chapter_emotion_rows(project)] == ["ch1"]


def test_local_reversal_against_the_overall_arc_is_reported():
    from app.core.story_metrics import emotion_arc_breaks

    out = emotion_arc_breaks(_arc_break_project())
    assert len(out["breaks"]) == 1
    brk = out["breaks"][0]
    assert brk["chapterId"] == "ch2"
    assert brk["character"] == "林夏"
    assert brk["issue"] == "emotion_arc_break"
    assert brk["chapterDelta"] * brk["overallDelta"] < 0
    assert "ch2" in brk["message"]


def test_chapter_that_follows_the_overall_arc_is_not_reported():
    """ch3 也是「往下」之前先往上——局部与全篇同向，不该报。"""
    from app.core.story_metrics import emotion_arc_breaks

    project = _project(
        [
            _ch("ch1", [_d("lin", "嗯。"), _d("lin", "好。")]),
            _ch("ch2", [_d("lin", "算了吧。"), _d("lin", "没事。")]),
        ]
    )
    assert emotion_arc_breaks(project)["breaks"] == []


def test_flat_overall_arc_never_produces_breaks():
    """全篇本来就平 → 不报"局部与全篇相反"（那是 flatArcs 那条提示的事）。"""
    from app.core.story_metrics import emotion_arc_breaks

    project = _project(
        [
            _ch("ch1", [_d("lin", "嗯。"), _d("lin", "好。")]),
            _ch("ch2", [_d("lin", "混蛋！"), _d("lin", "该死！")]),
            _ch("ch3", [_d("lin", "知道了。"), _d("lin", "行。")]),
        ]
    )
    assert emotion_arc_breaks(project)["breaks"] == []


def test_arc_break_finding_carries_chapter_id_for_attribution():
    """断裂必须带 chapterId：前端要能定位，基准也要能按章归因。"""
    out = analyze_story_metrics(_arc_break_project())
    breaks = [f for f in out["findings"] if f["code"] == "emotion_arc_break"]
    assert breaks
    assert breaks[0]["chapterId"] == "ch2"
    assert breaks[0]["severity"] == "warn"
    assert out["emotionArcBreaks"]["breaks"]


# ---------------------------------------------------------- 未回收伏笔逐条
# 单列成 finding 是为了"按章展示"与"在基准里按章归因"；
# 聚合口径（回收率）另有一条 foreshadow_low_resolution 兜底。


def test_each_open_hook_becomes_a_finding_with_its_chapter():
    ledger = {
        "foreshadows": [
            {"id": "f1", "hook": "伞", "status": "open", "plantedChapter": "c1"},
            {"id": "f2", "hook": "信", "status": "paid", "plantedChapter": "c1", "paidInChapter": "c3"},
        ]
    }
    project = _project(
        [_ch(f"c{i}", [{"type": "return"}]) for i in range(1, 4)], ledger=ledger
    )
    out = analyze_story_metrics(project)
    hooks = [f for f in out["findings"] if f["code"] == "foreshadow_unresolved"]
    assert len(hooks) == 1
    assert hooks[0]["chapterId"] == "c1"
    assert "伞" in hooks[0]["message"]
    assert "已过" in hooks[0]["message"]


def test_unresolved_hook_findings_are_capped():
    """几十条未回收时列表会淹没别的建议 → 逐条提示封顶 20。"""
    ledger = {
        "foreshadows": [
            {"id": f"f{i}", "hook": f"钩子{i}", "status": "open", "plantedChapter": "c1"}
            for i in range(30)
        ]
    }
    project = _project([_ch("c1", [{"type": "return"}])], ledger=ledger)
    out = analyze_story_metrics(project)
    hooks = [f for f in out["findings"] if f["code"] == "foreshadow_unresolved"]
    assert len(hooks) == 20
    # 但总量口径不受影响：聚合那条仍然看得见全部 30 条
    assert out["foreshadow"]["total"] == 30
    assert out["foreshadow"]["open"] == 30


# ------------------------------------------- 与运行历史的接线（防"静默死功能"）


def test_run_history_persists_the_beat_sheet():
    """**回归闸**：运行历史必须存下 plan 阶段的节拍表。

    此前这条记录里没有 `beatSheet` 字段，于是 `analysis/story-metrics` 里
    "声明的情感弧线 vs 实际写出来的弧线"那个对账**在生产里永远返回空**——
    一个看着有、其实从不报的功能。只写单元测试测不到这个（函数本身是对的，
    错在没人把数据传进来），所以这里从"写历史"一路测到"能报出对账问题"。
    """
    from app.core.pipeline.run_history import append_harness_run

    project = _project(
        [
            _ch("c1", [_d("lin", "嗯。"), _d("lin", "好。")]),
            _ch("c2", [_d("lin", "知道了。"), _d("lin", "行。")]),
        ]
    )
    sheet = {
        "goal": "让她发火",
        "beats": [{"name": "铺垫", "action": "等待"}],
        "emotionStart": {"林夏": "平静"},
        "emotionEnd": {"林夏": "愤怒"},
        "junk": "不该被存下来",
    }
    stamped = append_harness_run(project, kind="pipeline", beat_sheet=sheet)
    stored = (stamped.harnessRuns or [])[0]["beatSheet"]
    assert stored["emotionEnd"] == {"林夏": "愤怒"}
    assert "junk" not in stored, "只留对账需要的字段，别把整张表塞进每次运行的历史"

    # 端到端：从运行历史取出节拍表喂给 story-metrics，必须真的能报出对账问题
    sheets = [
        r.get("beatSheet")
        for r in (stamped.harnessRuns or [])
        if isinstance(r, dict) and r.get("beatSheet")
    ]
    out = analyze_story_metrics(stamped, beat_sheets=sheets)
    assert out["declaredArcMismatches"], "声明要往上走、实际全篇平静，应当被报出来"
    assert out["declaredArcMismatches"][0]["issue"] == "arc_flat"


def test_run_history_without_a_beat_sheet_stays_clean():
    """没传节拍表时不要凭空造一个空 dict（否则前端会显示一个空的对账区）。"""
    from app.core.pipeline.run_history import append_harness_run

    stamped = append_harness_run(_project([_ch("c1", [{"type": "return"}])]), kind="pipeline")
    assert "beatSheet" not in (stamped.harnessRuns or [])[0]
