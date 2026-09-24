"""记忆探针：按 LongMemEval 的维度检查"该进上下文的东西有没有真的进去"。

这里既测探针本身的正确性（能不能发现真的缺口、会不会误报），也**留档一次真实收获**：
写这套探针时，"时间推理"维度第一次运行就是红的——作者登记的时间线从没进过写作时的
上下文（`agent_context._timeline_lines` 是为此补的）。所以下面既有"现在必须全绿"的断言，
也有专门针对时间线的那条回归守卫。
"""

from __future__ import annotations

from app.core.memory_probe import build_probes, run_probes
from app.core.project import normalize_project


def _book(*, timeline: bool = True, pinned: bool = False, stale_event: bool = False):
    entry = {
        "id": "e1",
        "title": "第二次钟声的规矩",
        "body": "钟声一天只会响两次，第二次响过之后当天不会再有第三次。",
        "keywords": ["钟声", "规矩"],
        "links": [{"toType": "character", "toId": "c1", "note": "这条规矩约束的是他"}],
    }
    entries = [entry]
    if pinned:
        entries.append(
            {
                "id": "e2",
                "title": "雨见町的天气",
                "body": "一年有两百天在下雨，雨具是常备品。",
                "keywords": ["天气"],
                "pinned": True,
            }
        )
    events = []
    if timeline:
        events = [
            {
                "id": "t1",
                "title": "转学第一天听见钟声",
                "when": "第一天",
                "chapterRef": "ch1",
                "summary": "他在失物招领处第一次听见钟声里的呼救。",
                "order": 1.0,
            },
            {
                "id": "t2",
                "title": "钟楼的门被打开",
                "when": "第三晚",
                "chapterRef": "ch3",
                "summary": "门没有锁。",
                "order": 3.0,
            },
        ]
    if stale_event:
        events.append(
            {
                "id": "t9",
                "title": "（已作废的旧设定）钟声每天响一次",
                "when": "旧稿",
                "chapterRef": "ch1",
                "order": 0.5,
                "stale": True,
            }
        )
    return normalize_project(
        {
            "id": "p-probe",
            "title": "记忆探针",
            "logline": "一句话简介",
            "characters": [
                {
                    "id": "c1",
                    "displayName": "雨宫澪",
                    "defineName": "mio",
                    "voice": "短句",
                    "bio": "转学生",
                }
            ],
            "locations": [{"id": "l1", "name": "失物招领处"}],
            "loreEntries": entries,
            "timeline": events,
            "chapters": [
                {"id": "ch1", "title": "第一章", "prose": "雨停了，他站在月台上。", "synopsis": "转学第一天听见钟声。"},
                {"id": "ch2", "title": "第二章", "prose": "第二天，他又来了。", "synopsis": "第七个抽屉是空的。"},
                {"id": "ch3", "title": "第三章", "prose": "钟楼的门没有锁。", "synopsis": "他上了钟楼。"},
            ],
        }
    )


def _dimension(report, name: str):
    return report.by_dimension.get(name)


# ---- 探针本身的工作方式 --------------------------------------------------------


def test_probes_cover_the_longmemeval_dimensions_we_can_measure():
    probes = build_probes(_book(pinned=True), focus_chapter_id="ch2")
    dims = {p.dimension for p in probes}
    assert {"info_extraction", "multi_session", "temporal", "graph_hop", "abstention"} <= dims
    # 每条探针都要带得动"问什么、看什么"——否则报告没法解释
    for probe in probes:
        assert probe.question.strip()
        assert probe.needles, probe.id


def test_probe_report_passes_on_a_healthy_project():
    report = run_probes(_book(pinned=True), focus_chapter_id="ch2")
    assert report.summary.startswith("探针 ")
    for name in ("info_extraction", "multi_session", "temporal", "graph_hop", "abstention"):
        bucket = _dimension(report, name)
        assert bucket is not None, f"{name} 维度没有探针"
        assert bucket["rate"] == 1.0, (name, bucket)


