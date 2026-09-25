"""上下文政策 A/B 量具自身的测试（`app.core.context_policy_ab`）。

这份测试要钉住的不是"读数是多少"（那是报告的事），而是三件容易悄悄坏掉的事：

1. **量具可复现**：同一输入两臂的输出必须逐位一致（不能有随机、时间、环境依赖）；
   否则"改了以后变好了"可能只是这次随机数不同。
2. **两臂真的不同**，且差异出现在**事先说好的那几处**（焦点章覆盖率、记忆层上限、
   中段切一刀 vs 整块让位 + 篇幅说明）——如果哪天两臂读数变得一样，
   说明 legacy 分支已经悄悄失效，报告会变成"改动前后没差别"的假结论。
3. **对照臂不会漏进生产**：`policy="legacy"` 只允许出现在 core 的两处、CLI 与测试里；
   任何 API / service 传它就等于把旧行为发给用户。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.core.agent_context import (
    CURRENT_POLICY,
    LEGACY_MID_CUT_MARKER,
    LEGACY_POLICY,
    _focus_budget,
    build_agent_context,
)
from app.core.context_policy_ab import (
    FACT_TEMPLATE,
    SENTINEL_COUNT,
    build_case,
    default_focus_chapters,
    fact_sentence,
    format_report,
    memory_line,
    run_context_policy_ab,
    sentinel,
)

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"

# ---- 合成案例：结构必须成立，否则后面所有读数都无意义 --------------------------


def test_facts_are_unique_and_templated():
    case = build_case(chapters=30)
    assert len(case["facts"]) == 30
    assert len(set(case["facts"])) == 30, "事实句必须互不重复，否则'命中几条'会重复计数"
    # 超出内置标签表时要自动加编号，仍然唯一
    from app.core.context_policy_ab import FACT_LABELS

    assert (
        len(set(fact_sentence(i) for i in range(1, len(FACT_LABELS) * 3 + 1)))
        == len(FACT_LABELS) * 3
    )
    assert fact_sentence(1) == FACT_TEMPLATE.format(n=1, label=FACT_LABELS[0])


def test_sentinels_are_not_substrings_of_each_other():
    """哨兵必须两位补零：`【哨兵-1】`这种写法会让 1 命中 10，覆盖率被虚高。"""
    tokens = [sentinel(k) for k in range(1, SENTINEL_COUNT + 1)]
    for i, a in enumerate(tokens):
        for j, b in enumerate(tokens):
            if i != j:
                assert a not in b, f"{a} 是 {b} 的子串"


def test_memory_lines_exceed_legacy_clip():
    """记忆块必须明显超过旧上限（3200 / 2400），否则量不出'旧上限切掉了多少条'。"""
    from app.core.agent_context import LEGACY_CLIP_GLOBAL_MEMORY, LEGACY_CLIP_LONG_MEMORY

    lines = [memory_line(i) for i in range(1, 41)]
    assert sum(len(x) for x in lines) > LEGACY_CLIP_LONG_MEMORY * 2
    assert sum(len(x) for x in lines) > LEGACY_CLIP_GLOBAL_MEMORY * 2


def test_default_focus_chapters_are_the_tail_and_multiple():
    """默认焦点章必须是"末若干章"且**不止一章**：n=1 的报告给不出区间。"""
    got = default_focus_chapters(40, count=8)
    assert got == [33, 34, 35, 36, 37, 38, 39, 40]
    assert len(default_focus_chapters(20, count=8)) >= 2
    # 项目章节数少于 count 时不能给出越界章号
    assert default_focus_chapters(3) == [1, 2, 3]


def test_build_case_is_deterministic():
    a = build_case(chapters=24, focus_chapters=[24])
    b = build_case(chapters=24, focus_chapters=[24])
    assert a["longMemory"] == b["longMemory"]
    assert a["globalMemory"] == b["globalMemory"]
    assert [c.prose for c in a["project"].chapters] == [c.prose for c in b["project"].chapters]


# ---- 两臂真的不同，而且差在说好的地方 ----------------------------------------


@pytest.fixture(scope="module")
def report() -> dict:
    return run_context_policy_ab(chapters=24, shared_max_chars=48000, tight_max_chars=14000)


def test_current_policy_keeps_more_of_the_focus_chapter(report):
    """同预算下：焦点章覆盖率必须优于旧政策（这是'失忆'那条改动的主判据）。"""
    row = report["sameBudget"]["numeric"]["focusHit"]
    assert row["n"] >= 5
    assert row["toolMean"] > row["bareMean"], row
    assert row["meanDiff"] > 0
    assert row["ci"]["crossesZero"] is False, "差异方向必须稳定，不是噪声"


def test_current_policy_keeps_more_memory_facts_when_budget_allows(report):
    row = report["ownDefault"]["numeric"]["memoryFactHit"]
    assert row["toolMean"] > row["bareMean"], row


def test_legacy_arm_still_mid_cuts_and_current_arm_does_not(report):
    """旧政策的标志行为：超预算时**从中段切一刀**（且不留说明）。"""
    tight = report["sameTight"]
    mid = tight["binary"]["midCut"]
    assert mid["c"] == mid["c"] and mid["c"] > 0, "旧政策在紧预算下必须出现中段切割"
    assert mid["b"] == 0, "新政策只在最后手段时才切，且措辞不同——不该计入旧式中段切割"
    assert tight["numeric"]["droppedSections"]["toolMean"] > 0, "新政策应当整块让位"
    notice = tight["binary"]["hasBudgetNotice"]
    assert notice["b"] > 0 and notice["c"] == 0, notice


def test_tight_budget_reports_the_reversed_gap_instead_of_hiding_it(report):
    """紧预算下新政策在'记忆层事实条数'上是**落后**的，报告必须如实写出来。

    这条测试的作用是防止有人为了让报告好看而删掉这条注记——那正是量具失去意义的时刻。
    """
    row = report["sameTight"]["numeric"]["memoryFactHit"]
    assert row["meanDiff"] < 0, row
    joined = "\n".join(report["notes"])
    assert "反向差距" in joined
    assert "不判断" in joined, "要写明本量具不对这个取舍下结论"


def test_report_is_json_serializable(report):
    """CLI 会把它写成 JSON：里面不能混进不可序列化的对象或 NaN/Inf。"""
    blob = json.dumps(report, ensure_ascii=False)
    assert "NaN" not in blob and "Infinity" not in blob

    # 递归确认只剩基本类型
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                assert isinstance(k, str)
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, float):
            assert math.isfinite(node)
        else:
            assert node is None or isinstance(node, (str, int, bool)), type(node)

    walk(report)


def test_format_report_is_readable_and_honest(report):
    text = format_report(report)
    assert "同预算组" in text and "同紧预算组" in text and "各自默认组" in text
    assert "不证明" in text, "报告必须写明它不证明'写得更好'"
    assert "95%CI" in text, "必须带区间，不能只给均值"
    assert len(text.splitlines()) > 20


def test_default_policy_is_current_and_matches_explicit_current():
    """`build_agent_context` 不传 policy 时，必须与显式 current 逐位一致。"""
    case = build_case(chapters=12, focus_chapters=[12], focus_chars=6000)
    p = case["prompts"][0]
    kwargs = dict(
        chapterId=p["chapterId"],
        userMessage=p["userMessage"],
        task=p["task"],
        maxChars=20000,
        longChapterMemory=case["longMemory"],
        globalMemory=case["globalMemory"],
    )
    implicit = build_agent_context(case["project"], **kwargs)
    explicit = build_agent_context(case["project"], **kwargs, policy=CURRENT_POLICY)
    assert implicit.text == explicit.text


def test_unknown_policy_string_falls_back_to_current():
    """写错政策名时不能悄悄跑到对照臂上——只有精确的 "legacy" 才切旧行为。"""
    case = build_case(chapters=12, focus_chapters=[12], focus_chars=6000)
    p = case["prompts"][0]
    kwargs = dict(
        chapterId=p["chapterId"],
        userMessage=p["userMessage"],
        task=p["task"],
        maxChars=20000,
        longChapterMemory=case["longMemory"],
        globalMemory=case["globalMemory"],
    )
    current = build_agent_context(case["project"], **kwargs, policy=CURRENT_POLICY)
    typo = build_agent_context(case["project"], **kwargs, policy="legacyy")
    legacy = build_agent_context(case["project"], **kwargs, policy=LEGACY_POLICY)
    assert typo.text == current.text
    assert legacy.text != current.text, "对照臂必须真的与当前政策不同，否则量具是假的"


def test_legacy_arm_never_writes_the_budget_notice():
    """旧政策没有「篇幅说明」这套东西——这正是要量给作者看的那部分差别。"""
    case = build_case(chapters=40, focus_chapters=[40])
    p = case["prompts"][0]
    legacy = build_agent_context(
        case["project"],
        chapterId=p["chapterId"],
        userMessage=p["userMessage"],
        task=p["task"],
        maxChars=13000,
        longChapterMemory=case["longMemory"],
        globalMemory=case["globalMemory"],
        policy=LEGACY_POLICY,
    )
    assert "篇幅说明" not in legacy.text
    assert LEGACY_MID_CUT_MARKER in legacy.text, "紧预算下旧政策应当留下中段切割标记"


# ---- 焦点章占比：试过的那一版上限必须保持撤回 --------------------------------


def test_focus_budget_keeps_the_floor_and_has_no_share_cap():
    """钉住撤回的那次实验：焦点章预算不得再长出"占总预算百分之多少"的上限。

    背景：曾经加过 `_FOCUS_SHARE_CAP = 0.70` 来避免小预算下记忆层被挤光，
    结果 `--context-ab` 显示记忆照样为 0、焦点章覆盖率反而从 6/10 掉到 5/10，
    于是撤回。这条测试是"别再来一遍"的守卫：小预算下焦点章仍然拿满 12000。
    """
    assert _focus_budget(14000, "continue") == 12000
    assert _focus_budget(48000, "continue") == 24000
    assert _focus_budget(40000, "outline") == 2400
    # polish / chat 走 35% 档（polish 保留末尾，但预算按"非续写"给——现有行为，钉住即可）
    assert _focus_budget(48000, "polish") == 16800
    assert _focus_budget(48000, "chat") == 16800
    assert _focus_budget(10000, "chat") == 6000


# ---- 源码级守卫：对照臂不能漏进生产 ------------------------------------------


def test_legacy_policy_is_only_used_by_the_measurement_path():
    """`policy=LEGACY_POLICY` / `"legacy"` 只允许出现在 core、CLI 与测试里。

    防的是一类"看起来无害"的改动：某个 service 为了兼容旧行为传 `policy="legacy"`，
    用户于是拿到被撤回的旧拼装方式，而报告还在说"改动后更好"。
    """
    allowed = {
        Path("core/agent_context.py"),
        Path("core/context_policy_ab.py"),
        Path("cli.py"),
    }
    offenders = []
    for path in BACKEND_APP.rglob("*.py"):
        rel = path.relative_to(BACKEND_APP)
        if rel in allowed:
            continue
        src = path.read_text(encoding="utf-8")
        if "LEGACY_POLICY" in src or 'policy="legacy"' in src or "policy='legacy'" in src:
            offenders.append(str(rel))
    assert offenders == [], f"对照臂只应存在于度量路径，这些文件越界了：{offenders}"


def test_measurement_module_never_calls_a_model():
    """量具必须是零 token 的：不能 import 任何 LLM 客户端/网络层。"""
    src = (BACKEND_APP / "core" / "context_policy_ab.py").read_text(encoding="utf-8")
    for banned in ("llm_http", "httpx", "requests", "openai", "chat_completions"):
        assert banned not in src, f"机制量不该依赖 {banned}"
