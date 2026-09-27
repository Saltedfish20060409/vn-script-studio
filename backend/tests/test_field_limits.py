"""长度上限：与数据库列宽一致、与前端一致，且超长给的是 400 而不是 500。

这一组是**纯测试**（不连库），因为实盘那次故障的教训就是：
校验逻辑必须能离线跑，否则"只有线上才第一次执行到"。
"""

from __future__ import annotations

from pathlib import Path

from app.core.field_limits import (
    GENRE_LABEL,
    GENRE_MAX,
    TITLE_LABEL,
    TITLE_MAX,
    clamp,
    limit_error,
)
from app.models import Project


def test_limits_match_the_database_columns():
    """上限的唯一真相是数据库列宽：写错就会在保存那一刻变成 500。"""
    assert Project.__table__.c.title.type.length == TITLE_MAX
    assert Project.__table__.c.genre.type.length == GENRE_MAX


def test_boundary_is_inclusive():
    """正好等于上限要放行（差一就算错，用户会撞上莫名其妙的拒绝）。"""
    assert limit_error(title="字" * TITLE_MAX) is None
    assert limit_error(genre="字" * GENRE_MAX) is None
    assert limit_error(title="字" * (TITLE_MAX + 1)) is not None
    assert limit_error(genre="字" * (GENRE_MAX + 1)) is not None


def test_message_names_the_field_and_both_counts():
    """错误信息必须能直接照着做：哪一项、多少字、上限多少。"""
    too_long = "长" * (GENRE_MAX + 5)
    msg = limit_error(genre=too_long)
    assert msg is not None
    assert GENRE_LABEL in msg
    assert str(GENRE_MAX) in msg
    assert str(GENRE_MAX + 5) in msg
    # 不能把字段名写成 title / genre 这种开发者词
    assert "genre" not in msg

    msg_title = limit_error(title="题" * (TITLE_MAX + 1))
    assert msg_title is not None
    assert TITLE_LABEL in msg_title


def test_none_and_empty_are_fine():
    """没传这个字段（例如只改章节的 scoped 保存）不能被判成超长。"""
    assert limit_error() is None
    assert limit_error(title=None, genre=None) is None
    assert limit_error(title="", genre="") is None


def test_both_over_limit_reports_the_first_one():
    """两个都超长时报一个就够（用户一次修一个），但必须是能读到的那句。"""
    msg = limit_error(title="题" * (TITLE_MAX + 1), genre="类" * (GENRE_MAX + 1))
    assert msg is not None
    assert TITLE_LABEL in msg


def test_clamp_only_truncates_when_needed():
    """内部产生方的最后一道网：只截超长的，其余原样。"""
    assert clamp("短", GENRE_MAX) == "短"
    assert clamp(None, GENRE_MAX) is None
    assert len(clamp("x" * 500, GENRE_MAX) or "") == GENRE_MAX
    # 边界：正好等于上限不截
    exactly = "x" * GENRE_MAX
    assert clamp(exactly, GENRE_MAX) == exactly


def test_frontend_uses_the_same_numbers():
    """前后端各写一份上限必然漂移：前端 maxLength 比后端松，用户就会撞上 400。

    前端 `maxLength` 是"别让用户白打一遍字"的第一道门，后端 400 是兜底；
    两边数字不一致时，第一道门形同虚设。
    """
    path = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "lib"
        / "fieldLimits.ts"
    )
    if not path.exists():  # 只检出后端时跳过，不让测试变成假失败
        return
    text = path.read_text(encoding="utf-8")
    assert f"TITLE_MAX = {TITLE_MAX}" in text, "前端 TITLE_MAX 与后端不一致"
    assert f"GENRE_MAX = {GENRE_MAX}" in text, "前端 GENRE_MAX 与后端不一致"
