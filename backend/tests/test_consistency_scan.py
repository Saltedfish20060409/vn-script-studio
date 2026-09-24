"""分片全书一致性扫描的测试。

全部走注入的假 completer，绝不发网络请求。这些断言锁的是语义而非实现细节：
- 有正文的章节一个不漏（这正是旧实现"只扫前 14 章"要修的地方）；
- 跨窗复发的同一条冲突要去重成一条，并被标成更高置信度；
- 单窗失败只影响那一窗，且必须计入 coverage；
- 任何"没扫到的章"都要出现在 coverage 里，不许静默截断。
"""

from __future__ import annotations

import asyncio
import json

from app.core.ai import DeepSeekConfig
from app.core.consistency_scan import (
    merge_window_results,
    plan_windows,
    run_consistency_scan,
)
from app.core.project import normalize_project
from app.domain.types import VnProject


def _cfg(**kw) -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test-not-real", model="mock", **kw)


#: 这些用例测的是**分片机制**（窗口切分、跨窗合并、预算、单窗失败），
#: 不是默认参数，所以显式固定一组窗口参数：默认值以后按测量调整（见
#: tests/test_scan_exposure.py 与路由上方的注释）时，这些断言不该跟着变。
WINDOW_ARGS = {"size": 6, "overlap": 2}


def _project(chapter_count: int, *, empty: set | None = None, unit: int = 1) -> VnProject:
    """chapter_count 章，其中 empty 里的章没有任何正文。"""
    skip = empty or set()
    chapters = []
    for i in range(1, chapter_count + 1):
        blocks = []
        if i not in skip:
            blocks = [
                {
                    "type": "narration",
                    "text": f"第{i}章的正文，用来做分片一致性扫描的输入。" * unit,
                }
            ]
        chapters.append({"id": f"c{i}", "title": f"第{i}章", "blocks": blocks})
    return normalize_project(
        {
            "id": "p1",
            "title": "分片扫描测试",
            "characters": [{"id": "ch-lin", "defineName": "lin", "displayName": "林夏"}],
            "bible": {"world": "末班车之后的世界"},
            "timeline": [{"id": "t1", "title": "到站", "when": "深夜", "order": 1}],
            "chapters": chapters,
        }
    )


def _user_payload(messages: list[dict]) -> dict:
    return json.loads(messages[1]["content"])


def _chapter_ids(messages: list[dict]) -> list[str]:
    return [c["id"] for c in _user_payload(messages)["chapters"]]


