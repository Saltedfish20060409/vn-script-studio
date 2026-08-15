"""Beat-sheet coverage checks — hard validation against draft text."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.core.harness.ai_flavor import HarnessIssue

_SPLIT = re.compile(r"[\s,，。！？、；;：:（）()\-\—「」『』\"“”]+")
_STOP = {
    "然后",
    "开始",
    "继续",
    "进行",
    "一个",
    "一些",
    "这个",
    "那个",
    "可以",
    "需要",
    "通过",
    "以及",
    "自己",
    "他们",
    "我们",
    "什么",
    "怎么",
    "如果",
    "因为",
    "所以",
    "就是",
    "还是",
    "已经",
    "正在",
    "动作",
    "场景",
    "角色",
    "描写",
    "对白",
    "展示",
    "表现",
    "完成",
    "进入",
    "离开",
    "the",
    "and",
    "with",
    "from",
    "that",
    "this",
    "into",
}


def _keywords(text: str, *, limit: int = 10) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    out: List[str] = []
    seen: Set[str] = set()
    for part in _SPLIT.split(raw):
        tok = part.strip()
        if len(tok) < 2:
            continue
        if tok.lower() in _STOP or tok in _STOP:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= limit:
            break
    return out


def _hit_any(draft: str, keys: List[str]) -> bool:
    if not keys:
        return True
    return any(k in draft for k in keys)


def lint_beat_sheet(
    draft: str, beat_sheet: Optional[Dict[str, Any]]
) -> List[HarnessIssue]:
    """
    Deterministic coverage of plan beats / goal / triggers.
    Missing individual beats → warn; majority miss → error.
    """
    issues: List[HarnessIssue] = []
    if not beat_sheet or not isinstance(beat_sheet, dict):
        return issues
    text = draft or ""
    if not text.strip():
        issues.append(
            HarnessIssue(
                "error",
                "beats_empty_draft",
                "有节拍表但正文为空，无法对照节拍",
                source="beats",
            )
        )
        return issues

    beats = beat_sheet.get("beats") or []
    if not isinstance(beats, list):
        beats = []

    covered = 0
    total = 0
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        name = str(beat.get("name") or "").strip()
        action = str(beat.get("action") or "").strip()
        label = name or action or f"节拍{i + 1}"
        keys = _keywords(f"{name} {action}")
        if not keys and not name and not action:
            continue
        total += 1
        # name alone counts if present
        ok = (name and name in text) or _hit_any(text, keys)
        if ok:
            covered += 1
        else:
            issues.append(
                HarnessIssue(
                    "warn",
                    "beat_missing",
                    f"节拍未在正文中体现：{label}"
                    + (f"（关键词：{'、'.join(keys[:4])}）" if keys else ""),
                    source="beats",
                )
            )

    if total >= 2 and covered * 2 < total:
        issues.append(
            HarnessIssue(
                "error",
                "beats_coverage",
                f"节拍覆盖不足：{covered}/{total} 条有对应痕迹，请改写以落实规划",
                source="beats",
            )
        )
    elif total >= 1 and covered == 0:
        issues.append(
            HarnessIssue(
                "error",
                "beats_coverage",
                "节拍表中的动作均未在正文出现痕迹",
                source="beats",
            )
        )

    goal = str(beat_sheet.get("goal") or "").strip()
    if goal:
        gkeys = _keywords(goal, limit=6)
        if gkeys and not _hit_any(text, gkeys) and goal not in text:
            issues.append(
                HarnessIssue(
                    "warn",
                    "beat_goal_weak",
                    f"正文弱相关于节拍目标「{goal[:40]}」",
                    source="beats",
                )
            )

    triggers = beat_sheet.get("triggers") or []
    if isinstance(triggers, list) and triggers:
        trig_keys: List[str] = []
        for t in triggers:
            trig_keys.extend(_keywords(str(t), limit=4))
        trig_keys = list(dict.fromkeys(trig_keys))[:12]
        if trig_keys and not _hit_any(text, trig_keys):
            issues.append(
                HarnessIssue(
                    "warn",
                    "beat_triggers_missing",
                    "节拍触发物/钩子未在正文出现："
                    + "、".join(str(t) for t in triggers[:4]),
                    source="beats",
                )
            )

    # emotionEnd characters should speak or be named if provided
    emotion_end = beat_sheet.get("emotionEnd") or {}
    if isinstance(emotion_end, dict):
        for who in list(emotion_end.keys())[:8]:
            name = str(who).strip()
            if len(name) >= 2 and name not in text:
                issues.append(
                    HarnessIssue(
                        "info",
                        "beat_cast_absent",
                        f"节拍情感收束涉及「{name}」，正文未出现该名",
                        source="beats",
                    )
                )

    return issues


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    import json

    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def lint_beat_sheet_semantic(
    config: Any,
    draft: str,
    beat_sheet: Optional[Dict[str, Any]],
) -> List[HarnessIssue]:
    """
    LLM semantic coverage of beats. Returns issues only for uncovered beats.
    keyword lint remains the cheap pre-pass; this corrects false positives/negatives
    when callers merge both.
    """
    import json

    from app.core.ai import DeepSeekConfig
    from app.core.llm_http import chat_completions, content_from_response

    if not beat_sheet or not isinstance(beat_sheet, dict):
        return []
    text = (draft or "").strip()
    if not text:
        return []
    beats = beat_sheet.get("beats") or []
    if not isinstance(beats, list) or not beats:
        return []

    if not isinstance(config, DeepSeekConfig):
        return []
    if not config.apiKey or "your-key" in config.apiKey:
        return []

    compact_beats = []
    for i, b in enumerate(beats[:10]):
        if not isinstance(b, dict):
            continue
        compact_beats.append(
            {
                "i": i,
                "name": str(b.get("name") or ""),
                "action": str(b.get("action") or ""),
            }
        )
    if not compact_beats:
        return []

    prompt = (
        "你是视觉小说责编。判断正文是否落实了节拍表中的每一条。"
        "语义落实即可（不必出现原词）。只输出 JSON：\n"
        '{"beats":[{"i":0,"covered":true,"note":"一句话依据"}],'
        '"goalCovered":true,"triggersCovered":true}\n\n'
        f"## 节拍\n{json.dumps({'goal': beat_sheet.get('goal'), 'beats': compact_beats, 'triggers': beat_sheet.get('triggers')}, ensure_ascii=False)}\n\n"
        f"## 正文\n{text[:6000]}"
    )
    try:
        res = await chat_completions(
            config,
            messages=[
                {
                    "role": "system",
                    "content": "只输出 JSON，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            timeout=60,
        )
        content, _ = content_from_response(res)
    except Exception as exc:  # noqa: BLE001
        return [
            HarnessIssue(
                "warn",
                "beat_semantic_unavailable",
                f"节拍语义校验失败：{exc}",
                source="beats",
            )
        ]

    parsed = _extract_json_obj(content)
    if not parsed:
        return [
            HarnessIssue(
                "warn",
                "beat_semantic_parse",
                "节拍语义校验返回无法解析，已回退关键词结果",
                source="beats",
            )
        ]

    issues: List[HarnessIssue] = []
    rows = parsed.get("beats") or []
    uncovered = 0
    total = 0
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            total += 1
            if row.get("covered") is True:
                continue
            uncovered += 1
            idx = int(row.get("i") or 0)
            label = ""
            if 0 <= idx < len(compact_beats):
                label = compact_beats[idx].get("name") or compact_beats[idx].get(
                    "action"
                )
            note = str(row.get("note") or "").strip()
            issues.append(
                HarnessIssue(
                    "warn",
                    "beat_semantic_missing",
                    f"语义未落实节拍：{label or f'#{idx}'}"
                    + (f"（{note}）" if note else ""),
                    source="beats",
                )
            )
    if total >= 2 and uncovered * 2 >= total:
        issues.append(
            HarnessIssue(
                "error",
                "beats_semantic_coverage",
                f"语义节拍覆盖不足：未落实 {uncovered}/{total}",
                source="beats",
            )
        )
    elif total >= 1 and uncovered == total:
        issues.append(
            HarnessIssue(
                "error",
                "beats_semantic_coverage",
                "语义上节拍均未落实",
                source="beats",
            )
        )

    if parsed.get("goalCovered") is False and beat_sheet.get("goal"):
        issues.append(
            HarnessIssue(
                "warn",
                "beat_goal_semantic",
                f"语义上未达成节拍目标「{str(beat_sheet.get('goal'))[:40]}」",
                source="beats",
            )
        )
    if parsed.get("triggersCovered") is False and beat_sheet.get("triggers"):
        issues.append(
            HarnessIssue(
                "warn",
                "beat_triggers_semantic",
                "语义上未出现节拍触发物/钩子",
                source="beats",
            )
        )
    return issues


async def resolve_beat_issues(
    draft: str,
    beat_sheet: Optional[Dict[str, Any]],
    *,
    config: Any = None,
    semantic: bool = True,
) -> List[HarnessIssue]:
    """
    Keyword pre-pass + optional LLM semantic pass.
    When semantic succeeds, replace keyword coverage codes with semantic results.
    """
    kw = lint_beat_sheet(draft, beat_sheet)
    if not semantic or config is None or not beat_sheet:
        return kw
    sem = await lint_beat_sheet_semantic(config, draft, beat_sheet)
    soft_fail = {
        "beat_semantic_unavailable",
        "beat_semantic_parse",
    }
    if any(i.code in soft_fail for i in sem):
        # keep keyword; attach at most one soft warning
        extra = [i for i in sem if i.code in soft_fail][:1]
        return kw + extra
    drop_codes = {
        "beat_missing",
        "beats_coverage",
        "beat_goal_weak",
        "beat_triggers_missing",
    }
    kept_kw = [i for i in kw if i.code not in drop_codes]
    return kept_kw + sem


def merge_beat_issues(audit: Dict[str, Any], beat_issues: List[HarnessIssue]) -> Dict[str, Any]:
    issues = list(audit.get("issues") or [])
    seen = {i.get("message") for i in issues if isinstance(i, dict)}
    for iss in beat_issues:
        if iss.message in seen:
            continue
        issues.append(
            {
                "severity": iss.severity,
                "code": iss.code,
                "message": iss.message,
                "source": iss.source,
            }
        )
        seen.add(iss.message)
    err = sum(1 for i in issues if i.get("severity") == "error")
    warn = sum(1 for i in issues if i.get("severity") == "warn")
    info = sum(1 for i in issues if i.get("severity") == "info")
    return {
        **audit,
        "issues": issues,
        "errorCount": err,
        "warnCount": warn,
        "infoCount": info,
        "pass": err == 0,
        "beatChecked": True,
    }
