"""续写写后廉价闸 + 本场必带进窗。"""
from __future__ import annotations

from app.core.agent_context import build_agent_context, must_bring_items
from app.core.memory_probe import build_probes, run_probes
from app.core.project import normalize_project
from app.core.write_gate import gate_continue_draft, should_write_gate


def _project(**over):
    base = {
        "id": "p-r1",
        "title": "第一轮",
        "logline": "测必带与写后闸",
        "characters": [
            {
                "id": "c1",
                "displayName": "林夏",
                "defineName": "linxia",
                "voice": "短句",
                "bio": "左手有旧伤",
            }
        ],
        "chapters": [
            {"id": "ch1", "title": "第一章", "prose": "雨停了，她攥紧左手。"},
        ],
        "writingGoals": {
            "mustBring": [
                "林夏左手有旧伤",
                "禁止第一人称叙述",
            ]
        },
    }
    base.update(over)
    return normalize_project(base)


def test_should_write_gate_only_for_writing_tasks():
    assert should_write_gate("continue")
    assert should_write_gate("rewrite")
    assert not should_write_gate("chat")
    assert not should_write_gate("outline")


def test_write_gate_passes_clean_prose():
    draft = "林夏抬眼：「别跟了。」\n他停住脚步，没有再问。"
    result = gate_continue_draft(draft)
    assert result.passed is True
    assert result.as_meta()["passed"] is True


def test_write_gate_fails_on_apartment_tour_lecture():
    draft = "这里是厨房，带你熟悉一下这个空间。那边是吃饭的地方。"
    result = gate_continue_draft(draft)
    assert result.passed is False
    codes = {i["code"] for i in result.issues}
    assert any(c.startswith("antipattern:") for c in codes)
    assert result.warnings


def test_must_bring_items_normalized():
    items = must_bring_items(_project())
    assert items == ["林夏左手有旧伤", "禁止第一人称叙述"]
    empty = must_bring_items(_project(writingGoals={"daily": 1000}))
    assert empty == []


def test_must_bring_stays_in_context_head_even_under_tight_budget():
    """必带清单在头部，且不在整块让位表里——极紧预算下仍应保留。"""
    project = _project()
    # 塞大量参考资料逼裁剪
    ctx = build_agent_context(
        project,
        chapterId="ch1",
        userMessage="接着写",
        task="continue",
        maxChars=3500,
        referenceDocs=("参" * 8000),
    )
    assert "## 本场必带" in ctx.text
    assert "林夏左手有旧伤" in ctx.text
    assert "禁止第一人称叙述" in ctx.text
    assert any("必带" in x for x in ctx.included)
    # 必带不得出现在篇幅省去列表
    dropped = (ctx.budgetReport or {}).get("droppedSections") or []
    keys = {d.get("key") if isinstance(d, dict) else d for d in dropped}
    assert "mustBring" not in keys


def test_must_bring_memory_probe_passes():
    project = _project()
    probes = build_probes(project, focus_chapter_id="ch1")
    must = [p for p in probes if p.dimension == "must_bring"]
    assert len(must) == 2
    report = run_probes(project, focus_chapter_id="ch1")
    bucket = report.by_dimension.get("must_bring")
    assert bucket is not None
    assert bucket["rate"] == 1.0, bucket


def test_write_gate_voice_drift_warns_without_blocking():
    """寡言角色突然话密：warn + markHints，passed 仍为 True（不挡落地）。"""
    laconic = [
        "嗯。",
        "不要。",
        "走。",
        "知道。",
        "是吗。",
        "好。",
        "不。",
        "随便。",
        "算了。",
        "行。",
        "不用。",
        "没事。",
        "等。",
        "看。",
        "别。",
        "嗯。",
        "可以。",
        "不必。",
    ]
    project = normalize_project(
        {
            "id": "p-voice",
            "title": "声线闸",
            "characters": [
                {"id": "lin", "defineName": "lin", "displayName": "林夏"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "一",
                    "blocks": [
                        {"type": "dialogue", "characterId": "lin", "text": t}
                        for t in laconic
                    ],
                }
            ],
        }
    )
    long = (
        "我今天在车站等了三个小时呢，结果什么也没等到，真是的，"
        "你要是不来的话我就一直等下去哦。"
    )
    draft = f"林夏：{long}\n林夏：{long}"
    result = gate_continue_draft(draft, project=project, chapter_id="ch1")
    assert result.passed is True
    codes = {i["code"] for i in result.issues}
    assert "voice_drift" in codes
    assert any("声线跑偏" in w for w in result.warnings)
    assert any(h.get("code") == "voice_drift" for h in result.markHints)


def test_write_gate_skips_voice_when_profile_not_ready():
    project = _project()  # 几乎没有台词画像
    draft = "林夏：今天天气真好呢，我们一起去散步好不好呀。\n林夏：真的超级开心的说。"
    result = gate_continue_draft(draft, project=project, chapter_id="ch1")
    assert all(i.get("code") != "voice_drift" for i in result.issues)
