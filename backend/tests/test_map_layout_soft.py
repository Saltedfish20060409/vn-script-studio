from __future__ import annotations

import asyncio

from app.core import create_demo_project
from app.core.map_extract_smart import extract_map_smart
from app.core.map_layout import (
    count_edge_crossings,
    layout_story_map,
    segments_properly_cross,
)
from app.domain.types import Location, LocationLink


def test_segments_properly_cross_basic():
    assert segments_properly_cross((0, 0), (2, 2), (0, 2), (2, 0))
    assert not segments_properly_cross((0, 0), (1, 0), (1, 0), (2, 0))  # shared end
    assert not segments_properly_cross((0, 0), (1, 0), (0, 1), (1, 1))  # parallel


def test_crossing_penalty_reduces_x_shape():
    """Four nodes in a classic X should untangle under soft optimization."""
    locs = [
        Location(id="a", name="A", mapX=1400, mapY=1200),
        Location(id="b", name="B", mapX=2200, mapY=2200),
        Location(id="c", name="C", mapX=2200, mapY=1200),
        Location(id="d", name="D", mapX=1400, mapY=2200),
    ]
    links = [
        LocationLink(id="l1", fromId="a", toId="b", relation="adjacent"),
        LocationLink(id="l2", fromId="c", toId="d", relation="adjacent"),
    ]
    before = count_edge_crossings(
        {l.id: (l.mapX or 0, l.mapY or 0) for l in locs},
        [("a", "b"), ("c", "d")],
    )
    assert before == 1
    laid = layout_story_map(locs, links, iterations=120)
    after = count_edge_crossings(
        {l.id: (l.mapX or 0, l.mapY or 0) for l in laid},
        [("a", "b"), ("c", "d")],
    )
    assert after == 0


def test_demo_extract_has_limited_crossings():
    p = create_demo_project()
    p.locations = []
    p.locationLinks = []
    result = asyncio.run(extract_map_smart(p, config=None, use_llm=False))
    pos = {
        l.id: (float(l.mapX or 0), float(l.mapY or 0)) for l in result["locations"]
    }
    edges = [
        (l.fromId, l.toId)
        for l in result["locationLinks"]
        if l.fromId in pos and l.toId in pos
    ]
    crossings = count_edge_crossings(pos, edges)
    # Soft budget: demo graph should stay readable after untangle
    assert crossings <= max(2, len(edges) // 4)
