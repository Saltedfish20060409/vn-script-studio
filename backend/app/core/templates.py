"""Project starter templates — a curated set of genre scaffolds.

Each template ships a bible, characters, and one opening chapter so a new
writer can start typing immediately instead of facing a blank page. The
structure mirrors create_demo_project; templates are lightweight by design.
"""

from __future__ import annotations

from typing import Dict, List

from app.domain.types import VnProject

from .project import normalize_project, uid


def _template(
    key: str,
    title: str,
    genre: str,
    logline: str,
    bible: Dict[str, str],
    characters: List[dict],
    opening_blocks: List[dict],
) -> VnProject:
    return normalize_project(
        {
            "id": uid("proj"),
            "title": title,
            "genre": genre,
            "logline": logline,
            "bible": bible,
            "characters": characters,
            "chapters": [
                {
                    "id": uid("ch"),
                    "title": "第一章",
                    "blocks": opening_blocks,
                }
            ],
            "locations": [],
            "locationLinks": [],
        }
    )


TEMPLATES: Dict[str, VnProject] = {
    "slice_of_life": _template(
        key="slice_of_life",
        title="日常系 · 放学后的屋顶",
        genre="日常 / 青春",
        logline="转学生与摄影社学妹在放学后的屋顶上，各自藏着不愿说出口的理由。",
        bible={
            "world": "普通高中。天台是禁入区，却有一把从不落锁的旧门。",
            "background": "主角因为转学错过了毕业照；学妹想拍一张「只有我们知道」的照片。",
            "outline": "1. 天台相遇\n2. 交换秘密的开头\n3. 门被锁上，进退两难",
            "themes": "错过与重逢；青春期笨拙的诚实",
        },
        characters=[
            {
                "id": "watashi",
                "defineName": "watashi",
                "displayName": "我",
                "color": "#8fb7d9",
                "voice": "平静、略带疏离，内心话多",
                "bio": "转学生。对过去的事闭口不谈。",
            },
            {
                "id": "koharu",
                "defineName": "koharu",
                "displayName": "小春",
                "color": "#e8a4b8",
                "voice": "轻快、直接，偶尔突然沉默",
                "bio": "摄影社成员。总带着一台旧相机。",
            },
        ],
        opening_blocks=[
            {"type": "label", "id": "start", "name": "start"},
            {"type": "scene", "image": "bg rooftop"},
            {"type": "narration", "text": "放学铃响过很久，天台的风把废纸吹得打转。"},
            {"type": "dialogue", "characterId": "koharu", "text": "你也是来躲人的？"},
            {"type": "dialogue", "characterId": "watashi", "text": "……算是吧。"},
            {"type": "menu", "id": "m1", "prompt": "该怎么回应？", "choices": [{"text": "反问她的相机", "jump": "ask"}, {"text": "沉默地点头", "jump": "nod"}]},
        ],
    ),
    "mystery": _template(
        key="mystery",
        title="悬疑 · 末班车失联",
        genre="悬疑 / 都市",
        logline="每天同一班末班车，都会有一位乘客在到站前消失。",
        bible={
            "world": "沿海城市。地铁末班车只有三站，却常有人坐过站。",
            "background": "主角的合租室友三天前上了末班车，再没回来。",
            "outline": "1. 末班车上的异常\n2. 寻找失踪者\n3. 发现「多出来的一站」",
            "themes": "记忆的不可靠；都市人的消失",
        },
        characters=[
            {
                "id": "tantei",
                "defineName": "tantei",
                "displayName": "侦探",
                "color": "#5b8def",
                "voice": "冷静、爱记笔记",
                "bio": "自由撰稿人，兼职调查失踪案。",
            },
            {
                "id": "unmei",
                "defineName": "unmei",
                "displayName": "站长",
                "color": "#b85c38",
                "voice": "公事公办，偶尔漏出破绽",
                "bio": "末班车终点站站长。",
            },
        ],
        opening_blocks=[
            {"type": "label", "id": "start", "name": "start"},
            {"type": "scene", "image": "bg station_night"},
            {"type": "narration", "text": "监控里，他走进末班车，再没有走出来。"},
            {"type": "dialogue", "characterId": "unmei", "text": "那班车，早就停运了。"},
            {"type": "dialogue", "characterId": "tantei", "text": "可监控显示它今晚还在跑。"},
        ],
    ),
    "isekai": _template(
        key="isekai",
        title="异世界 · 图书馆管理员",
        genre="异世界 / 冒险",
        logline="被书吞进异世界的图书管理员，发现这里的一切都按小说的规则运转。",
        bible={
            "world": "魔法都市。知识与力量以「书页」为货币。",
            "background": "主角整理书架时被吸入一本未完成的小说。",
            "outline": "1. 坠入书页世界\n2. 结识向导\n3. 发现自己是「关键角色」",
            "themes": "知识即力量；写作者与被写者的边界",
        },
        characters=[
            {
                "id": "shiori",
                "defineName": "shiori",
                "displayName": "栞",
                "color": "#7eb8da",
                "voice": "文静、偶尔毒舌",
                "bio": "图书管理员，被吸入异世界。",
            },
            {
                "id": "foly",
                "defineName": "foly",
                "displayName": "弗利",
                "color": "#c4a574",
                "voice": "轻佻、熟稔这个世界",
                "bio": "自称向导的魔法书商人。",
            },
        ],
        opening_blocks=[
            {"type": "label", "id": "start", "name": "start"},
            {"type": "scene", "image": "bg great_library"},
            {"type": "narration", "text": "书架在摇晃，书页像鸟群一样飞起来。"},
            {"type": "dialogue", "characterId": "foly", "text": "欢迎。你是这本小说缺的那一页。"},
            {"type": "dialogue", "characterId": "shiori", "text": "……哪本小说？"},
        ],
    ),
}


def list_template_meta() -> List[dict]:
    """Public metadata (no full project payload)."""
    out = []
    for key, vn in TEMPLATES.items():
        out.append(
            {
                "id": key,
                "title": vn.title,
                "genre": vn.genre or "",
                "logline": vn.logline or "",
                "characters": [c.displayName for c in vn.characters or []],
            }
        )
    return out


def build_from_template(template_id: str, title: str | None = None) -> VnProject:
    """Deep-copy a template into a fresh project (new ids, optional title)."""
    template = TEMPLATES.get(template_id)
    if template is None:
        raise KeyError(template_id)
    import copy

    fresh = copy.deepcopy(template)
    fresh.id = uid("proj")
    if title and title.strip():
        fresh.title = title.strip()
    # Re-key chapter + block ids so duplicates never collide across projects.
    for ch in fresh.chapters or []:
        ch.id = uid("ch")
        for b in ch.blocks or []:
            if b.get("id"):
                b["id"] = uid("b")
    return normalize_project(fresh)
