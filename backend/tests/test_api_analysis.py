"""API 集成测试：本轮新增的分析/导出端点**接线**（需要测试库）。

为什么单独一个文件：本轮新增的核心模块各自都有充分的单元测试，但**端点接线**是另一回事——
"函数对、参数没传"这类缺陷模块测试根本看不见。本次会话已经踩到两次：

1. `harnessRuns` 不存 `beatSheet` → `story-metrics` 的"声明弧线 vs 实际弧线"对账**永远为空**；
2. `export_to_renpy(adaptive_reader=True)` **没有任何调用方** → 自适应选项做完却打不开。

所以这里逐个端点走真实 HTTP：路由存在、鉴权边界正确、响应形状可用、
以及两条曾经断掉的接线（`?adaptive_reader=true` 真的注入、伏笔能换成回收率）。

测试库不可达时整个模块跳过（``db_gate.DB_AVAILABLE``），与既有 ``test_api_*.py`` 一致。
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

MEI = "梅雨"  # 用于"没人选的选项"这类断言的可读标识


def _run(coro):
    return asyncio.run(coro)


def _lines(char_id: str, texts: list[str]) -> list[dict]:
    return [{"type": "dialogue", "characterId": char_id, "text": t} for t in texts]


async def _setup(client, name: str):
    """建一个"什么都有"的工程：菜单（含改变量的选项）、足够台词的角色、
    已登记结局（含一条走不到的）、账本里的伏笔（1 回收 + 1 未回收）。

    一个夹具喂全部端点，既省时间也让"不同端点看到的是同一个工程"这件事成立。
    """
    owner = await db_gate.register_headers(client, name)
    resp = await client.post(
        "/api/v1/projects", json={"title": f"分析工程-{name}"}, headers=owner
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    proj = (await client.get(f"/api/v1/projects/{pid}", headers=owner)).json()

    proj["characters"] = [
        {"id": "lin", "defineName": "lin", "displayName": "林夏", "voice": "克制、短句"},
        {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
    ]
    proj["variables"] = [
        {"id": "v-aff", "name": "好感", "key": "affection", "type": "number", "value": 0}
    ]
    proj["chapters"] = [
        {
            "id": "chA",
            "title": "第一章",
            "blocks": [
                {"type": "label", "id": "lbl-a", "name": "start"},
                *_lines("lin", ["嗯。", "好。", "知道了。", "行。", "走吧。", "等一下。"]),
                *_lines("zhou", ["来。", "不算常。", "记得路。", "嗯。", "别看。", "车快来了。"]),
                {
                    "type": "menu",
                    "id": "m1",
                    "prompt": MEI,
                    "choices": [
                        {
                            "text": "帮她",
                            "blocks": [
                                {"type": "set", "key": "affection", "op": "+=", "value": 1},
                                {"type": "return"},
                            ],
                        },
                        # 必须有**一条真跳转**，否则两个选项都 return、true_end 就真的不可达
                        # （第一版夹具就是这么写的，分析判它不可达是对的，是我的期望错了）
                        {"text": "去第二章", "jump": "true_end"},
                    ],
                },
            ],
        },
        {
            "id": "chB",
            "title": "第二章",
            "blocks": [
                {"type": "label", "id": "lbl-b", "name": "true_end"},
                *_lines("lin", ["等一下。", "别走。", "你听我说。", "算了。"]),
                *_lines("zhou", ["我不走。", "你先说。"]),
                {"type": "return"},
            ],
        },
    ]
    proj["endings"] = [
        {"id": "e1", "name": "真结局", "label": "true_end"},
        {"id": "e2", "name": "没人走到的结局", "label": "missing_end"},
    ]
    proj["writingLedger"] = {
        "foreshadows": [
            {
                "id": "fo-paid",
                "hook": "已回收的钩子",
                "status": "paid",
                "plantedChapter": "chA",
                "paidInChapter": "chB",
            },
            {
                "id": "fo-open",
                "hook": "埋下就没再提的钩子",
                "status": "open",
                "plantedChapter": "chA",
            },
        ]
    }
    resp = await client.put(
        f"/api/v1/projects/{pid}",
        json={"data": proj, "updated_at": proj.get("updatedAt"), "force": True},
        headers=owner,
    )
    assert resp.status_code == 200, resp.text
    return pid, owner


# ------------------------------------------------------------ 分支结构体检


def test_branch_report_endpoint_wires_through():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_branch")
            r = await client.get(f"/api/v1/projects/{pid}/analysis/branch-report", headers=owner)
            assert r.status_code == 200, r.text
            body = r.json()
            # 形状：前端与建议引擎都依赖这几个键
            assert set(body) >= {"graph", "coverage", "cycles", "menus", "endings", "findings", "counts"}
            assert body["counts"]["pass"] in (True, False)
            assert any(m["menuId"] == "m1" for m in body["menus"])
            # 登记的结局要与实际可达终点对账：missing_end 根本不存在
            declared = {e["name"]: e for e in body["endings"]["declared"]}
            assert declared["真结局"]["reachable"] is True
            assert declared["没人走到的结局"]["exists"] is False

    _run(_scenario())


# ---------------------------------------------------------------- 声线体检


def test_voice_report_endpoint_wires_through():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_voice")
            r = await client.get(f"/api/v1/projects/{pid}/analysis/voice-report", headers=owner)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "characters" in body and "notes" in body
            lin = next(c for c in body["characters"] if c["characterId"] == "lin")
            # 每角色 10 句台词 → 画像可用（阈值 8 句），留一法样本也够自校准（阈值 10）
            assert lin["ready"] is True
            assert lin["calibration"]["calibrated"] is True
            assert lin["calibration"]["watchThreshold"] <= lin["calibration"]["driftThreshold"]
            assert "signaturePhrases" in lin

    _run(_scenario())


# ------------------------------------------------------------ 跨章事实检测


def test_continuity_endpoint_wires_through():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_cont")
            r = await client.get(f"/api/v1/projects/{pid}/analysis/continuity", headers=owner)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "findings" in body and "counts" in body and "summary" in body
            assert set(body["counts"]) >= {"error", "warn", "info", "pass"}

    _run(_scenario())


# -------------------------------------------------------------- 故事层指标


def test_story_metrics_endpoint_turns_the_ledger_into_a_rate():
    """曾经的坏味道：账本里的伏笔在分析里从不出现。这条钉住"能算出回收率"。

    注意 `total` 会**大于**手工放进去的两条：保存工程时账本会自动从章末钩子派生伏笔
    （`pipeline/ledger.auto_digest_ledger` 的行为）。所以这里断言相对事实
    （我放的那条在、回收率是个介于 0 和 1 之间的数），而不是一个写死的条数。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_story")
            r = await client.get(f"/api/v1/projects/{pid}/analysis/story-metrics", headers=owner)
            assert r.status_code == 200, r.text
            body = r.json()
            fs = body["foreshadow"]
            assert fs["total"] >= 2, fs
            assert fs["paid"] >= 1 and fs["open"] >= 1
            assert 0 < fs["resolutionRate"] < 1
            # 我放进去的那条未回收伏笔必须在列表里（说明账本真的被读到了）
            assert any("埋下就没再提" in h["hook"] for h in fs["openHooks"]), fs["openHooks"]
            # 未回收的伏笔要按"埋点章"单列出来（前端按章展示、基准按章归因）
            hooks = [f for f in body["findings"] if f["code"] == "foreshadow_unresolved"]
            assert hooks, body["findings"]
            assert any(h["chapterId"] == "chA" for h in hooks)
            # 弧线部分至少要有结构
            assert "characters" in body["emotionArcs"]
            assert "breaks" in body["emotionArcBreaks"]

    _run(_scenario())


