"""Agent append/replace 写入面（writing_surface）契约。

prose 面：写 prose，blocks 同步（append=末尾追加 raw；replace=全文重排）。
script 面：只写 blocks，不污染 prose。
缺省：prose 非空 → prose；否则 script。
非法值：静默代理 + warnings 留痕（不 400）。
"""

from __future__ import annotations

from app.core.agent import apply_agent_actions, resolve_writing_surface
from app.core.agent_context import chapter_plain
from app.core.project import normalize_project


def _project(*, prose: str = "", blocks=None):
    return normalize_project(
        {
            "id": "p-surface",
            "title": "写入面",
            "characters": [
                {"id": "c1", "displayName": "雪菜", "defineName": "yukina"}
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "prose": prose,
                    "blocks": list(
                        blocks
                        or [
                            {
                                "type": "label",
                                "id": "keep_me",
                                "name": "keep_me",
                            },
                            {
                                "type": "dialogue",
                                "characterId": "c1",
                                "text": "旧对白。",
                            },
                        ]
                    ),
                }
            ],
        }
    )


def test_resolve_writing_surface_proxy_and_illegal():
    warns: list[str] = []
    assert resolve_writing_surface(None, "有正文") == "prose"
    assert resolve_writing_surface(None, "") == "script"
    assert resolve_writing_surface("prose", "") == "prose"
    assert resolve_writing_surface("script", "有正文") == "script"
    assert resolve_writing_surface("mixed", "有正文", warnings=warns) == "prose"
    assert any("非法" in w for w in warns)
    assert resolve_writing_surface("mixed", "", warnings=warns) == "script"
    assert warns.count("writing_surface 非法，已按 prose 非空代理") == 1


def test_default_surface_with_prose_append_updates_chapter_plain():
    proj = _project(prose="开头。")
    old_blocks = list(proj.chapters[0].blocks)
    res = apply_agent_actions(
        proj,
        [{"op": "append_script", "chapterRef": "ch1", "text": "追加段。"}],
    )
    ch = res.project.chapters[0]
    assert "追加段。" in (ch.prose or "")
    assert "开头。" in (ch.prose or "")
    assert "追加段。" in chapter_plain(ch, res.project.characters)
    # 原结构保留，新段以 raw 接在末尾
    assert ch.blocks[0] == old_blocks[0]
    assert ch.blocks[1] == old_blocks[1]
    assert ch.blocks[-1]["type"] == "raw"
    assert "追加段。" in ch.blocks[-1]["code"]
    assert res.skipped == []


def test_default_surface_with_prose_replace_rewrites_prose_and_blocks():
    proj = _project(prose="旧稿全文。")
    res = apply_agent_actions(
        proj,
        [{"op": "replace_script", "chapterRef": "ch1", "text": "全新一版。\n第二行。"}],
    )
    ch = res.project.chapters[0]
    assert ch.prose == "全新一版。\n第二行。"
    assert chapter_plain(ch, res.project.characters).startswith("全新一版")
    assert all(b.get("type") == "raw" for b in ch.blocks)


def test_script_surface_with_prose_does_not_touch_prose():
    prose = "正文档应保持原样。"
    proj = _project(prose=prose)
    res = apply_agent_actions(
        proj,
        [{"op": "append_script", "chapterRef": "ch1", "text": "只进脚本档。"}],
        writing_surface="script",
    )
    ch = res.project.chapters[0]
    assert ch.prose == prose
    assert "只进脚本档。" not in chapter_plain(ch, res.project.characters)
    assert any(
        b.get("type") == "raw" and "只进脚本档。" in str(b.get("code") or "")
        for b in ch.blocks
    )


def test_script_surface_replace_keeps_prose():
    prose = "正文档字节级不变。"
    proj = _project(prose=prose)
    res = apply_agent_actions(
        proj,
        [{"op": "replace_script", "chapterRef": "ch1", "text": "脚本新全文。"}],
        writing_surface="script",
    )
    ch = res.project.chapters[0]
    assert ch.prose == prose
    assert chapter_plain(ch, res.project.characters) == prose
    assert any("脚本新全文。" in str(b.get("code") or "") for b in ch.blocks)


def test_explicit_prose_surface_when_prose_empty():
    proj = _project(prose="")
    res = apply_agent_actions(
        proj,
        [{"op": "append_script", "chapterRef": "ch1", "text": "新建正文。"}],
        writing_surface="prose",
    )
    ch = res.project.chapters[0]
    assert "新建正文。" in (ch.prose or "")
    assert "新建正文。" in chapter_plain(ch, res.project.characters)


def test_forbid_replace_still_allows_append_on_prose_surface():
    proj = _project(prose="已有。")
    res = apply_agent_actions(
        proj,
        [
            {"op": "replace_script", "chapterRef": "ch1", "text": "整章重写。"},
            {"op": "append_script", "chapterRef": "ch1", "text": "仍可追加。"},
        ],
        forbid_replace_script=True,
        writing_surface="prose",
    )
    assert any("replace_script" in s or "整章" in s or "定点" in s for s in res.skipped)
    ch = res.project.chapters[0]
    assert "仍可追加。" in (ch.prose or "")
    assert "整章重写。" not in (ch.prose or "")


def test_illegal_surface_warns_and_proxies():
    proj = _project(prose="有正文。")
    res = apply_agent_actions(
        proj,
        [{"op": "append_script", "chapterRef": "ch1", "text": "代理写 prose。"}],
        writing_surface="auto",
    )
    assert any("非法" in w for w in res.warnings)
    assert "代理写 prose。" in (res.project.chapters[0].prose or "")
    assert res.skipped == []
