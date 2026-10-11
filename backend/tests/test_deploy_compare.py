"""线上 vs 本地对照夹具（不打真 API）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.core.deploy_compare import (
    build_blind_pack,
    load_cases,
    parse_sse_done_content,
    run_deploy_compare,
    structure_gate,
    write_compare_artifacts,
)


def test_load_cases_and_structure_gate():
    cases = load_cases()
    assert len(cases) >= 5
    gate = structure_gate(epsilon=0.02)
    assert "passed" in gate
    assert gate.get("currentOverall") is not None
    # CI 门禁：夹具相对冻结基线不得退步
    assert gate.get("baselineOverall") is not None
    assert gate["passed"] is True, gate


def test_parse_sse_done():
    raw = (
        'data: {"type":"token","delta":"x"}\n\n'
        'data: {"type":"done","content":"雨夜草稿"}\n\n'
    )
    text, err = parse_sse_done_content(raw)
    assert text == "雨夜草稿"
    assert err is None


def test_blind_pack_and_artifacts(tmp_path: Path):
    cases = [
        {
            "id": "case-01",
            "task": "continue",
            "instruction": "续写",
            "deployed": {"text": "线上稿甲侧候选"},
            "local": {"text": "本地稿乙侧候选"},
        }
    ]
    blind, key = build_blind_pack(cases, seed=1, model="test-model")
    assert len(blind["items"]) == 1
    assert key
    report = {
        "mode": "deploy_compare",
        "blind": blind,
        "key": key,
        "structureGate": {"passed": True},
        "disclaimer": "x",
    }
    paths = write_compare_artifacts(report, tmp_path)
    assert Path(paths["md"]).is_file()
    assert "Rubric" in Path(paths["md"]).read_text(encoding="utf-8")


def test_run_deploy_compare_mock():
    mocks = {
        "case-01-continue-rain": ("deployed text rain", "local text rain"),
        "case-02-choice-cost": ("deployed choice", "local choice"),
    }
    report = asyncio.run(
        run_deploy_compare(
            case_limit=2,
            skip_deployed=True,
            mock_texts=mocks,
        )
    )
    assert report["summary"]["blindItemCount"] == 2
    assert report["structureGate"]["passed"] in (True, False)
    assert "主结论" in (report.get("disclaimer") or "")
