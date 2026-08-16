"""Helpers for reading/writing character voice corpus on a project."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.project import uid
from app.domain.types import Character, VnProject, VoiceCorpusLine, VoiceCorpusSample

# Higher = prefer when building generation context
SOURCE_WEIGHT: Dict[str, float] = {
    "manual": 1.0,
    "script_extract": 0.95,
    "scene": 0.72,
    "chat": 0.68,
    "interview": 0.55,
    "preference": 0.5,
    "import": 0.4,
}

_SOURCE_LABEL: Dict[str, str] = {
    "manual": "金句",
    "script_extract": "剧本",
    "scene": "长场次",
    "chat": "对话",
    "interview": "采访",
    "preference": "三选一",
    "import": "导入",
}


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


_GENERIC_CUSTOM_LABELS = {"", "自定义", "自定义…", "custom", "长场次·自定义"}


def _prompt_slug(prompt: str, *, max_len: int = 16) -> str:
    text = " ".join((prompt or "").split()).strip()
    if not text:
        return ""
    return text[:max_len]


def normalize_scenario_key(
    scenario: str = "",
    scenario_label: Optional[str] = None,
    *,
    prompt: str = "",
) -> str:
    """Stable coverage key. Custom scenes become custom:<name> so they count separately."""
    sid = (scenario or "").strip()
    label = (scenario_label or "").strip()
    # strip long-scene prefix for display labels like 长场次·雨夜
    if label.startswith("长场次·"):
        label = label[len("长场次·") :].strip() or label

    if sid.startswith("custom:"):
        name = sid.split(":", 1)[1].strip()
        if not name or name in _GENERIC_CUSTOM_LABELS:
            name = label if label not in _GENERIC_CUSTOM_LABELS else ""
            name = name or _prompt_slug(prompt) or "未命名"
        return f"custom:{name}"

    if sid == "custom":
        name = label if label not in _GENERIC_CUSTOM_LABELS else ""
        name = name or _prompt_slug(prompt) or "未命名"
        return f"custom:{name}"

    if sid:
        return sid
    if label and label not in _GENERIC_CUSTOM_LABELS:
        return label
    slug = _prompt_slug(prompt)
    return slug


def scenario_coverage(c: Character) -> int:
    keys = {
        normalize_scenario_key(s.scenario or "", s.scenarioLabel)
        for s in (c.voiceCorpus or [])
    }
    return len({k for k in keys if k})


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
    scenario_prompt: str = "",
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
    key = normalize_scenario_key(
        scenario, scenario_label, prompt=scenario_prompt
    )
    label_out = (scenario_label or "").strip() or None
    if key.startswith("custom:") and (not label_out or label_out in _GENERIC_CUSTOM_LABELS):
        label_out = key.split(":", 1)[1]
    return VoiceCorpusSample(
        id=uid("vsamp"),
        scenario=key or (scenario or "").strip(),
        scenarioLabel=label_out,
        axis=axis,
        hypothesis=hypothesis,
        lines=parsed,
        source=source,  # type: ignore[arg-type]
        userNote=user_note,
        rejectedSummary=rejected_summary,
        createdAt=_now(),
    )


def confirmed_axes(c: Character, *, limit: int = 8) -> List[str]:
    """Direction labels already accepted — used to converge later rounds."""
    labels: List[str] = []
    seen: set[str] = set()
    for s in reversed(list(c.voiceCorpus or [])):
        ax = (s.axis or "").strip()
        if not ax or ax in seen:
            continue
        seen.add(ax)
        labels.append(ax)
        if len(labels) >= limit:
            break
    labels.reverse()
    return labels


def append_prefer_note(c: Character, note: str, *, limit: int = 12) -> List[str]:
    """Deduped prefer notes; newest last, keep tail."""
    notes = [n.strip() for n in (c.voicePreferNotes or []) if n and str(n).strip()]
    bit = (note or "").strip()
    if not bit:
        return notes
    notes = [n for n in notes if n != bit]
    notes.append(bit)
    return notes[-limit:]


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}")


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def score_corpus_sample(
    s: VoiceCorpusSample,
    *,
    scenario_id: str = "",
    scenario_label: str = "",
    scenario_prompt: str = "",
    index: int = 0,
    total: int = 1,
) -> float:
    """Higher = more useful for the current generation context."""
    src = str(s.source or "preference")
    score = SOURCE_WEIGHT.get(src, 0.45) * 10.0

    target_key = normalize_scenario_key(
        scenario_id, scenario_label or None, prompt=scenario_prompt
    )
    sample_key = normalize_scenario_key(s.scenario or "", s.scenarioLabel)
    if target_key and sample_key and target_key == sample_key:
        score += 8.0
    elif target_key and sample_key:
        if target_key.split(":", 1)[0] == sample_key.split(":", 1)[0] and "custom" in target_key:
            score += 2.0

    hay = " ".join(
        [
            s.scenario or "",
            s.scenarioLabel or "",
            s.axis or "",
            s.hypothesis or "",
            s.userNote or "",
            " ".join(ln.text for ln in (s.lines or []) if ln.text),
        ]
    )
    q = " ".join([scenario_label, scenario_prompt, scenario_id])
    overlap = _tokens(hay) & _tokens(q)
    score += min(6.0, 1.2 * len(overlap))

    # Mild recency: later samples slightly preferred (not dominant)
    if total > 1:
        score += 1.5 * (index / (total - 1))
    return score


def rank_corpus_samples(
    c: Character,
    *,
    scenario_id: str = "",
    scenario_label: str = "",
    scenario_prompt: str = "",
) -> List[VoiceCorpusSample]:
    samples = list(c.voiceCorpus or [])
    n = len(samples)
    ranked: List[Tuple[float, int, VoiceCorpusSample]] = []
    for i, s in enumerate(samples):
        sc = score_corpus_sample(
            s,
            scenario_id=scenario_id,
            scenario_label=scenario_label,
            scenario_prompt=scenario_prompt,
            index=i,
            total=max(1, n),
        )
        ranked.append((sc, i, s))
    ranked.sort(key=lambda t: (-t[0], -t[1]))
    return [t[2] for t in ranked]


def select_corpus_for_prompt(
    c: Character,
    *,
    scenario_id: str = "",
    scenario_label: str = "",
    scenario_prompt: str = "",
    max_samples: int = 8,
    max_chars: int = 2200,
) -> str:
    """Ranked positive examples + prefer/reject notes for LLM context."""
    samples = rank_corpus_samples(
        c,
        scenario_id=scenario_id,
        scenario_label=scenario_label,
        scenario_prompt=scenario_prompt,
    )
    if not samples and not (c.voicePreferNotes or []) and not (c.voiceRejectNotes or []):
        return ""

    parts: List[str] = []
    dirs = confirmed_axes(c, limit=6)
    if samples:
        parts.append("  【口吻正例】（按场景相关与来源权重挑选；对齐感觉，勿照抄）")
    if dirs:
        parts.append("  【已确认方向】" + "、".join(dirs))

    used = sum(len(p) for p in parts)
    taken = 0
    for s in samples:
        if taken >= max_samples:
            break
        label = s.scenarioLabel or s.scenario or "场景"
        src_tag = _SOURCE_LABEL.get(str(s.source or "preference"), "正例")
        lines = " / ".join(
            (f"{ln.speaker}: {ln.text}" if ln.speaker not in ("self", c.displayName) else ln.text)
            for ln in (s.lines or [])
            if ln.text
        )
        bit = f"  · [{label}|{src_tag}]"
        if s.axis:
            bit += f"〈方向：{s.axis}〉"
        bit += f" {lines}"
        if s.hypothesis:
            bit += f"（假设：{s.hypothesis}）"
        if s.userNote:
            bit += f"（偏好：{s.userNote}）"
        if used + len(bit) > max_chars:
            break
        parts.append(bit)
        used += len(bit)
        taken += 1

    prefers = [n.strip() for n in (c.voicePreferNotes or []) if n and str(n).strip()]
    if prefers:
        bit = "  【偏好】" + "；".join(prefers[-6:])
        if used + len(bit) <= max_chars + 200:
            parts.append(bit)
            used += len(bit)

    notes = [n.strip() for n in (c.voiceRejectNotes or []) if n and str(n).strip()]
    if notes:
        bit = "  【忌讳】" + "；".join(notes[-5:])
        if used + len(bit) <= max_chars + 400:
            parts.append(bit)

    return "\n".join(parts) if parts else ""


def format_corpus_for_prompt(
    c: Character,
    *,
    max_samples: int = 8,
    max_chars: int = 2200,
    scenario_id: str = "",
    scenario_label: str = "",
    scenario_prompt: str = "",
) -> str:
    return select_corpus_for_prompt(
        c,
        scenario_id=scenario_id,
        scenario_label=scenario_label,
        scenario_prompt=scenario_prompt,
        max_samples=max_samples,
        max_chars=max_chars,
    )


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
        "confirmedAxes": confirmed_axes(c),
        "preferNoteCount": len(c.voicePreferNotes or []),
    }
