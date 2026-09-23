"""稿件体检：`POST /analysis/novel-audit` + `novel_audit` 工具 + 轻小说起步模板。

为什么值得单独测：
- 这两个检查是**离线**的（纯正则/计数），却很容易在接线路由时被写错参数名或
  在 parts 过滤上静默返回空结果——界面会显示"没有问题"，那是比报错更坏的结果。
- 轻小说模板是"函数式模板"（每次调用都是新对象，章节 id 被设定条目 links / 写作账本 /
  运行记录引用着）。它一旦误走 `build_from_template` 的重新分配 id 分支，
  引用就会断（正文还在，但账本与设定条目全部指空），所以要把这条约束锁住。
"""

from __future__ import annotations

import asyncio

import db_gate
import pytest

from app.core.agent_tools import run_agent_tool
from app.core.project import normalize_project
from app.core.templates import TEMPLATES, build_from_template, list_template_meta

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()


def _project_with_text() -> object:
    """一份"有真问题"的最小稿子：引号不配对 + 半角逗号贴汉字 + `--` 当破折号。"""
    return normalize_project(
        {
            "id": "proj-audit",
            "title": "体检样本",
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "prose": (
                        "雨停了,他站在月台上。\n"
                        "「走吧。」她说。\n"
                        "他点了点头--那种习惯性的点头。\n"
                        "「那明天呢？\n"
                    ),
                },
                {
                    "id": "ch2",
                    "title": "第二章",
                    "prose": "第二天下雨了。\n他还是在等。\n",
                },
            ],
        }
    )


# ---- 1. 轻小说模板 ---------------------------------------------------------


def test_ln_template_is_listed_with_metadata():
    """模板列表里能看到轻小说起步工程（选择器直接读这个接口）。"""
    meta = {m["id"]: m for m in list_template_meta()}
    assert "light_novel" in meta
    assert meta["light_novel"]["title"]
    assert meta["light_novel"]["genre"]
    assert meta["light_novel"]["logline"]
    assert meta["light_novel"]["characters"]


def test_ln_template_keeps_chapter_references_intact():
    """函数式模板不走 id 重分配：章节 id 变了，设定条目/账本/运行记录的引用就断了。"""
    fresh = build_from_template("light_novel")
    chapter_ids = {c.id for c in fresh.chapters}
    assert chapter_ids, "轻小说模板必须带章节"

    # 设定条目的 links 必须指到真实存在的章节
    for entry in fresh.loreEntries or []:
        for link in getattr(entry, "links", None) or []:
            raw = link if isinstance(link, dict) else link.model_dump()
            if raw.get("toType") == "chapter":
                assert raw.get("toId") in chapter_ids, f"设定条目 links 指向了不存在的章节：{raw}"

    # 账本里的伏笔也要指向真实章节
    ledger = fresh.writingLedger or {}
    for fs in ledger.get("foreshadows") or []:
        cid = fs.get("chapterId") if isinstance(fs, dict) else None
        if cid:
            assert cid in chapter_ids, f"伏笔指向了不存在的章节：{cid}"

    # 运行记录里的 chapterId 同理
    for run in fresh.harnessRuns or []:
        cid = run.get("chapterId") if isinstance(run, dict) else None
        if cid:
            assert cid in chapter_ids


def test_ln_template_gets_a_fresh_project_id_each_time():
    a = build_from_template("light_novel")
    b = build_from_template("light_novel")
    assert a.id != b.id
    # 静态模板仍然按原样深拷贝（章节 id 会被重新分配）
    static_a = build_from_template("slice_of_life")
    static_b = build_from_template("slice_of_life")
    assert [c.id for c in static_a.chapters] != [c.id for c in static_b.chapters]


def test_unknown_template_still_raises():
    with pytest.raises(KeyError):
        build_from_template("no_such_template")
    assert "light_novel" in TEMPLATES


# ---- 2. 离线体检路由 -------------------------------------------------------


def test_novel_audit_route_returns_both_parts_and_finds_real_problems():
    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner = await db_gate.register_headers(client, "audit_both")
            created = await client.post(
                "/api/v1/projects",
                json={"title": "体检路由", "template_id": "light_novel"},
                headers=owner,
            )
            assert created.status_code == 200, created.text
            pid = created.json()["id"]
            resp = await client.post(
                f"/api/v1/projects/{pid}/analysis/novel-audit", headers=owner
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["parts"] == ["consistency", "craft"]
            # 两个检查段都在，并且都带 coverage（不静默）
            assert "issues" in body["consistency"]
            assert "coverage" in body["consistency"]
            assert "hookScores" in body["craft"]
            assert "coverage" in body["craft"]
            # 模板正文是干净的中文正文，不该出现"引号不配对"这类硬错误
            errors = [
                i
                for i in body["consistency"]["issues"]
                if i.get("severity") == "error"
            ]
            assert errors == [], errors

    asyncio.run(_run())


def test_novel_audit_route_parts_filter_and_bad_parts():
    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner = await db_gate.register_headers(client, "audit_parts")
            created = await client.post(
                "/api/v1/projects", json={"title": "体检分段"}, headers=owner
            )
            pid = created.json()["id"]

            only_craft = await client.post(
                f"/api/v1/projects/{pid}/analysis/novel-audit?parts=craft",
                headers=owner,
            )
            assert only_craft.status_code == 200, only_craft.text
            assert only_craft.json()["parts"] == ["craft"]
            assert "consistency" not in only_craft.json()

            # 全是拼错的段名 → 400，而不是"什么都没查、返回 200 看着像通过"
            bad = await client.post(
                f"/api/v1/projects/{pid}/analysis/novel-audit?parts=nope",
                headers=owner,
            )
            assert bad.status_code == 400
            assert "consistency" in bad.json()["detail"]

    asyncio.run(_run())


# ---- 3. 体检工具 -----------------------------------------------------------


def test_agent_tool_novel_audit_reports_typography_clues():
    project = _project_with_text()
    ok, text = run_agent_tool("novel_audit", {"scope": "consistency"}, project=project)
    assert ok is True
    assert "【表记/视角】" in text
    # 半角逗号贴汉字、`--`、引号不配对都是确定性命中，必须出现在线索里
    assert "半角" in text
    assert "第1章" in text or "第 1 章" in text
    assert "扫描" in text  # coverage 摘要也在


def test_agent_tool_novel_audit_craft_scope_is_filtered():
    project = _project_with_text()
    ok, text = run_agent_tool("novel_audit", {"scope": "craft"}, project=project)
    assert ok is True
    assert "【文面统计】" in text
    assert "【表记/视角】" not in text


def test_agent_tool_novel_audit_focus_and_bad_scope_are_safe():
    project = _project_with_text()
    # focus 只扫第二章：第一章的引号问题不该出现在结果里
    ok, text = run_agent_tool(
        "novel_audit", {"scope": "consistency", "focus": "第二章"}, project=project
    )
    assert ok is True
    assert "第1章" not in text
    # 乱填 scope 不报错，退回 all
    ok2, text2 = run_agent_tool("novel_audit", {"scope": "乱填"}, project=project)
    assert ok2 is True
    assert "【表记/视角】" in text2 and "【文面统计】" in text2


def test_agent_tool_novel_audit_on_empty_project_does_not_crash():
    empty = normalize_project({"id": "p-empty", "title": "空"})
    ok, text = run_agent_tool("novel_audit", {}, project=empty)
    assert ok is True
    assert text.strip()
