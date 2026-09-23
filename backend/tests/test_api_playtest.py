"""API 集成测试：读者行为采集的**隐私红线**、幂等与开关（需要测试库）。

对应交付要求里的四条硬要求：
1. 未开启遥测时 record 拒绝，且**一行都不落**（``test_record_rejected_when_telemetry_disabled``）；
2. 上报体里的 ``text`` / 未知字段被丢弃，库里**没有任何文本列**存了它
   （``test_record_drops_unknown_and_text_fields``）；
3. 重复上报同一 ``client_run_id`` 幂等（``test_record_is_idempotent_for_same_client_run_id``）；
4. 无权限用户被拒（``test_settings_and_analytics_permissions``）。

测试库不可达时整个模块跳过（``db_gate.DB_AVAILABLE``），与既有 ``test_api_*.py`` 一致。
若本沙箱下 pytest 无法 scandir 临时目录而报 ERROR，那是环境限制而不是用例本身的问题；
核心逻辑的回归在 ``tests/test_playtest_analytics.py``（纯函数、无 DB）。
"""

from __future__ import annotations

import asyncio

import db_gate
import pytest

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()

# 用来验证"绝不落库"的探针字符串：只要它在库里出现一次就算红线破了
PROSE = "这是台词，绝不能进遥测库-UNIQUE-MARKER-7f3a"


def _run(coro):
    return asyncio.run(coro)


async def _counts_async(pid: str) -> dict:
    """直接查库：这个工程落了多少行 run / choice（在事件循环内 await）。"""
    from sqlalchemy import func, select

    from app.models import PlaytestChoice, PlaytestRun

    async with db_gate.SessionLocal() as session:
        runs = int(
            await session.scalar(
                select(func.count())
                .select_from(PlaytestRun)
                .where(PlaytestRun.project_id == pid)
            )
            or 0
        )
        choices = 0
        if runs:
            choices = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PlaytestChoice)
                    .join(PlaytestRun, PlaytestChoice.run_id == PlaytestRun.id)
                    .where(PlaytestRun.project_id == pid)
                )
                or 0
            )
        return {"runs": runs, "choices": choices}


def _counts(pid: str) -> dict:
    """同步壳（只在测试函数体里用，不能在事件循环里用）。"""
    return _run(_counts_async(pid))


async def _dump_rows_async(pid: str) -> list[dict]:
    """摊平成 [{__table__, column: value}]，用于"库里没有文本"的逐列断言。"""
    from sqlalchemy import select

    from app.models import PlaytestChoice, PlaytestRun

    out: list[dict] = []
    async with db_gate.SessionLocal() as session:
        res = await session.execute(
            select(PlaytestRun).where(PlaytestRun.project_id == pid)
        )
        for row in res.scalars().all():
            item = {"__table__": "playtest_runs"}
            for column in row.__table__.columns:
                item[column.name] = getattr(row, column.name)
            out.append(item)
        res = await session.execute(
            select(PlaytestChoice)
            .join(PlaytestRun, PlaytestChoice.run_id == PlaytestRun.id)
            .where(PlaytestRun.project_id == pid)
        )
        for row in res.scalars().all():
            item = {"__table__": "playtest_choices"}
            for column in row.__table__.columns:
                item[column.name] = getattr(row, column.name)
            out.append(item)
    return out


def _dump_rows(pid: str) -> list[dict]:
    return _run(_dump_rows_async(pid))


