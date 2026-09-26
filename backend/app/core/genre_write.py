"""作品体裁 → 续写硬规则 / 输出契约差分（与前端 genreCopy 同口径）。

只影响**可执行的写路径提示**（continue / scene / branch），不改界面文案。
显式 writingGenre 优先；否则按 genre 关键词猜；默认 vn（保守：不把 VN 当小说）。
"""
from __future__ import annotations

from typing import List, Literal, Optional

from app.domain.types import VnProject

WritingGenre = Literal["vn", "novel"]

_NOVEL_MARKERS = (
    "轻小说",
    "小说",
    "网文",
    "网络文学",
    "文学",
    "长篇小说",
    "短篇",
)
_VN_MARKERS = (
    "视觉小说",
    "文字冒险",
    "galgame",
    "ギャルゲー",
    "乙女游戏",
    "avg",
    "adv",
)

#: 体裁专属硬规则（叠在 TASK_KEY_RULES 后面）
GENRE_TASK_RULES: dict[str, dict[str, List[str]]] = {
    "novel": {
        "continue": [
            "体裁是小说/轻小说：以段落叙述为主，对白用引号或「」嵌在叙述里；不要输出 Ren'Py menu/label。",
            "章末优先落在可回收的具体钩子上（物件/一句未答完的话），不要空喊悬念。",
        ],
        "scene": [
            "写完整一小场叙述戏：进场感官 → 冲突 → 收束钩；不要写成分镜表或选项列表。",
        ],
        "branch": [
            "小说体裁下若被要求分支：用「若…则…」叙事分叉简述，不要输出 Ren'Py menu 语法。",
        ],
    },
    "vn": {
        "continue": [
            "体裁是视觉小说：对白可演、旁白宜短；信息优先落在台词与可见动作，少写说明书旁白。",
            "若出现选择，选项必须通向不同后果；禁止三选项接同一段。",
        ],
        "scene": [
            "写可上演的一小场：对白+少量旁白；不要大段心理说明书。",
        ],
        "branch": [
            "输出 Ren'Py menu 形态：每项后果不同；选项文案短，勿在选项里塞设定。",
        ],
    },
}

GENRE_OUTPUT_CONTRACT: dict[str, dict[str, str]] = {
    "novel": {
        "continue": (
            "只输出续写的一小段叙述正文（默认 180–450 字）；"
            "可用「」对白；不要一次写长章、不要 Ren'Py 语法、不要解释、不要小结、不要标题。"
        ),
        "scene": "只输出这一场的叙述正文；场景切换用空行；不要镜头术语、不要选项菜单。",
        "branch": "用短段落写出 2–3 条叙事分叉（若选A…/若选B…），不要 Ren'Py menu。",
    },
    "vn": {
        "continue": (
            "只输出续写的一小段可演正文（默认 180–450 字）；对白可演；"
            "不要一次写长章、不要解释、不要小结、不要标题。"
        ),
        "branch": (
            "输出 2–4 个分支（Ren'Py menu 形态）：每项一行选项文案，紧跟该选项的正文；"
            "选项之间后果必须不同。"
        ),
    },
}


def resolve_writing_genre(project: Optional[VnProject]) -> WritingGenre:
    if project is None:
        return "vn"
    explicit = str(getattr(project, "writingGenre", None) or "").strip().lower()
    if explicit in ("novel", "vn"):
        return explicit  # type: ignore[return-value]
    genre = str(getattr(project, "genre", None) or "").replace(" ", "").lower()
    if any(m.lower() in genre or m in genre for m in _VN_MARKERS):
        return "vn"
    # CJK markers: compare on original without lower for CJK
    raw = str(getattr(project, "genre", None) or "").replace(" ", "")
    if any(m in raw for m in _VN_MARKERS):
        return "vn"
    if any(m in raw for m in _NOVEL_MARKERS):
        return "novel"
    return "vn"


def genre_key_rules(project: Optional[VnProject], task: str) -> List[str]:
    g = resolve_writing_genre(project)
    return list(GENRE_TASK_RULES.get(g, {}).get(task or "", []) or [])


def genre_output_contract(project: Optional[VnProject], task: str) -> Optional[str]:
    g = resolve_writing_genre(project)
    return GENRE_OUTPUT_CONTRACT.get(g, {}).get(task or "")
