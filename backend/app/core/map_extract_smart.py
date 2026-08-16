"""Smart map extraction: rule-based scene tags + LLM over dialogue / bible / outline."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.domain.types import Location, LocationLink, ScriptBlock, VnProject

from .ai import DeepSeekConfig
from .llm_http import chat_completions, content_from_response
from .map_catalog import MAP_ELEMENT_PRESETS, preset_by_kind
from .map_layout import layout_project_map, pinned_location_ids
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
# Connectivity only — relation kept for schema compat, not chosen by LLM / UI.
_DEFAULT_LINK_RELATION = "adjacent"


# Prefer specific phrases first (first match wins per pattern loop; we keep all unique names).
_PLACE_LEXICON: List[Tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"停用站厅|站厅"), "station", "停用站厅"),
    (re.compile(r"维修通道"), "bridge", "维修通道"),
    (re.compile(r"雨夜月台|月台|站台"), "station", "雨夜月台"),
    (re.compile(r"人行天桥|天桥"), "bridge", "天桥"),
    (re.compile(r"便利店"), "shop", "便利店"),
    (re.compile(r"公园东门"), "park", "公园东门"),
    (re.compile(r"火车站|地铁站|车站"), "station", "车站"),
    (re.compile(r"学校|教室|天台|校园|宿舍"), "school", "学校"),
    (re.compile(r"咖啡店|咖啡馆|咖啡厅|茶馆"), "cafe", "咖啡馆"),
    (re.compile(r"公园|河边|湖边"), "park", "公园"),
    (re.compile(r"医院|病房|诊所"), "hospital", "医院"),
    (re.compile(r"商店|超市|商场"), "shop", "商店"),
    (re.compile(r"公司|办公室|职场|写字楼"), "office", "公司"),
    (re.compile(r"神社|寺庙|寺|教堂"), "temple", "神社"),
    (re.compile(r"森林|树林|密林"), "forest", "树林"),
    (re.compile(r"海边|沙滩|海岸"), "beach", "海边"),
    (re.compile(r"大桥|桥上|\b桥\b"), "bridge", "桥"),
    (re.compile(r"广场"), "plaza", "广场"),
    (re.compile(r"公寓|合租"), "apartment", "公寓"),
    (re.compile(r"家里|自宅|房间|卧室"), "home", "自宅"),
]

# Generic lexicon/scene labels that should fold into a more specific same-kind place.
_GENERIC_PLACE_NAMES = {
    "车站",
    "月台",
    "站台",
    "公园",
    "医院",
    "商店",
    "店",
    "桥",
    "学校",
    "咖啡馆",
    "咖啡店",
    "自宅",
    "家里",
    "广场",
    "树林",
    "海边",
    "公司",
    "神社",
    "公寓",
    "station",
    "park",
    "hospital",
    "shop",
    "bridge",
    "school",
    "cafe",
    "home",
}

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
        rival_keys = [
            k for k, v in found.items() if v.get("kind") == kind and k != key
        ]
        if rival_keys:
            best = max(
                [name] + [found[k]["name"] for k in rival_keys],
                key=lambda n: (len(n), not _is_generic_name(n)),
            )
            if best != name:
                continue
            for k in rival_keys:
                found.pop(k, None)
        found[key] = {
            "name": name,
            "kind": kind,
            "imageTag": f"bg {kind}",
            "evidence": m.group(0),
            "description": f"词典命中「{m.group(0)}」",
            "source": "lexicon",
            "aliases": [m.group(0)] if m.group(0) != name else [],
        }
    return list(found.values())


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _is_slug_name(name: str) -> bool:
    s = (name or "").strip()
    if not s:
        return True
    if re.search(r"[\u4e00-\u9fff]", s):
        return False
    return bool(re.fullmatch(r"[a-z0-9 _\-/]+", s, flags=re.I))


def _is_generic_name(name: str) -> bool:
    return _normalize_key(name) in {_normalize_key(g) for g in _GENERIC_PLACE_NAMES}


def _name_tokens(s: str) -> Set[str]:
    raw = _normalize_key(s)
    parts = re.split(r"[\s_\-/]+", raw)
    out: Set[str] = {p for p in parts if len(p) >= 2}
    hans = re.findall(r"[\u4e00-\u9fff]+", s or "")
    for h in hans:
        out.add(h)
        if len(h) >= 2:
            for i in range(len(h) - 1):
                out.add(h[i : i + 2])
    return out


def _names_soft_match(a: str, b: str) -> bool:
    na, nb = _normalize_key(a), _normalize_key(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    inter = (ta & tb) - {"bg"}
    if not inter:
        return False
    return len(inter) >= 1 and (
        len(inter) / max(1, min(len(ta), len(tb))) >= 0.4 or len(inter) >= 2
    )


def _pretty_tag(image: str) -> str:
    name = re.sub(r"^bg[_\s]+", "", image, flags=re.IGNORECASE)
    return name.replace("_", " ").strip() or image


def _infer_kind(text: str, fallback: str = "landmark") -> str:
    s = (text or "").lower()
    table = [
        (r"station|车站|月台|站厅", "station"),
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
        (r"bridge|桥|overpass|tunnel|通道", "bridge"),
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
        "以及地点之间是否连通（有明确前往/进入/通向依据）。只输出 JSON，不要解释。"
        "宁可少提，不要把抽象概念、情绪、时间当成地点。"
        "每个地点必须带简短 evidence（原文短语）。"
        "显示名优先使用中文专名（如「便利店」「停用站厅」），不要输出英文 slug。"
        "若与 known_locations 同义或更笼统（如「商店」对「便利店」、「车站」对「雨夜月台」），"
        "不要新建 places，应把别名写入 aliases 并在 edges 中引用已有显示名。"
        "edges 只表示两地联通，不要输出 relation 类型；禁止仅因章节先后顺序连边。"
    )
    user = {
        "title": project.title,
        "genre": project.genre,
        "known_locations": known,
        "allowed_kinds": kinds,
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
                    "evidence": "原文依据",
                }
            ],
        },
    }
    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(user, ensure_ascii=False),
            },
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
        timeout=120,
    )
    content, _model = content_from_response(res)
    return _parse_llm_json(content)


def _match_location(
    locations: List[Location],
    *,
    name: str = "",
    image_tag: str = "",
    aliases: Optional[List[str]] = None,
    kind: str = "",
) -> Optional[Location]:
    tag_key = _normalize_key(image_tag) if image_tag else ""
    name_key = _normalize_key(name) if name else ""
    alias_keys = {_normalize_key(a) for a in (aliases or []) if a}
    kind = (kind or "").strip()

    # Exact / alias match first
    for loc in locations:
        if tag_key and loc.imageTag and _normalize_key(loc.imageTag) == tag_key:
            return loc
        if name_key and _normalize_key(loc.name) == name_key:
            return loc
        if loc.imageTag and _normalize_key(loc.imageTag) in alias_keys:
            return loc
        if _normalize_key(loc.name) in alias_keys:
            return loc

    # Soft semantic match (synonyms / slug vs Chinese)
    candidates = list(locations)
    if kind:
        same_kind = [l for l in locations if (l.elementKind or "") == kind]
        if same_kind:
            candidates = same_kind

    for loc in candidates:
        blob = " ".join(
            x
            for x in [loc.name, loc.imageTag or "", " ".join(loc.tags or [])]
            if x
        )
        probe = " ".join(x for x in [name, image_tag, " ".join(aliases or [])] if x)
        if _names_soft_match(loc.name, name) or _names_soft_match(blob, probe):
            return loc
        if kind and (loc.elementKind or "") == kind:
            # Generic lexicon label folds into any same-kind concrete place
            if _is_generic_name(name) and not _is_generic_name(loc.name):
                return loc
            if _is_generic_name(loc.name) and name and not _is_generic_name(name):
                return loc
    return None


def _prefer_display_name(current: str, candidate: str) -> str:
    cur, cand = (current or "").strip(), (candidate or "").strip()
    if not cand:
        return cur
    if not cur:
        return cand
    if _is_slug_name(cur) and not _is_slug_name(cand):
        return cand
    if _is_generic_name(cur) and not _is_generic_name(cand) and len(cand) >= len(cur):
        return cand
    if len(cand) > len(cur) + 1 and not _is_slug_name(cand):
        # Prefer longer Chinese specific names (公园东门 > 公园)
        if re.search(r"[\u4e00-\u9fff]", cand):
            return cand
    return cur


def _grid_pos(idx: int) -> Tuple[float, float]:
    stage_x, stage_y = 1300, 1050
    return (
        stage_x + 200 + (idx % 5) * 320,
        stage_y + 280 + (idx // 5) * 260,
    )


def dedupe_synonym_locations(result: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse generic / slug duplicates into a single concrete place per cluster."""
    locations: List[Location] = list(result.get("locations") or [])
    links: List[LocationLink] = list(result.get("locationLinks") or [])
    if len(locations) < 2:
        return result

    parent = {l.id: l.id for l in locations}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def is_weak(loc: Location) -> bool:
        return _is_generic_name(loc.name) or _is_slug_name(loc.name)

    def soft_pair(a: Location, b: Location) -> bool:
        if _names_soft_match(a.name, b.name):
            return True
        if (
            a.imageTag
            and b.imageTag
            and _normalize_key(a.imageTag) == _normalize_key(b.imageTag)
        ):
            return True
        return False

    def place_score(l: Location) -> Tuple[int, int, int, int, int]:
        tag = l.imageTag or ""
        real_tag = bool(tag) and not re.fullmatch(
            r"bg\s+(station|park|shop|bridge|hospital|school|cafe|home|landmark|"
            r"plaza|office|temple|forest|beach|apartment)",
            tag,
            flags=re.I,
        )
        return (
            1 if real_tag else 0,
            0 if _is_slug_name(l.name) else 1,
            0 if _is_generic_name(l.name) else 1,
            len(l.name or ""),
            len(l.description or ""),
        )

    # 1) Soft / identical-tag clusters
    for i, a in enumerate(locations):
        for b in locations[i + 1 :]:
            if soft_pair(a, b):
                union(a.id, b.id)

    # 2) Fold each weak place into at most one strong same-kind peer
    for weak in locations:
        if not is_weak(weak):
            continue
        kind = weak.elementKind or ""
        strong = [
            loc
            for loc in locations
            if loc.id != weak.id
            and not is_weak(loc)
            and (loc.elementKind or "") == kind
            and kind
        ]
        if not strong:
            continue
        soft_hits = [loc for loc in strong if soft_pair(weak, loc)]
        if soft_hits:
            target = max(soft_hits, key=place_score)
            union(weak.id, target.id)
        elif len(strong) == 1:
            union(weak.id, strong[0].id)
        # multiple strong peers, no soft hit → drop weak later without merging them

    drop_ids: Set[str] = set()
    for weak in locations:
        if not is_weak(weak):
            continue
        kind = weak.elementKind or ""
        strong = [
            loc
            for loc in locations
            if loc.id != weak.id
            and not is_weak(loc)
            and (loc.elementKind or "") == kind
            and kind
        ]
        # Still weak-only cluster with multiple strong peers → discard weak node
        if len(strong) >= 2 and find(weak.id) == weak.id:
            # not unioned into anyone
            if not any(find(s.id) == find(weak.id) for s in strong):
                drop_ids.add(weak.id)

    clusters: Dict[str, List[Location]] = {}
    for loc in locations:
        if loc.id in drop_ids:
            continue
        clusters.setdefault(find(loc.id), []).append(loc)

    id_map: Dict[str, str] = {did: "" for did in drop_ids}
    kept: List[Location] = []
    removed = len(drop_ids)
    for members in clusters.values():
        members = [m for m in members if m.id not in drop_ids]
        if not members:
            continue
        if len(members) == 1:
            kept.append(members[0])
            id_map[members[0].id] = members[0].id
            continue

        winner = max(members, key=place_score)
        aliases: List[str] = list(winner.tags or [])
        for m in members:
            id_map[m.id] = winner.id
            if m.id == winner.id:
                continue
            removed += 1
            for extra in [m.name, *(m.tags or [])]:
                if (
                    extra
                    and _normalize_key(extra) != _normalize_key(winner.name)
                    and extra not in aliases
                ):
                    aliases.append(extra)
            better_name = _prefer_display_name(winner.name, m.name)
            if better_name != winner.name:
                winner = winner.model_copy(update={"name": better_name})
            if (
                not winner.imageTag
                or re.fullmatch(r"bg\s+\w+", winner.imageTag or "", flags=re.I)
            ) and m.imageTag and not re.fullmatch(
                r"bg\s+\w+", m.imageTag or "", flags=re.I
            ):
                winner = winner.model_copy(update={"imageTag": m.imageTag})
            if not winner.description and m.description:
                winner = winner.model_copy(update={"description": m.description})
        if aliases:
            winner = winner.model_copy(update={"tags": aliases[:12]})
        kept.append(winner)

    # Remap dropped ids onto best same-kind kept place when possible
    for did in drop_ids:
        dropped = next((l for l in locations if l.id == did), None)
        if not dropped:
            continue
        kind = dropped.elementKind or ""
        peers = [k for k in kept if (k.elementKind or "") == kind]
        if peers:
            id_map[did] = max(peers, key=place_score).id
        else:
            id_map[did] = ""

    new_links: List[LocationLink] = []
    link_keys: Set[str] = set()
    for link in links:
        frm = id_map.get(link.fromId, link.fromId)
        to = id_map.get(link.toId, link.toId)
        if not frm or not to or frm == to:
            continue
        key = f"{frm}->{to}:{link.relation}"
        if key in link_keys:
            continue
        link_keys.add(key)
        if frm != link.fromId or to != link.toId:
            new_links.append(link.model_copy(update={"fromId": frm, "toId": to}))
        else:
            new_links.append(link)

    out = dict(result)
    out["locations"] = kept
    out["locationLinks"] = new_links
    out["linkCount"] = len(new_links)
    if removed:
        warnings = list(out.get("warnings") or [])
        warnings.append(f"已合并同义地点 {removed} 个")
        out["warnings"] = warnings
    return out


