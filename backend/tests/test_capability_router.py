"""P4/P5 capability_router 纯函数守卫（不依赖 DB）。"""

from __future__ import annotations

import pytest

from app.core.capability_router import (
    ALL_WRITE_OPS,
    CAPABILITIES,
    CONDENSE_HOOK_PRIORITY,
    P4_WRITE_OPS,
    P5_WRITE_OPS,
    assert_known_capability,
    resolve_write_op,
    write_op_framing,
)


def test_capability_table_has_four():
    assert CAPABILITIES == frozenset({"write", "critique", "ingest", "chat"})


def test_write_op_sets():
    assert P4_WRITE_OPS == frozenset({"continue", "rewrite"})
    assert P5_WRITE_OPS == frozenset(
        {"polish", "expand", "condense", "style_transfer"}
    )
    assert ALL_WRITE_OPS == P4_WRITE_OPS | P5_WRITE_OPS


@pytest.mark.parametrize(
    "write_op,selection,expected",
    [
        (None, None, "continue"),
        (None, "", "continue"),
        (None, "选区", "rewrite"),
        ("continue", "选区", "continue"),
        ("rewrite", None, "rewrite"),
    ],
)
def test_resolve_write_op_defaults(write_op, selection, expected):
    r = resolve_write_op(write_op, selection=selection)
    assert r.ok is True
    assert r.write_op == expected


@pytest.mark.parametrize("op", sorted(P5_WRITE_OPS))
def test_resolve_write_op_accepts_p5(op):
    r = resolve_write_op(op)
    assert r.ok is True
    assert r.write_op == op
    assert r.error is None


def test_resolve_write_op_rejects_unknown():
    r = resolve_write_op("nope")
    assert r.ok is False
    assert "未知" in (r.error or "")


def test_assert_known_capability():
    assert_known_capability("write")
    with pytest.raises(ValueError, match="未知 capability"):
        assert_known_capability("dance")


def test_write_op_framing_continue_rewrite():
    c = write_op_framing("continue")
    r = write_op_framing("rewrite")
    assert "continue" in c and "续写" in c
    assert "rewrite" in r and "改写" in r
    assert c != r


@pytest.mark.parametrize("op", sorted(P5_WRITE_OPS))
def test_write_op_framing_p5(op):
    frame = write_op_framing(op)
    assert f"write_op={op}" in frame
    assert "自然语言" in frame or "风格迁移" in frame


def test_condense_framing_hook_priority():
    frame = write_op_framing("condense")
    assert CONDENSE_HOOK_PRIORITY in frame
    assert "钩子" in frame


def test_style_transfer_framing_includes_contract():
    frame = write_op_framing("style_transfer")
    assert "风格迁移" in frame
    assert "差异" in frame
