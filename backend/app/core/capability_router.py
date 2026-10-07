"""Capability 路由表（ADR 0001 P4 / P5）。

深模块：只做「表 + 校验 + write write_op」，不含 FastAPI / SSE。
`/agent/turn` 根据这里的结果再选 handler。

P5：`write` 支持 continue / rewrite / polish / expand / condense / style_transfer。
critique / ingest / chat 必须在表中（薄委托由 API 层执行）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Literal, Optional

from app.core.critique_contract import critique_framing as _critique_framing
from app.core.pipeline.style_transfer_contract import style_transfer_prompt_block

Capability = Literal["write", "critique", "ingest", "chat"]
WriteOp = Literal[
    "continue",
    "rewrite",
    "polish",
    "expand",
    "condense",
    "style_transfer",
]

CAPABILITIES: FrozenSet[str] = frozenset({"write", "critique", "ingest", "chat"})

#: 历史命名：P4 首批；P5 起全部 write 均可用
P4_WRITE_OPS: FrozenSet[str] = frozenset({"continue", "rewrite"})

P5_WRITE_OPS: FrozenSet[str] = frozenset(
    {"polish", "expand", "condense", "style_transfer"}
)

ALL_WRITE_OPS: FrozenSet[str] = P4_WRITE_OPS | P5_WRITE_OPS

#: P5 拍板：缩写时优先保留的顺序（写入 framing，供回归断言）
CONDENSE_HOOK_PRIORITY = "未回收钩子 > 因果主干 > 细节描写"


@dataclass(frozen=True)
class WriteOpResolution:
    """write 能力下的 write_op 解析结果。"""

    write_op: str
    ok: bool = True
    error: Optional[str] = None


def resolve_write_op(
    write_op: Optional[str],
    *,
    selection: Optional[str] = None,
) -> WriteOpResolution:
    """解析 / 校验 write_op。

    - 显式 continue/rewrite/polish/expand/condense/style_transfer → 原样
    - 缺省：有非空 selection → rewrite，否则 continue
    - 未知字符串 → 失败
    """
    raw = (write_op or "").strip() or None
    if raw is None:
        sel = (selection or "").strip()
        return WriteOpResolution(write_op="rewrite" if sel else "continue")
    if raw in ALL_WRITE_OPS:
        return WriteOpResolution(write_op=raw)
    return WriteOpResolution(
        write_op=raw,
        ok=False,
        error=(
            f"未知 write_op={raw}；"
            f"可选：{', '.join(sorted(ALL_WRITE_OPS))}。"
        ),
    )


def assert_known_capability(capability: str) -> None:
    """未知 capability → ValueError（API 层转 400）。"""
    if capability not in CAPABILITIES:
        raise ValueError(
            f"未知 capability={capability}；"
            f"可选：{', '.join(sorted(CAPABILITIES))}。"
        )


def write_op_framing(write_op: str) -> str:
    """注入 writer user prompt 的 op 专用短帧。"""
    op = (write_op or "continue").strip() or "continue"
    if op == "rewrite":
        return (
            "【本轮 write_op=rewrite · 改写】在作者点名的范围内改写；"
            "未点名的情节、人名与因果不要无故改动。"
            "有选区时优先改选区；无选区则按指令改当前章相关段落。"
            "输出仍是自然语言剧本，不要引擎语法。\n"
        )
    if op == "polish":
        return (
            "【本轮 write_op=polish · 润色】只动语言层：句式更顺、画面感与口吻更稳；"
            "不改情节事实、因果、专名与角色关系。有选区则只润选区。"
            "输出润色后的自然语言剧本，不要引擎语法、不要解释。\n"
        )
    if op == "expand":
        return (
            "【本轮 write_op=expand · 扩写】在既有节拍上加感官、反应与过渡；"
            "不要新开主线、不要换结局、不要新增未铺垫的关键转折。"
            "输出扩写后的自然语言剧本，不要引擎语法。\n"
        )
    if op == "condense":
        return (
            "【本轮 write_op=condense · 缩写】压缩篇幅，但必须按优先级保留："
            f"{CONDENSE_HOOK_PRIORITY}。"
            "可牺牲过渡句、重复描写、氛围铺陈；不要删未回收钩子与因果主干。"
            "输出缩写后的自然语言剧本，不要引擎语法。\n"
        )
    if op == "style_transfer":
        return (
            "【本轮 write_op=style_transfer · 风格迁移】"
            + style_transfer_prompt_block()
            + "务必让句式节奏与对白口吻相对原文有可识别的差异幅度；"
            "禁止情节漂移。输出迁移后的自然语言剧本。\n"
        )
    return (
        "【本轮 write_op=continue · 续写】在章末（或指示位置）接着往下写；"
        "不要重写已有正文，除非作者明确要求。输出自然语言剧本。\n"
    )


def critique_framing(genre: str = "vn") -> str:
    """P6：注入审稿短帧（按 writingGenre）。"""
    return _critique_framing(genre)
