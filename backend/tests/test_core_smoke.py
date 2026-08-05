from __future__ import annotations

from app.core import create_demo_project, export_to_renpy, lint_narrative_draft, normalize_project
from app.core.project import extract_map_from_script
from app.core.branch_tree import build_branch_tree


def test_demo_normalize_export():
    p = create_demo_project()
    assert p.title == "雨夜车站"
    assert len(p.characters) >= 2
    text = export_to_renpy(p)
    assert "label start" in text or "label start:" in text or "linxia" in text


def test_lint_and_map():
    p = create_demo_project()
    issues = lint_narrative_draft('"你好吗？"\n"你叫什么？"\n"从哪里来？"')
    assert isinstance(issues, list)
    result = extract_map_from_script(p)
    assert "locations" in result
    tree = build_branch_tree(p)
    assert len(tree) >= 1


def test_map_smart_lexicon_without_llm():
    import asyncio

    from app.core.map_extract_smart import extract_map_smart

    p = create_demo_project()
    ch = p.chapters[0]
    ch.blocks = list(ch.blocks) + [
        {"type": "narration", "text": "他们拐进街角的咖啡馆，点了两杯美式。"},
        {
            "type": "dialogue",
            "characterId": p.characters[0].id,
            "text": "我们去公园走走吧。",
        },
    ]
    p.chapters[0] = ch
    result = asyncio.run(extract_map_smart(p, config=None, use_llm=False))
    names = " ".join(l.name for l in result["locations"])
    assert ("咖啡" in names) or ("公园" in names)
    assert result["llmUsed"] is False


def test_normalize_roundtrip():
    p = create_demo_project()
    raw = p.model_dump(mode="json")
    p2 = normalize_project(raw)
    assert p2.id == p.id
    assert p2.title == p.title
