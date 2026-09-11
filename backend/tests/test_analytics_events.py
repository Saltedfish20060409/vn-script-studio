"""埋点与渠道归因的单元测试（roadmap 方向 B / C）。

覆盖：
- props 白名单过滤（防把正文/密钥写进埋点）；
- 事件名白名单（未知名字被拒）；
- 注册渠道名的清洗（只接受短标识）。
"""

from __future__ import annotations

import pytest

from app.api.v1.auth import _clean_signup_source
from app.core.analytics import (
    EVENT_NAMES,
    SIGNUP,
    sanitize_props,
)


def test_event_names_contains_funnel_nodes():
    for name in (
        "signup",
        "sample_created",
        "project_created",
        "prose_saved",
        "ai_call",
        "rpy_generated",
        "playtest_opened",
        "export_done",
        "share_created",
        "invite_sent",
    ):
        assert name in EVENT_NAMES


def test_sanitize_props_keeps_only_whitelisted_keys():
    props = sanitize_props(
        {
            "source": "bili",
            "kind": "auto",
            "step": 2,
            # 以下都应被丢弃：不在白名单里
            "prose": "这是用户正文，绝不能进埋点",
            "apiKey": "sk-secret",
        }
    )
    assert props == {"source": "bili", "kind": "auto", "step": "2"}
    assert "prose" not in props
    assert "apiKey" not in props


def test_sanitize_props_truncates_long_values_and_drops_containers():
    long_value = "x" * 500
    props = sanitize_props({"source": long_value, "model": {"nested": 1}, "kind": None})
    assert len(props["source"]) == 64
    assert "model" not in props  # 容器类型直接丢
    assert "kind" not in props  # None 丢


def test_sanitize_props_handles_garbage_input():
    assert sanitize_props(None) == {}
    assert sanitize_props("not-a-dict") == {}  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bili", "bili"),
        ("DouYin", "douyin"),
        ("  github  ", "github"),
        ("wechat_mp-1", "wechat_mp-1"),
        ("", None),
        (None, None),
        ("has space", None),
        ("有中文", None),
        ("a" * 100, "a" * 64),
    ],
)
def test_clean_signup_source(raw, expected):
    assert _clean_signup_source(raw) == expected


def test_signup_constant_matches_endpoint_usage():
    """注册端点用的常量名必须与前端/后台一致。"""
    assert SIGNUP == "signup"
