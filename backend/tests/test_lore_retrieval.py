"""设定条目的「AI 自己取」与「AI 只能提议」两条链路。

对应宣传视频评论里的两个痛点：
- 「提问时自动检索调取对应设定文档」——自动注入之外，模型还要能在同一轮里自己捞出没带上的条目；
- 「全是 AI 自己生成的设定，编辑自由度太小」——AI 永远不能直接写设定库，只能提议、由作者逐条接受。
"""

from __future__ import annotations

from app.core.agent import apply_agent_actions
from app.core.agent_context import (
    build_agent_context,
    lore_entry_index,
    rank_lore_entries,
)
from app.core.agent_tools import TOOL_SPECS, run_agent_tool
from app.core.demo import create_demo_project
from app.core.fact_extract import (
    accept_lore_entry,
    existing_dedupe_keys,
    lore_dedupe_key,
)
from app.domain.types import LoreEntry


def _project():
    p = create_demo_project()
    p.loreEntries = [
        LoreEntry(
            id="L1",
            title="青云门",
            body="青云门是正道第一大派，掌门玄真，本部在青云山。",
            keywords=["青云", "青云门", "掌门"],
        ),
        LoreEntry(
            id="L2",
            title="夺魂案",
            body="三年前夺魂案死七人，凶手至今未获。",
            keywords=["夺魂案"],
        ),
        LoreEntry(id="L3", title="镜湖封印推演", body="镜湖下有封印，百年一松动。"),
        LoreEntry(id="L4", title="铁律", body="不得提及先帝。", pinned=True),
    ]
    return p


# ---------------------------------------------------------------------------
# 工具：模型自己取设定
# ---------------------------------------------------------------------------


def test_search_lore_tool_is_advertised():
    names = [t["name"] for t in TOOL_SPECS]
    assert "search_lore" in names
    assert "get_lore_entry" in names


def test_search_lore_returns_body_of_matching_entry():
    ok, out = run_agent_tool("search_lore", {"query": "青云门的掌门是谁"}, project=_project())
    assert ok
    assert "青云门" in out
    assert "掌门玄真" in out
    assert "夺魂案" not in out


def test_search_lore_can_hit_entry_without_keywords():
    """没填触发词的条目也得能被检索到（用户不该被迫理解「触发词」）。"""
    ok, out = run_agent_tool("search_lore", {"query": "镜湖"}, project=_project())
    assert ok
    assert "镜湖封印推演" in out


def test_search_lore_falls_back_to_title_index():
    """没命中不能干等：把可点名的标题给它，避免模型自己编一条设定。"""
    ok, out = run_agent_tool("search_lore", {"query": "宇宙飞船"}, project=_project())
    assert ok
    assert "没有命中" in out
    assert "夺魂案" in out and "镜湖封印推演" in out


def test_search_lore_empty_query_lists_index():
    ok, out = run_agent_tool("search_lore", {}, project=_project())
    assert ok
    assert "索引" in out
    for title in ("青云门", "夺魂案", "镜湖封印推演", "铁律"):
        assert title in out


def test_search_lore_without_entries_is_not_an_error():
    p = create_demo_project()
    p.loreEntries = []
    ok, out = run_agent_tool("search_lore", {"query": "任何"}, project=p)
    assert ok
    assert "还没有设定条目" in out


def test_get_lore_entry_by_title_alias_and_id():
    p = _project()
    for ref in ("夺魂案", "L2", "夺魂"):
        ok, out = run_agent_tool("get_lore_entry", {"ref": ref}, project=p)
        assert ok, ref
        assert "三年前夺魂案死七人" in out, ref


def test_get_lore_entry_missing_returns_index_not_error_text():
    ok, out = run_agent_tool("get_lore_entry", {"ref": "不存在的条目"}, project=_project())
    assert ok is False
    assert "未找到设定条目" in out
    assert "青云门" in out  # 仍然给出可选清单


def test_pinned_entry_is_not_returned_by_search():
    """钉住的条目每轮自动带上，不该再被工具重复取一遍（省 context）。"""
    hits = rank_lore_entries(_project().loreEntries, "铁律", limit=8)
    titles = [str(e.title) for e, _ in hits]
    assert "铁律" not in titles


def test_tool_and_injection_use_the_same_ruler():
    """工具命中什么，自动检索就该带什么——两把尺子会自相矛盾。"""
    p = _project()
    query = "夺魂案"
    ctx = build_agent_context(p, chapterId=p.chapters[0].id, userMessage=query, task="chat")
    hits = [str(e.title) for e, _ in rank_lore_entries(p.loreEntries, query)]
    assert "夺魂案" in hits
    assert "夺魂案" in ctx.text
    assert any("设定条目" in x for x in includedDetails_labels(ctx))