async def _setup(client, name: str, *, telemetry: bool):
    """建一个带菜单和结局 label 的工程；返回 (project_id, owner_headers)。"""
    owner = await db_gate.register_headers(client, name)
    resp = await client.post(
        "/api/v1/projects", json={"title": f"试玩工程-{name}"}, headers=owner
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]

    proj = (await client.get(f"/api/v1/projects/{pid}", headers=owner)).json()
    proj["chapters"] = [
        {
            "id": "chA",
            "title": "章A",
            "blocks": [
                {"type": "label", "id": "lbl-a", "name": "start"},
                {
                    "type": "menu",
                    "id": "m1",
                    "prompt": PROSE,
                    "choices": [
                        {"text": f"选项甲-{PROSE}", "blocks": [{"type": "return"}]},
                        {"text": "选项乙", "blocks": [{"type": "return"}]},
                        {
                            "text": "选项丙",
                            "condition": "flag == 1",
                            "blocks": [{"type": "return"}],
                        },
                    ],
                },
            ],
        },
        {
            "id": "chB",
            "title": "章B",
            "blocks": [
                {"type": "label", "id": "lbl-b", "name": "true_end"},
                {"type": "return"},
            ],
        },
    ]
    proj["endings"] = [
        {"id": "e1", "name": "真结局", "label": "true_end"},
        {"id": "e2", "name": "没人走的结局", "label": "bad_end"},
    ]
    resp = await client.put(
        f"/api/v1/projects/{pid}",
        json={
            "data": proj,
            "updated_at": proj.get("updatedAt"),
            "force": True,
        },
        headers=owner,
    )
    assert resp.status_code == 200, resp.text

    if telemetry:
        resp = await client.put(
            f"/api/v1/projects/{pid}/playtest/settings",
            json={"enabled": True},
            headers=owner,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is True
    return pid, owner


def _payload(client_run_id: str, *, with_text: bool = False, seqs=(0, 1)) -> dict:
    choices = []
    for i, seq in enumerate(seqs):
        item = {
            "seq": seq,
            "chapter_id": "chA",
            "label": "start",
            "menu_id": "m1",
            "choice_index": i,
            "condition_passed": True,
        }
        if with_text:
            item.update({"text": PROSE, "choice_text": PROSE, "note": PROSE})
        choices.append(item)
    body = {
        "run": {
            "client_run_id": client_run_id,
            "chapter_count": 2,
            "choice_count": len(seqs),
            "ending_label": "true_end",
        },
        "choices": choices,
    }
    if with_text:
        body["run"].update(
            {
                "text": PROSE,
                "prose": PROSE,
                "user_agent": PROSE,
                "ip": PROSE,
                "user_id": PROSE,
            }
        )
        body["note"] = PROSE  # 信封层的未知字段
    return body


# --------------------------------------------------------- ① 默认关闭 / 不落库


def test_record_rejected_when_telemetry_disabled():
    """未开启遥测：默认关闭（settings GET 明示 defaultEnabled=False），record 返回 403。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_off", telemetry=False)

            # 没有任何设置行 = 关闭
            resp = await client.get(
                f"/api/v1/projects/{pid}/playtest/settings", headers=owner
            )
            assert resp.status_code == 200, resp.text
            assert resp.json() == {
                "projectId": pid,
                "enabled": False,
                "defaultEnabled": False,
            }

            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json=_payload("run-off-0001", with_text=True),
                headers=owner,
            )
            assert resp.status_code == 403, resp.text
            assert resp.json()["detail"]["code"] == "telemetry_disabled"

    _run(_scenario())


def test_record_rejected_leaves_no_rows_in_db():
    """未开启遥测时拒绝，并在**库层面**确认没有任何行（隐私红线 ①）。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_off_db", telemetry=False)
            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json=_payload("run-off-0002", with_text=True),
                headers=owner,
            )
            assert resp.status_code == 403

            async def _count():
                from sqlalchemy import func, select

                from app.models import PlaytestChoice, PlaytestRun

                async with db_gate.SessionLocal() as session:
                    return (
                        int(
                            await session.scalar(
                                select(func.count())
                                .select_from(PlaytestRun)
                                .where(PlaytestRun.project_id == pid)
                            )
                            or 0
                        ),
                        int(
                            await session.scalar(select(func.count()).select_from(PlaytestChoice))
                            or 0
                        ),
                    )

            runs, choices = await _count()
            assert runs == 0, "未开启遥测却落了 playtest_runs"
            assert choices == 0, "未开启遥测却落了 playtest_choices"

    _run(_scenario())


# ------------------------------------------------- ② 未知字段 / 文案不落库


