"""Smart map extraction: rule-based scene tags + LLM over dialogue / bible / outline."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from app.domain.types import Location, LocationLink, ScriptBlock, VnProject

from .ai import DeepSeekConfig
from .map_catalog import MAP_ELEMENT_PRESETS, preset_by_kind
from .project import (
    extract_map_from_script,
    new_location_link,
    uid,
)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")
_KNOWN_KINDS = {p["kind"] for p in MAP_ELEMENT_PRESETS}
_VALID_RELATIONS = {
    "adjacent",
    "contains",
    "inside",
    "above",
    "below",
    "leads_to",
    "visible_from",
    "other",
}

# Lightweight dictionary pass (no LLM) for Chinese / English place hints in prose
_PLACE_LEXICON: List[Tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"车站|月台|站台|火车站|地铁站"), "station", "车站"),
    (re.compile(r"学校|教室|天台|校园|宿舍"), "school", "学校"),
    (re.compile(r"咖啡店|咖啡馆|咖啡厅|茶馆"), "cafe", "咖啡馆"),
    (re.compile(r"公园|河边|湖边"), "park", "公园"),
    (re.compile(r"医院|病房|诊所"), "hospital", "医院"),
    (re.compile(r"便利店|商店|超市|商场"), "shop", "商店"),
    (re.compile(r"公司|办公室|职场|写字楼"), "office", "公司"),
    (re.compile(r"神社|寺庙|寺|教堂"), "temple", "神社"),
    (re.compile(r"森林|树林|密林"), "forest", "树林"),
    (re.compile(r"海边|沙滩|海岸"), "beach", "海边"),
    (re.compile(r"天桥|大桥|桥上"), "bridge", "桥"),
    (re.compile(r"广场"), "plaza", "广场"),
    (re.compile(r"公寓|合租"), "apartment", "公寓"),
    (re.compile(r"家里|自宅|房间|卧室"), "home", "自宅"),
]

_MAX_CORPUS_CHARS = 14000
_MAX_LLM_PLACES = 36
_MAX_LLM_EDGES = 48


def build_map_extract_corpus(project: VnProject) -> str:
    """Flatten script + bible into text the model can read."""
    parts: List[str] = []
    bible = project.bible
    if bible:
        for label, val in (
            ("世界观", bible.world),
            ("背景", bible.background),
            ("大纲", bible.outline),
            ("主题", bible.themes),
            ("备忘", bible.notes),
        ):
            if val and str(val).strip():
                parts.append(f"【{label}】\n{str(val).strip()}")

    if project.locations:
        listed = ", ".join(
            f"{l.name}" + (f"({l.imageTag})" if l.imageTag else "")
            for l in project.locations[:40]
        )
        parts.append(f"【已有地图地点】\n{listed}")

    for ch in project.chapters:
        lines: List[str] = [f"## 章节 {ch.title}"]
        if ch.synopsis:
            lines.append(f"（梗概）{ch.synopsis}")
        _append_block_lines(ch.blocks, lines, project)
        parts.append("\n".join(lines))

    text = "\n\n".join(parts).strip()
    if len(text) > _MAX_CORPUS_CHARS:
        text = text[:_MAX_CORPUS_CHARS] + "\n…(已截断)"
    return text


def _append_block_lines(
    blocks: List[ScriptBlock], lines: List[str], project: VnProject
) -> None:
    char_names = {c.id: c.displayName for c in project.characters}
    for b in blocks:
        t = b.get("type")
        if t == "scene":
            img = str(b.get("image") or "").strip()
            if img:
                lines.append(f"[scene] {img}")
        elif t == "narration":
            text = str(b.get("text") or "").strip()
            if text:
                lines.append(f"[旁白] {text}")
        elif t == "dialogue":
            who = char_names.get(str(b.get("characterId") or ""), "角色")
            text = str(b.get("text") or "").strip()
            if text:
                lines.append(f'[对白/{who}] "{text}"')
        elif t == "comment":
            text = str(b.get("text") or "").strip()
            if text:
                lines.append(f"# {text}")
        elif t == "label":
            name = str(b.get("name") or "").strip()
            if name:
                lines.append(f"[label] {name}")
        elif t == "jump":
            target = str(b.get("target") or "").strip()
            if target:
                lines.append(f"[jump] {target}")
        elif t == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                lines.append(f"[选项提示] {prompt}")
            for c in b.get("choices") or []:
                if not isinstance(c, dict):
                    continue
                ct = str(c.get("text") or "").strip()
                if ct:
                    lines.append(f"  - 选项: {ct}")
                child = c.get("blocks")
                if child:
                    _append_block_lines(child, lines, project)
        elif t == "raw":
            code = str(b.get("code") or "").strip()
            if code:
                lines.append(code[:400])


def lexicon_suggest_places(corpus: str) -> List[Dict[str, Any]]:
    """Deterministic place hints from prose (complements scene tags)."""
    found: Dict[str, Dict[str, Any]] = {}
    for pattern, kind, name in _PLACE_LEXICON:
        m = pattern.search(corpus)
        if not m:
            continue
        key = name.lower()
        if key in found:
            continue
        found[key] = {
            "name": name,
            "kind": kind,
            "imageTag": f"bg {kind}",
            "evidence": m.group(0),
            "description": f"词典命中「{m.group(0)}」",
            "source": "lexicon",
        }
    return list(found.values())


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _pretty_tag(image: str) -> str:
    name = re.sub(r"^bg[_\s]+", "", image, flags=re.IGNORECASE)
    return name.replace("_", " ").strip() or image


def _infer_kind(text: str, fallback: str = "landmark") -> str:
    s = (text or "").lower()
    table = [
        (r"station|车站|月台", "station"),
        (r"school|学校|教室|campus", "school"),
        (r"cafe|咖啡", "cafe"),
        (r"home|家|房间|room", "home"),
        (r"park|公园", "park"),
        (r"hospital|医院", "hospital"),
        (r"shop|店|便利", "shop"),
        (r"office|公司", "office"),
        (r"temple|神社|寺", "temple"),
        (r"forest|林|森", "forest"),
        (r"beach|海", "beach"),
        (r"bridge|桥", "bridge"),
        (r"plaza|广场", "plaza"),
        (r"apartment|公寓", "apartment"),
    ]
    for pat, kind in table:
        if re.search(pat, s, re.I):
            return kind if kind in _KNOWN_KINDS else fallback
    return fallback if fallback in _KNOWN_KINDS else "landmark"


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # tolerate leading junk
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("模型未返回 JSON 对象")
    return data


async def _call_llm_map_extract(
    config: DeepSeekConfig,
    project: VnProject,
    corpus: str,
    known_locations: List[Location],
) -> Dict[str, Any]:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")

    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = config.model or "deepseek-chat"
    known = [
        {
            "name": l.name,
            "imageTag": l.imageTag or "",
            "kind": l.elementKind or "",
        }
        for l in known_locations[:40]
    ]
    kinds = ", ".join(sorted(_KNOWN_KINDS))
    system = (
        "你是视觉小说「故事地图」分析器。根据剧本、对白、旁白与设定，提取真实出现或强暗示的地点，"
        "以及地点之间的通行/包含关系。只输出 JSON，不要解释。"
        "宁可少提，不要把抽象概念、情绪、时间当成地点。"
        "每个地点必须带简短 evidence（原文短语）。"
    )
    user = {
        "title": project.title,
        "genre": project.genre,
        "known_locations": known,
        "allowed_kinds": kinds,
        "allowed_relations": sorted(_VALID_RELATIONS),
        "script_corpus": corpus,
        "output_schema": {
            "places": [
                {
                    "name": "显示名",
                    "imageTag": "可选 Ren'Py bg 标签，如 bg station_night",
                    "kind": "allowed_kinds 之一",
                    "aliases": ["别名"],
                    "evidence": "原文依据",
                    "description": "一句话",
                }
            ],
            "edges": [
                {
                    "from": "地点名或 imageTag",
                    "to": "地点名或 imageTag",
                    "relation": "allowed_relations 之一",
                    "evidence": "原文依据",
                }
            ],
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.apiKey}",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(user, ensure_ascii=False),
                    },
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
        )
    if res.status_code >= 400:
        raise RuntimeError(f"DeepSeek API {res.status_code}: {res.text[:400]}")
    data = res.json()
    choices = data.get("choices") or []
    content = ""
    if choices:
        content = ((choices[0] or {}).get("message") or {}).get("content", "") or ""
    return _parse_llm_json(content)


def _match_location(
    locations: List[Location],
    *,
    name: str = "",
    image_tag: str = "",
    aliases: Optional[List[str]] = None,
) -> Optional[Location]:
    tag_key = _normalize_key(image_tag) if image_tag else ""
    name_key = _normalize_key(name) if name else ""
    alias_keys = {_normalize_key(a) for a in (aliases or []) if a}
    for loc in locations:
        if tag_key and loc.imageTag and _normalize_key(loc.imageTag) == tag_key:
            return loc
        if name_key and _normalize_key(loc.name) == name_key:
            return loc
        if loc.imageTag and _normalize_key(loc.imageTag) in alias_keys:
            return loc
        if _normalize_key(loc.name) in alias_keys:
            return loc
    return None


def _grid_pos(idx: int) -> Tuple[float, float]:
    stage_x, stage_y = 1300, 1050
    return (
        stage_x + 200 + (idx % 5) * 320,
        stage_y + 280 + (idx // 5) * 260,
    )


def merge_suggested_places(
    base: Dict[str, Any],
    suggestions: List[Dict[str, Any]],
    *,
    source_label: str,
) -> Dict[str, Any]:
    """Merge place/edge suggestions into a rule-extract result (non-destructive)."""
    locations: List[Location] = list(base.get("locations") or [])
    location_links: List[LocationLink] = list(base.get("locationLinks") or [])
    link_keys = {f"{l.fromId}->{l.toId}:{l.relation}" for l in location_links}
    added = int(base.get("addedCount") or 0)
    link_count = int(base.get("linkCount") or 0)
    llm_added = 0
    llm_links = 0

    # First pass: places only
    id_by_ref: Dict[str, str] = {}
    for loc in locations:
        id_by_ref[_normalize_key(loc.name)] = loc.id
        if loc.imageTag:
            id_by_ref[_normalize_key(loc.imageTag)] = loc.id

    place_items = [s for s in suggestions if s.get("_type") != "edge"]
    edge_items = [s for s in suggestions if s.get("_type") == "edge"]

    for raw in place_items[:_MAX_LLM_PLACES]:
        name = str(raw.get("name") or "").strip()
        evidence = str(raw.get("evidence") or "").strip()
        if not name:
            continue
        # Lexicon may lack evidence length; LLM should have some
        if raw.get("source") == "llm" and len(evidence) < 2:
            continue
        image_tag = str(raw.get("imageTag") or raw.get("image_tag") or "").strip()
        aliases = raw.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        aliases = [str(a).strip() for a in aliases if str(a).strip()]
        kind = str(raw.get("kind") or "").strip() or _infer_kind(
            f"{name} {image_tag} {' '.join(aliases)}"
        )
        if kind not in _KNOWN_KINDS:
            kind = _infer_kind(name)
        preset = preset_by_kind(kind)
        existing = _match_location(
            locations, name=name, image_tag=image_tag, aliases=aliases
        )
        if existing:
            id_by_ref[_normalize_key(name)] = existing.id
            for a in aliases:
                id_by_ref[_normalize_key(a)] = existing.id
            if image_tag:
                id_by_ref[_normalize_key(image_tag)] = existing.id
            # Enrich empty metadata only
            patch: Dict[str, Any] = {}
            if not existing.description and (
                raw.get("description") or evidence
            ):
                patch["description"] = str(
                    raw.get("description") or f"{source_label}：{evidence}"
                )[:240]
            if not existing.imageTag and image_tag:
                patch["imageTag"] = image_tag
            if not existing.elementKind:
                patch["elementKind"] = kind
                patch["icon"] = existing.icon or preset["icon"]
                patch["color"] = existing.color or preset["color"]
            if (existing.mapX is None or existing.mapY is None) and locations:
                idx = next(
                    (i for i, l in enumerate(locations) if l.id == existing.id),
                    len(locations),
                )
                mx, my = _grid_pos(idx)
                if existing.mapX is None:
                    patch["mapX"] = mx
                if existing.mapY is None:
                    patch["mapY"] = my
            if patch:
                updated = existing.model_copy(update=patch)
                locations = [updated if l.id == existing.id else l for l in locations]
            continue

        idx = len(locations)
        mx, my = _grid_pos(idx)
        tag = image_tag or f"bg {_slug_tag(name)}"
        loc = Location(
            id=uid("loc"),
            name=name,
            imageTag=tag,
            description=str(
                raw.get("description") or f"{source_label}：{evidence or name}"
            )[:240],
            elementKind=kind,
            icon=preset["icon"],
            color=preset["color"],
            mapX=mx,
            mapY=my,
            scale=1,
            rotation=0,
            tags=aliases[:8] or None,
        )
        locations.append(loc)
        id_by_ref[_normalize_key(name)] = loc.id
        id_by_ref[_normalize_key(tag)] = loc.id
        for a in aliases:
            id_by_ref[_normalize_key(a)] = loc.id
        added += 1
        llm_added += 1

    for raw in edge_items[:_MAX_LLM_EDGES]:
        frm = str(raw.get("from") or "").strip()
        to = str(raw.get("to") or "").strip()
        if not frm or not to:
            continue
        relation = str(raw.get("relation") or "leads_to").strip()
        if relation not in _VALID_RELATIONS:
            relation = "leads_to"
        from_id = id_by_ref.get(_normalize_key(frm))
        to_id = id_by_ref.get(_normalize_key(to))
        if not from_id or not to_id or from_id == to_id:
            continue
        key = f"{from_id}->{to_id}:{relation}"
        if key in link_keys:
            continue
        note = str(raw.get("evidence") or "").strip()[:160] or None
        link = new_location_link(from_id, to_id, relation)
        if note:
            link = link.model_copy(update={"note": note})
        location_links.append(link)
        link_keys.add(key)
        link_count += 1
        llm_links += 1

    return {
        "locations": locations,
        "locationLinks": location_links,
        "addedCount": added,
        "linkCount": link_count,
        "llmAddedCount": llm_added if source_label == "模型" else int(base.get("llmAddedCount") or 0),
        "llmLinkCount": llm_links if source_label == "模型" else int(base.get("llmLinkCount") or 0),
        "mode": base.get("mode"),
        "llmUsed": base.get("llmUsed", False),
        "warnings": list(base.get("warnings") or []),
    }


def _slug_tag(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name.strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s[:40] or "place"


def _suggestions_from_llm_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in data.get("places") or []:
        if not isinstance(p, dict):
            continue
        item = dict(p)
        item["source"] = "llm"
        item["_type"] = "place"
        out.append(item)
    for e in data.get("edges") or []:
        if not isinstance(e, dict):
            continue
        item = dict(e)
        item["source"] = "llm"
        item["_type"] = "edge"
        out.append(item)
    return out


def _suggestions_from_lexicon(places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in places:
        item = dict(p)
        item["_type"] = "place"
        out.append(item)
    return out


async def extract_map_smart(
    project: VnProject,
    config: Optional[DeepSeekConfig] = None,
    *,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    Strong extract pipeline:
    1) Rule extract from scene blocks
    2) Lexicon hints from narration / dialogue / bible
    3) Optional LLM semantic extract + merge
    """
    base = extract_map_from_script(project)
    corpus = build_map_extract_corpus(project)
    warnings: List[str] = []

    # Working snapshot after rules — lexicon merges on top
    working = dict(base)
    working["llmAddedCount"] = 0
    working["llmLinkCount"] = 0
    working["mode"] = "rules"
    working["llmUsed"] = False

    lex = lexicon_suggest_places(corpus)
    if lex:
        working = merge_suggested_places(
            working, _suggestions_from_lexicon(lex), source_label="词典"
        )
        working["mode"] = "rules+lexicon"

    if not use_llm:
        working["warnings"] = warnings
        return working

    if config is None or not config.apiKey or "your-key" in config.apiKey:
        warnings.append("未配置 DEEPSEEK_API_KEY，已跳过模型提取（仍使用 scene + 词典）")
        working["warnings"] = warnings
        return working

    if not corpus.strip():
        warnings.append("剧本与设定为空，无法做语义提取")
        working["warnings"] = warnings
        return working

    try:
        # Use locations after lexicon merge as "known" for the model
        known = list(working.get("locations") or [])
        payload = await _call_llm_map_extract(config, project, corpus, known)
        suggestions = _suggestions_from_llm_payload(payload)
        working = merge_suggested_places(
            working, suggestions, source_label="模型"
        )
        working["mode"] = "smart"
        working["llmUsed"] = True
    except Exception as exc:  # noqa: BLE001 — surface to API as warning + partial result
        warnings.append(f"模型提取失败，已保留规则/词典结果：{exc}")
        working["mode"] = "rules+lexicon"
        working["llmUsed"] = False

    working["warnings"] = warnings
    return working
