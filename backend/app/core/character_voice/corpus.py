"""Helpers for reading/writing character voice corpus on a project."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.core.project import uid
from app.domain.types import Character, VoiceCorpusLine, VoiceCorpusSample, VnProject


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_character(project: VnProject, character_id: str) -> Character:
    for c in project.characters or []:
        if c.id == character_id:
            return c
    raise KeyError(f"角色不存在：{character_id}")


def patch_character(
    project: VnProject,
    character_id: str,
    **updates: Any,
) -> VnProject:
    chars: List[Character] = []
    found = False
    for c in project.characters or []:
        if c.id != character_id:
            chars.append(c)
            continue
        found = True
        data = c.model_dump(mode="json")
        data.update(updates)
        chars.append(Character.model_validate(data))
    if not found:
        raise KeyError(f"角色不存在：{character_id}")
    return project.model_copy(update={"characters": chars})


def sample_count(c: Character) -> int:
    return len(c.voiceCorpus or [])


def scenario_coverage(c: Character) -> int:
    return len({(s.scenario or "").strip() for s in (c.voiceCorpus or []) if (s.scenario or "").strip()})


def make_sample(
    *,
    scenario: str,
    scenario_label: Optional[str],
    axis: Optional[str],
    hypothesis: Optional[str],
    lines: Sequence[Dict[str, str]] | Sequence[VoiceCorpusLine],
    source: str = "preference",
    user_note: Optional[str] = None,
    rejected_summary: Optional[str] = None,
) -> VoiceCorpusSample:
    parsed: List[VoiceCorpusLine] = []
    for row in lines:
        if isinstance(row, VoiceCorpusLine):
            parsed.append(row)
        else:
            parsed.append(
                VoiceCorpusLine(
                    speaker=str(row.get("speaker") or "self"),
                    text=str(row.get("text") or "").strip(),
                )
            )
    parsed = [x for x in parsed if x.text]
    return VoiceCorpusSample(
        id=uid("vsamp"),
        scenario=(scenario or "").strip(),
        scenarioLabel=scenario_label,
        axis=axis,
        hypothesis=hypothesis,
        lines=parsed,
        source=source,  # type: ignore[arg-type]
        userNote=user_note,
        rejectedSummary=rejected_summary,
        createdAt=_now(),
    )


def format_corpus_for_prompt(c: Character, *, max_samples: int = 8, max_chars: int = 2200) -> str:
    samples = list(c.voiceCorpus or [])[-max_samples:]
    if not samples:
        return ""
    parts: List[str] = ["  【口吻正例】（用户选中的证据，续写时对齐感觉，勿照抄）"]
    used = 0
    for s in samples:
        label = s.scenarioLabel or s.scenario or "场景"
        lines = " / ".join(
            (f"{ln.speaker}: {ln.text}" if ln.speaker not in ("self", c.displayName) else ln.text)
            for ln in (s.lines or [])
            if ln.text
        )
        bit = f"  · [{label}] {lines}"
        if s.hypothesis:
            bit += f"（假设：{s.hypothesis}）"
        if used + len(bit) > max_chars:
            break
        parts.append(bit)
        used += len(bit)
    notes = [n.strip() for n in (c.voiceRejectNotes or []) if n and str(n).strip()]
    if notes:
        parts.append("  【忌讳】" + "；".join(notes[-5:]))
    return "\n".join(parts)


def format_mind_for_prompt(c: Character, *, max_chars: int = 1800) -> str:
    md = (c.voiceMind or "").strip()
    if not md:
        return ""
    body = md if len(md) <= max_chars else md[: max_chars - 12] + "\n…(截断)"
    return f"  【角色思维包】\n{body}"


def corpus_char_volume(c: Character) -> int:
    total = 0
    names = {c.displayName, c.defineName, "self", ""}
    for s in c.voiceCorpus or []:
        for ln in s.lines or []:
            sp = (ln.speaker or "self").strip()
            if sp in names:
                total += len((ln.text or "").strip())
    return total


def corpus_stats(c: Character) -> Dict[str, Any]:
    samples = list(c.voiceCorpus or [])
    by_source: Dict[str, int] = {}
    for s in samples:
        key = str(s.source or "preference")
        by_source[key] = by_source.get(key, 0) + 1
    volume = corpus_char_volume(c)
    scene_n = by_source.get("scene", 0)
    interview_n = by_source.get("interview", 0)
    short_n = sum(
        1
        for s in samples
        if str(s.source or "preference")
        not in ("scene", "interview")
    )
    n = len(samples)
    cov = scenario_coverage(c)
    ready = (
        n >= 6
        or cov >= 5
        or volume >= 800
        or scene_n >= 2
        or (interview_n >= 4 and volume >= 400)
    )
    return {
        "sampleCount": n,
        "scenarioCoverage": cov,
        "volumeChars": volume,
        "shortCount": short_n,
        "sceneCount": scene_n,
        "interviewCount": interview_n,
        "bySource": by_source,
        "readyForMind": ready,
        "hasMindPack": bool((c.voiceMind or "").strip()),
    }
