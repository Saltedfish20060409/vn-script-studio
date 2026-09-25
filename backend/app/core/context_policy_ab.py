"""上下文政策的 **A/B 量具**：只回答「该进上下文的东西有没有真的进来」。

## 它能回答什么、不能回答什么

**能**：同一部合成长篇、同一批提示词，改动前（`policy="legacy"`）与改动后（默认）两臂
各自跑**真实代码**，量出结构指标——埋点事实的命中条数、焦点章的**覆盖率**（这一章有多少
比例的段落进了上下文）、记忆层带进来多少字、超预算时是「整块让位」还是「从中间切一刀」。
纯本地计算、零 token、可进 CI。

**不能**：它**不**回答「写得好不好」。那需要**人工盲测**（`docs/blind-ab.md` 的工作纸 +
`eval_stats` 的配对区间），而且要如实说明样本量与成本。两张量具的关系是：
机制量先证明「材料进来了」，人工盲测再证明「进来以后写得更好」。

## 为什么用埋点事实与哨兵，而不是让模型打分

项目已经定过这条纪律（Art or Artifice? / Silent Judge）：**不要用模型给文学质量打分**。
而「某条前情事实有没有出现在拼装好的上下文里」是可以逐字核对的，所以这里只用它。

## 两臂到底在比什么

`build_agent_context(policy=...)` 只切换那几个常量与分支，其余代码路径完全相同：

| 维度 | 改动前（legacy） | 改动后（current） |
| --- | --- | --- |
| 主预算默认值 | 12000 字符 | `AGENT_CONTEXT_MAX_CHARS`（默认 48000） |
| 焦点章上限 | 写死 1800 / 5000 / 4200 | 按预算比例（续写类 `max(12000, 预算/2)`） |
| 记忆层单块上限 | 长程 3200 / 全局 2400 | 8000 / 6000 |
| 超预算处理 | 压缩其他章后**从中段切一刀** | **整块让位** + 如实说明 + 取回指令 |
| 篇幅说明 | 无 | 有（含「怎么取回」） |

旧常量抄自改动前的提交（`git show 4daa44a^:backend/app/core/agent_context.py`）。

## 三组对照

- **同预算组**：两臂都传同一个 `maxChars`，排除「预算变大」这个因素，只比政策本身。
- **同紧预算组**：压到两者都必须让位，专门对照「整块让位 + 说明」与「从中段切一刀」。
- **各自默认组**：政策 + 预算一起比——即用户实际看到的差别。

## 合成案例的构造

- N 章合成长篇，每章正文埋一条**互不重复**的事实句（「第 7 章记录：钟声一天只响两次。」）。
- 记忆层（长程 / 全局）由事实句加长成段拼成，长度**故意超过**旧上限，
  用来量「旧上限切掉了多少条事实」。
- 焦点章很长，被切成 `SENTINEL_COUNT` 段、每段开头一个唯一哨兵。
  **为什么是等距一串而不是首/中/尾三个**：三个哨兵只能回答「某三个点可见吗」，
  而截断点在哪是任意的——只留头尾的实现也可能恰好三个都命中，读数就失真了；
  一串哨兵给出的是**覆盖率**。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.core.agent_context import (
    CURRENT_POLICY,
    LEGACY_MID_CUT_MARKER,
    LEGACY_POLICY,
    build_agent_context,
)
from app.core.eval_stats import (
    format_ci,
    format_proportion,
    summarize_binary_paired,
    summarize_paired,
    wilson_interval,
)
from app.core.project import normalize_project

#: 事实句模板：每条带唯一章号，便于逐字核对「进了几条」。
FACT_TEMPLATE = "第 {n} 章记录：{label}。"

#: 合成案例用的事实内容（互不重复、也不互相包含）。
FACT_LABELS: List[str] = [
    "钟声一天只响两次",
    "失物招领处的门朝西开",
    "雨宫澪左手腕有旧伤",
    "末班车在二十三点零七分",
    "那张照片拍摄于十年前",
    "佐仓铃从不喝茶",
    "天台的门锁换过三次",
    "站台的电子屏常常延时",
    "旧钟楼在去年拆掉了",
    "两人的约定写在信纸背面",
    "广播里念的站名有一处错",
    "周屿的伞是深蓝色的",
    "校门口的银杏树被雷劈过",
    "档案室的第七个抽屉是空的",
    "那卷录音带只剩半面",
    "雪天里车站会提前关灯",
    "她姐姐最后一次刷卡在这个站",
    "值夜班的人换成了老人",
    "候车室的挂钟快四分钟",
    "售票口的窗玻璃换过一次",
]

#: 记忆层里每条事实后面缀的说明（把记忆块撑到旧上限之上，才能量出切掉了多少）。
MEMORY_PAD = (
    "（备忘：本条事实在本章修订时逐条核对过，若后续章节的描写与它冲突，以本条为准并回看对应章节。）"
)

#: 每条记忆行重复几遍说明——目的是让**每行约 200 字**、整块明显超过旧上限（3200 / 2400），
#: 这样「切掉了多少条事实」才是个能读出来的数，而不是恒为 0。
MEMORY_PAD_REPEATS = 3

#: 焦点章切成几段哨兵。等距一串给出的是覆盖率，对「截断点在哪」不敏感。
SENTINEL_COUNT = 10

#: 焦点章自己的事实句放在第几段（1 起）。
FOCUS_FACT_SEGMENT = 3

#: 填充用的几个句子（轮换使用，避免整章被同一句重复填满而被去重逻辑压掉）。
_FILLER_POOL = [
    "他站在屋檐下看水珠沿着伞骨落下去，路灯把水面照成一片碎金。",
    "她把伞收好往站台那边看了一眼，电子屏上的数字翻了一页。",
    "候车室的长椅上有人睡着了，广播念过两次站名都没把他叫醒。",
    "雨点打在铁皮顶上，声音密得像有人在屋顶上走。",
    "他数着对面楼的窗子，数到第七扇就不数了。",
]


def sentinel(index: int) -> str:
    """第 `index`（1 起）个哨兵串（两位补零，保证互不为子串）。"""
    return f"【哨兵-{index:02d}】"


def _filler_to(chars: int, seed: int = 0) -> str:
    """约 `chars` 个字符的填充文本；`seed` 决定从池中哪句开始轮换。"""
    if chars <= 0:
        return ""
    pool = [_FILLER_POOL[(seed + i) % len(_FILLER_POOL)] for i in range(len(_FILLER_POOL))]
    unit = "".join(pool)
    reps = max(1, chars // len(unit) + 1)
    return (unit * reps)[:chars]


def fact_label(index: int) -> str:
    """第 `index`（1 起）条事实的内容；超出表长时加编号，保证仍然唯一。"""
    if index <= len(FACT_LABELS):
        return FACT_LABELS[index - 1]
    return f"{FACT_LABELS[(index - 1) % len(FACT_LABELS)]}（第 {index} 次记载）"


def fact_sentence(index: int) -> str:
    """第 `index` 条事实句——两条臂都用同一个字符串去 `in` 判断。"""
    return FACT_TEMPLATE.format(n=index, label=fact_label(index))


def memory_line(index: int) -> str:
    """记忆层里的一条：事实句 + 加长说明（每条独立成行，便于逐条核对命中）。"""
    return fact_sentence(index) + (MEMORY_PAD * MEMORY_PAD_REPEATS)


def default_focus_chapters(total: int, count: int = 8) -> List[int]:
    """默认焦点章：末 `count` 章。

    为什么不只取末章：样本量 = 提示词条数，n=1 的报告给不出区间，
    也就没法区分「真的更好」和「这一例恰好如此」。多取几章是让区间能说话的**最低**成本。
    """
    keep = max(1, int(count))
    return list(range(max(1, total - keep + 1), total + 1))


def build_case(
    *,
    chapters: int = 40,
    focus_chapters: Optional[Sequence[int]] = None,
    focus_chars: int = 20_000,
    filler_chars: int = 600,
) -> Dict[str, Any]:
    """造一部带埋点事实的合成长篇 + 配套提示词与记忆层（确定性、可复现）。"""
    total = max(4, int(chapters))
    focus_set = {
        int(i) for i in (focus_chapters if focus_chapters else default_focus_chapters(total))
    }
    focus_set = {i for i in focus_set if 1 <= i <= total} or {total}

    seg_chars = max(60, int(focus_chars) // SENTINEL_COUNT)
    chapter_rows: List[Dict[str, Any]] = []
    for i in range(1, total + 1):
        if i in focus_set:
            segments: List[str] = []
            for k in range(1, SENTINEL_COUNT + 1):
                parts = [sentinel(k)]
                if k == FOCUS_FACT_SEGMENT:
                    parts.append(fact_sentence(i))
                parts.append(_filler_to(seg_chars, seed=k))
                segments.append("".join(parts))
            body = "\n".join(segments)
        else:
            body = "\n".join([fact_sentence(i), _filler_to(filler_chars, seed=i)])
        chapter_rows.append({"id": f"ch{i:03d}", "title": f"第{i}章", "prose": body})

    project = normalize_project(
        {
            "id": "p-context-ab",
            "title": "上下文政策对照",
            "characters": [
                {"id": "c1", "displayName": "雨宫澪", "defineName": "mio", "voice": "短句为主"},
                {"id": "c2", "displayName": "佐仓铃", "defineName": "sakura", "voice": "语速偏快"},
            ],
            "chapters": chapter_rows,
        }
    )

    # 记忆层：每条事实一行并加长，便于量「旧上限切掉了多少条」。
    long_memory = "## 长程记忆（逐章要点）\n" + "\n".join(
        memory_line(i) for i in range(1, total + 1)
    )
    global_memory = "## 全局记忆（全书要点）\n" + "\n".join(
        memory_line(i) for i in range(1, total + 1)
    )

    prompts = [
        {
            "chapterId": f"ch{i:03d}",
            "chapterOrdinal": i,
            "userMessage": "接着写下去，注意别和前文冲突。",
            "task": "continue",
        }
        for i in sorted(focus_set)
    ]
    return {
        "project": project,
        "longMemory": long_memory,
        "globalMemory": global_memory,
        "prompts": prompts,
        "facts": [fact_sentence(i) for i in range(1, total + 1)],
        "chapters": total,
    }


def _memory_facts(case: Dict[str, Any]) -> List[str]:
    """记忆层里出现过的事实句（保持章序）——只有这些才是「切记忆」能切掉的。"""
    blob = case["longMemory"] + "\n" + case["globalMemory"]
    return [f for f in case["facts"] if f in blob]


def _measure_one(
    case: Dict[str, Any],
    prompt: Dict[str, Any],
    *,
    policy: str,
    max_chars: Optional[int],
) -> Dict[str, Any]:
    """按给定政策拼一次上下文，量出这一例的结构指标（不联网、不调模型）。"""
    ctx = build_agent_context(
        case["project"],
        chapterId=prompt["chapterId"],
        userMessage=prompt["userMessage"],
        task=prompt["task"],
        maxChars=max_chars,
        longChapterMemory=case["longMemory"],
        globalMemory=case["globalMemory"],
        policy=policy,
    )
    text = ctx.text
    memory_facts = _memory_facts(case)
    report = ctx.budgetReport or {}
    return {
        "chapterId": prompt["chapterId"],
        "chars": len(text),
        "memoryFactTotal": len(memory_facts),
        "memoryFactHit": sum(1 for f in memory_facts if f in text),
        "focusTotal": SENTINEL_COUNT,
        "focusHit": sum(1 for k in range(1, SENTINEL_COUNT + 1) if sentinel(k) in text),
        "focusHead": sentinel(1) in text,
        "focusMid": sentinel(SENTINEL_COUNT // 2) in text,
        "focusTail": sentinel(SENTINEL_COUNT) in text,
        "droppedSections": len(report.get("droppedSections") or []),
        # 旧式「从中段切一刀」：只认旧常量本身（当前政策最后一次手段也会切，措辞不同，
        # 那条记在 lastResort 里，两者不能混为一谈）。
        "midCut": LEGACY_MID_CUT_MARKER in text,
        "lastResort": "上下文中段压缩" in text,
        "hasBudgetNotice": "篇幅说明" in text,
        "truncated": bool(ctx.truncated),
    }


def _paired_block(
    current: Sequence[Dict[str, Any]],
    legacy: Sequence[Dict[str, Any]],
    *,
    iters: int,
) -> Dict[str, Any]:
    def col(rows: Sequence[Dict[str, Any]], key: str) -> List[float]:
        return [float(r[key]) for r in rows]

    def rate(rows: Sequence[Dict[str, Any]], hit: str, total: str) -> List[float]:
        return [((r[hit] / r[total]) if r[total] else 0.0) for r in rows]

    numeric = {
        "memoryFactHit": summarize_paired(
            col(current, "memoryFactHit"), col(legacy, "memoryFactHit"), iters=iters
        ),
        "memoryFactRate": summarize_paired(
            rate(current, "memoryFactHit", "memoryFactTotal"),
            rate(legacy, "memoryFactHit", "memoryFactTotal"),
            iters=iters,
        ),
        "focusHit": summarize_paired(
            col(current, "focusHit"), col(legacy, "focusHit"), iters=iters
        ),
        "focusRate": summarize_paired(
            rate(current, "focusHit", "focusTotal"),
            rate(legacy, "focusHit", "focusTotal"),
            iters=iters,
        ),
        "chars": summarize_paired(col(current, "chars"), col(legacy, "chars"), iters=iters),
        "droppedSections": summarize_paired(
            col(current, "droppedSections"), col(legacy, "droppedSections"), iters=iters
        ),
    }
    binary: Dict[str, Any] = {}
    for key in (
        "focusHead",
        "focusMid",
        "focusTail",
        "midCut",
        "lastResort",
        "hasBudgetNotice",
        "truncated",
    ):
        cur = [bool(r[key]) for r in current]
        leg = [bool(r[key]) for r in legacy]
        row = summarize_binary_paired(cur, leg)
        row["current"] = wilson_interval(sum(cur), len(cur))
        row["legacy"] = wilson_interval(sum(leg), len(leg))
        binary[key] = row
    return {"numeric": numeric, "binary": binary}


def run_context_policy_ab(
    *,
    chapters: int = 40,
    focus_chapters: Optional[Sequence[int]] = None,
    focus_chars: int = 20_000,
    shared_max_chars: int = 48_000,
    tight_max_chars: int = 14_000,
    iters: int = 4000,
) -> Dict[str, Any]:
    """跑两臂，给出三组配对差（同预算 / 同紧预算 / 各自默认）。"""
    case = build_case(chapters=chapters, focus_chapters=focus_chapters, focus_chars=focus_chars)
    prompts = case["prompts"]

    def rows(policy: str, max_chars: Optional[int]) -> List[Dict[str, Any]]:
        return [_measure_one(case, p, policy=policy, max_chars=max_chars) for p in prompts]

    shared = _paired_block(
        rows(CURRENT_POLICY, shared_max_chars),
        rows(LEGACY_POLICY, shared_max_chars),
        iters=iters,
    )
    tight = _paired_block(
        rows(CURRENT_POLICY, tight_max_chars),
        rows(LEGACY_POLICY, tight_max_chars),
        iters=iters,
    )
    default = _paired_block(
        rows(CURRENT_POLICY, None),
        rows(LEGACY_POLICY, None),
        iters=iters,
    )

    notes = [
        "这是**机制量**：只证明「该进上下文的材料有没有真的进来」，不证明「写得更好」"
        "——质量结论只能来自人工盲测（docs/blind-ab.md 的工作纸 + eval_stats 的配对区间）。",
        "两臂跑的是**同一份真实代码**（只是 policy 参数不同），不是拿模型去模拟旧行为，"
        "因此结论可证伪、可复现。",
        "覆盖率的哨兵与事实句都是构造出来的：它能说明「机制保住了多少材料」，"
        "不能替代真实稿件的多样性，也不能代替读者。",
        "样本量 = 提示词条数。区间跨 0（或 McNemar p 很大）时如实写「方向不显著」，"
        "不把它包装成结论；n 很小时 Wilson 区间会很宽（n=8、8/8 也只有 68%–100%）。",
        "**同预算组**排除「预算变大」这个因素，只比政策本身；**各自默认组**是用户实际看到的"
        "差别（政策 + 预算 + 执行档一起）；**同紧预算组**专门压到两者都必须让位，"
        "用来对照「整块让位 + 说明」与「从中段切一刀」。",
    ]
    if len(prompts) < 5:
        notes.append(
            f"本次只有 {len(prompts)} 条提示词：配对区间会很宽，只能当定性参考；"
            "要看区间收窄请用 --context-ab-focus 多给几个焦点章。"
        )

    # 如实报出**反向差距**，而不是只挑对自己有利的那组数字。
    tight_fact = (tight["numeric"].get("memoryFactHit") or {}).get("meanDiff")
    if tight_fact is not None and float(tight_fact) < 0:
        notes.append(
            f"⚠ 预算被压到 {tight_max_chars} 字时出现了**反向差距**：带进记忆层的事实"
            f"反而是改动后更少（差 {float(tight_fact):+.1f} 条）。成因已查清（不是玄学）："
            "记忆块的整块上限是 8000 + 6000 字符，预算被压到 14000 时**根本装不下**，"
            "于是走 `_BUDGET_DROP_ORDER_LAST` 整块让位（并如实写进篇幅说明）；"
            "改动前把记忆切到 3200 / 2400，虽然也是残的，却塞得进去。"
            "也就是说：这条读数**不是**「改动后处处更好」，而是「预算不够时，"
            "改动后宁可整块不给、也不给半句话，并把损失写进上下文」。"
            "至于「半句话」和「什么都没有」哪个更糟，本量具**不判断**——那要人工盲测。"
            "预算够用时（同预算组 / 各自默认组）这个反向差距不出现，"
            f"所以真遇到小预算，正确的动作是把 AGENT_CONTEXT_MAX_CHARS 调到能装下记忆块"
            "（生产默认 48000），而不是动这里的取舍。"
        )

    return {
        "case": {
            "chapters": case["chapters"],
            "focusChapters": [p["chapterOrdinal"] for p in prompts],
            "factsPerBook": len(case["facts"]),
            "factsInMemory": len(_memory_facts(case)),
            "sentinelCount": SENTINEL_COUNT,
            "focusChars": focus_chars,
            "sharedMaxChars": shared_max_chars,
            "tightMaxChars": tight_max_chars,
        },
        "sameBudget": shared,
        "sameTight": tight,
        "ownDefault": default,
        "notes": notes,
    }


def _fmt_num(block: Dict[str, Any], key: str, label: str) -> str:
    row = (block.get("numeric") or {}).get(key) or {}
    ci = row.get("ci") or {}
    return (
        f"  {label}：改动后 {row.get('toolMean')} / 改动前 {row.get('bareMean')}"
        f"　差 {format_ci(ci)}"
    )


def _fmt_bin(block: Dict[str, Any], key: str, label: str) -> str:
    row = (block.get("binary") or {}).get(key) or {}
    cur = format_proportion(row.get("current") or {})
    leg = format_proportion(row.get("legacy") or {})
    return (
        f"  {label}：改动后 {cur} / 改动前 {leg}"
        f"　仅前者成立 {row.get('b')} 例 · 仅后者成立 {row.get('c')} 例 · McNemar p={row.get('p')}"
    )


def format_report(report: Dict[str, Any]) -> str:
    """终端可读的报告：数字 + 区间 + 「这说明了什么 / 不说明什么」。"""
    case = report.get("case") or {}
    lines: List[str] = [
        "上下文政策 A/B（改动后 vs 改动前；纯结构量，不调用模型）",
        f"- 合成作品：{case.get('chapters')} 章 · 埋点事实 {case.get('factsPerBook')} 条"
        f"（其中 {case.get('factsInMemory')} 条进了记忆层）",
        f"- 焦点章：{case.get('focusChapters')} · 每章约 {case.get('focusChars')} 字"
        f" · 每章 {case.get('sentinelCount')} 段哨兵（覆盖率 = 进了几段 / {case.get('sentinelCount')}）",
        "",
        f"【同预算组】两臂都传 maxChars={case.get('sharedMaxChars')} —— 排除「预算变大」，只比政策",
        _fmt_num(report["sameBudget"], "focusHit", "焦点章覆盖率（段）"),
        _fmt_num(report["sameBudget"], "memoryFactHit", "记忆层事实命中（条）"),
        _fmt_num(report["sameBudget"], "memoryFactRate", "记忆层事实命中率"),
        _fmt_num(report["sameBudget"], "chars", "上下文总长（字符）"),
        _fmt_num(report["sameBudget"], "droppedSections", "整块让位的块数"),
        _fmt_bin(report["sameBudget"], "focusHead", "焦点章·开头段可见"),
        _fmt_bin(report["sameBudget"], "focusMid", "焦点章·中段可见"),
        _fmt_bin(report["sameBudget"], "focusTail", "焦点章·结尾段可见"),
        _fmt_bin(report["sameBudget"], "midCut", "被旧式「中段切一刀」"),
        "",
        f"【同紧预算组】两臂都传 maxChars={case.get('tightMaxChars')} —— 都必须让位时怎么让",
        _fmt_num(report["sameTight"], "focusHit", "焦点章覆盖率（段）"),
        _fmt_num(report["sameTight"], "memoryFactHit", "记忆层事实命中（条）"),
        _fmt_num(report["sameTight"], "chars", "上下文总长（字符）"),
        _fmt_num(report["sameTight"], "droppedSections", "整块让位的块数"),
        _fmt_bin(report["sameTight"], "midCut", "被旧式「中段切一刀」"),
        _fmt_bin(report["sameTight"], "lastResort", "走了「中段压缩」这类最后手段"),
        _fmt_bin(report["sameTight"], "hasBudgetNotice", "带篇幅说明（含取回方式）"),
        "",
        "【各自默认组】政策 + 预算一起比 —— 用户实际看到的差别",
        _fmt_num(report["ownDefault"], "focusHit", "焦点章覆盖率（段）"),
        _fmt_num(report["ownDefault"], "memoryFactHit", "记忆层事实命中（条）"),
        _fmt_num(report["ownDefault"], "chars", "上下文总长（字符）"),
        _fmt_bin(report["ownDefault"], "focusMid", "焦点章·中段可见"),
        _fmt_bin(report["ownDefault"], "midCut", "被旧式「中段切一刀」"),
        "",
        "这说明什么 / 不说明什么：",
    ]
    lines += [f"- {note}" for note in (report.get("notes") or [])]
    return "\n".join(lines)
