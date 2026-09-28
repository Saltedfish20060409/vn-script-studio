"""账本裁剪（retention）：丢掉的是"最没用的那条"，而不是"最早的那条"。

为什么要有这个文件
------------------
账本四个列表原来一律用尾部窗口截断（`rows[-40:]` / `[-60:]` / `[-50:]`）。
对"最近发生了什么"这类列表这是对的；但对**价值恰好等于其年龄**的两类数据是反的：

1. **未回收伏笔**：列表按插入顺序追加，尾部截断丢掉的因此是最早埋下的那条。
   一个每章一个钩子的工程写到第 41 章，第 1 章的钩子就静默消失了——而
   "埋了 25 章还没回收"正是 `foreshadow_report` / 伏笔回收率存在的全部理由。
   回收率还会因此**凭空变好**（丢掉的都是没回收的）。
2. **角色状态**：每章 × 每出场角色一行，`[-60:]` 大约只够 10 章 × 6 人。于是
   一个早期出场、后文只被提及的角色，他的"已死亡"记录会先于话多的配角消失——
   被挤掉的顺序取决于谁最近话多，与实际重要性无关。而 `write_precheck` 正是靠
   这些记录判断"这个人是不是已经死了"。

本文件同时钉住"丢了要说出来"：`_retention_record` 的累计值不清零，因此
"账本丢过东西"这件事在 API 上看得见，而不是又一次静默失忆。
"""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.pipeline.ledger import (
    _MAX_CHARACTER_STATES,
    _MAX_OPEN_FORESHADOWS,
    _MAX_PAID_FORESHADOWS,
    _retain_character_states,
    _retain_foreshadows,
    digest_chapter_into_ledger,
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


def _digest(project, chapter_id: str, foreshadows=None, states=None):
    ledger = digest_chapter_into_ledger(
        project, chapter_id, llm_foreshadows=foreshadows, llm_states=states
    )
    return set_ledger(project, ledger)


def _hook(i: int, status: str = "open") -> dict:
    return {"hook": f"钩子{i}", "status": status}


# --------------------------------------------------------------- 纯函数：伏笔


def test_open_hooks_are_never_displaced_by_paid_ones():
    """已回收的占位不该把未回收的挤出去。"""
    rows = [_hook(i, "paid") for i in range(_MAX_PAID_FORESHADOWS + 10)]
    rows += [_hook(100 + i, "open") for i in range(5)]

    kept, evicted = _retain_foreshadows(rows)

    opens = [r for r in kept if r["status"] == "open"]
    assert len(opens) == 5, "五条未回收伏笔一条都不该丢"
    assert evicted.get("paid") == 10
    assert "open" not in evicted


def test_earliest_open_hook_survives_forty_later_ones():
    """核心回归：`rows[-40:]` 会丢掉钩子 0，正是埋得最久的那条。"""
    rows = [_hook(i, "open") for i in range(45)]

    kept, evicted = _retain_foreshadows(rows)

    hooks = [r["hook"] for r in kept]
    assert "钩子0" in hooks, "最早埋下的钩子必须还在"
    assert not evicted, "45 条远未触到未回收的硬上限，不该有丢失"


def test_paid_hooks_keep_the_most_recent_and_report_the_loss():
    rows = [_hook(i, "paid") for i in range(_MAX_PAID_FORESHADOWS + 3)]

    kept, evicted = _retain_foreshadows(rows)

    assert len(kept) == _MAX_PAID_FORESHADOWS
    assert evicted["paid"] == 3
    # 已回收的留最近的：最早的三条出局，最新的一条还在
    assert kept[-1]["hook"] == f"钩子{_MAX_PAID_FORESHADOWS + 2}"
    assert "钩子0" not in [r["hook"] for r in kept]


def test_open_ceiling_reports_what_it_dropped():
    """超过未回收硬上限时必须计数，不许静默。"""
    rows = [_hook(i, "open") for i in range(_MAX_OPEN_FORESHADOWS + 7)]

    kept, evicted = _retain_foreshadows(rows)

    assert len(kept) == _MAX_OPEN_FORESHADOWS
    assert evicted["open"] == 7
    # 保留的是挂得最久的：队首还在，被丢的是最新埋的那几条
    assert kept[0]["hook"] == "钩子0"


def test_retention_preserves_relative_order():
    """下游按列表顺序读，保留后顺序不能被打乱（open/paid 不能互相穿插重排）。"""
    rows = [_hook(0, "paid"), _hook(1, "open"), _hook(2, "paid"), _hook(3, "open")]

    kept, _ = _retain_foreshadows(rows)

    assert [r["hook"] for r in kept] == ["钩子0", "钩子1", "钩子2", "钩子3"]


# ----------------------------------------------------------- 纯函数：角色状态


def _state(name: str, chapter: str, emotion: str = "平静") -> dict:
    return {
        "id": f"{name}-{chapter}",
        "chapterId": chapter,
        "characterName": name,
        "emotion": emotion,
    }


def test_every_character_keeps_its_latest_state():
    """早期出场过的角色，不能因为别人话多而整条消失。"""
    rows = [_state("林夏", "ch1", "悲伤")]
    # 之后的章节里另一个角色反复出现，把预算撑爆
    rows += [_state("周屿", f"ch{i}") for i in range(2, _MAX_CHARACTER_STATES + 20)]

    kept, evicted = _retain_character_states(rows)

    names = {r["characterName"] for r in kept}
    assert "林夏" in names, "只在第 1 章出场过的角色必须保住他唯一的状态"
    lx = next(r for r in kept if r["characterName"] == "林夏")
    assert lx["emotion"] == "悲伤", "保住的必须是那条记录本身"
    assert evicted.get("states", 0) > 0


def test_character_state_history_is_kept_when_budget_allows():
    """预算够时不做任何丢弃（反方向：别把正常的账本也裁了）。"""
    rows = [_state("林夏", f"ch{i}") for i in range(1, 20)]

    kept, evicted = _retain_character_states(rows)

    assert len(kept) == 19
    assert not evicted


def test_latest_state_wins_per_character():
    """同一角色多条时，保底保留的是最新那条（后写覆盖先写）。"""
    rows = [_state("绫", "ch1", "平静"), _state("绫", "ch2", "愤怒")]
    rows += [_state("路人", f"ch{i}") for i in range(3, _MAX_CHARACTER_STATES + 5)]

    kept, _ = _retain_character_states(rows)

    aya = [r for r in kept if r["characterName"] == "绫"]
    assert len(aya) == 1
    assert aya[0]["chapterId"] == "ch2"
    assert aya[0]["emotion"] == "愤怒"


# ------------------------------------------------------------- 端到端：账本写入


def test_earliest_open_hook_reaches_the_agent_block_after_forty_chapters():
    """端到端复现原缺陷：40 章之后，第 1 章的未回收钩子仍须在硬锚块里。"""
    p = _project_with_chapters(45)
    for i in range(1, 46):
        p = _digest(p, f"ch{i}", [_hook(i, "open")])

    ledger = get_ledger(p)
    hooks = [f["hook"] for f in ledger["foreshadows"]]
    assert "钩子1" in hooks, "第 1 章埋的钩子不该被后面的 44 条挤掉"

    block = format_ledger_for_agent(ledger, chapters=p.chapters)
    assert "钩子1" in block, "而且要真的进到提示词里"


def test_stalest_open_hooks_win_the_ten_slots():
    """硬锚块只有 10 个位置，该给挂得最久的，而不是最后埋的。"""
    p = _project_with_chapters(12)
    for i in range(1, 13):
        p = _digest(p, f"ch{i}", [_hook(i, "open")])

    block = format_ledger_for_agent(get_ledger(p), chapters=p.chapters)

    assert "钩子1" in block, "挂得最久的那条必须在场"
    assert "钩子12" not in block, "最新埋的不该挤掉更该被催的那条"
    assert "已埋 11 章未回收" in block, "而且要继续带着章龄"


def test_no_eviction_reports_zero_and_no_alarm():
    """反方向：正常长度的账本不该出现"丢过东西"的提示。"""
    p = _project_with_chapters(3)
    p = _digest(p, "ch1", [_hook(1, "open")])

    retention = get_ledger(p)["retention"]
    assert retention["evictedNow"] == {}
    assert set(retention["evictedTotal"].values()) <= {0}
    assert "note" not in retention, "没丢东西就不要报警"


def test_retention_survives_the_ledger_round_trip():
    """`retention` 必须被 get_ledger 放行，否则读一次就没了。"""
    p = _project_with_chapters(3)
    p = _digest(p, "ch1", [_hook(1, "open")])

    raw = p.writingLedger
    assert raw.get("retention"), "写进去了"
    assert get_ledger(p)["retention"], "读得回来"


def test_evicted_total_is_cumulative_not_per_run():
    """第 41 章丢的那条，到第 42 章再算时 `evictedNow` 是 0——只看本次会得出
    "从没丢过"的错误结论，所以累计值必须单独记。"""
    p = _project_with_chapters(45)
    p = _digest(p, "ch1", [_hook(1, "open")])
    # 一次性堆到超过未回收硬上限，制造真实丢弃
    ledger = get_ledger(p)
    ledger["foreshadows"] = [_hook(i, "open") for i in range(_MAX_OPEN_FORESHADOWS + 3)]
    p = set_ledger(p, ledger)

    # 用"重复已存在的钩子"入库：账本里匹配到就原地更新，不会新增行，因此这一轮
    # 的丢弃数只由超限决定（不带 llm_foreshadows 会走章末钩子自动派生，多出一条）。
    dup = [{"hook": "钩子0", "status": "open"}]
    p = _digest(p, "ch2", dup)
    first = get_ledger(p)["retention"]
    assert first["evictedNow"]["open"] == 3
    assert first["evictedTotal"]["open"] == 3

    # 再保存一次：这次没有新的丢弃，但累计值不该被清零
    p = _digest(p, "ch3", dup)
    second = get_ledger(p)["retention"]
    assert second["evictedNow"].get("open", 0) == 0
    assert second["evictedTotal"]["open"] == 3, "累计值被清零就等于把丢失痕迹抹掉了"
    assert "note" in second, "累计丢失不为 0 时，提示要一直在"


# ------------------------------------------------- 硬锚块：整段让位，不许中段切一刀


def test_bulky_facts_do_not_swallow_the_foreshadow_section():
    """真实缺陷回归：章节事实摘要体积最大且排在最前，原来的 `text[:limit-12]`
    会把后面的整段静默吃掉——最该在场的"未回收伏笔"因此根本不在提示词里。"""
    p = _project_with_chapters(45)
    for i in range(1, 46):
        p = _digest(p, f"ch{i}", [_hook(i, "open")])

    block = format_ledger_for_agent(get_ledger(p), chapters=p.chapters)

    assert "未回收伏笔" in block, "整段被吃掉过，必须钉住"
    assert "钩子1" in block
    assert "已埋 44 章未回收" in block


def test_omitted_sections_are_named_in_the_block():
    """省了哪几段要写在块尾（与 global_memory 的口径一致），不许静默。"""
    p = _project_with_chapters(45)
    for i in range(1, 46):
        p = _digest(p, f"ch{i}", [_hook(i, "open")])

    block = format_ledger_for_agent(get_ledger(p), chapters=p.chapters, limit=1200)

    assert "已省去" in block
    assert "未回收伏笔" in block, "最高优先级那段永远不该被省掉"


def test_short_ledger_output_is_unchanged_by_the_priority_rules():
    """反方向：装得下的时候，输出必须与原来的段序一致（提示词位置本身有讲究）。"""
    p = _project_with_chapters(3)
    p = _digest(p, "ch1", [_hook(1, "open")])

    block = format_ledger_for_agent(get_ledger(p), chapters=p.chapters)

    assert "已省去" not in block
    order = [
        block.index("### 章节事实摘要"),
        block.index("### 角色状态快照"),
        block.index("### 未回收伏笔"),
    ]
    assert order == sorted(order), "段序必须还是 事实→状态→伏笔"