def _reply(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _issue(category: str, severity: str, ids: list[str], quote: str, desc: str) -> dict:
    return {
        "category": category,
        "severity": severity,
        "chapterIds": ids,
        "quote": quote,
        "description": desc,
        "suggestion": "按设定统一改一遍",
    }


# ------------------------------------------------------------------ plan_windows


def test_plan_windows_single_window_when_chapters_fit():
    """章数 <= 窗口大小时只有一窗：行为与旧的一次性扫描等价。"""
    p = _project(4)
    windows = plan_windows(p, size=6, overlap=2)
    assert len(windows) == 1
    w = windows[0]
    assert w["index"] == 0
    assert w["chapterIds"] == ["c1", "c2", "c3", "c4"]
    assert w["chapterTitles"] == ["第1章", "第2章", "第3章", "第4章"]
    assert w["chars"] > 0


def test_plan_windows_covers_every_chapter_with_text():
    """最关键的一条：章节多、且有空洞时，每个有正文的章节都必须落在至少一个窗口里。"""
    p = _project(23, empty={5, 18})
    windows = plan_windows(p, size=6, overlap=2)
    assert len(windows) > 1

    expected = [f"c{i}" for i in range(1, 24) if i not in (5, 18)]
    covered = [cid for w in windows for cid in w["chapterIds"]]
    assert set(covered) == set(expected)
    # 没有正文的章节不该被塞进窗口（否则会虚报覆盖率）
    assert "c5" not in covered and "c18" not in covered
    # 末尾章必被覆盖：最后一个窗口要顶到全书结尾，而不是提前收尾
    assert windows[-1]["chapterIds"][-1] == "c23"
    # 每个窗口都不超过 size 章
    assert all(len(w["chapterIds"]) <= 6 for w in windows)


def test_plan_windows_adjacent_windows_overlap():
    p = _project(14)
    windows = plan_windows(p, size=6, overlap=2)
    assert [w["chapterIds"][0] for w in windows] == ["c1", "c5", "c9"]
    for left, right in zip(windows, windows[1:]):
        assert set(left["chapterIds"]) & set(right["chapterIds"]), "相邻窗口必须重叠"


def test_plan_windows_includes_prose_only_chapters():
    """只写 prose（不写 block）的章节也是"有正文"，必须进窗口。"""
    p = normalize_project(
        {
            "id": "p2",
            "title": "纯正文写作",
            "chapters": [
                {"id": "c1", "title": "第一章", "prose": "雨落在站台上。", "blocks": []},
                {"id": "c2", "title": "第二章", "prose": "", "blocks": []},
            ],
        }
    )
    windows = plan_windows(p)
    ids = [cid for w in windows for cid in w["chapterIds"]]
    assert ids == ["c1"]


# --------------------------------------------------------------- 多窗口扫 + 合并


def test_multi_window_scan_merges_and_promotes_repeated_issue():
    """两个窗口各报各的：去重正确，跨窗复发那条 confidence=high。"""
    p = _project(10)  # size=6 / overlap=2 → c1-c6、c5-c10 两窗
    repeated_medium = _issue(
        "character", "medium", ["c2"], "林夏的头发是黑色的。", "第三章写她金发。"
    )
    repeated_high = _issue(
        "character", "high", ["c9"], "林夏的头发是黑色的", "第三章写她金发"
    )
    only_first = _issue("timeline", "high", ["c1"], "昨天才到站", "第五天就说起三天前")
    only_second = _issue("plot", "low", ["c10"], "她把信收进口袋", "信在前一章已经烧了")
    calls: list[list[dict]] = []

    async def fake(messages: list[dict]) -> str:
        calls.append(messages)
        ids = _chapter_ids(messages)
        if ids[0] == "c1":
            return _reply(
                {"summary": "第一段问题集中在角色设定。", "issues": [repeated_medium, only_first]}
            )
        return _reply({"summary": "第二段仍有同一处角色冲突。", "issues": [repeated_high, only_second]})

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))

    assert result["error"] is None
    assert len(calls) == 2
    assert _chapter_ids(calls[0]) == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert _chapter_ids(calls[1]) == ["c5", "c6", "c7", "c8", "c9", "c10"]
    # 每个窗口都带全量权威设定 + 与旧审计同一套 system prompt 结构
    for messages in calls:
        user = _user_payload(messages)
        assert [c["displayName"] for c in user["authority"]["characters"]] == ["林夏"]
        assert user["authority"]["timeline"][0]["title"] == "到站"
        assert "一致性总编" in messages[0]["content"]
        assert "第 1 段" in user["scope"] or "第 2 段" in user["scope"]

    issues = result["issues"]
    assert len(issues) == 3, "同一条冲突（只差标点）必须并成一条"
    repeated = [i for i in issues if i["category"] == "character"]
    assert len(repeated) == 1
    assert repeated[0]["foundInWindows"] == 2
    assert repeated[0]["confidence"] == "high"
    assert repeated[0]["severity"] == "high"
    assert repeated[0]["chapterIds"] == ["c2", "c9"]
    assert repeated[0]["windowIndexes"] == [0, 1]
    singles = [i for i in issues if i["category"] in ("timeline", "plot")]
    assert singles and all(i["foundInWindows"] == 1 for i in singles)
    assert all(i["confidence"] == "medium" for i in singles)

    cov = result["coverage"]
    assert cov["chaptersTotal"] == 10
    assert cov["chaptersWithText"] == 10
    assert cov["chaptersScanned"] == 10
    assert cov["coverageRatio"] == 1.0
    assert cov["windowsPlanned"] == 2
    assert cov["windowsRun"] == 2
    assert cov["windowsFailed"] == 0
    assert cov["truncatedChapters"] == []
    assert cov["maxWindowsHit"] is False
    # ceilingNote 要如实对照旧实现的 14 章 / 1600 字上限
    assert "14 章" in result["ceilingNote"]
    assert "10/10" in result["ceilingNote"]