def merge_suggested_places(
    base: Dict[str, Any],
    suggestions: List[Dict[str, Any]],
    *,
    source_label: str,
) -> Dict[str, Any]:
    """Merge place/edge suggestions into a rule-extract result (non-destructive)."""
    locations: List[Location] = list(base.get("locations") or [])
    location_links: List[LocationLink] = list(base.get("locationLinks") or [])
    link_keys = {f"{l.fromId}->{l.toId}" for l in location_links}
    link_keys |= {f"{l.toId}->{l.fromId}" for l in location_links}
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
        for t in loc.tags or []:
            id_by_ref[_normalize_key(t)] = loc.id

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
            locations,
            name=name,
            image_tag=image_tag,
            aliases=aliases,
            kind=kind,
        )
        if existing:
            id_by_ref[_normalize_key(name)] = existing.id
            for a in aliases:
                id_by_ref[_normalize_key(a)] = existing.id
            if image_tag:
                id_by_ref[_normalize_key(image_tag)] = existing.id
            # Enrich empty metadata / upgrade slug or generic names
            patch: Dict[str, Any] = {}
            better = _prefer_display_name(existing.name, name)
            if better != existing.name:
                patch["name"] = better
            if not existing.description and (
                raw.get("description") or evidence
            ):
                patch["description"] = str(
                    raw.get("description") or f"{source_label}：{evidence}"
                )[:240]
            if image_tag and (
                not existing.imageTag
                or re.fullmatch(r"bg\s+\w+", existing.imageTag or "", flags=re.I)
            ):
                # Prefer concrete scene tags over generic bg shop
                if not re.fullmatch(r"bg\s+\w+", image_tag, flags=re.I):
                    patch["imageTag"] = image_tag
            if not existing.elementKind:
                patch["elementKind"] = kind
                patch["icon"] = existing.icon or preset["icon"]
                patch["color"] = existing.color or preset["color"]
            merged_tags = list(existing.tags or [])
            for a in aliases + ([name] if name != better else []):
                if a and a not in merged_tags and _normalize_key(a) != _normalize_key(
                    patch.get("name", existing.name)
                ):
                    merged_tags.append(a)
            if merged_tags != list(existing.tags or []):
                patch["tags"] = merged_tags[:12]
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
        from_id = id_by_ref.get(_normalize_key(frm))
        to_id = id_by_ref.get(_normalize_key(to))
        if not from_id:
            matched = _match_location(locations, name=frm, kind=_infer_kind(frm))
            from_id = matched.id if matched else None
        if not to_id:
            matched = _match_location(locations, name=to, kind=_infer_kind(to))
            to_id = matched.id if matched else None
        if not from_id or not to_id or from_id == to_id:
            continue
        key = f"{from_id}->{to_id}"
        if key in link_keys or f"{to_id}->{from_id}" in link_keys:
            continue
        note = str(raw.get("evidence") or "").strip()[:160] or None
        # LLM edges without evidence are often sequential hallucinations
        if source_label == "模型" and not note:
            continue
        link = new_location_link(from_id, to_id, _DEFAULT_LINK_RELATION)
        if note:
            link = link.model_copy(update={"note": note})
        location_links.append(link)
        link_keys.add(key)
        link_keys.add(f"{to_id}->{from_id}")
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
    preserve_ids = pinned_location_ids(project.locations)
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
    working = dedupe_synonym_locations(working)

    def _layout(snapshot: Dict[str, Any]) -> Dict[str, Any]:
        snapshot["locations"] = layout_project_map(
            project,
            list(snapshot.get("locations") or []),
            list(snapshot.get("locationLinks") or []),
            preserve_ids=preserve_ids,
        )
        return snapshot

    if not use_llm:
        working = _layout(working)
        working["warnings"] = list(working.get("warnings") or []) + warnings
        return working

    if config is None or not config.apiKey or "your-key" in config.apiKey:
        warnings.append("未配置 DEEPSEEK_API_KEY，已跳过模型提取（仍使用 scene + 词典）")
        working = _layout(working)
        working["warnings"] = list(working.get("warnings") or []) + warnings
        return working

    if not corpus.strip():
        warnings.append("剧本与设定为空，无法做语义提取")
        working = _layout(working)
        working["warnings"] = list(working.get("warnings") or []) + warnings
        return working

    try:
        # Use locations after lexicon merge as "known" for the model
        known = list(working.get("locations") or [])
        payload = await _call_llm_map_extract(config, project, corpus, known)
        suggestions = _suggestions_from_llm_payload(payload)
        working = merge_suggested_places(
            working, suggestions, source_label="模型"
        )
        working = dedupe_synonym_locations(working)
        working["mode"] = "smart"
        working["llmUsed"] = True
    except Exception as exc:  # noqa: BLE001 — surface to API as warning + partial result
        warnings.append(f"模型提取失败，已保留规则/词典结果：{exc}")
        working["mode"] = "rules+lexicon"
        working["llmUsed"] = False

    working = _layout(working)
    working["warnings"] = list(working.get("warnings") or []) + warnings
    return working


