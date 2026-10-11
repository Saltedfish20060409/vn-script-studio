"""子代理隔离：过程隔离、结论回传。

一致性 / 跨章核对任务在独立「窗口」里跑（受限上下文），只把结构化结论
并回主写路径；不把中间长文塞进主窗口。

默认：同进程隔离 + 本地小分类器（零成本）。
可选：``VNSS_LLM_SUBAGENT=1`` 时再走一轮窄上下文 LLM 复核（需模型 Key）。
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.domain.types import VnProject

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vnss-subagent")


@dataclass
class SubagentConclusion:
    task: str
    ok: bool
    contradictions: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    summary: str = ""
    #: 供策略闭环
    strengthen: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_meta(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "ok": self.ok,
            "contradictionCount": len(self.contradictions),
            "warnings": self.warnings[:6],
            "summary": self.summary[:400],
            "strengthen": self.strengthen,
            **(self.meta or {}),
        }

    def format_for_main(self) -> str:
        """主窗口只吃这段短结论。"""
        if self.ok and not self.contradictions and not self.warnings:
            return ""
        lines = ["## 子代理结论（过程已隔离，仅结论）"]
        lines.append(f"- 任务：{self.task}；状态：{'通过' if self.ok else '有问题'}")
        for c in self.contradictions[:6]:
            lines.append(
                f"- 矛盾：{c.get('code') or 'x'} — {c.get('message') or c}"
            )
        for w in self.warnings[:4]:
            lines.append(f"- 提醒：{w}")
        if self.summary:
            lines.append(f"- 摘要：{self.summary}")
        return "\n".join(lines)


def llm_subagent_enabled() -> bool:
    raw = (os.environ.get("VNSS_LLM_SUBAGENT") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _slice_project_for_consistency(
    project: VnProject,
    *,
    chapter_id: Optional[str],
    max_chapters: int = 8,
) -> VnProject:
    """给子代理的窄上下文：焦点章邻域 + 角色卡 + 账本，不含全量对话史。"""
    chapters = list(project.chapters or [])
    if not chapters:
        return project
    focus = (chapter_id or "").strip()
    idx = next((i for i, c in enumerate(chapters) if str(c.id) == focus), len(chapters) - 1)
    lo = max(0, idx - max_chapters // 2)
    hi = min(len(chapters), lo + max_chapters)
    lo = max(0, hi - max_chapters)
    sliced = project.model_copy(deep=True)
    sliced.chapters = chapters[lo:hi]
    return sliced


def _run_consistency_body(
    project: VnProject,
    *,
    chapter_id: Optional[str],
) -> SubagentConclusion:
    from app.core.scene_guard import guard_scene_draft
    from app.core.vn_classifiers import run_local_classifiers
    from app.core.write_precheck import precheck_before_continue

    narrow = _slice_project_for_consistency(project, chapter_id=chapter_id)
    contradictions: List[Dict[str, str]] = []
    warnings: List[str] = []
    classifier_meta: Dict[str, Any] = {"classifierHits": 0}

    # 本地小分类器（廉价预筛）
    try:
        from app.core.agent_context import chapter_plain

        ch0 = next((c for c in narrow.chapters if str(c.id) == (chapter_id or "")), None)
        plain0 = chapter_plain(ch0, narrow.characters) if ch0 else ""
        clf = run_local_classifiers(
            narrow, chapter_id=chapter_id, draft_text=plain0
        )
        classifier_meta["classifierHits"] = len(clf["errors"]) + len(clf["warnings"])
        for row in clf["errors"]:
            contradictions.append(row)
        for row in clf["warnings"]:
            warnings.append(str(row.get("message") or row))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"分类器子任务失败：{str(exc)[:80]}")

    # 写前对账（事实层）
    try:
        pre = precheck_before_continue(
            narrow, chapter_id=chapter_id, draft="", prose_audit=False
        )
        for iss in pre.issues or []:
            row = {
                "code": str(getattr(iss, "code", "") or "precheck"),
                "message": str(getattr(iss, "message", "") or iss),
                "severity": str(getattr(iss, "severity", "") or "warn"),
            }
            if row["severity"] == "error":
                contradictions.append(row)
            else:
                warnings.append(row["message"])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"对账子任务失败：{str(exc)[:80]}")

    # 焦点章正文当「已有草稿」再过一遍守卫（捕获死人说话等）
    try:
        from app.core.agent_context import chapter_plain

        ch = next((c for c in narrow.chapters if str(c.id) == (chapter_id or "")), None)
        plain = chapter_plain(ch, narrow.characters) if ch else ""
        if plain.strip():
            guard = guard_scene_draft(narrow, plain, chapter_id=chapter_id)
            for iss in guard.issues or []:
                if str(iss.get("severity") or "") == "error":
                    contradictions.append(
                        {
                            "code": str(iss.get("code") or "guard"),
                            "message": str(iss.get("message") or iss),
                            "severity": "error",
                        }
                    )
                else:
                    warnings.append(str(iss.get("message") or iss))
            warnings.extend(guard.warnings or [])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"守卫子任务失败：{str(exc)[:80]}")

    ok = len(contradictions) == 0
    summary = (
        "未发现硬矛盾"
        if ok
        else f"发现 {len(contradictions)} 条硬矛盾，请主写路径回避或改写"
    )
    return SubagentConclusion(
        task="consistency_isolation",
        ok=ok,
        contradictions=contradictions[:12],
        warnings=warnings[:8],
        summary=summary,
        strengthen=not ok or len(warnings) >= 3,
        meta={"mode": "local", **classifier_meta},
    )


def _llm_refine_conclusion(
    project: VnProject,
    *,
    chapter_id: Optional[str],
    base: SubagentConclusion,
) -> SubagentConclusion:
    """可选 LLM 复核：只看窄切片 + 本地结论，回传 JSON 补丁。失败则原样返回。"""
    try:
        from app.config import get_settings
        from app.core.agent_context import chapter_plain
        import httpx
    except Exception:
        return base

    settings = get_settings()
    api_key = (settings.deepseek_api_key or "").strip()
    base_url = (settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/")
    model = (settings.deepseek_model or "deepseek-v4-flash").strip()
    if not api_key:
        base.meta = {**(base.meta or {}), "llm": "skipped_no_key"}
        return base

    narrow = _slice_project_for_consistency(project, chapter_id=chapter_id, max_chapters=4)
    ch = next((c for c in narrow.chapters if str(c.id) == (chapter_id or "")), None)
    plain = (chapter_plain(ch, narrow.characters) if ch else "")[:1200]
    payload_user = {
        "chapterId": chapter_id,
        "localOk": base.ok,
        "contradictions": base.contradictions[:6],
        "warnings": base.warnings[:6],
        "chapterExcerpt": plain,
    }
    system = (
        "你是 VN 一致性子代理。只输出 JSON："
        '{"ok":bool,"contradictions":[{"code":str,"message":str}],'
        '"warnings":[str],"summary":str}。'
        "只报告硬事实矛盾；不要改写正文；不要解释过程。"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(payload_user, ensure_ascii=False),
            },
        ],
        "temperature": 0.0,
        "max_tokens": 400,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        )
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            base.meta = {**(base.meta or {}), "llm": "no_json"}
            return base
        parsed = json.loads(m.group(0))
    except Exception as exc:  # noqa: BLE001
        base.meta = {**(base.meta or {}), "llm": f"fail:{type(exc).__name__}"}
        return base

    cons = []
    for c in parsed.get("contradictions") or []:
        if isinstance(c, dict) and (c.get("message") or c.get("code")):
            cons.append(
                {
                    "code": str(c.get("code") or "llm"),
                    "message": str(c.get("message") or "")[:200],
                    "severity": "error",
                }
            )
    warns = [str(w)[:160] for w in (parsed.get("warnings") or []) if w][:6]
    # 合并：本地硬矛盾保留，LLM 追加
    merged = list(base.contradictions)
    seen = { (c.get("code"), c.get("message")) for c in merged }
    for c in cons:
        key = (c.get("code"), c.get("message"))
        if key not in seen:
            merged.append(c)
            seen.add(key)
    warn_merged = list(dict.fromkeys(list(base.warnings) + warns))[:8]
    ok = bool(parsed.get("ok", len(merged) == 0)) and len(merged) == 0
    return SubagentConclusion(
        task="consistency_isolation",
        ok=ok,
        contradictions=merged[:12],
        warnings=warn_merged,
        summary=str(parsed.get("summary") or base.summary)[:400],
        strengthen=not ok or len(warn_merged) >= 3,
        meta={**(base.meta or {}), "mode": "local+llm", "llm": "ok"},
    )


def run_consistency_subagent(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    timeout_s: float = 8.0,
    use_llm: Optional[bool] = None,
) -> SubagentConclusion:
    """在线程池隔离跑一致性子任务；超时则返回降级结论。"""
    fut = _POOL.submit(
        _run_consistency_body, project, chapter_id=chapter_id
    )
    try:
        base = fut.result(timeout=timeout_s)
    except FuturesTimeout:
        return SubagentConclusion(
            task="consistency_isolation",
            ok=True,
            warnings=["子代理超时，已跳过隔离一致性检查"],
            summary="timeout",
            strengthen=False,
            meta={"mode": "timeout"},
        )
    except Exception as exc:  # noqa: BLE001
        return SubagentConclusion(
            task="consistency_isolation",
            ok=True,
            warnings=[f"子代理异常：{str(exc)[:100]}"],
            summary="error",
            strengthen=False,
            meta={"mode": "error"},
        )

    want_llm = llm_subagent_enabled() if use_llm is None else bool(use_llm)
    if not want_llm:
        return base
    # LLM 复核单独限时，避免拖垮写路径
    fut2 = _POOL.submit(
        _llm_refine_conclusion, project, chapter_id=chapter_id, base=base
    )
    try:
        return fut2.result(timeout=max(8.0, float(timeout_s)))
    except Exception:  # noqa: BLE001
        base.meta = {**(base.meta or {}), "llm": "timeout_or_error"}
        return base
