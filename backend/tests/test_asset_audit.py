"""素材引用审计：清单 + 疑似写错的图像名。"""

from __future__ import annotations

from app.core.asset_audit import audit_assets
from app.core.project import normalize_project


def _project(blocks, sprites=None, characters=None):  # noqa: ANN001
    return normalize_project(
        {
            "id": "p1",
            "title": "T",
            "characters": characters or [],
            "sprites": sprites or [],
            "chapters": [{"id": "ch1", "title": "第一章", "blocks": blocks}],
        }
    )


def test_lists_images_and_audio_references():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "scene", "image": "bg station_night"},
        {"type": "show", "image": "linxia sad"},
        {"type": "music", "action": "play", "file": "bgm/rain.ogg"},
        {"type": "sound", "action": "play", "file": "sfx/door.mp3"},
        {"type": "voice", "action": "play", "file": "voice/y01.ogg"},
        {"type": "music", "action": "stop"},
        {"type": "hide", "image": "linxia sad"},
    ]
    out = audit_assets(
        _project(
            blocks,
            sprites=[
                {
                    "id": "s1",
                    "name": "林夏",
                    "imageTag": "linxia",
                    "expressions": [{"id": "e1", "name": "普通", "tag": "sad"}],
                }
            ],
        )
    )
    assert out["images"]["total"] == 2
    assert out["audio"]["music"]["total"] == 1
    assert out["audio"]["sound"]["items"][0]["file"] == "sfx/door.mp3"
    assert out["audio"]["voice"]["total"] == 1
    # stop 指令不该被算成素材引用
    assert all(i["file"] != "" for i in out["audio"]["music"]["items"])


def test_flags_image_names_without_matching_tag():
    blocks = [
        {"type": "scene", "image": "bg room"},
        {"type": "show", "image": "linxa sad"},  # 拼错：linxa
    ]
    out = audit_assets(
        _project(
            blocks,
            sprites=[
                {"id": "s1", "name": "林夏", "imageTag": "linxia", "expressions": []}
            ],
        )
    )
    suspicious = [s["image"] for s in out["images"]["suspicious"]]
    assert "linxa sad" in suspicious
    # bg/cg 是通用命名约定，不该被误报（否则每个项目都是一片红）
    assert "bg room" not in suspicious


def test_character_image_tag_counts_as_declared():
    blocks = [{"type": "show", "image": "linxia happy"}]
    out = audit_assets(
        _project(
            blocks,
            characters=[
                {
                    "id": "c1",
                    "defineName": "linxia",
                    "displayName": "林夏",
                    "imageTag": "linxia",
                }
            ],
        )
    )
    assert out["images"]["suspicious"] == []
    assert "linxia" in out["declaredTags"]


def test_reports_unused_declared_tags():
    out = audit_assets(
        _project(
            [{"type": "scene", "image": "bg room"}],
            sprites=[
                {"id": "s1", "name": "A", "imageTag": "linxia", "expressions": []},
                {"id": "s2", "name": "B", "imageTag": "yuki", "expressions": []},
            ],
        )
    )
    assert out["unusedTags"] == ["linxia", "yuki"]


def test_counts_references_inside_branches_and_choices():
    blocks = [
        {
            "type": "if",
            "branches": [
                {
                    "condition": "affection >= 1",
                    "blocks": [{"type": "show", "image": "linxia happy"}],
                }
            ],
        },
        {
            "type": "menu",
            "id": "m",
            "choices": [
                {"text": "走", "blocks": [{"type": "scene", "image": "bg park"}]}
            ],
        },
    ]
    out = audit_assets(
        _project(
            blocks,
            sprites=[{"id": "s1", "name": "A", "imageTag": "linxia", "expressions": []}],
        )
    )
    names = {i["image"] for i in out["images"]["items"]}
    assert names == {"linxia happy", "bg park"}
