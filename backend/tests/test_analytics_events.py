"""埋点与 props 白名单的单元测试（roadmap 方向 B）。

覆盖：
- props 白名单过滤（防把正文/密钥写进埋点）；
- 事件名白名单（未知名字被拒）。
"""

from __future__ import annotations

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
            "kind": "auto",
            "step": 2,
            # 以下都应被丢弃：不在白名单里
            "prose": "这是用户正文，绝不能进埋点",
            "apiKey": "sk-secret",
            "source": "bili",  # 渠道归因已移除，该键也不再接受
        }
    )
    assert props == {"kind": "auto", "step": "2"}
    assert "prose" not in props
    assert "apiKey" not in props
    assert "source" not in props


def test_sanitize_props_truncates_long_values_and_drops_containers():
    long_value = "x" * 500
    props = sanitize_props({"template": long_value, "model": {"nested": 1}, "kind": None})
    assert len(props["template"]) == 64
    assert "model" not in props  # 容器类型直接丢
    assert "kind" not in props  # None 丢


def test_sanitize_props_handles_garbage_input():
    assert sanitize_props(None) == {}
    assert sanitize_props("not-a-dict") == {}  # type: ignore[arg-type]


def test_signup_constant_matches_endpoint_usage():
    """注册端点用的常量名必须与前端/后台一致。"""
    assert SIGNUP == "signup"
