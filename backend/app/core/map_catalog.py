"""Ported from packages/core/src/mapCatalog.ts"""
from __future__ import annotations

from typing import List, Optional, TypedDict

DEFAULT_MAP_STYLE = "default"


class MapStyleInfo(TypedDict):
    id: str
    name: str
    genre: str
    desc: str


# Single Persona LOC_MAP board — multi-genre skins retired.
MAP_STYLES: List[MapStyleInfo] = [
    {
        "id": DEFAULT_MAP_STYLE,
        "name": "作战图",
        "genre": "Persona",
        "desc": "统一 LOC_MAP 底板",
    },
]


def normalize_map_style(style: Optional[str] = None) -> str:
    """Any legacy / unknown style collapses to the sole board."""
    return DEFAULT_MAP_STYLE


class MapElementPreset(TypedDict):
    kind: str
    name: str
    icon: str
    color: str
    hint: str


# Glyph keys (not emoji) — aligned with frontend mapCatalog
MAP_ELEMENT_PRESETS: List[MapElementPreset] = [
    {"kind": "station", "name": "车站", "icon": "station", "color": "#002fa7", "hint": "月台 / 换乘"},
    {"kind": "plaza", "name": "广场", "icon": "plaza", "color": "#4a5568", "hint": "集会 / 喷泉"},
    {"kind": "park", "name": "公园", "icon": "park", "color": "#0f766e", "hint": "散步 / 约会"},
    {"kind": "hospital", "name": "医院", "icon": "hospital", "color": "#be123c", "hint": "病房 / 走廊"},
    {"kind": "school", "name": "学校", "icon": "school", "color": "#1d4ed8", "hint": "教室 / 天台"},
    {"kind": "cafe", "name": "咖啡馆", "icon": "cafe", "color": "#9a3412", "hint": "闲谈场景"},
    {"kind": "home", "name": "自宅", "icon": "home", "color": "#a16207", "hint": "主角房间"},
    {"kind": "shop", "name": "商店", "icon": "shop", "color": "#0369a1", "hint": "便利店 / 街边"},
    {"kind": "office", "name": "公司", "icon": "office", "color": "#475569", "hint": "写字楼"},
    {"kind": "apartment", "name": "公寓", "icon": "apartment", "color": "#6d28d9", "hint": "合租 / 邻居"},
    {"kind": "temple", "name": "神社/寺", "icon": "temple", "color": "#b91c1c", "hint": "祈愿 / 祭典"},
    {"kind": "forest", "name": "树林", "icon": "forest", "color": "#166534", "hint": "秘密小路"},
    {"kind": "beach", "name": "海边", "icon": "beach", "color": "#0e7490", "hint": "度假线"},
    {"kind": "bridge", "name": "桥", "icon": "bridge", "color": "#64748b", "hint": "分手 / 重逢"},
    {"kind": "landmark", "name": "地标", "icon": "landmark", "color": "#c2410c", "hint": "标志建筑"},
    {"kind": "custom", "name": "自定义", "icon": "custom", "color": "#002fa7", "hint": "自订地点"},
]


def preset_by_kind(kind: Optional[str] = None) -> MapElementPreset:
    for p in MAP_ELEMENT_PRESETS:
        if p["kind"] == kind:
            return p
    for p in MAP_ELEMENT_PRESETS:
        if p["kind"] == "landmark":
            return p
    raise RuntimeError("landmark preset missing")
