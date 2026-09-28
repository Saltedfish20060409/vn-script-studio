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

from app.cli import cli, strip_test_hint

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


def test_markdown_worksheet_is_writable_and_leaks_nothing(tmp_path, monkeypatch, fake_llm):
    """人肉盲评工作纸：能直接读、且同样不含答案。"""
    _, blind, _, _ = _run_ab(tmp_path, monkeypatch, cases=2)
    md = (tmp_path / "blind-ab.md").read_text(encoding="utf-8")
    for leak in ("工具流程", "裸聊", "tool", "bare"):
        assert leak not in md, f"工作纸泄漏了 {leak}"
    # 每个用例的两稿与计分表都在
    assert "稿 甲" in md and "稿 乙" in md
    assert md.count("| case-") == 2
    for item in blind["items"]:
        assert item["id"] in md
        assert item["甲"] in md and item["乙"] in md
    assert "一票否决" in md and "拆封" in md


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
    # 汇总行：从"两臂差值"改成通用的「配对读数 {臂} − {基准}」——
    # 默认两臂时基准是 tool，读作"bare 比 tool 差多少"；加 --arms 后同一行
    # 也是消融读数（摘掉某块后分掉多少），口径一致才不用记两套读法。
    assert "配对读数 bare − tool" in output
    # 边界集的 lint 命中率会被"照写问题写法"这个指令混淆，必须把读法印出来
    assert "不作为优劣指标" in output
    assert "不作为优劣指标" in report["summaryNote"]


# ---------------------------------------------------------------- 评测方法论
# 这一节是补上"只印差值、不给不确定度"的旧毛病：n 很小时必须把区间与检验一起印出来，
# 并且必须说清裁判是不是独立模型、裁判有没有被透题。


def test_judge_prompt_never_sees_the_answer_key():
    """用例里的评测元信息不能进裁判提示——那等于把参考答案发给判卷人。

    以前边界集的指令里带着「（测试：审稿应抓住『设定宣讲』，判定不合格）」，
    它原样进了 `_judge_rubric` 的 user 消息，于是"工具 vs 裸聊"的差值里
    混进了"我们剧透了答案"这一项。
    """
    raw = "写一段对话：连续追问 3 次（照写，不要加入新信息）。（测试：审稿应抓住「问答乒乓」，判定不合格）"
    cleaned = strip_test_hint(raw)
    assert "测试" not in cleaned
    assert "判定不合格" not in cleaned
    # 作者原话（照写…）必须保留：那才是任务本身
    assert "照写" in cleaned
    assert cleaned.startswith("写一段对话")
    assert strip_test_hint("") == ""


def test_longrange_benchmark_runs_without_any_api_key():
    """长程基准必须能在没有模型的情况下跑——否则它进不了 CI，也就守不住回归。"""
    result = runner.invoke(
        cli, ["eval", "--longrange", "--longrange-chapters", "40", "--seed", "5"]
    )
    assert result.exit_code == 0, result.output
    assert "旧方案" in result.output and "分片方案" in result.output
    assert "暴露率" in result.output
    # 旧方案在长距离上必须为 0，这是本基准要钉住的核心结论
    assert "31+:0.00" in result.output


def test_method_block_discloses_judge_independence(tmp_path, monkeypatch, fake_llm):
    report, _, _, _ = _run_ab(tmp_path, monkeypatch, cases=2)
    method = report["method"]
    # 没配 CRITIC_*/--judge-model 时，裁判就是选手自己，必须如实标注并告警
    assert method["judgeIndependent"] is False
    assert "warning" in method
    assert method["judgeSawTestHints"] is False
    assert method["repeats"] == 1


def test_summary_carries_uncertainty_not_just_a_difference(tmp_path, monkeypatch, fake_llm):
    report, _, _, output = _run_ab(tmp_path, monkeypatch, cases=4)
    for kind in ("retention", "boundary"):
        stats = report["summary"][kind]["stats"]
        assert stats["ci"]["n"] >= 1
        assert "meanDiff" in stats
        assert "p" in stats["signTest"]
        assert "p" in stats["vetoMcNemar"]
        assert 0.0 <= stats["signTest"]["p"] <= 1.0
    # 区间与符号检验要印到终端，不能只躺在 JSON 里
    assert "符号检验" in output