def test_story_metrics_without_any_foreshadow_says_null_not_zero():
    """没有伏笔 ≠ 回收率 0%：null 是刻意的契约（前端据此显示"还没有记录任何伏笔"）。

    夹具刻意做成"没有任何台词、也没有账本"：那样章末钩子为空，
    自动派生也生不出伏笔，才能确定性地验证 null 这条契约。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner = await db_gate.register_headers(client, "ana_story_empty")
            resp = await client.post(
                "/api/v1/projects", json={"title": "空账本"}, headers=owner
            )
            pid = resp.json()["id"]
            proj = (await client.get(f"/api/v1/projects/{pid}", headers=owner)).json()
            proj["characters"] = []
            proj["chapters"] = [
                {
                    "id": "only",
                    "title": "空章",
                    "blocks": [
                        {"type": "label", "id": "l", "name": "start"},
                        {"type": "return"},
                    ],
                }
            ]
            proj["writingLedger"] = {"foreshadows": []}
            put = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": proj, "updated_at": proj.get("updatedAt"), "force": True},
                headers=owner,
            )
            assert put.status_code == 200, put.text

            r = await client.get(
                f"/api/v1/projects/{pid}/analysis/story-metrics", headers=owner
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["foreshadow"]["total"] == 0, body["foreshadow"]
            assert body["foreshadow"]["resolutionRate"] is None

    _run(_scenario())


# ---------------------------------------------------------------- 自适应


def test_adaptive_plan_endpoint_derives_counters_from_set_blocks():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_adaptive")
            r = await client.get(
                f"/api/v1/projects/{pid}/analysis/adaptive-plan", headers=owner
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["tendencyCounters"] == {"affection": "reader_tendency_affection"}
            assert "persistent.reader_tendency_affection" in body["prelude"]
            assert any(
                "persistent.reader_tendency_affection" in rec["condition"]
                for rec in body["recipes"]
            )

    _run(_scenario())


def test_export_rpy_injects_counters_only_when_asked():
    """**接线回归闸**：这个开关曾经做完却没人传，作者只能手工改 .rpy。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_export")
            off = await client.get(f"/api/v1/projects/{pid}/export/rpy", headers=owner)
            assert off.status_code == 200, off.text
            assert "reader_tendency" not in off.text

            on = await client.get(
                f"/api/v1/projects/{pid}/export/rpy?adaptive_reader=true", headers=owner
            )
            assert on.status_code == 200, on.text
            assert "default persistent.reader_tendency_affection = 0" in on.text
            assert "$ persistent.reader_tendency_affection += 1" in on.text
            # 计数必须排在"选了它就改状态"之前
            assert on.text.index("persistent.reader_tendency_affection += 1") < on.text.index(
                "affection += 1"
            )

    _run(_scenario())


