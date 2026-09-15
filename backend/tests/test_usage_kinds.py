"""AI 能力分类（llm_usage.kind）的测试。

线上曾经的状况：kind 在 llm_http 里写死 "llm"，30 天 448 次调用全是同一个标签，
等于没有任何可分析性。这里钉住"路径 → 能力"的映射和上下文的默认值。
"""

from __future__ import annotations

from app.core.usage import current_usage_kind, set_usage_kind
from app.core.usage_kinds import DEFAULT_KIND, KNOWN_KINDS, kind_for_path, kind_label


def test_paths_map_to_specific_capabilities():
    cases = {
        "/api/v1/projects/p1/agent": "agent",
        "/api/v1/projects/p1/agent/chapter-revise": "chapter_revise",
        "/api/v1/projects/p1/agent/pipeline/run": "pipeline",
        "/api/v1/projects/p1/pipeline/run": "pipeline",
        "/api/v1/projects/p1/pipeline/gate": "finalize",
        "/api/v1/projects/p1/pipeline/ledger/digest": "ledger",
        "/api/v1/projects/p1/generate-rpy": "rpy",
        "/api/v1/projects/p1/map/extract": "map",
        "/api/v1/projects/p1/analysis/facts/scan": "facts",
        "/api/v1/projects/p1/analysis/lint": "lint",
        "/api/v1/projects/p1/analysis/semantic-search": "search",
        "/api/v1/projects/p1/brainstorm": "brainstorm",
        "/api/v1/projects/p1/characters/c1/voice/synthesize": "voice",
        "/api/v1/settings/test-llm": "settings",
    }
    for path, expected in cases.items():
        assert kind_for_path(path) == expected, path


def test_specific_rules_win_over_generic_agent_rule():
    """更具体的路径必须先命中（/agent/pipeline/run 不能被 /agent/ 抢走）。"""
    assert kind_for_path("/api/v1/projects/p1/agent/pipeline/run") == "pipeline"
    assert kind_for_path("/api/v1/projects/p1/agent/chapter-revise") == "chapter_revise"
    assert kind_for_path("/api/v1/projects/p1/agent/conversations") == "agent"


def test_unknown_and_empty_paths_fall_back_to_default():
    assert kind_for_path("/api/v1/projects") == DEFAULT_KIND
    assert kind_for_path("") == DEFAULT_KIND
    assert kind_for_path("/api/v1/projects/p1/export/rpy") == DEFAULT_KIND


def test_query_string_does_not_confuse_matching():
    assert kind_for_path("/api/v1/projects/p1/analysis/lint?full=1") == "lint"


def test_usage_kind_context_defaults_and_resets():
    """没设置时是默认值；设置后能读到；reset 回默认（中间件 finally 会做这件事）。"""
    assert current_usage_kind() == DEFAULT_KIND
    set_usage_kind("facts")
    assert current_usage_kind() == "facts"
    set_usage_kind(None)
    assert current_usage_kind() == DEFAULT_KIND
    set_usage_kind("")
    assert current_usage_kind() == DEFAULT_KIND


def test_every_known_kind_has_a_chinese_label():
    for kind in KNOWN_KINDS:
        assert kind_label(kind) and kind_label(kind) != kind or kind == "llm"
