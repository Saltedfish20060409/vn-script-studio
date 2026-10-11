"""策略抬档事件落盘（JSONL），供日后 bandit / 效果记账。

默认写到 ``backend/.vnss-logs/strategy_adapt/{project_id}.jsonl``。
失败静默：不挡写作主路径。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = _BACKEND_ROOT / ".vnss-logs" / "strategy_adapt"


def resolve_log_dir(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = (os.environ.get("VNSS_STRATEGY_ADAPT_LOG_DIR") or "").strip()
    if env:
        return Path(env)
    return DEFAULT_LOG_DIR


def log_mode() -> str:
    """``all``（默认）| ``changed`` | ``off``。环境变量 ``VNSS_STRATEGY_ADAPT_LOG``。"""
    raw = (os.environ.get("VNSS_STRATEGY_ADAPT_LOG") or "all").strip().lower()
    if raw in ("0", "false", "no", "off", "none"):
        return "off"
    if raw in ("changed", "delta", "bump"):
        return "changed"
    return "all"


def append_strategy_adapt_event(
    *,
    project_id: str,
    adapt: Mapping[str, Any],
    chapter_id: Optional[str] = None,
    write_op: Optional[str] = None,
    outcome: Optional[str] = None,
    log_dir: Optional[Path] = None,
) -> Optional[str]:
    """追加一条 JSONL；返回文件路径字符串，失败返回 None。

    ``outcome``：``accept`` / ``reject``（作者确认写入或放弃），供 bandit。
    """
    pid = (project_id or "").strip() or "_unknown"
    if not adapt and not outcome:
        return None
    mode = log_mode()
    if mode == "off":
        return None
    # 有采纳信号时始终记；否则按 all/changed 闸
    if not outcome:
        if mode == "changed" and not bool((adapt or {}).get("changed")):
            return None
    record: Dict[str, Any] = {
        "ts": time.time(),
        "projectId": pid,
        "chapterId": chapter_id,
        "writeOp": write_op,
        "changed": bool((adapt or {}).get("changed")),
        "suggestedAssist": (adapt or {}).get("suggestedAssist"),
        "attention": (adapt or {}).get("attention"),
        "memory": (adapt or {}).get("memory"),
        "reasoning": (adapt or {}).get("reasoning"),
        "reasons": list((adapt or {}).get("reasons") or []),
    }
    if outcome:
        record["outcome"] = str(outcome).strip().lower()[:16]
    try:
        root = resolve_log_dir(log_dir)
        root.mkdir(parents=True, exist_ok=True)
        # 文件名只留安全字符
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pid)[:80]
        path = root / f"{safe or '_unknown'}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return str(path)
    except OSError:
        return None


def read_recent_events(
    project_id: str,
    *,
    limit: int = 20,
    log_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """读最近若干条（测试 / 排障用）。"""
    pid = (project_id or "").strip() or "_unknown"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pid)[:80]
    path = resolve_log_dir(log_dir) / f"{safe or '_unknown'}.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max(1, int(limit)) :]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