def test_run_passes_window_scope_and_reports_summaries():
    p = _project(7)  # size=6/overlap=2 → c1-c6、c5-c7（末窗顶到全书结尾）
    seen: list[list[str]] = []

    async def fake(messages: list[dict]) -> str:
        seen.append(_chapter_ids(messages))
        return _reply({"summary": "这一段没问题。", "issues": []})

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))
    assert seen == [["c1", "c2", "c3", "c4", "c5", "c6"], ["c5", "c6", "c7"]]
    assert result["issues"] == []
    assert result["summary"] == "这一段没问题。"
    assert result["coverage"]["windowsRun"] == 2
    assert all(w["reported"] for w in result["windows"])


# ---------------------------------------------------------------------- 失败隔离


def test_one_window_failure_does_not_sink_the_scan():
    """一个窗口抛异常：其余窗口结果照常返回，失败计入 coverage，异常不冒泡。"""
    p = _project(10)
    good = _issue("bible", "medium", ["c8"], "这个世界没有电", "设定里明明有电灯")

    async def fake(messages: list[dict]) -> str:
        ids = _chapter_ids(messages)
        if ids[0] == "c1":
            raise RuntimeError("上游超时")
        return _reply({"summary": "第二段扫到了问题。", "issues": [good]})

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))

    assert result["error"] is None, "只有部分窗口失败时不该报整体错误"
    assert len(result["issues"]) == 1
    assert result["issues"][0]["category"] == "bible"
    cov = result["coverage"]
    assert cov["windowsRun"] == 2
    assert cov["windowsFailed"] >= 1
    assert cov["chaptersScanned"] == 6
    assert cov["truncatedChapters"] == ["c1", "c2", "c3", "c4"]
    assert 0 < cov["coverageRatio"] < 1
    assert len(result["windowErrors"]) == 1
    assert result["windowErrors"][0]["chapterIds"] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert "超时" in result["windowErrors"][0]["error"]
    assert result["windows"][0]["reported"] is False


def test_all_windows_failed_surfaces_an_error():
    p = _project(10)

    async def fake(messages: list[dict]) -> str:
        raise RuntimeError("模型服务 500")

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))
    assert result["error"] and "全部 2 个窗口都失败" in result["error"]
    assert result["issues"] == []
    assert result["coverage"]["windowsFailed"] == 2
    assert result["coverage"]["chaptersScanned"] == 0


def test_malformed_window_output_only_fails_that_window():
    p = _project(10)

    async def fake(messages: list[dict]) -> str:
        if _chapter_ids(messages)[0] == "c1":
            return "模型今天不说 JSON"
        return _reply({"issues": "not-a-list"})

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))
    assert result["issues"] == []
    assert result["coverage"]["windowsFailed"] == 2  # 坏 JSON 也算这一窗没结论
    assert result["error"]


# ------------------------------------------------------------------- 预算与降级


def test_max_windows_budget_is_reported_not_silent():
    p = _project(10)  # 计划 2 窗（c1-c6 / c5-c10）
    seen: list[int] = []

    async def fake(messages: list[dict]) -> str:
        seen.append(len(_chapter_ids(messages)))
        return _reply({"summary": "只扫了第一段。", "issues": []})

    result = asyncio.run(
        run_consistency_scan(_cfg(), p, max_windows=1, **WINDOW_ARGS, completer=fake)
    )
    cov = result["coverage"]
    assert seen == [6], "超出预算的窗口不该被发出去"
    assert cov["windowsPlanned"] == 2
    assert cov["windowsRun"] == 1
    assert cov["chaptersScanned"] == 6
    assert cov["maxWindowsHit"] is True
    assert cov["truncatedChapters"] == ["c7", "c8", "c9", "c10"]
    assert cov["coverageRatio"] == 0.6
    assert "max_windows" in result["ceilingNote"]