def test_repeats_aggregate_instead_of_overwriting(tmp_path, monkeypatch, fake_llm):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "ab3.json"
    result = runner.invoke(
        cli,
        [
            "eval", "--ab", "--cases", "1", "--repeats", "3", "--seed", "3",
            "--api-key", "test-key", "--out", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    case = report["cases"][0]
    for arm in ("tool", "bare"):
        assert case[arm]["repeatCount"] == 3
        assert len(case[arm]["runs"]) == 3
        assert case[arm]["rubricAvg"] == 3.0
        assert case[arm]["vetoRate"] == 0.0
    # 3 例 × 2 臂 × 3 重复 = 6 次写作调用（本题 1 个用例）
    writes = [c for c in fake_llm if not c["json"]]
    assert len(writes) == 6


# ---------------------------------------------------------------- 单块消融（--arms）
# 为什么需要这一节：原来只有 tool vs bare 两臂，两臂差的是一整套流程，于是
# 「craft 3.3k token / 导师 1.2k token / 风格清单 2k token 谁在起作用」一个字都答不了。
# 线上实测：60 条真发出的 system 提示词里 craft 有 92% 的运行是关的，
# 导师块 100% 注入却从没单独测过——所以必须能逐个摘掉再比。


def _run_arms(tmp_path, monkeypatch, arms: str, *, cases=1, seed=20260409):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / f"ab-{arms.replace(',', '_')}.json"
    result = runner.invoke(
        cli,
        [
            "eval", "--ab", "--cases", str(cases), "--seed", str(seed),
            "--api-key", "test-key", "--arms", arms, "--out", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(out.read_text(encoding="utf-8")), result.output


def test_ablation_arms_run_and_report_against_the_baseline(tmp_path, monkeypatch, fake_llm):
    # cases=4 → 前两个是保留集、后两个是边界集，两个集合都要出汇总
    report, output = _run_arms(tmp_path, monkeypatch, "tool,no_craft,no_mentor,bare", cases=4)
    case = report["cases"][0]
    for arm in ("tool", "no_craft", "no_mentor", "bare"):
        assert "error" not in case[arm], (arm, case[arm])
    # 报告要能自证"这一轮到底跑了哪些臂、基准是谁"
    assert report["method"]["arms"] == ["tool", "no_craft", "no_mentor", "bare"]
    assert report["baselineArm"] == "tool"
    assert set(report["arms"]) == {"tool", "no_craft", "no_mentor", "bare"}
    # 每条消融臂都要有"相对基准"的配对读数（均值差 + 区间 + 符号检验）
    for kind in ("retention", "boundary"):
        cell = report["summary"][kind]
        for arm in ("no_craft", "no_mentor", "bare"):
            assert arm in cell["comparisons"], (kind, arm)
            st = cell["comparisons"][arm]
            assert st["base"] == "tool"
            assert "meanDiff" in st and "p" in st["signTest"]
    assert "配对读数 no_craft − tool" in output
    # 盲评文件仍只覆盖 tool vs bare：三稿以上人肉盲评没法读
    assert report["method"]["blindArms"] == ["tool", "bare"]


def test_no_craft_arm_really_drops_the_craft_block(tmp_path, monkeypatch, fake_llm):
    """三臂各摘一块，看 system 里到底少了什么。

    按"能区分三者的特征串"认臂，不要按顺序猜：
      tool      = 工艺 Skills 正文 + 导师块
      no_craft  = 「写作工艺：本轮关闭」占位 + 导师块
      no_mentor = 工艺 Skills 正文，但没有导师块
    """
    _run_arms(tmp_path, monkeypatch, "tool,no_craft,no_mentor")
    writes = [c for c in fake_llm if not c["json"]]
    assert len(writes) == 3, f"三臂应各一次写作调用，实际 {len(writes)}"

    has_skills = [c for c in writes if "写作工艺 Skills" in c["system"]]
    craft_off = [c for c in writes if "写作工艺：本轮关闭" in c["system"]]
    no_mentor = [c for c in has_skills if "写作导师" not in c["system"]]

    assert len(has_skills) == 2, "tool 与 no_mentor 该带工艺 Skills 正文"
    assert len(craft_off) == 1, "no_craft 该用「本轮关闭」那句占位（与线上 chat 任务一致）"
    assert len(no_mentor) == 1, "no_mentor 该带工艺但去掉导师块"
    assert "写作导师" in craft_off[0]["system"], "no_craft 只是摘工艺，导师块要留着"


def test_no_style_arm_keeps_skills_but_drops_the_style_guide(tmp_path, monkeypatch, fake_llm):
    _run_arms(tmp_path, monkeypatch, "tool,no_style")
    writes = [c for c in fake_llm if not c["json"]]
    with_style = next(c for c in writes if "写作风格 Skill" in c["system"])
    without = next(c for c in writes if c is not with_style)
    assert "写作工艺 Skills" in without["system"], "只是去掉风格硬约束，工艺 Skills 要留着"
    assert "写作风格 Skill" not in without["system"]


def test_unknown_arm_name_fails_loudly(tmp_path, monkeypatch, fake_llm):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli,
        ["eval", "--ab", "--cases", "1", "--api-key", "test-key", "--arms", "tool,nope"],
    )
    assert result.exit_code != 0
    combined = result.output + str(result.exception)
    assert "nope" in combined and "no_craft" in combined, combined


# ---------------------------------------------------------------- chat 用例集
# 为什么要单独量 chat：线上 60 次真实 Agent 运行里 55 次是 chat（讨论/审稿/追问），
# 而评测集以前一条 chat 用例都没有——"整条流程对讨论请求有没有用"从来没被量过。
# chat 用例走 agent_task=chat（工艺档按线上规则是关的），单独成一类，不污染
# retention/boundary 上的 craft/导师消融读数。


def test_chat_cases_form_their_own_section(tmp_path, monkeypatch, fake_llm):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "ab-chat.json"
    result = runner.invoke(
        cli,
        ["eval", "--ab", "--api-key", "test-key", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))

    kinds = {c["kind"] for c in report["cases"]}
    assert {"chat", "retention", "boundary"} <= kinds
    chat_cases = [c for c in report["cases"] if c["kind"] == "chat"]
    assert len(chat_cases) >= 3
    assert all(c["agentTask"] == "chat" for c in chat_cases)
    # 三类都要有汇总，chat 那一类里 tool 与 bare 都要有数
    assert set(report["summary"]) == {"chat", "retention", "boundary"}
    chat_summary = report["summary"]["chat"]
    for arm in ("tool", "bare"):
        assert chat_summary[arm]["n"] >= 3
        assert isinstance(chat_summary[arm]["rubricAvg"], float)
    # chat 用例里工艺档是关的：tool 与 no_craft 应该完全同分（同为 off）
    if "no_craft" in report["arms"]:
        d = chat_summary["comparisons"]["no_craft"]["meanDiff"]
        assert d == 0, f"chat 用例上工艺本来就关着，两者不该有差：{d}"
    assert "chat 讨论/审稿集" in result.output