def test_record_drops_unknown_and_text_fields():
    """隐私红线 ②：上报体里的 text / 未知字段被丢弃，库里没有任何列存了它。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_text", telemetry=True)
            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json=_payload("run-text-0001", with_text=True, seqs=(0, 1, 2)),
                headers=owner,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["ok"] is True
            assert body["accepted"] == 3
            assert body["duplicates"] == 0
            # 被丢弃的字段名要如实回显（可观测，而不是悄悄消失）
            for key in ("text", "choice_text", "note", "prose", "user_agent", "ip", "user_id"):
                assert key in body["droppedFields"], body["droppedFields"]

            # 结构性保证：这两张表根本没有能存正文的列
            from app.models import PlaytestChoice, PlaytestRun

            allowed_runs = {
                "id",
                "project_id",
                "client_run_id",
                "started_at",
                "ended_at",
                "chapter_count",
                "choice_count",
                "ending_label",
                "created_at",
            }
            allowed_choices = {
                "id",
                "run_id",
                "seq",
                "chapter_id",
                "label",
                "menu_id",
                "choice_index",
                "condition_passed",
                "created_at",
            }
            assert {c.name for c in PlaytestRun.__table__.columns} == allowed_runs
            assert {c.name for c in PlaytestChoice.__table__.columns} == allowed_choices
            for column in allowed_runs | allowed_choices:
                assert column not in ("text", "prose", "note", "body", "content", "stem")

            # 逐行逐列断言：没有任何一个值等于/包含探针正文
            rows = await _dump_rows_async(pid)
            assert len(rows) == 1 + 3  # 1 run + 3 choices
            for row in rows:
                for column, value in row.items():
                    assert PROSE not in str(value), f"{row['__table__']}.{column} 里出现了正文"

    _run(_scenario())


def test_prose_shaped_identifiers_are_dropped():
    """文案混进标识符列（label / menu_id / chapter_id）也会被白名单挡掉。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_ident", telemetry=True)
            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json={
                    "run": {"client_run_id": "run-ident-0001"},
                    "choices": [
                        {
                            "seq": 0,
                            "chapter_id": "chA",
                            "label": PROSE,  # 文案塞进 label 列 → 落成空串
                            "menu_id": PROSE,
                            "choice_index": 0,
                        }
                    ],
                },
                headers=owner,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["accepted"] == 1
            rows = [r for r in await _dump_rows_async(pid) if r["__table__"] == "playtest_choices"]
            assert rows[0]["label"] == ""
            assert rows[0]["menu_id"] == ""

    _run(_scenario())


# -------------------------------------------------------------- ③ 幂等


def test_record_is_idempotent_for_same_client_run_id():
    """隐私/正确性红线 ③：重复上报同一 client_run_id 不产生重复行，只补缺失的 seq。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_idem", telemetry=True)
            url = f"/api/v1/projects/{pid}/playtest/record"

            first = await client.post(url, json=_payload("run-idem-0001"), headers=owner)
            assert first.status_code == 200, first.text
            assert first.json()["accepted"] == 2
            assert first.json()["created"] is True
            run_id = first.json()["runId"]

            # 完全相同的第二次上报：一行都不新增
            second = await client.post(url, json=_payload("run-idem-0001"), headers=owner)
            assert second.status_code == 200, second.text
            assert second.json()["accepted"] == 0
            assert second.json()["duplicates"] == 2
            assert second.json()["created"] is False
            assert second.json()["runId"] == run_id

            counts = await _counts_async(pid)
            assert counts == {"runs": 1, "choices": 2}

            # 中断后续报：只补 seq 2、3
            third = await client.post(
                url, json=_payload("run-idem-0001", seqs=(0, 1, 2, 3)), headers=owner
            )
            assert third.status_code == 200, third.text
            assert third.json()["accepted"] == 2
            assert third.json()["duplicates"] == 2
            assert third.json()["runId"] == run_id
            assert await _counts_async(pid) == {"runs": 1, "choices": 4}

            # run 的 choice_count 与库内真实行数一致（回填，而不是信客户端自报）
            async def _stored_count():
                from sqlalchemy import select

                from app.models import PlaytestRun

                async with db_gate.SessionLocal() as session:
                    res = await session.execute(
                        select(PlaytestRun).where(PlaytestRun.id == run_id)
                    )
                    return res.scalar_one().choice_count

            assert await _stored_count() == 4

    _run(_scenario())


def test_record_rejects_invalid_client_run_id():
    """没有可用的幂等键就不落库（宁可 400，也不要写一堆无法去重的行）。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_badid", telemetry=True)
            for bad in ("short", "", "has space in it", "带中文的id"):
                resp = await client.post(
                    f"/api/v1/projects/{pid}/playtest/record",
                    json={"run": {"client_run_id": bad}, "choices": []},
                    headers=owner,
                )
                assert resp.status_code == 400, (bad, resp.text)
                assert resp.json()["detail"]["code"] == "invalid_client_run_id"
            assert await _counts_async(pid) == {"runs": 0, "choices": 0}

    _run(_scenario())


