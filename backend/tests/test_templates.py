"""Unit tests: starter templates."""

from __future__ import annotations

from app.core.templates import (
    TEMPLATES,
    build_from_template,
    list_template_meta,
)


def test_templates_exist():
    assert len(TEMPLATES) >= 3
    for key in ("slice_of_life", "mystery", "isekai"):
        assert key in TEMPLATES


def test_template_meta_shape():
    meta = list_template_meta()
    assert len(meta) == len(TEMPLATES)
    for m in meta:
        assert m["id"] in TEMPLATES
        assert m["title"]
        assert "characters" in m


def test_build_from_template_fresh_ids():
    a = build_from_template("mystery")
    b = build_from_template("mystery")
    assert a.id != b.id
    assert a.chapters[0].id != b.chapters[0].id
    # Same content otherwise.
    assert a.title == b.title == TEMPLATES["mystery"].title


def test_build_from_template_custom_title():
    p = build_from_template("isekai", title="我的图书馆")
    assert p.title == "我的图书馆"


def test_build_unknown_template_raises():
    try:
        build_from_template("nope")
        assert False, "expected KeyError"
    except KeyError:
        pass