def test_http_default_window_cap_exists_and_is_reported_not_silent():
    """HTTP 入口有默认窗口上界（16 = 一个并发批），超出部分必须如实报未扫。

    为什么要上界：窗口是并发发出的，但进程内只有 16 个 LLM 并发额度，超了要排队，
    墙钟时间成倍增长；调用方（HTTP 请求）自带超时预算，等不到结果 = 白扫还照付 token。
    """
    from app.core.consistency_scan import HTTP_DEFAULT_MAX_WINDOWS

    assert HTTP_DEFAULT_MAX_WINDOWS == 16
    planned = len(plan_windows(_project(200), size=6, overlap=2))
    assert planned > HTTP_DEFAULT_MAX_WINDOWS, "用例本身要能触发截断"

    sent: list[int] = []

    async def fake(messages: list[dict]) -> str:
        sent.append(1)
        return _reply({"summary": "ok", "issues": []})

    result = asyncio.run(
        run_consistency_scan(
            _cfg(),
            _project(200),
            max_windows=HTTP_DEFAULT_MAX_WINDOWS,
            **WINDOW_ARGS,
            completer=fake,
        )
    )
    cov = result["coverage"]
    assert len(sent) == HTTP_DEFAULT_MAX_WINDOWS, "超上界的窗口不该被发出去"
    assert cov["windowsPlanned"] == planned
    assert cov["windowsRun"] == HTTP_DEFAULT_MAX_WINDOWS
    assert cov["maxWindowsHit"] is True
    assert cov["truncatedChapters"], "被砍掉的章节必须列出来（不许静默丢）"
    assert "max_windows" in result["ceilingNote"]


def test_no_chapters_returns_safely():
    p = normalize_project({"id": "p3", "title": "空作品", "chapters": []}).model_copy(
        update={"chapters": []}
    )
    result = asyncio.run(run_consistency_scan(_cfg(), p, completer=None))
    assert result["issues"] == []
    assert result["error"] is None
    assert result["summary"] == "作品还没有章节。"
    cov = result["coverage"]
    assert cov["chaptersTotal"] == 0
    assert cov["chaptersWithText"] == 0
    assert cov["coverageRatio"] == 0.0
    assert cov["windowsPlanned"] == 0
    assert cov["truncatedChapters"] == []


def test_chapters_without_text_report_zero_coverage():
    p = normalize_project(
        {
            "id": "p4",
            "title": "还没写",
            "chapters": [{"id": "c1", "title": "第一章", "blocks": []}],
        }
    )
    result = asyncio.run(run_consistency_scan(_cfg(), p, completer=None))
    assert result["issues"] == []
    assert "没有可扫描的正文" in result["summary"]
    cov = result["coverage"]
    assert cov["chaptersTotal"] == 1
    assert cov["chaptersWithText"] == 0
    assert cov["chaptersScanned"] == 0
    assert cov["coverageRatio"] == 0.0
    assert cov["windowsPlanned"] == 0
    assert cov["windowsRun"] == 0
    assert cov["truncatedChapters"] == []
    assert "0/0" in result["ceilingNote"]


def test_missing_api_key_skips_without_calling_llm():
    p = _project(10)
    calls: list[list[dict]] = []

    async def fake(messages: list[dict]) -> str:
        calls.append(messages)
        return _reply({"issues": []})

    result = asyncio.run(
        run_consistency_scan(DeepSeekConfig(apiKey=""), p, **WINDOW_ARGS, completer=fake)
    )
    assert calls == [], "没配 key 时一次模型都不该调"
    assert result["error"] and "DEEPSEEK_API_KEY" in result["error"]
    assert result["issues"] == []
    cov = result["coverage"]
    # 覆盖率要如实为零：计划了 2 窗，实际 0 窗，10 章全未扫。
    assert cov["windowsPlanned"] == 2
    assert cov["windowsRun"] == 0
    assert cov["chaptersScanned"] == 0
    assert cov["coverageRatio"] == 0.0
    assert len(cov["truncatedChapters"]) == 10


def test_chapter_texts_override_wins_and_missing_chapters_still_scan():
    """服务端更新的正文优先；override 里没提到的章节回落到项目正文，而不是被跳过。"""
    p = normalize_project(
        {
            "id": "p5",
            "title": "新正文覆盖",
            "chapters": [
                {"id": "c1", "title": "第一章", "blocks": []},
                {"id": "c2", "title": "第二章", "blocks": [{"type": "narration", "text": "旧正文"}]},
            ],
        }
    )
    captured: list[dict] = []

    async def fake(messages: list[dict]) -> str:
        captured.append(_user_payload(messages))
        return _reply({"summary": "ok", "issues": []})

    result = asyncio.run(
        run_consistency_scan(
            _cfg(), p, chapter_texts={"c1": "第一章的最新正文。", "c2": ""}, completer=fake
        )
    )
    chapters = captured[0]["chapters"]
    assert [c["id"] for c in chapters] == ["c1", "c2"]
    assert chapters[0]["text"] == "第一章的最新正文。"
    assert chapters[1]["text"] == "旁白: 旧正文"
    assert result["coverage"]["chaptersScanned"] == 2


