"""保存链路上的设定条目：scoped save 只合并客户端声明的 sections。

前端 `SECTION_KEYS` 与后端 `MERGE_SECTIONS` 是两份手写名单，任何一边漏了
`loreEntries`，用户在编辑器里加的设定就会**静默不保存**（保存请求成功、内容没变）。
这条测试把两边钉在一起。
"""

from __future__ import annotations

from app.core.project import normalize_project
from app.services.projects import MERGE_SECTIONS, merge_project_changes


def _entry(title: str, body: str = "正文") -> dict:
    return {"id": f"le-{title}", "title": title, "body": body, "keywords": [title]}


def test_merge_sections_include_lore_entries():
    assert "loreEntries" in MERGE_SECTIONS


def test_scoped_save_persists_lore_entries():
    server = normalize_project({"id": "p1", "title": "T"})
    client = normalize_project(
        {"id": "p1", "title": "T", "loreEntries": [_entry("青云门")]}
    )
    merged = merge_project_changes(server, client, [], ["loreEntries"])
    assert [e.title for e in (merged.loreEntries or [])] == ["青云门"]


def test_undeclared_section_keeps_server_version():
    """没声明的 section 必须保留服务端版本 —— 不然并发编辑会互相覆盖。"""
    server = normalize_project(
        {"id": "p1", "title": "T", "loreEntries": [_entry("服务端条目")]}
    )
    client = normalize_project(
        {"id": "p1", "title": "T", "loreEntries": [_entry("客户端条目")]}
    )
    merged = merge_project_changes(server, client, [], ["title"])
    assert [e.title for e in (merged.loreEntries or [])] == ["服务端条目"]


def test_lore_entries_survive_a_plain_normalize():
    vn = normalize_project(
        {"id": "p1", "title": "T", "loreEntries": [_entry("夺魂案", "两百年前旧案")]}
    )
    again = normalize_project(vn.model_dump())
    assert again.loreEntries and again.loreEntries[0].body == "两百年前旧案"


def test_pinned_and_priority_round_trip():
    vn = normalize_project(
        {
            "id": "p1",
            "title": "T",
            "loreEntries": [
                {"id": "le1", "title": "铁律", "body": "不写主角杀人", "pinned": True, "priority": 5}
            ],
        }
    )
    e = (vn.loreEntries or [])[0]
    assert e.pinned is True and e.priority == 5
    assert normalize_project(vn.model_dump()).loreEntries[0].pinned is True


def test_aliases_survive_on_characters_and_locations():
    vn = normalize_project(
        {
            "id": "p1",
            "title": "T",
            "characters": [
                {"id": "c1", "defineName": "c1", "displayName": "雪见", "aliases": ["阿雪"]}
            ],
            "locations": [{"id": "l1", "name": "镜湖", "aliases": ["镜湖水"]}],
        }
    )
    assert vn.characters[0].aliases == ["阿雪"]
    assert (vn.locations or [])[0].aliases == ["镜湖水"]