# ---------------------------------------------------------------- 鉴权边界


def test_new_endpoints_are_not_readable_by_outsiders():
    """非成员一律 404（不泄露工程是否存在），且**不得**触发任何 LLM 调用。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, _owner = await _setup(client, "ana_perm_a")
            outsider = await db_gate.register_headers(client, "ana_perm_b")
            for path in (
                "analysis/branch-report",
                "analysis/voice-report",
                "analysis/continuity",
                "analysis/story-metrics",
                "analysis/adaptive-plan",
                "playtest/recommendations",
            ):
                r = await client.get(f"/api/v1/projects/{pid}/{path}", headers=outsider)
                assert r.status_code == 404, (path, r.status_code, r.text)
            # consistency-scan 要调模型：鉴权先于取凭据，所以外人不会把账单打出去
            r = await client.post(
                f"/api/v1/projects/{pid}/analysis/consistency-scan", headers=outsider
            )
            assert r.status_code == 404, r.text

    _run(_scenario())


def test_recommendations_endpoint_works_without_reader_data():
    """没开遥测时也要能用：只出静态建议，并把"为什么只有静态"写清楚。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            pid, owner = await _setup(client, "ana_rec")
            r = await client.get(
                f"/api/v1/projects/{pid}/playtest/recommendations", headers=owner
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["basis"] == "script-only"
            assert "recommendations" in body and "sampleNote" in body
            # 这个夹具的菜单两个选项后果不同 → 不该被误报成"无后果"
            assert "no_effect_menu" not in [x["code"] for x in body["recommendations"]]

    _run(_scenario())