def test_per_chapter_cap_and_trimming_are_reported():
    p = _project(2, unit=400)  # 每章正文远超 1600 字
    captured: list[dict] = []

    async def fake(messages: list[dict]) -> str:
        captured.append(_user_payload(messages))
        return _reply({"summary": "ok", "issues": []})

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))
    sent = captured[0]["chapters"][0]["text"]
    assert len(sent) == 1600
    cov = result["coverage"]
    assert cov["textTruncatedChapters"] == ["c1", "c2"]
    assert "截断后送审" in result["ceilingNote"]


def test_per_window_issue_cap_drops_are_counted():
    """单窗 30 条上限（复用旧审计）吃掉的部分也要报出来，不能变成新的静默截断。"""
    p = _project(4)  # 单窗
    many = [
        _issue("plot", "low", ["c1"], f"第{i}处证据", f"第{i}处矛盾说明")
        for i in range(1, 36)
    ]

    async def fake(messages: list[dict]) -> str:
        return _reply({"summary": "问题很多。", "issues": many})

    result = asyncio.run(run_consistency_scan(_cfg(), p, **WINDOW_ARGS, completer=fake))
    assert result["issuesDroppedByWindowCap"] == 5
    assert result["windows"][0]["rawIssueCount"] == 35
    assert result["windows"][0]["issueCount"] == 30
    assert len(result["issues"]) == 30
    assert "单窗 30 条上限" in result["ceilingNote"]


# ---------------------------------------------------------------------- 合并单元


def test_merge_takes_highest_severity_and_union_of_chapters():
    merged = merge_window_results(
        [
            {
                "index": 0,
                "error": None,
                "summary": "第一段",
                "issues": [
                    {
                        "category": "location",
                        "severity": "low",
                        "chapterIds": ["c3"],
                        "quote": "车站朝南",
                        "description": "第二章说朝北",
                        "suggestion": "统一朝向",
                    },
                    {
                        "category": "location",
                        "severity": "low",
                        "chapterIds": ["c3"],
                        "quote": "车站朝南",
                        "description": "第二章说朝北",
                        "suggestion": "同一窗重复，应只算一次",
                    },
                ],
            },
            {
                "index": 1,
                "error": None,
                "summary": "第二段",
                "issues": [
                    {
                        "category": "location",
                        "severity": "high",
                        "chapterIds": ["c9"],
                        "quote": "车站朝南。",
                        "description": "第二章说朝北！",
                        "suggestion": "统一朝向",
                    }
                ],
            },
            {"index": 2, "error": "第 3 段扫描失败：上游 500", "issues": []},
        ]
    )
    assert merged["windowsReported"] == 2
    assert len(merged["issues"]) == 1
    only = merged["issues"][0]
    assert only["severity"] == "high"
    assert only["chapterIds"] == ["c3", "c9"]
    assert only["foundInWindows"] == 2, "同一窗口内的重复不算两个窗口"
    assert only["confidence"] == "high"
    assert only["windowIndexes"] == [0, 1]
    assert merged["summary"] == "第一段 第二段"
    assert merged["issuesTruncated"] == 0


def test_merge_keeps_distinct_categories_apart():
    merged = merge_window_results(
        [
            {
                "index": 0,
                "error": None,
                "issues": [
                    {
                        "category": "character",
                        "severity": "medium",
                        "chapterIds": ["c1"],
                        "quote": "同一句",
                        "description": "同一说明",
                    },
                    {
                        "category": "timeline",
                        "severity": "medium",
                        "chapterIds": ["c1"],
                        "quote": "同一句",
                        "description": "同一说明",
                    },
                ],
            }
        ]
    )
    assert len(merged["issues"]) == 2
    assert all(i["confidence"] == "medium" for i in merged["issues"])


def test_merge_handles_empty_input():
    merged = merge_window_results([])
    assert merged["issues"] == []
    assert merged["windowsReported"] == 0
    assert merged["issuesTruncated"] == 0
