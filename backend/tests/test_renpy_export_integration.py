"""Export full-project integration: multi-chapter + menu + jump must yield a
structurally sound .rpy bundle (no duplicate defines, every label present,
indentation correct for Ren'Py)."""

from app.core.renpy import (
    export_character_defines,
    export_project_bundle,
    export_script_rpy,
    export_to_renpy,
)
from app.domain.types import Character, VnProject


def _characters():
    return [
        Character(id="lx", defineName="lx", displayName="林夏", color="#e8b64c"),
        Character(id="zy", defineName="zy", displayName="周屿", color="#7cc4ff"),
    ]


def _two_chapter_project():
    """Chapter 1 has a label + menu jumping to chapter 2's label; chapter 2 returns."""
    return VnProject.model_validate(
        {
            "id": "p",
            "title": "雨夜站台",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "logline": "末班车前的重逢。",
            "genre": "悬疑",
            "characters": [
                {"id": "lx", "defineName": "lx", "displayName": "林夏", "color": "#e8b64c"},
                {"id": "zy", "defineName": "zy", "displayName": "周屿", "color": "#7cc4ff"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "天桥",
                    "synopsis": "过桥，便利店。",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "scene", "image": "bg_street"},
                        {"type": "narration", "text": "雨还在下。"},
                        {
                            "type": "dialogue",
                            "characterId": "zy",
                            "text": "往东走就是那家便利店。",
                        },
                        {
                            "type": "menu",
                            "id": "m1",
                            "prompt": "你怎么知道？",
                            "choices": [
                                {
                                    "text": "跟着他走",
                                    "blocks": [
                                        {
                                            "type": "dialogue",
                                            "characterId": "lx",
                                            "text": "好。",
                                        }
                                    ],
                                },
                                {"text": "问他为何熟悉", "jump": "ch2"},
                            ],
                        },
                        {"type": "return"},
                    ],
                },
                {
                    "id": "ch2",
                    "title": "便利店",
                    "blocks": [
                        {"type": "label", "id": "ch2", "name": "ch2"},
                        {"type": "scene", "image": "bg_shop"},
                        {
                            "type": "dialogue",
                            "characterId": "zy",
                            "text": "她以前常来。",
                        },
                        {"type": "return"},
                    ],
                },
            ],
        }
    )


def test_export_defines_once():
    vn = _two_chapter_project()
    defines = export_character_defines(vn)
    # exactly one define per character, at top level (not inside a label)
    assert defines.count("define lx") == 1
    assert defines.count("define zy") == 1
    assert "    define" not in defines  # no indented (in-label) define


def test_export_all_labels_present():
    vn = _two_chapter_project()
    script = export_script_rpy(vn)
    # every chapter label survives, plus the injected start bridge
    assert "label start:" in script
    assert "label ch2:" in script
    # start bridges to the first real chapter label (not start itself → no self loop)
    assert "jump ch2" in script or "jump start" not in script.split("label start:")[1][:200]


def test_export_no_self_loop_bridge():
    vn = _two_chapter_project()
    script = export_script_rpy(vn)
    # The auto start bridge must not jump to itself.
    bridge = script.split("label start:")[1].split("\n\n")[0]
    assert "jump start" not in bridge


def test_export_menu_jump_targets_exist():
    vn = _two_chapter_project()
    blob = export_to_renpy(vn)
    labels = {ln.split()[1].rstrip(":") for ln in blob.splitlines() if ln.startswith("label ")}
    # menu jump target ch2 must resolve to a label present in the export
    assert "ch2" in labels
    # every jump references an existing label
    for ln in blob.splitlines():
        if ln.strip().startswith("jump "):
            target = ln.strip().split()[1]
            assert target in labels, f"jump target {target} missing label"


def test_export_bundle_has_all_files():
    vn = _two_chapter_project()
    bundle = export_project_bundle(vn)
    assert set(bundle) == {"script.rpy", "options.rpy", "gui.rpy", "README.txt"}
    assert "label start:" in bundle["script.rpy"]
    # gui accent color is a valid hex (M-7 safety)
    assert '"#' in bundle["gui.rpy"]


def test_export_rpy_is_parseable_shape():
    """Rough structural sanity: no bare `scene`, no `menu menu`, labels top-level."""
    vn = _two_chapter_project()
    rpy = export_to_renpy(vn)
    for line in rpy.splitlines():
        s = line.strip()
        if s.startswith("scene"):
            parts = s.split()
            # scene must have an image token after 'scene'
            assert len(parts) >= 2, f"bare scene in export: {s}"
        assert "menu menu" not in s


def test_export_chapter_with_own_start_no_duplicate():
    """A chapter whose only label is `start` must not produce two label start:."""
    vn = VnProject.model_validate(
        {
            "id": "p",
            "title": "test",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [
                {"id": "lx", "defineName": "lx", "displayName": "林夏"}
            ],
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "scene", "image": "bg_a"},
                        {
                            "type": "dialogue",
                            "characterId": "lx",
                            "text": "你好",
                        },
                        {"type": "return"},
                    ],
                }
            ],
        }
    )
    script = export_script_rpy(vn)
    # exactly one `label start:` in the whole file
    assert script.count("label start:") == 1
    # the chapter body itself is present (not swallowed by the empty fallback)
    assert "你好" in script
    # and the placeholder "空项目" must NOT appear
    assert "空项目" not in script
