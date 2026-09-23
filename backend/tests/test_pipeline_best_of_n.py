"""best-of-N 在**真实流水线**里的接线测试。

为什么单独一个文件：`core/pipeline/candidates.py` 自己的单测证明了"打分与排序是对的"，
但模块本身**没有调用点**——那等于没接。这里测的是接线本身：
`run_pipeline(candidates=N)` 是否真的多采了几份、是否选中了更干净的那一份、
是否把成本与选择理由写进了结果。

做法：只把 `stage_write` 换成假的（隔离模型调用），排序与打分的真实逻辑照跑。
"""

from __future__ import annotations

import app.core.pipeline.orchestrator as orchestrator
from app.core.ai import DeepSeekConfig
from app.core.pipeline.orchestrator import run_pipeline
from app.core.project import normalize_project

#: 会触发 narrative_lint 的 error 级问题（「作为一名」= 说明书腔），因此 hardErrorCount>=1
DIRTY = "作为一名学生，我每天都来这个车站。她看着我，什么也没说。"
CLEAN = (
    "雨把站牌洗得发白。她把伞收了，水顺着伞骨滴到鞋尖。\n"
    "「末班车还来吗。」她问。\n"
    "「来。」他说，没有看她。\n"
    "广播念不清站名，念到一半卡住了。她把袖口往上折了两折，没再说话。"
)


def _project():
    return normalize_project(
        {
            "id": "p1",
            "title": "best-of-N 接线测试",
            "characters": [
                {"id": "lin", "defineName": "lin", "displayName": "林夏"},
                {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "narration", "text": "雨落在站台上。"},
                        {"type": "dialogue", "characterId": "lin", "text": "嗯。"},
                        {"type": "return"},
                    ],
                }
            ],
        }
    )


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="test-key", baseUrl="http://x", model="fake")


def _patch_stage_write(monkeypatch, *, dirty_temperature: float):
    """假 stage_write：只有指定温度那一档返回脏稿，其余返回干净稿。"""
    calls: list[float] = []

    async def _fake_write(
        cfg,  # noqa: ANN001
        project,  # noqa: ANN001
        *,
        instruction="",  # noqa: ANN001
        chapter_id=None,  # noqa: ANN001
        selection="",  # noqa: ANN001
        beat_sheet=None,  # noqa: ANN001
        long_memory="",  # noqa: ANN001
        db_continuity=None,  # noqa: ANN001
        on_token=None,  # noqa: ANN001
        temperature=0.75,
    ):
        calls.append(round(float(temperature), 4))
        text = DIRTY if round(float(temperature), 4) == round(dirty_temperature, 4) else CLEAN
        return {"stage": "write", "content": text, "model": "fake"}

    monkeypatch.setattr(orchestrator, "stage_write", _fake_write)
    # 结尾的 quality gate 一并打桩（理由见 _patch_gate 的 docstring）
    _patch_gate(monkeypatch)
    return calls


def _patch_gate(monkeypatch):
    """把结尾的 quality gate 也打桩。

    必须打：`run_pipeline` **结尾总会算 gate**，而 `stages=["write"]` 时它会回落到
    `stage_check_async(...)`——里面 `voice_check=True` 会**真的发一次 LLM 请求**。
    不打桩的话，这个单元测试会去连一个不存在的 base URL（实测每次 DNS 超时 ≈13 秒/
    用例），既慢又是在"测试里发真实网络请求"。这里如实记下来，方便日后判断
    这是不是 `stages` 语义本身该收紧的地方（本次不改行为，只隔离测试）。
    """
    calls: list[dict] = []

    async def _fake_check(draft, **kw):  # noqa: ANN001, ANN003
        calls.append({"draft": draft, **{k: v for k, v in kw.items() if k != "cfg"}})
        return {
            "stage": "check",
            "pass": True,
            "errorCount": 0,
            "warnCount": 0,
            "infoCount": 0,
            "issues": [],
            "notes": ["fake gate"],
            "gateReady": True,
            "beatMode": "keyword",
        }

    monkeypatch.setattr(orchestrator, "stage_check_async", _fake_check)
    return calls


