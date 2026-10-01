"""判定侧（`style_guide.md` / `style_skill`）的两处卫生问题。

两块毛病都是 2026-10 实测出来的，各自都有明确的失败方式：

**一、禁用表被自动抓取污染（33 条种子 → 108 条）**
`_extract_banned` 曾用 `re.findall(r"[「「]([^」」]{2,24})[」」]", text)` 把整份文档里所有
「」引号内容都当禁用词，于是指南自己树为标杆的句子（范例 A/B/C、若干 ✅ 正面例）以及
章节小标题的普通词（为什么 / 解释 / 经过 / 目的 / 温度 / 毛边 / 收尾）全进了禁用表。
后果不是"更严格"，而是 `lint` 会对着**照着指南写出来的最好句子**报违规。

**二、`prompt_block` 说要保却只会切**
它用 `body[:max_chars-24]` 尾部切片，切掉的正好是 §三 禁用词（offset 2679）与
§六 参考范例（3687），块尾却写着"禁用词与检查清单仍须遵守"——要求模型遵守一份
它看不见的清单。注释里写的 `Prefer keeping principles + banned + post-check` 从未实现。
"""
from __future__ import annotations

import re

from app.core.pipeline.style_skill import (
    _MUST_KEEP,
    _extract_banned,
    _normalize_banned,
    lint_style_skill,
    load_style_skill,
)

#: 被旧抓取逻辑误收进来的东西。它们**必须**不在禁用表里。
_POLLUTION = [
    # 指南 §六 的三个范例
    "雨很大。你肯定会淋湿。",
    "你会生病吗？",
    "走了。",
    "伞……你拿去。",
    # ✅ 正面例
    "第二天早上。",
    "他手上的动作停了一下。",
    "他把那件外套挂在了她房间门口的挂钩上。",
    "这里和刚才不一样了",
    "……红的咸，白的甜。你自己尝。",
    # 章节小标题 / 被引用的普通词
    "为什么",
    "解释",
    "经过",
    "目的",
    "温度",
    "毛边",
    "收尾",
    "在做什么",
    "开灯",
    "算了",
]


# ---- 一、禁用表必须是手工维护的短表 --------------------------------------------


def test_banned_table_is_a_short_hand_maintained_list():
    banned = load_style_skill().banned_phrases
    # 旧值是 108（其中 75 条是抓来的）。种子 33 + §三 条目去重后应在此量级。
    assert len(banned) <= 60, f"禁用表又肿了（{len(banned)} 条），是不是又有人往正文里抓了？"
    assert len(banned) >= 30, "缩得太狠，说明 §三 没被解析到"


def test_no_harvested_pollution_left_in_the_banned_table():
    banned = set(load_style_skill().banned_phrases)
    still = [p for p in _POLLUTION if p in banned]
    assert not still, "这些不是禁用词，是被抓进来的正文：" + "、".join(still)


def test_real_violations_are_still_caught():
    """清污染不能把真规则一起清掉。"""
    banned = set(load_style_skill().banned_phrases)
    for real in ("内心OS", "愣了一下", "微微一怔", "原来如此", "我明白了", "点了点头", "嘴角勾起"):
        assert real in banned, real
    # 端到端：命中要有 issue
    issues = lint_style_skill("他愣了一下，点了点头。")
    assert issues, "真违规不该漏"
    codes = {i.code for i in issues}
    assert "style_donot" in codes


def test_annotated_entries_are_normalized_so_they_actually_match():
    """`很多事都这样（单独成段的收尾金句）` 用子串永远匹配不到——这条规则以前从没生效过。"""
    assert _normalize_banned("很多事都这样（单独成段的收尾金句）") == "很多事都这样"
    assert _normalize_banned("不是A，是B（纠偏连环）") == "不是A，是B"
    assert _normalize_banned("空气突然安静") == "空气突然安静"
    banned = set(load_style_skill().banned_phrases)
    assert "很多事都这样" in banned
    assert "不是A，是B" in banned
    assert lint_style_skill("很多事都这样。"), "归一化之后这条规则应该能命中了"


def test_extract_banned_only_reads_seed_and_the_banned_section():
    """正面反例各来一条：抓取只认 §三，别的地方的引号一概不算。"""
    text = (
        "## 一、核心原则\n"
        "❌「这句话不该被禁」 ✅「这句也不该」\n\n"
        "## 三、禁用词 / 句式\n"
        "- 内心OS\n"
        "- 空气突然安静\n"
    )
    banned = _extract_banned(text)
    assert "内心OS" in banned and "空气突然安静" in banned
    assert "这句话不该被禁" not in banned
    assert "这句也不该" not in banned


# ---- 二、prompt_block：整节取用，且不谎报 --------------------------------------


def _sections_in(block: str) -> list[str]:
    return re.findall(r"^##\s+([一二三四五六七八]、[^\n]+)", block, re.M)


def _omitted_in(block: str) -> list[str]:
    m = re.search(r"未收入：(.+?)；", block)
    return [x.strip() for x in m.group(1).split(" · ")] if m else []


def test_block_always_carries_the_banned_list_and_the_examples():
    """这是核心回归：旧实现在 2000 字预算下把 §三 与 §六 整段切掉了。"""
    skill = load_style_skill()
    for budget in (2000, 1800, 2400):
        block = skill.prompt_block(max_chars=budget)
        assert "三、禁用词" in block, f"budget={budget} 丢了禁用清单"
        assert "六、参考范例" in block, f"budget={budget} 丢了三条例句"
        assert "五、生成后检查" in block, f"budget={budget} 丢了落笔自检"


def test_block_never_claims_a_section_it_did_not_include():
    """块尾那句"未收入"必须与正文对得上——两头都不许说谎。"""
    skill = load_style_skill()
    for budget in (4500, 2400, 2000, 1800, 1200, 800):
        block = skill.prompt_block(max_chars=budget)
        inside = "".join(_sections_in(block))
        for name in _omitted_in(block):
            key = name.split("（")[0].strip()
            assert key not in inside, f"budget={budget} 声称省了「{name}」，其实在里面"


def test_filler_never_squeezes_out_a_must_keep_section():
    """必保项缺了就不要再塞填充节：一份"有流水线摘要、却没有禁用清单"的检查块最误导人。"""
    skill = load_style_skill()
    for budget in (1200, 800, 400):
        block = skill.prompt_block(max_chars=budget)
        inside = _sections_in(block)
        dropped = [k for k in _MUST_KEEP if not any(k in h for h in inside)]
        if dropped:
            # 只要丢了必保项，就不该有任何非必保节混进来
            extra = [h for h in inside if not any(k in h for k in _MUST_KEEP)]
            assert not extra, f"budget={budget} 丢了 {dropped} 却还塞了 {extra}"


def test_tightest_budget_still_returns_something_real():
    block = load_style_skill().prompt_block(max_chars=200)
    assert len(block) > 200, "第一节应当无条件进，宁可超预算也不能是空壳"
    assert "一、核心原则" in block
