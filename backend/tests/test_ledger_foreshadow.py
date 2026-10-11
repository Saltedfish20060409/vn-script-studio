"""伏笔闭环：回收记在哪一章、埋了多久、同一个钩子不重复。

为什么要这几条：原来只记 open/paid，于是
- 说不出"这条在第 12 章回收了"；
- 也算不出"埋了 25 章还没回收"（模型因此不会觉得这事有时限）；
- 模型把"这章回收了它"当成新发现报上来时，账本里会出现两条同一个钩子（一条 open 一条 paid）。
"""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.pipeline.ledger import (
    AUTO_FORESHADOW_NOTE,
    digest_chapter_into_ledger,
    foreshadow_report,
    format_ledger_for_agent,
    get_ledger,
    set_ledger,
)


def _project_with_chapters(n: int = 5):
    p = create_demo_project()
    base = p.chapters[0]
    chapters = []
    for i in range(n):
        ch = base.model_copy(deep=True)
        ch.id = f"ch{i + 1}"
        ch.title = f"第{i + 1}章"
        chapters.append(ch)
    p = p.model_copy(deep=True)
    p.chapters = chapters
    return p


def _digest(project, chapter_id: str, foreshadows=None):
    ledger = digest_chapter_into_ledger(project, chapter_id, llm_foreshadows=foreshadows)
    return set_ledger(project, ledger)


def test_paid_foreshadow_records_which_chapter_paid_it():
    p = _project_with_chapters(3)
    p = _digest(p, "ch1", [{"hook": "红伞的来历", "status": "open"}])
    p = _digest(p, "ch3", [{"hook": "红伞的来历", "status": "paid"}])

    rows = foreshadow_report(p)
    assert len(rows) == 1, "同一个钩子只应留一条"
    row = rows[0]
    assert row["status"] == "paid"
    assert row["plantedChapter"] == "ch1"
    assert row["paidInChapter"] == "ch3"
    assert row["ageChapters"] == 2  # 埋了 2 章才回收


def test_same_hook_reported_twice_does_not_duplicate():
    p = _project_with_chapters(3)
    p = _digest(p, "ch1", [{"hook": "谁在跟踪她", "status": "open"}])
    p = _digest(p, "ch2", [{"hook": "谁在跟踪她", "status": "open"}])
    rows = foreshadow_report(p)
    assert len(rows) == 1


def test_open_foreshadow_age_counts_to_latest_chapter():
    p = _project_with_chapters(6)
    p = _digest(p, "ch1", [{"hook": "钟楼上的灯", "status": "open"}])
    row = foreshadow_report(p)[0]
    assert row["status"] == "open"
    assert row["paidInChapter"] is None
    assert row["ageChapters"] == 5  # 5 章过去了还没回收


def test_agent_block_tells_the_model_how_long_hooks_have_been_open():
    p = _project_with_chapters(8)
    p = _digest(p, "ch1", [{"hook": "雨里的脚步声", "status": "open"}])
    block = format_ledger_for_agent(get_ledger(p), chapters=p.chapters)
    assert "未回收伏笔" in block
    assert "已埋 7 章未回收" in block


def test_short_ages_are_not_noisy():
    """刚埋一两章的不用催（避免每轮都在催，反而变噪音）。"""
    p = _project_with_chapters(2)
    p = _digest(p, "ch1", [{"hook": "新埋的", "status": "open"}])
    block = format_ledger_for_agent(get_ledger(p), chapters=p.chapters)
    assert "未回收伏笔" in block
    assert "已埋" not in block


def test_report_works_without_chapters():
    """没有章节信息时不该炸，只是算不出年龄。"""
    p = create_demo_project()
    ledger = get_ledger(p)
    ledger["foreshadows"] = [
        {"id": "f1", "hook": "x", "plantedChapter": "gone", "status": "open"}
    ]
    p = set_ledger(p, ledger)
    rows = foreshadow_report(p)
    assert rows[0]["ageChapters"] is None
    # 硬锚块也不该因为缺章节而失效
    assert isinstance(format_ledger_for_agent(ledger), str)


def test_heuristic_rewrites_replace_auto_foreshadow_for_same_chapter():
    """大改章末钩：旧「自动」open 应消失，新钩出现；人工伏笔保留。"""
    p = _project_with_chapters(2)
    ch = p.chapters[0]
    # 先塞一条自动伏笔 + 一条人工伏笔
    ledger = get_ledger(p)
    ledger["foreshadows"] = [
        {
            "id": "auto1",
            "hook": "旧章末钩：雨夜有人在跟踪",
            "plantedChapter": ch.id,
            "status": "open",
            "note": AUTO_FORESHADOW_NOTE,
        },
        {
            "id": "manual1",
            "hook": "人工埋下的红伞",
            "plantedChapter": ch.id,
            "status": "open",
            "note": "作者手记",
        },
    ]
    p = set_ledger(p, ledger)

    # 改正文，使 closeHook 变成新内容
    p = p.model_copy(deep=True)
    p.chapters[0].prose = (
        "林夏推开门。\n"
        "门外空无一人。\n"
        "她听见远处传来钟声。\n"
        "新章末钩：钟楼上的灯突然灭了。"
    )
    ledger2 = digest_chapter_into_ledger(p, ch.id)
    fores = ledger2.get("foreshadows") or []
    hooks = [str(f.get("hook") or "") for f in fores]
    assert "旧章末钩：雨夜有人在跟踪" not in hooks
    assert any("人工埋下的红伞" in h for h in hooks)
    autos = [f for f in fores if f.get("note") == AUTO_FORESHADOW_NOTE]
    assert len(autos) <= 1
    if autos:
        assert "钟楼" in str(autos[0].get("hook") or "") or "灯" in str(
            autos[0].get("hook") or ""
        )