def test_single_candidate_keeps_the_old_single_sample_behaviour(monkeypatch):
    """默认 N=1：行为与接 best-of-N 之前完全一致（不多花一次调用、不动结果）。"""
    calls = _patch_stage_write(monkeypatch, dirty_temperature=0.75)
    import asyncio

    result = asyncio.run(
        run_pipeline(
            _cfg(),
            _project(),
            instruction="续写",
            stages=["write"],
            candidates=1,
            persist_run=False,
        )
    )
    assert len(calls) == 1
    assert "candidates" not in result
    assert result["finalDraft"] == DIRTY


def test_best_of_n_samples_and_picks_the_cleaner_candidate(monkeypatch):
    """基础温度那一档故意返回脏稿 → 选中的必须是别的温度那一份。"""
    calls = _patch_stage_write(monkeypatch, dirty_temperature=0.75)
    import asyncio

    result = asyncio.run(
        run_pipeline(
            _cfg(),
            _project(),
            instruction="续写",
            stages=["write"],
            candidates=3,
            candidates_temperature=0.75,
            persist_run=False,
        )
    )
    assert len(calls) == 3, calls
    assert len(set(calls)) == 3, f"温度必须拉开，否则 N 份是同一次采样：{calls}"

    info = result["candidates"]
    assert info["n"] == 3
    assert info["sampled"] == 3
    # 选中的不是脏稿那一档，且最终稿确实是干净的
    assert info["chosenTemperature"] != 0.75
    assert result["finalDraft"] == CLEAN
    assert "作为一名" not in result["finalDraft"]
    # 每份候选都留了得分与理由，作者能看懂为什么选它
    assert len(info["ranked"]) == 3
    for row in info["ranked"]:
        assert isinstance(row["score"], float)
        assert row["reason"]
    assert info["reason"]
    # 成本必须如实写在返回值里，不能悄悄多花钱
    assert "3 倍" in info["costNote"]


def test_best_of_n_penalises_the_draft_with_a_hard_error(monkeypatch):
    """硬错误一票否决：脏稿必须排在最后一名，而不是靠软项拉分。"""
    _patch_stage_write(monkeypatch, dirty_temperature=0.75)
    import asyncio

    result = asyncio.run(
        run_pipeline(
            _cfg(),
            _project(),
            instruction="续写",
            stages=["write"],
            candidates=3,
            persist_run=False,
        )
    )
    ranked = result["candidates"]["ranked"]
    dirty_rows = [r for r in ranked if r["hardErrorCount"]]
    assert dirty_rows, ranked
    assert dirty_rows[0]["rank"] == len(ranked)
    assert dirty_rows[0]["score"] == 0.0


def test_one_failed_candidate_does_not_sink_the_run(monkeypatch):
    """某一份候选抛异常时，其余候选仍要能选出结果。"""
    calls: list[float] = []

    async def _flaky_write(cfg, project, *, temperature=0.75, **kw):  # noqa: ANN001
        calls.append(round(float(temperature), 4))
        if len(calls) == 2:
            raise RuntimeError("boom")
        return {"stage": "write", "content": CLEAN, "model": "fake"}

    monkeypatch.setattr(orchestrator, "stage_write", _flaky_write)
    _patch_gate(monkeypatch)
    import asyncio

    result = asyncio.run(
        run_pipeline(
            _cfg(),
            _project(),
            instruction="续写",
            stages=["write"],
            candidates=3,
            persist_run=False,
        )
    )
    assert len(calls) == 3
    assert result["finalDraft"] == CLEAN
    assert result["candidates"]["sampled"] == 3
    failed = [r for r in result["candidates"]["ranked"] if r["score"] == 0.0]
    assert failed, "失败的那一份应当以 0 分留痕，而不是被静默丢掉"


def test_candidates_are_capped(monkeypatch):
    """N 有上限：不能因为调用方传了 99 就发出 99 次请求。"""
    calls = _patch_stage_write(monkeypatch, dirty_temperature=-1.0)
    import asyncio

    result = asyncio.run(
        run_pipeline(
            _cfg(),
            _project(),
            instruction="续写",
            stages=["write"],
            candidates=99,
            persist_run=False,
        )
    )
    from app.core.pipeline.candidates import MAX_CANDIDATES

    assert len(calls) == MAX_CANDIDATES
    assert result["candidates"]["n"] == MAX_CANDIDATES
