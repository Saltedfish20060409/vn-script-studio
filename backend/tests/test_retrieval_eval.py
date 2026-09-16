"""检索评测（回归用）：给"写了上百万字设定"的作者，问一句话能不能取到对的那几条。

跑的是 `build_agent_context` 真身（Agent 每轮用的就是它），语料见 `_retrieval_corpus.py`：
40 角色（12 个带别名）/ 30 地点 / 80 条设定条目 / 20 章 / 关系链。

三类断言：
1. **触发词与别名**：问"阿雪…"要命中雪见；问"九幽诀的反噬"要命中该条目。
   —— 这两条是"换个说法就搜不到"的直接修复。
2. **链接扩展**：命中角色时，直接关系要一起带进来（避免写错立场）。
3. **不挤占预算**：上下文长度不能因为条目多而爆掉。
"""

from __future__ import annotations

import _retrieval_corpus as corpus  # noqa: I001  (tests/ 在 sys.path 上)

from app.core.agent_context import build_agent_context
from app.core.project import normalize_project


def _ctx(project, question: str, **kw) -> str:
    return build_agent_context(
        project,
        chapterId=project.chapters[0].id if project.chapters else None,
        userMessage=question,
        task="chat",
        **kw,
    ).text


def _project(**overrides):
    raw = corpus.build_project()
    raw.update(overrides)
    return normalize_project(raw)


def test_lore_entries_survive_normalization():
    """新字段必须活着穿过 normalize_project —— 否则编辑器里存了、检索里看不见。"""
    p = _project()
    expected = len(corpus.LORE_ENTRIES) + len(corpus.TRIGGER_ONLY_ENTRIES)
    assert len(p.loreEntries) == expected
    assert p.loreEntries[0].title == corpus.LORE_ENTRIES[0][0]
    assert p.loreEntries[0].keywords
    assert p.characters[0].aliases == corpus.NAMED_CHARACTERS[0][1]


def test_keyword_question_hits_the_right_entry():
    p = _project()
    out = build_agent_context(
        p, chapterId=p.chapters[0].id, userMessage="九幽诀的反噬症状是什么？", task="chat"
    )
    text = out.text
    assert "九幽诀" in text
    # 毫无关系的条目（北洋航路图是第 4 条噪声）正文不该跟进来；
    # 未命中的条目只以标题形式出现在末尾"可点名"提示里，所以查的是它正文里的标记。
    assert "noise-4）" not in text, "无关条目被搜进来了"
    n_entries = int(next(i.split("×")[1] for i in out.included if i.startswith("设定条目×")))
    assert n_entries <= 4, f"80 条里进来了 {n_entries} 条，检索没收敛"


def test_alias_in_question_hits_the_character():
    p = _project()
    text = _ctx(p, "阿雪当年差点被逐出山门是怎么回事？")
    assert "雪见" in text, "问别名没命中本人"
    # 别名的强命中应该压过正文里的巧合：雪见要排在角色区里
    head, _, _ = text.partition("## Locations")
    assert "雪见" in head


def test_alias_disabled_loses_the_hit():
    """对照组：去掉别名，只问别名就命中不了 —— 证明别名确实在起作用。

    选一个排名靠后的角色（陆离是第 8 位），因为"命中为空时兜底带前 3 个角色"这条
    会让排前面的角色无论如何都出现，拿它做对照测不出差别。
    """
    raw = corpus.build_project()
    no_alias_chars = [dict(c) for c in raw["characters"]]
    for c in no_alias_chars:
        c.pop("aliases", None)

    p_with = normalize_project(raw)
    p_without = normalize_project({**raw, "characters": no_alias_chars})

    assert "陆离" in _ctx(p_with, "离公子最近怎么样？"), "带别名时没命中"
    assert "陆离" not in _ctx(p_without, "离公子最近怎么样？"), "去掉别名仍然命中，说明不是别名的功劳"


def test_all_questions_find_something_expected():
    """整体命中率：这是"设定很大也用得动"的底线指标（实测 20/20）。"""
    rows = corpus.evaluate(lambda proj, q: _ctx(proj, q))
    missed = [r.question for r in rows if not r.ok]
    hit_rate = sum(1 for r in rows if r.ok) / len(rows)
    assert hit_rate >= 0.9, f"命中率 {hit_rate:.0%} 低于 90%，漏掉：{missed}"


def test_mechanisms_are_what_make_vague_questions_work():
    """机制专测：只问别名 / 只问口头上叫法时，没有这两个机制就是 0 命中。

    实测：加之前 0/6，只加触发词 3/6，只加别名 3/6，两个都有 6/6。
    这条断言把"这两个机制到底买到了什么"钉住——有人日后动到打分逻辑会立刻红。
    """
    mech = corpus.ALIAS_ONLY_QUESTIONS + corpus.TRIGGER_ONLY_QUESTIONS
    before = corpus.evaluate(
        _ctx, strip_aliases=True, strip_keywords=True, questions=mech
    )
    after = corpus.evaluate(_ctx, questions=mech)
    ok_before = sum(1 for r in before if r.ok)
    ok_after = sum(1 for r in after if r.ok)
    assert ok_after == len(mech), f"机制专测应当全中，实际 {ok_after}/{len(mech)}"
    assert ok_before <= 1, f"关掉机制后还有 {ok_before}/{len(mech)} 命中，说明测试没测到点子上"


def test_character_relations_are_pulled_in():
    p = _project()
    text = _ctx(p, "青哥替人垫了多少银子？")
    assert "## 角色关系" in text
    assert "沈青" in text and "雪见" in text, "命中角色后没带出直接关系"


def test_linked_location_is_listed():
    p = _project()
    text = _ctx(p, "青云山上有什么？")
    assert "青云山" in text
    assert "落霞峰" in text or "镜湖" in text, "没说清相邻/从属地点"


def test_pinned_entries_always_included():
    raw = corpus.build_project()
    raw["loreEntries"] = list(raw["loreEntries"]) + [
        {"id": "le-pin", "title": "铁律：主角不会杀人", "body": "任何情况下都不要写成主角主动杀人。", "pinned": True}
    ]
    p = normalize_project(raw)
    # 问一个跟"铁律"完全无关的问题，钉住的条目也必须进来
    text = _ctx(p, "北洋航路图的季风规律是什么？")
    assert "铁律：主角不会杀人" in text


def test_unmatched_titles_are_listed_as_hint():
    p = _project()
    text = _ctx(p, "九幽诀的反噬症状是什么？")
    assert "另有" in text and "条设定未进上下文" in text, "没有告诉模型还有哪些设定可点名"


def test_context_stays_within_budget():
    p = _project()
    for budget in (6000, 12000, 18000):
        out = build_agent_context(
            p,
            chapterId=p.chapters[0].id,
            userMessage="青云门和太虚宗为什么结怨？",
            task="chat",
            maxChars=budget,
        )
        assert out.charsUsed <= budget * 1.05, f"预算 {budget} 被突破：{out.charsUsed}"
        assert "设定条目" in out.included or any("设定条目" in i for i in out.included)


def test_entries_scoring_prefers_keywords_over_body_noise():
    from app.core.agent_context import _entry_score, _tokenize

    raw = corpus.build_project()["loreEntries"]
    target = next(e for e in raw if e["title"] == "影阁")
    noise = next(e for e in raw if e["title"] == "北洋航路图")
    q = "影阁为什么不接东域的单子？"
    toks = _tokenize(q.lower())
    assert _entry_score(type("E", (), target)(), q.lower(), toks) > _entry_score(
        type("E", (), noise)(), q.lower(), toks
    )
