from __future__ import annotations

from app.core import create_demo_project, export_to_renpy, lint_narrative_draft, normalize_project
from app.core.project import extract_map_from_script
from app.core.branch_tree import build_branch_tree


def test_demo_normalize_export():
    p = create_demo_project()
    assert p.title == "雨夜车站"
    assert len(p.characters) >= 2
    assert len(p.chapters) >= 4
    text = export_to_renpy(p)
    assert "label start" in text or "label start:" in text or "linxia" in text


def test_lint_and_map():
    p = create_demo_project()
    issues = lint_narrative_draft('"你好吗？"\n"你叫什么？"\n"从哪里来？"')
    assert isinstance(issues, list)
    result = extract_map_from_script(p)
    assert "locations" in result
    assert len(result["locations"]) >= 4
    tree = build_branch_tree(p)
    assert len(tree) >= 1


def test_map_smart_lexicon_without_llm():
    import asyncio

    from app.core.map_extract_smart import extract_map_smart

    p = create_demo_project()
    p.locations = []
    p.locationLinks = []
    result = asyncio.run(extract_map_smart(p, config=None, use_llm=False))
    names = " ".join(l.name for l in result["locations"])
    assert "便利店" in names
    assert "公园" in names
    assert "医院" in names
    assert result["llmUsed"] is False
    assert result["addedCount"] >= 4
    # Slug leftovers should be gone after naming + dedupe
    assert "station night" not in names.lower()
    assert "convenience store" not in names.lower()

def test_normalize_roundtrip():
    p = create_demo_project()
    raw = p.model_dump(mode="json")
    p2 = normalize_project(raw)
    assert p2.id == p.id
    assert p2.title == p.title


def test_renpy_project_bundle():
    from app.core.renpy import export_project_bundle, export_script_rpy

    p = create_demo_project()
    files = export_project_bundle(p)
    assert set(files) == {"script.rpy", "options.rpy", "gui.rpy", "README.txt"}
    script = export_script_rpy(p)
    assert "label start:" in script
    # start bridges to the first chapter label
    bridge = script.split("label start:")[1].split("\n")[1]
    assert bridge.strip().startswith("jump ")
    assert "define config.name" in files["options.rpy"]
    assert "define gui.accent_color" in files["gui.rpy"]
