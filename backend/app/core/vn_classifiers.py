"""本地小分类器：死人出场 / 假选择风险 / 伏笔压力——不调模型。

挂在子代理或写后守卫前作廉价预筛；结论结构与 ``SubagentConclusion`` 兼容
（code/message/severity），便于合并。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.domain.types import VnProject


def classify_dead_character_in_text(
    project: VnProject,
    text: str,
) -> List[Dict[str, str]]:
    """正文是否提及账本中已标死亡的角色。"""
    from app.core.pipeline.ledger import get_ledger

    draft = (text or "").strip()
    if not draft:
        return []
    ledger = get_ledger(project)
    out: List[Dict[str, str]] = []
    for s in ledger.get("characterStates") or []:
        body = str(s.get("body") or "")
        name = str(s.get("characterName") or s.get("characterId") or "").strip()
        if not name:
            continue
        deadish = any(k in body for k in ("死", "亡", "身故", "已故", "阵亡"))
        if not deadish:
            continue
        if name in draft:
            out.append(
                {
                    "code": "dead_character_present",
                    "message": f"疑似死人出场：正文提到「{name}」（状态：{body[:40]}）",
                    "severity": "error",
                }
            )
    return out


def _choice_effect_sig(choice: Any) -> str:
    """后果签名：jump 目标 + set 变量（结构相同 ≈ 假选择）。"""
    if isinstance(choice, dict):
        jump = str(choice.get("jump") or choice.get("target") or "")
        sets = choice.get("set") or choice.get("effects") or []
    else:
        jump = str(getattr(choice, "jump", None) or getattr(choice, "target", None) or "")
        sets = getattr(choice, "set", None) or getattr(choice, "effects", None) or []
    bits = [f"jump:{jump}"]
    if isinstance(sets, list):
        for s in sets[:6]:
            if isinstance(s, dict):
                bits.append(
                    f"set:{s.get('key') or s.get('variable')}={s.get('value')}"
                )
            else:
                bits.append(str(s)[:40])
    return "|".join(bits)


def classify_fake_choice_risk(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    """焦点章 menu 是否像假选择（文案同质或后果签名相同）。"""
    out: List[Dict[str, str]] = []
    focus = (chapter_id or "").strip()
    for ch in project.chapters or []:
        if focus and str(ch.id) != focus:
            continue
        for block in getattr(ch, "blocks", None) or []:
            if isinstance(block, dict):
                btype = block.get("type")
                choices = list(block.get("choices") or [])
            else:
                btype = getattr(block, "type", None)
                choices = list(getattr(block, "choices", None) or [])
            if btype != "menu":
                continue
            texts = []
            for c in choices:
                if isinstance(c, dict):
                    texts.append(str(c.get("text") or c.get("label") or "").strip())
                else:
                    texts.append(
                        str(
                            getattr(c, "text", None)
                            or getattr(c, "label", None)
                            or ""
                        ).strip()
                    )
            texts = [t for t in texts if t]
            if len(texts) < 2:
                continue
            # 后果签名完全相同
            sigs = [_choice_effect_sig(c) for c in choices]
            if len(sigs) >= 2 and len(set(sigs)) == 1 and sigs[0] not in ("jump:",):
                out.append(
                    {
                        "code": "fake_choice_same_effect",
                        "message": f"章 {ch.id} 选项后果签名相同（假选择风险）",
                        "severity": "warn",
                    }
                )
            # 同质：都以「同意/好的/明白」类起头，或两两编辑距离极近（字重叠）
            agreeish = sum(
                1
                for t in texts
                if t.startswith(("好", "是", "同意", "明白", "当然", "嗯"))
            )
            if agreeish >= len(texts) and len(texts) >= 2:
                out.append(
                    {
                        "code": "fake_choice_risk",
                        "message": f"章 {ch.id} 菜单选项文案过于同质（假选择风险）",
                        "severity": "warn",
                    }
                )
                continue
            # 字符集合 Jaccard 过高
            pairs = 0
            hot = 0
            for i in range(len(texts)):
                for j in range(i + 1, len(texts)):
                    a, b = set(texts[i]), set(texts[j])
                    if not a or not b:
                        continue
                    pairs += 1
                    if len(a & b) / len(a | b) >= 0.85:
                        hot += 1
            if pairs and hot / pairs >= 0.5:
                out.append(
                    {
                        "code": "fake_choice_risk",
                        "message": f"章 {ch.id} 选项两两过于相似（假选择风险）",
                        "severity": "warn",
                    }
                )
        if focus:
            break
    return out


def classify_foreshadow_pressure(project: VnProject) -> List[Dict[str, str]]:
    """未回收且章龄偏高的伏笔 → 写时压力提醒；联动结局完备性。"""
    from app.core.pipeline.ledger import _foreshadow_rows, get_ledger

    ledger = get_ledger(project)
    rows = _foreshadow_rows(ledger, project.chapters)
    out: List[Dict[str, str]] = []
    for r in rows:
        if str(r.get("status") or "open") == "paid":
            continue
        age = r.get("ageChapters")
        if not isinstance(age, int) or age < 5:
            continue
        hook = str(r.get("hook") or r.get("id") or "")
        out.append(
            {
                "code": "foreshadow_pressure",
                "message": f"高压伏笔「{hook}」已埋 {age} 章未回收",
                "severity": "warn",
            }
        )
    # 与结局路径完备性联动：不完备时加一条总提醒
    try:
        from app.core.foreshadow_endings import check_foreshadow_ending_completeness

        report = check_foreshadow_ending_completeness(project)
        rate = float(report.completeness_rate if report.completeness_rate is not None else 1.0)
        if rate < 0.85 and int(report.open_incomplete or 0) > 0:
            out.append(
                {
                    "code": "foreshadow_ending_gap",
                    "message": (
                        f"伏笔结局路径完备率偏低（{rate:.0%}）："
                        "部分钩子可能在结局前无法回收，写时请预留收束场"
                    ),
                    "severity": "warn",
                }
            )
    except Exception:  # noqa: BLE001
        pass
    return out[:8]


def run_local_classifiers(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    draft_text: str = "",
) -> Dict[str, Any]:
    """跑全套本地分类器，返回可合并进子代理的结构。"""
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    for row in classify_dead_character_in_text(project, draft_text):
        (errors if row.get("severity") == "error" else warnings).append(row)
    for row in classify_fake_choice_risk(project, chapter_id=chapter_id):
        (errors if row.get("severity") == "error" else warnings).append(row)
    for row in classify_foreshadow_pressure(project):
        warnings.append(row)
    return {
        "errors": errors,
        "warnings": warnings,
        "ok": len(errors) == 0,
    }
