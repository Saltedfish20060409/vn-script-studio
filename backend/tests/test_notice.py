"""公告接口：历史列表 + 最新一版（免登录）。

关键契约：
- 顶层必须保留最新一版的 version/title/updatedAt/sections —— 浏览器里可能还缓存着
  旧前端，字段搬家会让它渲染空白；
- announcements 必须按 version 倒序，第一条就是最新的（前端默认展示它）。
"""

from __future__ import annotations

from app.api.v1.notice import ANNOUNCEMENTS, LATEST, NOTICE, get_notice


def test_latest_fields_are_still_at_top_level():
    """旧前端（localStorage 已读判断 + 渲染 sections）读的就是这几个字段。"""
    assert NOTICE["version"] == LATEST["version"]
    assert NOTICE["title"] == LATEST["title"]
    assert NOTICE["updatedAt"] == LATEST["updatedAt"]
    assert NOTICE["sections"] == LATEST["sections"]
    assert NOTICE["sections"], "最新一版得有内容"


def test_announcements_are_newest_first_and_include_latest():
    assert NOTICE["announcements"] is ANNOUNCEMENTS
    versions = [a["version"] for a in ANNOUNCEMENTS]
    assert versions == sorted(versions, reverse=True), "公告必须按版本倒序"
    assert ANNOUNCEMENTS[0] is LATEST


def test_every_announcement_is_well_formed():
    for a in ANNOUNCEMENTS:
        assert isinstance(a["version"], int) and a["version"] > 0
        assert a["title"].strip()
        assert len(a["updatedAt"]) == 10 and a["updatedAt"][4] == "-", a["updatedAt"]
        assert a["sections"], f"v{a['version']} 没有内容"
        for s in a["sections"]:
            assert s["heading"].strip(), f"v{a['version']} 有空标题"
            assert s["body"].strip(), f"v{a['version']} 的「{s['heading']}」正文为空"


def test_versions_are_unique():
    versions = [a["version"] for a in ANNOUNCEMENTS]
    assert len(versions) == len(set(versions)), f"版本号重复：{versions}"


def test_history_is_preserved():
    """用户要能在公告里翻到以前那几版，所以欢迎公告必须还在。"""
    welcome = [a for a in ANNOUNCEMENTS if "欢迎" in a["title"]]
    assert welcome, "历史公告（欢迎 / 起步指导）被删掉了"


def test_endpoint_returns_the_same_object_shape():
    import asyncio

    payload = asyncio.run(get_notice())
    assert payload["version"] == LATEST["version"]
    assert len(payload["announcements"]) == len(ANNOUNCEMENTS)
