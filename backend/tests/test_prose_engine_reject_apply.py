"""P4.5：prose 面引擎语法硬拒 + flag 回滚。"""

from __future__ import annotations

from app.core.agent import apply_agent_actions
from app.core.prose_engine_syntax import PROSE_ENGINE_PATCH_MSG, PROSE_ENGINE_REJECT_MSG
from app.core.project import normalize_project


def _project(*, prose: str = "旧稿。", blocks=None):
    return normalize_project(
        {
            "id": "p-eng",
            "title": "引擎护栏",
            "characters": [
                {"id": "c1", "displayName": "雪菜", "defineName": "yukina"}
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "一",
                    "prose": prose,
                    "blocks": list(
                        blocks
                        or [
                            {"type": "label", "id": "start", "name": "start"},
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


def test_prose_append_with_label_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.core.prose_engine_syntax.prose_engine_reject_enabled", lambda: True
    )
    proj = _project()
    res = apply_agent_actions(
        proj,
        [
            {
                "op": "append_script",
                "chapterRef": "ch1",
                "text": 'label start:\n    yukina "hi"',
            }
        ],
        writing_surface="prose",
    )
    assert PROSE_ENGINE_REJECT_MSG in res.skipped
    assert res.project.chapters[0].prose == "旧稿。"


def test_prose_replace_with_fade_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.core.prose_engine_syntax.prose_engine_reject_enabled", lambda: True
    )
    proj = _project()
    res = apply_agent_actions(
        proj,
        [{"op": "replace_script", "chapterRef": "ch1", "text": "with fade\n雨。"}],
        writing_surface="prose",
    )
    assert PROSE_ENGINE_REJECT_MSG in res.skipped
    assert res.project.chapters[0].prose == "旧稿。"


def test_prose_append_natural_language_ok(monkeypatch):
    monkeypatch.setattr(
        "app.core.prose_engine_syntax.prose_engine_reject_enabled", lambda: True
    )
    proj = _project()
    res = apply_agent_actions(
        proj,
        [{"op": "append_script", "chapterRef": "ch1", "text": "雪菜：「别叫我。」"}],
        writing_surface="prose",
    )
    assert not any(PROSE_ENGINE_REJECT_MSG in s for s in res.skipped)
    assert "别叫我" in (res.project.chapters[0].prose or "")


def test_script_surface_allows_engine_syntax(monkeypatch):
    monkeypatch.setattr(
        "app.core.prose_engine_syntax.prose_engine_reject_enabled", lambda: True
    )
    prose = "正文档不动。"
    proj = _project(prose=prose)
    res = apply_agent_actions(
        proj,
        [
            {
                "op": "append_script",
                "chapterRef": "ch1",
                "text": "$ player_name = \"x\"",
            }
        ],
        writing_surface="script",
    )
    assert res.project.chapters[0].prose == prose
    assert any(
        b.get("type") == "raw" and "player_name" in str(b.get("code") or "")
        for b in res.project.chapters[0].blocks
    )


def test_patch_filters_dirty_replace_keeps_clean(monkeypatch):
    monkeypatch.setattr(
        "app.core.prose_engine_syntax.prose_engine_reject_enabled", lambda: True
    )
    proj = _project(prose="雪菜：「别叫我。」还有一句。")
    res = apply_agent_actions(
        proj,
        [
            {
                "op": "patch_script",
                "chapterRef": "ch1",
                "edits": [
                    {
                        "find": "别叫我",
                        "replace": "$ player_name = \"x\"",
                    },
                    {"find": "还有一句。", "replace": "还有一句！"},
                ],
            }
        ],
        writing_surface="prose",
    )
    assert any("第 1 条" in s for s in res.skipped)
    assert PROSE_ENGINE_PATCH_MSG.format(n=1) in res.skipped
    assert "还有一句！" in (res.project.chapters[0].prose or "")
    assert "$ player_name" not in (res.project.chapters[0].prose or "")


def test_flag_off_allows_prose_engine(monkeypatch):
    monkeypatch.setattr(
        "app.core.prose_engine_syntax.prose_engine_reject_enabled", lambda: False
    )
    proj = _project()
    res = apply_agent_actions(
        proj,
        [
            {
                "op": "append_script",
                "chapterRef": "ch1",
                "text": "label start:\n    \"雨。\"",
            }
        ],
        writing_surface="prose",
    )
    assert not any(PROSE_ENGINE_REJECT_MSG in s for s in res.skipped)
    assert "label start" in (res.project.chapters[0].prose or "")
