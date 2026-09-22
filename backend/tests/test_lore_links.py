"""设定条目实体链接 + 关系图第二跳（沿边检索）。

背景：条目原来只有触发词，是孤岛——提问里没出现那个词就永远进不来。
加了 links 之后应该能：
- 命中条目 → 把它点名的角色/地点带进上下文（**前提是它们本来没进**）；
- 命中角色 → 把点名它的条目补进来（反向）。

注意：角色/地点本来就有"前 3/前 4 名无条件带进来"的兜底，所以小项目里
这部分看起来像没生效。测试要造**足够多的角色/地点**，让被链接的那个确实落在兜底之外。
"""

from __future__ import annotations

from app.core.agent_context import build_agent_context
from app.core.demo import create_demo_project
from app.domain.types import Character, CharacterLink, Location, LoreEntry


def _big_project(n_chars: int = 8, n_locs: int = 8):
    """造一个角色/地点足够多的项目，让"没被点名"的实体真的落在兜底之外。"""
    p = create_demo_project()
    chars = list(p.characters)
    for i in range(n_chars):
        chars.append(
            Character(
                id=f"c{i}",
                defineName=f"c{i}",
                displayName=f"配角{i}",
                color="#6b7280",
                voice=f"配角{i}的口吻：干脆利落。",
            )
        )
    p.characters = chars
    p.locations = [
        Location(id=f"loc{i}", name=f"地点{i}", description=f"地点{i}的说明") for i in range(n_locs)
    ]
    p.loreEntries = []
    return p


def test_hit_entry_brings_its_linked_entities():
    """命中条目 → 它点名的角色/地点进上下文（它们本来没被点名）。"""
    p = _big_project()
    p.loreEntries = [
        LoreEntry(
            id="L1",
            title="灯影巷旧事",
            body="灯影巷里那件事没人愿意提。",
            keywords=["灯影巷"],
            links=[
                {"toType": "character", "toId": "c5"},
                {"toType": "location", "toId": "loc5"},
            ],
        )
    ]
    ctx = build_agent_context(
        p,
        chapterId=p.chapters[0].id,
        userMessage="灯影巷",
        task="scene",
    )
    assert "配角5" in ctx.text, "条目点名的角色没被带进来"
    assert "地点5" in ctx.text, "条目点名地点没被带进来"
    assert any("条目关联" in x for x in ctx.included)


def test_no_duplicate_when_entity_already_in_context():
    """已经在上下文里的实体不重复列一遍（省预算）。"""
    p = _big_project()
    # c0 属于兜底的前几名，本来就会进上下文
    p.loreEntries = [
        LoreEntry(
            id="L1",
            title="旧事",
            body="x",
            keywords=["旧事"],
            links=[{"toType": "character", "toId": "c0"}],
        )
    ]
    ctx = build_agent_context(p, chapterId=p.chapters[0].id, userMessage="旧事", task="scene")
    assert "点名关联" not in ctx.text


def test_entry_linked_to_a_picked_character_is_pulled_in():
    """反向：命中了角色 → 点名它的条目补进来（即使触发词没命中）。"""
    p = _big_project()
    p.loreEntries = [
        LoreEntry(
            id="L1",
            title="主角的旧伤",
            body="主角左肩有一道旧伤，阴天会疼。",
            keywords=["完全不会被问到的词"],
            links=[{"toType": "character", "toId": p.characters[0].id}],
        )
    ]
    name = p.characters[0].displayName
    ctx = build_agent_context(p, chapterId=p.chapters[0].id, userMessage=f"{name}今天怎么样", task="scene")
    assert "主角左肩有一道旧伤" in ctx.text, "反向关联没把条目带进来"
    assert any("关联条目" in x for x in ctx.included)


def test_two_hop_relations_for_consistency_and_scene_only():
    """第二跳只给需要跨章对照的任务（consistency / scene），其它任务保持 1 跳。"""
    p = _big_project()
    a, b, c = p.characters[0].id, "c1", "c2"
    # 用真模型构造（直接塞 dict 会绕过校验，而这段代码按对象取属性）
    p.characterLinks = [
        CharacterLink(id="l1", fromId=a, toId=b, label="朋友"),
        CharacterLink(id="l2", fromId=b, toId=c, label="师父"),
    ]
    ask = f"{p.characters[0].displayName}"

    scene = build_agent_context(p, chapterId=p.chapters[0].id, userMessage=ask, task="scene")
    assert "（间接）" in scene.text, "scene 任务应该有第二跳"

    chat = build_agent_context(p, chapterId=p.chapters[0].id, userMessage=ask, task="chat")
    assert "（间接）" not in chat.text, "chat 任务不该做第二跳（省预算）"


def test_links_are_optional_and_backwards_compatible():
    """老数据没有 links 字段也必须照常工作。"""
    p = _big_project()
    p.loreEntries = [LoreEntry(id="L1", title="老条目", body="x", keywords=["老条目"])]
    ctx = build_agent_context(p, chapterId=p.chapters[0].id, userMessage="老条目", task="scene")
    assert "老条目" in ctx.text
    assert "设定条目关联到" not in ctx.text