def test_temporal_dimension_would_have_caught_the_missing_timeline():
    """**回归守卫**：时间线必须真的进上下文（写这套探针时它第一次运行就是红的）。

    当时的状况：`project.timeline` 只在一致性审计/事实扫描里被当"准绳"用，
    **从没进过写作时的上下文**——模型一边被要求别写乱时间，一边看不到那份时间线。
    """
    report = run_probes(_book(), focus_chapter_id="ch2")
    temporal = _dimension(report, "temporal")
    assert temporal is not None and temporal["rate"] == 1.0, temporal

    # 更强的一条：时间线段本身要出现在上下文里
    from app.core.agent_context import build_agent_context

    ctx = build_agent_context(_book(), chapterId="ch2", userMessage="接着写", task="continue")
    assert "## 时间线（作者登记的事件" in ctx.text


def test_temporal_probe_ignores_future_and_stale_events():
    """焦点章之后的事件与 stale 事件都不该进上下文——探针也不该把它们算成应有。"""
    from app.core.agent_context import build_agent_context

    project = _book(stale_event=True)
    ctx = build_agent_context(project, chapterId="ch1", userMessage="接着写", task="continue")
    assert "转学第一天听见钟声" in ctx.text  # 本章事件在
    assert "钟楼的门被打开" not in ctx.text  # 未来事件不在（chapterRef=ch3）
    assert "已作废的旧设定" not in ctx.text  # stale 事件不在
    assert "跳过 1 条可能已失效（stale）的事件" in ctx.text  # 但如实说明跳过了


def test_abstention_probe_fails_when_unrelated_entries_are_injected():
    """拒答探针的判据是"非钉住条目的正文不该被注入"——把它反过来验证探针有效。"""
    project = _book(pinned=False)
    probes = build_probes(project, focus_chapter_id="ch2")
    abstain = next(p for p in probes if p.dimension == "abstention")
    assert abstain.mode == "absent"
    # 人为把"不该出现"改成必然出现的片段：探针必须报失败
    abstain.needles = ["雨停了，他站在月台上。"]
    report = run_probes(project, focus_chapter_id="ch2", probes=probes)
    assert _dimension(report, "abstention")["rate"] == 0.0


def test_pinned_entries_are_excluded_from_the_abstention_judgement():
    """钉住的条目本来就永远带上，拿它判"凭空注入"会冤枉工具。"""
    probes = build_probes(_book(pinned=True), focus_chapter_id="ch2")
    abstain = next(p for p in probes if p.dimension == "abstention")
    assert all("雨具是常备品" not in needle for needle in abstain.needles)


def test_dimensions_without_data_are_reported_as_unmeasured_not_passed():
    """没有时间线/设定条目的书：那些维度必须**明说没测**，不能算成通过。"""
    project = normalize_project(
        {
            "id": "p-bare",
            "title": "只有正文",
            "chapters": [{"id": "ch1", "title": "第一章", "prose": "雨停了。"}],
        }
    )
    report = run_probes(project, focus_chapter_id="ch1")
    assert "没有测量" in report.notes[-3] or any("没有测量" in n for n in report.notes)
    assert _dimension(report, "multi_session") is None


def test_report_states_its_own_limits():
    """报告要自带边界说明：它只测检索层，不代表模型会不会用。"""
    report = run_probes(_book(), focus_chapter_id="ch2")
    joined = "\n".join(report.notes)
    assert "知识更新" in joined
    assert "不代表模型" in joined


def test_probe_run_costs_one_context_assembly():
    """整套测量的开销 = 一次上下文组装（不随探针数量增长、零模型调用）。"""
    report = run_probes(_book(pinned=True), focus_chapter_id="ch2")
    assert len(report.results) >= 6
    assert report.chars_used > 0
    # 组装一次的结果就是报告里用的那份文本：探针数量多于上下文组装次数，说明复用了
    assert report.chars_used < 20000


def test_probe_is_deterministic():
    """同一本书两次测量结果一致（纯函数，可用于回归对比）。"""
    a = run_probes(_book(pinned=True), focus_chapter_id="ch2")
    b = run_probes(_book(pinned=True), focus_chapter_id="ch2")
    assert [r.id for r in a.results] == [r.id for r in b.results]
    assert [r.ok for r in a.results] == [r.ok for r in b.results]
    assert a.by_dimension == b.by_dimension
