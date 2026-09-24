"""Ported from packages/core/src/agentContext.ts"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.domain.types import Character, Location, SceneChapter, ScriptBlock, VnProject

from .chapter_digest import digest_all_chapters, format_chapter_digest_index
from .longform_memory import select_outline_beats

AgentTaskKind = str

# Specialized writing tasks — drives both prompt hints and retrieval bias.
AGENT_TASKS: List[str] = [
    "chat",
    "continue",
    "rewrite",
    "polish",
    "branch",
    "outline",
    "voice",
    "consistency",
    "scene",
]


def is_agent_task(v: Any) -> bool:
    return isinstance(v, str) and v in AGENT_TASKS


# --- 上下文预算政策（质量优先） ---------------------------------------------
#
# 立场（作者明确要求）：**"写差一次再花 token 重写"比"多带资料"更浪费**。
# 所以预算不是要省的资源，能装就装——上限只由两件硬事实决定：
#
# 1. **模型窗口**：塞爆窗口上游直接拒答，用户什么都拿不到（见 context_budget_for_model）。
# 2. **我们自己的超时预算**：预填充耗时随提示词线性增长，而 read timeout 覆盖
#    "预填充 + 生成"。预算放开而超时不放，就会重演用户报障过的假"后端没启动"。
#
# 于是 MAX 与 `llm_budget.PREFILL_MAX_BONUS` 成对存在，由
# `tests/test_context_budget_policy.py` 跨模块钉住不变量：
#     (MAX_CONTEXT_MAX_CHARS - PREFILL_FREE_CHARS) / PREFILL_CHARS_PER_SECOND ≤ PREFILL_MAX_BONUS
# 谁想再把上限调大，必须同时把预填充加时上限调大（前端阶梯表也读那个数）。
DEFAULT_CONTEXT_MAX_CHARS = 48000
"""默认主预算（字符）：旧值 12000 的 4 倍，为长篇留出"整章 + 记忆层 + 摘要"的余地。

按 1 token ≈ 1.4 汉字估，约 3.4 万 token——远小于最小预设窗口（128k），
也够放下一章正文（续写场景 24k）+ 长程记忆 8k + 全局记忆 6k + 人设与摘要。
"""

MAX_CONTEXT_MAX_CHARS = 96000
"""配置上限（字符，**同步档**）：超过这个量级，超时预算就不再能覆盖预填充（见上面的不变量）。

作者仍可用 AGENT_CONTEXT_MAX_CHARS 调整，但会被夹到这里；想真正突破，
改的是 `llm_budget.PREFILL_*`（那意味着"愿意为一次请求等更久"）。
"""

MAX_CONTEXT_MAX_CHARS_STREAMED = 240000
"""配置上限（字符，**流式档**）。

流式端点（SSE + 心跳、前端不设总超时）可以等更久，所以这里给到 240k 字符
（≈17 万 token）：长篇把"整章 + 全部记忆层 + 更多章节摘要"一起带上也装得下。
它与 `llm_budget.PREFILL_MAX_BONUS_STREAMED`（240s）成对，同样由不变量测试钉住。

代价如实记在这里：240k 字符的提示词按当前模型定价是**每次调用十几万输入 token**，
多步 Agent 会乘上步数。所以它是"上限"，不是目标——真的用到这么大的上下文，
应当先看 `GET /admin/llm-latency` 里的 promptChars 分布与截断率，再决定值不值。
"""

MIN_CONTEXT_MAX_CHARS = 3000
"""预算下限：低于这个数连人设+硬规则都装不下，拼出来的上下文只会误导模型。"""

_CHARS_PER_TOKEN = 1.2
"""1 token 至少装多少字符（**保守**取值：中文实测 ≈1.4–1.7，这里按 1.2 算窗口）。

算窗口容量时宁可低估：低估只是少带资料，高估会被上游直接拒答。
"""

_WINDOW_INPUT_SHARE = 0.5
"""输入最多占窗口的比例：另一半留给输出、思考过程、多轮工具结果。"""

UNKNOWN_MODEL_WINDOW_K = 128
"""**未知模型**的窗口保守假设（千 token）。

