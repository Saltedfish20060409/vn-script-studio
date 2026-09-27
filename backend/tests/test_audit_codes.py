"""audit 码注册表的守卫：不允许"没登记的码"，也不允许缺码被伪装成正常码。

为什么专门一个文件（对齐 `tests/test_rule_basis.py` 的纪律）：
1. `core/pipeline/run_history.py` 把 `check.issues` 里 severity=error 的码写进
   `harnessRuns[].blockers[].code` 落库。码改名不报错，只让历史里的旧记录变成孤儿——
   所以码必须有注册表，且新增/改名必须**显式**登记。
2. `write_gate` 过去把缺失的 code 静默重贴成 `"harness"`：它看起来像一条正常规则，
   于是没人会去查。这里钉住两件事：缺码有自己的标记，且**任何 linter 都不许**报出它。

`EXPECTED_CODES` 刻意写成常量而不是"跑一遍看看"（照 `test_rule_basis.py` 的说明）：
跑一遍只能覆盖到当前 fixture 触发到的码，新增码会被悄悄绕过。写成常量之后，
新增一个码就必须同时改注册表和这里，否则红。

**范围是机器强制的**：守卫扫遍 `app/core/**` 的所有码字面量，每个出码的模块必须
要么在 `IN_SCOPE_SOURCES`（码全部登记），要么在 `OUT_OF_SCOPE_SOURCES`
（例外理由要写清）。新加一个 linter 无法"悄悄溜过"。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set

from app.core.harness.audit_codes import (
    AUDIT_CODE_BASIS,
    AUDIT_CODE_MISSING,
    CHAPTER_STABLE_CODES,
    DEFECT_MARKER_CODES,
    DRAFT_LOCAL_CODES,
    IN_SCOPE_SOURCES,
    OUT_OF_SCOPE_SOURCES,
    is_chapter_stable,
)
from app.core.harness.audit_full import full_audit_draft
from app.core.write_gate import _ANTIPATTERN_LABEL, _ANTIPATTERN_LINE_RES
from app.core.write_precheck import _CONTINUITY_FOCUS_CODES

BACKEND = Path(__file__).resolve().parent.parent
CORE = BACKEND / "app" / "core"

#: 反例生成器（`chapter_revise._hard_fail_snippets`）返回的原始名
ANTIPATTERN_SOURCE = "app/core/chapter_revise.py"

#: 注册表应有且仅有的码。改这里 = 承认自己动过码空间。
EXPECTED_CODES = {
    # narrative_lint
    "multi_question",
    "qa_pingpong",
    "long_monologue",
    "talk_heavy",
    "exposition",
    "cliche",
    # ai_flavor
    "ai_not_but",
    "ai_unlike_like",
    "ai_telegram_dialogue",
    "ai_dash_gloss",
    "ai_dash_dense",
    "ai_cliche",
    "otaku_shell",
    "ai_fragment_stack",
    "ai_guess_hedge",
    "ai_adverb_pile",
    "ai_said_tag",
    "ai_emotion_cliche",
    "ai_omniscient_spoil",
    "vn_dialogue_sparse",
    # style_skill
    "style_donot",
    "style_os_tag",
    "style_author_summary",
    "style_universal_ack",
    # beat_check
    "beats_empty_draft",
    "beat_missing",
    "beats_coverage",
    "beat_goal_weak",
    "beat_triggers_missing",
    "beat_cast_absent",
    "beat_semantic_unavailable",
    "beat_semantic_parse",
    "beat_semantic_missing",
    "beats_semantic_coverage",
    "beat_goal_semantic",
    "beat_triggers_semantic",
    # voice_lint / write_gate
    "voice_check_unavailable",
    "voice_break",
    "voice_drift",
    # 空稿
    "empty_draft",
    # 说明书硬伤（前缀在 write_gate 加）
    "antipattern:task_summary_ack",
    "antipattern:respect_lecture",
    "antipattern:apartment_tour",
    "antipattern:process_faq",
    "antipattern:inner_os",
    "antipattern:fake_choice",
    # 账本对账（章属性）
    "dead_character_present",
    "foreshadow_stale",
    "gone_location_present",
    "unknown_location_tag",
    "death_then_speaks",
    # 缺陷标记
    "code_missing",
}

#: 依据里必须出现一个可核对的源码位置
_SOURCE_PATH_RE = re.compile(r"app/core/[\w/]+\.py")

_ISSUE_CALLS = frozenset({"HarnessIssue", "NarrativeLintIssue", "PrecheckIssue"})


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _const_str(node: ast.AST) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def _scan_tree(tree: ast.AST) -> Set[str]:
    """静态扫出一棵 AST 里的 code 字面量。

    覆盖三种写法（本仓都用过）：
    - `HarnessIssue("warn", "ai_cliche", ...)`  位置参数
    - `NarrativeLintIssue(severity=..., code="multi_question", ...)`  关键字
    - `{"severity": "warn", "code": "empty_draft", ...}`  字典

    `code=code` / `"code": code` 这类透传不算字面量，自然扫不到——它们的真源在被调用方，
    由"在册模块的码都在注册表里"这条子集断言保证不会漏。
    """
    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in _ISSUE_CALLS:
                if name == "HarnessIssue" and len(node.args) >= 2:
                    lit = _const_str(node.args[1])
                    if lit:
                        found.add(lit)
                for kw in node.keywords:
                    if kw.arg == "code":
                        lit = _const_str(kw.value)
                        if lit:
                            found.add(lit)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if _const_str(key) == "code":
                    lit = _const_str(value)
                    if lit:
                        found.add(lit)
    return found


def _scan_rel(rel: str) -> Set[str]:
    path = BACKEND / rel
    assert path.exists(), f"清单里声明了 {rel}，但文件不存在"
    return _scan_tree(ast.parse(path.read_text(encoding="utf-8")))


def _codes_by_module() -> Dict[str, Set[str]]:
    """扫遍 `app/core/**`，返回"会报码的模块 → 它报的码"。"""
    out: Dict[str, Set[str]] = {}
    for path in sorted(CORE.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        found = _scan_tree(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            out[rel] = found
    return out


def _antipattern_names() -> Set[str]:
    """从 `_hard_fail_snippets` 里取出 `hits.append("…")` 的原始名。

    不写 fixture 去"跑一遍看看"：返回值是固定枚举，直接读源码更准也更稳。
    """
    tree = ast.parse((BACKEND / ANTIPATTERN_SOURCE).read_text(encoding="utf-8"))
    names: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_hard_fail_snippets":
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            if not isinstance(sub.func, ast.Attribute) or sub.func.attr != "append":
                continue
            if sub.args:
                lit = _const_str(sub.args[0])
                if lit:
                    names.add(lit)
    return names


# ---- 注册表本身的形状 -------------------------------------------------------


def test_registry_matches_the_explicit_expectation():
    """注册表必须与显式常量一致——新增码不能悄悄溜进去。"""
    assert set(AUDIT_CODE_BASIS) == EXPECTED_CODES, (
        f"注册表多出：{sorted(set(AUDIT_CODE_BASIS) - EXPECTED_CODES)}；"
        f"注册表缺少：{sorted(EXPECTED_CODES - set(AUDIT_CODE_BASIS))}"
    )


def test_every_basis_points_at_a_checkable_source():
    """每个码都要能指出"谁判的"——依据里必须有一个可核对的源码位置。"""
    for code, basis in AUDIT_CODE_BASIS.items():
        assert len(basis.strip()) > 8, f"{code} 的依据太短，等于没写：{basis!r}"
        assert _SOURCE_PATH_RE.search(basis), f"{code} 的依据看不出出处：{basis}"


def test_categories_partition_the_registry():
    """三组必须互不相交、且合起来正好覆盖注册表（新增码必须选边站）。"""
    stable = set(CHAPTER_STABLE_CODES)
    draft = set(DRAFT_LOCAL_CODES)
    marker = set(DEFECT_MARKER_CODES)

    assert not (stable & draft), f"章属性与稿属性重叠：{sorted(stable & draft)}"
    assert not (stable & marker) and not (draft & marker), "缺陷标记不该进语义分组"
    assert stable | draft | marker == set(AUDIT_CODE_BASIS), (
        f"没归类的码：{sorted(set(AUDIT_CODE_BASIS) - (stable | draft | marker))}；"
        f"归类了但没登记的码：{sorted((stable | draft | marker) - set(AUDIT_CODE_BASIS))}"
    )


def test_category_membership_anchors():
    """两个分组各自的语义锚点：改分类必须先改这两个断言。"""
    # 章属性：账本对账类（随章内容变化，可以做跨轮次状态）
    assert "dead_character_present" in CHAPTER_STABLE_CODES
    assert "foreshadow_stale" in CHAPTER_STABLE_CODES
    # 稿属性：文风 / 节拍 / 声线（随每一次生成变化，不该做状态）
    assert "ai_adverb_pile" in DRAFT_LOCAL_CODES
    assert "antipattern:inner_os" in DRAFT_LOCAL_CODES
    assert "beats_coverage" in DRAFT_LOCAL_CODES
    assert "voice_break" in DRAFT_LOCAL_CODES
    # 未知码一律不当章属性：宁可不做状态，也不要给一个会变的东西记账
    assert is_chapter_stable("dead_character_present") is True
    assert is_chapter_stable("ai_adverb_pile") is False
    assert is_chapter_stable("从来没有过的码") is False


# ---- 范围：出码的模块必须显式归类 -------------------------------------------


def test_scan_actually_finds_codes():
    """扫描器自己不能坏掉：一声不响的守卫比没有守卫更糟。"""
    by_module = _codes_by_module()
    assert len(by_module) >= 10, f"只扫到 {len(by_module)} 个出码模块，AST 扫描可能失效"


def test_every_module_that_emits_codes_is_classified():
    """**这条是范围闸**：`app/core` 里每个出码的模块，要么在册、要么写清例外理由。

    新加一个 linter、或在既有模块里加一个新的码前缀，都必须在这里显式决定归属。
    """
    declared = set(IN_SCOPE_SOURCES) | set(OUT_OF_SCOPE_SOURCES)
    unclassified = sorted(set(_codes_by_module()) - declared)
    assert not unclassified, (
        f"这些模块会报出 code，但既不在 IN_SCOPE_SOURCES 也不在 OUT_OF_SCOPE_SOURCES："
        f"{unclassified}。新加 linter 必须显式决定它的码要不要登记。"
    )


def test_in_scope_source_codes_are_all_registered():
    """在册模块里的码字面量必须都登记过——改名会在这里红。"""
    scanned: Set[str] = set()
    for rel in IN_SCOPE_SOURCES:
        scanned |= _scan_rel(rel)
    scanned |= {f"antipattern:{n}" for n in _antipattern_names()}
    assert scanned, "在册模块一个码都没扫到，AST 扫描可能失效"
    unregistered = sorted(scanned - set(AUDIT_CODE_BASIS))
    assert not unregistered, f"这些码在源码里出现但没登记：{unregistered}"


def test_out_of_scope_exceptions_are_written_and_checkable():
    """例外必须显式登记**并写清原因**（照 `test_rule_basis.py` 的做法）。"""
    for rel, reason in OUT_OF_SCOPE_SOURCES.items():
        assert (BACKEND / rel).exists(), f"例外清单里的 {rel} 不存在，清单烂了"
        assert len(reason.strip()) > 15, f"{rel} 的例外理由太短，等于没写"
        assert ("另有注册表" in reason) or ("不按 code 归档" in reason), (
            f"{rel} 的例外理由必须说清是《另有注册表》还是《不按 code 归档》：{reason}"
        )


def test_missing_code_marker_is_never_emitted_by_a_linter():
    """`code_missing` 是缺陷标记，不是规则：任何 linter 报出它都说明有 bug。"""
    scanned: Set[str] = set()
    for rel in IN_SCOPE_SOURCES:
        scanned |= _scan_rel(rel)
    assert AUDIT_CODE_MISSING not in scanned, (
        f"{AUDIT_CODE_MISSING} 被当成了真实规则码报出来，这会掩盖上游漏传 code 的 bug"
    )


def test_antipattern_namespace_is_closed():
    """`_hard_fail_snippets` 返回的名字、write_gate 的标签表、注册表三者必须对齐。"""
    names = _antipattern_names()
    assert names, "没扫到 `hits.append(...)`，结构可能变了"

    labels = set(_ANTIPATTERN_LABEL)
    assert names == labels, (
        f"反例生成器返回的名字与标签表不一致：生成器多 {sorted(names - labels)}，"
        f"标签表多 {sorted(labels - names)}"
    )
    # 只给了逐行抽取正则的那几个必须是标签表的子集（抽不出 quote 的会静默跳过 markHint）
    assert set(_ANTIPATTERN_LINE_RES) <= labels

    prefixed = {f"antipattern:{n}" for n in names}
    assert prefixed <= set(AUDIT_CODE_BASIS), (
        f"这些说明书硬伤码没登记：{sorted(prefixed - set(AUDIT_CODE_BASIS))}"
    )


def test_continuity_focus_codes_are_registered():
    """续写前对账从连续性体检里捞的那几个码也要登记。"""
    assert _CONTINUITY_FOCUS_CODES <= set(AUDIT_CODE_BASIS), (
        f"没登记：{sorted(set(_CONTINUITY_FOCUS_CODES) - set(AUDIT_CODE_BASIS))}"
    )


# ---- 实跑一遍：动态产生 / f-string 拼出来的码也要被覆盖 ----------------------


def test_full_audit_emits_only_registered_codes():
    """拿能触发多种硬伤的稿子实跑，断言报出来的码全在注册表里。

    这条兜的是静态扫描覆盖不到的情况（f-string 拼码、从词表生成码）。
    """
    drafts: List[str] = [
        # 叙事结构 + AI 味 + 风格 Skill
        "你叫什么？你从哪来？你为什么在这里？\n"
        "他缓缓地抬起头，缓缓地开口，缓缓地说了一句。\n"
        "不是害怕，是别的。不是逃避，是等待。\n"
        "原来如此。\n",
        # 内心 OS / 全知旁白
        "内心OS：其实凶手就是他的哥哥。\n",
        # VN 形态提示（长段几乎无对白）
        "他走进屋子。" + "屋里的东西都还在原来的位置上。" * 40,
    ]
    emitted: Set[str] = set()
    for draft in drafts:
        for raw in full_audit_draft(draft).get("issues") or []:
            code = str((raw or {}).get("code") or "")
            if code:
                emitted.add(code)

    assert emitted, "fixture 一个码都没触发，这条测试等于没测"
    unregistered = sorted(emitted - set(AUDIT_CODE_BASIS))
    assert not unregistered, f"实跑报出了没登记的码：{unregistered}"
    # 抽查两个"阈值写死在代码里"的码，确保 fixture 真的有效
    assert "ai_adverb_pile" in emitted
    assert "style_universal_ack" in emitted
