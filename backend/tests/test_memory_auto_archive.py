"""章节记忆自动归档的决策逻辑单测（roadmap 方向 F）。

只测纯函数 should_auto_archive：它决定"这次保存要不要重建记忆归档"，
避免每次保存都做无谓计算，也避免永远不生成。
"""

from __future__ import annotations

import pytest

from app.services.novel_memory import AUTO_MIN_SPANS, should_auto_archive


def test_no_archive_before_one_full_span():
    # 9 章：连一个完整跨度（10 章）都不够 → 不归档
    assert should_auto_archive(9, 0, span=10) is False


def test_first_span_completion_triggers():
    # 刚满 10 章、还没有任何归档 → 触发
    assert should_auto_archive(10, 0, span=10) is True
    # 11 章仍然覆盖到 10 → 触发（覆盖目标还是 10，因为 11//10*10 = 10）
    assert should_auto_archive(11, 0, span=10) is True


def test_no_repeat_when_already_covered():
    # 已有归档覆盖到 10，章数还是 10~19 → 不重复归档
    assert should_auto_archive(10, 10, span=10) is False
    assert should_auto_archive(19, 10, span=10) is False


def test_new_span_triggers_again():
    # 攒到 20 章、上次只覆盖到 10 → 再次触发
    assert should_auto_archive(20, 10, span=10) is True
    # 覆盖到 20 之后就不再动
    assert should_auto_archive(20, 20, span=10) is False
    assert should_auto_archive(29, 20, span=10) is False


@pytest.mark.parametrize(
    ("chapters", "latest", "span", "expected"),
    [
        (0, 0, 10, False),
        (-5, 0, 10, False),
        (100, 0, 10, True),
        (100, 100, 10, False),
        (100, 90, 10, True),
        (10, 0, 0, False),  # span 非法 → 不做
    ],
)
def test_edge_cases(chapters, latest, span, expected):
    assert should_auto_archive(chapters, latest, span=span) is expected


def test_min_spans_setting_is_respected():
    # 若要求至少 2 个跨度，则 10 章不够、20 章才触发
    assert should_auto_archive(10, 0, span=10, min_spans=2) is False
    assert should_auto_archive(20, 0, span=10, min_spans=2) is True
    assert AUTO_MIN_SPANS >= 1
