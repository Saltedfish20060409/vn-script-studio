"""Writing Turn 写路径上下文拼装（ADR 0001 P2 / P2.5）。

透镜注入策略（写路径）：
- 来源：`VnProject.authorLenses` 或本轮 `lens_ids` 覆盖；
- 装配：`build_lens_prompt_for_project(..., intent="write", total_budget=LENS_BUDGET_CHARS)`；
- 冲突优先级：StyleSkill（style_guide）> mentor（默认不注入）> lens > 本轮用户指令微调；
- 风格迁移另见 `pipeline/style_transfer_contract.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

#: 写路径对话史预算（字符）
CHAT_HISTORY_MAX_CHARS = 4000
#: 写入 system 的 bible 摘要
BIBLE_BRIEF_MAX_CHARS = 2400
#: 透镜注入预算（写路径比审阅环更短）
LENS_BUDGET_CHARS = 2800
#: style_skill 写路径预算（判定侧仍用更大块；生成侧只带硬约束头）
STYLE_SKILL_WRITE_MAX_CHARS = 1600
#: 章尾可见正文（相对 P1 的 1200 放宽，仍远小于全章倾倒）
CHAPTER_TAIL_MAX_CHARS = 6000
#: project_to_context 节选
PROJECT_CONTEXT_MAX_CHARS = 4500
#: 长程 / 全局记忆单块
LONG_MEMORY_MAX_CHARS = 4000
GLOBAL_MEMORY_MAX_CHARS = 3000


@dataclass
class WriteContextBundle:
    """供 `stage_write` / 单测核对的拼装结果。"""

    system_extra: str = ""
    chat_block: str = ""
    bible_block: str = ""
    lens_block: str = ""
    style_block: str = ""
    long_memory: str = ""
    global_memory: str = ""
    chapter_tail_limit: int = CHAPTER_TAIL_MAX_CHARS
    project_context_limit: int = PROJECT_CONTEXT_MAX_CHARS
    included: List[str] = field(default_factory=list)


def _clip(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0 or len(t) <= max_chars:
        return t
    return t[: max(0, max_chars - 12)].rstrip() + "\n…(截断)"


def format_chat_history(
    messages: Optional[Sequence[Any]],
    *,
    max_chars: int = CHAT_HISTORY_MAX_CHARS,
    max_turns: int = 12,
) -> str:
    """把会话 messages 收成写路径可读的对话块。"""
    if not messages:
        return ""
    lines: List[str] = []
    # 只取尾部若干轮，避免整段日志淹没正文指令
    tail = list(messages)[-max_turns:]
    for m in tail:
        if isinstance(m, dict):
            role = str(m.get("role") or "")
            content = str(m.get("content") or "")
        else:
            role = str(getattr(m, "role", "") or "")
            content = str(getattr(m, "content", "") or "")
        content = content.strip()
        if not content:
            continue
        label = "作者" if role == "user" else ("助手" if role == "assistant" else role or "消息")
        # 单条过长时先裁，避免一轮占满预算
        if len(content) > 1200:
            content = content[:1188].rstrip() + "…(截断)"
        lines.append(f"{label}：{content}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return "## 最近对话\n" + _clip(body, max_chars)


def format_bible_brief(project: Any, *, max_chars: int = BIBLE_BRIEF_MAX_CHARS) -> str:
    bible = getattr(project, "bible", None)
    if bible is None and isinstance(project, dict):
        bible = project.get("bible")
    if not bible:
        return ""
    def _get(obj: Any, key: str) -> str:
        if isinstance(obj, dict):
            return str(obj.get(key) or "").strip()
        return str(getattr(obj, key, "") or "").strip()

    parts = []
    for key, label in (
        ("world", "世界观"),
        ("background", "背景"),
        ("outline", "大纲"),
        ("themes", "主题/禁忌"),
        ("notes", "备忘"),
    ):
        val = _get(bible, key)
        if val:
            parts.append(f"### {label}\n{val}")
    if not parts:
        return ""
    return "## 设定 bible\n" + _clip("\n\n".join(parts), max_chars)


def assemble_write_context(
    project: Any,
    *,
    messages: Optional[Sequence[Any]] = None,
    chat_memory: str = "",
    long_memory: str = "",
    global_memory: str = "",
    lens_ids: Optional[Sequence[str]] = None,
    include_lenses: bool = True,
    include_style_skill: bool = True,
    include_bible: bool = True,
) -> WriteContextBundle:
    """组装写路径上下文；`included` 列出实际进 prompt 的块名（供单测与 meta）。"""
    included: List[str] = []
    system_parts: List[str] = []

    bible_block = format_bible_brief(project) if include_bible else ""
    if bible_block:
        included.append("bible")
        system_parts.append(bible_block)

    lens_block = ""
    if include_lenses:
        try:
            from app.core.lenses import build_lens_prompt_for_project

            lens_block = (
                build_lens_prompt_for_project(
                    project,
                    override_ids=list(lens_ids) if lens_ids is not None else None,
                    intent="write",
                    total_budget=LENS_BUDGET_CHARS,
                )
                or ""
            ).strip()
        except Exception:  # noqa: BLE001 — 透镜失败不该挡写作
            lens_block = ""
        if lens_block:
            included.append("lens")
            system_parts.append(lens_block)

    style_block = ""
    if include_style_skill:
        try:
            from app.core.pipeline.style_skill import load_style_skill

            style_block = load_style_skill().prompt_block(
                max_chars=STYLE_SKILL_WRITE_MAX_CHARS
            )
        except Exception:  # noqa: BLE001
            style_block = ""
        if style_block.strip():
            included.append("style_skill")
            system_parts.append(style_block.strip())

    chat_block = format_chat_history(messages)
    mem = (chat_memory or "").strip()
    if mem:
        chat_extra = "## 对话记忆摘要\n" + _clip(mem, 2000)
        chat_block = (
            (chat_block + "\n\n" + chat_extra).strip()
            if chat_block
            else chat_extra
        )
    if chat_block:
        included.append("chat_history")

    long_m = _clip(long_memory, LONG_MEMORY_MAX_CHARS)
    if long_m:
        included.append("long_memory")
        if not long_m.startswith("#"):
            long_m = "## 长程章节记忆\n" + long_m

    global_m = _clip(global_memory, GLOBAL_MEMORY_MAX_CHARS)
    if global_m:
        included.append("global_memory")
        if not global_m.startswith("#"):
            global_m = "## 全局记忆\n" + global_m

    # 作品上下文节选仍由 stage_write 用 project_to_context 追加；这里标记意图
    included.append("project_context")
    included.append("chapter_tail")
    included.append("ledger")

    return WriteContextBundle(
        system_extra="\n\n".join(system_parts).strip(),
        chat_block=chat_block,
        bible_block=bible_block,
        lens_block=lens_block,
        style_block=style_block,
        long_memory=long_m,
        global_memory=global_m,
        included=included,
    )


def messages_from_raw(raw: Any) -> List[Dict[str, str]]:
    """归一会话消息为 {role, content} 列表。"""
    out: List[Dict[str, str]] = []
    if not raw:
        return out
    for m in raw:
        if isinstance(m, dict):
            role = str(m.get("role") or "")
            content = str(m.get("content") or "")
        else:
            role = str(getattr(m, "role", "") or "")
            content = str(getattr(m, "content", "") or "")
        if role and content.strip():
            out.append({"role": role, "content": content.strip()})
    return out
