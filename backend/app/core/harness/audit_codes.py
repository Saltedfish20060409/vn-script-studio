"""audit 码注册表 —— 会**按 code 归档**的码必须在这里登记。

这不是文档，是一个真实缺陷的补丁，理由有两条：

1. **过去缺码会被静默重贴。** `write_gate.gate_continue_draft` 曾经写
   ``code = str(raw.get("code") or "harness")``：上游漏传 code 时，历史里会多出一个
   ``"harness"`` —— 它看起来像一个正常来源标签，于是没有人会去查。缺的信号应当如实
   标成"缺了"（本模块的 `AUDIT_CODE_MISSING`），而不是伪装成一个真实规则名。
   这与 `docs/references.md` 里那条既有纪律同源：**"缺的信号是 None（未测量），不是 0"**
   （Best-of-N 的 `peakedness` 一栏）。

2. **已经有一个按 code 归档的地方了。** `core/pipeline/run_history.py` 把
   `check.issues` 里 severity=error 的码写进 `harnessRuns[].blockers[].code` 落库。
   码一改名不会报错，只会让历史里的旧记录变成孤儿。本仓对"表 + 显式常量 + 解析源码比对"
   这套做法已有先例：`novel_consistency._RULE_BASIS` 配 `tests/test_rule_basis.py`。
   这里照同一套纪律做，只是对象换成 audit / 检查码。

## 范围（`tests/test_audit_codes.py` 机器强制，不靠自觉）

**在册**（`IN_SCOPE_SOURCES`）：它们的码能落进 `harnessRuns[].blockers[].code`，
或者能进 `write_precheck` 的对账报告 —— 也就是"会被按 code 读回去"的那些。

**刻意不在册**（`OUT_OF_SCOPE_SOURCES`）：每个都要写清理由。两类理由——
"已经另有注册表"（如 `novel_consistency._RULE_BASIS`，重复登记只会分叉），
或者"码只出现在按需计算的报告里，不按 code 归档"。

守卫会扫遍 `app/core/**` 的**所有**码字面量：既不在在册清单、也不在例外清单的模块，
直接红。所以新加一个 linter 时必须显式决定它的码归哪边，不能悄悄溜过。

## 三类分组（`tests/test_audit_codes.py` 钉住这是对注册表的一个划分）

- **章属性码**（`CHAPTER_STABLE_CODES`）：描述"这一章相对全书存在某个可证伪的事实/结构"
  （死人对账、伏笔陈旧、地点无认领…）。它随**章的内容**变化，所以"open → cleared"
  这种跨轮次状态语义对它成立。
- **稿属性码**（`DRAFT_LOCAL_CODES`）：描述"某一次生成出来的稿子"的特征
  （AI 味、套话、说明书腔、节拍没落实、声线跑偏…）。它随**每一句新正文**变化，
  "open → cleared" 对它不成立——把这类码写成持久状态，就是在给一个每次都变的东西记账。
- **缺陷标记**（`DEFECT_MARKER_CODES`）：不是规则，是"上游漏传 code"的标记，只让缺失可见。
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

#: 上游漏传 code 时的标记。**刻意起一个自曝其短的名字**：它出现在数据里就说明有 bug，
#: 而不是像 `"harness"` 那样看起来像一条正常规则。
AUDIT_CODE_MISSING = "code_missing"

#: 码 → 出处（哪个模块判的、判什么）。写法照 `novel_consistency._RULE_BASIS`：
#: **必须指向可核对的源码位置**，`tests/test_audit_codes.py` 会解析这个字符串里有没有
#: `app/core/...py` 形态的路径。
AUDIT_CODE_BASIS: Dict[str, str] = {
    # ---- 叙事结构（app/core/narrative_lint.py）----
    "multi_question": "`app/core/narrative_lint.py`：同一段里连问多个问题，读起来像审问",
    "qa_pingpong": "`app/core/narrative_lint.py`：问答乒乓（问一句答一句的整齐回合）",
    "long_monologue": "`app/core/narrative_lint.py`：单段独白过长，缺少动作与打断",
    "talk_heavy": "`app/core/narrative_lint.py`：对白占比过高、叙述推进不足",
    "exposition": "`app/core/narrative_lint.py`：疑似设定倾倒（把设定当台词念）",
    "cliche": "`app/core/narrative_lint.py`：套话偏多",
    # ---- AI 味（app/core/harness/ai_flavor.py）----
    "ai_not_but": "`app/core/harness/ai_flavor.py`：纠偏句式「不是A，是B」过密",
    "ai_unlike_like": "`app/core/harness/ai_flavor.py`：双否一肯／叠喻梯（不像A也不像B像C）",
    "ai_telegram_dialogue": "`app/core/harness/ai_flavor.py`：分工电报腔／电报式短句指令",
    "ai_dash_gloss": "`app/core/harness/ai_flavor.py`：破折号纠偏腔「——不是/像…」",
    "ai_dash_dense": "`app/core/harness/ai_flavor.py`：破折号密度偏高",
    "ai_cliche": "`app/core/harness/ai_flavor.py`：AI 高频套话重复出现",
    "otaku_shell": "`app/core/harness/ai_flavor.py`：日式次文化假朋友词误用",
    "ai_fragment_stack": "`app/core/harness/ai_flavor.py`：极短段堆叠（空心节奏腔）",
    "ai_guess_hedge": "`app/core/harness/ai_flavor.py`：猜测腔（仿佛/似乎/莫名）过密",
    "ai_adverb_pile": "`app/core/harness/ai_flavor.py`：软副词（缓缓/轻轻/微微）堆砌",
    "ai_said_tag": "`app/core/harness/ai_flavor.py`：「副词+说/道」情绪标签过密",
    "ai_emotion_cliche": "`app/core/harness/ai_flavor.py`：情绪陈词（概括情绪而非写反应）",
    "ai_omniscient_spoil": "`app/core/harness/ai_flavor.py`：旁白／内心OS 全知剧透",
    "vn_dialogue_sparse": "`app/core/harness/ai_flavor.py`：长段几乎无对白（VN 形态提示）",
    # ---- 风格 Skill（app/core/pipeline/style_skill.py）----
    "style_donot": "`app/core/pipeline/style_skill.py`：命中 `style_guide.md` 禁用词表",
    "style_os_tag": "`app/core/pipeline/style_skill.py`：标签式心理描写（内心OS/心声/吐槽）",
    "style_author_summary": "`app/core/pipeline/style_skill.py`：作者抒情升华／总结收束",
    "style_universal_ack": "`app/core/pipeline/style_skill.py`：万能回应（原来如此/我明白了）",
    # ---- 节拍对账（app/core/pipeline/beat_check.py）----
    "beats_empty_draft": "`app/core/pipeline/beat_check.py`：有节拍表但正文为空，无法对照节拍",
    "beat_missing": "`app/core/pipeline/beat_check.py`：某条节拍未在正文中体现",
    "beats_coverage": "`app/core/pipeline/beat_check.py`：节拍覆盖不足（多条无对应痕迹）",
    "beat_goal_weak": "`app/core/pipeline/beat_check.py`：正文弱相关于节拍目标",
    "beat_triggers_missing": "`app/core/pipeline/beat_check.py`：节拍触发物/钩子未在正文出现",
    "beat_cast_absent": "`app/core/pipeline/beat_check.py`：节拍情感收束涉及的角色正文未出现",
    "beat_semantic_unavailable": (
        "`app/core/pipeline/beat_check.py`：语义节拍检查不可用（软失败）"
    ),
    "beat_semantic_parse": "`app/core/pipeline/beat_check.py`：语义节拍判定的返回无法解析",
    "beat_semantic_missing": "`app/core/pipeline/beat_check.py`：语义判定给出的节拍缺失",
    "beats_semantic_coverage": "`app/core/pipeline/beat_check.py`：语义上节拍覆盖不足",
    "beat_goal_semantic": "`app/core/pipeline/beat_check.py`：语义上未达成节拍目标",
    "beat_triggers_semantic": "`app/core/pipeline/beat_check.py`：语义上未覆盖节拍触发条件",
    # ---- 声线检查（app/core/pipeline/voice_lint.py）----
    "voice_check_unavailable": "`app/core/pipeline/voice_lint.py`：角色声线检查未完成（软失败）",
    "voice_break": (
        "`app/core/pipeline/voice_lint.py`：声线偏离（voice_check 报告，hard 时升 error）"
    ),
    "voice_drift": "`app/core/write_gate.py`：写后声线指纹偏离角色画像（只 warn，不挡落地）",
    # ---- 空稿（app/core/pipeline/orchestrator.py）----
    "empty_draft": "`app/core/pipeline/orchestrator.py`：写路径产出为空稿，检查无从进行",
    # ---- 说明书硬伤（app/core/chapter_revise.py，前缀由 app/core/write_gate.py 加）----
    "antipattern:task_summary_ack": (
        "`app/core/chapter_revise.py::_hard_fail_snippets`：任务总结腔"
        "（前缀见 `app/core/write_gate.py`）"
    ),
    "antipattern:respect_lecture": (
        "`app/core/chapter_revise.py::_hard_fail_snippets`：尊重定义课"
        "（前缀见 `app/core/write_gate.py`）"
    ),
    "antipattern:apartment_tour": (
        "`app/core/chapter_revise.py::_hard_fail_snippets`：场景导览说明书"
        "（前缀见 `app/core/write_gate.py`）"
    ),
    "antipattern:process_faq": (
        "`app/core/chapter_revise.py::_hard_fail_snippets`：工序／百科问答"
        "（前缀见 `app/core/write_gate.py`）"
    ),
    "antipattern:inner_os": (
        "`app/core/chapter_revise.py::_hard_fail_snippets`：内心 OS 标签"
        "（前缀见 `app/core/write_gate.py`）"
    ),
    "antipattern:fake_choice": (
        "`app/core/chapter_revise.py::_hard_fail_snippets`：假选择"
        "（前缀见 `app/core/write_gate.py`）"
    ),
    # ---- 章属性 / 账本对账（app/core/write_precheck.py）----
    "dead_character_present": (
        "`app/core/write_precheck.py`：账本记为已故／不在场的角色仍出现在本章或本稿"
    ),
    "foreshadow_stale": "`app/core/write_precheck.py`：未回收伏笔已埋 ≥3 章",
    "gone_location_present": "`app/core/write_precheck.py`：设定里已标废弃／已毁的地点仍出现",
    "unknown_location_tag": (
        "`app/core/write_precheck.py`：从 `app/core/continuity_graph.py` 捞出的"
        "「焦点章场景图无地点认领」"
    ),
    "death_then_speaks": (
        "`app/core/write_precheck.py`：从 `app/core/continuity_graph.py` 捞出的「死人说话」"
    ),
    # ---- 缺陷标记（不是规则）----
    AUDIT_CODE_MISSING: (
        "**不是规则**：`app/core/write_gate.py` 在收到没有 code 的体检问题时的标记。"
        "它出现就说明上游 linter 漏传了 code，应当去修上游，而不是把它当一条规则处理"
    ),
}

#: 章属性码：随**章内容**变化，"open → cleared" 的跨轮次状态语义成立。
#: 只有这一组适合做账本对账／记忆锚。
CHAPTER_STABLE_CODES: FrozenSet[str] = frozenset(
    {
        "dead_character_present",
        "foreshadow_stale",
        "gone_location_present",
        "unknown_location_tag",
        "death_then_speaks",
    }
)

#: 稿属性码：随**每一次生成**变化。**不要**给它们做持久状态——
#: 那等于给一个每次都变的东西记账（见模块说明）。
DRAFT_LOCAL_CODES: FrozenSet[str] = frozenset(
    {
        "multi_question",
        "qa_pingpong",
        "long_monologue",
        "talk_heavy",
        "exposition",
        "cliche",
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
        "style_donot",
        "style_os_tag",
        "style_author_summary",
        "style_universal_ack",
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
        "voice_check_unavailable",
        "voice_break",
        "voice_drift",
        "empty_draft",
        "antipattern:task_summary_ack",
        "antipattern:respect_lecture",
        "antipattern:apartment_tour",
        "antipattern:process_faq",
        "antipattern:inner_os",
        "antipattern:fake_choice",
    }
)

#: 缺陷标记：既不是章属性也不是稿属性，不进任何一组的语义。
DEFECT_MARKER_CODES: FrozenSet[str] = frozenset({AUDIT_CODE_MISSING})

#: **在册**模块：它们的码会落进 `harnessRuns[].blockers[].code`，
#: 或者会进 `write_precheck` 的对账报告，所以必须全部登记。
IN_SCOPE_SOURCES: Tuple[str, ...] = (
    "app/core/narrative_lint.py",
    "app/core/harness/ai_flavor.py",
    "app/core/pipeline/style_skill.py",
    "app/core/pipeline/beat_check.py",
    "app/core/pipeline/voice_lint.py",
    "app/core/pipeline/orchestrator.py",
    "app/core/write_gate.py",
    "app/core/write_precheck.py",
    # 它的码是 `hits.append("名字")` 形态，静态扫描看不到 code 字面量；
    # 由 `tests/test_audit_codes.py::test_antipattern_namespace_is_closed` 单独钉住，
    # 登记进注册表时统一加 `antipattern:` 前缀。
    "app/core/chapter_revise.py",
)

#: 刻意**不**登记在 `AUDIT_CODE_BASIS` 里的模块——每个都要写清理由。
#: 照 `tests/test_rule_basis.py` 对"例外必须显式登记并写清原因"的做法：
#: 理由必须说清是"已经另有注册表"还是"不按 code 归档"，否则守卫会红。
OUT_OF_SCOPE_SOURCES: Dict[str, str] = {
    "app/core/novel_consistency.py": (
        "已经另有注册表：`app/core/novel_consistency.py` 的 `_RULE_BASIS` 配 "
        "`tests/test_rule_basis.py`（逐条核对前后端依据、并要求指向国标）。"
        "在两处重复登记只会让两份表分叉"
    ),
    "app/core/story_metrics.py": (
        "码只出现在按需计算的 `/analysis/story-metrics` 报告里，不按 code 归档"
    ),
    "app/core/choice_poetics.py": (
        "码只出现在按需生成的 `branch_recommendations` 建议里，不按 code 归档"
    ),
    "app/core/adaptation_checklist.py": (
        "码只出现在按需计算的改编体检读数里，不按 code 归档"
    ),
    "app/core/constraints.py": (
        "码只出现在按需计算的作者硬规则体检里，不按 code 归档"
    ),
}


def is_chapter_stable(code: str) -> bool:
    """这个码能不能被写成跨轮次的状态（账本对账／记忆锚）。未知码一律 False。"""
    return code in CHAPTER_STABLE_CODES
