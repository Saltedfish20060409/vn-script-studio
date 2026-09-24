"""长程一致性基准测试：把"几十万字还能不能查出一致性问题"变成可量化的实验。

为什么需要它
------------
原来的全书一致性审计有个**硬上限**：只扫前 14 章、每章截 1600 字
（`core/consistency_audit.py`）。问题是，这个上限是**静默**的——
跑一次能得到一份看起来正常的报告，作者无从知道"第 30 章的矛盾根本没被检查过"。

于是一个自然的疑问浮上来：**长篇到底从第几章开始失效？**
本文回答它，方式不是举例子，而是造一个**带标准答案的合成长篇**：

1. 用模板生成 N 章连贯的小说，先建立一批"权威事实"（年龄 / 季节 / 关系 / 物件 /
   死亡 / 时间线）；
2. 在**受控章距**上注入矛盾——把第 k 章建立的事实，在第 k+d 章写反；
3. 同时埋入**诱导项**（看着可疑但其实不矛盾，例如"十七岁那年"是回忆、
   另一角色同名物件），用来量误报；
4. 用两种指标评估：
   - ``exposure``（暴露率）：矛盾的**冲突章**有没有被送进检测器视野。
     这是检测的必要条件，**不需要任何模型**就能算——旧方案在第 15 章之后
     暴露率为 0，于是那些章的召回**在构造上**就不可能是 1。
   - ``detection``：给定一套检测结果，按类别 + 章节重合判对错，算
     precision / recall / F1，并按章距分桶看衰减。
5. 分两层埋点，避免"没配 Key 就跑不了"：
   - **A 层（确定性可分）**：死亡后仍出场、时间线顺序矛盾、未声明地点、
     未登记说话人——这些现有确定性检测器能抓；
   - **B 层（语义，需模型）**：年龄 / 季节 / 关系 / 物件属性矛盾——
     只有 LLM 扫描能抓，用于在有 Key 时评估分片扫描。

评价口径（写清楚，免得被误读）
------------------------------
- 只在**基准埋点涉及的类别**内计分；结构性 lint（死代码、章末无出口等）
  记为 ``outOfScope`` 并单列，不计入 precision——本文量的是"事实矛盾检出"，
  不是"结构性写得干不干净"。
- 章节重合但类别判错 → 记 ``misclassified``，既不算命中也不算误报，单列出来。
- 一个埋点被多条检测命中只算一次（避免刷召回），但多余的那几条会进 ``duplicateHits``。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.project import normalize_project
from app.domain.types import VnProject

#: 旧实现的硬上限，用来做对照（不要改这两个数，它代表"以前的线上行为"）。
LEGACY_MAX_CHAPTERS = 14
LEGACY_CHAPTER_TEXT_CAP = 1600

#: 分片方案默认参数：**直接取生产实现的常量**，不再抄一份数值。
#:
#: 抄一份的代价实测过：把生产默认值从 6/2 调到 12/4 时，基准还在按 6/2 切窗，
#: 于是"基准必须测线上真正跑的那套切窗逻辑"那条测试立刻红了——基准测的就不再是线上行为。
from app.core.consistency_scan import (  # noqa: E402  (放在常量区，见上方说明)
    DEFAULT_WINDOW_OVERLAP,
    DEFAULT_WINDOW_SIZE,
)

#: 章距分桶：用来展示"越远越查不出"的衰减曲线。
DISTANCE_BUCKETS: List[Tuple[str, int, int]] = [
    ("1-3", 1, 3),
    ("4-8", 4, 8),
    ("9-15", 9, 15),
    ("16-30", 16, 30),
    ("31+", 31, 10**9),
]


def bucket_of(distance: int) -> str:
    for name, lo, hi in DISTANCE_BUCKETS:
        if lo <= distance <= hi:
            return name
    return DISTANCE_BUCKETS[-1][0]


def bucket_range(name: str) -> Tuple[int, int]:
    for bname, lo, hi in DISTANCE_BUCKETS:
        if bname == name:
            return lo, hi
    raise KeyError(f"未知章距分桶：{name}")


# --------------------------------------------------------------------- 生成器


@dataclass
class Planted:
    id: str
    category: str  # character | timeline | location | bible | plot | style
    kind: str
    tier: str  # deterministic | semantic
    establishedChapter: str
    conflictChapter: str
    distance: int
    establishedQuote: str
    conflictQuote: str
    description: str
    #: 涉及的角色 id / 物件 / 标签等主语。标注它，下游（含测试）就不必靠
    #: "哪个角色在这一章说过话"去反推主语——那个推断在有多个埋点时并不可靠。
    subject: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "kind": self.kind,
            "tier": self.tier,
            "establishedChapter": self.establishedChapter,
            "conflictChapter": self.conflictChapter,
            "distance": self.distance,
            "bucket": bucket_of(self.distance),
            "establishedQuote": self.establishedQuote,
            "conflictQuote": self.conflictQuote,
            "description": self.description,
            "subject": self.subject,
        }


@dataclass
class Distractor:
    id: str
    chapter: str
    kind: str
    quote: str
    why: str
    tier: str = "semantic"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "chapter": self.chapter,
            "kind": self.kind,
            "quote": self.quote,
            "why": self.why,
            "tier": self.tier,
        }


_WEATHER = ["细雨", "阴云", "风把站牌吹得发白", "路灯下浮着薄雾", "夜里的凉意贴着皮肤"]
_ACTION = [
    "她把伞收了，水顺着伞骨滴到鞋尖",
    "他在检票口站了一会儿，没进去",
    "远处传来广播，念不清站名",
    "手机屏亮了一下，又暗下去",
    "她把袖口往上折了两折",
]


def _chapter(chapter_id: str, title: str, blocks: List[dict]) -> dict:
    return {"id": chapter_id, "title": title, "blocks": blocks}


def _narr(text: str) -> dict:
    return {"type": "narration", "text": text}


def _dlg(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def build_synthetic_novel(
    *,
    chapters: int = 48,
    seed: int = 20260409,
    deterministic_per_kind: int = 2,
    semantic_per_kind: int = 2,
    distractors: int = 3,
) -> Tuple[VnProject, Dict[str, Any]]:
    """造一部 N 章的合成长篇 + 标准答案（planted 矛盾 + 诱导项）。

    设计原则：**干净基线必须真的干净**——没有注入任何矛盾的那些章节，
    确定性检测器跑上去应当一条都不报（测试里锁死了这一点）。
    否则 precision 会被结构性噪音淹没，指标就失去意义。
    """
    if chapters < 12:
        raise ValueError("章节数太少，无法覆盖多个章距分桶")
    rng = random.Random(seed)

    characters = [
        {"id": "lin", "defineName": "lin", "displayName": "林夏", "aliases": ["阿夏"]},
        {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
        {"id": "chen", "defineName": "chen", "displayName": "陈默"},
        # 沈知：A 层"声线走样"埋点专用角色。与死亡埋点（林夏/周屿）、
        # 语义埋点（陈默）都不共用角色，几类埋点互不干扰。
        {"id": "shen", "defineName": "shen", "displayName": "沈知"},
        # 吴岚 / 韩序：A 层"情感弧线断裂"埋点专用角色。
        # **每个情感埋点必须用不同角色**：共用角色时，后一个埋点的"平静"章会插在
        # 前一个埋点的激动章之后，把"全篇起点情绪"污染成激动，全篇走向于是变平，
        # 断裂判定（局部与全篇相反）自然不成立——实测就是这样把两项都变成漏检的。
        {"id": "wu", "defineName": "wu", "displayName": "吴岚"},
        {"id": "han", "defineName": "han", "displayName": "韩序"},
    ]
    locations = [
        {"id": "loc-station", "name": "车站", "imageTag": "bg_station", "description": "老旧的站台"},
        {"id": "loc-library", "name": "图书馆", "imageTag": "bg_library", "description": "很安静"},
    ]
    variables = [
        {"id": "v-truth", "name": "真相", "key": "saw_truth", "type": "bool", "value": False}
    ]

    chapter_titles = [f"第{i}章" for i in range(1, chapters + 1)]
    ch_ids = [f"ch{i}" for i in range(1, chapters + 1)]

    blocks_by_chapter: Dict[str, List[dict]] = {}
    for i, cid in enumerate(ch_ids):
        base: List[dict] = []
        if i == 0:
            base.append({"type": "label", "id": "start", "name": "start"})
        base.append({"type": "scene", "image": rng.choice(["bg_station", "bg_library"])})
        base.append(_narr(f"{rng.choice(_WEATHER)}。{rng.choice(_ACTION)}。"))
        base.append(_dlg("lin", "末班车还来吗。"))
        base.append(_dlg("zhou", "来。"))
        # 沈知每章只有一句极短台词：这是他"寡言克制"的稳定基线。
        # 声线量具评估某一章需要该角色在那章有 ≥3 句，所以正常情况下不会误报；
        # 只有被埋了"走样"的那一章他会连说几句长台词。
        base.append(_dlg("shen", "嗯。"))
        base.append(_narr(f"{rng.choice(_ACTION)}。"))
        base.append({"type": "return"})
        blocks_by_chapter[cid] = base

    planted: List[Planted] = []
    distractor_rows: List[Distractor] = []
    timeline: List[dict] = []
    #: 写进 project.writingLedger 的伏笔行。伏笔回收率读的就是这里，
    #: 所以"未回收的钩子"这类埋点必须落在账本里，而不是散在正文里等抽取。
    foreshadow_seed: List[dict] = []

    def pick_in_bucket(bucket: str) -> Tuple[int, int]:
        """在指定章距分桶内挑一对 (建立章, 冲突章)。

        刻意**显式铺满每个分桶**，而不是随机撒点：随机撒会导致近端（1–3 章）
        几乎没有埋点，于是"检出率随章距衰减"这条曲线只有远端、画不出来——
        而没有近端对照，就无法区分"远距离查不出"和"这个检测器本来就查不出"。

        作品太短装不下目标分桶时（例如 30 章里塞 "31+"），退到**能塞下的最大距离**：
        宁可在结果里如实反映"这个距离放不进这本作品"，也不能越界或静默丢埋点。
        """
        lo, hi = bucket_range(bucket)
        max_d = chapters - 1
        if max_d < 1:
            return 0, 1
        hi_eff = min(hi, max_d)
        lo_eff = min(lo, hi_eff)
        d = rng.randint(lo_eff, hi_eff)
        est = rng.randint(0, max(0, chapters - 1 - d))
        return est, est + d

    bucket_cycle = [name for name, _lo, _hi in DISTANCE_BUCKETS]

    def target_bucket(k: int, offset: int) -> str:
        return bucket_cycle[(k + offset) % len(bucket_cycle)]

    used_chapters: set[str] = set()

    def pick_free(bucket: str) -> Optional[Tuple[int, int]]:
        """在分桶内挑一对**尚未被其它埋点占用**的章；找不到就返回 None（放弃该埋点）。

        占用检查不是洁癖，是判定正确性的前提：如果一个埋点的"建立章"正好是另一个
        埋点的"冲突章"，检测器只报一条就同时落在两个埋点的跨度里，归属变得含糊——
        基准会把这条算给其中一个，另一个就凭空变成"漏检"。
        实测就是在这一点上把确定性层的召回从 1.00 拉到了 0.90。
        """
        for _ in range(32):
            est, conflict = pick_in_bucket(bucket)
            key_est, key_con = ch_ids[est], ch_ids[conflict]
            if key_est not in used_chapters and key_con not in used_chapters:
                used_chapters.add(key_est)
                used_chapters.add(key_con)
                return est, conflict
        return None

    # ---------- A 层：确定性可分 ----------
    # ① 死亡后仍出场（按章距分批）
    #    每个埋点用**不同角色**：同一角色埋两次死亡记录会让"死亡章"变得歧义
    #    （检测器只能取最早那次），那是基准自身的伪影，不是检测器的缺陷。
    death_chars = [c["id"] for c in characters]
    for k in range(deterministic_per_kind):
        pair = pick_free(target_bucket(k, 0))
        if pair is None:
            continue
        est, conflict = pair
        d = conflict - est
        who = death_chars[k % len(death_chars)]
        display = next(c["displayName"] for c in characters if c["id"] == who)
        death_quote = f"{display}去世了。"
        # order 与章节序保持一致：不再制造**计划外**的顺序矛盾，
        # 否则"顺序矛盾"这项召回会被非受控埋点污染，数字没法解释。
        timeline.append(
            {
                "id": f"tl-death-{k}",
                "title": f"告别 {k}",
                "summary": death_quote,
                "when": f"第{est + 1}章",
                "order": 1000 + est,
                "chapterRef": ch_ids[est],
            }
        )
        blocks_by_chapter[ch_ids[conflict]].insert(-1, _dlg(who, "我在这儿。"))
        # 让该角色在"去世"到声明的冲突章之间**闭嘴**。
        # 不这么做的话，基线里每章都有他的台词，检测器会在死亡次章就报违规——
        # 而那不是我们声明的距离，基准的"章距 vs 召回"曲线就失去控制变量。
        for gap in range(est + 1, conflict):
            blocks_by_chapter[ch_ids[gap]] = [
                blk
                for blk in blocks_by_chapter[ch_ids[gap]]
                if not (blk.get("type") == "dialogue" and blk.get("characterId") == who)
            ]
        planted.append(
            Planted(
                id=f"det-death-{k}",
                category="character",
                kind="death_then_speaks",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=d,
                establishedQuote=death_quote,
                conflictQuote=f"{display}：我在这儿。",
                description=f"第{est + 1}章记录{display}去世，第{conflict + 1}章仍有台词",
                subject=who,
            )
        )

    # ② 时间线顺序矛盾（order 与章节先后不一致）——这是本基准**唯一**的受控顺序矛盾
    for k in range(deterministic_per_kind):
        pair = pick_free(target_bucket(k, 1))
        if pair is None:
            continue
        est, conflict = pair
        timeline.append(
            {
                "id": f"tl-a-{k}",
                "title": f"事件甲 {k}",
                "summary": "先发生的事",
                "order": 200,
                "chapterRef": ch_ids[conflict],
            }
        )
        timeline.append(
            {
                "id": f"tl-b-{k}",
                "title": f"事件乙 {k}",
                "summary": "后发生的事",
                "order": 201,
                "chapterRef": ch_ids[est],
            }
        )
        planted.append(
            Planted(
                id=f"det-order-{k}",
                category="timeline",
                kind="timeline_order_conflict",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=conflict - est,
                establishedQuote=f"事件乙（order 201）在 {ch_ids[est]}",
                conflictQuote=f"事件甲（order 200）在 {ch_ids[conflict]}",
                description="order 大小与章节先后相反",
                subject="timeline",
            )
        )

    # ③ 声线走样：寡言克制的角色在某一章被写成长篇大论。
    #    这是"角色像不像本人"这一维的**带标注埋点**——在此之前这一维没有任何量具，
    #    只能靠作者凭感觉读、或再调一次模型主观判断。声线量具是确定性的，
    #    所以它进 A 层，可以进 CI 当回归基准。
    for k in range(deterministic_per_kind):
        pair = pick_free(target_bucket(k, 4))
        if pair is None:
            continue
        est, conflict = pair
        verbose_lines = [
            "我今天在车站等了三个小时呢，结果什么也没等到，真是的。",
            "你要是不来的话，我就一直等下去哦，反正我也没什么别的地方可以去嘛。",
            "说起来啊，那天的雨其实挺大的，我站在檐下看了很久，心里有点乱。",
            "总之呢，你什么时候有空，我们就什么时候再说，我都可以的呀。",
        ]
        # 把该章里沈知那句短台词换成一段长篇大论：同一章内他的语言风格整体位移
        blocks_by_chapter[ch_ids[conflict]] = [
            blk
            for blk in blocks_by_chapter[ch_ids[conflict]]
            if not (blk.get("type") == "dialogue" and blk.get("characterId") == "shen")
        ]
        for line in verbose_lines:
            blocks_by_chapter[ch_ids[conflict]].insert(-1, _dlg("shen", line))
        planted.append(
            Planted(
                id=f"det-voice-{k}",
                category="character",
                kind="voice_drift",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=conflict - est,
                establishedQuote="沈知：嗯。（一贯寡言）",
                conflictQuote=verbose_lines[0],
                description="寡言克制的角色在同一章里被写成长篇大论（声线走样）",
                subject="shen",
            )
        )

    # ④ 未声明地点标（scene 用了没登记过的 image tag）
    for k in range(deterministic_per_kind):
        pair = pick_free(target_bucket(k, 2))
        if pair is None:
            continue
        est, conflict = pair
        blocks_by_chapter[ch_ids[est]].insert(
            1, {"type": "scene", "image": "bg_station"}
        )
        blocks_by_chapter[ch_ids[conflict]].insert(
            1, {"type": "scene", "image": f"bg_rooftop_{k}"}
        )
        planted.append(
            Planted(
                id=f"det-loc-{k}",
                category="location",
                kind="unknown_location_tag",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=conflict - est,
                establishedQuote="bg_station（已登记）",
                conflictQuote=f"bg_rooftop_{k}（未登记）",
                description="场景用了未在地点表登记的 image tag",
                subject=f"bg_rooftop_{k}",
            )
        )

    # ⑤ 未登记说话人
    for k in range(deterministic_per_kind):
        pair = pick_free(target_bucket(k, 3))
        if pair is None:
            continue
        est, conflict = pair
        blocks_by_chapter[ch_ids[conflict]].insert(-1, _dlg(f"ghost{k}", "……"))
        planted.append(
            Planted(
                id=f"det-speaker-{k}",
                category="character",
                kind="unknown_speaker",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=conflict - est,
                establishedQuote="说话人都在角色卡里",
                conflictQuote="characterId=ghost（无角色卡）",
                description="台词指向不存在的角色 id",
                subject=f"ghost{k}",
            )
        )

    # ---------- B 层：语义矛盾（需模型） ----------
    # 建立事实的句子固定在很早的章节，冲突写在很晚的章节
    semantic_specs = [
        ("age_conflict", "character", "林夏今年十七岁。", "林夏今年十九岁。", "年龄前后不一致"),
        ("season_conflict", "bible", "故事发生在冬天，站台上落着雪。", "盛夏的站台，蝉鸣吵得人心烦。", "季节前后不一致"),
        ("relationship_conflict", "character", "周屿是她的学长。", "周屿是她的弟弟。", "人物关系前后不一致"),
        ("item_conflict", "plot", "那把伞是深蓝色的。", "那把红伞她一直留着。", "同一件物品的属性不一致"),
    ]
    est_indices = [1, 2, 3, 4][: len(semantic_specs)]
    early_span = max(6, chapters // 2)
    for k in range(semantic_per_kind):
        for si, (kind, category, setup, conflict_text, desc) in enumerate(semantic_specs):
            # 距离**先定死**在目标分桶里，再倒推建立章：否则"建立章固定写在前几章"
            # 会把大分桶压成小分桶（distance 被截断），分桶统计就不再可信。
            lo, hi = bucket_range(target_bucket(k, si))
            d = rng.randint(lo, max(lo, min(hi, chapters - 2)))
            # 同样要避开已被占用的章（理由见 pick_free）。语义埋点的建立章希望靠前，
            # 但"靠前"让位于"不冲突"：章冲突会让判定归属变含糊，那比建立章偏后严重得多。
            candidates = [
                i
                for i in range(0, early_span)
                if i + d <= chapters - 1
                and ch_ids[i] not in used_chapters
                and ch_ids[i + d] not in used_chapters
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda i: (abs(i - est_indices[si]), i))
            e = (
                candidates[0]
                if rng.random() < 0.7
                else candidates[rng.randrange(len(candidates))]
            )
            c = e + d
            used_chapters.add(ch_ids[e])
            used_chapters.add(ch_ids[c])
            # 语义埋点固定用第三位角色（陈默）：他与 A 层的死亡/声线埋点不共用角色，
            # 因此"死亡后闭嘴"的处理不会误删语义埋点的台词，几类埋点互不干扰。
            blocks_by_chapter[ch_ids[e]].insert(-1, _dlg("chen", setup))
            blocks_by_chapter[ch_ids[c]].insert(-1, _dlg("chen", conflict_text))
            planted.append(
                Planted(
                    id=f"sem-{kind}-{k}",
                    category=category,
                    kind=kind,
                    tier="semantic",
                    establishedChapter=ch_ids[e],
                    conflictChapter=ch_ids[c],
                    distance=d,
                    establishedQuote=setup,
                    conflictQuote=conflict_text,
                    description=desc,
                    subject="chen",
                )
            )

    # ⑥ 情感弧线断裂：全篇的情绪往上走，但中间某一章掉下来。
    #    需要**三个**章才能构造成"全篇有明确走向、局部反向"：
    #    建立章（平静）→ 断裂章（激动掉到平静）→ 收尾章（激动，把全篇走向拽成向上）。
    #    每个埋点用一个**独立角色**（理由见 characters 里的注释）。
    arc_chars = ["wu", "han"]
    for k in range(deterministic_per_kind):
        triple = _pick_emotion_triple(pick_free, ch_ids, used_chapters, target_bucket(k, 0))
        if triple is None:
            continue
        est, conflict, closing = triple
        who = arc_chars[k % len(arc_chars)]
        # 建立章：平静（全篇的"起点"）
        for line in ("嗯。", "好。"):
            blocks_by_chapter[ch_ids[est]].insert(-1, _dlg(who, line))
        # 断裂章：先激动再平静（局部往下），且必须有 ≥2 句才评估该章
        for line in ("混蛋！", "该死！", "算了。", "嗯。"):
            blocks_by_chapter[ch_ids[conflict]].insert(-1, _dlg(who, line))
        # 收尾章：激动（全篇终点的情绪），必须在断裂章之后
        for line in ("你给我站住！", "别走！"):
            blocks_by_chapter[ch_ids[closing]].insert(-1, _dlg(who, line))
        planted.append(
            Planted(
                id=f"det-arc-{k}",
                category="character",
                kind="emotion_arc_break",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=conflict - est,
                establishedQuote="嗯。／好。（全篇从平静起步）",
                conflictQuote="混蛋！……嗯。（这一章从激动掉到平静）",
                description=(
                    "全篇情绪往上走（平静→激动），但这一章局部是往下掉的，"
                    "局部走向与全篇相反"
                ),
                subject=who,
            )
        )

    # ⑦ 未回收伏笔：账本里埋一个钩子，全书结束都没回收。
    #    先给两条已回收的，保证回收率不是 0/0（也就有了"已回收不该被报"的对照）。
    for k in range(deterministic_per_kind):
        pair = pick_free(target_bucket(k, 1))
        if pair is None:
            continue
        est, conflict = pair
        foreshadow_seed.append(
            {
                "id": f"fo-paid-{k}",
                "hook": f"已回收的钩子 {k}",
                "status": "paid",
                "plantedChapter": ch_ids[est],
                "paidInChapter": ch_ids[conflict],
            }
        )
        foreshadow_seed.append(
            {
                "id": f"fo-open-{k}",
                "hook": f"埋下就没再提的钩子 {k}",
                "status": "open",
                "plantedChapter": ch_ids[conflict],
            }
        )
        planted.append(
            Planted(
                id=f"det-hook-{k}",
                category="plot",
                kind="foreshadow_unresolved",
                tier="deterministic",
                establishedChapter=ch_ids[est],
                conflictChapter=ch_ids[conflict],
                distance=conflict - est,
                establishedQuote=f"已回收的钩子 {k}（对照组：不该被报）",
                conflictQuote=f"埋下就没再提的钩子 {k}（到全书结束仍未回收）",
                description="账本里挂着一条从未回收的伏笔",
                subject=f"fo-open-{k}",
            )
        )

    # ---------- 诱导项：看着可疑，其实不矛盾 ----------
    distractor_specs = [
        ("回忆里的年龄", "她想起十七岁那年的冬天，那时她还不知道这些。", "这是回忆，不与当前年龄冲突"),
        ("另一角色的物件", "陈默把伞收好，那把伞是他自己的。", "物件换了主人，不是同一把"),
        ("闪回的季节", "梦里回到那年冬天，雪落在她的睫毛上。", "闪回场景，不违反当前季节"),
        ("泛指而非特指", "很多人都在等末班车，等的人各有各的理由。", "泛指句，没有具体事实主张"),
    ]
    for k in range(min(distractors, len(distractor_specs))):
        kind_name, quote, why = distractor_specs[k]
        c = min(chapters - 1, 6 + k * 5)
        blocks_by_chapter[ch_ids[c]].insert(-1, _narr(quote))
        distractor_rows.append(
            Distractor(id=f"dist-{k}", chapter=ch_ids[c], kind=kind_name, quote=quote, why=why)
        )

    project = normalize_project(
        {
            "id": "bench-longrange",
            "title": f"长程基准（{chapters} 章）",
            "characters": characters,
            "locations": locations,
            "variables": variables,
            "timeline": timeline,
            "bible": {"world": "多雨的城市。", "outline": "两人在站台反复相遇。"},
            "writingLedger": {"foreshadows": foreshadow_seed} if foreshadow_seed else None,
            "chapters": [
                _chapter(cid, chapter_titles[i], blocks_by_chapter[cid])
                for i, cid in enumerate(ch_ids)
            ],
        }
    )
    ground_truth = {
        "chapters": chapters,
        "seed": seed,
        "planted": [p.as_dict() for p in planted],
        "distractors": [d.as_dict() for d in distractor_rows],
        "counts": {
            "total": len(planted),
            "deterministic": sum(1 for p in planted if p.tier == "deterministic"),
            "semantic": sum(1 for p in planted if p.tier == "semantic"),
            "byCategory": _count_by(planted, "category"),
            "byBucket": _count_by(planted, "bucket"),
        },
    }
    return project, ground_truth


def _pick_emotion_triple(
    pick_free: Callable[[str], Optional[Tuple[int, int]]],
    ch_ids: List[str],
    used: set,
    bucket: str,
) -> Optional[Tuple[int, int, int]]:
    """挑 (建立章, 断裂章, 收尾章)：est < conflict < closing，且三章都未被占用。

    需要三章而不是两章，是因为"全篇往上走 + 局部往下掉"这个构造必须有一个**在断裂章之后**
    的章来把全篇终点拽回上方——否则全篇终点就落在断裂章的"平静"上，
    全篇走向也变成往下，那就不是"局部与全篇相反"了（测的会是另一件事）。

    这里必须用 ``pick_free`` 而不是 ``pick_in_bucket``：后者不做占用登记，
    拿它挑出来的章会和别的埋点撞章，判定归属立刻变得含糊（第一次实现就踩了这个）。
    """
    pair = pick_free(bucket)
    if pair is None:
        return None
    est, conflict = pair
    closing = next(
        (i for i in range(conflict + 1, len(ch_ids)) if ch_ids[i] not in used),
        None,
    )
    if closing is None:
        return None
    used.add(ch_ids[closing])
    return est, conflict, closing


def _count_by(rows: Sequence[Planted], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for p in rows:
        k = bucket_of(p.distance) if key == "bucket" else str(getattr(p, key))
        out[k] = out.get(k, 0) + 1
    return out


# ----------------------------------------------------------------- 扫描方案


def legacy_plan(project: VnProject, *, cap: int = LEGACY_MAX_CHAPTERS) -> List[Dict[str, Any]]:
    """复刻旧行为：只取前 ``cap`` 章，一次扫完（静默截断）。"""
    ids = [str(c.id) for c in (project.chapters or [])][:cap]
    return [{"index": 0, "chapterIds": ids, "legacy": True}]


def chunked_plan(
    project: VnProject,
    *,
    size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_WINDOW_OVERLAP,
) -> List[Dict[str, Any]]:
    """分片方案：按章序切成互相重叠的窗口，覆盖**全部**章节。

    优先直接调用**生产实现** `core/consistency_scan.plan_windows`——基准必须测
    线上真正跑的那套切窗逻辑。自己在基准里另写一份，风险是"基准测得很漂亮，
    产品切的窗却不是这样"（评测与被测对象不一致，是这类实验最经典的失效方式）。
    只有在生产模块不可导入时才回落到本地等价实现，并在结果里标出 ``fallback``。
    """
    try:
        from app.core.consistency_scan import plan_windows as _prod_plan

        windows = _prod_plan(project, size=size, overlap=overlap)
        return [
            {
                "index": i,
                "chapterIds": [str(x) for x in (w.get("chapterIds") or [])],
                "production": True,
            }
            for i, w in enumerate(windows)
        ]
    except Exception:  # noqa: BLE001 — 生产模块缺失/接口变动时仍要能跑基准
        pass
    ids = [str(c.id) for c in (project.chapters or [])]
    if not ids:
        return []
    step = max(1, size - max(0, overlap))
    windows = []
    start = 0
    while start < len(ids):
        windows.append(
            {
                "index": len(windows),
                "chapterIds": ids[start : start + size],
                "production": False,
            }
        )
        if start + size >= len(ids):
            break
        start += step
    return windows


# --------------------------------------------------------------------- 指标


def evaluate_exposure(
    ground_truth: Dict[str, Any], windows: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """暴露率：矛盾的冲突章有没有被送进检测器视野（不需要模型）。"""
    seen: set[str] = set()
    for w in windows:
        seen.update(str(x) for x in (w.get("chapterIds") or []))
    items = ground_truth.get("planted") or []
    exposed = 0
    per_bucket: Dict[str, Dict[str, int]] = {}
    missed: List[str] = []
    for it in items:
        b = str(it.get("bucket"))
        row = per_bucket.setdefault(b, {"exposed": 0, "total": 0})
        row["total"] += 1
        hit = str(it.get("conflictChapter")) in seen
        if hit:
            exposed += 1
            row["exposed"] += 1
        else:
            missed.append(str(it.get("id")))
    for row in per_bucket.values():
        row["recall"] = round(row["exposed"] / row["total"], 3) if row["total"] else 0.0
    return {
        "chaptersVisible": len(seen),
        "chaptersTotal": int(ground_truth.get("chapters") or 0),
        "exposureRecall": round(exposed / len(items), 3) if items else 0.0,
        "exposed": exposed,
        "total": len(items),
        "byBucket": _ordered_buckets(per_bucket),
        "missedItems": missed,
    }


def _ordered_buckets(per_bucket: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    order = [name for name, _lo, _hi in DISTANCE_BUCKETS]
    return {k: per_bucket[k] for k in order if k in per_bucket}


def evaluate_detections(
    ground_truth: Dict[str, Any],
    detections: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """按「种类（或类别）+ 章节重合」判对错，算 precision / recall / F1 并按章距分桶。

    归属规则（写清楚，免得数字被误读）：
    - 检测若带 ``kind``，**优先按 kind 匹配**同种埋点；无 kind 才退回按 category 匹配。
      必须这样分两级：同一个 "character" 类别下既有"死亡后出场"也有"声线走样"，
      只按类别匹配会让两类埋点互相顶包，召回数字就没意义了。
    - 章节重合但种类不符 → ``misclassified``（单列，既不算命中也不算误报）；
    - 有章节指向但不对应任何埋点 → 误报；
    - 没有章节指向、或类别不在基准范畴内 → ``outOfScope``（结构性 lint 走这里，不计入 precision）。
    """
    items = ground_truth.get("planted") or []
    scope = {str(it.get("category")) for it in items}
    by_id: Dict[str, Dict[str, Any]] = {str(it["id"]): dict(it) for it in items}

    hit_ids: set[str] = set()
    misclassified: List[Dict[str, Any]] = []
    false_positives: List[Dict[str, Any]] = []
    out_of_scope: List[Dict[str, Any]] = []
    duplicate_hits = 0
    spans = {
        str(it["id"]): {str(it.get("establishedChapter")), str(it.get("conflictChapter"))}
        for it in items
    }
    kinds = {str(it["id"]): str(it.get("kind")) for it in items}

    for det in detections or []:
        cat = str(det.get("category") or "")
        chs = {str(x) for x in (det.get("chapterIds") or []) if str(x)}
        if not chs or cat not in scope:
            out_of_scope.append({"category": cat, "chapterIds": sorted(chs)})
            continue
        overlapping = [iid for iid, chapter_set in spans.items() if chs & chapter_set]
        det_kind = str(det.get("kind") or "")
        if det_kind:
            matched = [i for i in overlapping if kinds.get(i) == det_kind]
        else:
            matched = [i for i in overlapping if by_id[i].get("category") == cat]
        if matched:
            fresh = [i for i in matched if i not in hit_ids]
            if fresh:
                hit_ids.add(fresh[0])
                duplicate_hits += max(0, len(fresh) - 1)
            else:
                duplicate_hits += 1
            continue
        if overlapping:
            misclassified.append(
                {"category": cat, "kind": det_kind, "chapterIds": sorted(chs), "nearItems": overlapping}
            )
            continue
        false_positives.append(
            {"category": cat, "kind": det_kind, "chapterIds": sorted(chs), "code": det.get("code")}
        )

    tp = len(hit_ids)
    fp = len(false_positives)
    fn = len(items) - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / len(items) if items else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    per_bucket: Dict[str, Dict[str, int]] = {}
    for it in items:
        b = str(it.get("bucket"))
        row = per_bucket.setdefault(b, {"hit": 0, "total": 0})
        row["total"] += 1
        if str(it["id"]) in hit_ids:
            row["hit"] += 1
    for row in per_bucket.values():
        row["recall"] = round(row["hit"] / row["total"], 3) if row["total"] else 0.0

    per_tier: Dict[str, Dict[str, int]] = {}
    for it in items:
        t = str(it.get("tier"))
        row = per_tier.setdefault(t, {"hit": 0, "total": 0})
        row["total"] += 1
        if str(it["id"]) in hit_ids:
            row["hit"] += 1
    for row in per_tier.values():
        row["recall"] = round(row["hit"] / row["total"], 3) if row["total"] else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "misclassified": misclassified,
        "falsePositives": false_positives,
        "outOfScope": out_of_scope,
        "duplicateHits": duplicate_hits,
        "missedItems": [str(it["id"]) for it in items if str(it["id"]) not in hit_ids],
        "byBucket": _ordered_buckets(per_bucket),
        "byTier": per_tier,
    }


# ------------------------------------------------------- 确定性检测器适配层


def detect_deterministic(project: VnProject) -> List[Dict[str, Any]]:
    """把现有确定性检查的结果统一成基准可评分的形状。

    来源：`branch_analysis`（结构类）、`continuity_graph`（事实类）、
    `voice_fingerprint`（声线类）。每条检测带 ``kind``，让判分能**按种类**精确归属
    （只按 category 匹配的话，同一个「character」类别下的死亡埋点与声线埋点会互相顶包）。
    """
    out: List[Dict[str, Any]] = []
    code_to_category = {
        "death_then_speaks": "character",
        "unknown_speaker": "character",
        "alias_collision": "character",
        "timeline_order_conflict": "timeline",
        "timeline_bad_ref": "timeline",
        "duplicate_timeline_event": "timeline",
        "unknown_location_tag": "location",
        "dangling_character_link": "character",
        "dangling_location_link": "location",
        "voice_drift": "character",
        # 故事层两类（来自 core/story_metrics.py）：都带 chapterId，因此能按章归因
        "foreshadow_unresolved": "plot",
        "emotion_arc_break": "character",
    }

    def _push(code: Any, chapter: Any, message: Any) -> None:
        key = str(code or "")
        cat = code_to_category.get(key)
        if not cat:
            return
        ch = str(chapter or "")
        out.append(
            {
                "code": key,
                "kind": key,
                "category": cat,
                "chapterIds": [ch] if ch else [],
                "message": message,
            }
        )

    try:
        from app.core.branch_analysis import analyze_branches

        for f in analyze_branches(project).get("findings") or []:
            _push(f.get("code"), f.get("chapterId"), f.get("message"))
    except Exception:  # noqa: BLE001 — 适配层失败不该让基准崩掉
        pass
    try:
        from app.core.continuity_graph import analyze_continuity

        for f in analyze_continuity(project).get("findings") or []:
            _push(f.get("code"), f.get("chapterId"), f.get("message"))
    except Exception:  # noqa: BLE001 — 模块可能尚未安装/导入失败
        pass
    try:
        # 声线走样：只把 level == "drift" 的章当检出（"watch" 是提示级别，不该算命中，
        # 否则量具会靠误报刷召回）。
        from app.core.voice_fingerprint import analyze_voices

        for row in analyze_voices(project).get("characters") or []:
            for ch_id in row.get("driftChapters") or []:
                _push(
                    "voice_drift",
                    ch_id,
                    f"「{row.get('displayName')}」在 {ch_id} 的说话方式偏离其自身习惯",
                )
    except Exception:  # noqa: BLE001 — 声线量具不可用时跳过该层
        pass
    try:
        # 故事层：未回收伏笔（按"埋点章"归因）与情感弧线断裂（按断裂章归因）。
        # 这两条是本轮才补进基准的指标：此前它们只在分析端点里，没有标准答案可对照。
        from app.core.story_metrics import analyze_story_metrics

        story = analyze_story_metrics(project)
        for f in story.get("findings") or []:
            if isinstance(f, Mapping):
                _push(f.get("code"), f.get("chapterId"), f.get("message"))
    except Exception:  # noqa: BLE001 — 故事层不可用时跳过
        pass
    return out


# ------------------------------------------------------------------ 基准入口


def run_benchmark(
    *,
    chapters: int = 48,
    seed: int = 20260409,
    detector: Optional[Callable[[VnProject], Sequence[Dict[str, Any]]]] = None,
    window_size: int = DEFAULT_WINDOW_SIZE,
    window_overlap: int = DEFAULT_WINDOW_OVERLAP,
) -> Dict[str, Any]:
    """跑一次完整基准：对"旧方案"与"分片方案"各算暴露率，并（可选）评检测器。"""
    project, ground_truth = build_synthetic_novel(chapters=chapters, seed=seed)
    legacy = legacy_plan(project)
    chunked = chunked_plan(project, size=window_size, overlap=window_overlap)
    report: Dict[str, Any] = {
        "chapters": chapters,
        "seed": seed,
        "groundTruth": ground_truth["counts"],
        "distractors": ground_truth["distractors"],
        "legacyMaxChapters": LEGACY_MAX_CHAPTERS,
        "windowSize": window_size,
        "windowOverlap": window_overlap,
        "windows": {"legacy": len(legacy), "chunked": len(chunked)},
        "exposure": {
            "legacy": evaluate_exposure(ground_truth, legacy),
            "chunked": evaluate_exposure(ground_truth, chunked),
        },
    }
    det = detector(project) if detector is not None else None
    if det is not None:
        report["detection"] = evaluate_detections(ground_truth, det)
        report["detector"] = getattr(detector, "__name__", "custom")
    return report


def format_report(report: Dict[str, Any]) -> str:
    """终端可读的一页结论。"""
    gt = report["groundTruth"]
    lines = [
        f"长程一致性基准：{report['chapters']} 章 · 埋点 {gt['total']} 条"
        f"（确定性 {gt['deterministic']} / 语义 {gt['semantic']}）"
        f" · 诱导项 {len(report['distractors'])} 条",
        "",
        f"{'方案':<12}{'可见章数':>10}{'暴露率':>10}   分桶暴露率",
    ]
    for name, label in (("legacy", f"旧方案(前{report['legacyMaxChapters']}章)"), ("chunked", "分片方案")):
        ex = report["exposure"][name]
        buckets = "  ".join(
            f"{b}:{row['recall']:.2f}" for b, row in ex["byBucket"].items()
        )
        lines.append(
            f"{label:<12}{ex['chaptersVisible']:>10}{ex['exposureRecall']:>10.2f}   {buckets}"
        )
    det = report.get("detection")
    if det:
        lines += [
            "",
            f"检测器 {report.get('detector')}: precision {det['precision']:.2f} · "
            f"recall {det['recall']:.2f} · F1 {det['f1']:.2f} "
            f"(TP {det['tp']} / FP {det['fp']} / FN {det['fn']})",
            "  分桶召回: "
            + "  ".join(f"{b}:{row['recall']:.2f}" for b, row in det["byBucket"].items()),
            f"  分类错但章节对: {len(det['misclassified'])} · "
            f"范畴外（结构性 lint）: {len(det['outOfScope'])} · "
            f"重复命中: {det['duplicateHits']}",
        ]
        if det["falsePositives"]:
            lines.append(f"  误报样例: {det['falsePositives'][:3]}")
    return "\n".join(lines)
