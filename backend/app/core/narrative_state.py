"""叙事状态与因果对账：把"情节前后不对应"从"读起来别扭"变成可判定的一条。

为什么单开一个模块，而不是塞进 `continuity_graph`
--------------------------------------------------
`continuity_graph` 问的是**实体状态**：死没死、地点在不在、时间线顺序对不对。
那些只要**一张章**被看到就能判（权威设定每窗全量带进模型）。
而作者抱怨的"AI 缺乏对情节前后关系的推理，会写出前后不对应甚至矛盾的情节"，
多数不是实体状态，是**因果**：

- 第 40 章让她用上了从未获得的知情，全书没有一章交代她怎么知道的；
- 第 2 章写死"只有她亲口叫出那个名字，钟才会停"，第 40 章钟停了，而她始终没有开口。

这类判断需要**两张章同时在场**，所以窗口法在远端**结构性**做不到：
同窗距离上界见 `docs/longrange-consistency-and-eval.md` 第八节（60 章实测
16-30 桶同窗率 0.00）。本模块绕开窗口的办法是：**按新章自己的断言去索引历史断言**，
查询跨度与章距无关——一次遍历就能把第 2 章与第 40 章对上。

只判**两侧都是显式断言**的矛盾（这是本模块最重要的取舍）
--------------------------------------------------------
不判"没交代"（缺省推断连人都要读完整本才敢下结论），只判两种：

A. ``unenabled_event``：前面**明写**某人不知道某事，后面**明写**他知道了，
   而中间**没有任何**授予知情的断言；
B. ``payoff_terms_mismatch``：前面**明写**某结果的前提条件，后面**明写**结果发生了、
   且**明写**前提里的那个动作没有发生。

两条都要求两侧都有字面证据，所以：不需要模型，也不会因为"作者没写"而误报。
代价是**召回偏低**（判不了隐喻式伏笔、判不了"没说但读者能推出来"的那类）——
这个上界是刻意的：宁可漏，也不能把作者的正常写法当成矛盾报上去。

已知判不了的东西（写在这里，免得下一个人以为它该管）
----------------------------------------------------
- **代词主题**（「这些」「那件事」）一律不建断言：指代要靠上下文消解，纯文本层面
  判不了，硬凑只会制造误报（见 `_PRONOUN_TOPICS`）。
- **主题词面不一致**：「门后的一切」与「那扇门后面是什么」靠高频字交集匹配，
  换个说法就未必接得上；所以阈值取宽，精度靠"同一主语 + 两侧都是显式断言"兜住。
- **动作类别的覆盖面**：只认 `_ACTION_CLASSES` 里那几类说法（「开口」「碰」
  「进入」），类别之外的动作（「按下开关」「点燃信纸」）判不了。

严重度：一律 ``warn``。这是**推断**不是证明，所以只进候选与提示，**不挡任何东西**
（`write_gate` 目前只阻断 `dead_character_present` 这类可证缺口）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.domain.types import VnProject

#: 主题匹配时剔掉的字：虚词、代词、数词、能愿动词、方位词。留下的是**内容字**。
#: 用字集合（而不是分词）是因为这里只需要"两句话说的是不是同一件事"这个粗判；
#: 上分词器会把依赖与维护成本一起带进来，而精度由"同一主语 + 两侧显式"兜住。
_TOPIC_STOP = set(
    "的了是在有和与及就都也还才不没我你他她它们这那些什么么怎样会要能可所以为等"
    "一二三四五六七八九十上下里外中前后时着过又再很太更最"
)

#: 指代不明的主题：出现这些就当"这一条判不了"，不建断言。
_PRONOUN_TOPICS = {"这些", "那些", "这件事", "那件事", "一切", "什么", "它", "它们", "此事"}

#: 知情类动词。`不` 紧贴在动词前即为"不知道"这一侧。
_KNOW_RE = re.compile(r"(?P<neg>不)?(?P<verb>知道|知情|明白|得知|意识到|了解|清楚)")

#: "授予知情"的写法：中间章出现这些，说明前文的"不知道"已被覆盖，不再报。
#: 刻意只收明确的告知/揭开类动词——「看见」「听见」不算，因为看见不等于被告知。
_GRANT_RE = re.compile(r"告诉|告知|透露|坦白|说明|解释|揭开|查明|查清|承认")

#: 前提条款：「只有 A，B 才 C」。A 是**前提动作**，B+C 是**被条件约束的结果**。
#: 要求 A 与结果之间有一个逗号：「只有…才…」在中文里最常见的断句就是这样，
#: 不要求逗号会把「只有他知道这件事」这类定语从句也吞进来。
_COND_RE = re.compile(
    r"只有(?P<action>[^，,。！？；]{1,40})[，,](?P<out>[^，,。！？；]{1,40}?)才(?P<rest>[^。！？；]{1,20})"
)

#: 动作**类别**：结果被约束在一个动作上时，后面才认得出"这个动作没发生"。
#: 只收几类高频、说法收敛的动作；类别之外的一律不判（见模块 docstring）。
_ACTION_CLASSES: Dict[str, Tuple[str, ...]] = {
    "utter": ("开口", "出声", "说出", "说话", "叫出", "喊出", "念出", "回答", "唱出"),
    "touch": ("碰", "摸", "触碰", "接触", "拿起", "握住"),
    "enter": ("进入", "走进", "进门", "跨进"),
}

#: 否定写法：`没有开口` / `没开口` / `始终没有开口` / `未开口` / `不曾开口`
_NEG_RE = re.compile(r"没|没有|未|不曾|从未|从不|未能")

#: 主题匹配阈值。**用重叠系数（inter/min）而不是 Jaccard**：一侧常常只是另一侧的
#: 片段——「门后的一切」对「那扇门后面是什么」，能对上的只有「门」一个字。Jaccard
#: 会被并集里的噪声字稀释到阈值以下（实测 1/4=0.25），而这正是本模块最该抓住的
#: 那类改写。精度不靠这里卡死，靠"同一主语 + 前后都是显式断言"两道约束兜。
_TOPIC_SIMILARITY = 0.5

#: 否定词要落在动作词前多少字以内才算"否定了这个动作"。
_NEG_WINDOW = 8


def _topic_chars(text: str) -> Set[str]:
    """主题的内容字集合（去掉虚词/代词/数词/方位词）。"""
    return {c for c in (text or "") if "\u4e00" <= c <= "\u9fff" and c not in _TOPIC_STOP}


def _similar(a: Set[str], b: Set[str]) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    if not inter:
        return False
    return (inter / min(len(a), len(b))) >= _TOPIC_SIMILARITY


def _clean_topic(text: str) -> str:
    """把断言后面的尾巴收拾成主题：去掉标点、句末语气词，以及**开头的体标记**。

    开头的「了」「已经」「曾经」是体（aspect）标记而不是主题的一部分——
    「她已经知道了门后的一切」里断言之后剩下的是「了门后的一切」，
    不去掉这个「了」，主题就会被写成「了门后的一切」（实测就是这样）。
    """
    cleaned = re.sub(r"[。！？；，,、\s\"「」'']+$", "", (text or "").strip())
    return re.sub(r"^(?:了|已经|曾经|总算|终于|早就|就)+", "", cleaned).strip()


@dataclass
class KnowledgeAssertion:
    """某人在某一章**明写**知道 / 不知道某件事。"""

    chapterId: str
    chapterIndex: int
    subject: str
    topic: str
    polarity: str  # knows | not_knows
    quote: str

    @property
    def topic_chars(self) -> Set[str]:
        return _topic_chars(self.topic)


@dataclass
class ConditionAssertion:
    """某一章给出的前提条款：「只有（动作）…，（结果）才…」。"""

    chapterId: str
    chapterIndex: int
    action_text: str
    action_classes: Set[str]
    outcome: str
    quote: str

    @property
    def outcome_chars(self) -> Set[str]:
        return _topic_chars(self.outcome)


@dataclass
class NarrativeState:
    knowledge: List[KnowledgeAssertion] = field(default_factory=list)
    conditions: List[ConditionAssertion] = field(default_factory=list)
    #: (章序, 章 id, 正文)。payoff 规则要在"条件之后"的章里找共现，所以正文必须留着。
    chapters: List[Tuple[int, str, str]] = field(default_factory=list)
    #: 「授予知情」的写法，记成 (章序, 那句话)。必须带句子：只按"这一章里出现过
    #: 告诉/说明"来抑制，会把**与本事无关**的那些交代也算成已经交代过——
    #: 实测就是这么把一条真的无因事件给漏掉的（见 `_findings_unenabled`）。
    grants: List[Tuple[int, str]] = field(default_factory=list)


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[。！？；\n])", text or "") if s.strip()]


def _name_positions(text: str, names: Sequence[Tuple[str, str]]) -> List[Tuple[int, str]]:
    """句子里出现的角色名及其位置。长名优先，避免短名把长名切碎。"""
    found: List[Tuple[int, str]] = []
    taken: List[Tuple[int, int]] = []
    for name, _cid in names:
        start = 0
        while True:
            pos = text.find(name, start)
            if pos < 0:
                break
            if not any(s <= pos < e for s, e in taken):
                found.append((pos, name))
                taken.append((pos, pos + len(name)))
            start = pos + len(name)
    return sorted(found)


def _extract_knowledge(
    text: str, names: Sequence[Tuple[str, str]], chapter_id: str, index: int
) -> List[KnowledgeAssertion]:
    out: List[KnowledgeAssertion] = []
    for sentence in _sentences(text):
        positions = _name_positions(sentence, names)
        if not positions:
            continue
        for m in _KNOW_RE.finditer(sentence):
            # 主语取动词**之前最近**的那个名字。这是最廉价的代词消解：
            # 「林夏径直走向那扇门，她已经知道了…」里的「她」按最近原则归给林夏。
            before = [p for p in positions if p[0] < m.start()]
            if not before:
                continue
            subject = before[-1][1]
            topic = _clean_topic(sentence[m.end() :])
            if not topic or topic in _PRONOUN_TOPICS:
                continue  # 指代不明 → 判不了，不建断言
            if not _topic_chars(topic):
                continue
            out.append(
                KnowledgeAssertion(
                    chapterId=chapter_id,
                    chapterIndex=index,
                    subject=subject,
                    topic=topic,
                    polarity="not_knows" if m.group("neg") else "knows",
                    quote=sentence.strip(),
                )
            )
    return out


def _action_classes(action_text: str) -> Set[str]:
    return {
        name
        for name, keywords in _ACTION_CLASSES.items()
        if any(k in action_text for k in keywords)
    }


def _extract_conditions(text: str, chapter_id: str, index: int) -> List[ConditionAssertion]:
    out: List[ConditionAssertion] = []
    for sentence in _sentences(text):
        for m in _COND_RE.finditer(sentence):
            action = m.group("action").strip()
            outcome = (m.group("out") + m.group("rest")).strip()
            classes = _action_classes(action)
            if not classes or not _topic_chars(outcome):
                continue
            out.append(
                ConditionAssertion(
                    chapterId=chapter_id,
                    chapterIndex=index,
                    action_text=action,
                    action_classes=classes,
                    outcome=outcome,
                    quote=sentence.strip(),
                )
            )
    return out


def build_state(project: VnProject) -> NarrativeState:
    """把全书按章扫成叙事状态（纯本地、不调模型）。

    正文来源走 `agent_context.chapter_plain`（正文优先，正文为空才渲染块）——
    与硬锚块、写前对账同源，避免出现"这里读 blocks、那里读 prose"两套口径。
    """
    from app.core.agent_context import chapter_plain

    characters = list(project.characters or [])
    names: List[Tuple[str, str]] = []
    for c in characters:
        cid = str(getattr(c, "id", "") or "")
        for raw in [
            getattr(c, "displayName", None),
            getattr(c, "defineName", None),
            *list(getattr(c, "aliases", None) or []),
        ]:
            name = str(raw or "").strip()
            if name:
                names.append((name, cid))
    names.sort(key=lambda p: len(p[0]), reverse=True)

    state = NarrativeState()
    for index, ch in enumerate(project.chapters or []):
        cid = str(getattr(ch, "id", "") or "")
        text = chapter_plain(ch, characters)
        if not text:
            continue
        state.chapters.append((index, cid, text))
        state.knowledge.extend(_extract_knowledge(text, names, cid, index))
        state.conditions.extend(_extract_conditions(text, cid, index))
        for sentence in _sentences(text):
            if _GRANT_RE.search(sentence):
                state.grants.append((index, sentence.strip()))
    return state


# ------------------------------------------------------------------ 两条判定


def _findings_unenabled(state: NarrativeState) -> List[Dict[str, Any]]:
    """规则 A：明写"不知道" → 明写"知道了"，中间没有任何授予知情的断言。"""
    out: List[Dict[str, Any]] = []
    for now in state.knowledge:
        if now.polarity != "knows":
            continue
        for before in state.knowledge:
            if before.polarity != "not_knows":
                continue
            if before.subject != now.subject or before.chapterIndex >= now.chapterIndex:
                continue
            if not _similar(before.topic_chars, now.topic_chars):
                continue
            # 中间（**含本章**）有没有交代这件事是怎么知道的？
            #
            # 两个关键取舍：
            # ① **必须看那句话讲的是不是同一件事**。只用"这一章里出现过告诉/说明"来
            #    抑制，会把与本事无关的交代也算成已交代——实测正是这样漏掉了一条真的
            #    无因事件（第 13 章埋、第 46 章兑现，中间第 23 章因为别处的「说明」被
            #    当成了交代）。所以要求那句话**提到同一主语**或**主题相近**。
            # ② **含本章**：把交代与结果写在同一章（「他告诉她来历。她已经知道了来历。」）
            #    是常见写法，用严格小于会把它误判成无因事件。
            #
            # 已知残留：把知情授予写成"他告诉了她一切"（代词主语 + 代词主题）时，
            # 两条腿都够不着，会**多报**一条。这是刻意选的方向：宁可让作者看一眼
            # 一条多余的提示，也不要把真的漏掉。
            if any(
                before.chapterIndex < gi <= now.chapterIndex
                and (now.subject in gsent or _similar(_topic_chars(gsent), now.topic_chars))
                for gi, gsent in state.grants
            ):
                continue
            out.append(
                {
                    "code": "unenabled_event",
                    "severity": "warn",
                    "chapterId": now.chapterId,
                    "subject": now.subject,
                    "message": (
                        f"「{now.subject}」在第 {before.chapterIndex + 1} 章还是「{before.topic}」，"
                        f"到第 {now.chapterIndex + 1} 章已经「{now.topic}」，"
                        "而中间没有任何一章交代这个知情是怎么来的。"
                        "（依据是两侧正文的显式断言；若中间确有交代，请忽略）"
                    ),
                    "evidence": {
                        "beforeChapterId": before.chapterId,
                        "before": before.quote,
                        "after": now.quote,
                    },
                }
            )
            break
    return out


def _negated_action(text: str, classes: Set[str]) -> Optional[str]:
    """这一章里有没有"明写某动作没发生"？返回那句话，没有则 None。

    同时要求：同一个动作**没有**在别处被写成发生过——否则"没碰到"与"碰到了"
    同时在章里出现时，我们会拿前半句去指控后半句。
    """
    keywords = [k for cls in classes for k in _ACTION_CLASSES[cls]]
    negated: Optional[str] = None
    for sentence in _sentences(text):
        for kw in keywords:
            pos = sentence.find(kw)
            if pos < 0:
                continue
            window = sentence[max(0, pos - _NEG_WINDOW) : pos]
            if _NEG_RE.search(window):
                negated = negated or sentence.strip()
            else:
                return None  # 动作确实发生了 → 条款满足，不报
    return negated


def _outcome_present(text: str, outcome_chars: Set[str]) -> Optional[str]:
    for sentence in _sentences(text):
        if _similar(_topic_chars(sentence), outcome_chars):
            return sentence.strip()
    return None


def _findings_payoff(state: NarrativeState) -> List[Dict[str, Any]]:
    """规则 B：结果发生了，而它的前提动作在同一章被明写为"没有发生"。"""
    out: List[Dict[str, Any]] = []
    for cond in state.conditions:
        for index, cid, text in state.chapters:
            if index <= cond.chapterIndex:
                continue
            happened = _outcome_present(text, cond.outcome_chars)
            if not happened:
                continue
            missed = _negated_action(text, cond.action_classes)
            if not missed:
                continue
            out.append(
                {
                    "code": "payoff_terms_mismatch",
                    "severity": "warn",
                    "chapterId": cid,
                    "subject": "",
                    "message": (
                        f"第 {cond.chapterIndex + 1} 章写过「{cond.quote}」，"
                        f"而第 {index + 1} 章「{happened}」——同时明写「{missed}」。"
                        "结果出现了，但当时给出的前提动作没有发生。"
                    ),
                    "evidence": {
                        "conditionChapterId": cond.chapterId,
                        "condition": cond.quote,
                        "outcome": happened,
                        "missedAction": missed,
                    },
                }
            )
            break  # 同一个条款只报最靠前的那一次
    return out


def analyze_narrative_state(project: VnProject) -> Dict[str, Any]:
    """因果对账总入口：返回 findings + 抽到了什么（便于作者与测试核对口径）。

    任何路径都不抛异常：这本是"附带能力"，不该让稿件保存或审稿挂掉。
    """
    try:
        state = build_state(project)
        findings = _findings_unenabled(state) + _findings_payoff(state)
    except Exception:  # noqa: BLE001 — 抽取失败不该让调用方挂掉
        return {"findings": [], "knowledge": 0, "conditions": 0, "notes": ["抽取失败，本轮跳过"]}
    return {
        "findings": findings,
        "knowledge": len(state.knowledge),
        "conditions": len(state.conditions),
        "notes": [
            "只判两侧都是**显式断言**的因果矛盾（明写不知道→明写知道、"
            "明写前提动作未发生而结果已发生），因此召回偏低是设计如此："
            "缺省推断与隐喻式伏笔不在射程内。"
        ],
    }
