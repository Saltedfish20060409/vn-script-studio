"""把一次请求（或它派生出的后台任务）归类到具体 AI 能力，用于用量与成本统计。

为什么需要：线上 `llm_usage.kind` 一直是写死的 `"llm"` —— 于是我们只能看到"今天调了
80 次模型"，却不知道钱花在审稿、一致性检查还是地图抽取上。要做"该收缩到哪一小块"的
决策，就必须先有这份分类。

实现方式：在请求中间件里按**路径**判定一次，写进 ContextVar；llm_http 记录用量时读它。
后台任务（pipeline / 回炉）由 asyncio.create_task 派生，会自动继承同一份上下文。
"""

from __future__ import annotations

from typing import Tuple

# 顺序敏感：先匹配更具体的路径。默认 "llm" 表示"其它/未分类"。
_RULES: Tuple[Tuple[str, str], ...] = (
    ("/agent/pipeline/run", "pipeline"),
    ("/pipeline/run", "pipeline"),
    ("/pipeline/gate", "finalize"),
    ("/pipeline/check", "finalize"),
    ("/pipeline/ledger/digest", "ledger"),
    ("/agent/chapter-revise", "chapter_revise"),
    ("/generate-rpy", "rpy"),
    ("/map/extract", "map"),
    ("/analysis/facts/scan", "facts"),
    ("/analysis/facts/reconcile", "facts"),
    ("/analysis/lint", "lint"),
    ("/analysis/semantic-search", "search"),
    ("/brainstorm", "brainstorm"),
    ("/voice/", "voice"),
    ("/settings/test-llm", "settings"),
    ("/settings/ingest", "settings_ingest"),
    # 放最后：更具体的 /agent/pipeline/run、/agent/chapter-revise 已在上面命中
    ("/agent", "agent"),
)

DEFAULT_KIND = "llm"

# 已知分类（管理面板/报表按这个顺序展示，便于横向对比）
KNOWN_KINDS: Tuple[str, ...] = (
    "agent",
    "chapter_revise",
    "pipeline",
    "finalize",
    "rpy",
    "facts",
    "map",
    "voice",
    "brainstorm",
    "search",
    "ledger",
    "lint",
    "settings_ingest",
    "settings",
    "llm",
)

_LABELS = {
    "agent": "AI 责编对话",
    "chapter_revise": "章节回炉/改写",
    "pipeline": "自动写作流水线",
    "finalize": "定稿检查",
    "rpy": "剧本转 RPY",
    "facts": "一致性检查",
    "map": "地图/地点抽取",
    "voice": "角色声音",
    "brainstorm": "头脑风暴",
    "search": "语义检索",
    "ledger": "账本入库",
    "lint": "文风体检",
    "settings_ingest": "设定入库",
    "settings": "模型连通性测试",
    "llm": "未分类/其它",
}


def kind_label(kind: str) -> str:
    return _LABELS.get(kind, kind)


def kind_for_path(path: str) -> str:
    """把请求路径映射成 AI 能力标签（纯函数，方便测试）。"""
    p = (path or "").split("?")[0]
    for needle, kind in _RULES:
        if needle in p:
            return kind
    return DEFAULT_KIND