def test_lore_entry_index_marks_pinned():
    idx = lore_entry_index(_project().loreEntries)
    assert "铁律 ☆钉住" in idx
    assert "青云门（青云/青云门/掌门）" in idx


def includedDetails_labels(ctx):  # noqa: ANN001, ANN201 - tiny test helper
    return [d.get("label", "") for d in (ctx.includedDetails or [])]


# ---------------------------------------------------------------------------
# 提议：AI 只能进待审列表
# ---------------------------------------------------------------------------


def test_propose_lore_entries_creates_inbox_items_without_touching_library():
    p = _project()
    before = len(p.loreEntries)
    result = apply_agent_actions(
        p,
        [
            {
                "op": "propose_lore_entries",
                "entries": [
                    {"title": "玄真", "body": "青云门掌门，性情冷。"},
                    {"title": "封印来历", "body": "封印源自百年前的镜湖之乱。"},
                ],
            }
        ],
    )
    # 设定库没被改动
    assert len(result.project.loreEntries) == before
    # 但进了待审
    assert len(result.inbox_proposals) == 2
    kinds = {x["kind"] for x in result.inbox_proposals}
    assert kinds == {"lore_entry"}
    first = result.inbox_proposals[0]
    assert first["payload"]["title"] == "玄真"
    assert first["dedupe_key"] == lore_dedupe_key("玄真")
    assert any("提议设定条目" in x for x in result.applied)


def test_propose_lore_entries_normalizes_keywords_and_skips_bad_rows():
    p = _project()
    result = apply_agent_actions(
        p,
        [
            {
                "op": "propose_lore_entries",
                "entries": [
                    {"body": "没有标题，应该被跳过"},
                    "不是对象",
                    {"title": "门规", "keywords": ["门规", "", "   ", "青云戒律"]},
                ],
            }
        ],
    )
    assert len(result.inbox_proposals) == 1
    payload = result.inbox_proposals[0]["payload"]
    assert payload["title"] == "门规"
    assert payload["keywords"] == ["门规", "青云戒律"]


def test_propose_lore_entries_missing_entries_is_skipped_not_crashed():
    result = apply_agent_actions(_project(), [{"op": "propose_lore_entries"}])
    assert result.inbox_proposals == []
    assert any("propose_lore_entries" in x for x in result.skipped)


def test_there_is_still_no_direct_lore_write_op():
    """守住这条线：AI 永远不能直接写设定库（这是「编辑自由度」的底线）。

    写成行为测试而不是字符串检查——提示词里为了叮嘱模型，本来就写了
    「没有 add_lore 这个 op」这句话，字符串匹配会误判。
    """
    p = _project()
    before = [e.title for e in p.loreEntries]
    for op in ("add_lore", "update_lore", "delete_lore"):
        result = apply_agent_actions(
            p, [{"op": op, "title": "洗剑池", "body": "不该被写进去"}]
        )
        assert [e.title for e in result.project.loreEntries] == before, op
        assert any(op in x or "未知" in x for x in result.skipped), op


# ---------------------------------------------------------------------------
# 接受：作者点确认后才进设定库
# ---------------------------------------------------------------------------


def test_accept_lore_entry_writes_and_dedupes_by_title():
    p = _project()
    before = len(p.loreEntries)
    p2 = accept_lore_entry(p, title="玄真", body="青云门掌门。", keywords=["玄真", "掌门"])
    assert len(p2.loreEntries) == before + 1
    added = p2.loreEntries[-1]
    assert added.title == "玄真"
    assert added.keywords == ["玄真", "掌门"]
    # 同名再来一次不重复添加（作者不会看到两个「玄真」）
    p3 = accept_lore_entry(p2, title=" 玄真 ", body="重复的")
    assert len(p3.loreEntries) == before + 1


def test_existing_dedupe_keys_includes_lore_titles():
    keys = existing_dedupe_keys(_project())
    assert lore_dedupe_key("青云门") in keys
    assert lore_dedupe_key("夺魂案") in keys


def test_accepted_entry_is_immediately_retrievable():
    """接受之后立刻就能被检索到（不用等下一次重建上下文）。"""
    p = accept_lore_entry(_project(), title="洗剑池", body="洗剑池在后山，水深三丈。")
    ok, out = run_agent_tool("search_lore", {"query": "洗剑池"}, project=p)
    assert ok
    assert "水深三丈" in out
