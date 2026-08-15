"""Industrial harness helpers: run history + voice merge soft-fail."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.core.pipeline.run_history import append_harness_run, list_harness_runs
from app.core.pipeline.voice_lint import merge_voice_issues
from app.domain.types import Character, SceneChapter, StoryBible, VnProject


def _vn() -> VnProject:
    return VnProject(
        id="p1",
        title="t",
        logline="",
        updatedAt="2026-01-01T00:00:00Z",
        bible=StoryBible(),
        characters=[Character(id="c1", defineName="aya", displayName="绫")],
        chapters=[SceneChapter(id="ch1", title="一", blocks=[])],
        locations=[],
        locationLinks=[],
    )


def test_append_harness_run_caps():
    vn = _vn()
    for i in range(30):
        vn = append_harness_run(
            vn,
            kind="pipeline",
            chapter_id="ch1",
            gate={"pass": True, "errorCount": 0, "warnCount": 0},
            check={"issues": [], "beatMode": "keyword"},
            stages=["check"],
            instruction=f"run-{i}",
        )
    assert len(vn.harnessRuns or []) == 24
    assert list_harness_runs(vn, limit=3)[0]["instruction"].startswith("run-")


def test_merge_voice_soft_fail():
    audit = {
        "pass": True,
        "errorCount": 0,
        "warnCount": 0,
        "infoCount": 0,
        "issues": [],
        "notes": [],
    }

    async def _boom(*_a, **_k):
        raise RuntimeError("no key")

    async def _run():
        with patch(
            "app.core.voice_check.run_voice_check",
            new=AsyncMock(side_effect=_boom),
        ):
            from app.core.ai import DeepSeekConfig

            return await merge_voice_issues(
                audit,
                cfg=DeepSeekConfig(apiKey="sk-x", model="m"),
                project=_vn(),
                chapter_id="ch1",
            )

    out = asyncio.run(_run())
    assert out["pass"] is True
    assert out["voiceChecked"] is False
    assert any(i.get("code") == "voice_check_unavailable" for i in out["issues"])
