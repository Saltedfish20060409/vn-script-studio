"""Ported from packages/core/src/project.ts"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Set

from app.domain.types import (
    Location,
    LocationLink,
    ScriptBlock,
    StoryBible,
    VnProject,
)

from .map_catalog import normalize_map_style, preset_by_kind
from .map_layout import layout_project_map, pinned_location_ids

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits: List[str] = []
    while n:
        n, r = divmod(n, 36)
        digits.append(_BASE36[r])
    return "".join(reversed(digits))


def uid(prefix: str) -> str:
    ts = _to_base36(int(time.time() * 1000))
    rand = "".join(random.choice(_BASE36) for _ in range(5))
    return f"{prefix}-{ts}-{rand}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_location_link(
    from_id: str, to_id: str, relation: str = "adjacent"
) -> LocationLink:
    return LocationLink(id=uid("link"), fromId=from_id, toId=to_id, relation=relation)


def normalize_volumes(
    raw_volumes: Any, raw_chapters: Any
) -> tuple[list[dict[str, Any]], list[Any]]:
    """规范化卷与章节归属。

    两条硬约束（都是"删卷/删章"以后最容易留下的残渣）：
    1. 卷必须有 id（缺了补一个）；
    2. ``chapter.volumeId`` 指向不存在的卷时**清空**（而不是留一个悬空 id 让界面找不到归属）。
    另外顺手丢掉既无 id 又无标题的空卷。
    """
    volumes: list[dict[str, Any]] = []
    for item in list(raw_volumes or []):
        if not isinstance(item, dict):
            continue
        vid = str(item.get("id") or "").strip() or uid("vol")
        title = str(item.get("title") or "").strip()
        note = item.get("note")
        if not title and not item.get("id"):
            continue
        volume: dict[str, Any] = {"id": vid, "title": title or "未命名卷"}
        if note:
            volume["note"] = str(note)
        volumes.append(volume)

    valid_ids = {v["id"] for v in volumes}
    chapters: list[Any] = []
    for ch in list(raw_chapters or []):
        if not isinstance(ch, dict):
            chapters.append(ch)
            continue
        vid = ch.get("volumeId")
        if isinstance(vid, str) and vid.strip() and vid not in valid_ids:
            ch = {k: v for k, v in ch.items() if k != "volumeId"}
        chapters.append(ch)
    return volumes, chapters


def _model_field_names() -> set[str]:
    """VnProject 声明的全部字段名（含别名）。

    为什么需要：normalize_project 之前是**手写枚举**要保留哪些字段，于是任何新加的
    模型字段只要忘了补一行，就会在每次保存时被静默丢掉。实测后果：`styleMemory`
    （作者风格记忆）在线上 165 个项目里**全是 null**——功能看着在，数据一次没存住过。
    这里改成"模型声明了哪些字段就透传哪些"，从根上消除这类漏字段。
    """
    names: set[str] = set()
    for name, field in VnProject.model_fields.items():
        names.add(name)
        if field.alias:
            names.add(field.alias)
    return names


def normalize_project(raw: Any = None) -> VnProject:
    if raw is None:
        raw = {}
    elif isinstance(raw, VnProject):
        raw = raw.model_dump(mode="json")
    elif not isinstance(raw, dict):
        raw = dict(raw)
    raw_bible = raw.get("bible") or {}
    if isinstance(raw_bible, StoryBible):
        raw_bible = raw_bible.model_dump()
    bible = StoryBible(
        world=raw_bible.get("world") or raw.get("lore") or "",
        background=raw_bible.get("background") or "",
        outline=raw_bible.get("outline") or "",
        themes=raw_bible.get("themes") or "",
        notes=raw_bible.get("notes") or "",
    )

    raw_chapters = raw.get("chapters")
    chapters = (
        raw_chapters
        if raw_chapters and len(raw_chapters) > 0
        else [
            {
                "id": "ch1",
                "title": "第一章",
                "blocks": [{"type": "label", "id": "start", "name": "start"}],
            }
        ]
    )
    volumes, chapters = normalize_volumes(raw.get("volumes"), chapters)

    # 先透传模型已声明、且调用方确实给了值的字段（避免上面那种"新字段被丢掉"）。
    data: dict[str, Any] = {
        k: v for k, v in raw.items() if k in _model_field_names()
    }
    data.update(
        {
            "id": data.get("id") or f"proj-{int(time.time() * 1000)}",
            "title": data.get("title") or "未命名剧本",
            "characters": data.get("characters") or [],
            "chapters": chapters,
            "volumes": volumes,
            "lore": bible.world,
            "bible": bible,
            "locations": data.get("locations") or [],
            "locationLinks": data.get("locationLinks") or [],
            "mapStyle": normalize_map_style(data.get("mapStyle")),
            "customMapElements": data.get("customMapElements") or [],
            "mapStrokes": data.get("mapStrokes") or [],
            "characterLinks": data.get("characterLinks") or [],
            "timeline": data.get("timeline") or [],
            "variables": data.get("variables") or [],
            "sprites": data.get("sprites") or [],
            "snapshots": data.get("snapshots") or [],
            "updatedAt": data.get("updatedAt") or _now_iso(),
        }
    )
    return VnProject.model_validate(data)


def touch_project(project: VnProject) -> VnProject:
    bible = project.bible or StoryBible()
    new_bible = StoryBible(
        world=bible.world or project.lore or "",
        background=bible.background or "",
        outline=bible.outline or "",
        themes=bible.themes or "",
        notes=bible.notes or "",
    )
    return project.model_copy(
        update={
            "lore": bible.world or project.lore,
            "bible": new_bible,
            "locations": project.locations or [],
            "locationLinks": project.locationLinks or [],
            "mapStyle": normalize_map_style(project.mapStyle),
            "customMapElements": project.customMapElements or [],
            "mapStrokes": project.mapStrokes or [],
            "characterLinks": project.characterLinks or [],
            "timeline": project.timeline or [],
            "variables": project.variables or [],
            "sprites": project.sprites or [],
            "snapshots": project.snapshots or [],
            "chapterIndex": project.chapterIndex,
            "writingLedger": project.writingLedger,
            "harnessRuns": project.harnessRuns,
            "analysisMeta": project.analysisMeta,
            "voiceReports": project.voiceReports,
            "updatedAt": _now_iso(),
        }
    )


def extract_locations_from_script(project: VnProject) -> List[Location]:
    """Pull scene tags from script → locations + sequential links (merge, non-destructive)."""
    return extract_map_from_script(project)["locations"]


def extract_map_from_script(project: VnProject) -> Dict[str, Any]:
    stage_x = 1300
    stage_y = 1050
    preserve_ids = pinned_location_ids(project.locations)
    existing_by_tag: Dict[str, Location] = {}
    for l in project.locations or []:
        if l.imageTag:
            existing_by_tag[_normalize_scene_key(l.imageTag)] = l

    locations: List[Location] = list(project.locations or [])
    added_count = 0

    # Sequential leads_to only within the same chapter (avoid narrative jump edges).
    chapter_orders: List[List[str]] = []

    for ch in project.chapters:
        scenes: List[str] = []

        def _collect(b: ScriptBlock) -> None:
            if b.get("type") == "scene" and str(b.get("image", "")).strip():
                scenes.append(str(b["image"]).strip())

        _walk_blocks(ch.blocks, _collect)

        order_ids: List[str] = []
        seen_in_chapter: Set[str] = set()
        for image in scenes:
            key = _normalize_scene_key(image)
            loc = existing_by_tag.get(key)
            if loc is None:
                preset = _infer_preset_from_scene(image)
                idx = len(locations)
                loc = Location(
                    id=uid("loc"),
                    name=_pretty_scene_name(image),
                    imageTag=image,
                    description="从剧本 scene 自动提取",
                    elementKind=preset["kind"],
                    icon=preset["icon"],
                    color=preset["color"],
                    mapX=stage_x + 200 + (idx % 5) * 320,
                    mapY=stage_y + 280 + (idx // 5) * 260,
                    scale=1,
                    rotation=0,
                )
                locations.append(loc)
                existing_by_tag[key] = loc
                added_count += 1
            elif loc.mapX is None or loc.mapY is None:
                idx = next((i for i, l in enumerate(locations) if l.id == loc.id), -1)
                map_x = stage_x + 200 + (max(0, idx) % 5) * 320
                map_y = stage_y + 280 + (max(0, idx) // 5) * 260
                preset = _infer_preset_from_scene(image)
                updated = loc.model_copy(
                    update={
                        "mapX": loc.mapX if loc.mapX is not None else map_x,
                        "mapY": loc.mapY if loc.mapY is not None else map_y,
                        "icon": loc.icon or preset["icon"],
                        "color": loc.color or preset["color"],
                        "elementKind": loc.elementKind or preset["kind"],
                    }
                )
                locations = [updated if l.id == loc.id else l for l in locations]
                loc = next(l for l in locations if l.id == updated.id)
                existing_by_tag[key] = loc
            if loc.id not in seen_in_chapter:
                seen_in_chapter.add(loc.id)
                order_ids.append(loc.id)
        chapter_orders.append(order_ids)

    old_links = project.locationLinks or []
    link_keys = {f"{l.fromId}->{l.toId}" for l in old_links}
    location_links: List[LocationLink] = list(old_links)
    link_count = 0
    for order_ids in chapter_orders:
        for i in range(len(order_ids) - 1):
            from_id = order_ids[i]
            to_id = order_ids[i + 1]
            if from_id == to_id:
                continue
            key = f"{from_id}->{to_id}"
            if key in link_keys or f"{to_id}->{from_id}" in link_keys:
                continue
            location_links.append(new_location_link(from_id, to_id, "adjacent"))
            link_keys.add(key)
            link_count += 1

    locations = layout_project_map(
        project, locations, location_links, preserve_ids=preserve_ids
    )

    return {
        "locations": locations,
        "locationLinks": location_links,
        "addedCount": added_count,
        "linkCount": link_count,
    }


def _normalize_scene_key(image: str) -> str:
    return re.sub(r"\s+", " ", image.strip().lower())


# Prefer Chinese display names over English slug leftovers from bg tags.
_SCENE_DISPLAY_NAMES: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"station.*hall|hall.*closed|停用站厅|站厅"), "停用站厅"),
    (re.compile(r"maintenance|tunnel|维修|通道"), "维修通道"),
    (re.compile(r"station.*(night|rain)|(night|rain).*station|月台"), "雨夜月台"),
    (re.compile(r"overpass|天桥"), "人行天桥"),
    (re.compile(r"convenience|便利店"), "便利店"),
    (re.compile(r"park.*east|east.*gate|公园东门"), "公园东门"),
    (re.compile(r"\bpark\b|公园"), "公园"),
    (re.compile(r"hospital|医院"), "医院"),
    (re.compile(r"cafe|咖啡"), "咖啡馆"),
    (re.compile(r"school|学校|教室"), "学校"),
    (re.compile(r"bridge|桥"), "桥"),
    (re.compile(r"plaza|广场"), "广场"),
    (re.compile(r"apartment|公寓"), "公寓"),
    (re.compile(r"office|公司|职场"), "公司"),
    (re.compile(r"temple|神社|寺"), "神社"),
    (re.compile(r"forest|林|森"), "树林"),
    (re.compile(r"beach|海边|沙滩"), "海边"),
    (re.compile(r"home|自宅|房间"), "自宅"),
    (re.compile(r"shop|商店|店"), "商店"),
    (re.compile(r"station|车站"), "车站"),
]


def _pretty_scene_name(image: str) -> str:
    s = image.strip()
    for pattern, label in _SCENE_DISPLAY_NAMES:
        if pattern.search(s):
            return label
    name = re.sub(r"^bg[_\s]+", "", s, flags=re.IGNORECASE)
    name = name.replace("_", " ").strip()
    return name or image


_SCENE_PRESET_TABLE = [
    (re.compile(r"station|车站|月台|rail"), "station"),
    (re.compile(r"school|学校|教室|campus"), "school"),
    (re.compile(r"cafe|咖啡|茶"), "cafe"),
    (re.compile(r"home|家|房间|room"), "home"),
    (re.compile(r"park|公园"), "park"),
    (re.compile(r"hospital|医院"), "hospital"),
    (re.compile(r"shop|店|便利|convenience"), "shop"),
    (re.compile(r"office|公司|职场"), "office"),
    (re.compile(r"temple|神社|寺"), "temple"),
    (re.compile(r"forest|林|森"), "forest"),
    (re.compile(r"beach|海|海边"), "beach"),
    (re.compile(r"bridge|桥|通道|tunnel|overpass"), "bridge"),
    (re.compile(r"plaza|广场"), "plaza"),
    (re.compile(r"apartment|公寓"), "apartment"),
]


def _infer_preset_from_scene(image: str) -> Dict[str, str]:
    s = image.lower()
    for pattern, kind in _SCENE_PRESET_TABLE:
        if pattern.search(s):
            p = preset_by_kind(kind)
            return {"kind": p["kind"], "icon": p["icon"], "color": p["color"]}
    p = preset_by_kind("landmark")
    return {"kind": p["kind"], "icon": p["icon"], "color": p["color"]}


def _walk_blocks(
    blocks: List[ScriptBlock], visit: Callable[[ScriptBlock], None]
) -> None:
    for b in blocks:
        visit(b)
        if b.get("type") == "menu":
            for c in b.get("choices", []) or []:
                child_blocks = c.get("blocks") if isinstance(c, dict) else None
                if child_blocks:
                    _walk_blocks(child_blocks, visit)