为什么要有这一条：预设表不可能收全（用户会手填自建端点、自部署模型、厂商新名字）。
此前"认不出来就不夹"，等于假设它的窗口无限大——对 32k 窗口的自部署模型来说，
一次 48k 字符的拼装会被上游直接拒答：**用户什么都拿不到**（比截断严重得多）。
所以改成按 128k token 保守估计（128k × 1.2 × 0.5 ≈ 76.8k 字符），
并在文档里说明：模型确实更大时用 `AGENT_UNKNOWN_MODEL_WINDOW_K` 声明真实窗口
（0 = 明确表示"不用夹"，负值同样视为不夹）。
"""
# 各资料块的**单块上限**。全部提到模块级，是为了让"预算够不够装下它们"这件事
# 可被测试断言（见 tests/test_context_budget_policy.py），而不是散在拼装代码里。
#
# 长程/全局记忆是**抗失忆的主要手段**（"四十章之前发生过什么"只有这两层有），
# 所以它们随预算一起放宽：旧值 3200/2400 在两百章的书里只够放十来条。
_CLIP_LONG_MEMORY = 8000
"""长程章节记忆（滚动归档）：最近这一段发生了什么。"""
_CLIP_GLOBAL_MEMORY = 6000
"""全局记忆（卷级总述与未回收伏笔）：整本书到目前为止的骨架。"""
_CLIP_CHAT_MEMORY = 2800
"""对话滚动记忆：非正式剧情，压得比较狠。"""
_CLIP_CRAFT = 2400
"""ACG 工艺卡：写作技法提示，属于"建议"而非"事实"，不必全带。"""
_CLIP_REFERENCE_DOCS = 12000
"""作者上传的参考资料：量大且与本章相关性最低，超预算时整块让位（排在丢弃序最前）。"""
_CLIP_SELECTION = 2000
"""用户选区：改写任务的焦点，超长选区本身就该先缩小。"""


def _default_context_max_chars(ceiling: int = MAX_CONTEXT_MAX_CHARS) -> int:
    """Agent 上下文主预算：优先 AGENT_CONTEXT_MAX_CHARS（Settings），默认 48000。

    用 try/except 包裹，保证纯上下文拼装（含测试）永远有可用默认值，
    不会因 SECRET_KEY 校验等环境问题抛错。
    `ceiling` 是执行档对应的天花板（同步 96k / 流式 240k，见 `context_budget_for_model`）。
    """
    try:
        from app.config import get_settings

        v = get_settings().agent_context_max_chars
        configured = int(v) if v else DEFAULT_CONTEXT_MAX_CHARS
    except Exception:  # noqa: BLE001 - core util must never raise for tuning knob
        configured = DEFAULT_CONTEXT_MAX_CHARS
    return max(MIN_CONTEXT_MAX_CHARS, min(configured, max(ceiling, MIN_CONTEXT_MAX_CHARS)))


def context_budget_for_model(
    model: Optional[str] = None,
    budget: Optional[int] = None,
    *,
    streamed: Optional[bool] = None,
) -> int:
    """按**所选模型的窗口**与**执行档**夹一次预算；窗口未知则不改行为。

    为什么要按窗口夹：预设里既有 1000k 的 DeepSeek，也有 32k 的本地 Ollama。
    预算是个"能装多少就装多少"的上限，遇到小窗口模型会被上游直接拒
    （context length exceeded）——那比截断更难善后，用户拿不到任何结果。

    为什么要按执行档分：天花板由**我们的超时预算**决定，而"能等多久"取决于
    客户端是不是看着进度条（见 `core/execution_profile.py`）。同步档 96k、流式档 240k；
    `streamed=None` 时读请求级档位（默认同步档，保守）。
    """
    if streamed is None:
        from app.core.execution_profile import is_streamed

        streamed = is_streamed()
    ceiling = MAX_CONTEXT_MAX_CHARS_STREAMED if streamed else MAX_CONTEXT_MAX_CHARS
    resolved = int(budget) if budget else _default_context_max_chars(ceiling=ceiling)
    window_k = _effective_window_k(model)
    if window_k:
        room = int(window_k * 1000 * _CHARS_PER_TOKEN * _WINDOW_INPUT_SHARE)
        resolved = min(resolved, room)
    return max(MIN_CONTEXT_MAX_CHARS, min(resolved, ceiling))


def _effective_window_k(model: Optional[str]) -> Optional[int]:
    """生效的模型窗口（千 token）；`None` = 不用夹。

    优先级（每一条都有理由）：
    1. **用户声明的窗口**（账号设置，请求级上下文）
       - 已知模型：`min(预设, 声明)`——用户只能调**低**，不可能超过厂商窗口；
       - 未知模型：直接用声明值（他自己知道自建端点的窗口，比我们的保守假设准）；
       - 声明为负 = 明确"不用夹"。
    2. **预设表**（`model_presets.context_window_k`）。
    3. **服务端保守假设** `AGENT_UNKNOWN_MODEL_WINDOW_K`（0/负 = 不夹）。
    """
    from app.core.execution_profile import declared_window_k

    declared = declared_window_k()
    try:
        from app.core.model_presets import context_window_k

        known = context_window_k(model or "")
    except Exception:  # noqa: BLE001 - 预设表不可用时不缩小（保持原行为）
        known = None

    if declared < 0:
        return None  # 用户明确表示不用夹
    if declared > 0:
        return min(known, declared) if known else declared
    if known:
        return known
    try:
        from app.config import get_settings

        raw = int(getattr(get_settings(), "agent_unknown_model_window_k", UNKNOWN_MODEL_WINDOW_K))
    except Exception:  # noqa: BLE001 - 配置不可用时用保守默认
        raw = UNKNOWN_MODEL_WINDOW_K
    if raw <= 0:
        return None  # 服务端明确声明"不用夹"
    return raw


@dataclass
class AgentContextOptions:
    chapterId: Optional[str] = None
    selection: Optional[str] = None
    # Latest user utterance — used for keyword retrieval
    userMessage: Optional[str] = None
    task: Optional[str] = None
    # Soft budget for the assembled context string
    maxChars: Optional[int] = None
    # Rolling chat memory (extractive, from client)
    chatMemory: Optional[str] = None
    # NovelMaster-style long chapter archive (from PostgreSQL)
    longChapterMemory: Optional[str] = None
    # Distilled ACG craft cards (萌百启发)
    loreCraft: Optional[str] = None
    # User-uploaded reference documents (plain text block)
    referenceDocs: Optional[str] = None


@dataclass
class AgentContextResult:
    text: str
    # Human-readable list of what was injected (for UI transparency)
    included: List[str]
    charsUsed: int
    task: str
    # 这次**没带**的资料块 key（前端可显示、可让作者改回来）
    excluded: List[str] = field(default_factory=list)
    # 「证明它记得」：这次实际依据了什么（可展开看摘录），前端默认摆出来
    includedDetails: List[Dict[str, str]] = field(default_factory=list)
    # 这次上下文是否**被裁过**（正文截断 / 整块让位 / 中段压缩任一发生）。
    # 单列一个布尔量是为了让调用方不必去解析 `included` 里的中文串就能统计截断率
    # （`GET /admin/llm-latency` 的 context 系列就用它）。
    truncated: bool = False
    # 「这次怎么拼的、有没有没装下的」的结构化报告（见 `_budget_report`）：
    # 界面上要稳定地列出"没装下的是什么、怎么取回来"，而不是解析中文标记。
    budgetReport: Dict[str, Any] = field(default_factory=dict)


# 可以被作者按需摘掉的资料块：key → 人话（前端「资料」面板直接用它渲染）
EXCLUDABLE_SECTIONS: Dict[str, str] = {
    "bible": "设定 bible（世界观 / 大纲 / 背景）",
    "lore": "设定条目",
    "longMemory": "长程章节记忆",
    # 卷级/全局记忆层（core/global_memory.py）：四十章之后"到目前为止发生了什么"的压缩表示
    "globalMemory": "全局记忆（卷级总述与未回收伏笔）",
    "craft": "ACG 工艺卡",
    "referenceDocs": "上传的参考资料",
    "chatMemory": "对话滚动记忆",
    "index": "章节目录与本地摘要",
    "characters": "角色卡",
    "relations": "角色关系",
    "locations": "地点与通路",
    "variables": "变量 / 状态机",
    "sprites": "立绘",
    "otherChapters": "其他章节摘录",
    "style": "文风记忆",
}

# 按任务默认丢掉的**噪音**块：机制类资料对写散文没用，带上去只会分散注意力。
# 注意：这里只放"去掉不影响正确性"的块（人设/地点/摘要一律保留）。
TASK_DROP_SECTIONS: Dict[str, set] = {
    "continue": {"sprites", "variables"},
    "rewrite": {"sprites", "variables"},
    "polish": {"sprites", "variables"},
    "chat": {"otherChapters"},
    # 下面几类同理：立绘是演出资源，对"怎么写"没有信息量。
    # **variables 不丢**：分支与场景的条件判断依赖它，丢了会写出走不通的选项。
    "branch": {"sprites"},
    "scene": {"sprites"},
    "voice": {"sprites", "variables"},
    "outline": {"sprites", "variables"},
}


def sections_to_drop(task: str, exclude: Optional[Iterable[str]] = None) -> set:
    """本轮要丢掉的资料块 = 任务默认裁剪 ∪ 作者手动摘掉的（只认已知 key）。"""
    drop = set(TASK_DROP_SECTIONS.get(task or "chat", set()))
    for key in exclude or []:
        if key in EXCLUDABLE_SECTIONS:
            drop.add(key)
    return drop


#: 上下文分块的**位置策略**。
#:
#: 依据 **Lost in the Middle: How Language Models Use Long Contexts**（arXiv:2307.03172）：
#: 长上下文里，模型对**开头**与**结尾**的信息利用最好，夹在中间的最容易被忽略；
#: 上下文越长这个偏差越明显。我们这里还有一层放大效应：**超预算时的裁剪是"保头保尾、
#: 压中段"**（见 build_agent_context 末尾），所以放在头部的块会被逐字保留，
#: 放在中段的块最先被压掉。两件事叠加，位置就不是审美问题，而是"哪些事实会被模型看到"。
#:
#: 于是分三组：
#: 1. **头部**——身份与"绝不能说错"的事实（硬规则、角色、关系、地点、设定、检索命中的
#:    条目、长程/全局/对话记忆）。它们是这一轮的地基，而且会被裁剪原样保留。
#: 2. **中段**——量大但通常不决定"这一步怎么写"的参考资料（章节目录、其它章摘录、
#:    写作参考卡、作者上传的参考文档、变量与立绘）。**参考文档最大（上限 12000 字）**，
#:    它过去排在头部，会把角色/关系挤进被压缩的中段——这正是这一版要修的。
#: 3. **尾部**——贴着用户这次请求的东西（文风样例、当前章正文、用户选区），
#:    紧接在末尾的硬规则与输出契约之前（那一小段是最后的"当场生效"区）。
#:
#: 任何一个 key 漏在这里都会被排到最后（`order_index.get(key, len(...))`），
#: 所以 `tests/test_context_ordering.py` 会断言这张表与代码里的 key 完全一致。
_SECTION_ORDER: Tuple[str, ...] = (
    # —— 头部：地基，且会被裁剪原样保留
    "meta",
    "rules",
    "characters",
    "relations",
    "locations",
    "bible",
    "timeline",
    "lore",
    "loreLinks",
    "longMemory",
    "globalMemory",
    "chatMemory",
    # —— 中段：量大但不决定"这一步怎么写"，超预算时最先被压
    "index",
    "otherChapters",
    "craft",
    "referenceDocs",
    "variables",
    "sprites",
    # —— 尾部：贴着这次请求（最近优先）
    "style",
    "focus",
    "selection",
)


# 每个任务的**硬规则**：短、可执行、且会在上下文末尾再重复一次。
# 为什么单列：长上下文里夹在中间的要求最容易被忽略，末尾的位置才是"当场生效"的。
TASK_KEY_RULES: Dict[str, List[str]] = {
    "continue": [
        "紧接「当前章节」正文末尾续写，不要重述已经写过的内容。",
        "只输出正文本身：不要解释、不要总结、不要加小标题。",
        "保持紧邻前文的人称、时态与专名；新出现的专名必须能在设定里找到出处。",
        "对白与叙述的比例、句子长短要贴近紧邻的前文。",
    ],
    "rewrite": [
        "只改指定的这一段（或这一章），其余一字不动。",
        "不新增事实、不删关键信息；专名原样保留。",
        "只输出正文本身：不要解释、不要前后对比。",
    ],
    "polish": [
        "只做语言层面的润色：节奏、用词、具体程度；不改情节。",
        "只输出润色后的正文，不加说明。",
    ],
    "consistency": [
        "逐条比对设定/台账与正文，指出冲突，并给出可执行的修法。",
        "不要为了「看起来没问题」而放过可疑处；拿不准就明确标出来。",
    ],
    # 下面这几类是**曾经缺位的**：它们当初没进这张表，于是回落到了 chat 的规则
    # （「除非我明确要求，否则不要改工程」），而同一轮 system 里的 task hint 却写着
    # 「append_script」——同一条 prompt 里自相矛盾，写出来的东西自然就不稳定。
    "branch": [
        "本轮产出的是**分支结构**：每个选项必须真的通向不同的后果；禁止「三个选项接同一段」的假分支。",
        "选项文案要短、有戏剧性、有取舍；不要在选项里解释设定。",
        "分支正文里的台词照常遵守人设与反倾倒规则（选项正文也要能演）。",
    ],
    "scene": [
        "写完整一小场戏：进场 → 冲突 → 收束钩子，不要停在半截。",
        "设定与人物关系靠动作和对白露出，不要宣讲；不要写镜头术语或分镜表。",
        "紧接当前章的时间与地点，不要无故跳场或引入未登场的人物。",
    ],
    "outline": [
        "输出分级大纲（卷 / 章 / 节），每条一句话，不要展开成正文。",
        "用戏剧事件推进，不要写成设定条目或世界观清单。",
        "只给方案，不要顺手改动工程正文。",
    ],
    "voice": [
        "只调整语气与用词，不改情节、不改专名。",
        "对照角色 voice / bio 与思维卡找破人设的句子，逐句给改法。",
        "只输出调整后的台词或段落，不写解释。",
    ],
    "chat": [
        "给结论与理由，不要客套、不要复述我的问题。",
        "除非我明确要求，否则不要改工程。",
    ],
}


def task_key_rules(task: str) -> List[str]:
    return TASK_KEY_RULES.get(task or "chat") or TASK_KEY_RULES["chat"]


# 每个任务的**输出契约**：长度与形态。写清楚"给我什么形状的东西"，
# 模型就不会拿解释、总结、小标题来凑数——这也是"工具不如裸聊"的一个常见原因。
TASK_OUTPUT_CONTRACT: Dict[str, str] = {
    "continue": "只输出续写的正文（300–900 字，用户另有要求按用户要求）；不要解释、不要小结、不要标题。",
    "scene": "只输出这一场的正文；场景切换用空行分隔，不要写镜头术语或舞台指令（除非用户要求）。",
    "rewrite": "只输出改写后的正文；长度与原文相当；不附说明、不附对照。",
    "polish": "只输出润色后的正文；不改情节、不改专名。",
    "consistency": "先列冲突（每条一行：位置 → 与什么设定冲突 → 建议改法），再给一句总体判断；不要重写正文。",
    "outline": "输出分级大纲：卷/章/节三层用缩进或编号表示；每条一句话，不要展开成正文。",
    "branch": (
        "输出 2–4 个分支（Ren'Py menu 形态）：每项一行选项文案，紧跟该选项的正文（或 jump 到 label）；"
        "选项之间后果必须不同；不要解释、不要小结、不要给「建议」。"
    ),
    "voice": "输出调整后的台词或段落；旁边不写解释。",
    "chat": "直接回答：先结论后理由；需要时给可执行的改法；不要复述我的问题。",
}


def output_contract(task: str) -> str:
    return TASK_OUTPUT_CONTRACT.get(task or "chat") or TASK_OUTPUT_CONTRACT["chat"]


TASK_HINTS: Dict[str, str] = {
    "chat": (
        "本轮模式：自由讨论。可给方案、点评、大纲；把完整意见写进 message。"
        "仅当用户明确要求写入工程时再给 actions。设定勿当讲义复述。"
        "若用户征求修改意见/点评长文分析：actions=[]，用 message 长文回应。"
    ),
    "continue": (
        "本轮任务：续写一小段可上演节拍。紧接【当前章末尾】；人设只校准语气。禁止设定宣讲；"
        "禁止陌生人连问盘人（一拍一角色 ideally ≤1 问）；信息用环境/失言/残缺感推进。默认 append_script；不要重写前文。"
        "message 须简要说明本段节拍意图。"
    ),
    "rewrite": (
        "本轮任务：改写选区。保持剧情意图，砍盘问串与说明书腔，提升画面感与对白张力；"
        "append_script 追加改写稿（勿 replace 整章，除非用户要求）。message 说明改法要点。"
    ),
    "polish": (
        "本轮任务：润色。不改情节；重点砍盘问串、问答乒乓、过熟闲聊与套话，打磨对白自然度；"
        "append_script 写入。message 说明润了哪些口气问题。"
    ),
    "branch": (
        "本轮任务：有意义的分支。2～4 个 Ren'Py menu，每项后果不同；选项文案短而有戏剧性，"
        "勿在选项里塞设定说明；append_script。"
    ),
    "outline": "本轮任务：场景大纲。规划 3～5 场（冲突/人物/钩子），用戏剧事件而非设定条目来写；先 message；同意后再 update_bible/add_chapter。",
    "voice": "本轮任务：人设语气审校。对照 voice/bio 找破功句；改写时仍禁止设定宣讲与过熟盘问。",
    "consistency": (
        "本轮任务：一致性排查。列矛盾与最小改法；报告里可以引用设定，但建议写入正文时仍遵守反倾倒。"
        "优先用 get_chapter 一次读多章（chapterRefs）做跨章对照，再结合 get_character/get_bible 核对；"
        "不要只凭片段猜。"
    ),
    "scene": (
        "本轮任务：写完整一小场戏（进场→冲突→收束钩子）。设定溶于表演；对照社交温度与人设惜话程度，"
        "勿把冷角色写成访谈主持。append_script。"
    ),
}


def infer_agent_task(message: str) -> str:
    m = message.strip()
    # Long paste asking for opinions/critique stays in chat (don't mis-fire rewrite).
    if len(m) > 800 and re.search(
        r"(修改意见|审稿|你觉得|对吗|据此|怎么改|提一些|征求)", m
    ):
        return "chat"
    if re.search(r"【任务：续写】|^续写|请续写|往下写", m):
        return "continue"
    if re.search(r"【任务：改写】|改写选区", m) or (
        len(m) < 240 and re.search(r"请改写", m)
    ):
        return "rewrite"
    if re.search(r"【任务：润色】|请润色", m):
        return "polish"
    if re.search(r"【任务：分支】|生成分支|设计分支|menu", m):
        return "branch"
    if re.search(r"【任务：大纲】|场景大纲|给出.*大纲", m):
        return "outline"
    if re.search(r"【任务：语气】|统一语气|人设一致|voice", m):
        return "voice"
    if re.search(r"【任务：查矛盾】|一致性|矛盾|冲突检查|状态机", m):
        return "consistency"
    if re.search(r"【任务：写一场戏】|写一场戏|完整一场|一场戏", m):
        return "scene"
    return "chat"


def task_hint(task: str) -> str:
    # 不再用 TASK_HINTS[task]：调用方（含 API）传了未登记的任务名时，
    # 这里过去会抛 KeyError，把整轮对话打断；回落到 chat 才是合理行为。
    return TASK_HINTS.get(task or "chat") or TASK_HINTS["chat"]


def _js(v: Optional[str]) -> str:
    """Mirror JS template-literal embedding of an undefined value as 'undefined'."""
    return v if v is not None else "undefined"


def chapter_plain(ch: Optional[SceneChapter], characters: Optional[List[Character]] = None) -> str:
    """一章的纯文本：**正文优先**，正文为空才回落到脚本块。

    这是全项目读"一章的正文"的唯一口径（工具、摘要、上下文都走它）：
    - 口径与 `consistency_scan._chapter_source_text`、`writing_stats.count_chapter_words`
      一致：正文（`prose`）优先，正文为空才渲染脚本块。
    - 曾经的坑：`agent_tools.get_chapter` / `agent_context.plain_of` 只读 `blocks`，
      对本作品的主写作面（`prose`）等于瞎——纯正文工程里 `get_chapter` 返回空、
      「当前章节」只剩标题。这正是记忆探针（`core/memory_probe.py` 的 focus-body
      探针）抓到的"证据根本没进上下文"，它的表现与"模型记不住"一模一样。
    """
    if ch is None:
        return ""
    prose = str(getattr(ch, "prose", None) or "").strip()
    if prose:
        return prose
    return _blocks_to_plain(list(getattr(ch, "blocks", None) or []), list(characters or []))


def _blocks_to_plain(blocks: List[ScriptBlock], characters: List[Character]) -> str:
    char_map = {c.id: c for c in characters}
    lines: List[str] = []
    for b in blocks:
        btype = b.get("type")
        if btype == "label":
            line: Optional[str] = f"[label {b['name']}]"
        elif btype == "scene":
            line = f"[scene {b['image']}]"
        elif btype == "show":
            line = f"[show {b['image']}]"
        elif btype == "hide":
            line = f"[hide {b['image']}]"
        elif btype == "narration":
            line = f"旁白: {b['text']}"
        elif btype == "dialogue":
            ch = char_map.get(b.get("characterId"))
            name = ch.displayName if ch else b.get("characterId")
            line = f"{name}: {b['text']}"
        elif btype == "menu":
            line = f"选项: {' / '.join(c['text'] for c in b.get('choices', []))}"
        elif btype == "jump":
            line = f"[jump {b['target']}]"
        elif btype == "comment":
            line = f"# {b['text']}"
        elif btype == "raw":
            line = b.get("code", "")
        elif btype == "music":
            line = (
                f"[音乐 {b.get('file') or ''}]"
                if (b.get("action") or "play") == "play"
                else "[音乐 停]"
            )
        elif btype == "sound":
            line = (
                f"[音效 {b.get('file') or ''}]"
                if (b.get("action") or "play") == "play"
                else "[音效 停]"
            )
        elif btype == "voice":
            line = (
                f"[语音 {b.get('file') or ''}]"
                if (b.get("action") or "play") == "play"
                else "[语音 停]"
            )
        elif btype == "wait":
            line = f"[等待 {b.get('seconds') or 0} 秒]"
        elif btype == "camera":
            zoom = b.get("zoom")
            line = f"[镜头 at {b['at']}]" if b.get("at") else f"[镜头 zoom={zoom or 1}]"
        elif btype == "effect":
            line = f"[特效 {b.get('kind') or ''}]"
        elif btype == "set":
            line = f"[变量 {b.get('key')} {b.get('op') or '='} {b.get('value')}]"
        elif btype == "if":
            # 条件分支：把每个分支的条件与正文都折进行，让 AI 看得到分支结构
            branch_bits = []
            for branch in b.get("branches") or []:
                cond = (branch.get("condition") or "").strip() or "否则"
                body = _blocks_to_plain(branch.get("blocks") or [], characters)
                branch_bits.append(f"条件({cond}) {{ {body} }}")
            line = "[如果 " + " 否则 ".join(branch_bits) + "]" if branch_bits else ""
        else:
            line = ""
        if line:
            lines.append(line)
    return "\n".join(lines)


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}")
_CJK_ONLY = re.compile(r"^[\u4e00-\u9fff]+$")


def _tokenize(query: str) -> List[str]:
    lower = query.lower()
    tokens: List[str] = []
    seen: set = set()

    def _add(tok: str) -> None:
        if tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    for m in _TOKEN_RE.finditer(lower):
        t = m.group(0)
        if len(t) >= 2:
            _add(t)
        # CJK bigrams for denser matching
        if _CJK_ONLY.match(t) and len(t) >= 3:
            for i in range(len(t) - 1):
                _add(t[i : i + 2])
    return tokens[:80]


def _score_haystack(hay: str, tokens: List[str]) -> int:
    if not tokens or not hay:
        return 0
    h = hay.lower()
    score = 0
    for tok in tokens:
        if tok not in h:
            continue
        score += 4 if len(tok) >= 4 else 3 if len(tok) >= 3 else 2
    return score


def _ask_text(userMessage: Optional[str], selection: Optional[str]) -> str:
    """提问原文（小写）。名字类命中要按"整串出现在提问里"判断，不能只看分词。"""
    return "\n".join([userMessage or "", selection or ""]).lower()


def _names_of(obj: Any, *field_names: str) -> List[str]:
    """取一个条目的所有叫法：主名字段 + aliases 列表。"""
    out: List[str] = []
    for f in field_names:
        v = getattr(obj, f, None)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    aliases = getattr(obj, "aliases", None)
    if isinstance(aliases, (list, tuple)):
        for a in aliases:
            if isinstance(a, str) and a.strip():
                out.append(a.strip())
    # 去重但保序
    seen: set = set()
    uniq: List[str] = []
    for n in out:
        low = n.lower()
        if low not in seen:
            seen.add(low)
            uniq.append(n)
    return uniq


def _name_hit_bonus(names: Sequence[str], ask: str) -> int:
    """名字/别名**整串**出现在提问里 = 强信号。

    为什么单独算：只靠分词的话，"雪见" 这种两字名字只值 2 分，而正文里随便一个
    常见词也可能值 2~4 分——命中名字反而被淹没。名字命中应该明显压过正文里的巧合。
    """
    if not ask:
        return 0
    bonus = 0
    for n in names:
        low = n.strip().lower()
        if len(low) >= 2 and low in ask:
            bonus += 10
    return min(bonus, 20)


def _entry_text(e: Any) -> str:
    return str(getattr(e, "body", "") or "")


def _entry_keywords(e: Any) -> List[str]:
    raw = getattr(e, "keywords", None)
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(k).strip() for k in raw if str(k).strip()]


def _entry_score(e: Any, ask: str, tokens: List[str]) -> int:
    """设定条目的相关度：触发词 > 标题 > 正文（正文封顶，防止长文里凑巧撞词）。

    标题命中按"标签级"计入（每个命中词 5 分），因为标题通常就是条目的名字
    （"镜湖封印推演"里的"镜湖"），比正文里恰好出现同一个字可靠得多。
    """
    keys = _entry_keywords(e)
    title = str(getattr(e, "title", "") or "")
    title_low = title.lower()
    score = 0
    for k in keys:
        low = k.lower()
        if len(low) >= 2 and low in ask:
            score += 12
    if len(title) >= 2 and title_low in ask:
        score += 8
    score += _score_haystack(" ".join(keys), tokens)
    title_hits = sum(1 for tok in tokens if len(tok) >= 2 and tok in title_low)
    score += min(title_hits * 5, 15)
    # 正文命中只算很弱的信号，并且封顶（长正文里撞到常见词太容易了）
    score += min(_score_haystack(_entry_text(e), tokens), 6)
    return score


# 非钉住的条目至少要过这条线才进上下文。
#
# 取值依据（用 80 条目的评测语料量过）：正文命中两个词 ≈ 4 分，是"这条确实相关"的
# 最低可信信号（例如问"白砚的妹妹去哪了"命中正文里的"白砚/妹妹"）；只撞上一个两字词
# （2 分）多半是巧合，滤掉。而没进来的条目仍会以标题形式出现在末尾的可点名提示里，
# 所以这里收紧的是**精度**，不是召回。
_ENTRY_MIN_SCORE = 4


def rank_lore_entries(
    entries: Sequence[Any],
    query: str,
    *,
    limit: int = 8,
    min_score: int = _ENTRY_MIN_SCORE,
) -> List[Tuple[Any, int]]:
    """按提问给设定条目打分排序。

    存在的理由：自动注入（开场拼上下文）和 Agent 的 `search_lore` 工具必须是**同一把尺子**，
    否则会出现"工具说命中、注入却不带"这种自相矛盾的行为。所以两处都走这个函数。
    """
    ask = (query or "").strip().lower()
    tokens = _tokenize(query or "")
    scored = [
        (e, _entry_score(e, ask, tokens))
        for e in (entries or [])
        if e is not None and not bool(getattr(e, "pinned", None))
    ]
    scored = [(e, s) for e, s in scored if s >= min_score]
    scored.sort(
        key=lambda pair: (pair[1], int(getattr(pair[0], "priority", 0) or 0)),
        reverse=True,
    )
    return scored[: max(1, limit)]


def lore_entry_index(entries: Sequence[Any], limit: int = 60) -> str:
    """条目索引（标题 + 触发词一行一条）：模型不知道叫什么名字时先看这个。"""
    lines: List[str] = []
    for e in (entries or [])[:limit]:
        if e is None:
            continue
        title = str(getattr(e, "title", "") or "").strip()
        if not title:
            continue
        keys = _entry_keywords(e)
        pin = " ☆钉住" if bool(getattr(e, "pinned", None)) else ""
        lines.append(f"- {title}" + (f"（{'/'.join(keys)}）" if keys else "") + pin)
    return "\n".join(lines)


def _clip(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 12]}\n…(截断)"


def _char_card(c: Character) -> str:
    from app.core.character_voice.corpus import format_corpus_for_prompt, format_mind_for_prompt

    mind = format_mind_for_prompt(c, max_chars=1600)
    corpus = format_corpus_for_prompt(c, max_samples=6, max_chars=1400)
    return "\n".join(
        p
        for p in [
            f"- {c.displayName} ({c.defineName})",
            f"  语气: {c.voice}" if c.voice else "",
            f"  人设: {c.bio}" if c.bio else "",
            f"  关系: {c.relationships}" if c.relationships else "",
            mind,
            corpus,
        ]
        if p
    )


def _loc_card(l: Location) -> str:
    tags = f" #{'#'.join(l.tags)}" if l.tags else ""
    return (
        f"- {l.name}"
        + (f" [{l.imageTag}]" if l.imageTag else "")
        + (f": {l.description}" if l.description else "")
        + tags
    )


def _focus_budget(max_chars: int, task: str) -> int:
    """焦点章正文能占多少字符（按总预算分档，而不是写死 5000）。

    写死 5000 的直接后果：一章三千字的稿子没问题，**一章两万字的稿子续写时模型只
    看得到最后一小截**，于是"失忆"发生在作者最需要连贯的地方。所以这里改成按预算
    比例给，续写类给到一半——"接着写"本来就该以本章正文为主体。
    """
    if task == "outline":
        return max(1800, int(max_chars * 0.06))  # 大纲任务不需要正文，只要摘要
    if task in ("continue", "branch", "scene"):
        return max(12000, int(max_chars * 0.5))
    return max(6000, int(max_chars * 0.35))


def _chapter_tail(plain: str, max_len: int, *, hint: str = "") -> str:
    """保留末尾（续写要接的就是末尾），省略量如实写在标记里。

    标记里必须带上"省了多少字"和取回方式：作者看到自己三千字的前情没进去，
    才知道该用工具取或缩小范围；模型看到同一行，也不会以为这章只有这么长。
    """
    if len(plain) <= max_len:
        return plain
    dropped = len(plain) - max_len
    return f"…(本章前 {dropped} 字未展开{hint})…\n{plain[len(plain) - max_len:]}"


def _chapter_head_tail(plain: str, max_len: int, *, hint: str = "") -> str:
    if len(plain) <= max_len:
        return plain
    head = int(max_len * 0.35)
    tail = max_len - head - 20
    dropped = len(plain) - head - tail
    return f"{plain[:head]}\n…(本章中段 {dropped} 字未展开{hint})…\n{plain[len(plain) - tail:]}"


#: 正文被压缩时提示模型"缺的东西可以取回来"的唯一说明（不要在各处重写一遍）。
_RETRIEVE_HINT = "，可用 get_chapter 工具取回整章"


def _section_label(key: str) -> str:
    """资料块 key → 人话（复用可摘清单里的说法，避免两处各起一个名字）。"""
    return (
        EXCLUDABLE_SECTIONS.get(key)
        or _SECTION_LABELS_EXTRA.get(key)
        or key
    )


#: **不可摘**（但会在"这次带了什么"里出现）的块的人话名。
#: 单独一张表而不是塞进 `EXCLUDABLE_SECTIONS`：那个字典是给"作者可以摘掉哪些块"用的，
#: 把 meta/rules 这类塞进去会在界面上给出"可以摘掉写作规则"的假选项。
#: 为什么这些也要有名字：`budgetReport.includedSections` 会原样显示，露出英文 key 很丑。
_SECTION_LABELS_EXTRA: Dict[str, str] = {
    "meta": "作品信息",
    "rules": "写作规则",
    "timeline": "时间线",
    "focus": "当前章正文",
    "selection": "你的选区",
}


#: 每类资料"怎么取回来"——界面上的可执行提示，别让作者自己猜。
#: 没有工具能取回的（例如作者上传的参考资料）**如实说"要重新上传/换进来"**，
#: 不编一个不存在的工具名。
_RETRIEVE_BY_SECTION: Dict[str, str] = {
    "referenceDocs": "重新上传这份资料，或在「资料」里换成更相关的一段",
    "craft": "工艺卡是按任务自动挑的，不必手动取回",
    "otherChapters": "让它用 search_script 搜关键词，或 get_chapter 读某一章",
    "sprites": "立绘是演出资源，对写正文没有信息量（想看完整结构去「导出 → 工程包」）",
    "variables": "变量/状态机在「项目 → 结构分析」里能看到",
    "index": "章节目录在「项目」页能看到；也可以让它 get_chapter 读某一章",
    "loreLinks": "让它用 search_lore 按关键词搜设定",
    "lore": "让它用 search_lore / get_lore_entry 取回具体条目",
    "chatMemory": "更早的对话轮次没有工具可取回，可把关键结论写进要求里",
    "globalMemory": "全局记忆会随章节推进自动重建（MEMORY_AUTO_ARCHIVE）",
    "longMemory": "长程记忆会随章节推进自动重建（MEMORY_AUTO_ARCHIVE）",
}

#: 「一键取回」按钮要发出去的那句话（**第一人称、可直接发送**）。
#:
#: 为什么由后端给：工具名只有一处真源（`agent_tools.TOOL_SPECS` 那一侧），
#: 前端自己拼模板就会在某个时刻编出一个不存在的工具名。**没有工具能取回的块不给这句话**
#: （界面据此不显示按钮）——"取不回来就别给按钮"比给一个点了没用的按钮诚实。
_RETRIEVE_INSTRUCTION_BY_SECTION: Dict[str, str] = {
    "otherChapters": "先用 search_script 搜一遍全书，必要时用 get_chapter 读整章，把和这次要求相关的章节内容补齐，然后再继续。",
    "index": "先用 get_chapter 读一下这次要写的那一章，再继续。",
    "lore": "先用 search_lore 把相关的设定条目取回来，然后再继续。",
    "loreLinks": "先用 search_lore 把相关的设定条目取回来，然后再继续。",
}


def _budget_report(
    *,
    result_chars: int,
    budget_chars: int,
    task_excluded: Sequence[str],
    budget_dropped: Sequence[str],
    budget_compressed: Sequence[str],
    focus_cut: Optional[Dict[str, Any]],
    kept_keys: Sequence[str],
) -> Dict[str, Any]:
    """把"这次上下文怎么拼的、有没有没装下的"整理成**结构化**的一份报告。

    为什么要结构化（而不是只有 `included` 里的中文串）：
    1. 界面上要稳定地列出"没装下的是什么、怎么取回来"，靠正则去解析中文标记太脆
       （前端此前就是这么干的：`/工艺卡|bible|角色|…/` 过滤 `included`）；
    2. 必须区分**两件性质完全不同的事**：
       - 按任务省去（`task_excluded`：立绘、变量这类机制资料对写散文没用）——**这是设计**，
         不是"没装下"，不能拿来吓作者；
       - 因为篇幅没装下（`budget_dropped` / `budget_compressed` / 正文截断）——**这才是要处理的**。
    """
    dropped_rows = []
    for key in budget_dropped:
        row: Dict[str, Any] = {
            "key": key,
            "label": _section_label(key),
            "retrieve": _RETRIEVE_BY_SECTION.get(key, "需要时让它用工具取，或把它换进「资料」"),
        }
        instruction = _RETRIEVE_INSTRUCTION_BY_SECTION.get(key)
        if instruction:
            row["instruction"] = instruction
        dropped_rows.append(row)
    trimmed_rows: List[Dict[str, Any]] = []
    if focus_cut:
        trimmed_rows.append(dict(focus_cut))
    for key in budget_compressed:
        if key == "otherChapters":
            trimmed_rows.append(
                {
                    "kind": "otherChapters",
                    "label": "其他章节的正文摘录",
                    "detail": "已压成标题 + 一句话摘要",
                    "retrieve": _RETRIEVE_BY_SECTION["otherChapters"],
                    "instruction": _RETRIEVE_INSTRUCTION_BY_SECTION["otherChapters"],
                }
            )
        elif key == "中段":
            trimmed_rows.append(
                {
                    "kind": "middle",
                    "label": "上下文中段",
                    "detail": "首尾保留、中段压缩（仍然超预算时的最后手段）",
                    "retrieve": "缩小范围（少带几块资料）后再试，或让它用工具单独取那一段",
                    "instruction": "这次上下文中段被压缩了。请先说明你还需要哪一块信息，我用工具单独取给你。",
                }
            )
    return {
        "usedChars": int(result_chars),
        "budgetChars": int(budget_chars),
        # 只用掉多少 / 上限多少：作者据此判断"是不是预算卡住了写作"
        "usageRatio": round(int(result_chars) / max(1, int(budget_chars)), 3),
        # 因为篇幅没装下（可处理）
        "droppedSections": dropped_rows,
        "trimmedParts": trimmed_rows,
        # 按任务省去（设计如此，不是问题）
        "excludedByTask": [
            {"key": key, "label": _section_label(key)} for key in task_excluded
        ],
        # 这次真的带上的资料块（界面"依据"用，不必再解析中文串）
        "includedSections": [
            {"key": key, "label": _section_label(key)}
            for key in kept_keys
            if key and key != _TAIL_KEY
        ],
        "truncated": bool(dropped_rows or trimmed_rows),
    }


def _light_other_chapters(project: VnProject, focus_chapter: Any) -> str:
    """「其他章节」的降级版：只剩标题 + 一句话摘要（正文摘录全部让位）。

    保留标题与摘要而不是整块丢掉，是因为"这本书有哪些章、各写了什么"是连续性
    的最低需要；丢掉的只是那些可被 `get_chapter` 取回的正文摘录。
    """
    parts: List[str] = []
    for ch in project.chapters:
        if focus_chapter and ch.id == focus_chapter.id:
            continue
        if ch.synopsis:
            parts.append(f"### {ch.title}\n摘要: {_clip(ch.synopsis, 100)}")
        else:
            parts.append(f"### {ch.title}")
    if not parts:
        return ""
    return (
        "\n## 其他章节（仅摘要，因篇幅压缩；需要正文可用 get_chapter / search_script）\n"
        + "\n\n".join(parts)
    )


def _budget_notice(dropped_keys: Sequence[str], compressed_keys: Sequence[str]) -> str:
    """把"这次上下文被怎么处理过"写进提示词本身。

    这是"失忆"的结构性对策之一：模型不知道提示词被裁过时，会把缺失当成"作者没写"，
    于是编造或前后矛盾。写清楚"哪块没带、用什么工具能取"，它就能自己补。
    """
    lines: List[str] = ["## 篇幅说明（本次上下文经过压缩，请据此判断）"]
    if dropped_keys:
        lines.append(
            "- 已整块省去："
            + "、".join(_section_label(k) for k in dropped_keys)
            + "（需要时用 get_chapter / search_script / search_lore 取回）"
        )
    if compressed_keys:
        lines.append(
            "- 已压缩："
            + "、".join(_section_label(k) for k in compressed_keys)
            + "（正文标记里写了省略量）"
        )
    lines.append(
        "- 提示词里**没有**的设定/章节就是「这次没带来」，"
        "不要凭印象补写；缺什么先用工具取，取不到就明确说不确定。"
    )
    return "\n".join(lines)


#: 末尾"编排说明 + 硬规则 + 输出契约"的哨兵 key：不在 `_SECTION_ORDER` 里，永不丢弃。
_TAIL_KEY = "__tail__"

#: 超预算时的**整块让位**顺序（从最可替代的往下）。
#: 只列"中段"的量大块：它们与"这一步怎么写"关系最弱，且大多能用工具取回。
_BUDGET_DROP_ORDER: Tuple[str, ...] = (
    "referenceDocs",  # 作者上传资料：量最大、相关性最低，可重新上传
    "craft",  # 工艺卡是"建议"不是"事实"
    "otherChapters",  # 其他章摘录：可用 get_chapter / search_script 取
    "sprites",  # 演出资源（立绘）：对"怎么写"没有信息量
    "variables",  # 机制类：分支/场景需要，所以排在立绘之后
    "index",  # 章节目录：检索结果里已经有章节标题
    "loreLinks",  # 条目沿边带出的一跳关联
)

#: 仍然超预算时的**第二级让位**：这些是"最好别丢"的块，所以只在整块表丢完之后动，
#: 而且必须如实写进篇幅说明。排序理由：先丢"能用工具取回"的，最后才动记忆层
#: （长程/全局记忆没有工具能补——它们是从数据库滚动归档出来的）。
_BUDGET_DROP_ORDER_LAST: Tuple[str, ...] = (
    "lore",  # 设定条目：检索命中，可用 search_lore / get_lore_entry 取回
    "chatMemory",  # 对话滚动记忆（非正式剧情）
    "globalMemory",  # 全局记忆：整本书骨架，尽量留到最后
    "longMemory",  # 长程记忆：最近发生了什么，最不该丢
)

#: 给"篇幅说明"预留的字符数：说明本身也要算进预算，否则会把它自己挤掉。
_NOTICE_RESERVE = 420

#: 超过这个长度才写「长上下文提醒」（约 1.4 万 token）。
#: 依据：Lost in the Middle（arXiv:2307.03172）显示中段信息在长上下文里利用率明显下降，
#: 而这类"以哪里为准"的指令本身很短，宁可在长上下文里多重复一次。
_LONG_CONTEXT_NOTICE_CHARS = 20000


def _timeline_lines(project: VnProject, focus_chapter: Any) -> Tuple[List[str], str]:
    """作者登记的时间线（`project.timeline`）→ 上下文里的几行 + 一条如实说明。

    为什么需要它：时间线一直被当成"准绳"用在别处（一致性审计拿它读完全部章节、
    事实扫描用它判定时间线错序），**但从没进过写作时的上下文**——于是模型一边被要求
    别写乱时间，一边看不到那份时间线。这是 LongMemEval 那套记忆维度里"时间推理"
    暴露出来的缺口（见 docs/references.md）。

    取舍（都写在这里，免得以后被"顺手放开"）：
    - 只带**焦点章之前（含本章）已经发生**的事件：未来的事件不该影响这一章怎么写；
      解析不出章号的事件（作者没填 chapterRef）当背景带上，标注「章号未填」。
    - **跳过 stale 事件**（证据已失效）并说明跳了几条：喂"可能已经不对"的事实比不喂更糟
      （与账本里那条"假钩子会被当成事实喂给写作模型"是同一类风险的两种形态）。
    - 按 `order` 升序（书内先后），条数与每条长度都设上限，超出如实说明。
    """
    events = [e for e in (getattr(project, "timeline", None) or []) if e is not None]
    if not events:
        return [], ""

    order_of: dict = {}
    for idx, ch in enumerate(list(getattr(project, "chapters", None) or []), start=1):
        cid = str(getattr(ch, "id", "") or "")
        title = str(getattr(ch, "title", "") or "")
        if cid:
            order_of[cid] = idx
        if title:
            order_of.setdefault(title, idx)
    focus_ordinal = order_of.get(str(getattr(focus_chapter, "id", "") or ""), None)

    kept: List[Tuple[float, str]] = []
    skipped_stale = 0
    skipped_future = 0
    for event in events:
        if bool(getattr(event, "stale", None)):
            skipped_stale += 1
            continue
        ref = str(getattr(event, "chapterRef", None) or "").strip()
        ref_ordinal = order_of.get(ref)
        label = str(getattr(event, "when", None) or "").strip() or (
            f"第 {ref_ordinal} 章" if ref_ordinal else "章号未填"
        )
        if focus_ordinal is not None and ref_ordinal is not None and ref_ordinal > focus_ordinal:
            skipped_future += 1
            continue
        title = str(getattr(event, "title", "") or "").strip() or "（无标题事件）"
        summary = _clip(str(getattr(event, "summary", None) or "").strip(), 120)
        kept.append(
            (
                float(getattr(event, "order", 0.0) or 0.0),
                f"- [{label}] {title}" + (f"：{summary}" if summary else ""),
            )
        )

    kept.sort(key=lambda pair: pair[0])
    cap = 20
    shown = kept[-cap:] if len(kept) > cap else kept
    notes: List[str] = []
    if len(kept) > cap:
        notes.append(f"共 {len(kept)} 条，这里列出最近 {cap} 条")
    if skipped_future:
        notes.append(f"省略了 {skipped_future} 条焦点章之后的事件")
    if skipped_stale:
        notes.append(f"跳过 {skipped_stale} 条可能已失效（stale）的事件")
    return [text for _order, text in shown], "；".join(notes)


def build_agent_context(
    project: VnProject,
    chapterId: Optional[str] = None,
    selection: Optional[str] = None,
    userMessage: Optional[str] = None,
    task: Optional[str] = None,
    maxChars: Optional[int] = None,
    chatMemory: Optional[str] = None,
    longChapterMemory: Optional[str] = None,
    globalMemory: Optional[str] = None,
    loreCraft: Optional[str] = None,
    referenceDocs: Optional[str] = None,
    exclude: Optional[Iterable[str]] = None,
) -> AgentContextResult:
    """Build a retrieval-biased project context for long-form Agent use.

    Prefer: meta + bible digest + chapter index + focus chapter + scored slices.
    """
    max_chars = maxChars if maxChars is not None else _default_context_max_chars()
    resolved_task = task or (infer_agent_task(userMessage) if userMessage else "chat")
    included: List[str] = [f"模式:{resolved_task}"]

    focus_chapter = next((c for c in project.chapters if c.id == chapterId), None) or (
        project.chapters[0] if project.chapters else None
    )

    # Perf: blocks→plain conversion is O(blocks) and hot in character scoring /
    # chapter excerpts below — memoize per chapter so each chapter converts once.
    plain_cache: Dict[str, str] = {}

    def plain_of(ch: Optional[SceneChapter]) -> str:
        """一章的纯文本（正文优先）——口径见模块级 `chapter_plain`，这里只做缓存。"""
        if ch is None:
            return ""
        cached = plain_cache.get(ch.id)
        if cached is None:
            cached = chapter_plain(ch, project.characters)
            plain_cache[ch.id] = cached
        return cached

    ask_tokens = _tokenize("\n".join([userMessage or "", selection or ""]))
    ask_lower = _ask_text(userMessage, selection)
    # Only score against the user ask / selection — never seed with every name
    # (that would make every character card match itself).
    effective_tokens = ask_tokens

    bible = project.bible
    meta_lines = [
        p
        for p in [
            f"# {project.title}",
            f"Logline: {project.logline}" if project.logline else "",
            f"Genre: {project.genre}" if project.genre else "",
        ]
        if p
    ]

    bible_budget = 2800 if resolved_task in ("outline", "consistency") else 2000
    bible_parts: List[str] = []
    if (bible and bible.world) or project.lore:
        bible_parts.append(f"世界观:\n{_clip((bible.world if bible else None) or project.lore or '', 900)}")
    if bible and bible.background:
        bible_parts.append(f"故事背景:\n{_clip(bible.background, 500)}")
    if bible and bible.outline:
        related_beats = select_outline_beats(bible.outline, effective_tokens, 5)
        if related_beats and resolved_task != "outline":
            bible_parts.append("大纲相关节拍（检索）:\n" + "\n".join(f"- {b}" for b in related_beats))
            included.append(f"大纲节拍×{len(related_beats)}")
        bible_parts.append(f"大纲:\n{_clip(bible.outline, 1200 if resolved_task == 'outline' else 500)}")
    if bible and bible.themes:
        bible_parts.append(f"主题/基调:\n{_clip(bible.themes, 300)}")
    if bible and bible.notes:
        bible_parts.append(f"备忘:\n{_clip(bible.notes, 300)}")
    bible_block = "\n\n".join(bible_parts)
    if len(bible_block) > bible_budget:
        bible_block = _clip(bible_block, bible_budget)
    if bible_block:
        included.append("设定bible")

    digests = digest_all_chapters(project)
    # 分卷的作品：模型看到的章节目录也带卷（长篇续写时它要知道自己在写哪一卷）
    volume_titles: Dict[str, str] = {}
    if project.volumes:
        title_by_id = {str(v.id): (v.title or "") for v in project.volumes}
        for ch in project.chapters or []:
            title = title_by_id.get(str(getattr(ch, "volumeId", "") or ""))
            if title:
                volume_titles[ch.id] = title
    digest_fmt = format_chapter_digest_index(
        digests,
        focus_id=focus_chapter.id if focus_chapter else None,
        tokens=effective_tokens,
        max_related_excerpts=5 if resolved_task == "consistency" else 3,
        volume_titles=volume_titles,
    )
    included.extend([x for x in digest_fmt.included if not x.startswith("章摘要")])

    if digest_fmt.indexLines:
        index_lines = digest_fmt.indexLines
    else:
        index_lines = []
        for i, ch in enumerate(project.chapters):
            mark = "◀当前" if focus_chapter and ch.id == focus_chapter.id else ""
            syn = f" — {_clip(ch.synopsis, 80)}" if ch.synopsis else ""
            index_lines.append(f"{i + 1}. {ch.title}{mark}{syn}")
    included.append(f"章节目录×{len(project.chapters)}")

    # Score characters
    ranked_chars: List[Tuple[Character, int]] = []
    for c in project.characters:
        names = _names_of(c, "displayName", "defineName")
        # 别名也要进 haystack：正文里提到"阿雪"这种别称时同样该命中
        hay = (
            f"{' '.join(names)} {_js(c.voice)} {_js(c.bio)} "
            f"{_js(c.relationships)} {_js(getattr(c, 'voiceMind', None))}"
        )
        score = _score_haystack(hay, effective_tokens) + _name_hit_bonus(names, ask_lower)
        if focus_chapter:
            plain = plain_of(focus_chapter)
            if any(n in plain for n in names):
                score += 8
        if resolved_task in ("voice", "consistency"):
            score += 2
        ranked_chars.append((c, score))
    ranked_chars.sort(key=lambda pair: pair[1], reverse=True)

    char_pick_count = (
        min(12, len(ranked_chars))
        if resolved_task in ("voice", "consistency")
        else min(6, len(ranked_chars))
    )
    picked_chars = [r for i, r in enumerate(ranked_chars) if r[1] > 0 or i < 3][:char_pick_count]
    if not picked_chars and ranked_chars:
        picked_chars = ranked_chars[: min(3, len(ranked_chars))]

    locs = project.locations or []
    ranked_locs: List[Tuple[Location, int]] = []
    for l in locs:
        names = _names_of(l, "name", "imageTag")
        hay = f"{' '.join(names)} {l.description or ''} {' '.join(l.tags or [])}"
        score = _score_haystack(hay, effective_tokens) + _name_hit_bonus(names, ask_lower)
        if resolved_task in ("scene", "consistency"):
            score += 1
        ranked_locs.append((l, score))
    ranked_locs.sort(key=lambda pair: pair[1], reverse=True)
    loc_pick_max = 8 if resolved_task == "scene" else 5
    picked_locs = [r for i, r in enumerate(ranked_locs) if r[1] > 0 or i < 4][:loc_pick_max]
    if not picked_locs and ranked_locs:
        picked_locs = ranked_locs[: min(4, len(ranked_locs))]

    link_lines: List[str] = []
    links = project.locationLinks or []
    related_loc_lines: List[str] = []
    if links and picked_locs:
        by_id = {l.id: l.name for l in locs}
        id_set = {r[0].id for r in picked_locs}
        loc_by_id = {l.id: l for l in locs}
        for link in links:
            if link.fromId in id_set or link.toId in id_set:
                link_lines.append(
                    f"- {by_id.get(link.fromId, link.fromId)} --{link.relation}--> "
                    f"{by_id.get(link.toId, link.toId)}" + (f" ({link.note})" if link.note else "")
                )
        # 链接扩展：命中地点的直接邻居也带进来（只列一行要点，不占整张卡）
        for link in links:
            for near, far in ((link.fromId, link.toId), (link.toId, link.fromId)):
                if near not in id_set or far in id_set:
                    continue
                other = loc_by_id.get(far)
                if other is None:
                    continue
                brief = _clip((other.description or "").strip(), 60)
                related_loc_lines.append(
                    f"- {other.name}" + (f"：{brief}" if brief else "")
                )
        # 去重、限量
        seen_rel: set = set()
        related_loc_lines = [
            ln for ln in related_loc_lines if not (ln in seen_rel or seen_rel.add(ln))
        ][:6]

    import json as _json

    var_lines = [
        f"- {v.name} ({v.key}: {v.type}) = {_json.dumps(v.value, ensure_ascii=False)}"
        + (f" [char:{v.bindCharacterId}]" if v.bindCharacterId else "")
        + (f" // {v.note}" if v.note else "")
        for v in (project.variables or [])
    ]
    sprite_lines = [
        f"- {s.name} image={s.imageTag}"
        + (f" char={s.characterId}" if s.characterId else "")
        + f" exprs=[{', '.join(e.tag for e in s.expressions)}]"
        for s in (project.sprites or [])
    ]

    timeline_lines, timeline_note = _timeline_lines(project, focus_chapter)

    # ── 设定条目：按触发词/标题/正文检索，只有命中的进上下文 ──────────────
    # 这是"设定很大也用得动"的关键：条目可以无上限地堆，而每次调用只带相关的几条。
    # 钉住的条目（pinned）永远带上——作者认为"绝不能写错"的那几条。
    entries = [e for e in (getattr(project, "loreEntries", None) or []) if e is not None]
    entry_blocks: List[str] = []
    entry_titles_all: List[str] = []
    pinned_entries: List[Any] = []
    scored_entries: List[Tuple[Any, int]] = []
    for e in entries:
        title = str(getattr(e, "title", "") or "").strip()
        if title:
            entry_titles_all.append(title)
        if bool(getattr(e, "pinned", None)):
            pinned_entries.append(e)
            continue
        scored_entries.append((e, _entry_score(e, ask_lower, effective_tokens)))
    scored_entries.sort(
        key=lambda pair: (pair[1], int(getattr(pair[0], "priority", 0) or 0)), reverse=True
    )

    entry_budget = 3200 if resolved_task in ("outline", "consistency", "scene") else 2400
    used_entry = 0
    picked_entry_titles: List[str] = []

    def _entry_block(e: Any, tag: str) -> str:
        title = str(getattr(e, "title", "") or "（无标题）").strip() or "（无标题）"
        body = _entry_text(e).strip()
        keys = _entry_keywords(e)
        head = f"### {title}" + (f"　[{'/'.join(keys)}]" if keys else "")
        return f"{head}\n{_clip(body, 700)}" if body else head + f"（{tag}）"

    for e in pinned_entries[:6]:
        block = _entry_block(e, "钉住")
        if used_entry + len(block) > entry_budget and entry_blocks:
            break
        entry_blocks.append(block)
        used_entry += len(block)
        picked_entry_titles.append(str(getattr(e, "title", "") or ""))

    for e, score in scored_entries:
        if score < _ENTRY_MIN_SCORE:
            break
        block = _entry_block(e, f"score={score}")
        if used_entry + len(block) > entry_budget:
            break
        entry_blocks.append(block)
        used_entry += len(block)
        picked_entry_titles.append(str(getattr(e, "title", "") or ""))

    # ── 设定条目的实体链接：命中条目 → 带出它点名的角色/地点/章节 ──────────
    # 条目原来只靠触发词命中，等于孤岛；有了 links，就能沿着边多走一步：
    # ① 条目点名了谁 → 把那个角色/地点带进来；② 本轮命中了谁 → 把点名它的条目补进来。
    lore_link_lines: List[str] = []
    linked_extra_entries = 0
    if entries:
        picked_entry_ids = {
            str(getattr(e, "id", "")) for e, _ in scored_entries[: len(entry_blocks)]
        }
        picked_entry_ids.update(
            str(getattr(e, "id", "")) for e in pinned_entries[: len(entry_blocks)]
        )
        picked_char_ids = {r[0].id for r in picked_chars}
        picked_loc_ids = {r[0].id for r in picked_locs}
        char_by_id_all = {c.id: c for c in project.characters}
        loc_by_id_all = {l.id: l for l in (project.locations or [])}
        chapter_by_id_all = {str(c.id): c for c in (project.chapters or [])}

        seen_link_lines: set = set()
        for e, _score in scored_entries:
            title = str(getattr(e, "title", "") or "")
            for link in getattr(e, "links", None) or []:
                kind = str(getattr(link, "toType", "") or "")
                target_id = str(getattr(link, "toId", "") or "")
                if not kind or not target_id:
                    continue
                line = ""
                if kind == "character" and target_id not in picked_char_ids:
                    c = char_by_id_all.get(target_id)
                    if c is not None:
                        brief = _clip((c.voice or c.bio or "").strip(), 80)
                        line = f"- {c.displayName}（{title} 点名关联）" + (f"：{brief}" if brief else "")
                elif kind == "location" and target_id not in picked_loc_ids:
                    loc = loc_by_id_all.get(target_id)
                    if loc is not None:
                        brief = _clip((loc.description or "").strip(), 80)
                        line = f"- {loc.name}（{title} 点名关联）" + (f"：{brief}" if brief else "")
                elif kind == "chapter":
                    ch = chapter_by_id_all.get(target_id)
                    if ch is not None and title not in picked_entry_titles:
                        line = f"- {ch.title or target_id}（{title} 关联章节）"
                if line and line not in seen_link_lines:
                    seen_link_lines.add(line)
                    lore_link_lines.append(line)
                if len(lore_link_lines) >= 8:
                    break
            if len(lore_link_lines) >= 8:
                break

        # 反向：本轮命中的角色/地点，把它们点名的条目补进上下文（预算允许时）
        asked = picked_char_ids | picked_loc_ids
        if asked and used_entry < entry_budget:
            for e in entries:
                eid = str(getattr(e, "id", ""))
                if eid in picked_entry_ids:
                    continue
                hit = any(
                    str(getattr(lk, "toId", "")) in asked
                    for lk in (getattr(e, "links", None) or [])
                )
                if not hit:
                    continue
                block = _entry_block(e, "关联命中")
                if used_entry + len(block) > entry_budget:
                    break
                entry_blocks.append(block)
                used_entry += len(block)
                linked_extra_entries += 1

    # 没进上下文的条目只列标题：让模型（和用户）知道"还有哪些设定可点名"
    rest_titles = [t for t in entry_titles_all if t and t not in picked_entry_titles]
    entry_index_note = ""
    if rest_titles:
        entry_index_note = (
            f"\n（另有 {len(rest_titles)} 条设定未进上下文，需要时可让用户点名："
            f"{_clip('、'.join(rest_titles), 300)}）"
        )

    # ── 角色关系：命中角色的直接关系带出来，避免写错立场 ────────────────
    relation_lines: List[str] = []
    char_links = getattr(project, "characterLinks", None) or []
    if char_links and picked_chars:
        picked_ids = {r[0].id for r in picked_chars}
        char_by_id = {c.id: c for c in project.characters}
        for link in char_links:
            if link.fromId in picked_ids or link.toId in picked_ids:
                a = char_by_id.get(link.fromId)
                b = char_by_id.get(link.toId)
                an = a.displayName if a else str(link.fromId)
                bn = b.displayName if b else str(link.toId)
                line = f"- {an} --{link.label}--> {bn}"
                # 对面没进上下文时，附一行要点（立场判断往往就靠这句）
                far = b if link.fromId in picked_ids else a
                if far is not None and far.id not in picked_ids:
                    brief = _clip((far.bio or far.voice or "").strip(), 60)
                    if brief:
                        line += f"（{far.displayName}：{brief}）"
                relation_lines.append(line)
        seen_rel2: set = set()
        relation_lines = [
            ln for ln in relation_lines if not (ln in seen_rel2 or seen_rel2.add(ln))
        ][:8]

    # ── 关系图的第二跳（只给需要跨章对照的任务）─────────────────────────
    # 1 跳回答"他直接认识谁"；跨章一致性常常要问"通过谁连着"（A 的学生 C 与 B 的师父 D），
    # 所以对 consistency / scene 多走一步。带上"（间接）"标记，避免模型把它当直接关系。
    if char_links and picked_chars and resolved_task in ("consistency", "scene"):
        hop1_ids = {r[0].id for r in picked_chars}
        far_ids: set = set()
        for link in char_links:
            if link.fromId in hop1_ids and link.toId not in hop1_ids:
                far_ids.add(link.toId)
            elif link.toId in hop1_ids and link.fromId not in hop1_ids:
                far_ids.add(link.fromId)
        char_by_id = {c.id: c for c in project.characters}
        seen2 = set(relation_lines)
        for link in char_links:
            near_far = None
            if link.fromId in far_ids and link.toId not in hop1_ids:
                near_far = (link.fromId, link.toId)
            elif link.toId in far_ids and link.fromId not in hop1_ids:
                near_far = (link.toId, link.fromId)
            if near_far is None:
                continue
            a = char_by_id.get(near_far[0])
            b = char_by_id.get(near_far[1])
            if a is None or b is None:
                continue
            line = f"- （间接）{a.displayName} --{link.label}--> {b.displayName}"
            if line in seen2:
                continue
            seen2.add(line)
            relation_lines.append(line)
            if len(relation_lines) >= 12:
                break

    # Other chapters: prefer extractive digests; raw excerpt only if high score + short
    other_chapter_blocks: List[str] = list(digest_fmt.relatedBlocks)
    for ch in project.chapters:
        if focus_chapter and ch.id == focus_chapter.id:
            continue
        plain = plain_of(ch)
        hay = f"{ch.title}\n{ch.synopsis or ''}\n{plain}"
        score = _score_haystack(hay, effective_tokens)
        already = score >= 4 and any(f"### {ch.title}" in b for b in other_chapter_blocks)
        if score >= 8 and plain and len(plain) < 2500 and not already:
            budget = min(900, 300 + score * 40)
            other_chapter_blocks.append(
                f"### {ch.title}（正文摘录 score={score}）\n"
                f"{_chapter_head_tail(plain, budget, hint='，可用 get_chapter 取该章')}"
            )
            included.append(f"摘录章:{ch.title}")

    # Focus chapter — prefer tail for continue/polish/branch/scene
    focus_body = ""
    focus_truncated = False
    focus_cut: Optional[Dict[str, Any]] = None
    focus_digest = next((d for d in digests if focus_chapter and d.chapterId == focus_chapter.id), None)
    if focus_chapter:
        plain = plain_of(focus_chapter)
        # 预算随总预算走（旧值 1800/5000/4200 是"省 token"年代的产物）。
        focus_budget = _focus_budget(max_chars, resolved_task)
        use_tail = resolved_task in ("continue", "polish", "branch", "scene")
        focus_body = "\n".join(
            p
            for p in [
                f"## 当前章节：{focus_chapter.title}",
                f"Synopsis: {focus_chapter.synopsis}" if focus_chapter.synopsis else "",
                (
                    _chapter_tail(plain, focus_budget, hint=_RETRIEVE_HINT)
                    if use_tail
                    else _chapter_head_tail(plain, focus_budget, hint=_RETRIEVE_HINT)
                ),
            ]
            if p
        )
        included.append(f"当前章:{focus_chapter.title}")
        if len(plain) > focus_budget:
            # 透明化：作者要能一眼看出"当前章被截了"，而不是以为模型读了全文
            included.append(f"当前章截断:{focus_budget}/{len(plain)}字")
            focus_truncated = True
            focus_cut = {
                "kind": "focus",
                "label": f"当前章正文（{focus_chapter.title or '未命名'}）",
                "detail": f"只带了末尾 {focus_budget} / {len(plain)} 字",
                "keptChars": focus_budget,
                "totalChars": len(plain),
                "retrieve": f"让它用 get_chapter 读「{focus_chapter.title or '当前章'}」的完整正文",
                # 一键取回按钮要发的原话（第一人称、可直接发送；工具名只有后端一处真源）
                "instruction": (
                    f"先用 get_chapter 读「{focus_chapter.title or '当前章'}」的完整正文"
                    "（这次只带了末尾部分），读完用一句话确认你读到的位置，然后再继续。"
                ),
            }

    if picked_chars:
        included.append(f"角色×{len(picked_chars)}")
    if picked_locs:
        included.append(f"地点×{len(picked_locs)}")
    if entry_blocks:
        included.append(f"设定条目×{len(entry_blocks)}")
    if relation_lines:
        included.append(f"角色关系×{len(relation_lines)}")
    if lore_link_lines:
        included.append(f"条目关联×{len(lore_link_lines)}")
    if linked_extra_entries:
        included.append(f"关联条目×{linked_extra_entries}")
    if related_loc_lines:
        included.append(f"相邻地点×{len(related_loc_lines)}")
    if var_lines:
        included.append(f"变量×{len(var_lines)}")
    if selection:
        included.append(f"选区{len(selection)}字")
    if chatMemory and chatMemory.strip():
        included.append("对话记忆")
    if longChapterMemory and longChapterMemory.strip():
        included.append("长程章节记忆")
    if globalMemory and globalMemory.strip():
        included.append("全局记忆")
    if loreCraft and loreCraft.strip():
        included.append("ACG工艺卡")
    if referenceDocs and referenceDocs.strip():
        included.append("上传资料")

    show_vars = bool(
        var_lines
        and (
            resolved_task in ("consistency", "branch", "scene", "continue")
            or effective_tokens
        )
    )
    show_vars_chat_clipped = bool(var_lines and resolved_task == "chat" and not show_vars)

    # Author style memory: LLM-learned writing-style guide (continuity of voice)
    style_block = ""
    style_samples: List[str] = []
    sm = getattr(project, "styleMemory", None)
    if isinstance(sm, dict):
        guide = str(sm.get("guide") or "").strip()
        samples = [
            str(s).strip() for s in (sm.get("samples") or []) if str(s or "").strip()
        ][:3]
        style_samples = samples
        if guide:
            style_block = (
                "\n## 作者文风记忆（延续作者自己的习惯：续写/改写/润色请贴合此风格；"
                "它是归纳不是圣旨，具体情节仍听用户）\n" + _clip(guide, 1200)
            )
            included.append("文风记忆")
        if samples:
            # 样例比规则更管用：模型模仿"看得见的句子"远比遵守"形容词式的规则"稳。
            style_block += (
                "\n\n【作者原文样例（最重要：模仿它们的句法、节奏与用词密度，不要照抄内容）】\n"
                + "\n".join(f"- {_clip(s, 200)}" for s in samples)
            )
            included.append(f"文风样例×{len(samples)}")

    # 每块都带一个 key：既方便按任务裁剪/作者摘掉，也让"这次带了什么"可解释。
    # 注意 `rules` 刻意**不在** EXCLUDABLE_SECTIONS 里：本次硬规则不是"可摘的参考资料"，
    # 而是这一轮的任务契约，必须首尾各出现一次（末尾那次见下方 tail）。
    #
    # **下面的书写顺序不代表输出顺序**：真正的顺序由 `_SECTION_ORDER` 决定（见那里的理由）。
    head_rules = task_key_rules(resolved_task)
    keyed_sections: List[Tuple[str, str]] = [
        ("meta", "\n".join(meta_lines)),
        (
            "rules",
            (
                "\n## 本次硬规则（先读一遍；末尾会再出现一次）\n"
                + "\n".join(f"- {r}" for r in head_rules)
            )
            if head_rules
            else "",
        ),
        ("bible", f"\n## Story Bible（内部参考，禁止整段搬进正文）\n{bible_block}" if bible_block else ""),
        (
            # 时间线放进**头部**：它是"什么已经发生了"的地基（LongMemEval 的"时间推理"
            # 维度），而且按 Lost in the Middle 的结论，头部是最不易被忽略的位置。
            "timeline",
            (
                "\n## 时间线（作者登记的事件，按书内先后；内部参考）\n"
                + "\n".join(timeline_lines)
                + (f"\n（{timeline_note}）" if timeline_note else "")
                if timeline_lines
                else ""
            ),
        ),
        (
            "lore",
            (
                "\n## 设定条目（按触发词/正文检索命中；内部参考，禁止整段搬进正文）\n"
                + "\n\n".join(entry_blocks)
                + entry_index_note
                if entry_blocks
                else ""
            ),
        ),
        (
            # 条目沿边带出来的实体（1 跳）。和 `rules` 一样不进可摘清单：
            # 它是"这条设定点名关联的人/地"，属于命中条目的必要补充，不是可摘的资料块。
            "loreLinks",
            (
                "\n## 设定条目关联到的角色/地点/章节（沿条目的 links 走一步）\n"
                + "\n".join(lore_link_lines)
                if lore_link_lines
                else ""
            ),
        ),
        (
            "longMemory",
            (
                f"\n{_clip(longChapterMemory.strip(), _CLIP_LONG_MEMORY)}"
                if longChapterMemory and longChapterMemory.strip()
                else ""
            ),
        ),
        (
            # 全局记忆排在长程记忆之后：先给"最近这段发生了什么"（更直接影响续写），
            # 再给"整本书到目前为止"（影响主线判断）。两块都会在超预算时被压。
            "globalMemory",
            (
                f"\n{_clip(globalMemory.strip(), _CLIP_GLOBAL_MEMORY)}"
                if globalMemory and globalMemory.strip()
                else ""
            ),
        ),
        (
            "craft",
            (
                f"\n{_clip(loreCraft.strip(), _CLIP_CRAFT)}"
                if loreCraft and loreCraft.strip()
                else ""
            ),
        ),
        (
            "referenceDocs",
            (
                f"\n{_clip(referenceDocs.strip(), _CLIP_REFERENCE_DOCS)}"
                if referenceDocs and referenceDocs.strip()
                else ""
            ),
        ),
        (
            "chatMemory",
            (
                f"\n## 对话滚动记忆（更早轮次压缩，非正式剧情）\n{_clip(chatMemory.strip(), _CLIP_CHAT_MEMORY)}"
                if chatMemory and chatMemory.strip()
                else ""
            ),
        ),
        ("index", "\n## 章节目录（含本地摘要）\n" + "\n".join(index_lines)),
        (
            "characters",
            (
                "\n## Characters（内部参考：只校准语气与行为，禁止写入对白当说明书）\n"
                + "\n".join(_char_card(r[0]) for r in picked_chars)
                if picked_chars
                else ""
            ),
        ),
        (
            "relations",
            (
                "\n## 角色关系（命中角色的直接关系；用来避免写错立场）\n"
                + "\n".join(relation_lines)
                if relation_lines
                else ""
            ),
        ),
        (
            "locations",
            (
                "\n## Locations（内部参考：氛围与走位，勿念地名百科）\n"
                + "\n".join(_loc_card(r[0]) for r in picked_locs)
                + ("\n通路:\n" + "\n".join(link_lines) if link_lines else "")
                + ("\n相邻地点:\n" + "\n".join(related_loc_lines) if related_loc_lines else "")
                if picked_locs
                else ""
            ),
        ),
        (
            "variables",
            (
                "\n## Variables / 状态机\n" + "\n".join(var_lines)
                if show_vars
                else (f"\n## Variables / 状态机\n{_clip(chr(10).join(var_lines), 600)}" if show_vars_chat_clipped else "")
            ),
        ),
        ("sprites", f"\n## Sprites\n{_clip(chr(10).join(sprite_lines), 400)}" if sprite_lines else ""),
        ("otherChapters", "\n## 其他章节（摘要优先）\n" + "\n\n".join(other_chapter_blocks) if other_chapter_blocks else ""),
        (
            "focus",
            (
                f"\n{focus_body}" + (f"\n（章摘要备忘: {focus_digest.beatSummary}）" if focus_digest and focus_digest.beatSummary else "")
                if focus_body
                else ""
            ),
        ),
        ("selection", f"\n## 用户选区（审稿/改写焦点）\n{_clip(selection, _CLIP_SELECTION)}" if selection else ""),
        ("style", style_block),
    ]

    dropped = sections_to_drop(resolved_task, exclude)
    # 顺序由 _SECTION_ORDER 决定（下面这行排序），这里的书写顺序不影响输出。
    order_index = {key: i for i, key in enumerate(_SECTION_ORDER)}
    keyed_sections.sort(key=lambda kv: order_index.get(kv[0], len(_SECTION_ORDER)))
    # 保留 key（不只是文本）：超预算时要按 key 决定"丢哪一块"，而不是从中间砍一刀。
    kept_keyed: List[Tuple[str, str]] = [
        (key, text) for key, text in keyed_sections if text and key not in dropped
    ]
    if dropped:
        # 透明化：告诉作者这次省掉了什么（前端会把没省的显示成"依据"）
        included.append("省去:" + "、".join(sorted(dropped)))
    # 长上下文里模型会"读到但没用上"（Lost in the Middle）：明确告诉它**以哪两处为准**，
    # 以及"缺的东西可以取回来"。只在真的长时才写，短上下文里这句话本身就是噪音。
    long_note = ""
    if sum(len(t) for _, t in kept_keyed) >= _LONG_CONTEXT_NOTICE_CHARS:
        long_note = (
            "\n\n## 长上下文提醒\n"
            "本次上下文较长：请以**开头的角色/设定与末尾的硬规则、「当前章节」正文**为准；"
            "中间的资料是按检索拼上的，可能与本步无关，不要为了用上它们而离题。"
            "提示词里没有的章节或设定就是这次没带来——用 get_chapter / search_script / "
            "search_lore 取，不要凭印象补写。"
        )
        included.append("长上下文提醒")
    tail = (
        f"\n## 编排说明\n上下文按任务「{resolved_task}」检索拼装：章摘要本地抽取、"
        "大纲节拍检索、对话记忆压缩。人设与 bible 是作者备忘不是讲稿。"
        "续写请紧接「当前章节」正文末尾。"
        + long_note
    )
    # 硬规则在**末尾再出现一次**：长上下文里夹在中间的要求最容易被忽略。
    key_rules = task_key_rules(resolved_task)
    if key_rules:
        tail += "\n\n## 本次硬规则（务必遵守）\n" + "\n".join(f"- {r}" for r in key_rules)
        included.append("本次硬规则")
    tail += "\n\n## 输出契约\n" + output_contract(resolved_task)
    included.append("输出契约")

    # 作者自己写的硬规则（"必须/不要/禁止…"）单独拎出来，放进末尾的硬规则区：
    # 它们最容易淹没在世界观叙述里，而末尾的位置才是"当场生效"的。
    from .constraints import author_hard_rules

    bible = project.bible
    author_rules = author_hard_rules(
        bible_text="\n".join(
            [
                str(getattr(bible, "world", "") or ""),
                str(getattr(bible, "notes", "") or ""),
                str(getattr(bible, "themes", "") or ""),
                str(getattr(bible, "outline", "") or ""),
            ]
        ),
        entry_texts=[
            f"{e.title}：{e.body}" for e in (project.loreEntries or [])
        ],
        limit=5,
    )
    if author_rules:
        tail += "\n\n## 作者自己的硬规则（最高优先，务必遵守）\n" + "\n".join(
            f"- {r}" for r in author_rules
        )
        included.append(f"作者硬约束×{len(author_rules)}")
    kept_keyed.append((_TAIL_KEY, tail))

    # 「证明它记得」：把这次真正用到的资料连同摘录列出来（前端可展开看），
    # 这是"聊天给不了"的东西——作者能核对它到底读了什么，而不是只能猜。
    details: List[Dict[str, str]] = []
    if "lore" not in dropped and entry_blocks:
        for block in entry_blocks[:5]:
            details.append({"label": "设定条目", "preview": _clip(block, 120)})
    if "characters" not in dropped and picked_chars:
        details.append(
            {"label": f"角色×{len(picked_chars)}", "preview": "、".join(r[0].displayName for r in picked_chars[:8])}
        )
    if "locations" not in dropped and picked_locs:
        details.append(
            {"label": f"地点×{len(picked_locs)}", "preview": "、".join(r[0].name for r in picked_locs[:8])}
        )
    if "bible" not in dropped and bible_block:
        details.append({"label": "设定 bible", "preview": _clip(bible_block, 120)})
    if "style" not in dropped and style_samples:
        details.append({"label": "文风样例", "preview": _clip(style_samples[0], 120)})
    if "index" not in dropped and index_lines:
        details.append(
            {"label": f"章节目录×{len(index_lines)}", "preview": "；".join(index_lines[:3])}
        )
    if focus_chapter is not None and "focus" not in dropped:
        details.append(
            {
                "label": "当前章",
                "preview": f"{focus_chapter.title}（{len(focus_body or '')} 字）",
            }
        )

    # --- 超预算：**整块让位 + 如实说明**，而不是"从中间砍一刀" -----------------
    #
    # 旧实现是 `text[:keep_head] + text[-keep_tail:]`：一句话把上下文从中段切成两半。
    # 后果有两层：块边界被切碎（人设/设定只剩半句），而且**没人知道少了什么**——
    # 模型把缺失当成"作者没写"，于是编造；作者以为模型读了全书。
    #
    # 现在分三级，每一级都留痕（写进提示词末尾的「篇幅说明」+ API 的 included）：
    #   1. 中段量大的块整块让位（_BUDGET_DROP_ORDER）；
    #   2. 仍然超预算才动"可用工具取回"的块与记忆层（_BUDGET_DROP_ORDER_LAST）；
    #   3. 最后手段才是首尾保留的字符级压缩——真发生时标记里写明省了多少字。
    budget_dropped: List[str] = []
    budget_compressed: List[str] = []
    # 给「篇幅说明」留位：说明本身也算上下文长度，否则它会把自己挤掉。
    budget = max(1000, max_chars - _NOTICE_RESERVE)

    def _join_sections() -> str:
        return "\n".join(t for k, t in kept_keyed if k not in budget_dropped and t)

    if len(_join_sections()) > budget:
        stored_keys = {k for k, _ in kept_keyed}
        if other_chapter_blocks and "otherChapters" in stored_keys:
            light = _light_other_chapters(project, focus_chapter)
            if light:
                kept_keyed = [
                    (k, light if k == "otherChapters" else t) for k, t in kept_keyed
                ]
                budget_compressed.append("otherChapters")
                included.append("已压缩其他章摘录")
        for key in _BUDGET_DROP_ORDER + _BUDGET_DROP_ORDER_LAST:
            if len(_join_sections()) <= budget:
                break
            if key in {k for k, _ in kept_keyed} and key not in budget_dropped:
                budget_dropped.append(key)
                included.append(f"篇幅省去:{key}")
        text = _join_sections()
        if len(text) > budget:
            keep_tail = min(
                int(budget * 0.55), len(focus_body) + len(selection or "") + 400
            )
            keep_head = max(0, budget - keep_tail - 40)
            removed = max(0, len(text) - keep_head - keep_tail)
            text = (
                f"{text[:keep_head]}\n\n"
                f"…(上下文中段压缩：省去约 {removed} 字，用工具取回需要的那一块)…\n\n"
                f"{text[len(text) - keep_tail:]}"
            )
            budget_compressed.append("中段")
            included.append("中段压缩")
    else:
        text = _join_sections()

    notice = ""
    if budget_dropped or budget_compressed:
        notice = "\n\n" + _budget_notice(budget_dropped, budget_compressed)
        if len(text) + len(notice) > max_chars:
            # 装不下说明本身时，宁可不要说明（作者仍能在界面上看到 included），
            # 也不要让上下文超出预算。
            notice = ""
        else:
            text = f"{text}{notice}"

    return AgentContextResult(
        text=text,
        included=included,
        charsUsed=len(text),
        task=resolved_task,
        excluded=sorted(dropped),
        includedDetails=details,
        truncated=bool(focus_truncated or budget_dropped or budget_compressed),
        budgetReport=_budget_report(
            result_chars=len(text),
            budget_chars=max_chars,
            task_excluded=sorted(dropped),
            budget_dropped=budget_dropped,
            budget_compressed=budget_compressed,
            focus_cut=focus_cut,
            kept_keys=[k for k, t in kept_keyed if t],
        ),
    )
