"""Ported from packages/core/src/writingCraft.ts

Studio-side writing "skills": compact craft constraints for VN / light-novel
scripts. Injected into the Editor Agent by task — not Cursor SKILL.md files.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.domain.types import VnProject

WritingSkillId = str
CraftMode = str  # "off" | "lite" | "full"
CraftModePreference = str  # "auto" | CraftMode


@dataclass
class WritingSkill:
    id: str
    title: str
    body: str


@dataclass
class CraftDecision:
    mode: str
    reason: str


def _s(id_: str, title: str, lines: List[str]) -> WritingSkill:
    body = f"【技能：{title}】\n" + "\n".join(f"- {l}" for l in lines)
    return WritingSkill(id=id_, title=title, body=body)


SKILLS: Dict[str, WritingSkill] = {
    "anti_exposition": _s("anti_exposition", "反设定倾倒", [
        "Characters/Bible/Variables 是作者备忘，不是对白讲义",
        "严禁履历介绍、能力清单、世界观词典进对白/旁白",
        "设定只体现在态度、用词、选择与反应；每拍最多透露剧情所需的最小信息",
    ]),
    "narrative_continuity": _s("narrative_continuity", "叙事接续", [
        "必须接【当前章末尾】的情绪、未完成动作、未答之问，禁止另开介绍课",
        "先问：上一拍发生了什么？角色此刻要什么/怕什么？",
        "时空与在场人物默认与末尾一致，除非正文写明转移",
        "末尾若是钩子/高潮，优先拧紧或兑现，勿回头补说明书",
    ]),
    "vn_stagecraft": _s("vn_stagecraft", "VN 舞台感", [
        "输出可上演脚本：短旁白 + 对白 + 必要时 scene/show，忌小说大段说明",
        "旁白做氛围/动作/感官；对白做关系与冲突",
        "禁止旁白与对白重复同一信息；禁止影评式总结代替戏",
    ]),
    "dialogue_natural": _s("dialogue_natural", "对白自然度", [
        "voice/bio 校准「怎么说」，不是「念什么设定」",
        "允许口语、打断、省略、答非所问、顾左右而言他；禁止演讲腔与念稿轮流发言",
        "角色不知之事不可全知全讲；称呼/敬慢语符合关系但勿贴标签对白",
        "推进剧情不必靠「连问三句」；可用沉默、动作、转移话题、只接半句",
    ]),
    "pacing_hook": _s("pacing_hook", "节奏与钩子", [
        "单次只写一小段节拍（数轮对白+少量旁白），留呼吸",
        "参考：反应→摩擦/推进→新信息或选择或余韵",
        "禁开场倾泻背景；禁段末作者总结；段末留问题/决定/误会/感官余韵",
        "信息点单次 ideally 一个主推进；其余用氛围与关系变化填",
    ]),
    "audience_delight": _s("audience_delight", "受众喜爱感", [
        "优先关系张力、具体细节、意外但合理的反应、一点幽默或痛感",
        "少用抽象形容词堆砌、正确无趣的说明、万能鸡汤旁白",
        "自检：删掉所有设定名词后戏是否仍好看？否→重写",
    ]),
    "anti_cliche": _s("anti_cliche", "反套话紫散文", [
        "避免 AI 套话：微微一笑、不禁、仿佛、涌上心头、命运的齿轮、空气突然安静得可怕（滥用时）",
        "少堆「美丽/悲伤/复杂」等空心词；用可见动作与具体物象代替",
        "比喻要准而省，宁缺毋滥；禁止为了华丽牺牲清晰",
    ]),
    "subtext_conflict": _s("subtext_conflict", "潜台词与冲突", [
        "好对白往往话里有话：表面话题≠真正争夺（面子、秘密、亲近、控制）",
        "每一小段至少有一处摩擦、误会、试探或拒绝，避免纯信息传递会",
        "冲突可小：抢话、回避、玩笑带刺、沉默抗拒——不一定要靠追问",
    ]),
    "voice_contrast": _s("voice_contrast", "声线区分", [
        "遮住名字也应能辨出是谁：句长、节奏、用词、礼貌度、话题偏好不同",
        "禁止全员同一种「正确书面语」；对照各角色 voice 拉开差距",
        "配角也要有辨识短句，勿工具人传声筒",
    ]),
    "info_control": _s("info_control", "信息控制", [
        "悬念靠藏与露的节奏：读者可略懂一点，角色可更懵或更知情",
        "禁止一次解开所有谜；禁止用旁白剧透尚未发生的结局感",
        "新信息最好由行动/证物/失言/环境异常带出，而非一问一答百科",
        "陌生人不会无偿把路线图讲清楚；透露要有动机或口误代价",
    ]),
    "cast_economy": _s("cast_economy", "出场经济", [
        "单拍焦点角色宜少（通常 2～3 人主说话）；其他人用反应/短句即可",
        "勿突然拉进一串只为介绍的新名字；新角色要有当场功能",
        "群众戏用声音/动作群像，勿点名点到流水账",
    ]),
    "sensory_ground": _s("sensory_ground", "感官锚定", [
        "每拍至少一处可见/可听/可触的具体细节（光、声、气味、体温、物件）",
        "细节服务情绪或伏笔，禁止风景明信片堆砌",
        "换景时用一两个感官锚点，代替「来到了某某地点」说明书",
    ]),
    "monologue_balance": _s("monologue_balance", "内心独白分寸", [
        "内心独白短而尖：一个判断、一个恐惧、一个决定；忌小论文",
        "能用表情/动作表现的，少用「我感到很…」",
        "独白不要复述刚说出口的对白",
    ]),
    "sprite_direction": _s("sprite_direction", "立绘表情指示", [
        "情绪转折处可注释 show 表情（如 show name happy），勿句句标注",
        "表情变化要有戏的理由；禁止表情与台词情绪打架",
        "无立绘设定时用短动作代替：偏头、握拳、视线躲开",
    ]),
    "choice_design": _s("choice_design", "选项设计", [
        "menu 每项后果须不同（信息/关系/路线/风险），禁假选择（三句同意）",
        "选项文案短、有人物态度，像角色会说的话，不像问卷",
        "至少一项带代价或暴露性格；标注 jump 目标要合理",
    ]),
    "romance_beat": _s("romance_beat", "恋线节拍", [
        "好感推进靠具体互动（帮忙、共情、越界一点、留下把柄），忌突然告白说明书",
        "距离感：试探→靠近→受阻→再靠近；尊重当前好感变量，勿无故飞跃",
        "羞涩/撩拨用细节与停顿，少用「心跳加速」堆叠",
    ]),
    "comedy_timing": _s("comedy_timing", "喜剧节奏", [
        "笑点靠反差、误解、毒舌、冷处理；铺垫要短，抖包袱要脆",
        "严肃戏里的幽默应出自主角性格，勿突然网感玩梗出戏",
        "笑完立刻回到处境，勿连续段子冲淡张力",
    ]),
    "atmosphere": _s("atmosphere", "氛围类型感", [
        "按作品 genre/主题保持调性：甜、悬疑、恐怖、校园等勿串味硬切",
        "恐怖靠未知与身体不适感；悬疑靠线索与不可靠叙述；甜靠温度与节奏",
        "氛围服务于人物处境，禁止为炫技空转气氛",
    ]),
    "escalation": _s("escalation", "场景内升级", [
        "一场戏内压力应有阶梯：试探→加压→爆发或强行按住",
        "禁止平铺信息交换；每一轮对白后处境应略有不同",
        "高潮后给半拍余韵或新伤口，再进入下一钩子",
    ]),
    "silence_beat": _s("silence_beat", "停顿与留白", [
        "关键处可用短旁白/省略/动作代替说话；沉默也是对白",
        "勿用长旁白填满所有空白；给玩家想象与立绘表演留空",
        "连续对白之间插入一个可见动作，避免机关枪对轰",
    ]),
    "renpy_hygiene": _s("renpy_hygiene", "Ren'Py 脚本卫生", [
        '输出可粘贴片段：旁白用引号行，对白 name "..."，选项用 menu',
        "label/jump 名称简短英文；勿发明无法落地的引擎指令",
        "一次 append 保持同一场景连贯；大换景先写 scene",
    ]),
    "player_agency": _s("player_agency", "玩家能动感", [
        "重要分歧前给可读信号；选择后世界/关系要有可感反馈",
        "勿用长独白剥夺选择意义；勿嘲讽玩家选项（除非角色人设如此且有代价）",
        "即使无 menu，也让主角的主动选择推动情节，减少纯旁观",
    ]),
    "emotion_truth": _s("emotion_truth", "情感真实", [
        "情绪要有触发物；禁无因崩溃、无因告白、无因和解",
        "大哭大喊须挣来；更多时候用压抑、转移话题、过度平静",
        "悲剧勿贩卖惨；甜宠勿无冲突的糖水流水线",
    ]),
    "foreshadow_light": _s("foreshadow_light", "伏笔轻点", [
        "伏笔用物件、口误、反常反应埋，勿旁白标注「这很重要」",
        "单次续写最多轻点一处，勿集中剧透未来线",
        "回收伏笔要让玩家「想起来」而非被作者提醒",
    ]),
    "power_dynamics": _s("power_dynamics", "关系权力", [
        "对白反映谁在主导：提问权、打断权、空间距离、知情权",
        "关系变化应改变说话方式（敬语崩塌、绰号出现、命令变请求）",
        "忌所有人永远平等礼貌座谈",
    ]),
    "scene_blocking": _s("scene_blocking", "走位进出场", [
        "进出场要有理由与方向感；人来人往服务戏，不走过场点名",
        "空间关系清晰：谁靠近、谁挡门、谁背对",
        "换景用 scene + 一句感官，勿旅程流水账",
    ]),
    "flag_subtle": _s("flag_subtle", "变量不说破", [
        "好感/flag 影响态度与选项结果，禁止对白里报数值或「好感度上升」",
        "状态变化用行为证明：多看一眼、肯帮忙、肯说谎",
        "需要改变量时，戏里先发生可感事件，再在工程里改（若用户要求）",
    ]),
    "anti_repeat": _s("anti_repeat", "反重复结构", [
        "避免又一段「问候→介绍→说明任务」模板",
        "若前文已用过某种误会/搞笑结构，换机制，勿同构复读",
        "角色口头禅可重复，情节节拍勿复制粘贴",
    ]),
    "name_economy": _s("name_economy", "称呼节制", [
        "对话中少反复喊全名；用你/喂/称呼关系更自然",
        "名字出现要有功能：提醒、强调、亲密或威胁",
        "旁白不要每句主语全名复读",
    ]),
    "cg_buildup": _s("cg_buildup", "名场面铺垫", [
        "大告白/揭秘/决裂前要有铺垫与节奏加速，忌突然降临",
        "名场面当拍聚焦：减旁支、加具体细节与选择重量",
        "事后留余震（尴尬、沉默、玩笑掩饰），勿立刻日常复原",
    ]),
    "stranger_distance": _s("stranger_distance", "陌生人距离", [
        "互不相识、且人设非热情外向时：默认惜话、戒备、礼貌疏离，禁止像老同学盘根究底",
        "一拍里同一角色主动追问 ideally ≤1 次；第二次起改用沉默、盯着别处、短应、或被环境打断",
        "对方多说了不该说的话时，反应可以是警觉/停顿，而不必立刻连环质询把地图问出来",
        "对照角色 voice：克制型用短句与省略；温和回避型用笑/岔开，而不是耐心答疑",
    ]),
    "anti_qa_pingpong": _s("anti_qa_pingpong", "反问答乒乓", [
        "严禁「问→答→再问→再答」当唯一引擎把设定/路线塞进戏",
        "坏例：你好像很熟？→停用站厅？→你听见了吗？ 连续疑问句推进",
        "好例：一问之后用动作/环境/对方主动漏嘴推进；或只应半句，信息残缺留给下拍",
        "需要揭示时，让知情者因失言、炫耀、安抚、恐惧而说，而不是被主角审讯逼出",
    ]),
    "talk_economy": _s("talk_economy", "对白经济", [
        "陌生人场景总对白轮次宜少：宁可旁白/声响/画面多一点，对白少而尖",
        "删掉不改变关系与处境的寒暄式确认句（「是吗」「这样啊」连发）",
        "每一句对白最好同时做两件事：推进处境 + 暴露态度；只做传声筒的删掉",
    ]),
    "social_temperature": _s("social_temperature", "社交温度", [
        "写对话前先定温度：冷淡/客气/试探/暧昧/敌意——整拍保持，勿无故升温成倾诉局",
        "温度升高需要触发（共伞、共敌、共同秘密、酒精、恐惧），禁止为推进剧情强行变熟",
        "热情角色可以说多；冷角色说少——不要为了「写满」让冷角色变主持访谈",
    ]),
    "otaku_literacy": _s("otaku_literacy", "二次元文化落地", [
        "写类型张力（傲娇/中二/电波/青梅）靠动作与口是心非，禁止念属性词条",
        "同人/gal 语感：对白短、潜台词密；制服袖口、铃声、贩卖机灯等物象优先于空心形容词",
        "中二要有羞耻与代价；电波要有错频喜剧或孤独，勿空喊口号",
        "忌伪二次元套话：命运的邂逅、好感度上升、萌萌哒堆砌",
    ]),
    "ln_vn_bridge": _s("ln_vn_bridge", "轻小说↔视觉小说", [
        "画面感服务可上演：可见动作 + 听得见对白；大段心声压成一句刺人独白+小动作",
        "场末钩子服务下一页/下一句：半揭误会、门响、破格称呼、秘密物件",
        "默认 Ren'Py 友好：短旁白分行对白；需要才 scene/show",
    ]),
    "de_ai_voice": _s("de_ai_voice", "去AI味", [
        "禁纠偏讲解「不是A，是B」与双否一肯叠喻梯；直接写判断与动作",
        "禁电报分工对白；少装饰破折号；少空心极短段堆叠",
        "比喻要准而省；华丽须服务角色视角，不是作者炫技",
    ]),
    "genre_heat": _s("genre_heat", "类型热度", [
        "恋爱升温要有触发场景；校园用时间表与公共空间压力",
        "悬疑信息残缺留给读者；喜剧靠错位与角色坚持，不靠尬梗三连",
    ]),
}

# Full library order (for docs / UI)
ALL_WRITING_SKILL_IDS: List[str] = list(SKILLS.keys())

PROSE_CORE: List[str] = [
    "anti_exposition",
    "narrative_continuity",
    "vn_stagecraft",
    "dialogue_natural",
    "pacing_hook",
    "audience_delight",
    "anti_cliche",
    "subtext_conflict",
    "voice_contrast",
    "info_control",
    "cast_economy",
    "sensory_ground",
    "monologue_balance",
    "sprite_direction",
    "escalation",
    "silence_beat",
    "emotion_truth",
    "power_dynamics",
    "scene_blocking",
    "flag_subtle",
    "anti_repeat",
    "name_economy",
    "atmosphere",
    "renpy_hygiene",
    "stranger_distance",
    "anti_qa_pingpong",
    "talk_economy",
    "social_temperature",
    "otaku_literacy",
    "ln_vn_bridge",
    "de_ai_voice",
    "genre_heat",
]

PROSE_EXTRA: List[str] = [
    "romance_beat",
    "comedy_timing",
    "foreshadow_light",
    "cg_buildup",
    "player_agency",
]

# Which craft skills apply to which Agent task
TASK_SKILLS: Dict[str, List[str]] = {
    "chat": [
        "anti_exposition",
        "audience_delight",
        "anti_cliche",
        "otaku_literacy",
        "de_ai_voice",
    ],
    "continue": [*PROSE_CORE, *PROSE_EXTRA],
    "scene": [*PROSE_CORE, *PROSE_EXTRA],
    "rewrite": [
        "anti_exposition",
        "vn_stagecraft",
        "dialogue_natural",
        "anti_cliche",
        "subtext_conflict",
        "voice_contrast",
        "sensory_ground",
        "monologue_balance",
        "audience_delight",
        "emotion_truth",
        "name_economy",
        "anti_repeat",
        "renpy_hygiene",
        "stranger_distance",
        "anti_qa_pingpong",
        "talk_economy",
        "social_temperature",
        "otaku_literacy",
        "ln_vn_bridge",
        "de_ai_voice",
        "genre_heat",
    ],
    "polish": [
        "dialogue_natural",
        "vn_stagecraft",
        "anti_exposition",
        "anti_cliche",
        "de_ai_voice",
        "otaku_literacy",
        "ln_vn_bridge",
        "voice_contrast",
        "silence_beat",
        "name_economy",
        "monologue_balance",
        "sensory_ground",
        "stranger_distance",
        "anti_qa_pingpong",
        "talk_economy",
        "social_temperature",
    ],
    "branch": [
        "choice_design",
        "player_agency",
        "vn_stagecraft",
        "anti_exposition",
        "subtext_conflict",
        "flag_subtle",
        "pacing_hook",
        "renpy_hygiene",
        "voice_contrast",
    ],
    "outline": [
        "pacing_hook",
        "anti_exposition",
        "audience_delight",
        "escalation",
        "info_control",
        "foreshadow_light",
        "cg_buildup",
        "cast_economy",
        "atmosphere",
        "player_agency",
    ],
    "voice": [
        "dialogue_natural",
        "voice_contrast",
        "anti_exposition",
        "anti_cliche",
        "power_dynamics",
        "name_economy",
        "subtext_conflict",
    ],
    "consistency": [
        "anti_exposition",
        "info_control",
        "flag_subtle",
        "narrative_continuity",
        "foreshadow_light",
    ],
}

SELF_CHECK = """【落笔自检】
1. 有无念设定/履历/能力清单？→删或改成行动潜台词
2. 是否紧接章末节拍？另起介绍段→重写
3. 遮住名字能否分辨说话人？全员同腔→改
4. 本拍有无摩擦/选择/关系变化？纯传信息→加冲突
5. 有无 AI 套话与空心形容词？→换成具体物象/动作
6. 段末是钩子还是作者总结？总结→改钩子
7. 是否报了好感/flag 或喊名过度？→改
8. 同一角色是否连问≥2 个疑问句在盘人？→改成惜话/沉默/环境推进
9. 陌生人是否聊得过熟、答得过全？→降温、残缺信息"""

LITE_IDS: List[str] = [
    "anti_exposition",
    "narrative_continuity",
    "vn_stagecraft",
    "dialogue_natural",
    "pacing_hook",
    "renpy_hygiene",
    "anti_cliche",
    "stranger_distance",
    "anti_qa_pingpong",
    "talk_economy",
    "de_ai_voice",
    "otaku_literacy",
]


def _chapter_plain_length(project: Optional[VnProject], chapter_id: Optional[str]) -> int:
    if not project or not project.chapters:
        return 0
    ch = next((c for c in project.chapters if c.id == chapter_id), None) or project.chapters[0]
    if not ch:
        return 0
    return len(json.dumps(ch.blocks, ensure_ascii=False, separators=(",", ":")))


def _bio_risk(project: Optional[VnProject]) -> int:
    if not project:
        return 0
    n = 0
    for c in project.characters:
        n += len(c.bio or "") + len(c.voice or "") + len(c.relationships or "")
    bible = project.bible
    if bible:
        n += len(bible.world or "") + len(bible.background or "")
    return n


def select_craft_mode(
    task: str,
    user_message: Optional[str] = None,
    project: Optional[VnProject] = None,
    chapter_id: Optional[str] = None,
    preference: Optional[str] = None,
) -> CraftDecision:
    """Decide whether to inject writing craft skills.

    Explicit user intent > settings preference > task > risk signals.
    """
    pref = preference or "auto"
    if pref in ("off", "lite", "full"):
        return CraftDecision(mode=pref, reason=f"用户固定为「{pref}」")

    msg = (user_message or "").strip()

    if re.search(r"关闭工艺|不要\s*skills?|不用工艺|关掉skills?|无工艺|别套工艺", msg, re.IGNORECASE):
        return CraftDecision(mode="off", reason="用户要求关闭工艺")
    if re.search(r"强制工艺|全套工艺|防倾倒|严格按skills?|用足工艺", msg, re.IGNORECASE):
        return CraftDecision(mode="full", reason="用户要求加强工艺")
    if re.search(r"短拍|写短|干脆|少修饰|自然点|别太文艺|紧凑|少技巧|朴素", msg, re.IGNORECASE):
        return CraftDecision(mode="lite", reason="用户要短/自然，用轻量工艺")

    if task == "chat":
        return CraftDecision(mode="off", reason="自由讨论：不注入工艺，保持松弛")
    if task in ("consistency", "outline", "voice"):
        return CraftDecision(mode="lite", reason=f"任务「{task}」宜轻量约束")
    if task in ("polish", "branch"):
        return CraftDecision(mode="lite", reason=f"任务「{task}」：去套话/选项，轻量即可")

    bio = _bio_risk(project)
    ch_len = _chapter_plain_length(project, chapter_id)
    if bio >= 400 or ch_len < 800:
        return CraftDecision(
            mode="full",
            reason=(
                "人设/设定较厚，倾倒风险高 → 全套工艺"
                if bio >= 400
                else "当前章较短/偏开头，倾倒风险高 → 全套工艺"
            ),
        )
    if ch_len > 4000 and re.search(r"续写|往下写", msg) and not re.search(r"写一场戏|完整", msg):
        return CraftDecision(mode="lite", reason="章内已有较密正文，续写偏短拍 → 轻量工艺更利落")
    if task == "scene":
        return CraftDecision(mode="full", reason="写一场戏需要舞台与节奏全套")
    if task == "rewrite":
        return CraftDecision(mode="full", reason="改写需压倾倒与提升对白")
    return CraftDecision(mode="full", reason="默认续写启用全套工艺")


def get_writing_skill(id_: str) -> WritingSkill:
    return SKILLS[id_]


def list_writing_skills() -> List[WritingSkill]:
    return [SKILLS[id_] for id_ in ALL_WRITING_SKILL_IDS]


def skills_for_task(task: str, mode: str = "full") -> List[WritingSkill]:
    if mode == "off":
        return []
    ids = TASK_SKILLS.get(task, [])
    seen: set = set()
    out: List[WritingSkill] = []
    for id_ in ids:
        if mode == "lite" and id_ not in LITE_IDS:
            continue
        if id_ in seen:
            continue
        seen.add(id_)
        out.append(SKILLS[id_])
    if mode == "lite":
        return out[:8]
    return out


PRIORITY_IDS: List[str] = [
    "anti_exposition",
    "de_ai_voice",
    "otaku_literacy",
    "stranger_distance",
    "anti_qa_pingpong",
    "talk_economy",
    "social_temperature",
    "narrative_continuity",
    "vn_stagecraft",
    "dialogue_natural",
    "pacing_hook",
    "subtext_conflict",
    "anti_cliche",
    "ln_vn_bridge",
    "renpy_hygiene",
    "voice_contrast",
    "sensory_ground",
]


def build_writing_craft_prompt(task: str, mode: str = "full") -> str:
    """Build craft prompt for the selected mode."""
    if mode == "off":
        return "—— 写作工艺：本轮关闭（追求短拍自然；仍禁止把人设条目念进对白）——"
    skills = skills_for_task(task, mode)
    if not skills:
        return ""
    need_check = task in ("continue", "scene", "rewrite", "polish", "branch")

    if mode == "lite":
        parts = [
            f"—— 写作工艺 Skills（轻量×{len(skills)}：利落优先，防倾倒仍生效）——",
            "\n\n".join(s.body for s in skills),
            "【轻量自检】有无念设定？是否接章末？段末是钩子还是总结？" if need_check else "",
        ]
        return "\n\n".join(p for p in parts if p)

    priority = [s for s in skills if s.id in PRIORITY_IDS]
    rest = [s for s in skills if s.id not in PRIORITY_IDS]
    primary = [s.body for s in (priority if priority else skills[:8])]
    checklist = (
        f"【亦须遵守（简表）】{'、'.join(s.title for s in rest)}。冲突时以反设定倾倒与叙事接续为准。"
        if rest
        else ""
    )

    parts = [
        f"—— 写作工艺 Skills（详述 {len(primary)} + 简表 {len(rest)}；优先级高于「把上下文写全」）——",
        "\n\n".join(primary),
        checklist,
        SELF_CHECK if need_check else "",
    ]
    text = "\n\n".join(p for p in parts if p)
    try:
        from app.core.pipeline.style_skill import load_style_skill

        text += "\n\n" + load_style_skill().prompt_block(max_chars=2000)
    except Exception:
        pass
    return text


def writing_skill_titles(task: str, mode: str = "full") -> List[str]:
    return [s.title for s in skills_for_task(task, mode)]
