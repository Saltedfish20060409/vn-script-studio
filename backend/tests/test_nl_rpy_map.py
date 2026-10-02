"""NL↔RPY 映射纯函数测试。"""

from __future__ import annotations

from app.core.nl_rpy_map import (
    build_nl_rpy_map,
    detect_conflict,
    ensure_block_map_ids,
    merge_preserve_structure,
)


def test_ensure_and_conflict():
    blocks = [{"type": "narration", "text": "雨。"}]
    ensured = ensure_block_map_ids(blocks)
    assert ensured[0]["mapId"]
    m = build_nl_rpy_map("雨。", ensured)
    assert detect_conflict("雨。", ensured, m) == "none"
    assert detect_conflict("雨下了。", ensured, m) == "prose"
    other = ensure_block_map_ids([{"type": "narration", "text": "别的"}])
    assert detect_conflict("雨。", other, m) == "blocks"
    assert detect_conflict("变了", other, m) == "both"


def test_merge_preserves_label_and_menu_jump():
    old = ensure_block_map_ids(
        [
            {"type": "label", "id": "start", "name": "start"},
            {
                "type": "menu",
                "id": "m1",
                "choices": [{"text": "走", "jump": "go"}, {"text": "留", "jump": "stay"}],
            },
        ]
    )
    new = [
        {"type": "label", "id": "x", "name": "start", "mapId": old[0]["mapId"]},
        {
            "type": "menu",
            "id": "new",
            "mapId": old[1]["mapId"],
            "choices": [{"text": "走"}, {"text": "留"}],
        },
    ]
    merged, unmapped = merge_preserve_structure(old, new)
    assert merged[0]["id"] == "start"
    assert merged[1]["choices"][0]["jump"] == "go"
    assert unmapped == []
