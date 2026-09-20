"""对照盲评（`eval --ab`）不连真模型的自检。

要守住三件事：
1. 两臂**只差流程**：tool 臂走线上真实拼装（检索上下文 + 工艺卡 + 输出契约 +
   作者硬规则 + 任务分档温度 + 第二遍自检），bare 臂只有一句通用人设；
2. 盲评文件里**不能泄漏答案**（不得出现 tool / bare / 工具流程 等字样），
   答案单独写在 -key.json；
3. 甲/乙 标签是按 seed 随机的，且同一 seed 可复现。
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from app.cli import cli

runner = CliRunner()

CLEAN_PROSE = "雨敲着站台的铁棚。她把伞收了，水顺着伞骨滴到鞋尖。\n「末班车还来吗。」\n「来。」"


class _FakeResp:
    def __init__(self, content: str) -> None:
        self._content = content

    def json(self):  # noqa: ANN201
        return {
            "choices": [{"message": {"content": self._content}}],
            "model": "fake-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }


def _judge_json() -> str:
    return json.dumps(
        {
            "scores": {"social": 3, "dialogue": 3, "setting": 3, "stageable": 3, "consistency": 3},
            "evidence": {"social": "引用"},
            "veto": False,
            "note": "还行",
        },
        ensure_ascii=False,
    )


@pytest.fixture()
def fake_llm(monkeypatch):
    """假模型：写作调用返回正文，Judge 调用返回 Rubric JSON（靠响应格式区分）。"""
    calls: list[dict] = []

    async def _fake_chat(config, messages, temperature=0.7, timeout=60, **kw):  # noqa: ANN001
        calls.append(
            {
                "temperature": temperature,
                "system": messages[0]["content"],
                "user": messages[-1]["content"],
                "json": bool(kw.get("response_format")),
            }
        )
        return _FakeResp(_judge_json() if kw.get("response_format") else CLEAN_PROSE)

    monkeypatch.setattr("app.core.llm_http.chat_completions", _fake_chat)

    async def _fake_review(config, draft, task, project, **kw):  # noqa: ANN001
        class _R:
            ok = True
            issues: list = []
            lintIssues: list = []
            note = "假责编：通过"
            revisedText = None

        return _R()

    monkeypatch.setattr("app.core.narrative_review.run_narrative_self_review", _fake_review)
    return calls


def _run_ab(tmp_path, monkeypatch, *, cases=1, seed=20260409):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "ab.json"
    result = runner.invoke(
        cli,
        [
            "eval",
            "--ab",
            "--cases",
            str(cases),
            "--seed",
            str(seed),
            "--api-key",
            "test-key",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    blind = json.loads((tmp_path / "blind-ab.json").read_text(encoding="utf-8"))
    key = json.loads((tmp_path / "blind-ab-key.json").read_text(encoding="utf-8"))
    return report, blind, key, result.output


def test_ab_runs_two_arms_and_writes_blind_files(tmp_path, monkeypatch, fake_llm):
    report, blind, key, _ = _run_ab(tmp_path, monkeypatch)

    assert report["mode"] == "ab"
    case = report["cases"][0]
    # 两臂都跑到了，并且两臂用同一套量具（lint + judge）
    for arm in ("tool", "bare"):
        assert "error" not in case[arm], case[arm]
        assert case[arm]["chars"] > 0
        assert case[arm]["rubricAvg"] == 3.0
        assert case[arm]["judge"]["veto"] is False
    # 盲评文件每例两稿，答案在 key 里且标签与两臂一一对应
    assert len(blind["items"]) == 1
    item = blind["items"][0]
    assert item["甲"].strip() and item["乙"].strip()
    assert set(key["key"][item["id"]].values()) == {"tool", "bare"}


def test_blind_document_leaks_no_answer(tmp_path, monkeypatch, fake_llm):
    _, blind, _, _ = _run_ab(tmp_path, monkeypatch, cases=2)
    blob = json.dumps(blind, ensure_ascii=False)
    for leak in ("工具流程", "裸聊", "tool", "bare", "selfRevised"):
        assert leak not in blob, f"盲评文件泄漏了 {leak}"
    assert "rubric" in blind and "一票否决" in blind


def test_tool_arm_carries_pipeline_and_bare_arm_does_not(tmp_path, monkeypatch, fake_llm):
    _run_ab(tmp_path, monkeypatch)
    writes = [c for c in fake_llm if not c["json"]]
    # 每个任务两次写作调用：tool + bare；再各自一次 Judge（json=True）
    assert len(writes) == 2
    tool = next(c for c in writes if "作品上下文" in c["system"])
    bare = next(c for c in writes if c is not tool)
    # tool 臂带上了作品上下文、输出契约与分档温度
    assert "输出契约" in tool["system"]
    assert tool["temperature"] != bare["temperature"]
    # bare 臂就是一句话人设 + 原始任务，没有上下文/工艺/契约
    assert bare["system"] == "你是一个乐于助人的写作助手，请按用户要求完成写作。"
    assert "作品上下文" not in bare["system"]
    assert "输出契约" not in bare["system"]
    # 两臂看到的用户话术必须完全一致（差别只能来自流程，不能来自我们多写提示词）
    assert tool["user"] == bare["user"]
    assert tool["user"].startswith("续写下一小段")


def test_blind_labels_follow_seed(tmp_path, monkeypatch, fake_llm):
    _, _, key_a, _ = _run_ab(tmp_path, monkeypatch, cases=6, seed=1)
    _, _, key_b, _ = _run_ab(tmp_path, monkeypatch, cases=6, seed=1)
    assert key_a["key"] == key_b["key"], "同 seed 必须可复现"

    _, _, key_c, _ = _run_ab(tmp_path, monkeypatch, cases=6, seed=99)
    assert key_c["key"] != key_a["key"], "不同 seed 应给出不同的甲/乙分配"


def test_summary_reports_retention_and_boundary(tmp_path, monkeypatch, fake_llm):
    report, _, _, output = _run_ab(tmp_path, monkeypatch, cases=4)
    assert set(report["summary"]) == {"retention", "boundary"}
    for kind in ("retention", "boundary"):
        for arm in ("tool", "bare"):
            agg = report["summary"][kind][arm]
            assert agg["n"] >= 1
            assert isinstance(agg["rubricAvg"], float)
    assert "差值（工具 − 裸聊）" in output
