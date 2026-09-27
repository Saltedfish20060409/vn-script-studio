"""改章方向的解析：「照我说的改」这一档必须真的把话语权交回作者。

背景（用户反馈原话）：三选一那三条方向"很多时候并不符合说的这三种情况，所以不太有用，
更多时候看 Agent 理解"。而改稿提示词里「回炉指引」是**无条件**拼进去的，所以作者说了 A、
指引却在推 B。`follow_note` 这一档就是为它加的。

为什么要专门测：`resolve_mode_hint` 里的回落规则很细——它得同时保证
① 新增的 `follow_note` 真的不推固定方向；
② **既有调用方**（不传 mode 的入口）仍然回落到 `human_warmth`，行为不变。
两件事反向，写歪一个就是线上悄悄改了别人的行为。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.chapter_revise import _MODE_HINTS, FOLLOW_NOTE_MODE, resolve_mode_hint

REPO = Path(__file__).resolve().parent.parent.parent
FRONTEND_PREFS = REPO / "frontend" / "src" / "lib" / "chapterRevisePrefs.ts"


def test_the_three_fixed_modes_are_unchanged():
    """三档固定方向的文案不许被这次改动带走——它们仍是不想细说时的省事选项。"""
    assert "只去说明书" in _MODE_HINTS["cut_lecture"]
    assert "加强人味" in _MODE_HINTS["human_warmth"]
    assert "轻润不改结构" in _MODE_HINTS["light_touch"]


def test_follow_note_delegates_to_the_author_word():
    """这一档必须把话语权交回「用户说明」，而不是又推一个方向。"""
    hint = resolve_mode_hint(FOLLOW_NOTE_MODE)
    assert "按作者说明改" in hint
    assert "以「用户说明」为准" in hint
    # 明确要求"说明没覆盖到的部分尽量原样保留"，否则模型会顺手发挥
    assert "原样保留" in hint
    # 它不能等同于任何一条固定方向
    for other in ("cut_lecture", "human_warmth", "light_touch"):
        assert hint != _MODE_HINTS[other]


def test_missing_or_unknown_mode_still_falls_back_to_human_warmth():
    """**这条是防止改坏既有调用方**：不传 mode（或传了没见过的值）时行为必须与改动前一致。

    改动前的实现是 `mode_key = (mode or "").strip() or "human_warmth"` + 未知值回落，
    这条把那个行为钉住。
    """
    expected = _MODE_HINTS["human_warmth"]
    for value in (None, "", "   ", "unknown_mode", "CUT_LECTURE"):
        assert resolve_mode_hint(value) == expected, f"mode={value!r} 的回落变了"


def test_known_modes_resolve_to_their_own_hint():
    for key in ("cut_lecture", "human_warmth", "light_touch"):
        assert resolve_mode_hint(key) == _MODE_HINTS[key]


def test_frontend_and_backend_agree_on_the_mode_vocabulary():
    """前后端必须用同一个字符串。

    分叉的代价是**静默**的：前端发一个后端不认识的 mode，`resolve_mode_hint` 会安静地按
    `human_warmth` 处理——作者选了「照我说的改」，结果模型收到的却是"加强人味"。
    所以这里直接解析前端源码比对（同 `tests/test_rule_basis.py` 解析 TS 的做法）。
    """
    src = FRONTEND_PREFS.read_text(encoding="utf-8")
    m = re.search(r'FOLLOW_NOTE_MODE:\s*ReviseMode\s*=\s*"([a-z_]+)"', src)
    assert m, "前端没有找到 FOLLOW_NOTE_MODE 常量的定义，结构可能变了"
    assert m.group(1) == FOLLOW_NOTE_MODE, (
        f"前后端的 follow_note 不一致：前端 {m.group(1)!r} / 后端 {FOLLOW_NOTE_MODE!r}"
    )
    # 三个固定方向也要在 TS 的联合类型里（否则前端根本发不出这些值）
    union = re.search(r"export type ReviseMode\s*=\s*([^;]+);", src)
    assert union, "没找到 ReviseMode 联合类型"
    for key in ("cut_lecture", "human_warmth", "light_touch"):
        assert f'"{key}"' in union.group(1), f"前端 ReviseMode 缺 {key}"
