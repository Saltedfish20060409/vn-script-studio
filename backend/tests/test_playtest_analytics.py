"""读者行为建模的纯函数单测 —— 无 DB、无网络、无 fixture，可在任何环境跑通。

覆盖（对应交付要求）：
- 选项占比与"从未被选的选项"；
- 章级漏斗递减与最大流失点；
- 结局分布与"没人走到的声明结局"对账；
- 读者侧分支覆盖率（含"静态分析说不可选、玩家却选了"的矛盾）；
- 样本量不足提示；
- 空数据不崩；
- 隐私红线（纯函数层）：未知字段被丢弃、文案类字符串进不了任何字段、
  分析结果里不含任何选项文案。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.services.playtest_telemetry import (
    MIN_SAMPLE_RUNS,
    build_reader_analytics,
    dropped_field_names,
    is_telemetry_enabled,
    missing_choices,
    sanitize_choice,
    sanitize_choices,
    sanitize_client_run_id,
    sanitize_identifier,
    sanitize_run_payload,
)

T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)


# --------------------------------------------------------------- 测试夹具


def _option(index: int, *, condition: str = "", available: bool = True) -> dict:
    return {
        "index": index,
        "text": f"选项文案{index}",  # 故意带文案：分析输出里绝不允许出现它
        "condition": condition,
        "effect": "inline",
        "target": None,
        "varsModified": [],
        "available": available,
    }


def _menu(menu_id: str, chapter: str, label: str, options: list[dict]) -> dict:
    return {
        "chapterId": chapter,
        "label": label,
        "menuId": menu_id,
        "prompt": f"提示语-{menu_id}",
        "choices": options,
        "findings": [],
    }


def _branch() -> dict:
    """一份最小的 branch_analysis 输出（结构照 app/core/branch_analysis.py）。"""
    return {
        "menus": [
            _menu(
                "m1",
                "chA",
                "start",
                [
                    _option(0),
                    _option(1, condition="affection >= 30"),
                    _option(2, condition="never_true_flag == 1", available=False),
                ],
            ),
            _menu("m2", "chB", "mid", [_option(0), _option(1)]),
        ],
        "endings": {
            "declared": [
                {
                    "id": "e1",
                    "name": "真结局",
                    "label": "true_end",
                    "route": "雪见线",
                    "condition": "",
                    "exists": True,
                    "reachable": True,
                },
                {
                    "id": "e2",
                    "name": "坏结局",
                    "label": "bad_end",
                    "route": "雪见线",
                    "condition": "",
                    "exists": True,
                    "reachable": True,
                },
            ],
            "undeclaredTerminals": ["true_end", "bad_end", "silent_end"],
        },
    }


def _run(run_id: str, *, chapters: int = 2, ending: str | None = None) -> dict:
    return {
        "id": run_id,
        "chapter_count": chapters,
        "choice_count": 0,
        "ending_label": ending,
        "started_at": T0,
        "ended_at": T0 + timedelta(minutes=5),
    }


def _choice(run_id: str, seq: int, menu: str, index: int, *, chapter: str = "chA") -> dict:
    return {
        "run_id": run_id,
        "seq": seq,
        "chapter_id": chapter,
        "label": "start",
        "menu_id": menu,
        "choice_index": index,
        "condition_passed": True,
    }


def _analytics(runs, choices, branch=None, order=("chA", "chB")):
    return build_reader_analytics(
        runs, choices, _branch() if branch is None else branch, list(order)
    )


# ------------------------------------------------------------------- 选项占比


def test_option_share_and_never_selected():
    runs = [_run(f"r{i}") for i in range(4)]
    choices = [
        _choice("r0", 0, "m1", 0),
        _choice("r1", 0, "m1", 0),
        _choice("r2", 0, "m1", 1),
        _choice("r3", 0, "m2", 1, chapter="chB"),
    ]
    out = _analytics(runs, choices)
    menus = {m["menuId"]: m for m in out["choices"]["menus"]}

    m1 = menus["m1"]
    assert m1["selections"] == 3
    by_index = {o["index"]: o for o in m1["options"]}
    assert by_index[0]["selected"] == 2
    assert by_index[0]["share"] == round(2 / 3, 4)
    assert by_index[1]["selected"] == 1
    assert by_index[1]["share"] == round(1 / 3, 4)
    # 选项 2 条件恒不成立（available=False）且从没人选
    assert by_index[2]["selected"] == 0
    assert by_index[2]["neverSelected"] is True
    assert by_index[2]["available"] is False
    assert m1["neverSelected"] == [2]
    # m2 只有第 1 项被选过 → 第 0 项是从未被选的选项
    assert menus["m2"]["neverSelected"] == [0]
    assert out["choices"]["totalSelections"] == 4
    assert out["choices"]["observedMenuCount"] == 2


def test_option_share_is_zero_when_menu_never_shown():
    out = _analytics([_run("r0")], [])
    for menu in out["choices"]["menus"]:
        assert menu["selections"] == 0
        for option in menu["options"]:
            assert option["share"] == 0.0
            assert option["neverSelected"] is True


def test_unknown_menu_and_chapter_are_reported_separately():
    runs = [_run("r0")]
    choices = [
        _choice("r0", 0, "m-ghost", 3, chapter="ch-ghost"),
        _choice("r0", 1, "", 1),  # 没有 menu_id → 不可归因
    ]
    out = _analytics(runs, choices)
    assert [m["menuId"] for m in out["choices"]["unknownMenus"]] == ["m-ghost"]
    assert out["choices"]["unknownMenus"][0]["selections"] == 1
    assert out["choices"]["unattributedSelections"] == 1
    assert out["funnel"]["unknownChapters"] == [
        {"chapterId": "ch-ghost", "selections": 1}
    ]
    assert any("menu_id 在剧本里找不到" in n for n in out["notes"])


# --------------------------------------------------------------------- 漏斗


def test_funnel_is_monotonic_and_finds_biggest_drop():
    runs = [
        _run("r0", chapters=2),
        _run("r1", chapters=2),
        _run("r2", chapters=1),
        _run("r3", chapters=0),
        _run("r4", chapters=0),
    ]
    out = _analytics(runs, [])
    chapters = out["funnel"]["chapters"]
    assert [c["chapterId"] for c in chapters] == ["chA", "chB"]
    assert [c["reached"] for c in chapters] == [3, 2]
    reached = [c["reached"] for c in chapters]
    assert reached == sorted(reached, reverse=True)  # 单调不增
    assert chapters[0]["dropFromPrevious"] == 2  # 5 次开始 → 3 次进第一章
    assert chapters[1]["dropFromPrevious"] == 1
    assert out["funnel"]["startedRuns"] == 5
    assert out["funnel"]["biggestDrop"]["chapterId"] == "chA"
    assert out["funnel"]["biggestDrop"]["dropFromPrevious"] == 2
    assert out["funnel"]["deepestChapterId"] == "chB"
    assert chapters[0]["retention"] == round(3 / 5, 4)
    assert any("流失最多的一章" in n for n in out["notes"])


def test_funnel_uses_choice_chapters_when_chapter_count_missing():
    """客户端没上报 chapter_count，也要能从选择记录里看出玩家走到了哪一章。"""
    runs = [_run("r0", chapters=0)]
    choices = [_choice("r0", 0, "m2", 0, chapter="chB")]
    out = _analytics(runs, choices)
    assert [c["reached"] for c in out["funnel"]["chapters"]] == [1, 1]
    assert out["funnel"]["chapters"][1]["choosingRuns"] == 1
    assert out["funnel"]["deepestChapterId"] == "chB"


def test_funnel_falls_back_to_observed_chapters_without_a_script():
    """没有剧本结构（branch=None）时，章节顺序退回观测到的出现顺序。"""
    runs = [_run("r0", chapters=0)]
    choices = [
        _choice("r0", 1, "m1", 0, chapter="chB"),
        _choice("r0", 2, "m1", 1, chapter="chA"),
    ]
    out = build_reader_analytics(runs, choices, None, [])
    assert [c["chapterId"] for c in out["funnel"]["chapters"]] == ["chB", "chA"]
    assert any("剧本结构分析不可用" in n for n in out["notes"])


def test_all_reading_no_choices_is_explained():
    out = _analytics([_run("r0")], [])
    assert out["coverage"]["ratio"] == 0.0
    assert any("纯阅读" in n for n in out["notes"])


# --------------------------------------------------------------------- 结局


def test_ending_distribution_and_declared_never_reached():
    runs = [
        _run("r0", ending="true_end"),
        _run("r1", ending="true_end"),
        _run("r2", ending=None),
    ]
    out = _analytics(runs, [])
    endings = out["endings"]
    assert endings["reached"] == [
        {
            "label": "true_end",
            "name": "真结局",
            "runs": 2,
            "share": round(2 / 3, 4),
            "declared": True,
            "declaredReachable": True,
            "declaredExists": True,
            "isStaticTerminal": True,
        }
    ]
    assert [row["label"] for row in endings["neverReached"]] == ["bad_end"]
    assert endings["neverReached"][0]["name"] == "坏结局"
    assert endings["declaredTotal"] == 2
    assert endings["declaredReached"] == 1
    assert endings["unfinishedRuns"] == 1
    assert any("没有任何玩家走到" in n for n in out["notes"])


def test_undeclared_and_unknown_ending_labels():
    runs = [_run("r0", ending="silent_end"), _run("r1", ending="ghost_end")]
    out = _analytics(runs, [])
    labels = [row["label"] for row in out["endings"]["undeclared"]]
    assert labels == ["ghost_end", "silent_end"]
    # silent_end 是静态分析的终点（只是没登记），ghost_end 连终点都不是
    assert [row["label"] for row in out["endings"]["unknownEndingLabels"]] == ["ghost_end"]
    assert any("既没登记为结局" in n for n in out["notes"])


def test_ending_declared_without_label_is_flagged():
    branch = _branch()
    branch["endings"]["declared"] = [
        {"id": "e9", "name": "无 label 结局", "label": None, "reachable": False, "exists": False}
    ]
    out = build_reader_analytics([_run("r0")], [], branch, ["chA", "chB"])
    assert out["endings"]["declaredTotal"] == 0
    assert out["endings"]["declaredWithoutLabel"] == [{"name": "无 label 结局", "route": ""}]
    assert any("没有 label" in n for n in out["notes"])


def test_endings_note_is_silent_without_any_run():
    """一次试玩都没有时，不该说"没有任何玩家走到"（那是误导）。"""
    out = _analytics([], [])
    assert out["endings"]["neverReached"]  # 声明结局确实都没走到
    assert not any("没有任何玩家走到" in n for n in out["notes"])
    assert any("还没有任何试玩记录" in n for n in out["notes"])


# --------------------------------------------------------------- 读者覆盖率


def test_reader_side_coverage_ratio():
    runs = [_run("r0"), _run("r1")]
    choices = [_choice("r0", 0, "m1", 0), _choice("r1", 0, "m2", 1, chapter="chB")]
    out = _analytics(runs, choices)
    cov = out["coverage"]
    # m1 有 2 个可选（第 3 个 available=False），m2 有 2 个可选 → 4 个可用选项
    assert cov["availableOptions"] == 4
    assert cov["observedOptions"] == 2
    assert cov["ratio"] == 0.5
    assert cov["menusTotal"] == 2
    assert cov["menusTouched"] == 2
    assert cov["menusNeverTouched"] == []


def test_coverage_zero_when_no_menu_exists():
    out = build_reader_analytics([_run("r0")], [_choice("r0", 0, "m1", 0)], None, ["chA"])
    assert out["coverage"]["availableOptions"] == 0
    assert out["coverage"]["ratio"] == 0.0  # 不除零
    assert out["coverage"]["unmappedSelections"] == 1


def test_selected_unavailable_option_is_flagged_as_contradiction():
    runs = [_run("r0")]
    # 玩家选了 index=2，而静态分析认为它恒不可选（condition_passed=False）
    broken = _choice("r0", 0, "m1", 2)
    broken["condition_passed"] = False
    out = _analytics(runs, [broken])
    cov = out["coverage"]
    assert cov["selectedUnavailableOptions"] == [
        {"menuId": "m1", "index": 2, "selections": 1}
    ]
    # 不可选选项不算进"读者走过多少可用选项"
    assert cov["observedOptions"] == 0
    assert out["choices"]["menus"][0]["options"][2]["conditionBlockedSelections"] == 1
    assert any("玩家实际选了它们" in n for n in out["notes"])


# ----------------------------------------------------------------- 运行统计


def test_run_stats_avg_and_median():
    runs = [
        _run("r0", chapters=1),
        _run("r1", chapters=2),
        _run("r2", chapters=3),
    ]
    for run in runs:
        run["choice_count"] = {"r0": 1, "r1": 2, "r2": 6}[run["id"]]
    choices = [
        _choice("r0", 0, "m1", 0),
        _choice("r1", 0, "m1", 0),
        _choice("r1", 1, "m1", 1),
    ]
    out = _analytics(runs, choices)
    stats = out["runs"]
    assert stats["total"] == 3
    assert stats["finished"] == 3
    assert stats["choicesReported"]["avg"] == 3.0
    assert stats["choicesReported"]["median"] == 2.0
    assert stats["choicesObserved"]["avg"] == round(3 / 3, 3)
    assert stats["chaptersPlayed"]["avg"] == 2.0
    assert stats["chaptersPlayed"]["median"] == 2.0
    assert stats["durationSeconds"]["avg"] == 300.0
    # 自报 9 条、库里只有 3 条 → notes 里说明差额
    assert any("客户端自报选择数合计" in n for n in out["notes"])


# --------------------------------------------------------------- 样本量提示


def test_sample_size_note_when_too_few_runs():
    out = _analytics([_run("r0"), _run("r1")], [])
    assert out["sample"] == {
        "runs": 2,
        "choices": 0,
        "minSample": MIN_SAMPLE_RUNS,
        "sufficient": False,
        "truncated": False,
    }
    assert any("样本量不足" in n and "不足以下结论" in n for n in out["notes"])


def test_sample_size_note_when_enough_runs():
    runs = [_run(f"r{i}") for i in range(MIN_SAMPLE_RUNS)]
    out = _analytics(runs, [])
    assert out["sample"]["sufficient"] is True
    assert any("达到统计口径下限" in n for n in out["notes"])
    assert not any("不足以下结论" in n for n in out["notes"])


def test_min_sample_is_configurable():
    runs = [_run(f"r{i}") for i in range(3)]
    out = build_reader_analytics(runs, [], _branch(), ["chA", "chB"], min_sample=3)
    assert out["sample"]["sufficient"] is True


# --------------------------------------------------------------- 空数据不崩


def test_empty_inputs_do_not_crash():
    for branch in (None, {}, {"menus": [], "endings": {}}):
        out = build_reader_analytics([], [], branch, [])
        assert out["sample"]["runs"] == 0
        assert out["funnel"]["chapters"] == []
        assert out["funnel"]["biggestDrop"] is None
        assert out["endings"]["reached"] == []
        assert out["runs"]["choicesObserved"]["count"] == 0.0
        assert out["runs"]["durationSeconds"] is None
        assert out["coverage"]["ratio"] == 0.0
        assert out["notes"] and all(isinstance(n, str) for n in out["notes"])


def test_garbage_rows_do_not_crash():
    """裸 ORM 行 / 缺字段的 dict / 类型不对的值都不能让分析抛异常。"""
    runs = [{"id": "r0"}, {"id": "r1", "chapter_count": "abc", "ending_label": 42}]
    choices = [{"run_id": "r0"}, {"run_id": "r0", "seq": None, "choice_index": "x"}]
    out = build_reader_analytics(runs, choices, {"menus": [None, 1]}, ["chA"])
    assert out["sample"]["runs"] == 2
    assert out["sample"]["choices"] == 2


# --------------------------------------------------- 隐私红线（纯函数层）


def test_sanitize_run_payload_drops_unknown_fields():
    payload = {
        "client_run_id": "run-abc-0001",
        "started_at": T0.isoformat(),
        "chapter_count": "3",
        "ending_label": "true_end",
        # 以下都是"有人试图夹带内容"，必须全部丢弃
        "text": "这是台词，绝不能入库",
        "prose": "旁白正文",
        "note": "读者备注",
        "user_agent": "Mozilla/5.0",
        "ip": "1.2.3.4",
        "user_id": "u-123",
    }
    clean, dropped = sanitize_run_payload(payload)
    assert set(clean) == {
        "client_run_id",
        "started_at",
        "ended_at",
        "chapter_count",
        "choice_count",
        "ending_label",
    }
    assert clean["client_run_id"] == "run-abc-0001"
    assert clean["chapter_count"] == 3
    assert clean["ended_at"] is None
    for key in ("text", "prose", "note", "user_agent", "ip", "user_id"):
        assert key in dropped
        assert key not in clean
    assert "这是台词，绝不能入库" not in json.dumps(clean, ensure_ascii=False, default=str)


def test_sanitize_choice_drops_unknown_fields_and_requires_seq():
    clean, dropped = sanitize_choice(
        {
            "seq": 7,
            "chapter_id": "chA",
            "menu_id": "m1",
            "choice_index": 1,
            "condition_passed": 0,
            "text": "选项文案：跟她走",
            "choice_text": "跟她走",
        }
    )
    assert clean is not None
    assert set(clean) == {
        "seq",
        "chapter_id",
        "label",
        "menu_id",
        "choice_index",
        "condition_passed",
    }
    assert clean["seq"] == 7
    assert clean["condition_passed"] is False
    assert clean["label"] == ""
    assert dropped == ["text", "choice_text"]

    # seq 缺失 / 非法 → 整条丢弃（没有 seq 就无法做幂等合并）
    assert sanitize_choice({"text": "没有 seq"})[0] is None
    assert sanitize_choice({"seq": -3})[0] is None
    assert sanitize_choice("不是对象")[0] is None


def test_sanitize_identifier_rejects_any_prose():
    """所有字符串列都过标识符白名单：含空格/标点/中文的值一律进不去。"""
    assert sanitize_identifier("chA") == "chA"
    assert sanitize_identifier("menu-1_2.x:y") == "menu-1_2.x:y"
    assert sanitize_identifier("  真结局  ") == ""  # 中文
    assert sanitize_identifier("这是台词，绝不能入库") == ""
    assert sanitize_identifier("hello world") == ""  # 空格
    assert sanitize_identifier("句号结尾。") == ""
    assert sanitize_identifier("x" * 65) == ""  # 超长
    assert sanitize_identifier(123) == ""
    assert sanitize_identifier(None) == ""


def test_sanitize_client_run_id_requires_entropy():
    assert sanitize_client_run_id("a1b2c3d4-e5f6-7890-abcd-ef1234567890") != ""
    assert sanitize_client_run_id("short") == ""
    assert sanitize_client_run_id("") == ""
    assert sanitize_client_run_id("bad id with spaces") == ""
    assert sanitize_client_run_id(None) == ""


def test_sanitize_choices_dedupes_by_seq_and_counts_the_rest():
    rows, rejected, dropped = sanitize_choices(
        [
            {"seq": 2, "menu_id": "m1", "text": "文案"},
            {"seq": 1, "menu_id": "m1"},
            {"seq": 2, "menu_id": "m1", "choice_index": 5},  # 同 seq 后到覆盖前到
            {"no_seq": True},
        ]
    )
    assert [r["seq"] for r in rows] == [1, 2]
    assert rows[1]["choice_index"] == 5
    assert rejected == 1
    # 未知键即使所在那一行被整条拒绝，也要被记名（说明客户端在发垃圾字段）
    assert dropped == ["text", "no_seq"]
    assert sanitize_choices("not-a-list") == ([], 0, [])


def test_analytics_output_contains_no_option_text():
    """响应里也不回正文：整条遥测链路（表 + 响应）都是可机检的"零正文"。"""
    runs = [_run("r0")]
    choices = [_choice("r0", 0, "m1", 0)]
    out = _analytics(runs, choices)
    blob = json.dumps(out, ensure_ascii=False, default=str)
    assert "选项文案" not in blob
    assert "提示语" not in blob
    # 但定位信息必须在：menu_id + index
    assert "m1" in blob


# ------------------------------------------------------------------- 幂等


def test_missing_choices_is_idempotent():
    incoming = sanitize_choices(
        [
            {"seq": 0, "menu_id": "m1", "choice_index": 0},
            {"seq": 1, "menu_id": "m1", "choice_index": 1},
        ]
    )[0]
    first = missing_choices([], incoming)
    assert [r["seq"] for r in first] == [0, 1]
    # 第二次上报同一份 payload：库里已有 0/1 → 不再插入任何行
    assert missing_choices([0, 1], incoming) == []
    # 中断后续报：只想补 seq=2
    more = sanitize_choices([{"seq": 2, "menu_id": "m2", "choice_index": 0}])[0]
    assert [r["seq"] for r in missing_choices([0, 1], more)] == [2]
    # 同一批里 seq 重复也只插一条
    dupe = [{"seq": 3}, {"seq": 3}]
    assert len(missing_choices([], dupe)) == 1


def test_telemetry_defaults_to_disabled():
    assert is_telemetry_enabled(None) is False  # 没有设置行 = 关闭
    assert is_telemetry_enabled({"enabled": False}) is False
    assert is_telemetry_enabled({"enabled": True}) is True

    class _Row:
        enabled = True

    assert is_telemetry_enabled(_Row()) is True


def test_dropped_field_names_is_bounded_and_deduplicated():
    names = dropped_field_names(["a", "a", *[f"k{i}" for i in range(30)]])
    assert names[0] == "a"
    assert len(names) == len(set(names))
    assert len(names) <= 12
    assert dropped_field_names(["x" * 500])[0] == "x" * 40
