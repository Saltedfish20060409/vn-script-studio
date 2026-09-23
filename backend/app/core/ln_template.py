"""轻小说起步工程模板（纯函数：不联网、不调模型、不碰数据库）。

为什么要有它：`core/demo.py` 的《雨夜车站》是**视觉小说**的演示——四章全由 script block
组成，带 label / menu / jump，适合拆开看结构。轻小说作者第一次进来要的是另一种东西：
一卷三章、每章一段能接着往下写的正文、章末留钩子，角色口吻与设定先立住，节拍表摆在
那里。这份模板给的就是这个起点。

所有字段都取自 `app.domain.types`（VnProject / Volume / SceneChapter / Character /
VoiceCorpusSample / LoreEntry / LoreLink），没有自造字段。三处"预置"是刻意的，也都用
真实字段承载：

1. ``bible.outline``：第一卷的四个节拍，`core.longform_memory.parse_outline_beats`
   会把它当成检索用的大纲节拍；
2. ``harnessRuns[0].beatSheet``：节拍表骨架。节拍表在工程里的**唯一**归宿就是这里——
   `api/v1/projects.py` 的 story-metrics 与 `core/pipeline/run_history.py` 都从
   ``run["beatSheet"]`` 读，放在别处不会被任何功能看到。这条记录带
   ``templateSeed=True``，标明它不是一次真实运行，而是模板预置的骨架；
3. ``writingLedger.foreshadows``：三章的章末钩子，预置成「未回收」。账本的钩子自动提取
   只读 script block（见 `core/pipeline/ledger.py`），**纯正文写作的章节不会自动进账本**
   ——所以模板把这一卷的三条钩子直接放进去，作者一进来就能在「账本 / 摘要」看到伏笔
   这一栏长什么样，续写时也会被提示回收。

三章正文都是 `SceneChapter.prose`（自然语言正文，写作统计优先数它），末尾一段就是
章末钩子；钩子文本由 `_hook_of` 从正文末段取，不另写一份，避免两处漂移。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.domain.types import VnProject

from .project import normalize_project, uid

#: 模板只建一卷；章节靠 ``SceneChapter.volumeId`` 归属（见 domain/types.py 的 Volume）。
LN_VOLUME_ID = "vol-1"
LN_CHAPTER_IDS: tuple[str, ...] = ("ch1", "ch2", "ch3")
LN_DEFAULT_TITLE = "（未命名轻小说）"

LN_LOGLINE = "转学第三天，我听见了停了三年的大钟——钟声里有人喊救命，而它喊的是我的名字。"
LN_GENRE = "轻小说 / 校园悬疑"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- 节拍表


def build_ln_beat_sheet() -> Dict[str, Any]:
    """第一卷的节拍表骨架：一个目标 + 三个节拍（外加触发物与声明的情感弧线）。

    形状与 `core/pipeline/orchestrator.py` 产出的 plan 阶段节拍表一致：
    ``goal / beats[{name, action}] / triggers / emotionStart / emotionEnd``。
    ``emotionStart`` / ``emotionEnd`` 里的情绪词刻意只用
    `core/story_metrics.EMOTION_ORDER` 认得的词——它认不出就不猜，写自由词等于这条
    「与节拍表声明的对账」永远不出结果。
    """
    return {
        "goal": "让读者在第三章结束时确认：钟声真的在挑人，而雨宫澪已经被记在名单上。",
        "beats": [
            {
                "name": "开场钩",
                "action": (
                    "转学第一天，澪在失物招领处听见钟声里的一声「救命」，"
                    "被同班的值日生当场认出「你也听见了」。"
                ),
            },
            {
                "name": "试探与反证",
                "action": (
                    "灯用失物登记本证明编号 H-107 的登记日期早于澪来到这个镇子的时间，"
                    "而登记人一栏写的是她的名字。"
                ),
            },
            {
                "name": "代价落地",
                "action": (
                    "第七个抽屉里出现澪自己的东西；九条莲在钟楼门前说出「换班」，"
                    "本卷收在门被推开的一刻。"
                ),
            },
        ],
        "triggers": ["钟声", "失物招领处", "第七个抽屉", "换班", "H-107"],
        "emotionStart": {"雨宫澪": "平静", "篠原灯": "平静"},
        "emotionEnd": {"雨宫澪": "担忧", "篠原灯": "疑惑"},
    }


# --------------------------------------------------------------------------- 设定条目


def build_ln_world_entries() -> List[Dict[str, Any]]:
    """世界设定 4 条（`LoreEntry`，``tags`` 带「世界设定」）。

    用设定条目而不是往 ``bible.world`` 里堆：那几格有长度上限，而且命中不了"按需取一条"。
    条目带 ``keywords``（提问里出现就命中）与 ``links``（连到角色 / 章节，检索会顺带走一步）。
    """
    return [
        {
            "id": "lore-town",
            "title": "雨见町与雨见高中",
            "body": (
                "临海小镇，一年有两百天在下雨。雨见高中的钟楼在三年前的台风夜停摆："
                "钟锤被拆走了，钟还挂在那里。镇上人默认——听不见钟声才是正常的。"
            ),
            "tags": ["世界设定"],
            "keywords": ["雨见町", "雨见高中", "钟楼", "小镇"],
            "links": [{"toType": "chapter", "toId": "ch1", "note": "钟声第一次响在第一章"}],
        },
        {
            "id": "lore-second-bell",
            "title": "第二次钟声的规矩",
            "body": (
                "钟只在一个人的名字被人记住的时候响第二遍。听见第二遍的人会成为记录者："
                "他记住的名字，会被所有人慢慢忘记；他忘了的名字，会重新回到那个人身上。"
            ),
            "tags": ["世界设定"],
            "keywords": ["第二次钟声", "钟声", "记名字"],
            # 「绝不能写错」的那一条：钉住之后每轮都会带上，不受检索影响
            "pinned": True,
            "priority": 10,
            "links": [
                {"toType": "character", "toId": "mio", "note": "澪是听见第二遍钟的人"}
            ],
        },
        {
            "id": "lore-lost-and-found",
            "title": "失物招领处的登记本",
            "body": (
                "所有被捡到的东西都要登记：日期、拾获地点、编号，以及拾获人的名字。"
                "规矩是「登记过的失物不还给原主，只交给下一个人」——所以登记本其实是一份"
                "交接记录，翻它等于翻这三年谁把什么交了出去。"
            ),
            "tags": ["世界设定"],
            "keywords": ["失物招领处", "登记本", "失物"],
            "links": [
                {"toType": "character", "toId": "akari", "note": "灯是失物招领处的值日生"}
            ],
        },
        {
            "id": "lore-typhoon-night",
            "title": "三年前的台风夜",
            "body": (
                "台风过境那晚，学生会长在钟楼值最后一班，天亮以后就没人再见过她。"
                "校方记录写的是「转学」，但那一届的毕业照上，她站的位置空着，"
                "旁边的九条莲替她把校服领子理好。"
            ),
            "tags": ["世界设定"],
            "keywords": ["三年前", "台风夜", "学生会长", "失踪"],
            "links": [
                {"toType": "character", "toId": "ren", "note": "莲在场"},
                {"toType": "chapter", "toId": "ch3", "note": "第三章说出那晚的另一半"},
            ],
        },
    ]


def build_ln_glossary() -> List[Dict[str, Any]]:
    """术语表 3 条（同样是 `LoreEntry`，``tags`` 带「术语」）。

    为什么术语也用设定条目：条目自带触发词，问答与续写时只有命中的那几条会进上下文
    ——专有名词正是最该"按需取一条"的一类设定，写成另一个字段反而检索不到。
    """
    return [
        {
            "id": "glossary-handover",
            "title": "换班",
            "body": (
                "钟楼值守的说法：一个人被钟记住之后，必须有人替他把名字念回来，"
                "这个动作叫换班。字面意思是「换一个人站上钟楼」。"
            ),
            "tags": ["术语"],
            "keywords": ["换班"],
        },
        {
            "id": "glossary-keeper",
            "title": "记录者",
            "body": (
                "本作术语：听得见第二遍钟声、并被钟要求记住别人名字的人。"
                "记录者每记住一个名字，自己就少被一个人记得。"
            ),
            "tags": ["术语"],
            "keywords": ["记录者"],
        },
        {
            "id": "glossary-h-number",
            "title": "H 编号",
            "body": (
                "失物的编号格式：H 加三位流水号，H 是「拾」的旧写法。"
                "同一件东西如果被登记两次，会分到两个号——第二个号代表它被交出去过一次。"
            ),
            "tags": ["术语"],
            "keywords": ["H编号", "编号格式", "H-"],
        },
    ]


# --------------------------------------------------------------------------- 角色


def _sample(sample_id: str, label: str, text: str, note: str) -> Dict[str, Any]:
    """一条口吻示例（``VoiceCorpusSample``）：角色工坊的示例库、合成口吻说明都用它。"""
    return {
        "id": sample_id,
        "scenario": f"custom:{label}",
        "scenarioLabel": label,
        "source": "manual",
        "lines": [{"speaker": "self", "text": text}],
        "userNote": note,
        "createdAt": _now_iso(),
    }


def _characters() -> List[Dict[str, Any]]:
    """三位主要角色：显示名 / 口吻 / 简介 / 关系，各带一条台词示例。"""
    return [
        {
            "id": "mio",
            "defineName": "mio",
            "displayName": "雨宫澪",
            "color": "#7eb8da",
            "voice": (
                "第一人称，短句。先观察再开口，遇到怪事先找证据；被追问时会绕开自己的感受，"
                "只回答事实，句尾很少用感叹号。"
            ),
            "bio": "高一转学生，从东京搬到雨见町第三天。听觉异常敏锐，讨厌被当成特殊的人。",
            "relationships": "与篠原灯同班，被她一眼认出听得见钟声；对九条莲的客气保持警惕。",
            "aliases": ["澪", "雨宫"],
            "voiceCorpus": [
                _sample(
                    "vc-mio-1",
                    "被灯追问",
                    "我没说我听见了。我说的是——钟响的时候，你的笔停了。",
                    "模板预置示例：主角不承认感受，只交事实。",
                )
            ],
        },
        {
            "id": "akari",
            "defineName": "akari",
            "displayName": "篠原灯",
            "color": "#c4a574",
            "voice": (
                "话少，多用陈述句直接给结论，不解释理由；被逼急了改用反问，"
                "越在意的事说得越平。"
            ),
            "bio": "高二，失物招领处值日生。登记本上记着过去三年所有没人认领的东西。",
            "relationships": "知道钟楼的旧事，也知道 H-107 的登记人是谁；对澪既戒备又有期待。",
            "aliases": ["灯", "篠原"],
            "voiceCorpus": [
                _sample(
                    "vc-akari-1",
                    "说明规矩",
                    "登记过的失物不还给原主，只交给下一个人。这是规矩——不是我不还。",
                    "模板预置示例：灯用陈述句给结论，不解释动机。",
                )
            ],
        },
        {
            "id": "ren",
            "defineName": "ren",
            "displayName": "九条莲",
            "color": "#b85c38",
            "voice": (
                "礼貌得过分，句尾常带「呢」「吧」；越关键的地方越含糊，"
                "习惯把问题换成一个更温和的问题。"
            ),
            "bio": "高三，学生会副会长。三年前台风夜之后，钟楼的钥匙在他手里。",
            "relationships": "与三年前失踪的学生会长有旧；对澪的熟悉程度超出第一次见面的人。",
            "aliases": ["莲", "九条", "副会长"],
            "voiceCorpus": [
                _sample(
                    "vc-ren-1",
                    "把问题换掉",
                    "你想问的不是钟吧？先回答我一个问题——你为什么会听见呢。",
                    "模板预置示例：莲从不正面回答，只把问题换一个更温和的。",
                )
            ],
        },
    ]


# --------------------------------------------------------------------------- 章节


def _hook_of(chapter: Dict[str, Any]) -> str:
    """章末钩子 = 正文最后一段。账本预置的那条就从这里取，两处不会写歪。"""
    paras = [p.strip() for p in str(chapter.get("prose") or "").split("\n") if p.strip()]
    return paras[-1] if paras else ""


def _chapters() -> List[Dict[str, Any]]:
    """第一卷三章：每章一句 synopsis + 2–4 段正文，末段就是章末钩子。"""
    return [
        {
            "id": LN_CHAPTER_IDS[0],
            "title": "迟到三天的钟声",
            "volumeId": LN_VOLUME_ID,
            "synopsis": (
                "转学第一天，澪在失物招领处听见钟声里夹着的一声「救命」；"
                "值日的篠原灯听懂了她没说出口的话。"
            ),
            "prose": (
                "雨见高中的钟楼早就停了——至少在所有人都这么说。我转学来的第一天，"
                "站在告示栏前看分班表，直到钟声从头顶落下来。它只响了一声，"
                "却像有人隔着水喊我的名字。\n\n"
                "我告诉自己那是耳鸣。我从东京搬到这个镇子才三天，除了班主任，"
                "没有人知道我叫雨宫澪。可第二节课下课，我又听见了一次："
                "夹在钟声里的不是我的名字，而是一声很轻的「救命」。\n\n"
                "失物招领处在一楼最里面，门牌歪着。我推门进去的时候钟声正好停下，"
                "屋里只有翻纸的声音。值日的女生从登记本上抬起头，看了我三秒。\n\n"
                "「你也听见了。」她说。不是问句。"
            ),
        },
        {
            "id": LN_CHAPTER_IDS[1],
            "title": "第七个抽屉",
            "volumeId": LN_VOLUME_ID,
            "synopsis": (
                "为了核对那个声音，澪翻开失物登记本：编号 H-107 的登记日期，"
                "比她搬来这个镇子还早两天。"
            ),
            "prose": (
                "「登记过的失物不还给原主。」篠原灯把登记本推过来，"
                "「只交给下一个人。这是规矩，不是我不还。」\n\n"
                "本子是旧的，纸角发软。她翻到三天前那一页指给我看——H-107，"
                "拾获地点写着「钟楼」，拾获人一栏是我的名字，笔迹却不是我写的。\n\n"
                "「三天前我还在东京。」我说。\n\n"
                "「我知道。」她把本子合上，「所以我才在这里等。第七个抽屉一直锁不上。」"
            ),
        },
        {
            "id": LN_CHAPTER_IDS[2],
            "title": "钟楼上的另一个我",
            "volumeId": LN_VOLUME_ID,
            "synopsis": (
                "钟楼的门本来就没有锁。里面等着的人长着澪的脸，说出的却是三年前那一晚"
                "没说完的话。"
            ),
            "prose": (
                "九条莲站在钟楼门口，校服扣得整整齐齐，语气礼貌得过分："
                "「你想问的不是钟吧？先回答我一个问题——你为什么听得见呢。」\n\n"
                "我没有回答。门本来就没有锁，一推就开。\n\n"
                "楼梯很窄，雨声从四面漏进来。钟挂在顶层，钟锤不见了，"
                "钟口下站着一个人——穿着和我一样的校服，转过身来，长着我的脸。\n\n"
                "「你终于来了。」她说，「换班，一个人换一个人。"
                "你听见的第一声，是上一班留下来的。」"
            ),
        },
    ]


# --------------------------------------------------------------------------- 装配


def _seed_ledger(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """预置账本：三章的章末钩子记成「未回收」。

    键名与 `core/pipeline/ledger.py` 的 ``empty_ledger`` 一致，值也走同一套字段
    （``hook`` / ``plantedChapter`` / ``status`` / ``paidInChapter``），所以
    `foreshadow_report` 能直接算出"埋在哪一章、埋了几章"。
    """
    return {
        "chapterFacts": [],
        "characterStates": [],
        "foreshadows": [
            {
                "id": f"fs-{ch['id']}",
                "hook": _hook_of(ch),
                "plantedChapter": ch["id"],
                "status": "open",
                "note": "模板预置：本章章末钩子（还没回收）",
                "paidInChapter": None,
                "updatedAt": _now_iso(),
            }
            for ch in chapters
        ],
        "events": [],
        "updatedAt": _now_iso(),
    }


def _seed_plan_run() -> Dict[str, Any]:
    """一条 plan 记录，带第一卷的节拍表骨架。

    记录形状照着 `core/pipeline/run_history.py` 的 summary 写，这样界面与
    story-metrics 读到它时不会缺字段；``templateSeed`` 说明它是模板预置而非真实运行。
    """
    return {
        "id": "hr_ln_template_plan",
        "at": _now_iso(),
        "kind": "plan",
        "chapterId": LN_CHAPTER_IDS[0],
        "instruction": "模板预置：第一卷节拍表骨架（可改，也可以让审稿 Agent 重新规划）",
        "gatePass": True,
        "errorCount": 0,
        "warnCount": 0,
        "beatMode": "seed",
        "stages": ["plan"],
        "reviseRounds": 0,
        "applied": False,
        "blockers": [],
        "templateSeed": True,
        "beatSheet": build_ln_beat_sheet(),
    }


def build_ln_template_project(title: str = LN_DEFAULT_TITLE) -> VnProject:
    """构造一份轻小说起步工程（纯函数，可反复调用，每次都返回全新对象）。

    返回的 `VnProject` 已经过 `normalize_project`，可以直接走保存链路
    （``normalize_project`` 会把 ``volumeId`` 指向不存在的卷时清空，所以卷与章节
    必须一致地建出来）。
    """
    chapters = _chapters()
    clean_title = (title or "").strip() or LN_DEFAULT_TITLE
    return normalize_project(
        {
            "id": uid("proj"),
            "title": clean_title,
            "logline": LN_LOGLINE,
            "genre": LN_GENRE,
            "bible": {
                "world": (
                    "临海的雨见町，一年有两百天在下雨。雨见高中的钟楼在三年前的台风夜停摆："
                    "钟锤被拆走了，钟还挂在那里。镇上人默认，听不见钟声才是正常的。"
                ),
                "background": (
                    "雨宫澪从东京转学来雨见町的第三天，在失物招领处听见钟声里夹着一声"
                    "「救命」。同班的值日生篠原灯当场认出她听得见；学生会副会长九条莲认得"
                    "那口钟的旧事，却只肯把一个更温和的问题还给她。"
                ),
                "outline": (
                    "1. 转学第一天：钟声里的一声「救命」，被同班的篠原灯当场认出\n"
                    "2. 登记本与编号 H-107：登记日期比澪来到这个镇子还早\n"
                    "3. 第七个抽屉：里面是澪自己的东西\n"
                    "4. 钟楼的门没有锁：等她的人长着她的脸，说的是「换班」"
                ),
                "themes": "被记住与被忘记；「听见」是一种责任；小镇对异常的共同沉默",
                "notes": (
                    "写作口径：第一人称、短句，对白密集（每段至少一句台词），章末必留钩子。"
                    "设定条目里「第二次钟声的规矩」是钉住的硬设定，任何一章都不能写反。"
                ),
            },
            "volumes": [
                {
                    "id": LN_VOLUME_ID,
                    "title": "第一卷 钟声与失物招领处",
                    "note": (
                        "本卷任务：让读者相信「钟声真的在挑人」，并在第三章末尾把主角推到"
                        "钟楼门前。每章正文 2–4 段，章末留一句钩子。"
                    ),
                }
            ],
            "chapters": chapters,
            "characters": _characters(),
            "loreEntries": [*build_ln_world_entries(), *build_ln_glossary()],
            "writingLedger": _seed_ledger(chapters),
            "harnessRuns": [_seed_plan_run()],
        }
    )
