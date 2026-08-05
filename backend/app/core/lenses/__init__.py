"""作家思维包（Author Lens）：可叠加的审稿/剧情视角。

设计见 ``backend/vendor/AUTHOR_LENS_DESIGN.md``。
默认关闭；不得推翻 style_guide 与常驻写作导师。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.core.mentors import (
    MentorPack,
    _clip,
    _parse_frontmatter,
    _FRONTMATTER_RE,
    _split_sections,
)

PACKS_DIR = Path(__file__).resolve().parent / "authors"
CRAFT_DIR = Path(__file__).resolve().parent / "craft"

_PRIORITY_SECTIONS = (
    "视角一句话",
    "反模式",
    "心智模型",
    "表达 DNA",
    "决策启发式",
    "审阅时问什么",
    "剧情参谋时问什么",
    "诚实边界",
)

# 兼容女娲等 SKILL.md 常见标题
_SECTION_ALIASES = {
    "人格一句话": "视角一句话",
    "怎么想": "心智模型",
    "怎么判断": "决策启发式",
    "怎么说话": "表达 DNA",
    "什么不做": "反模式",
    "知道局限": "诚实边界",
    "决策启发式": "决策启发式",
    "表达DNA": "表达 DNA",
}

_LEGACY_LENS_IDS = {
    "murakami-mood": "author-murakami",
    "higashino-plot": "author-higashino",
}

_RETIRED_CRAFT_IDS = {
    "jp-ln-crisp",
    "vn-tearjerker",
    "dialogue-virtuoso",
    "mythos-rules",
    "school-romance",
    "info-battle-pace",
}


def normalize_lens_id(pack_id: str) -> Optional[str]:
    pid = (pack_id or "").strip()
    if not pid or pid in _RETIRED_CRAFT_IDS:
        return None
    return _LEGACY_LENS_IDS.get(pid, pid)


def parse_lens_markdown(
    markdown: str,
    *,
    fallback_id: str = "custom-lens",
    source: str = "custom",
) -> MentorPack:
    raw = markdown or ""
    meta: Dict[str, Any] = {}
    body = raw
    m = _FRONTMATTER_RE.match(raw.strip())
    if m:
        meta = _parse_frontmatter(m.group(1))
        body = m.group(2).strip()
    sections = _split_sections(body)
    # normalize alias titles
    normalized: Dict[str, str] = {}
    for k, v in sections.items():
        normalized[_SECTION_ALIASES.get(k, k)] = v
    pack_id = str(meta.get("id") or fallback_id).strip() or fallback_id
    name = str(meta.get("name") or pack_id).strip()
    media = meta.get("media")
    if not isinstance(media, list):
        media = ["light_novel", "visual_novel"]
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    stages = meta.get("modes") if isinstance(meta.get("modes"), list) else ["review", "plot"]
    if not isinstance(meta.get("stages"), list):
        pass
    else:
        stages = meta["stages"]
    budget = meta.get("budget_chars")
    if not isinstance(budget, int) or budget <= 0:
        budget = 2200
    return MentorPack(
        id=pack_id,
        name=name,
        version=str(meta.get("version") or "1.0"),
        kind=str(meta.get("kind") or "author_lens"),
        media=[str(x) for x in media],
        locale=str(meta.get("locale") or "zh-Hans"),
        tags=[str(x) for x in tags],
        stages=[str(x) for x in stages],
        budget_chars=budget,
        provenance=str(meta.get("provenance") or "unknown"),
        body=body,
        sections=normalized,
        raw=raw,
        source=source,
    )


def pack_prompt_block(pack: MentorPack, *, max_chars: Optional[int] = None) -> str:
    budget = max_chars if max_chars is not None else pack.budget_chars
    parts: List[str] = [
        f"## 作家思维：{pack.name}",
        f"（id=`{pack.id}`；视角透镜，非真人扮演；不得仿写受版权原文；不得推翻 style_guide / 写作导师。）",
    ]
    used = "\n".join(parts)
    for title in _PRIORITY_SECTIONS:
        content = pack.sections.get(title)
        if not content:
            continue
        chunk = f"### {title}\n{content}"
        if len(used) + 2 + len(chunk) > budget:
            remain = budget - len(used) - 2
            if remain < 80:
                break
            chunk = _clip(chunk, remain)
            parts.append(chunk)
            break
        parts.append(chunk)
        used = "\n\n".join(parts)
    return _clip("\n\n".join(parts), budget)


def lenses_prompt_block(
    packs: Sequence[MentorPack],
    *,
    total_budget: int = 5200,
    intent: str = "review",
) -> str:
    if not packs:
        return ""
    n = len(packs)
    per = max(700, total_budget // n)
    blocks = [pack_prompt_block(p, max_chars=min(p.budget_chars, per)) for p in packs]
    header = (
        "—— 作家思维透镜（可选；多视角时请分段输出）——\n"
        "规则：\n"
        "- 审阅/参谋：按「## 视角：名称」分段给意见；最后用「## 综合（责编）」收束到本作品可执行的下一步。\n"
        "- 续写正文：透镜只作节制参考，保持角色声口与 VN 可演，禁止写成某作家仿作。\n"
        f"- 本轮意图偏置：{intent}\n"
    )
    return _clip(header + "\n\n".join(b for b in blocks if b.strip()), total_budget)


@lru_cache(maxsize=1)
def load_builtin_lenses() -> Dict[str, MentorPack]:
    out: Dict[str, MentorPack] = {}
    if not PACKS_DIR.is_dir():
        return out
    for path in sorted(PACKS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        pack = parse_lens_markdown(text, fallback_id=path.stem, source="builtin")
        if pack.id.startswith("_"):
            continue
        out[pack.id] = pack
    return out


def reload_builtin_lenses() -> Dict[str, MentorPack]:
    load_builtin_lenses.cache_clear()
    return load_builtin_lenses()


def list_builtin_lens_meta() -> List[Dict[str, Any]]:
    return [p.meta() for p in load_builtin_lenses().values()]


def get_builtin_lens(pack_id: str) -> Optional[MentorPack]:
    return load_builtin_lenses().get(pack_id)


def _project_lens_state(project: Any) -> Dict[str, Any]:
    raw = getattr(project, "authorLenses", None)
    if raw is None and isinstance(project, dict):
        raw = project.get("authorLenses")
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    return raw if isinstance(raw, dict) else {}


def active_lens_ids_for_project(
    project: Any,
    *,
    override_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    raw_ids: List[str]
    if override_ids is not None:
        raw_ids = [str(x).strip() for x in override_ids if str(x).strip()]
    else:
        state = _project_lens_state(project)
        ids = state.get("activeIds")
        raw_ids = [str(x).strip() for x in ids if str(x).strip()] if isinstance(ids, list) else []
    out: List[str] = []
    for x in raw_ids:
        nid = normalize_lens_id(x)
        if nid and nid not in out:
            out.append(nid)
    return out[:3]


def custom_lenses_for_project(project: Any) -> List[Dict[str, Any]]:
    state = _project_lens_state(project)
    packs = state.get("customPacks")
    return [p for p in packs if isinstance(p, dict)] if isinstance(packs, list) else []


def resolve_lenses(
    ids: Iterable[str],
    *,
    custom: Optional[Sequence[Dict[str, Any]]] = None,
    max_active: int = 3,
) -> List[MentorPack]:
    custom_map: Dict[str, MentorPack] = {}
    for row in custom or []:
        md = (row.get("markdown") or "").strip()
        if not md:
            continue
        cid = str(row.get("id") or "custom-lens").strip()
        custom_map[cid] = parse_lens_markdown(md, fallback_id=cid, source="custom")
        if row.get("name"):
            custom_map[cid].name = str(row["name"])
    builtins = load_builtin_lenses()
    resolved: List[MentorPack] = []
    seen = set()
    for raw_id in ids:
        pid = normalize_lens_id(raw_id or "") or ""
        if not pid or pid in seen:
            continue
        pack = custom_map.get(pid) or builtins.get(pid)
        if not pack:
            continue
        resolved.append(pack)
        seen.add(pid)
        if len(resolved) >= max_active:
            break
    return resolved


def resolve_project_lenses(
    project: Any,
    *,
    override_ids: Optional[Sequence[str]] = None,
) -> List[MentorPack]:
    return resolve_lenses(
        active_lens_ids_for_project(project, override_ids=override_ids),
        custom=custom_lenses_for_project(project),
    )


def build_lens_prompt_for_project(
    project: Any,
    *,
    override_ids: Optional[Sequence[str]] = None,
    intent: str = "review",
    total_budget: int = 5200,
) -> str:
    packs = resolve_project_lenses(project, override_ids=override_ids)
    return lenses_prompt_block(packs, total_budget=total_budget, intent=intent)


LENS_ALIASES: Dict[str, str] = {
    "村上": "author-murakami",
    "村上春树": "author-murakami",
    "author-murakami": "author-murakami",
    "murakami-mood": "author-murakami",
    "东野": "author-higashino",
    "东野圭吾": "author-higashino",
    "author-higashino": "author-higashino",
    "higashino-plot": "author-higashino",
    "渡航": "author-watari",
    "author-watari": "author-watari",
    "西尾": "author-nishio",
    "西尾维新": "author-nishio",
    "author-nishio": "author-nishio",
    "鎌池": "author-kamachi",
    "鎌池和馬": "author-kamachi",
    "author-kamachi": "author-kamachi",
    "奈须": "author-nasu",
    "奈須": "author-nasu",
    "奈須きのこ": "author-nasu",
    "author-nasu": "author-nasu",
    "麻枝": "author-maeda",
    "麻枝准": "author-maeda",
    "author-maeda": "author-maeda",
    "丸户": "author-maruto",
    "丸戸": "author-maruto",
    "丸戸史明": "author-maruto",
    "author-maruto": "author-maruto",
    "虚渊": "author-urobuchi",
    "虚渊玄": "author-urobuchi",
    "author-urobuchi": "author-urobuchi",
    "罗密欧": "author-romeo",
    "田中罗密欧": "author-romeo",
    "author-romeo": "author-romeo",
    "林直孝": "author-hayashi",
    "author-hayashi": "author-hayashi",
    "Looseboy": "author-looseboy",
    "looseboy": "author-looseboy",
    "author-looseboy": "author-looseboy",
    "新岛夕": "author-niijima",
    "新島夕": "author-niijima",
    "author-niijima": "author-niijima",
    "漆原": "author-urushibara",
    "漆原雪人": "author-urushibara",
    "author-urushibara": "author-urushibara",
    "Kai": "author-kai",
    "kai": "author-kai",
    "author-kai": "author-kai",
}


def lens_family(pack_id: str) -> str:
    return "author"


def match_lens_ids_from_text(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    found: List[str] = []
    for alias, mid in sorted(LENS_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in raw or alias.lower() in raw.lower():
            nid = normalize_lens_id(mid)
            if nid and nid not in found:
                found.append(nid)
        if len(found) >= 3:
            break
    if len(found) < 3:
        for pack in load_builtin_lenses().values():
            if pack.name and pack.name in raw:
                nid = normalize_lens_id(pack.id)
                if nid and nid not in found:
                    found.append(nid)
            if len(found) >= 3:
                break
    return found


def infer_lens_intent(text: str) -> str:
    t = text or ""
    if any(k in t for k in ("审", "改", "润色", "体检", "挑剔")):
        return "review"
    if any(k in t for k in ("剧情", "走向", "大纲", "伏笔", "下一场", "参谋")):
        return "plot"
    if any(k in t for k in ("续写", "写成", "重写")):
        return "rewrite_hint"
    return "review"
