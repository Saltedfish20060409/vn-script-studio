"""静态 WritingStrategyProfile：档位解析与硬锚前置块。"""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.pipeline.ledger import auto_digest_ledger, get_ledger
from app.core.writing_strategy import (
    WritingStrategyProfile,
    apply_strategy_to_ledger_block,
    critical_anchors_block,
    profile_from_assist,
    reasoning_framing_extra,
    resolve_writing_strategy,
)


def test_assist_strength_maps_to_tiers():
    strong = profile_from_assist("strong")
    assert strong.attention == "low"
    assert strong.memory == "low"
    weak = profile_from_assist("weak")
    assert weak.attention == "high"
    assert weak.reasoning == "high"


def test_resolve_defaults_to_shortboard_compensation():
    p = resolve_writing_strategy()
    assert p.attention == "low"
    assert p.memory == "low"


def test_critical_anchors_and_strategy_block_for_low_attention():
    from app.core.writing_strategy import (
        CRITICAL_ANCHOR_CLOSE,
        CRITICAL_ANCHOR_OPEN,
    )

    p = auto_digest_ledger(create_demo_project())
    ledger = get_ledger(p)
    crit = critical_anchors_block(ledger, top_k=5, chapters=p.chapters)
    # demo 有角色状态或伏笔之一即可
    base = "## 项目硬锚（写作账本·不得推翻已确认事实）\n### 角色状态快照（最近）\n- x"
    low = apply_strategy_to_ledger_block(
        base,
        ledger,
        profile=WritingStrategyProfile(attention="low", memory="low", reasoning="mid"),
        chapters=p.chapters,
    )
    high = apply_strategy_to_ledger_block(
        base,
        ledger,
        profile=WritingStrategyProfile(attention="high", memory="high", reasoning="high"),
        chapters=p.chapters,
    )
    assert "必须遵守" in low or "截至本章" in low
    assert "必须遵守" not in high
    assert "截至本章" not in high
    # crit 可能为空（空账本），但 demo digest 后通常有内容
    if crit:
        assert "必须遵守" in crit or "未回收" in crit or "角色状态" in crit
        assert crit.startswith(CRITICAL_ANCHOR_OPEN)
        assert crit.rstrip().endswith(CRITICAL_ANCHOR_CLOSE)


def test_critical_anchors_respect_budget():
    from app.core.writing_strategy import CRITICAL_ANCHOR_OPEN

    ledger = {
        "foreshadows": [
            {"id": f"f{i}", "hook": "钩子" + ("详" * 40), "status": "open"}
            for i in range(8)
        ],
        "characterStates": [
            {
                "characterName": f"角色{i}",
                "emotion": "平静" * 10,
                "body": "站立" * 10,
            }
            for i in range(6)
        ],
    }
    tiny = critical_anchors_block(ledger, top_k=5, budget_chars=180)
    assert tiny.startswith(CRITICAL_ANCHOR_OPEN)
    assert len(tiny) <= 180 + 8  # 截断容差
    assert tiny.count("- ") <= 5


def test_reasoning_framing_only_for_continue_rewrite():
    assert "分步" in reasoning_framing_extra("continue")
    assert "分步" in reasoning_framing_extra("rewrite")
    assert reasoning_framing_extra("polish") == ""