# ------------------------------------------------------- ④ 权限 / settings


def test_settings_and_analytics_permissions():
    """隐私/安全红线 ④：非成员 404（不泄露存在性），viewer 只读。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_perm", telemetry=True)
            viewer = await db_gate.register_headers(client, "pt_perm_viewer")
            outsider = await db_gate.register_headers(client, "pt_perm_out")

            resp = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "pt_perm_viewer", "role": "viewer"},
                headers=owner,
            )
            assert resp.status_code == 200, resp.text

            # viewer 能读开关、能读分析，也能**上报自己这一次试玩**（record 走 read 权限：
            # 能看剧本的人就能报告自己怎么玩的），但不能改开关。
            assert (
                await client.get(f"/api/v1/projects/{pid}/playtest/settings", headers=viewer)
            ).status_code == 200
            assert (
                await client.get(f"/api/v1/projects/{pid}/playtest/analytics", headers=viewer)
            ).status_code == 200
            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json=_payload("run-perm-viewer"),
                headers=viewer,
            )
            assert resp.status_code == 200, resp.text
            resp = await client.put(
                f"/api/v1/projects/{pid}/playtest/settings",
                json={"enabled": False},
                headers=viewer,
            )
            assert resp.status_code == 403, resp.text

            # 非成员：一律 404（存在性不外泄）。
            # 注意 body 必须是合法形状：FastAPI 在跑 handler 之前就校验 body，
            # 形状不对会先拿到 422 —— 那样测的就不是权限了。
            for method, path, body in (
                ("get", f"/api/v1/projects/{pid}/playtest/settings", None),
                ("get", f"/api/v1/projects/{pid}/playtest/analytics", None),
                ("put", f"/api/v1/projects/{pid}/playtest/settings", {"enabled": False}),
                ("post", f"/api/v1/projects/{pid}/playtest/record", _payload("run-perm-out")),
            ):
                call = getattr(client, method)
                if body is None:
                    resp = await call(path, headers=outsider)
                else:
                    resp = await call(path, json=body, headers=outsider)
                assert resp.status_code == 404, (method, path, resp.text)

    _run(_scenario())


def test_settings_roundtrip():
    """开关可以来回切；关掉之后 record 立刻被拒。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_switch", telemetry=True)
            url = f"/api/v1/projects/{pid}/playtest/settings"

            assert (await client.get(url, headers=owner)).json()["enabled"] is True
            resp = await client.put(url, json={"enabled": False}, headers=owner)
            assert resp.status_code == 200 and resp.json()["enabled"] is False
            assert (await client.get(url, headers=owner)).json()["enabled"] is False

            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json=_payload("run-switch-0001"),
                headers=owner,
            )
            assert resp.status_code == 403

            await client.put(url, json={"enabled": True}, headers=owner)
            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json=_payload("run-switch-0001"),
                headers=owner,
            )
            assert resp.status_code == 200, resp.text

    _run(_scenario())


# -------------------------------------------------------------- analytics


