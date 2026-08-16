from __future__ import annotations

import asyncio

from app.core import create_demo_project
from app.core.map_extract_smart import extract_map_smart
from app.core.project import _pretty_scene_name, extract_map_from_script


def test_pretty_scene_names_are_chinese():
    assert _pretty_scene_name("bg station_night_rain") == "雨夜月台"
    assert _pretty_scene_name("bg convenience_store") == "便利店"
    assert _pretty_scene_name("bg park_east_gate_rain") == "公园东门"
    assert _pretty_scene_name("bg overpass_rain") == "人行天桥"


def test_scene_links_stay_within_chapter():
    p = create_demo_project()
    p.locations = []
    p.locationLinks = []
    result = extract_map_from_script(p)
    names = {l.id: l.name for l in result["locations"]}
    # Cross-chapter narrative jump must NOT create 便利店 → 停用站厅
    pairs = {
        (names[link.fromId], names[link.toId]) for link in result["locationLinks"]
    }
    assert ("便利店", "停用站厅") not in pairs
    # Within ch2 sequential scene is OK
    assert ("人行天桥", "便利店") in pairs


def test_smart_extract_dedupes_and_names():
    p = create_demo_project()
    p.locations = []
    p.locationLinks = []
    result = asyncio.run(extract_map_smart(p, config=None, use_llm=False))
    names = [l.name for l in result["locations"]]
    joined = " ".join(names)

    # Chinese display names, not English slugs
    assert all(
        not name.replace(" ", "").isascii() or "bg" in name.lower()
        for name in names
    ) or any("\u4e00" <= ch <= "\u9fff" for name in names for ch in name)
    assert "雨夜月台" in names
    assert "便利店" in names
    assert "停用站厅" in names
    assert "公园东门" in names or "公园" in joined

    # No generic duplicates alongside specifics
    assert "商店" not in names
    assert "车站" not in names
    assert "桥" not in names
    assert not any(name.isascii() and " " in name for name in names)

    # No cross-chapter hard link
    name_of = {l.id: l.name for l in result["locations"]}
    pairs = {
        (name_of[link.fromId], name_of[link.toId])
        for link in result["locationLinks"]
    }
    assert ("便利店", "停用站厅") not in pairs
    assert result["addedCount"] >= 4


def test_extract_layout_spreads_nodes():
    import asyncio

    from app.core.map_extract_smart import extract_map_smart

    p = create_demo_project()
    p.locations = []
    p.locationLinks = []
    result = asyncio.run(extract_map_smart(p, config=None, use_llm=False))
    coords = [(l.mapX or 0, l.mapY or 0) for l in result["locations"]]
    assert len(coords) >= 4
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    assert max(xs) - min(xs) > 400
    assert max(ys) - min(ys) > 120
    for i, (x1, y1) in enumerate(coords):
        for x2, y2 in coords[i + 1 :]:
            assert (x1 - x2) ** 2 + (y1 - y2) ** 2 > 80 ** 2
