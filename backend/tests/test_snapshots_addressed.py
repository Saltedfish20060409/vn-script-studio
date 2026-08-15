"""P2: content-addressed snapshots."""
from __future__ import annotations

import json

from app.core.demo import create_demo_project
from app.core.snapshots import (
    content_hash_for_payload,
    decode_snapshot_payload,
    latest_content_hash,
    snapshot_payload_dict,
)
from app.domain.types import ProjectSnapshot


def test_content_hash_stable_and_ignores_snapshots_field():
    p = create_demo_project()
    payload = snapshot_payload_dict(p)
    h1 = content_hash_for_payload(payload)
    h2 = content_hash_for_payload(payload)
    assert h1 == h2
    assert "snapshots" not in payload


def test_decode_legacy_string_and_object():
    obj = {"id": "p1", "title": "t", "chapters": []}
    assert decode_snapshot_payload(obj)["title"] == "t"
    assert decode_snapshot_payload(json.dumps(obj, ensure_ascii=False))["id"] == "p1"


def test_dedupe_via_latest_hash():
    p = create_demo_project()
    payload = snapshot_payload_dict(p)
    h = content_hash_for_payload(payload)
    snaps = [
        ProjectSnapshot(
            id="snap-1",
            label="a",
            createdAt="2020-01-01T00:00:00+00:00",
            payload=payload,
            contentHash=h,
        )
    ]
    assert latest_content_hash(snaps) == h
    # Same content → would dedupe
    assert content_hash_for_payload(snapshot_payload_dict(p)) == h
