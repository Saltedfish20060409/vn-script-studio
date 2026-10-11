"""声线指纹写时先验：把数值画像（口癖 / 句长中心）塞进生成，而不只写后 warn。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.domain.types import VnProject


def _focus_speaker_ids(project: VnProject, chapter_id: Optional[str]) -> List[str]:
    """焦点章近期出场角色（有 define 的优先）。"""
    cid = (chapter_id or "").strip()
    ch = next((c for c in (project.chapters or []) if str(c.id) == cid), None)
    names: List[str] = []
    if ch is not None:
        from app.core.agent_context import chapter_plain
        from app.core.chapter_digest import make_chapter_digest

        dig = make_chapter_digest(ch, project.characters)
        names = list(dig.speakers or [])
        if not names:
            plain = chapter_plain(ch, project.characters) or ""
            for c in project.characters or []:
                dn = c.displayName or ""
                if dn and dn in plain:
                    names.append(dn)
    # 回退：全员前 4
    ids: List[str] = []
    for c in project.characters or []:
        if (c.displayName in names) or (c.defineName in names) or (not names and len(ids) < 4):
            ids.append(str(c.id))
        if len(ids) >= 4:
            break
    return ids


def build_voice_write_priors(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    max_chars: int = 4,
) -> List[Dict[str, Any]]:
    from app.core.voice_fingerprint import build_voice_profile

    out: List[Dict[str, Any]] = []
    for cid in _focus_speaker_ids(project, chapter_id):
        try:
            profile = build_voice_profile(
                project, cid, exclude_chapters=[chapter_id] if chapter_id else None
            )
        except Exception:  # noqa: BLE001
            continue
        if not profile.get("ready"):
            continue
        agg = profile.get("aggregate") or {}
        phrases = list(profile.get("signaturePhrases") or [])[:3]
        out.append(
            {
                "characterId": cid,
                "displayName": profile.get("displayName") or cid,
                "avgSentenceLen": agg.get("sentenceLen"),
                "questionRate": agg.get("isQuestion"),
                "signaturePhrases": [
                    p.get("phrase") if isinstance(p, dict) else str(p) for p in phrases
                ],
                "sampleLines": list(profile.get("sampleLines") or [])[:2],
            }
        )
        if len(out) >= max_chars:
            break
    return out


def format_voice_write_prior_block(
    priors: List[Dict[str, Any]],
) -> str:
    if not priors:
        return ""
    lines = ["## 声线指纹先验（写时 · 偏离则改对白）"]
    for p in priors:
        name = p.get("displayName") or p.get("characterId")
        bits = [f"- {name}"]
        asl = p.get("avgSentenceLen")
        if isinstance(asl, (int, float)) and asl > 0:
            bits.append(f"  句长中心≈{asl:.1f}")
        qr = p.get("questionRate")
        if isinstance(qr, (int, float)) and qr > 0:
            bits.append(f"  疑问句比例≈{qr:.2f}")
        phrases = [x for x in (p.get("signaturePhrases") or []) if x]
        if phrases:
            bits.append("  口癖倾向：" + "、".join(str(x)[:12] for x in phrases[:3]))
        samples = [x for x in (p.get("sampleLines") or []) if x]
        if samples:
            bits.append("  短样例：" + " / ".join(str(x)[:40] for x in samples[:2]))
        lines.extend(bits)
    lines.append("- 规则：本场对白须贴近上述节奏与口癖；明显跑偏时优先改语气，勿整段换成说明腔。")
    return "\n".join(lines)
