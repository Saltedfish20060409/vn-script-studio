from __future__ import annotations

import asyncio

from app.core import create_demo_project
from app.core.map_extract_smart import (
    accept_map_extract_proposal,
    build_map_extract_proposal,
    extract_map_smart,
)
from app.core.project import extract_map_from_script
from app.domain.types import Location


def test_extract_preserves_existing_pin_coords():
    p = create_demo_project()
    pinned = Location(
        id="loc_hand",
        name="手排车站",
        imageTag="bg station_night_rain",
        mapX=1500.0,
        mapY=1200.0,
        elementKind="station",
    )
    p.locations = [pinned]
    p.locationLinks = []

    result = extract_map_from_script(p)
    kept = next(l for l in result["locations"] if l.id == "loc_hand")
    assert kept.mapX == 1500.0
    assert kept.mapY == 1200.0
    assert result["addedCount"] >= 1


def test_proposal_lists_only_new_ids():
    p = create_demo_project()
    p.locations = [
        Location(
            id="loc_keep",
            name="已有点",
            imageTag="bg park_east_gate_rain",
            mapX=1600.0,
            mapY=1300.0,
        )
    ]
    p.locationLinks = []
    result = extract_map_from_script(p)
    proposal = build_map_extract_proposal(p, result)
    assert "loc_keep" not in proposal["newPlaceIds"]
    assert all(pid != "loc_keep" for pid in proposal["newPlaceIds"])
    assert len(proposal["newPlaceIds"]) == result["addedCount"]


def test_accept_merges_selection_without_moving_pins():
    p = create_demo_project()
    p.locations = [
        Location(
            id="loc_hand",
            name="手排点",
            imageTag="bg overpass_rain",
            mapX=1410.0,
            mapY=1110.0,
            elementKind="bridge",
        )
    ]
    p.locationLinks = []

    result = asyncio.run(extract_map_smart(p, config=None, use_llm=False))
    proposal = build_map_extract_proposal(p, result)
    assert proposal["newPlaceIds"], "demo script should yield new places"

    take = proposal["newPlaceIds"][:1]
    skip = set(proposal["newPlaceIds"][1:])
    take_links = proposal["newLinkIds"][:1] if proposal["newLinkIds"] else []

    merged = accept_map_extract_proposal(
        p,
        proposal_locations=proposal["locations"],
        proposal_links=proposal["locationLinks"],
        place_ids=take,
        link_ids=take_links,
        new_place_ids=proposal["newPlaceIds"],
        new_link_ids=proposal["newLinkIds"],
    )

    by_id = {l.id: l for l in merged["locations"]}
    assert by_id["loc_hand"].mapX == 1410.0
    assert by_id["loc_hand"].mapY == 1110.0
    assert take[0] in by_id
    for sid in skip:
        assert sid not in by_id
    assert merged["addedCount"] == 1


def test_accept_empty_selection_is_noop():
    p = create_demo_project()
    p.locations = [
        Location(id="loc_a", name="A", mapX=1500.0, mapY=1200.0)
    ]
    p.locationLinks = []
    result = extract_map_from_script(p)
    proposal = build_map_extract_proposal(p, result)
    merged = accept_map_extract_proposal(
        p,
        proposal_locations=proposal["locations"],
        proposal_links=proposal["locationLinks"],
        place_ids=[],
        link_ids=[],
        new_place_ids=proposal["newPlaceIds"],
        new_link_ids=proposal["newLinkIds"],
    )
    assert len(merged["locations"]) == 1
    assert merged["locations"][0].id == "loc_a"
    assert merged["locations"][0].mapX == 1500.0
    assert merged["addedCount"] == 0
    assert merged["linkCount"] == 0
