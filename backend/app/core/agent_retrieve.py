"""写路径材料取回：上下文被裁时，服务端确定性补料（不靠模型记得调用工具）。

定位：
- 软约束「请用 get_chapter」经常被忽略 → 裁掉 lore / 焦点章截断时，写作前**先跑工具**，
  把结果以 tool_result 形态注入对话，再让模型写。
- 可测：给定 truncated / droppedSections，断言会规划并执行哪些工具。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.core.agent_context import AgentContextResult
from app.core.agent_tools import run_agent_tool
from app.domain.types import VnProject

#: 写路径任务：产出正文前可做材料预取
WRITE_PREFETCH_TASKS = frozenset({"continue", "scene", "rewrite", "polish", "branch"})

#: 被裁掉时值得预取的块 → 工具
_DROP_TO_TOOL: Dict[str, str] = {
    "lore": "search_lore",
    "loreLinks": "search_lore",
    "otherChapters": "search_script",
    "longMemory": "get_chapter",
    "globalMemory": "get_chapter",
}


@dataclass
class PrefetchCall:
    name: str
    arguments: Dict[str, Any]
    reason: str


@dataclass
class PrefetchReport:
    calls: List[PrefetchCall] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)

    def as_meta(self) -> Dict[str, Any]:
        return {
            "callCount": len(self.calls),
            "calls": [
                {"name": c.name, "arguments": c.arguments, "reason": c.reason}
                for c in self.calls[:6]
            ],
            "okCount": sum(1 for r in self.results if r.get("ok")),
        }

    def as_messages(self) -> List[Dict[str, str]]:
        """注入到 agent messages：模拟已执行的工具结果，供本轮写作直接用。"""
        if not self.results:
            return []
        parts = [
            "【系统预取】本轮上下文因篇幅裁过，已自动取回下列材料（勿再声称「没看到」）："
        ]
        for r in self.results[:4]:
            name = str(r.get("name") or "tool")
            ok = "ok" if r.get("ok") else "fail"
            preview = str(r.get("preview") or "")[:4000]
            parts.append(f"\n### {name} ({ok})\n{preview}")
        return [{"role": "user", "content": "\n".join(parts)}]


def _dropped_keys(ctx: AgentContextResult) -> List[str]:
    report = getattr(ctx, "budgetReport", None) or {}
    keys: List[str] = []
    for row in report.get("droppedSections") or []:
        if isinstance(row, dict):
            k = str(row.get("key") or "").strip()
        else:
            k = str(row).strip()
        if k:
            keys.append(k)
    return keys


def _focus_was_trimmed(ctx: AgentContextResult) -> bool:
    report = getattr(ctx, "budgetReport", None) or {}
    for row in report.get("trimmedParts") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        label = str(row.get("label") or "")
        if kind in ("focus", "chapter", "currentChapter") or "当前章" in label:
            return True
        if "keptChars" in row or "focus" in kind.lower():
            return True
    # included 标记：当前章截断:N/M字
    for item in getattr(ctx, "included", None) or []:
        if isinstance(item, str) and item.startswith("当前章截断"):
            return True
    return bool(getattr(ctx, "truncated", False) and not _dropped_keys(ctx))


def _query_tokens(user_message: str, limit: int = 4) -> str:
    raw = (user_message or "").strip()
    if not raw:
        return "设定"
    # 抽中文词块 / 拉丁词
    parts = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{2,}", raw)
    if not parts:
        return raw[:24] or "设定"
    # 去重保序
    seen: set[str] = set()
    out: List[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= limit:
            break
    return " ".join(out)


def plan_write_prefetch(
    ctx: AgentContextResult,
    *,
    task: str,
    chapter_id: Optional[str] = None,
    user_message: str = "",
) -> List[PrefetchCall]:
    """根据上下文裁剪情况规划要预取的工具调用（不执行）。"""
    if (task or "") not in WRITE_PREFETCH_TASKS:
        return []
    calls: List[PrefetchCall] = []
    seen: set[str] = set()

    def _add(name: str, arguments: Dict[str, Any], reason: str) -> None:
        key = f"{name}:{sorted(arguments.items())}"
        if key in seen:
            return
        seen.add(key)
        calls.append(PrefetchCall(name=name, arguments=arguments, reason=reason))

    if _focus_was_trimmed(ctx) or (
        getattr(ctx, "truncated", False) and chapter_id
    ):
        # 焦点章被截：把整章（或更大窗口）取回来，写作才接得上
        args: Dict[str, Any] = {"maxChars": 16000}
        if chapter_id:
            args["chapterRef"] = chapter_id
        _add("get_chapter", args, "当前章正文被截断或上下文已裁，预取完整焦点章")

    for key in _dropped_keys(ctx):
        tool = _DROP_TO_TOOL.get(key)
        if not tool:
            continue
        if tool == "search_lore":
            _add(
                "search_lore",
                {"query": _query_tokens(user_message), "limit": 6},
                f"篇幅省去了「{key}」，预取相关设定",
            )
        elif tool == "search_script":
            _add(
                "search_script",
                {"query": _query_tokens(user_message), "limit": 6},
                f"篇幅省去了「{key}」，预取相关章节片段",
            )
        elif tool == "get_chapter" and chapter_id:
            _add(
                "get_chapter",
                {"chapterRef": chapter_id, "maxChars": 16000},
                f"篇幅省去了「{key}」，预取焦点章正文兜底",
            )

    return calls[:4]


def run_write_prefetch(
    project: VnProject,
    ctx: AgentContextResult,
    *,
    task: str,
    chapter_id: Optional[str] = None,
    user_message: str = "",
) -> PrefetchReport:
    """规划并执行预取；失败的工具记入 results，不抛。"""
    planned = plan_write_prefetch(
        ctx, task=task, chapter_id=chapter_id, user_message=user_message
    )
    report = PrefetchReport(calls=planned)
    for call in planned:
        ok, preview = run_agent_tool(
            call.name,
            call.arguments,
            project=project,
            chapter_id=chapter_id,
        )
        report.results.append(
            {
                "name": call.name,
                "ok": ok,
                "preview": preview,
                "reason": call.reason,
            }
        )
    return report


def should_prefetch(task: str, ctx: AgentContextResult) -> bool:
    if (task or "") not in WRITE_PREFETCH_TASKS:
        return False
    if getattr(ctx, "truncated", False):
        return True
    if _dropped_keys(ctx):
        return True
    if _focus_was_trimmed(ctx):
        return True
    return False
