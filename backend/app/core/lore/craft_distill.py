"""Distill Moegirl extracts into VN/LN craft cards (not wiki dumps).

Seeded curated cards cover common tropes offline; live lookup fills gaps.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

ATTRIBUTION = (
    "参考萌娘百科条目（通常 CC BY-NC-SA 3.0）：仅作术语/套路启发，"
    "禁止把百科正文粘进剧本；写表现勿念标签。"
)

# Curated offline seeds — do/dont tuned for visual novel & light novel
SEED_CARDS: List[Dict[str, Any]] = [
    {
        "term": "傲娇",
        "aliases": ["tsundere", "ツンデレ"],
        "kind": "moe_attribute",
        "definition_short": "表面强硬别扭、内心在意对方；反差靠行动兑现，不靠自报属性。",
        "do": [
            "先拒绝/毒舌，再用行动补救（送伞、留门、多做一份便当）",
            "破防用短句与停顿，不要长篇告白说明书",
            "让旁人（或玩家）读出反差，角色本人可死不承认",
        ],
        "dont": [
            "对白直接说「我才不是傲娇」当笑点连发",
            "无触发就突然变软、变熟",
            "把傲娇写成单纯骂人",
        ],
        "vn_beats": [
            "雨天：嘴上让你自己走，却把伞塞过来",
            "值日：抱怨麻烦，却把你那份也做完",
            "选项后：选关心她 → 羞恼跳开；选玩笑 → 真生气留钩子",
        ],
        "source_title": "傲娇",
        "source_url": "https://zh.moegirl.org.cn/傲娇",
    },
    {
        "term": "三无",
        "aliases": ["クール", "无口", "无表情"],
        "kind": "moe_attribute",
        "definition_short": "少言、少表情、少情绪外放；魅力来自微反应与行动密度。",
        "do": [
            "对白极短；用点头、视线、物件传递态度",
            "情绪破例时只放大一处（多说半句 / 眼神停顿）",
            "让其他角色误读她的沉默，制造喜剧或误会",
        ],
        "dont": [
            "写成长篇独白解释自己「其实很在意」",
            "突然变成话痨主持访谈",
            "用旁白不断标注「她毫无表情」",
        ],
        "vn_beats": [
            "只回「……嗯。」却把热水放到你手边",
            "战斗后唯一多余的话是角色名的轻声呼唤",
            "menu：逼问 → 更沉默；并肩沉默 → 她主动多走半步",
        ],
        "source_title": "三无",
        "source_url": "https://zh.moegirl.org.cn/三无",
    },
    {
        "term": "世界系",
        "aliases": ["セカイ系"],
        "kind": "genre",
        "definition_short": "两人（或小圈）关系与「世界存亡」被叙事强行同构；重点在关系张力而非宏大战争场面。",
        "do": [
            "把危机压在日常细节上（手机未读、教室空位、同一首歌）",
            "信息残缺：角色不知全局，玩家略知一二",
            "选择影响「关系 ↔ 世界」的隐喻兑现，而非兵棋推演",
        ],
        "dont": [
            "写成普通异能战斗热血番却贴世界系标签",
            "用旁白直接解释世界系定义",
            "无限升级战力而丢掉两人关系轴",
        ],
        "vn_beats": [
            "她消失的那天，自动贩卖机仍吐出熟悉的饮料",
            "拯救世界的关键道具是一封未寄出的信",
            "选项：追问真相 / 先抓住她的手——后果不同",
        ],
        "source_title": "世界系",
        "source_url": "https://zh.moegirl.org.cn/世界系",
    },
    {
        "term": "空气系",
        "aliases": ["空気系"],
        "kind": "genre",
        "definition_short": "弱情节、强氛围的日常；冲突是温度与节奏，不是阴谋主线。",
        "do": [
            "用季节、光线、社团室气味、放学铃声做锚点",
            "小摩擦即可：抢同一把伞、值日表写错名",
            "对白留白多，让沉默也可爱/可痛",
        ],
        "dont": [
            "硬塞谋杀/拯救世界破坏调性",
            "用网感尬梗代替生活质感",
            "每场都高潮，毁掉「空气」",
        ],
        "vn_beats": [
            "天台门锁着——两人只好坐楼梯间喝同一瓶汽水",
            "她把刘海拨开又拨回，整场戏只完成这一件事",
            "BGM/环境音提示比台词更多情绪",
        ],
        "source_title": "空气系",
        "source_url": "https://zh.moegirl.org.cn/空气系",
    },
    {
        "term": "异世界转生",
        "aliases": ["isekai", "穿越"],
        "kind": "trope",
        "definition_short": "带着前世记忆进入异世界；新鲜感应来自文化错位与规则学习，而非金手指说明书。",
        "do": [
            "用失败的生活技能制造喜剧与代价",
            "规则通过受伤/交易/禁忌场景揭示",
            "前世记忆影响选择，但不要每句都回忆杀",
        ],
        "dont": [
            "开场三千字能力表与等级系统宣讲",
            "无代价的全知外挂",
            "把原世界人际关系全部清空却毫无情绪余波",
        ],
        "vn_beats": [
            "第一次说话用了现代梗，对方完全听不懂",
            "想买面包却触发某种贵族礼仪陷阱",
            "menu：暴露前世知识换捷径 / 装不懂保命",
        ],
        "source_title": "异世界",
        "source_url": "https://zh.moegirl.org.cn/异世界",
    },
    {
        "term": "死亡游戏",
        "aliases": ["survival game", "杀人游戏"],
        "kind": "trope",
        "definition_short": "规则化杀戮/淘汰竞赛；张力来自规则漏洞、结盟背叛与道德选择。",
        "do": [
            "规则要可被玩家记住：边界、惩罚、胜利条件",
            "信息战：谁说谎、谁试探、谁牺牲",
            "VN 选项承担道德重量，不只是「打/跑」",
        ],
        "dont": [
            "无规则的随机虐杀堆尸",
            "主角永远被剧情护体",
            "用旁白提前剧透凶手",
        ],
        "vn_beats": [
            "广播宣读新规则——旧盟友的表情先于台词变化",
            "投票前夜：给不给对方救命道具",
            "发现规则漏洞却要用同伴当诱饵",
        ],
        "source_title": "死亡游戏",
        "source_url": "https://zh.moegirl.org.cn/死亡游戏",
    },
    {
        "term": "青梅竹马",
        "aliases": ["osananajimi", "幼驯染"],
        "kind": "moe_attribute",
        "definition_short": "长期共同成长的亲近；张力在「太熟」与「不敢越界」之间。",
        "do": [
            "用共享回忆物件（旧书包、秘密基地）触发",
            "熟能生巧的默契 + 突然的陌生感",
            "第三者介入时写嫉妒的具体小动作",
        ],
        "dont": [
            "只会喊「我们从小一起长大啊」",
            "无铺垫直球告白冲掉日常质感",
            "把青梅写成免费保姆工具人",
        ],
        "vn_beats": [
            "她记得你过敏，却假装是顺手",
            "重逢：称呼从小名改回姓氏",
            "选项：提起旧事 / 装作忘记——关系温度分叉",
        ],
        "source_title": "青梅竹马",
        "source_url": "https://zh.moegirl.org.cn/青梅竹马",
    },
    {
        "term": "中二病",
        "aliases": ["chuunibyou", "中二"],
        "kind": "moe_attribute",
        "definition_short": "青春期自我戏剧化；好笑要有羞耻与被看见的代价，不能只喊口号。",
        "do": [
            "中二台词配上周围人的反应与社会压力",
            "认真对待她的「设定」，偶发真心时刻更痛",
            "破功用生活细节（妈妈来学校）",
        ],
        "dont": [
            "纯嘲讽羞辱主角取乐",
            "无人物弧光的空喊黑暗之力",
            "全员一起中二导致没有对照",
        ],
        "vn_beats": [
            "天台「结界」其实是禁止翻越的栏杆",
            "战斗姿态被风吹乱刘海——她先尴尬",
            "选项：配合演出 / 当场拆穿",
        ],
        "source_title": "中二病",
        "source_url": "https://zh.moegirl.org.cn/中二病",
    },
    {
        "term": "病娇",
        "aliases": ["yandere", "ヤンデレ"],
        "kind": "moe_attribute",
        "definition_short": "爱意扭曲为占有/伤害；恐怖与甜蜜同轴，关键在「爱」的具体行为而非血腥堆砌。",
        "do": [
            "先铺正常亲昵，再让边界一点点越线",
            "用日记、监视痕迹、过度关心物件暗示",
            "给玩家道德两难：揭穿会毁她，沉默会毁别人",
        ],
        "dont": [
            "开场就刀人无铺垫",
            "把病娇写成无动机的杀人机器",
            "用旁白直接标注「她是病娇」",
        ],
        "vn_beats": [
            "她记得你说过一次的口味，却忘了问过你是否方便",
            "选项：收下「护身符」/ 拒绝——后续监视强度不同",
            "发现她删了你通讯录里某个人的痕迹",
        ],
        "source_title": "病娇",
        "source_url": "https://zh.moegirl.org.cn/病娇",
    },
    {
        "term": "学园",
        "aliases": ["校园", "スクール"],
        "kind": "genre",
        "definition_short": "校园时空容器：铃声、教室、社团与学年节奏提供冲突舞台。",
        "do": [
            "用作息与公共空间制造偶遇与错过",
            "小事（值日、考试、文化祭）扛大情绪",
            "校园规则限制选择，逼出创意解法",
        ],
        "dont": [
            "只有教室背景板，没有校园生活肌理",
            "无视学年/假期时间线乱跳",
            "把所有冲突都搬出校园导致类型空心",
        ],
        "vn_beats": [
            "放学铃响，走廊人潮把两人冲开又撞回",
            "屋顶门锁着——只能去无人的音乐室",
            "文化祭筹备把「告白时机」不断推迟",
        ],
        "source_title": "学园",
        "source_url": "https://zh.moegirl.org.cn/学园",
    },
]


def seed_by_term(term: str) -> Optional[Dict[str, Any]]:
    key = _norm(term)
    for card in SEED_CARDS:
        if _norm(card["term"]) == key:
            return _with_meta(card)
        for a in card.get("aliases") or []:
            if _norm(a) == key:
                return _with_meta(card)
    return None


def match_seeds_in_text(text: str, limit: int = 5) -> List[Dict[str, Any]]:
    t = text or ""
    found: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for card in SEED_CARDS:
        names = [card["term"], *(card.get("aliases") or [])]
        if any(n and n in t for n in names):
            k = _norm(card["term"])
            if k in seen:
                continue
            seen.add(k)
            found.append(_with_meta(card))
            if len(found) >= limit:
                break
    return found


def distill_from_extract(
    term: str,
    extract: str,
    *,
    source_title: str,
    source_url: str,
    kind: str = "term",
) -> Dict[str, Any]:
    """Heuristic distill: short definition + VN-oriented do/dont scaffolds."""
    plain = re.sub(r"\s+", " ", (extract or "").strip())
    definition = plain[:180] + ("…" if len(plain) > 180 else "")
    # Light keyword hints for kind
    kind_guess = kind
    if any(x in term for x in ("系", "风格")):
        kind_guess = "genre"
    elif any(x in plain for x in ("转生", "穿越", "游戏", "设定")):
        kind_guess = "trope"
    elif any(x in plain for x in ("属性", "角色", "性格")):
        kind_guess = "moe_attribute"

    return _with_meta(
        {
            "term": term,
            "aliases": [],
            "kind": kind_guess,
            "definition_short": definition or f"「{term}」的二次元用语（见萌百）。",
            "do": [
                "把词条含义落成场景动作与关系张力",
                "用 1～2 个可上演节拍表达，而非解释定义",
                "让角色不知「标签」，只知处境与心情",
            ],
            "dont": [
                "对白或旁白直接念百科定义",
                "堆砌同义词标签冒充人物弧光",
                "照搬条目中的作品剧透当自己的情节",
            ],
            "vn_beats": [
                f"用一个日常物件触发「{term}」相关的态度反差",
                "选项分叉：迎合该类型期待 / 故意颠覆期待",
            ],
            "source_title": source_title or term,
            "source_url": source_url,
            "raw_extract": plain[:800],
        }
    )


def format_cards_for_agent(cards: List[Dict[str, Any]], max_chars: int = 2800) -> str:
    if not cards:
        return ""
    parts = [
        "## ACG 术语工艺卡（萌百启发 · 禁止照抄百科进正文）",
        ATTRIBUTION,
        "",
    ]
    for c in cards:
        block = [
            f"### {c.get('term')}（{c.get('kind', 'term')}）",
            c.get("definition_short") or "",
            "写的时候要做：",
            *[f"- {x}" for x in (c.get("do") or [])[:4]],
            "不要：",
            *[f"- {x}" for x in (c.get("dont") or [])[:4]],
            "可上演节拍：",
            *[f"- {x}" for x in (c.get("vn_beats") or [])[:3]],
        ]
        if c.get("source_url"):
            block.append(f"来源：{c.get('source_title') or c.get('term')} · {c['source_url']}")
        parts.append("\n".join(block))
        parts.append("")
    text = "\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…(工艺卡截断)"
    return text


def checklist_inspire(kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Character/world checklist from seeds."""
    want = set(kinds or ["moe_attribute", "genre", "trope"])
    return [_with_meta(c) for c in SEED_CARDS if c.get("kind") in want]


def _with_meta(card: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(card)
    out.setdefault("attribution", ATTRIBUTION)
    out.setdefault("license_note", "CC BY-NC-SA 3.0（以萌娘百科页面标注为准）；自用精炼，勿商业整页复用。")
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())