def _as_location(raw: Any) -> Location:
    if isinstance(raw, Location):
        return raw
    return Location.model_validate(raw)


def _as_link(raw: Any) -> LocationLink:
    if isinstance(raw, LocationLink):
        return raw
    return LocationLink.model_validate(raw)


def build_map_extract_proposal(
    project: VnProject, extract_result: Dict[str, Any]
) -> Dict[str, Any]:
    """Diff extract result against current project → reviewable proposal."""
    before_places = {l.id for l in project.locations or []}
    before_links = {l.id for l in project.locationLinks or []}
    locations = [_as_location(l) for l in extract_result.get("locations") or []]
    links = [_as_link(l) for l in extract_result.get("locationLinks") or []]
    new_place_ids = [l.id for l in locations if l.id not in before_places]
    new_link_ids = [l.id for l in links if l.id not in before_links]
    return {
        "locations": [l.model_dump(mode="json") for l in locations],
        "locationLinks": [l.model_dump(mode="json") for l in links],
        "newPlaceIds": new_place_ids,
        "newLinkIds": new_link_ids,
    }


def accept_map_extract_proposal(
    project: VnProject,
    *,
    proposal_locations: List[Any],
    proposal_links: List[Any],
    place_ids: List[str],
    link_ids: List[str],
    new_place_ids: Optional[List[str]] = None,
    new_link_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Merge checked new places/links into the project without moving existing pins.
    """
    prop_locs = [_as_location(l) for l in proposal_locations]
    prop_links = [_as_link(l) for l in proposal_links]
    prop_by_id = {l.id: l for l in prop_locs}
    prop_link_by_id = {l.id: l for l in prop_links}

    allowed_places = set(new_place_ids or prop_by_id.keys())
    allowed_links = set(new_link_ids or prop_link_by_id.keys())
    existing_ids = {l.id for l in project.locations or []}
    existing_link_ids = {l.id for l in project.locationLinks or []}

    selected_places = []
    for pid in place_ids:
        if pid not in prop_by_id:
            raise ValueError(f"未知地点候选：{pid}")
        if pid not in allowed_places and pid not in existing_ids:
            raise ValueError(f"地点不在新增候选中：{pid}")
        if pid in existing_ids:
            continue
        selected_places.append(prop_by_id[pid])

    selected_links = []
    for lid in link_ids:
        if lid not in prop_link_by_id:
            raise ValueError(f"未知通路候选：{lid}")
        if lid not in allowed_links and lid not in existing_link_ids:
            raise ValueError(f"通路不在新增候选中：{lid}")
        if lid in existing_link_ids:
            continue
        selected_links.append(prop_link_by_id[lid])

    locations: List[Location] = []
    for loc in project.locations or []:
        p = prop_by_id.get(loc.id)
        if not p:
            locations.append(loc)
            continue
        updates: Dict[str, Any] = {}
        if not (loc.description or "").strip() and (p.description or "").strip():
            updates["description"] = p.description
        if not (loc.imageTag or "").strip() and (p.imageTag or "").strip():
            updates["imageTag"] = p.imageTag
        if not loc.tags and p.tags:
            updates["tags"] = list(p.tags)
        if not loc.elementKind and p.elementKind:
            updates["elementKind"] = p.elementKind
        if not loc.icon and p.icon:
            updates["icon"] = p.icon
        if not loc.color and p.color:
            updates["color"] = p.color
        locations.append(loc.model_copy(update=updates) if updates else loc)

    locations.extend(selected_places)
    loc_ids = {l.id for l in locations}

    links: List[LocationLink] = list(project.locationLinks or [])
    added_links = 0
    for link in selected_links:
        if link.fromId not in loc_ids or link.toId not in loc_ids:
            continue
        links.append(link)
        added_links += 1

    preserve = pinned_location_ids(locations)
    locations = layout_project_map(
        project, locations, links, preserve_ids=preserve
    )
    return {
        "locations": locations,
        "locationLinks": links,
        "addedCount": len(selected_places),
        "linkCount": added_links,
    }
