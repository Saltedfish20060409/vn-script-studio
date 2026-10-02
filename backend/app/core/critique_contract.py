"""P6：结构化审稿契约（ADR 0001）。

字段对齐 chapter_revise 诊断思路：issues 列表 + summary；
体裁 rubric 按 writingGenre 分流。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional

WritingGenre = Literal["vn", "novel"]

CRITIQUE_OUTPUT_CONTRACT = (
    "只输出 JSON（不要 markdown 围栏）："
    '{"summary":"一句总评","issues":[{"code":"短码","severity":"error|warn|info",'
    '"quote":"原文摘句可选","reason":"为何有问题","suggestion":"可执行改法可选"}]}。'
    "不要改写正文，不要 apply 工程。"
)

GENRE_CRITIQUE_RUBRIC: dict[str, List[str]] = {
    "vn": [
        "视觉小说：优先查对白是否可演、说明书旁白、假分支（多选项同结果）、钩子是否具体。",
        "少报文笔偏好；多报可上演性问题。",
    ],
    "novel": [
        "小说/轻小说：优先查章末钩子是否可回收、叙述是否空喊悬念、对白是否过稀或过密失衡。",
        "不要要求 Ren'Py menu/label。",
    ],
}


def critique_framing(genre: WritingGenre | str = "vn") -> str:
    g = genre if genre in ("vn", "novel") else "vn"
    lines = GENRE_CRITIQUE_RUBRIC.get(g, GENRE_CRITIQUE_RUBRIC["vn"])
    body = " ".join(lines)
    return (
        f"【本轮 capability=critique · 体裁={g}】只审稿不改稿。"
        f"{body} {CRITIQUE_OUTPUT_CONTRACT}\n"
    )


def parse_critique_payload(raw: str) -> Dict[str, Any]:
    """从模型输出中抽出 summary + issues；失败返回空 issues + 原文摘要。"""
    text = (raw or "").strip()
    if not text:
        return {"summary": "", "issues": []}
    # 尝试 JSON 对象
    try:
        from app.core.llm_text import extract_json_object

        data = extract_json_object(text)
    except Exception:
        data = None
    if not isinstance(data, dict):
        # 裸 JSON
        try:
            m = re.search(r"\{[\s\S]*\}", text)
            data = json.loads(m.group(0)) if m else None
        except Exception:
            data = None
    if not isinstance(data, dict):
        return {"summary": text[:200], "issues": []}
    issues_raw = data.get("issues") or []
    issues: List[Dict[str, Any]] = []
    if isinstance(issues_raw, list):
        for item in issues_raw[:40]:
            if isinstance(item, str) and item.strip():
                issues.append(
                    {
                        "code": "note",
                        "severity": "warn",
                        "reason": item.strip(),
                    }
                )
            elif isinstance(item, dict):
                reason = str(item.get("reason") or item.get("message") or "").strip()
                if not reason:
                    continue
                issues.append(
                    {
                        "code": str(item.get("code") or "issue")[:40],
                        "severity": str(item.get("severity") or "warn")[:16],
                        "quote": str(item.get("quote") or "")[:200] or None,
                        "reason": reason[:500],
                        "suggestion": (
                            str(item.get("suggestion") or "")[:400] or None
                        ),
                    }
                )
    summary = str(data.get("summary") or data.get("note") or "").strip()
    return {"summary": summary[:400], "issues": issues}