def test_analytics_shape_and_alignment():
    """analytics 返回形状 + 与 branch_analysis 对齐（选项占比 / 漏斗 / 结局 / 覆盖率）。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_ana", telemetry=True)
            url = f"/api/v1/projects/{pid}/playtest/record"

            for i, index in enumerate((0, 0, 1)):
                resp = await client.post(
                    url,
                    json={
                        "run": {
                            "client_run_id": f"run-ana-{i:04d}",
                            "chapter_count": 2 if i < 2 else 1,
                            "ending_label": "true_end" if i == 0 else None,
                        },
                        "choices": [
                            {
                                "seq": 0,
                                "chapter_id": "chA",
                                "label": "start",
                                "menu_id": "m1",
                                "choice_index": index,
                                "condition_passed": True,
                            }
                        ],
                    },
                    headers=owner,
                )
                assert resp.status_code == 200, resp.text

            resp = await client.get(
                f"/api/v1/projects/{pid}/playtest/analytics", headers=owner
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()

            assert set(body) == {
                "sample",
                "choices",
                "funnel",
                "endings",
                "runs",
                "coverage",
                "notes",
            }
            assert body["sample"]["runs"] == 3
            assert body["sample"]["choices"] == 3
            assert body["sample"]["sufficient"] is False  # 3 < MIN_SAMPLE_RUNS

            # 选项占比：m1 的第 0 项 2 次、第 1 项 1 次、第 2 项从未被选
            menu = next(m for m in body["choices"]["menus"] if m["menuId"] == "m1")
            by_index = {o["index"]: o for o in menu["options"]}
            assert by_index[0]["selected"] == 2
            assert by_index[1]["selected"] == 1
            assert by_index[2]["neverSelected"] is True
            assert menu["neverSelected"] == [2]
            assert by_index[0]["share"] == round(2 / 3, 4)

            # 漏斗按章递减
            assert [c["chapterId"] for c in body["funnel"]["chapters"]] == ["chA", "chB"]
            reached = [c["reached"] for c in body["funnel"]["chapters"]]
            assert reached == sorted(reached, reverse=True)
            assert body["funnel"]["chapters"][0]["reached"] == 3

            # 结局：true_end 走到 1 次，声明了但没人走的 bad_end 被点出来
            assert body["endings"]["reached"][0]["label"] == "true_end"
            assert body["endings"]["reached"][0]["name"] == "真结局"
            assert [r["label"] for r in body["endings"]["neverReached"]] == ["bad_end"]

            # 运行统计
            assert body["runs"]["total"] == 3
            assert body["runs"]["choicesObserved"]["avg"] == 1.0
            assert body["runs"]["chaptersPlayed"]["avg"] == round(5 / 3, 3)

            # 读者侧覆盖率：m1 有 3 个可用选项，玩家走过 2 个
            assert body["coverage"]["availableOptions"] == 3
            assert body["coverage"]["observedOptions"] == 2
            assert body["coverage"]["ratio"] == round(2 / 3, 4)

            # 中文口径说明 + 样本量提示
            assert isinstance(body["notes"], list) and body["notes"]
            assert any("样本量不足" in n for n in body["notes"])

            # 响应里也不含任何选项文案 / 提示语
            assert PROSE not in resp.text

    _run(_scenario())


def test_analytics_empty_project_is_safe():
    """一次试玩都没有：analytics 不报错，且明确说"还没有数据"。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_empty", telemetry=True)
            resp = await client.get(
                f"/api/v1/projects/{pid}/playtest/analytics", headers=owner
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["sample"]["runs"] == 0
            # 章节顺序来自工程本身，所以漏斗框架在、到达数全为 0
            assert [c["chapterId"] for c in body["funnel"]["chapters"]] == ["chA", "chB"]
            assert all(c["reached"] == 0 for c in body["funnel"]["chapters"])
            assert body["funnel"]["biggestDrop"] is None
            assert body["endings"]["reached"] == []
            assert body["coverage"]["ratio"] == 0.0
            assert any("还没有任何试玩记录" in n for n in body["notes"])

    _run(_scenario())


def test_record_rejects_oversized_batch():
    """超过单批上限的选择条数被信封层挡掉（422），不会打爆一次写库。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "pt_big", telemetry=True)
            from app.services.playtest_telemetry import MAX_CHOICES_PER_RUN

            choices = [
                {"seq": i, "menu_id": "m1", "choice_index": 0}
                for i in range(MAX_CHOICES_PER_RUN + 5)
            ]
            resp = await client.post(
                f"/api/v1/projects/{pid}/playtest/record",
                json={"run": {"client_run_id": "run-big-0001"}, "choices": choices},
                headers=owner,
            )
            assert resp.status_code == 422, resp.text
            assert await _counts_async(pid) == {"runs": 0, "choices": 0}

    _run(_scenario())
